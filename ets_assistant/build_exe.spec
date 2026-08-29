# PyInstaller 打包配置
# 使用: pyinstaller build_exe.spec
import os

block_cipher = None

a = Analysis(
    ["__main__.py"],
    pathex=[os.path.dirname(os.path.abspath(__file__))],
    binaries=[],
    datas=[],
    hiddenimports=["PyQt5.QtWidgets", "PyQt5.QtCore", "PyQt5.QtGui",
                   "cv2", "pyautogui", "numpy", "pyaudio", "wave"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ETSAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,           # 不弹黑窗口
    icon=None,
)
