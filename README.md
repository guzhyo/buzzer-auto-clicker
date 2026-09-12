# 抢答器定时点击器

按每个坐标自己设定的间隔时间，自动依次点击「3秒延时抢答」→「复位」→「3秒延时抢答」三个按钮。
每个坐标行都能单独设置**间隔秒数**和**单击 / 双击**，默认间隔 **10 秒**、默认**单击**；
每一行都是**先点击、再等待**这一行设定的秒数，一轮的最后一步到下一轮第一步之间至少停 **1 秒**。

## 快速开始（Windows，打包成 exe）

1. 安装 Python 3：https://www.python.org （安装时务必勾选 **Add Python to PATH**）
2. 双击运行 `build_exe.py`，等待打包完成
3. 产物：`dist/抢答器定时点击器.exe`（单个文件，可直接双击运行，也可拷给其他人）

## 首次使用前：校准坐标

脚本里的坐标 `(1570, 130)` / `(1720, 130)` 是基于截图估算的，**大概率需要修改**：

1. 运行 `get_pos.py`，把鼠标分别移到「3秒延时抢答」和「复位」按钮中心
2. 记下打印出来的坐标，填入 `auto_clicker.py` 顶部的 `DEFAULT_POSITIONS`
3. （可选）更稳的做法：截取两个按钮的图片存为 `btn_qiangda.png` / `btn_fuwei.png`，
   程序会自动图像识别定位，无需手动填坐标

## 直接使用（不打包）

```bash
pip install pyautogui
python auto_clicker.py                # 图形界面，新增坐标的默认间隔 10 秒
python auto_clicker.py --interval 5   # 新增坐标的默认间隔改为 5 秒
python auto_clicker.py --cli          # 命令行模式
python auto_clicker.py --cli --points "1570,130d@5;1720,130@10"   # d=双击，@后为该点间隔
```

## 紧急停止

- 图形界面：点「停止」按钮
- 通用：把鼠标快速移到屏幕**左上角**（触发 pyautogui FailSafe）

## 文件说明

| 文件 | 作用 |
|------|------|
| `auto_clicker.py` | 主程序（图形界面 + 命令行双模式） |
| `build_exe.py` | 一键打包脚本，生成单个 exe |
| `get_pos.py` | 坐标采集工具，用于校准按钮位置 |
| `btn_qiangda.png` / `btn_fuwei.png` | （可选）按钮截图，用于图像识别定位 |
