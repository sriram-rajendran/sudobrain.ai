# PyInstaller spec for an experimental packaged backend.

block_cipher = None

a = Analysis(
    ["../backend/main.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "uvicorn",
        "fastapi",
        "psycopg2",
        "chromadb",
        "neo4j",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="sudobrain-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
