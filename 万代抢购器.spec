# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 配置文件 · 万代抢购器
#
# 用法（在 Windows PowerShell 里）：
#   pyinstaller --clean 万代抢购器.spec
# 或直接跑 scripts/build_exe.ps1
#
# 输出：dist/万代抢购器.exe（约 50-70 MB 单文件）

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).resolve()
SRC = ROOT / "src"

# ─── 数据文件（HTML/CSS/JS 必须打进 exe）──────────────
datas = [
    (str(SRC / "bandai_sniper" / "ui" / "web"), "bandai_sniper/ui/web"),
]

# 如果未来加 assets/icon.ico，这里也放进 datas 让运行时能读
icon_path = ROOT / "assets" / "icon.ico"

# ─── 显式 import（PyInstaller 自动扫描漏掉的）────────
hidden = [
    # httpx HTTP/2
    "h2",
    "h2.config",
    "h2.connection",
    "hpack",
    "hyperframe",
    # pywebview Qt 后端
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWidgets",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "qtpy",
    # pycryptodome（部分子模块按需加载）
    "Crypto.Cipher.AES",
    "Crypto.Util.Padding",
    # loguru / pydantic
    "loguru",
    "pydantic",
    "pydantic_core",
    # bottle (pywebview 内置 HTTP server)
    "bottle",
]

a = Analysis(
    ["main.py"],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要的大依赖排除，减小体积
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── onedir 模式：dist/万代抢购器/ 目录里有 .exe + 一堆 .dll/.pyd ───
# 优势：启动快（< 1 秒，不用解压临时目录）、调试友好（能看到包了哪些文件）
# 代价：分发要打成 zip。给朋友先压一个 zip 即可。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # 关键：onedir 模式 binaries 走 COLLECT
    name="万代抢购器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX 压缩有时触发杀毒，先关
    console=False,               # windowed：不弹 cmd 黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
    version=None,                # 后续可加 version_info.txt
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="万代抢购器",            # 输出目录名
)
