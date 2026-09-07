# -*- mode: python ; coding: utf-8 -*-
# Build with: source .buildenv/bin/activate && pyinstaller backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

datas = collect_data_files('pyexiv2')
binaries = collect_dynamic_libs('pyexiv2')

hiddenimports = (
    collect_submodules('uvicorn') +
    collect_submodules('fastapi') +
    collect_submodules('routers') +
    collect_submodules('domains') +
    collect_submodules('tools') +
    collect_submodules('mcp_servers') +
    [
        'main',
        'database',
        'models',
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
    ]
)

a = Analysis(
    ['cli.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
