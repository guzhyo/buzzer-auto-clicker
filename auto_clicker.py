"""
抢答器定时点击器（图形界面版）
=================================
功能：按每个坐标自己设定的间隔时间，自动依次点击坐标：
    1) 第一次点击：抢答按钮（该按钮本身带 3 秒延时抢答）
    2) 第二次点击：复位按钮

用法：
    python auto_clicker.py                  # 打开图形界面
    python auto_clicker.py --interval 5     # 指定新增坐标的默认间隔（秒）
    python auto_clicker.py --duration 30    # 指定自动点击总时长（分钟，0=不限时）
    python auto_clicker.py --cli            # 无界面命令行模式
    python auto_clicker.py --cli --points "1570,130d@5;1720,130@10"  # d=双击，@后为间隔秒
    python build_exe.py                     # 打包成单个 exe

说明：每个坐标都可以单独设置「间隔秒数」和「单击 / 双击」（界面坐标行内），
     间隔指「点完这个坐标后等多久点下一个」；新增坐标时默认是「单击」，
     一轮的最后一步到下一轮第一步之间至少停 LOOP_GAP(=1) 秒。
"""

import time
import os
import sys
import threading
import argparse

try:
    import ctypes  # 用于检测全局热键（Windows）
    HAS_CTYPES = True
except Exception:
    HAS_CTYPES = False


# 打包成无控制台的 exe（--windowed）时 stdout/stderr 为 None，
# 这里补上空实现，避免 print() 抛异常（也就不会出现黑色控制台窗口）
class _NullStream:
    def write(self, *_args):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

# tkinter 延迟导入：仅在进入 GUI 模式时才 import，
# 避免无显示环境 / 精简 Python 下因缺少 tkinter 导致整个模块无法加载
try:
    import tkinter as tk  # noqa: F401
    from tkinter import ttk, messagebox  # noqa: F401
    HAS_TK = True
except Exception:
    HAS_TK = False


def _load_tk():
    """进入 GUI 模式时真正导入 tkinter（含控件）。"""
    import tkinter as tk_mod
    from tkinter import ttk as ttk_mod, messagebox as mb_mod
    return tk_mod, ttk_mod, mb_mod


# pyautogui 涉及屏幕操作，延迟导入（--dry-run / 无 GUI 环境也可运行）
try:
    import pyautogui
    # 关闭「鼠标移到屏幕角落即中止」的 fail-safe：
    # 自动点击会主动移动鼠标，容易误触；改为使用全局热键 Ctrl+Q 紧急停止。
    pyautogui.FAILSAFE = False
    # 默认 PAUSE=0.1，会在每次鼠标动作后额外多停 0.1 秒，导致「点完后等待的
    # 秒数」比设定值偏大；这里调小到几乎不占时间，保证间隔就是设定的时间。
    pyautogui.PAUSE = 0.02
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

