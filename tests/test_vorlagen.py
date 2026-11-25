"""Vorlagen-Engine: alle Vorlagen in allen Dialekten anlegen, KI-Antworten prüfen und bereinigen."""
import json

import pytest

from dbstudio import vorlagen

from .conftest import schema_von


@pytest.mark.parametrize("schluessel", sorted(vorlagen.VORLAGEN))
def test_vorlagen_laufen_in_jedem_dialekt(db, schluessel):
    m = vorlagen.vorlage(schluessel)
    anweisungen = vorlagen.ddl(m, db.art)
    vorher = set(db.objekte(schema_von(db))["tabellen"])
    try:
        vorlagen.einspielen(db, anweisungen)
        neu = set(db.objekte(schema_von(db))["tabellen"]) - vorher
        assert {t["name"] for t in m.tabellen} <= {n.lower() for n in neu}
        for tn, zeilen in m.daten.items():
            assert db.abfrage(f"SELECT count(*) FROM {db.zitiere(tn)}").zeilen[0][0] == len(zeilen)
    finally:
        if db.art in ("mysql",):
            db.abfrage("SET FOREIGN_KEY_CHECKS = 0")
        for t in reversed(vorlagen._reihenfolge(m)[0]):
            try:
                db.abfrage(f"DROP TABLE IF EXISTS {db.zitiere(t['name'])}" + (" CASCADE" if db.art == "postgresql" else ""))
            except Exception:
                pass
        if db.art == "mysql":
            db.abfrage("SET FOREIGN_KEY_CHECKS = 1")
        if db.art == "duckdb":
            for t in m.tabellen:
                db.abfrage(f"DROP SEQUENCE IF EXISTS seq_{t['name']}")


def test_kaskade_und_identity_nach_beispieldaten(tmp_path):
    from dbstudio import treiber
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "s.db")})
    m = vorlagen.vorlage("shop")
    vorlagen.einspielen(t, vorlagen.ddl(m, "sqlite"))
    t.abfrage("INSERT INTO bestellungen (kunde_id) VALUES (1)")
    bid = t.abfrage("SELECT max(id) FROM bestellungen").zeilen[0][0]
    t.abfrage(f"INSERT INTO bestellpositionen (bestellung_id, produkt_id, einzelpreis) VALUES ({bid}, 1, 29.9)")
    t.abfrage(f"DELETE FROM bestellungen WHERE id = {bid}")
    assert t.abfrage("SELECT count(*) FROM bestellpositionen").zeilen[0][0] == 0          # ON DELETE CASCADE
    t.abfrage("INSERT INTO produkte (sku, name, preis) VALUES ('X-1', 'Neu', 1)")          # id nach den Beispieldaten
    assert t.abfrage("SELECT max(id) FROM produkte").zeilen[0][0] == 3
    t.schliessen()


def test_ki_antwort_wird_geprueft_und_bereinigt():
    antwort = "Hier dein Modell:\n```json\n" + json.dumps({
        "name": "Fahrradverleih", "tabellen": [
            {"name": "Kunden", "spalten": [{"name": "Name", "typ": "text", "pflicht": True}, {"name": "Größe", "typ": "varchar"}]},
            {"name": "räder", "spalten": [{"name": "id", "typ": "ganzzahl", "pk": True, "auto": True}, {"name": "rahmennummer", "typ": "text", "eindeutig": True}]},
            {"name": "buchungen", "spalten": [{"name": "kunde_id", "verweis": "kunden"}, {"name": "rad_id", "verweis": "raeder", "kaskade": True},
                                               {"name": "lager_id", "verweis": "lager"}, {"name": "von", "typ": "zeitstempel", "standard": "jetzt"}]},
            {"name": "kunden", "spalten": []}],
        "daten": {"kunden": [{"id": 1, "name": "Anna", "geheim; DROP": "x"}], "gibtsnicht": [{"a": 1}]}}) + "\n```"
    m, hinweise = vorlagen.aus_ki_antwort(antwort)
    assert [t["name"] for t in m.tabellen] == ["kunden", "raeder", "buchungen"]
    kunden = m.tabellen[0]
    assert kunden["spalten"][0]["name"] == "id" and kunden["spalten"][0]["pk"]              # Schlüssel ergänzt
    assert [s["name"] for s in kunden["spalten"]] == ["id", "name", "groesse"]
    assert any("varchar" in h for h in hinweise) and any("lager" in h for h in hinweise)
    b = {s["name"]: s for s in m.tabellen[2]["spalten"]}
    assert b["rad_id"]["verweis"] == "raeder" and b["rad_id"]["kaskade"] and "verweis" not in b["lager_id"]
    assert m.daten == {"kunden": [{"id": 1, "name": "Anna"}]}
    with pytest.raises(vorlagen.VorlagenFehler):
        vorlagen.aus_ki_antwort("kein json")
    assert "raeder" in vorlagen.uebersicht(m)


