# -*- mode: python ; coding: utf-8 -*-
# Build with: source .buildenv/bin/activate && pyinstaller backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
import sys
from pathlib import Path

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

# Fiona ships its own SQLite dylib. On macOS it can take precedence over
# Python's sqlite3 extension and cause an unresolved sqlite3_deserialize
# symbol before FastAPI starts. Ensure only a modern SQLite dylib containing
# sqlite3_deserialize is included.
collected_binaries = [
    item for item in a.binaries
    if Path(item[0]).name not in {'libsqlite3.0.dylib', 'libsqlite3.dylib'}
]

if sys.platform == 'darwin':
    import ctypes
    import subprocess
    sqlite_candidates = [
        Path(sys.base_prefix) / 'lib' / 'libsqlite3.0.dylib',
        Path(sys.base_prefix) / 'lib' / 'libsqlite3.dylib',
        Path(sys.prefix) / 'lib' / 'libsqlite3.0.dylib',
        Path(sys.prefix) / 'lib' / 'libsqlite3.dylib',
        Path('/opt/homebrew/opt/sqlite/lib/libsqlite3.0.dylib'),
        Path('/opt/homebrew/opt/sqlite/lib/libsqlite3.dylib'),
        Path('/usr/local/opt/sqlite/lib/libsqlite3.0.dylib'),
        Path('/usr/local/opt/sqlite/lib/libsqlite3.dylib'),
    ]
    try:
        brew_prefix = subprocess.check_output(['brew', '--prefix', 'sqlite'], text=True, stderr=subprocess.DEVNULL).strip()
        if brew_prefix:
            sqlite_candidates.extend([
                Path(brew_prefix) / 'lib' / 'libsqlite3.0.dylib',
                Path(brew_prefix) / 'lib' / 'libsqlite3.dylib',
            ])
    except Exception:
        pass

    sqlite_source = None
    for cand in sqlite_candidates:
        if cand.exists():
            resolved = cand.resolve()
            if resolved.exists():
                try:
                    lib = ctypes.cdll.LoadLibrary(str(resolved))
                    if hasattr(lib, 'sqlite3_deserialize'):
                        sqlite_source = resolved
                        break
                except Exception:
                    continue

    if sqlite_source:
        collected_binaries.append(('libsqlite3.0.dylib', str(sqlite_source), 'BINARY'))
        collected_binaries.append(('libsqlite3.dylib', str(sqlite_source), 'BINARY'))

coll = COLLECT(
    exe,
    collected_binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
