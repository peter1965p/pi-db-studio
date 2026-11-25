"""Oberfläche offscreen: verbinden, Baum, Datenraster bearbeiten, SQL-Editor, Schutzabfragen, Import."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from dbstudio import austausch, treiber, verbindungen  # noqa: E402
from dbstudio.ui import arbeiter, bausteine, fenster as fenster_modul, seite_austausch, seite_editor, seite_explorer  # noqa: E402


@pytest.fixture
def fenster(qtbot, tmp_path, monkeypatch):
    import keyring
    monkeypatch.setattr(keyring, "get_password", lambda d, k: None)
    db = tmp_path / "demo.db"
    t = treiber.oeffne({"art": "sqlite", "datei": str(db)})
    t.abfrage("CREATE TABLE artikel (id INTEGER PRIMARY KEY, name TEXT NOT NULL, preis REAL)")
    t.ausfuehren_viele("INSERT INTO artikel VALUES (?, ?, ?)", [(i, f"Artikel {i}", i * 0.5) for i in range(1, 301)])
    t.abfrage("CREATE TABLE ohne_pk (a TEXT)")
    t.schliessen()
    v = verbindungen.neu(name="Demo", art="sqlite", datei=str(db))
    verbindungen.speichern([v])
    from dbstudio.ui.fenster import Hauptfenster
    f = Hauptfenster()
    qtbot.addWidget(f)
    f.v = v
    yield f
    arbeiter.warte_alle(5000)
    if f.t:
        f.t.schliessen()


def _verbinden(qtbot, f, **extra):
    f.verbinden(dict(f.v, **extra))
    qtbot.waitUntil(lambda: f.t is not None, timeout=15000)
    qtbot.waitUntil(lambda: f.explorer.baum.topLevelItemCount() > 0, timeout=15000)


def test_verbinden_und_baum(qtbot, fenster):
    _verbinden(qtbot, fenster)
    assert fenster.stapel.currentWidget() is fenster.explorer
    main = fenster.explorer.baum.topLevelItem(0)
    tabellen = main.child(0)
    assert tabellen.text(0).startswith("Tabellen")
    assert {tabellen.child(i).text(0) for i in range(tabellen.childCount())} == {"artikel", "ohne_pk"}
    fenster.explorer.suche.setText("ohne")
    sichtbar = [tabellen.child(i).text(0) for i in range(tabellen.childCount()) if not tabellen.child(i).isHidden()]
    assert sichtbar == ["ohne_pk"]


def test_datenraster_bearbeiten_und_uebernehmen(qtbot, fenster):
    _verbinden(qtbot, fenster)
    e = fenster.explorer
    e.oeffnen("main", "artikel")
    qtbot.waitUntil(lambda: e.modell.rowCount() == 200, timeout=15000)
    assert "von 300" in e.seite_text.text()
    m = e.modell
    assert m.setData(m.index(0, 1), "Geändert")
    r = m.zeile_neu()
    m.setData(m.index(r, 0), "999")
    m.setData(m.index(r, 1), "Neu")
    m.zeilen_loeschen([5])
    assert e.k_uebernehmen.isEnabled()
    e._uebernehmen()  # Rückfrage für das Löschen: siehe Monkeypatch unten nicht nötig – wir bestätigen direkt
    qtbot.waitUntil(lambda: "übernommen" in e.status.text() or not m.geaendert, timeout=15000)
    t = fenster.t
    assert t.abfrage("SELECT name FROM artikel WHERE id = 1").zeilen[0][0] == "Geändert"
    assert t.abfrage("SELECT name FROM artikel WHERE id = 999").zeilen[0][0] == "Neu"
    assert t.abfrage("SELECT COUNT(*) FROM artikel WHERE id = 6").zeilen[0][0] == 0


@pytest.fixture(autouse=True)
def immer_ja(monkeypatch):
    gefragt = []

    def ja(eltern, titel, text, ja="Ausführen"):
        gefragt.append(text)
        return True
    for modul in (bausteine, seite_explorer, seite_editor, seite_austausch, fenster_modul):
        monkeypatch.setattr(modul, "rueckfrage", ja)
    meldungen = []
    for modul in (seite_editor, seite_explorer, seite_austausch, fenster_modul):
        monkeypatch.setattr(modul, "meldung", lambda e, t, x, f=False: meldungen.append(x))
    return gefragt, meldungen


def test_ohne_primaerschluessel_nur_lesen(qtbot, fenster):
    _verbinden(qtbot, fenster)
    e = fenster.explorer
    e.oeffnen("main", "ohne_pk")
    qtbot.waitUntil(lambda: "Primärschlüssel" in e.status.text(), timeout=15000)
    assert e.modell.nur_lesen and not e.k_neu.isEnabled()


def test_sql_editor_ausfuehren_und_nachladen(qtbot, fenster, monkeypatch):
    monkeypatch.setattr(verbindungen, "einstellungen", lambda: {"zeilenlimit": 100})
    _verbinden(qtbot, fenster)
    ed = fenster.editor
    ed.editor().setPlainText("SELECT * FROM artikel ORDER BY id")
    ed.ausfuehren()
    qtbot.waitUntil(lambda: ed.modell.rowCount() == 100, timeout=15000)
    assert ed.k_mehr.isVisibleTo(ed)
    ed._mehr()
    qtbot.waitUntil(lambda: ed.modell.rowCount() == 300, timeout=15000)
    assert ed.modell.zeilen[150][0] == 151


def test_gefaehrliches_sql_fragt_nach(qtbot, fenster, immer_ja):
    gefragt, _ = immer_ja
    _verbinden(qtbot, fenster)
    ed = fenster.editor
    ed.editor().setPlainText("DELETE FROM artikel")
    ed.ausfuehren()
    qtbot.waitUntil(lambda: not ed.laeuft and "betroffen" in ed.meldungen.toPlainText(), timeout=15000)
    assert any("ohne WHERE" in g for g in gefragt)
    assert fenster.t.anzahl("main", "artikel") == 0


def test_ki_sql_aendernd_verlangt_bestaetigung(qtbot, fenster, immer_ja):
    gefragt, _ = immer_ja
    _verbinden(qtbot, fenster)
    ed = fenster.editor
    ed.ki_sql = "UPDATE artikel SET preis = 0 WHERE id = 1"
    ed._ki_uebernehmen()
    ed.ausfuehren()
    qtbot.waitUntil(lambda: not ed.laeuft and bool(ed.meldungen.toPlainText()), timeout=15000)
    assert any("KI-Assistenten" in g for g in gefragt)


def test_schreibschutz_sperrt(qtbot, fenster, immer_ja):
    _, meldungen = immer_ja
    _verbinden(qtbot, fenster, schreibschutz=True)
    ed = fenster.editor
    ed.editor().setPlainText("DROP TABLE artikel")
    ed.ausfuehren()
    assert meldungen and "schreibgeschützt" in meldungen[-1]
    assert "artikel" in fenster.t.objekte("main")["tabellen"]
    fenster.explorer.oeffnen("main", "artikel")
    qtbot.waitUntil(lambda: fenster.explorer.modell.rowCount() > 0, timeout=15000)
    assert fenster.explorer.modell.nur_lesen


def test_fehler_landet_in_meldungen(qtbot, fenster):
    _verbinden(qtbot, fenster)
    ed = fenster.editor
    ed.editor().setPlainText("SELECT * FROM nichts_da")
    ed.ausfuehren()
    qtbot.waitUntil(lambda: ed.letzter_fehler[1] != "", timeout=15000)
    assert "nichts_da" in ed.meldungen.toPlainText()


def test_import_seite(qtbot, fenster, tmp_path):
    _verbinden(qtbot, fenster)
    a = fenster.austausch
    pfad = tmp_path / "neu.csv"
    austausch.exportieren(pfad, ["Nr", "Bezeichnung"], [(1, "x"), (2, "y")])
    a.pfad = str(pfad)
    a._gelesen(austausch.lesen(pfad))
    qtbot.waitUntil(lambda: a.ziel_schema.currentText() == "main", timeout=15000)
    a.ziel_tabelle.setEditText("neu_import")
    a._ziel_gewechselt("neu_import")
    assert a.neu_anlegen.isChecked()
    a._importieren()
    qtbot.waitUntil(lambda: "importiert" in a.import_status.text(), timeout=15000)
    assert fenster.t.abfrage("SELECT bezeichnung FROM neu_import ORDER BY nr").zeilen == [("x",), ("y",)]


def test_thema_wechseln(qtbot, fenster):
    vorher = fenster.thema
    fenster._thema_wechseln()
    assert fenster.thema != vorher


# --- Start von außen (Visual Death Studio: „In DB Studio bearbeiten“) ---------------------------------------------------

def test_von_aussen_vorhandene_verbindung_wiederverwenden_und_tabelle_oeffnen(qtbot, fenster):
    v = fenster.oeffne_von_aussen({"art": "sqlite", "datei": fenster.v["datei"], "name": "aus VDS"}, "artikel")
    assert v["id"] == fenster.v["id"] and len(fenster.verbindungen.liste) == 1
    qtbot.waitUntil(lambda: fenster.explorer.modell.rowCount() == 200, timeout=15000)
    assert fenster.explorer.tabelle_name == "artikel"


def test_von_aussen_neue_verbindung_ohne_passwort_im_speicher(qtbot, fenster, tmp_path):
    neu = tmp_path / "andere.db"
    treiber.oeffne({"art": "sqlite", "datei": str(neu)}).schliessen()
    v = fenster.oeffne_von_aussen({"art": "sqlite", "datei": str(neu)})
    qtbot.waitUntil(lambda: fenster.t is not None, timeout=15000)
    assert v["name"] == "andere.db" and len(verbindungen.laden()) == 2
    assert "passwort" not in (verbindungen.ordner() / "verbindungen.json").read_text()


def test_von_aussen_server_ohne_passwort_zeigt_dialog(qtbot, fenster, monkeypatch):
    from dbstudio.ui import seite_verbindungen
    gezeigt = []
    monkeypatch.setattr(seite_verbindungen.VerbindungDialog, "exec", lambda self: gezeigt.append(self.v["host"]) or 0)
    assert fenster.oeffne_von_aussen({"art": "postgresql", "host": "db.local", "port": 5432, "datenbank": "shop", "benutzer": "app"}) is None
    assert gezeigt == ["db.local"]
    assert any(v.get("host") == "db.local" for v in verbindungen.laden())     # gemerkt, Passwort trägt man im Dialog ein


def test_startargumente_lehnen_passwort_ab():
    from dbstudio.__main__ import argumente
    a = argumente(["--verbindung", '{"art": "sqlite", "datei": "/x.db"}', "--tabelle", "Orders", "-platform", "offscreen"])
    assert a.verbindung["art"] == "sqlite" and a.tabelle == "Orders"
    with pytest.raises(SystemExit):
        argumente(["--verbindung", '{"art": "postgresql", "passwort": "geheim"}'])


def test_passwort_von_verbindung_mit_gleichem_server_und_benutzer(qtbot, monkeypatch):
    import keyring
    ablage = {}
    monkeypatch.setattr(keyring, "get_password", lambda d, k: ablage.get((d, k)))
    monkeypatch.setattr(keyring, "set_password", lambda d, k, w: ablage.__setitem__((d, k), w))
    alt = verbindungen.neu(name="Aether", art="postgresql", host="DB.local", port="", datenbank="aether", benutzer="dbstudio")
    ablage[("db-studio", verbindungen.schluessel(alt))] = "geheim-123"
    verbindungen.speichern([alt])
    neu = verbindungen.neu(art="postgresql", host="db.local", port="5432", datenbank="dbstudio_test", benutzer="dbstudio")
    assert verbindungen.passwort_gleiches_konto(neu) == "geheim-123"                    # Port 5432 = Standard, Host ohne Groß/klein
    assert verbindungen.passwort_gleiches_konto(dict(neu, benutzer="andere")) is None
    from dbstudio.ui.seite_verbindungen import VerbindungDialog
    d = VerbindungDialog(None, neu)
    qtbot.addWidget(d)
    assert d.passwort() == "geheim-123"
    d._speichern()
    assert ablage[("db-studio", verbindungen.schluessel(d.ergebnis))] == "geheim-123"     # eigene Kopie
