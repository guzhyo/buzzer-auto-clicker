# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/Administrator/Desktop/抢答器定时点击器/auto_clicker.py'],
    pathex=[],
    binaries=[('D:/ProgramData/miniconda3/Library/bin/ffi-7.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/ffi-8.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/ffi.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/libbz2.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/libcrypto-3-x64.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/libexpat.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/liblzma.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/libmpdec-4.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/libssl-3-x64.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/tcl86t.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/tk86t.dll', '.'), ('D:/ProgramData/miniconda3/Library/bin/zlib.dll', '.'), ('D:/ProgramData/miniconda3/zlib.dll', '.')],
    datas=[('C:/Users/Administrator/Desktop/抢答器定时点击器/app.ico', '.')],
    hiddenimports=['pyautogui', 'pyautogui._pyautogui_win', 'pyscreeze', 'pymsgbox', 'pytweening', 'mouseinfo', 'PIL', 'PIL.Image', 'PIL.ImageGrab', 'PIL.ImageDraw'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='抢答器定时点击器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/Administrator/Desktop/抢答器定时点击器/app.ico'],
)