def test_zyklische_verweise_werden_nachgetragen():
    m = vorlagen.vorlage("personal")                     # abteilungen.leitung_id → mitarbeiter, mitarbeiter.abteilung_id → abteilungen
    sql = vorlagen.ddl(m, "postgresql")
    assert any(a.startswith('ALTER TABLE') and "FOREIGN KEY" in a for a in sql)


def test_dialog_vorschau_ki_und_ergebnis(qtbot, monkeypatch):
    from dbstudio import ki
    from dbstudio.ui import arbeiter
    from dbstudio import verbindungen
    from dbstudio.ui.dialog_vorlage import KI_EIGEN, VorlagenDialog
    verbindungen.setze_einstellungen({"ki_anbieter": "claude-code"})       # sonst fragt der Dialog „KI einrichten“
    d = VorlagenDialog(None, "postgresql", neu=True, rollen=["app"], benutzer="peter")
    qtbot.addWidget(d)
    d.vorlage.setCurrentIndex(d.vorlage.findData("shop"))
    assert "bestellpositionen" in d.ueber.toPlainText() and 'CREATE TABLE "kunden"' in d.sql.toPlainText()
    gesendet = {}

    def frage(anbieter, art, kontext, modell="", **w):
        gesendet.update(w)
        return '```json\n{"name": "Verleih", "tabellen": [{"name": "raeder", "spalten": [{"name": "rahmen", "typ": "text"}]}], "daten": {}}\n```'
    monkeypatch.setattr(ki, "frage", frage)
    d.vorlage.setCurrentIndex(d.vorlage.findData(KI_EIGEN))
    d.wunsch.setPlainText("Fahrradverleih")
    d.mit_ki()
    arbeiter.warte_alle(5000)
    qtbot.waitUntil(lambda: "raeder" in d.ueber.toPlainText(), timeout=5000)
    assert "Fahrradverleih" in gesendet["aufgabe"] and "Primärschlüssel id ergänzt" in d.ueber.toPlainText()
    d.name.setText("verleih")
    d.besitzer.setCurrentIndex(1)
    name, besitzer, anweisungen = d.ergebnis()
    assert name == "verleih" and besitzer == "app" and anweisungen[0].startswith('CREATE TABLE "raeder"')


def test_ohne_anbieter_wird_gefragt_und_gemerkt(qtbot, monkeypatch):
    from dbstudio import ki, verbindungen
    from dbstudio.ui import bausteine
    monkeypatch.setattr(ki, "claude_pfad", lambda: "/usr/bin/claude")
    monkeypatch.setattr(ki, "anbieter_liste", lambda: [("claude-api", "Claude (API)"), ("claude-code", "Abo"), ("ollama:x", "Lokal: x")])
    gesetzt = []
    monkeypatch.setattr(ki, "setze_api_schluessel", gesetzt.append)
    monkeypatch.setattr(ki, "api_schluessel", lambda: None)
    gezeigt = []

    def exec_(self):
        gezeigt.append(self)
        assert self.abo.isChecked() and self.lokal.isEnabled()          # Abo vorgewählt, wenn Claude Code da ist
        self.api.setChecked(True)
        self._ok()
        assert not self.result() and "API-Schlüssel" in self.fehler.text()   # ohne Schlüssel geht es nicht weiter
        self.schluessel.setText("sk-ant-test")
        self._ok()
        return self.result()
    monkeypatch.setattr(bausteine.KiWahlDialog, "exec", exec_)
    assert bausteine.ki_anbieter_klaeren(None) == ("claude-api", "")
    assert gesetzt == ["sk-ant-test"] and verbindungen.einstellungen()["ki_anbieter"] == "claude-api"
    assert bausteine.ki_anbieter_klaeren(None) == ("claude-api", "") and len(gezeigt) == 1     # nur einmal gefragt
