# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: onedir + Fluxel.exe（Inno Setup から取り込み）
# ビルド: リポジトリルートで  uv sync --extra pack  のあと
#   uv run pyinstaller packaging\fluxel.spec
#
# PySide6 は collect_all しない（QtWebEngine / 3D / Charts 等まで梱包して数百 MB になるため）。
# main.py → fluxel の import ツリーと PyInstaller の PySide6 フックで必要分のみ取り込む。

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / "fig" / "ico" / "app.ico"), "fig/ico")]
binaries: list = []
hiddenimports = list(collect_submodules("fluxel"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="Fluxel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "fig" / "ico" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Fluxel",
)
