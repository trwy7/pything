# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/trey/Documents/pything/launch.py'],
    pathex=[],
    binaries=[('/home/trey/Documents/pything/.venv/bin/uv', 'bin')],
    datas=[('/home/trey/Documents/pything/src', 'src'), ('/home/trey/Documents/pything/pyproject.toml', '.'), ('/home/trey/Documents/pything/uv.lock', '.'), ('/home/trey/Documents/pything/README.md', '.')],
    hiddenimports=['uv', 'engineio.async_drivers.threading'],
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
    name='pything',
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
