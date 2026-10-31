# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_submodules

# two standard packages required by apps, unfortunately
# FIXME: find a way to force pyinstaller to include standard libraries
hiddenimports = ["uv", "fileinput", "unittest"]
hiddenimports += collect_submodules('apps')


a = Analysis(
    ['src/pything/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/pything/apps', 'pything/apps'), ('src/pything/pages', 'pything/pages'), ('src/pything/static', 'pything/static')],
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
    a.binaries,
    a.datas,
    [],
    name='pything-windows.exe' if sys.platform == 'win32' else 'pything-linux',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
