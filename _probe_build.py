# -*- coding: utf-8 -*-
"""临时脚本：构建带控制台的诊断版 exe（--onedir 更快），用于查看冻结环境里的报错。"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "auto_clicker.py")
WORK = os.path.join(HERE, "_probe")
DIST = os.path.join(WORK, "dist")
BUILD = os.path.join(WORK, "build")

for p in (WORK,):
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)

dlls = []
for d in (os.path.join(sys.base_prefix, "Library", "bin"),
          os.path.join(sys.prefix, "Library", "bin"),
          os.path.join(sys.base_prefix, "DLLs")):
    if os.path.isdir(d):
        for pat in ("tcl[0-9]*t.dll", "tk[0-9]*t.dll", "zlib*.dll", "liblzma*.dll"):
            dlls.extend(glob.glob(os.path.join(d, pat)))

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--console", "--onedir",
    "--name", "probe_console",
    "--distpath", DIST, "--workpath", BUILD, "--specpath", WORK,
    "--hidden-import", "pyautogui",
    "--hidden-import", "pyscreeze",
    "--hidden-import", "PIL",
]
for d in sorted(set(dlls)):
    cmd += ["--add-binary", d + os.pathsep + "."]
cmd.append(ENTRY)

print("构建诊断版 ...")
subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
exe = os.path.join(DIST, "probe_console", "probe_console.exe")
print("EXE =", exe, os.path.isfile(exe))

# 运行并捕获输出（3 秒后杀掉）
out = os.path.join(WORK, "out.txt")
err = os.path.join(WORK, "err.txt")
with open(out, "wb") as fo, open(err, "wb") as fe:
    p = subprocess.Popen([exe], stdout=fo, stderr=fe, cwd=os.path.dirname(exe))
    try:
        code = p.wait(timeout=8)
        print("已退出, code =", code)
    except subprocess.TimeoutExpired:
        p.kill()
        print("仍在运行(GUI 已启动)")

print("--- STDOUT ---")
print(open(out, "rb").read().decode("utf-8", "replace")[:3000])
print("--- STDERR ---")
print(open(err, "rb").read().decode("utf-8", "replace")[:3000])
