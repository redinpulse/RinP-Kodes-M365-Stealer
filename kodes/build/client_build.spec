# -*- mode: python ; coding: utf-8 -*-
#
# Kodes client build spec — shared across Windows/macOS/Linux.
# Run from the kodes/ root:  pyinstaller build/client_build.spec
#
# Notes:
#  - Entry point is client_entry.py (a wrapper enabling package-relative imports).
#  - The template image is bundled as static/img/microsoft.png;
#    auth._find_template_image checks both this path and the bundle root.
#  - The campaign client.json is NOT bundled: it is per-engagement and passed
#    in externally via the -c flag (the frozen exe never reads config/client.json).
#  - Windows icons require .ico (PNG is invalid); the shared spec ships iconless.

block_cipher = None

a = Analysis(
    ['client_entry.py'],
    pathex=[],
    binaries=[],
    datas=[('static/img/microsoft.png', 'static/img')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='kodes-client',
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
)
