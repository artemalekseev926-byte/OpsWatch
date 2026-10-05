import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
ICON = str(Path(SPECPATH) / "opswatch.ico")

hiddenimports = collect_submodules("opswatch", filter=lambda name: not name.startswith("opswatch.migrations"))
for package in ("uvicorn", "aiogram", "apscheduler", "pyzipper", "alembic"):
    hiddenimports += collect_submodules(package)
hiddenimports += [
    "aiosqlite",
    "asyncpg",
    "asyncpg.pgproto.pgproto",
    "aiomysql",
    "pymysql",
    "pymssql",
    "pymssql._pymssql",
    "pymssql._mssql",
    "tzlocal",
    "multipart",
    "python_multipart",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "greenlet",
]
if sys.platform == "win32":
    hiddenimports += ["pystray._win32", "win32timezone", "win32serviceutil", "win32service", "win32event", "servicemanager", "pywintypes"]

datas = collect_data_files(
    "opswatch",
    includes=["web/static/*", "locales/*.json", "migrations/*.py", "migrations/*.mako", "migrations/versions/*.py"],
    include_py_files=True,
)
for dist in ("alembic", "apscheduler", "aiogram", "fastapi", "starlette", "pydantic", "uvicorn", "sqlalchemy", "httpx", "pywebview", "pystray", "tzlocal"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

excludes = ["tkinter", "matplotlib", "numpy", "pandas", "IPython", "pytest"]

desktop = Analysis(
    [str(Path(SPECPATH) / "opswatch_desktop.py")],
    pathex=[str(ROOT)],
    hiddenimports=hiddenimports + collect_submodules("webview"),
    datas=datas + collect_data_files("webview"),
    excludes=excludes,
    noarchive=False,
)
server = Analysis(
    [str(Path(SPECPATH) / "opswatch_server.py")],
    pathex=[str(ROOT)],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=excludes + ["webview", "clr", "pythonnet"],
    noarchive=False,
)

desktop_pyz = PYZ(desktop.pure)
server_pyz = PYZ(server.pure)

desktop_exe = EXE(
    desktop_pyz,
    desktop.scripts,
    [],
    exclude_binaries=True,
    name="OpsWatch",
    console=False,
    icon=ICON,
    version=str(Path(SPECPATH) / "version_info.txt"),
)
server_exe = EXE(
    server_pyz,
    server.scripts,
    [],
    exclude_binaries=True,
    name="OpsWatchServer",
    console=True,
    icon=ICON,
    version=str(Path(SPECPATH) / "version_info.txt"),
)

coll = COLLECT(
    desktop_exe,
    desktop.binaries,
    desktop.datas,
    server_exe,
    server.binaries,
    server.datas,
    name="OpsWatch",
)
