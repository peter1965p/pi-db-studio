"""Screenshots des Beziehungsdesigners (Datenbank- und EF-Core-Stil) mit erfundener Demo-Struktur.

Aufruf: QT_QPA_PLATFORM=offscreen venv/bin/python docs/diagramm_screenshot.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ZIEL = Path(__file__).parent
tmp = Path(tempfile.mkdtemp(prefix="dbstudio-er-"))
os.environ["DB_STUDIO_CONFIG"] = str(tmp / "konfig")
sys.path.insert(0, str(ZIEL.parent))

demo = tmp / "bewerbungen-demo.db"
c = sqlite3.connect(demo)
c.executescript("""
CREATE TABLE firmen (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sitz TEXT NOT NULL, website TEXT, email TEXT,
  passung TEXT, warum TEXT, quelle TEXT NOT NULL, seiten_geladen TEXT, score INTEGER, erstellt TEXT NOT NULL,
  status TEXT NOT NULL, notiz TEXT, branche TEXT);
CREATE TABLE dokumente (id INTEGER PRIMARY KEY, pfad TEXT NOT NULL, titel TEXT NOT NULL, art TEXT NOT NULL, eingelesen TEXT NOT NULL);
CREATE TABLE fakten (id INTEGER PRIMARY KEY, kategorie TEXT NOT NULL, text TEXT NOT NULL, quelle TEXT NOT NULL,
  dokument_id INTEGER REFERENCES dokumente(id) ON DELETE SET NULL, status TEXT NOT NULL, erstellt TEXT NOT NULL);
CREATE TABLE entwuerfe (id INTEGER PRIMARY KEY, firma_id INTEGER NOT NULL REFERENCES firmen(id) ON DELETE CASCADE,
  empfaenger TEXT NOT NULL, betreff TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, erstellt TEXT NOT NULL,
  gesendet_am TEXT);
CREATE TABLE chunks (id INTEGER PRIMARY KEY, firma_id INTEGER REFERENCES firmen(id) ON DELETE CASCADE,
  dokument_id INTEGER REFERENCES dokumente(id), fakt_id INTEGER REFERENCES fakten(id), text TEXT NOT NULL, quelle TEXT NOT NULL);
CREATE TABLE lektionen (id INTEGER PRIMARY KEY, entwurf_id INTEGER REFERENCES entwuerfe(id),
  firma_id INTEGER REFERENCES firmen(id), vorher TEXT NOT NULL, nachher TEXT NOT NULL, erstellt TEXT NOT NULL);
CREATE TABLE ereignisse (id INTEGER PRIMARY KEY, firma_id INTEGER REFERENCES firmen(id), zeit TEXT NOT NULL,
  aktion TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE schlagworte (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE firmen_schlagworte (firma_id INTEGER NOT NULL REFERENCES firmen(id) ON DELETE CASCADE,
  schlagwort_id INTEGER NOT NULL REFERENCES schlagworte(id), PRIMARY KEY (firma_id, schlagwort_id));
CREATE TABLE einstellungen (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE berichte (id INTEGER PRIMARY KEY, datum TEXT NOT NULL, inhalt TEXT NOT NULL);
CREATE TABLE cv_stationen (id INTEGER PRIMARY KEY, art TEXT NOT NULL, titel TEXT NOT NULL, organisation TEXT, von TEXT, bis TEXT);
CREATE TABLE regeln (id INTEGER PRIMARY KEY, art TEXT NOT NULL, wert TEXT NOT NULL);
CREATE TABLE wohnungen (kennung TEXT PRIMARY KEY, ort TEXT, kalt REAL, zimmer REAL, url TEXT NOT NULL);
""")
c.close()

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbstudio import verbindungen  # noqa: E402

v = verbindungen.neu(name="Bewerbungen-Demo", art="sqlite", datei=str(demo), farbe="#5aa0e6")
verbindungen.speichern([v])
app = QApplication(sys.argv)
from dbstudio.ui import arbeiter  # noqa: E402
from dbstudio.ui.fenster import Hauptfenster  # noqa: E402

f = Hauptfenster()
f.resize(1600, 960)
f.show()


def warte(bed, ms=30000):
    import time
    ende = time.time() + ms / 1000
    while time.time() < ende:
        app.processEvents()
        if bed():
            return True
        time.sleep(0.02)
    return False


def bild(name):
    for _ in range(30):
        app.processEvents()
    f.grab().save(str(ZIEL / name))
    print("gespeichert", name)


f.verbinden(v)
warte(lambda: f.t is not None)
d = f.diagramm
f.zeige(d)
warte(lambda: d.modell is not None and len(d.karten) > 5)
d.auto_anordnen()
bild("diagramm.png")
d.karten["firmen"].setSelected(True)
bild("diagramm-hervorhebung.png")
d.karten["firmen"].setSelected(False)
d.stil.setCurrentIndex(d.stil.findData("ef"))
d._stil_gewechselt()
warte(lambda: d.karten and d.karten["firmen"].stil == "ef")
bild("diagramm-efcore.png")
arbeiter.warte_alle(3000)
f.close()
