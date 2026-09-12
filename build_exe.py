"""
【在 Windows 上运行】一键打包成单个 exe。

用法：
    1) 安装 Python 3（https://www.python.org ，安装时勾选 Add to PATH）
    2) 双击运行本脚本，或在命令行执行：
           python build_exe.py
    3) 生成的 exe 在 dist 目录： dist/抢答器定时点击器.exe

若想带图标：把 app.ico 放在与本脚本同一目录即可自动启用。
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "auto_clicker.py")
DIST = os.path.join(HERE, "dist")
BUILD = os.path.join(HERE, "build")

# 清理旧产物
for p in (DIST, BUILD, os.path.join(HERE, "auto_clicker.spec")):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.isfile(p):
        os.remove(p)

if not os.path.isfile(ENTRY):
    print("找不到入口文件:", ENTRY)
    sys.exit(1)

# 确保依赖（Pillow 是 pyscreeze/pyautogui 在运行时所必需的）
for pkg in ("pyinstaller", "pyautogui", "pillow"):
    print("检查/安装:", pkg)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])


def find_runtime_dlls():
    """定位 conda/Python 运行时 DLL。

    conda 环境的 tcl86t.dll / tk86t.dll 以及 _ctypes/_ssl/_decimal 等扩展模块
    依赖的 DLL（ffi.dll、libssl、libcrypto 等）都位于 Library/bin，不在
    PyInstaller 默认搜索路径内。若不手动 --add-binary 打进 exe，冻结环境
    中这些扩展模块会加载失败，表现为 tkinter / ctypes / pyautogui 等无法使用。
    """
    search_dirs = [
        os.path.join(sys.base_prefix, "Library", "bin"),  # conda 基础环境
        os.path.join(sys.prefix, "Library", "bin"),       # 基于 conda 的 venv
        os.path.join(sys.base_prefix, "DLLs"),
        os.path.join(sys.prefix, "DLLs"),
        sys.base_prefix,
        sys.prefix,
    ]
    patterns = (
        "tcl[0-9]*t.dll", "tk[0-9]*t.dll",
        "zlib*.dll", "liblzma*.dll",
        "ffi*.dll", "libssl*.dll", "libcrypto*.dll",
        "libexpat*.dll", "libmpdec*.dll", "libbz2*.dll", "LIBBZ2*.dll",
    )
    found = []
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for pat in patterns:
            found.extend(glob.glob(os.path.join(d, pat)))
    return sorted(set(found))


add_binary_opts = []
runtime_dlls = find_runtime_dlls()
for dll in runtime_dlls:
    add_binary_opts += ["--add-binary", dll + os.pathsep + "."]
if runtime_dlls:
    print("附加运行时 DLL:", ", ".join(os.path.basename(x) for x in runtime_dlls))
else:
    print("提示: 未找到运行时 DLL（若来自 conda 请检查 Library/bin）")

icon_opt = []
data_opts = []
app_icon = os.path.join(HERE, "app.ico")
if os.path.isfile(app_icon):
    icon_opt = ["--icon", app_icon]
    # 同时打进包内，供程序运行时 iconbitmap 设置窗口图标
    data_opts = ["--add-data", app_icon + os.pathsep + "."]
else:
    print("提示: 未找到 app.ico，将使用默认图标。")

# --onefile: 单个 exe
# --windowed: 无控制台黑框（GUI 程序；命令行模式请用 python auto_clicker.py --cli）
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed",
    "--name", "抢答器定时点击器",
    "--clean",
    "--hidden-import", "pyautogui",
    "--hidden-import", "pyautogui._pyautogui_win",
    "--hidden-import", "pyscreeze",
    "--hidden-import", "pymsgbox",
    "--hidden-import", "pytweening",
    "--hidden-import", "mouseinfo",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL.Image",
    "--hidden-import", "PIL.ImageGrab",
    "--hidden-import", "PIL.ImageDraw",
    *add_binary_opts,
    *data_opts,
    *icon_opt,
    ENTRY,
]
print("执行:", " ".join(cmd))
subprocess.check_call(cmd)

exe = os.path.join(DIST, "抢答器定时点击器.exe")
if os.path.isfile(exe):
    print("打包成功:", exe, f"({os.path.getsize(exe)/1024/1024:.1f} MB)")
else:
    print("未找到 exe，打包失败。")
    sys.exit(1)