# ================= 资源路径 =================
def resource_path(name):
    """获取资源文件的绝对路径（兼容源码运行与 PyInstaller 单文件打包）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# ================= 紧急停止热键 =================
VK_CONTROL = 0x11   # Ctrl
VK_Q       = 0x51   # Q
HOTKEY_TEXT = "Ctrl+Q"   # 界面提示用的文本

# 双击模式下两次点击之间的间隔（秒）
DOUBLE_CLICK_INTERVAL = 0.1

# 等待时间的检查粒度（秒）：越小，实际等待越接近设定值
SLEEP_TICK = 0.02

# 一轮循环的最后一步到下一轮第一步之间的等待时间（秒，最后一行间隔不小于它）
LOOP_GAP = 1.0

# 新增坐标行时的默认间隔时间（秒）
DEFAULT_INTERVAL = 10.0

# 默认的三行坐标（名称, 抢答器上的按钮关键字, 该行默认间隔秒；None = 用 DEFAULT_INTERVAL）
DEFAULT_STEPS = (("3秒延时抢答", "抢答", 10.0),   # 第 1 个坐标：10 秒
                 ("复位", "复位", 1.0),           # 第 2 个坐标：1 秒
                 ("3秒延时抢答", "抢答", 1.0))     # 第 3 个坐标：1 秒


def step_interval(interval, fallback):
    """默认行的间隔：None 时回退到全局默认间隔。"""
    return fallback if interval is None else interval

# 每个坐标可单独选择点击方式（坐标行里保存的就是这两个文本，默认第一项「单击」）
CLICK_SINGLE = "单击"
CLICK_DOUBLE = "双击"
CLICK_MODES = (CLICK_SINGLE, CLICK_DOUBLE)

# 坐标列表：单行高度（像素）与不出现滚动条时最多显示的行数
COORD_ROW_H = 36
COORD_VISIBLE_ROWS = 5
MAX_COORD_ROWS = 20        # 坐标数量上限，防止误点


def hotkey_stop_pressed():
    """检测是否按下了 Ctrl+Q（Windows 全局检测，窗口失焦同样有效）。"""
    if not HAS_CTYPES or os.name != "nt":
        return False
    try:
        u = ctypes.windll.user32
        ctrl = u.GetAsyncKeyState(VK_CONTROL) & 0x8000
        q    = u.GetAsyncKeyState(VK_Q) & 0x8000
        return bool(ctrl) and bool(q)
    except Exception:
        return False
# ================================================


class RunState:
    """运行状态：界面里的每个参数在「开始」时都会被快照到这里再做校验。

    某个字段一旦填错，界面会把对应的输入框/下拉框标红并弹窗提示，
    避免出现「界面看着改了、实际没生效」的情况。
    """

    __slots__ = ("names", "points", "doubles", "intervals", "duration")

    def __init__(self, names, points, doubles, intervals, duration):
        self.names = names
        self.points = points
        self.doubles = doubles
        self.intervals = intervals      # 每个坐标点完之后的间隔（秒），与 points 一一对应
        self.duration = duration        # 自动点击总时长（分钟，0 = 不限时）

    def as_points(self):
        """转成循环用的 [(名称, (x, y), 是否双击, 间隔秒), ...]。"""
        return [(n, p, d, iv) for n, p, d, iv
                in zip(self.names, self.points, self.doubles, self.intervals)]

    @property
    def mode_text(self):
        n = sum(1 for d in self.doubles if d)
        if not n:
            return "全部单击"
        if n == len(self.doubles):
            return "全部双击"
        return f"{n} 个双击"

    @property
    def interval_text(self):
        iv = list(self.intervals)
        return f"{iv[0]:g}" if len(set(iv)) == 1 else f"{min(iv):g}~{max(iv):g}"

    def interval_text_at(self, index):
        """状态栏用的等待文本：轮末按实际等待（不少于 LOOP_GAP 秒）。"""
        wait = self.intervals[index]
        if index == len(self.points) - 1:
            wait = max(wait, LOOP_GAP)
        return f"{wait:g}"

    def mode_text_at(self, index):
        return CLICK_DOUBLE if self.doubles[index] else CLICK_SINGLE

    def describe(self):
        """开始时的状态栏文本。"""
        dur = "不限时" if self.duration <= 0 else f"{self.duration:g} 分钟"
        return (f"运行中 · {self.mode_text} · 间隔 {self.interval_text} 秒"
                f"（轮末 ≥{LOOP_GAP:g} 秒）· 总时长 {dur} · "
                f"{len(self.points)} 个坐标 · {HOTKEY_TEXT} 紧急停止")

    def describe_point(self, index, remain=""):
        """点完某个坐标后的状态栏文本（带上该坐标自己的间隔）。"""
        dbl = CLICK_DOUBLE if self.doubles[index] else CLICK_SINGLE
        waiting = "轮末等待" if index == len(self.points) - 1 else "等待"
        return (f"已{dbl}「{self.names[index]}」"
                f"（第 {index + 1}/{len(self.points)} 步）@ "
                f"{time.strftime('%H:%M:%S')}{remain} · "
                f"{waiting} {self.interval_text_at(index)} 秒")


# ================= 界面主题 =================
BG        = "#eef1f6"   # 窗口背景
CARD      = "#ffffff"   # 卡片背景
FIELD     = "#f5f7fa"   # 输入框背景
BORDER    = "#e2e6ee"   # 边框
TEXT      = "#25324a"   # 主要文字
MUTED     = "#8b95a7"   # 次要文字
ACCENT    = "#2f7cf6"   # 主色
GREEN     = "#20b26c"   # 运行/开始
GREEN_HL  = "#199a5c"
RED       = "#ef5350"   # 停止
RED_HL    = "#d84340"
DISABLED  = "#c9cfda"   # 禁用态

# 坐标拾取遮罩：整块窗口半透明，既能看到屏幕内容，又能吃掉鼠标点击
MASK_BG    = "#0b1220"
MASK_ALPHA = 0.45

FONT      = ("Microsoft YaHei UI", 10)
FONT_BTN  = ("Microsoft YaHei UI", 11, "bold")
FONT_SM   = ("Microsoft YaHei UI", 9)
FONT_H1   = ("Microsoft YaHei UI", 16, "bold")
FONT_DOT  = ("Microsoft YaHei UI", 13)
# ============================================


# ============ 默认坐标（可在界面里修改） ============
# 把 get_pos.py 测到的真实坐标填到这里，或直接在界面里点「拾取」。
DEFAULT_POSITIONS = {
    "抢答": (1570, 130),   # 第一次点击：3 秒延时抢答
    "复位": (1720, 130),   # 第二次点击：复位
}
# ==================================================


def locate_buttons():
    """若有按钮截图，则自动图像识别；否则用默认坐标。"""
    positions = dict(DEFAULT_POSITIONS)
    if not HAS_PYAUTOGUI:
        return positions
    try:
        for name, img in {"抢答": "btn_qiangda.png", "复位": "btn_fuwei.png"}.items():
            if os.path.isfile(img):
                loc = pyautogui.locateOnScreen(img, confidence=0.8)
                if loc:
                    positions[name] = pyautogui.center(loc)
    except Exception:
        pass
    return positions


class App:
    def __init__(self, root, interval=10.0, duration=30.0):
        self.root = root
        self.running = False
        self.thread = None
        self.default_points = locate_buttons()   # {"抢答": (x, y), "复位": (x, y)}
        self.rows = []             # 坐标行列表，数量可自定义
        self._picking = False      # 遮罩拾取器是否激活
        self._overlay = None       # 全屏遮罩窗口
        self._overlay_index = None  # 当前正在拾取的坐标行下标
        self._deadline = None      # 自动点击的截止时间戳（None=不限时）
        self._state = None         # 当前生效的运行参数快照（RunState）
        self._win_pos = None       # 窗口左上角位置，增删坐标行时保持不动
        self._restore_job = None   # 恢复窗口时的「临时置顶」定时器
        self._minimize_job = None  # 开始运行时「最小化到任务栏」的定时器
        _tk, _ttk, messagebox = _load_tk()  # 延迟加载 tkinter 控件
        self._ttk = _ttk                   # 每个坐标的点击方式下拉框使用
        self._messagebox = messagebox

        # 先隐藏窗口：等所有控件布局完成、尺寸算好并居中后，
        # 再一次性显示，避免出现「默认尺寸 -> 调整尺寸/移动」的闪烁。
        try:
            self.root.withdraw()
        except Exception:
            pass

        self._setup_window()
        self._build_ui(interval, duration)
        self._show_window()

    # ---------------- 窗口 ----------------
    def _setup_window(self):
        self.root.title("抢答器定时点击器【GUZYO】")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        # 窗口 / 任务栏图标（app.ico 与程序放在同一目录）
        try:
            ico = resource_path("app.ico")
            if os.path.isfile(ico):
                self.root.iconbitmap(default=ico)
        except Exception:
            pass
        # 界面聚焦时按下 Ctrl+Q 也能立即紧急停止
        self.root.bind_all("<Control-q>", lambda e: self.emergency_stop())
        self.root.bind_all("<Control-Q>", lambda e: self.emergency_stop())

    def _autosize(self, keep_pos=False):
        """按内容自适应窗口大小并居中（保持紧凑）。

        keep_pos=True 时保持窗口当前位置，只调整高度（增删坐标行时用），
        避免窗口在屏幕上跳来跳去。
        """
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 430)
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if keep_pos and self._win_pos:
            x, y = self._win_pos
            x = min(max(x, 0), max(sw - w, 0))
            y = min(y, max(sh - h - 40, 0))
        else:
            # 启动时窗口在屏幕上水平、垂直都居中
            x, y = max((sw - w) // 2, 0), max((sh - h) // 2, 0)
        self._win_pos = (x, y)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _show_window(self):
        """布局完成后一次性显示窗口（窗口居中，避免启动时闪烁 / 尺寸跳变）。"""
        self.root.update_idletasks()
        if self._win_pos:
            # 显示前再确认一次位置，保证启动即屏幕居中
            w = max(self.root.winfo_reqwidth(), 430)
            h = self.root.winfo_reqheight()
            x, y = self._win_pos
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass

    # ---------------- 组件工具 ----------------
    def _card(self, parent, pady=(0, 8)):
        """白底卡片容器，返回内部可放置内容的 Frame。"""
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", pady=pady)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=12, pady=10)
        return inner

    def _section_title(self, parent, text, row):
        tk.Label(parent, text=text, bg=CARD, fg=MUTED, font=FONT_SM).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))

    def _make_button(self, parent, text, command, bg, hover, font=FONT_BTN):
        btn = tk.Button(parent, text=text, command=command,
                        bg=bg, fg="#ffffff", activebackground=hover,
                        activeforeground="#ffffff", disabledforeground="#ffffff",
                        relief="flat", bd=0, cursor="hand2", font=font,
                        highlightthickness=0, takefocus=0)
        btn._bg, btn._hover = bg, hover
        btn.bind("<Enter>", lambda e: btn.config(bg=btn._hover)
                 if str(btn["state"]) == "normal" else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=btn._bg)
                 if str(btn["state"]) == "normal" else None)
        return btn

    def _make_ghost_button(self, parent, text, command, fg=ACCENT):
        """浅底描边按钮（用于次要操作）。"""
        btn = tk.Button(parent, text=text, command=command, font=FONT_SM,
                        bg=FIELD, fg=fg, activebackground="#e8f0fe",
                        activeforeground=fg, disabledforeground=MUTED,
                        relief="flat", bd=0, cursor="hand2",
                        highlightthickness=1, highlightbackground=BORDER,
                        padx=10, pady=3, takefocus=0)
        btn._bg, btn._hover = FIELD, "#e8f0fe"
        btn.bind("<Enter>", lambda e: btn.config(bg=btn._hover)
                 if str(btn["state"]) == "normal" else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=btn._bg)
                 if str(btn["state"]) == "normal" else None)
        return btn

    def _enable_button(self, btn, enabled):
        if enabled:
            btn.config(state="normal", bg=btn._bg, cursor="hand2")
        else:
            btn.config(state="disabled", bg=DISABLED, cursor="arrow")

    def _make_entry(self, parent, textvariable, width=None):
        entry = tk.Entry(parent, textvariable=textvariable, font=FONT,
                         bg=FIELD, fg=TEXT, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT, insertbackground=TEXT,
                         justify="center")
        if width:
            entry.config(width=width)
        return entry


    # ---------------- 界面 ----------------
    def _build_ui(self, interval, duration):
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=14, pady=12)

        # 标题
        hdr = tk.Frame(main, bg=BG)
        hdr.pack(fill="x", pady=(0, 10))
        tk.Label(hdr, text="抢答器定时点击器", bg=BG, fg=TEXT,
                 font=FONT_H1).pack(anchor="w")
        tk.Label(hdr, text="按每个坐标自己的间隔依次自动点击（默认：抢答 → 复位）",
                 bg=BG, fg=MUTED, font=FONT_SM).pack(anchor="w", pady=(2, 0))

        # 卡片 1：参数设置（自动点击总时长）
        self.default_interval = float(interval)   # 新增坐标行的默认间隔（秒）
        self.default_duration = float(duration)   # 默认总时长（分钟），重置时使用
        f1 = self._card(main)
        self._section_title(f1, "参数设置（总时长填 0 表示不限时）", 0)
        f1.columnconfigure(0, weight=1)
        tk.Label(f1, text="自动点击总时长（分钟，填 0 = 不限时、一直循环）",
                 bg=CARD, fg=TEXT, font=FONT_SM).grid(row=1, column=0, sticky="w")
        self.duration_var = tk.DoubleVar(value=duration)
        self.duration_entry = self._make_entry(f1, self.duration_var)
        self.duration_entry.grid(
            row=2, column=0, sticky="ew", ipady=5, pady=(2, 0))
        note = ("说明：总时长到点即停止（步骤之间不会被打断）；"
                "填 0 则一直按每步间隔循环，直到手动停止")
        tk.Label(f1, text=note, bg=CARD, fg=MUTED, font=FONT_SM,
                 anchor="w", justify="left").grid(
            row=3, column=0, sticky="w", pady=(4, 0))

        # 卡片 2：点击坐标（数量可自定义，按顺序依次点击，
        # 每个坐标可单独设置间隔秒数与单击/双击）
        f2 = self._card(main)
        self._section_title(f2, "点击坐标（可增删，最多 20 个，每行可单独设置间隔与单击/双击）", 0)
        f2.columnconfigure(0, weight=1)

        # 坐标列表表头（与下面的行使用相同的列权重，保证对齐）
        head = tk.Frame(f2, bg=CARD)
        head.grid(row=1, column=0, sticky="ew")
        head.columnconfigure(1, weight=3)
        head.columnconfigure(2, weight=4)
        heads = ((0, "次序", 5, {"sticky": "w"}),
                 (1, "名称", None, {"sticky": "w", "padx": (0, 6)}),
                 (2, "坐标 X,Y", None, {"sticky": "w", "padx": (0, 6)}),
                 (3, "间隔(秒)", None, {"sticky": "w", "padx": (0, 6)}),
                 (4, "点击方式", None, {"sticky": "w"}))
        for col, text, width, kw in heads:
            lbl = tk.Label(head, text=text, bg=CARD, fg=MUTED, font=FONT_SM,
                           anchor="w")
            if width:
                lbl.config(width=width)
            lbl.grid(row=0, column=col, **kw)

        body = tk.Frame(f2, bg=CARD)
        body.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._rows_canvas = tk.Canvas(body, bg=CARD, highlightthickness=0, bd=0,
                                      height=COORD_ROW_H * 2)
        self._rows_scroll = tk.Scrollbar(body, orient="vertical", width=10,
                                         command=self._rows_canvas.yview,
                                         bg=CARD, troughcolor=FIELD, bd=0,
                                         highlightthickness=0, relief="flat",
                                         activebackground=BORDER)
        self._rows_canvas.configure(yscrollcommand=self._rows_scroll.set)
        self._rows_canvas.pack(side="left", fill="both", expand=True)
        self.rows_host = tk.Frame(self._rows_canvas, bg=CARD)
        self._rows_win = self._rows_canvas.create_window((0, 0), window=self.rows_host,
                                                         anchor="nw")
        self.rows_host.bind(
            "<Configure>",
            lambda e: self._rows_canvas.configure(scrollregion=self._rows_canvas.bbox("all")))
        self._rows_canvas.bind(
            "<Configure>",
            lambda e: self._rows_canvas.itemconfigure(self._rows_win, width=e.width))
        self._bind_wheel(self._rows_canvas)
        self._bind_wheel(self.rows_host)

        # 坐标列表工具栏
        tools = tk.Frame(f2, bg=CARD)
        tools.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.add_btn = self._make_ghost_button(
            tools, "＋ 添加坐标", self.add_row, fg=GREEN)
        self.add_btn.pack(side="left")
        self.reset_btn = self._make_ghost_button(
            tools, "重置默认", self.reset_rows)
        self.reset_btn.pack(side="left", padx=(8, 0))
        tk.Label(tools, text=f"间隔 = 点完后等多久点下一个 · 轮末至少 {LOOP_GAP:g} 秒",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(side="right")

        # 默认三行：抢答 / 复位 / 抢答
        for name, key, iv in DEFAULT_STEPS:
            pos = self.default_points.get(key, (0, 0))
            self.add_row(name=name, pos=f"{pos[0]},{pos[1]}",
                         interval=step_interval(iv, self.default_interval),
                         redraw=False)
        self._sync_rows_height()
        # 界面里显示的参数就是即将生效的参数（点击「开始」时还会再次校验）
        try:
            self._state = self.collect_state()
        except ValueError:
            self._state = None

        # 开始 / 停止
        btns = tk.Frame(main, bg=BG)
        btns.pack(fill="x", pady=(0, 8))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        self.start_btn = self._make_button(btns, "开 始", self.start, GREEN, GREEN_HL)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipady=6)
        self.stop_btn = self._make_button(btns, "停 止", self.stop, RED, RED_HL)
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0), ipady=6)
        self._enable_button(self.stop_btn, False)

        # 状态栏
        f3 = self._card(main, pady=(0, 6))
        self.dot = tk.Label(f3, text="\u25cf", bg=CARD, fg=MUTED, font=FONT_DOT)
        self.dot.grid(row=0, column=0, sticky="n")
        self.status_var = tk.StringVar(value=self.default_status())
        tk.Label(f3, textvariable=self.status_var, bg=CARD, fg=TEXT, font=FONT_SM,
                 anchor="w", justify="left", wraplength=380).grid(
            row=0, column=1, sticky="w", padx=(8, 0))
        f3.columnconfigure(1, weight=1)

        # 使用提示
        tk.Label(main, text=f"紧急停止：按 {HOTKEY_TEXT}（任意窗口下均有效）",
                 bg=BG, fg=RED, font=FONT_SM).pack(anchor="w")

        self._autosize()

    def default_status(self):
        """未运行时的默认状态栏文本。"""
        return (f"就绪 · 每行按自己的间隔点击（轮末 ≥{LOOP_GAP:g} 秒）"
                f" · {HOTKEY_TEXT} 紧急停止")

    def _set_status(self, text, color=MUTED):
        self.status_var.set(text)
        self.dot.config(fg=color)

    # ---------------- 坐标行（数量可自定义） ----------------
    def add_row(self, name="", pos="", mode=None, interval=None, redraw=True):
        """新增一行坐标，返回该行数据字典。"""
        if len(self.rows) >= MAX_COORD_ROWS:
            self._messagebox.showinfo("提示", f"最多支持 {MAX_COORD_ROWS} 个坐标")
            return None

        if interval is None:      # 沿用上一行的间隔，没有则用默认值
            if self.rows:
                interval = self.rows[-1]["interval"].get()
            else:
                interval = getattr(self, "default_interval", DEFAULT_INTERVAL)

        row = {"name": tk.StringVar(value=str(name)),
               "pos": tk.StringVar(value=str(pos)),
               "mode": tk.StringVar(value=mode or CLICK_SINGLE),
               "interval": tk.StringVar(value=self._fmt_num(interval))}
        frame = tk.Frame(self.rows_host, bg=CARD)
        frame.pack(fill="x", pady=(0, 4))
        frame.columnconfigure(1, weight=3)
        frame.columnconfigure(2, weight=4)
        row["frame"] = frame

        seq = tk.Label(frame, text="", bg=CARD, fg=MUTED, font=FONT_SM,
                       width=5, anchor="w")
        seq.grid(row=0, column=0, sticky="w")
        row["seq"] = seq

        name_entry = self._make_entry(frame, row["name"])
        name_entry.grid(row=0, column=1, sticky="ew", ipady=4, padx=(0, 6))
        row["name_entry"] = name_entry
        pos_entry = self._make_entry(frame, row["pos"])
        pos_entry.grid(row=0, column=2, sticky="ew", ipady=4, padx=(0, 6))
        row["pos_entry"] = pos_entry

        # 该坐标点击完之后的间隔时间（秒）
        interval_entry = self._make_entry(frame, row["interval"], width=5)
        interval_entry.grid(row=0, column=3, sticky="ew", ipady=4, padx=(0, 6))
        row["interval_entry"] = interval_entry

        # 该坐标的点击方式：单击 / 双击（默认单击）
        mode_box = self._ttk.Combobox(frame, textvariable=row["mode"], font=FONT_SM,
                                      width=4, state="readonly", takefocus=0,
                                      values=list(CLICK_MODES))
        mode_box.grid(row=0, column=4, sticky="ew", ipady=3, padx=(0, 6))
        row["mode_box"] = mode_box

        pick_btn = self._make_ghost_button(frame, "拾取", lambda: None)
        pick_btn.grid(row=0, column=5, padx=(0, 4))
        row["pick_btn"] = pick_btn

        del_btn = self._make_ghost_button(frame, "✕", lambda: None, fg=RED)
        del_btn.config(padx=6)
        del_btn.grid(row=0, column=6)
        row["del_btn"] = del_btn

        # 行内控件都绑定滚轮，鼠标停在输入框上也能滚动列表
        for w in (frame, seq, name_entry, pos_entry, interval_entry,
                  mode_box, pick_btn, del_btn):
            self._bind_wheel(w)

        self.rows.append(row)
        index = len(self.rows) - 1
        pick_btn.config(command=lambda i=index: self.capture_pos(i))
        del_btn.config(command=lambda r=row: self.remove_row(r))

        self._renumber_rows()
        if redraw:
            self._sync_rows_height()
            self._autosize(keep_pos=True)
        return row

    def remove_row(self, row):
        """删除一行坐标（至少保留一行）。"""
        if row not in self.rows or len(self.rows) <= 1:
            return
        self.rows.remove(row)
        try:
            row["frame"].destroy()
        except Exception:
            pass
        self._renumber_rows()
        self._sync_rows_height()
        self._autosize(keep_pos=True)

    def reset_rows(self):
        """恢复为默认的三行坐标（抢答 / 复位 / 抢答）。"""
        if not self._messagebox.askyesno("确认", "恢复为默认的三行坐标？"):
            return
        for row in list(self.rows):
            try:
                row["frame"].destroy()
            except Exception:
                pass
        self.rows.clear()
        for name, key, iv in DEFAULT_STEPS:
            pos = self.default_points.get(key, (0, 0))
            self.add_row(name=name, pos=f"{pos[0]},{pos[1]}",
                         interval=step_interval(iv, self.default_interval),
                         redraw=False)
        self.duration_var.set(self._fmt_num(self.default_duration))
        self._sync_rows_height()
        self._autosize(keep_pos=True)
        self._state = self.collect_state()
        self.apply_state(self._state)
        self._set_status("已恢复默认参数", ACCENT)

    def _renumber_rows(self):
        """刷新「第 N 次」序号以及删除按钮可用状态。"""
        only_one = len(self.rows) <= 1
        for i, row in enumerate(self.rows):
            row["seq"].config(text=f"第{i + 1}次")
            self._enable_button(row["del_btn"], not only_one)

    def _sync_rows_height(self):
        """按行数调整列表高度：超过 4 行才显示滚动条。"""
        visible = min(max(len(self.rows), 1), COORD_VISIBLE_ROWS)
        self._rows_canvas.configure(height=visible * COORD_ROW_H)
        if len(self.rows) > COORD_VISIBLE_ROWS:
            if not self._rows_scroll.winfo_manager():
                self._rows_scroll.pack(side="right", fill="y")
        else:
            self._rows_scroll.pack_forget()
            self._rows_canvas.yview_moveto(0)

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        if self._rows_scroll.winfo_manager():
            self._rows_canvas.yview_scroll(int(-event.delta / 120), "units")

    @staticmethod
    def _fmt_num(value):
        """把数字格式化成界面显示的文本（10.0 -> 10，1.50 -> 1.5）。"""
        try:
            return f"{float(value):g}"
        except Exception:
            return str(value)

    # ---------------- 参数校验（出错时把对应输入框标红） ----------------
    def _mark_error(self, widget, message):
        """把出错的控件标红并抛出带定位信息的 ValueError。"""
        try:
            widget.configure(highlightthickness=2, highlightbackground=RED,
                             highlightcolor=RED)
            widget.focus_set()
        except Exception:
            pass
        raise ValueError(message)

    def _clear_error(self, widget):
        try:
            widget.configure(highlightthickness=0)
        except Exception:
            pass

    def collect_state(self):
        """读取并校验界面里的全部参数，返回 RunState；出错抛 ValueError。

        校验用的是界面上「当前显示」的值，并会标红出错的输入框，
        因此不会出现「界面改了但程序仍按旧值运行」的情况。
        """
        try:
            duration = float(self.duration_var.get())
            if duration < 0:
                raise ValueError
        except Exception:
            self._mark_error(self.duration_entry,
                             "自动点击总时长必须是不小于 0 的数字（0 表示不限时）")

        names, points, doubles, intervals = [], [], [], []
        for i, row in enumerate(self.rows):
            name = row["name"].get().strip() or f"第{i + 1}次"
            raw = row["pos"].get().strip().replace("，", ",")
            self._clear_error(row["pos_entry"])
            try:
                x_str, y_str = raw.split(",")
                pos = (int(float(x_str)), int(float(y_str)))
            except Exception:
                self._mark_error(
                    row["pos_entry"],
                    f"第 {i + 1} 行「{name}」的坐标格式应为：X,Y（例如 1570,130）")

            self._clear_error(row["interval_entry"])
            raw_iv = row["interval"].get().strip().replace("，", ".")
            try:
                interval = float(raw_iv)
            except Exception:
                self._mark_error(
                    row["interval_entry"],
                    f"第 {i + 1} 行「{name}」的间隔时间不是数字：{raw_iv or '（空）'}")
            if interval <= 0:
                self._mark_error(
                    row["interval_entry"],
                    f"第 {i + 1} 行「{name}」的间隔时间必须大于 0 秒")

            names.append(name)
            points.append(pos)
            doubles.append(self.row_double(i))
            intervals.append(interval)

        return RunState(names, points, doubles, intervals, duration)

    def apply_state(self, state):
        """把状态写回界面（用于「重置默认」「开始」后的界面同步）。"""
        self.duration_var.set(self._fmt_num(state.duration))
        for i, row in enumerate(self.rows):
            if i >= len(state.points):
                break
            row["name"].set(state.names[i])
            row["pos"].set(f"{state.points[i][0]},{state.points[i][1]}")
            row["interval"].set(f"{state.intervals[i]:g}")
            row["mode"].set(CLICK_DOUBLE if state.doubles[i] else CLICK_SINGLE)
        return state

    def _parse_row(self, index):
        row = self.rows[index]
        raw = row["pos"].get().strip().replace("，", ",")
        x_str, y_str = raw.split(",")
        return int(float(x_str)), int(float(y_str))

    def row_name(self, index):
        if 0 <= index < len(self.rows):
            return self.rows[index]["name"].get().strip() or f"第{index + 1}次"
        return f"第{index + 1}次"

    def row_double(self, index):
        """该坐标行是否为双击（界面上显示的是「双击」二字）。"""
        if 0 <= index < len(self.rows):
            return self.rows[index]["mode"].get().strip() == CLICK_DOUBLE
        return False

    # ---------------- 遮罩式坐标拾取器 ----------------
    def capture_pos(self, index):
        """弹出全屏半透明遮罩，鼠标点击处即为拾取坐标。"""
        if not HAS_PYAUTOGUI:
            self._messagebox.showerror("缺少依赖", "请先安装 pyautogui：\npip install pyautogui")
            return
        if self._picking:
            return
        if not (0 <= index < len(self.rows)):
            return

        self._picking = True
        self._overlay_index = index
        nice = self.row_name(index)

        ov = tk.Toplevel(self.root)
        self._overlay = ov
        ov.overrideredirect(True)          # 无边框
        ov.configure(bg=MASK_BG)
        sw, sh = ov.winfo_screenwidth(), ov.winfo_screenheight()
        ov.geometry(f"{sw}x{sh}+0+0")

        # 真正的透明遮罩：整块窗口半透明（能看见屏幕后面的画面），
        # 且 alpha 大于 0，鼠标点击会被遮罩吃掉、不会穿透到后面的程序。
        try:
            ov.attributes("-alpha", MASK_ALPHA)
        except Exception:
            pass
        try:
            ov.attributes("-topmost", True)
        except Exception:
            pass

        canvas = tk.Canvas(ov, bg=MASK_BG, highlightthickness=0, bd=0,
                           cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        # 十字准线（画在遮罩画布上，跟随鼠标）
        vline = canvas.create_line(-1, -1, -1, -1, fill=ACCENT, width=2)
        hline = canvas.create_line(-1, -1, -1, -1, fill=ACCENT, width=2)

        # 提示条与坐标气泡
        tip = tk.Label(canvas, text=f"点击屏幕拾取「{nice}」  ·  按 Esc 取消",
                       bg="#111a2e", fg="#ffffff", font=FONT_SM,
                       padx=12, pady=6)
        tip.place(x=20, y=20)
        coord = tk.Label(canvas, text="0, 0", bg=ACCENT, fg="#ffffff",
                         font=("Consolas", 10, "bold"), padx=8, pady=4)

        def _on_move(e):
            canvas.coords(vline, e.x, 0, e.x, sh)
            canvas.coords(hline, 0, e.y, sw, e.y)
            coord.place(x=min(e.x + 16, sw - 90), y=max(e.y - 34, 8))
            coord.config(text=f"{e.x_root}, {e.y_root}")
            tip.place(x=min(e.x + 16, sw - 240),
                      y=e.y + 16 if e.y + 46 < sh else e.y - 46)

        def _on_click(e):
            self._finish_pick(index, e.x_root, e.y_root)

        for w in (ov, canvas):
            w.bind("<Motion>", _on_move)
            w.bind("<Button-1>", _on_click)
            w.bind("<Escape>", lambda e: self._close_overlay())
            w.bind("<Button-3>", lambda e: self._close_overlay())

        ov.lift()
        ov.update_idletasks()              # 一次性画完再显示，避免闪黑屏
        ov.update()
        try:
            ov.focus_force()               # 让 Esc 生效
        except Exception:
            pass

        self._set_status(f"请点击屏幕上「{nice}」的位置（Esc 取消）…", ACCENT)

    def _finish_pick(self, index, x, y):
        nice = self.row_name(index)
        if 0 <= index < len(self.rows):
            self.rows[index]["pos"].set(f"{x},{y}")
        self._close_overlay()
        self._set_status(f"已拾取「{nice}」坐标：({x}, {y})", ACCENT)

    def _close_overlay(self):
        self._picking = False
        self._overlay_index = None
        ov = self._overlay
        self._overlay = None
        if ov is not None:
            try:
                ov.destroy()
            except Exception:
                pass
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass

    # ---------------- 启停控制 ----------------
    def set_running(self, running):
        was_running = self.running
        self.running = running
        self._enable_button(self.start_btn, not running)
        self._enable_button(self.stop_btn, running)
        # 运行结束（到时 / 手动停止 / 急停 / 出错）后，把窗口从任务栏自动恢复
        if was_running and not running:
            self._restore_window()

    def start(self):
        if not HAS_PYAUTOGUI:
            self._messagebox.showerror("缺少依赖", "请先安装 pyautogui：\npip install pyautogui")
            return
        if self.running:
            return
        try:
            state = self.collect_state()          # 读界面 → 校验
        except ValueError as e:
            self._set_status(str(e), RED)
            self._messagebox.showwarning("参数有误", str(e))
            return
        if not state.points:
            self._messagebox.showwarning("提示", "请至少添加一个点击坐标")
            return

        self.apply_state(state)                   # 把生效值写回界面（所见即所跑）
        self._state = state

        # 计算截止时间（0 = 不限时）
        self._deadline = (time.time() + state.duration * 60
                          if state.duration > 0 else None)

        self.set_running(True)
        self._set_status(state.describe(), GREEN)
        # 运行期间自动隐藏到任务栏（等界面刷新完再最小化）
        self._minimize_job = self.root.after(150, self._minimize_window)
        self.thread = threading.Thread(target=self.loop,
                                       args=(state, self._deadline),
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.set_running(False)
        self._set_status("已停止", RED)

    def emergency_stop(self):
        """紧急停止（Ctrl+Q 或热键触发），并把窗口还原到最前。"""
        if not self.running:
            return
        self.set_running(False)
        self._set_status(f"已按 {HOTKEY_TEXT} 紧急停止", RED)

    def _minimize_window(self):
        """把主窗口最小化到任务栏（运行时尽量不打扰用户）。"""
        self._minimize_job = None
        if not self.running:
            return
        try:
            self.root.iconify()
        except Exception:
            pass

    def _restore_window(self):
        """还原并置前主窗口（最小化时恢复显示）。"""
        job = getattr(self, "_minimize_job", None)
        if job is not None:                       # 取消还没执行的最小化
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
            self._minimize_job = None
        try:
            self.root.deiconify()        # 若被最小化/隐藏则还原
            self.root.state("normal")
        except Exception:
            pass
        job = getattr(self, "_restore_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
            self._restore_job = None
        try:
            self.root.attributes("-topmost", True)   # 短暂置顶以抢回焦点
            self.root.lift()
            self.root.focus_force()
            self._restore_job = self.root.after(
                400, self._topmost_off)
        except Exception:
            pass

    def _topmost_off(self):
        """取消临时置顶。"""
        self._restore_job = None
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass

    @staticmethod
    def _remain_text(deadline):
        """剩余时长文本（不限时返回空串）。"""
        if deadline is None:
            return ""
        left = max(int(deadline - time.time()), 0)
        return f" · 剩余 {left // 60:02d}:{left % 60:02d}"

    @staticmethod
    def _click_once(pos):
        """单击一次。"""
        pyautogui.click(pos[0], pos[1])

    @staticmethod
    def _click_twice(pos):
        """快速双击（两次点击间隔 0.1 秒）。"""
        pyautogui.click(pos[0], pos[1], clicks=2, interval=DOUBLE_CLICK_INTERVAL)

    def loop(self, state, deadline=None):
        """按顺序依次点击 state 里的每个坐标，每个点用自己设定的间隔。

        间隔表示「点完这个坐标后等多久点下一个」；
        一轮的最后一步到下一轮第一步之间至少等待 LOOP_GAP 秒。
        state 是开始运行时从界面读取的快照（RunState）。
        """
        points = state.as_points()
        if not points:
            self.root.after(0, self.set_running, False)
            return
        try:
            while self.running:
                if self._stop_if_finished(deadline):
                    break

                stopped = False
                last = len(points) - 1
                for i, (_name, pos, double, wait) in enumerate(points):
                    if not self.running:
                        stopped = True
                        break
                    (self._click_twice if double else self._click_once)(pos)
                    self.root.after(0, self._set_status,
                                    state.describe_point(
                                        i, self._remain_text(deadline)), GREEN)
                    # 先点击，再等待本行设定的间隔（间隔 = 点完这个坐标后
                    # 等多久点下一个；轮末不少于 LOOP_GAP 秒）
                    gap = max(wait, LOOP_GAP) if i == last else wait
                    if not self._sleep(gap, deadline):
                        stopped = True
                        break
                if stopped:
                    break
        except pyautogui.FailSafeException:
            self.root.after(0, self._set_status, "已触发 fail-safe，循环已停止", RED)
            self.root.after(0, self.emergency_stop)
        except Exception as e:
            self.root.after(0, self._messagebox.showerror, "运行错误", str(e))
            self.root.after(0, self.emergency_stop)
        finally:
            self.root.after(0, self.set_running, False)

    def _sleep(self, seconds, deadline=None):
        """可被打断的分段等待，返回 False 表示已停止 / 到时。

        说明：调用时机是「本次点击已经完成之后」，所以每一步都是
        「先点击，再等待」；这里也不做「不超过 _deadline」的截断，
        以保证真的会停满设定的秒数。
        """
        end = time.time() + seconds
        while self.running:
            remain = end - time.time()
            if remain <= 0:                     # 停满设定的秒数
                break
            if hotkey_stop_pressed():
                self.root.after(0, self.emergency_stop)
                return False
            if deadline is not None and time.time() >= deadline:
                self.root.after(0, self._finish_duration)
                return False
            time.sleep(min(SLEEP_TICK, remain))
        return self.running

    def _stop_if_finished(self, deadline):
        """每一步开始前检查：是否按下急停 / 是否已到设定总时长。

        返回 True 表示应当停止循环。
        """
        if not self.running:
            return True
        if hotkey_stop_pressed():
            self.root.after(0, self.emergency_stop)
            return True
        if deadline is not None and time.time() >= deadline:
            self.root.after(0, self._finish_duration)
            return True
        return False

    def _finish_duration(self):
        """到达设定总时长后自动停止。"""
        if not self.running:
            return
        self._deadline = None
        self.set_running(False)
        self._set_status("已到达设定总时长，自动停止", ACCENT)
        self._restore_window()


def main():
    parser = argparse.ArgumentParser(description="抢答器定时点击器")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="新增坐标的默认间隔时间（秒）")
    parser.add_argument("--duration", type=float, default=30.0,
                        help="自动点击总时长（分钟，0 表示不限时）")
    parser.add_argument("--cli", action="store_true", help="使用命令行模式（无界面）")
    parser.add_argument("--double", action="store_true",
                        help="命令行模式下全部使用双击（默认单击）")
    parser.add_argument("--points", default="",
                        help='自定义坐标，分号分隔，如 "1570,130@5;1720,130@10"\n'
                             '坐标后可加 d 表示双击、@秒 单独指定该坐标的间隔\n'
                             '（不写均为 --interval，默认抢答+复位）')
    args = parser.parse_args()

    if args.cli:
        pass  # 直接进入下方命令行逻辑
    elif not HAS_TK:
        print("当前环境无 tkinter，自动降级为命令行模式。")
    else:
        _tk, _ttk, _mb = _load_tk()
        root = _tk.Tk()
        root.withdraw()   # 先隐藏，等界面布局完成后再显示，避免启动闪烁
        App(root, interval=args.interval, duration=args.duration)
        root.mainloop()
        return

    # ===== 命令行模式（--cli 或无 GUI 时）=====
    interval = args.interval
    duration = args.duration
    if not HAS_PYAUTOGUI:
        print("需要 pyautogui: pip install pyautogui")
        return
    if args.points.strip():
        points = []
        for i, seg in enumerate(args.points.replace("；", ";").split(";")):
            seg = seg.strip()
            if not seg:
                continue
            gap = interval                       # 该坐标的间隔：默认用 --interval
            if "@" in seg:
                seg, gap_txt = seg.rsplit("@", 1)
                gap = float(gap_txt)
            if gap <= 0:
                print(f"间隔时间必须大于 0：{seg}")
                return
            double = seg.endswith(("d", "D"))
            if double:
                seg = seg[:-1]
            xs, ys = seg.replace("，", ",").split(",")
            points.append((f"第{i + 1}次",
                           (int(float(xs)), int(float(ys))),
                           double or args.double, gap))
    else:
        buttons = locate_buttons()
        points = [(name, buttons[key], args.double, step_interval(iv, interval))
                  for name, key, iv in DEFAULT_STEPS]

    deadline = time.time() + duration * 60 if duration > 0 else None
    dur_txt = "不限时" if deadline is None else f"{duration:g} 分钟"
    n_double = sum(1 for _, _, dbl, _ in points if dbl)
    mode_txt = "全部单击" if not n_double else (
        "全部双击" if n_double == len(points) else f"{n_double} 个双击")

    def do_click(pos, double):
        if double:
            pyautogui.click(pos[0], pos[1], clicks=2, interval=DOUBLE_CLICK_INTERVAL)
        else:
            pyautogui.click(pos[0], pos[1])

    print(f"{mode_txt}, 间隔 {[iv for *_, iv in points]}s（轮末 ≥{LOOP_GAP:g}s）, "
          f"总时长 {dur_txt}, {len(points)} 个坐标 "
          f"{[p for _, p, _d, _iv in points]}  (Ctrl+C 停止)")
    try:
        while deadline is None or time.time() < deadline:
            last = len(points) - 1
            for i, (name, pos, double, gap) in enumerate(points):
                do_click(pos, double)
                print(f"{'双击' if double else '单击'} {name}")
                # 最后一步之后等待自己的间隔（不少于 LOOP_GAP）再开下一轮
                time.sleep(max(gap, LOOP_GAP) if i == last else gap)
                if deadline is not None and time.time() >= deadline:
                    break
        print("已停止")
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 无控制台的 exe 看不到报错信息，用弹窗提示
        import traceback
        detail = traceback.format_exc()
        try:
            import tkinter.messagebox as _mb
            _mb.showerror("程序出错", detail)
        except Exception:
            pass
        raise
