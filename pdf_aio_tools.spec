# PyInstaller build description. Run: python -m PyInstaller pdf_aio_tools.spec
# Produces dist/PDF-AIO-Tools.exe, one file that runs without Python installed.

a = Analysis(
    ["pdf_aio/__main__.py"],
    pathex=["."],
    datas=[("pdf_aio/assets/app.ico", "pdf_aio/assets")],
    # Standard library packages that nothing in the application imports at
    # run time, but that analysis would otherwise follow and bundle.
    excludes=["unittest", "pydoc", "doctest", "xmlrpc", "http.server", "sqlite3", "lib2to3"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="PDF-AIO-Tools",
    icon="pdf_aio/assets/app.ico",
    console=False,
    upx=False,  # UPX packed executables are flagged by antivirus scanners far more often
)
