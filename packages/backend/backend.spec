# -*- mode: python ; coding: utf-8 -*-
# Build with: source .buildenv/bin/activate && pyinstaller backend.spec --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

datas = collect_data_files('pyexiv2')
binaries = collect_dynamic_libs('pyexiv2')

a = Analysis(
    ['cli.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.workers',
        'uvicorn.__main__',
        'main',
        'database',
        'models',
        'routers',
        'routers.artifacts',
        'routers.chat',
        'routers.diagnostics',
        'routers.files',
        'routers.gee',
        'routers.geocode',
        'routers.rag',
        'routers.scenarios',
        'routers.streetview',
        'routers.wms',
        'mcp_servers',
        'mcp_servers.datameet_server',
        'mcp_servers.demographics_server',
        'mcp_servers.emissions_server',
        'mcp_servers.gee_server',
        'mcp_servers.gis_server',
        'mcp_servers.google_environment_server',
        'mcp_servers.google_places_server',
        'mcp_servers.gtfs_server',
        'mcp_servers.its_server',
        'mcp_servers.network_server',
        'mcp_servers.od_server',
        'mcp_servers.osm_server',
        'mcp_servers.overture_server',
        'mcp_servers.scenario_server',
        'mcp_servers.weather_server',
        'mcp_servers.wms_server',
        'mcp_servers.zoning_server',
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
        'tools.artifact_store',
        'tools.utility',
    ],
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
