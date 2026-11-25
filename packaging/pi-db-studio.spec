# PyInstaller-Rezept für Pi DB Studio (Linux und Windows). Aufruf aus dem Projektordner:
#   pyinstaller packaging/pi-db-studio.spec --noconfirm
# Ergebnis: dist/PiDBStudio/ (Programm + _internal), daraus bauen die Workflows AppImage, tar.gz, ZIP und Setup.exe.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

wurzel = Path(SPECPATH).parent
windows = sys.platform == "win32"

# Bilder, Icons, Demo-Datenbank: alle Nicht-Python-Dateien des Pakets (ohne Web-Oberfläche und Caches)
paket = wurzel / "dbstudio"
datas = [(str(f), str(f.parent.relative_to(wurzel))) for f in paket.rglob("*")
         if f.is_file() and f.suffix not in (".py", ".pyc") and "__pycache__" not in f.parts and "web" not in f.relative_to(paket).parts[:1]]
datas += collect_data_files("access_parser")
hidden = ["dbstudio." + f.stem for f in paket.glob("*.py") if f.stem != "__init__"] + \
         ["dbstudio.ui." + f.stem for f in (paket / "ui").glob("*.py") if f.stem != "__init__"]
hidden += collect_submodules("keyring.backends") + ["psycopg_binary", "psycopg_binary.pq", "psycopg_binary._psycopg", "pymysql", "pymssql", "duckdb", "openpyxl", "access_parser"]

# Qt-Module, die Pi DB Studio nicht braucht – spart über 300 MB
weg = ["tkinter", "PIL", "fastapi", "uvicorn", "starlette", "pytest", "pytestqt", "IPython",
       "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
       "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
       "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
       "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtLocation", "PySide6.QtPositioning",
       "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtDesigner",
       "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech"]

a = Analysis([str(wurzel / "packaging" / "start.py")], pathex=[str(wurzel)], datas=datas, hiddenimports=hidden,
             excludes=weg, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PiDBStudio", console=False, upx=False,
          icon=str(wurzel / "packaging" / "windows" / "pi-db-studio.ico") if windows else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PiDBStudio")
