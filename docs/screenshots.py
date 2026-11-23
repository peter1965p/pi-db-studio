"""Erzeugt die Screenshots in docs/ offscreen mit einer Demo-Datenbank (erfundene Daten).

Aufruf: QT_QPA_PLATFORM=offscreen venv/bin/python docs/screenshots.py
Die KI-Antwort kommt echt vom lokalen Ollama (qwen2.5-coder:7b), falls vorhanden.
"""

import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ZIEL = Path(__file__).parent
tmp = Path(tempfile.mkdtemp(prefix="dbstudio-shots-"))
os.environ["DB_STUDIO_CONFIG"] = str(tmp / "konfig")
sys.path.insert(0, str(ZIEL.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dbstudio import ki, treiber, verbindungen  # noqa: E402

random.seed(7)
demo = tmp / "shop-demo.duckdb"
t = treiber.oeffne({"art": "duckdb", "datei": str(demo)})
t.abfrage("CREATE TABLE kunden (id INTEGER PRIMARY KEY, firma VARCHAR NOT NULL, ort VARCHAR, seit DATE)")
t.abfrage("CREATE TABLE artikel (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, kategorie VARCHAR, preis DECIMAL(10,2))")
t.abfrage("CREATE TABLE bestellungen (id INTEGER PRIMARY KEY, kunde_id INTEGER, artikel_id INTEGER, menge INTEGER, datum DATE)")
orte = ["Köln", "Bonn", "Trier", "Koblenz", "Aachen", "Düsseldorf", "Essen", "Mainz"]
t.ausfuehren_viele("INSERT INTO kunden VALUES (?, ?, ?, ?)",
                   [(i, f"Beispiel {n} GmbH", random.choice(orte), f"20{random.randint(15, 26)}-0{random.randint(1, 9)}-1{random.randint(0, 9)}")
                    for i, n in enumerate(["Nord", "Süd", "Ost", "West", "Rhein", "Mosel", "Eifel", "Ruhr", "Lahn", "Sieg",
                                           "Ahr", "Erft", "Wupper", "Emscher", "Lippe", "Saar"], 1)])
art = [("Server-Rack 42 HE", "Hardware", 899.0), ("Switch 24 Port", "Netzwerk", 249.9), ("NVMe 2 TB", "Speicher", 139.0),
       ("USV 1500 VA", "Strom", 329.0), ("Patchkabel 2 m", "Netzwerk", 3.9), ("Mini-PC", "Hardware", 449.0),
       ("WLAN-Access-Point", "Netzwerk", 159.0), ("Backup-Lizenz", "Software", 89.0)]
t.ausfuehren_viele("INSERT INTO artikel VALUES (?, ?, ?, ?)", [(i, *a) for i, a in enumerate(art, 1)])
t.ausfuehren_viele("INSERT INTO bestellungen VALUES (?, ?, ?, ?, ?)",
                   [(i, random.randint(1, 16), random.randint(1, 8), random.randint(1, 20),
                     f"2026-{random.randint(1, 11):02d}-{random.randint(1, 28):02d}") for i in range(1, 1201)])
t.schliessen()

liste = [verbindungen.neu(name="Shop-Demo (DuckDB)", art="duckdb", datei=str(demo), farbe="#3ecf8e"),
         verbindungen.neu(name="Produktion", art="postgresql", host="db.beispiel.example", port="5432", datenbank="shop",
                          benutzer="leser", sslmode="verify-full", farbe="#e05252", schreibschutz=True),
         verbindungen.neu(name="Test-Umgebung", art="mysql", host="test.beispiel.example", port="3306", datenbank="shop",
                          benutzer="entwickler", farbe="#f5a623"),
         verbindungen.neu(name="Lokale Notizen", art="sqlite", datei="~/notizen.db", farbe="#5aa0e6")]
verbindungen.speichern(liste)
modelle = ki.ollama_modelle()
modell = next((m for m in ("qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "qwen2.5:3b") if m in modelle), "")
verbindungen.setze_einstellungen({"ki_anbieter": f"ollama:{modell}" if modell else "claude-api", "zeilenlimit": 1000})

app = QApplication(sys.argv)
from dbstudio.ui import arbeiter  # noqa: E402
from dbstudio.ui.fenster import Hauptfenster  # noqa: E402

f = Hauptfenster()
f.resize(1500, 900)
f.show()


def warte(bedingung, ms=60000):
    import time
    ende = time.time() + ms / 1000
    while time.time() < ende:
        app.processEvents()
        if bedingung():
            return True
        time.sleep(0.02)
    return False


def bild(name):
    for _ in range(20):
        app.processEvents()
    f.grab().save(str(ZIEL / name))
    print("gespeichert", name)


bild("verbindungen.png")
f.verbinden(liste[0])
warte(lambda: f.t is not None and f.explorer.baum.topLevelItemCount() > 0)
f.explorer.oeffnen("main", "bestellungen")
warte(lambda: f.explorer.modell.rowCount() > 0)
f.explorer.filter.setText("menge >= 5")
f.explorer._seite(0)
warte(lambda: "von" in f.explorer.seite_text.text() and "1.200" not in f.explorer.seite_text.text())
bild("datenbank.png")
ed = f.editor
ed.editor().setPlainText(
    "-- Umsatz je Kunde 2026\nSELECT k.firma, k.ort,\n       SUM(b.menge * a.preis) AS umsatz,\n       COUNT(*) AS bestellungen\n"
    "FROM bestellungen b\nJOIN kunden k ON k.id = b.kunde_id\nJOIN artikel a ON a.id = b.artikel_id\n"
    "WHERE b.datum >= DATE '2026-01-01'\nGROUP BY k.firma, k.ort\nORDER BY umsatz DESC;")
f.zeige(ed)
ed.ausfuehren()
warte(lambda: not ed.laeuft and ed.modell.rowCount() > 0)
ed.ki_frage.setPlainText("Welche drei Artikel bringen je Ort den meisten Umsatz?")
if modell:
    ed._ki("sql")
    warte(lambda: "Denke nach" not in ed.ki_antwort.toPlainText(), 600000)
bild("sql-editor.png")
arbeiter.warte_alle(5000)
QTimer.singleShot(0, app.quit)
f.close()
