"""Screenshots der Web-Oberfläche mit erfundenen Demo-Daten (lokaler Server, headless Chromium über Playwright).

venv/bin/python docs/web_screenshots.py   ->  docs/web-*.png
"""

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from dbstudio.web.app import erstelle_app
from dbstudio.web.speicher import Speicher, neuer_schluessel

DOCS = Path(__file__).parent
PORT = 8771
PW = "demo-passwort-123"


def demo_db(pfad: Path):
    c = sqlite3.connect(pfad)
    c.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE kategorien (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE kunden (id INTEGER PRIMARY KEY, name TEXT NOT NULL, ort TEXT, email TEXT, seit DATE);
    CREATE TABLE artikel (id INTEGER PRIMARY KEY, kategorie_id INTEGER NOT NULL REFERENCES kategorien(id), name TEXT NOT NULL, preis NUMERIC NOT NULL);
    CREATE TABLE bestellungen (id INTEGER PRIMARY KEY, kunde_id INTEGER NOT NULL REFERENCES kunden(id), datum DATE NOT NULL, status TEXT NOT NULL);
    CREATE TABLE positionen (bestellung_id INTEGER NOT NULL REFERENCES bestellungen(id), artikel_id INTEGER NOT NULL REFERENCES artikel(id), menge INTEGER NOT NULL, PRIMARY KEY (bestellung_id, artikel_id));
    CREATE TABLE lieferanten (id INTEGER PRIMARY KEY, firma TEXT NOT NULL, land TEXT);
    CREATE TABLE einstellungen (schluessel TEXT PRIMARY KEY, wert TEXT);
    """)
    orte = ["Köln", "Münster", "Bielefeld", "Essen", "Bremen", "Dortmund"]
    namen = ["Anna Beispiel", "Ben Muster", "Clara Test", "David Demo", "Eva Probe", "Finn Fiktiv", "Greta Gedacht", "Hugo Hypothese"]
    c.executemany("INSERT INTO kategorien VALUES (?,?)", [(1, "Werkzeug"), (2, "Garten"), (3, "Elektronik")])
    c.executemany("INSERT INTO kunden VALUES (?,?,?,?,?)", [(i + 1, n, orte[i % 6], f"kunde{i + 1}@beispiel.example", f"2025-0{i % 9 + 1}-1{i % 9}") for i, n in enumerate(namen)])
    c.executemany("INSERT INTO artikel VALUES (?,?,?,?)", [(i + 1, i % 3 + 1, f"Artikel {i + 1}", round(4.9 + i * 3.7, 2)) for i in range(12)])
    c.executemany("INSERT INTO bestellungen VALUES (?,?,?,?)", [(i + 1, i % 8 + 1, f"2026-1{i % 2}-0{i % 9 + 1}", ["neu", "bezahlt", "versendet"][i % 3]) for i in range(30)])
    c.executemany("INSERT INTO positionen VALUES (?,?,?)", [(i % 30 + 1, i % 12 + 1, i % 4 + 1) for i in range(60)])
    c.commit()
    c.close()


def main():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "shop.db"
    demo_db(db)
    sp = Speicher(tmp / "web", neuer_schluessel())
    sp.benutzer_setzen("admin", PW)
    sp.verbindung_speichern({"name": "Demo-Shop", "art": "sqlite", "datei": str(db), "farbe": "#5aa0e6"})
    sp.verbindung_speichern({"name": "Kundenportal (produktiv)", "art": "postgresql", "host": "db.beispiel.example", "port": "5432",
                             "datenbank": "portal", "benutzer": "leser", "sslmode": "require", "farbe": "#e05252", "schreibschutz": True})
    server = uvicorn.Server(uvicorn.Config(erstelle_app(sp, cookie_secure=False), host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    with sync_playwright() as p:
        b = p.chromium.launch()
        s = b.new_page(viewport={"width": 1600, "height": 940}, device_scale_factor=1)
        s.goto(f"http://127.0.0.1:{PORT}/")
        s.wait_for_selector("#f-anmelden")
        s.screenshot(path=DOCS / "web-anmeldung.png")
        s.fill("input[name=benutzer]", "admin")
        s.fill("input[name=passwort]", PW)
        s.click("#f-anmelden button[type=submit]")
        s.wait_for_selector(".vkarte")
        s.screenshot(path=DOCS / "web-verbindungen.png")
        s.click("[data-verbinden]")
        s.wait_for_selector("#baum [data-tabelle]")
        s.click("#baum [data-tabelle='kunden']")
        s.wait_for_selector("#raster tbody tr")
        s.dblclick("#raster tbody tr:nth-child(2) td:nth-child(4)")
        s.keyboard.press("Control+A")
        s.keyboard.type("Paderborn")
        s.keyboard.press("Enter")
        s.screenshot(path=DOCS / "web-datenbank.png")
        s.click("#verwerfen")
        s.click("[data-ansicht=diagramm]")
        s.wait_for_selector(".erm-linie")
        time.sleep(0.4)
        s.click("#z-100")
        s.mouse.move(5, 5)
        time.sleep(0.2)
        s.screenshot(path=DOCS / "web-diagramm.png")
        s.evaluate("document.querySelector(\".erm-karte[data-t='bestellungen']\").dispatchEvent(new MouseEvent('mouseenter'))")
        time.sleep(0.2)
        s.screenshot(path=DOCS / "web-diagramm-hervorhebung.png")
        s.evaluate("document.querySelector(\".erm-karte[data-t='bestellungen']\").dispatchEvent(new MouseEvent('mouseleave'))")
        s.select_option("#erm-stil", "ef")
        time.sleep(0.3)
        s.screenshot(path=DOCS / "web-diagramm-efcore.png")
        s.click("[data-ansicht=editor]")
        s.wait_for_selector(".CodeMirror")
        s.evaluate("""() => document.querySelector('.CodeMirror').CodeMirror.setValue(
          "-- Umsatz je Kunde\\nSELECT k.name, k.ort, COUNT(DISTINCT b.id) AS bestellungen,\\n       SUM(p.menge * a.preis) AS umsatz\\nFROM kunden k\\nJOIN bestellungen b ON b.kunde_id = k.id\\nJOIN positionen p ON p.bestellung_id = b.id\\nJOIN artikel a ON a.id = p.artikel_id\\nGROUP BY k.id\\nORDER BY umsatz DESC;")""")
        s.click("#sql-los")
        s.wait_for_selector("#sql-ergebnis tbody tr")
        s.fill("#ki-text", "Welche Kunden haben seit drei Monaten nichts bestellt?")
        s.screenshot(path=DOCS / "web-editor.png")
        b.close()
    server.should_exit = True
    print("Screenshots:", ", ".join(sorted(x.name for x in DOCS.glob("web-*.png"))))


if __name__ == "__main__":
    main()
