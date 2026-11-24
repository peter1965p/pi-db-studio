"""REST-API mit Berechtigungen: Schlüssel, Regeln, Filter, gesperrte Spalten, Zeilenfilter, Schreibschutz, Injection."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from dbstudio.web.app import erstelle_app
from dbstudio.web.speicher import Speicher, neuer_schluessel

PW = "ein-sehr-geheimes-pw"
K = {"X-Pi-Anfrage": "1"}


@pytest.fixture
def umgebung(tmp_path):
    datei = tmp_path / "r.db"
    conn = sqlite3.connect(datei)
    conn.executescript("""
        CREATE TABLE kunden (id INTEGER PRIMARY KEY, name TEXT NOT NULL, ort TEXT, mandant INTEGER, passwort TEXT);
        INSERT INTO kunden VALUES (1, 'Anna', 'Osnabrück', 1, 'x1'), (2, 'Bert', 'Köln', 1, 'x2'),
                                  (3, 'Cora', 'Osnabrück', 2, 'x3');
        CREATE TABLE geheim (id INTEGER PRIMARY KEY, wert TEXT);
    """)
    conn.commit()
    conn.close()
    sp = Speicher(tmp_path / "web", neuer_schluessel())
    sp.benutzer_setzen("admin", PW)
    with TestClient(erstelle_app(sp), base_url="https://testserver") as c:
        assert c.post("/api/anmelden", json={"benutzer": "admin", "passwort": PW}, headers=K).status_code == 200
        v = c.post("/api/verbindungen", json={"name": "t", "art": "sqlite", "datei": str(datei)}, headers=K).json()
        yield c, v["id"]


def _schluessel(c, regeln, **mehr):
    r = c.post("/api/rest/schluessel", json={"name": "test", "regeln": regeln, **mehr}, headers=K)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["geheim"]}, r.json()["schluessel"]


def test_ohne_schluessel_kein_zugriff(umgebung):
    c, vid = umgebung
    assert c.get(f"/rest/v1/{vid}/kunden").status_code == 401
    assert c.get(f"/rest/v1/{vid}/kunden", headers={"Authorization": "Bearer pi_falsch"}).status_code == 401


def test_schluessel_nur_einmal_sichtbar(umgebung):
    c, vid = umgebung
    _, eintrag = _schluessel(c, [{"verbindung": vid, "tabelle": "kunden", "rolle": "leser"}])
    liste = c.get("/api/rest/schluessel").json()["schluessel"]
    assert eintrag["id"] in [s["id"] for s in liste]
    assert all("hash" not in s and "geheim" not in s for s in liste)


def test_lesen_filter_sortierung_spalten(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "kunden", "rolle": "leser", "spalten_gesperrt": ["passwort"]}])
    r = c.get(f"/rest/v1/{vid}/kunden?ort=eq.Osnabrück&order=name.desc", headers=h)
    assert r.status_code == 200
    assert [z["name"] for z in r.json()["daten"]] == ["Cora", "Anna"]
    assert all("passwort" not in z for z in r.json()["daten"])
    assert c.get(f"/rest/v1/{vid}/kunden?select=passwort", headers=h).status_code == 400
    assert c.get(f"/rest/v1/{vid}/kunden?passwort=eq.x1", headers=h).status_code == 400
    assert c.get(f"/rest/v1/{vid}/kunden/2", headers=h).json()["name"] == "Bert"


def test_andere_tabelle_und_schreiben_verboten(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "kunden", "rolle": "leser"}])
    assert c.get(f"/rest/v1/{vid}/geheim", headers=h).status_code == 403
    assert c.post(f"/rest/v1/{vid}/kunden", json={"id": 9, "name": "X"}, headers=h).status_code == 403
    assert c.delete(f"/rest/v1/{vid}/kunden/1", headers=h).status_code == 403


def test_zeilenfilter_gilt_fuer_alles(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "kunden", "rolle": "admin", "zeilenfilter": {"mandant": 1}}])
    assert {z["name"] for z in c.get(f"/rest/v1/{vid}/kunden", headers=h).json()["daten"]} == {"Anna", "Bert"}
    assert c.get(f"/rest/v1/{vid}/kunden/3", headers=h).status_code == 404  # fremder Mandant
    assert c.patch(f"/rest/v1/{vid}/kunden/3", json={"name": "Hack"}, headers=h).status_code == 404
    assert c.delete(f"/rest/v1/{vid}/kunden/3", headers=h).status_code == 404
    assert c.post(f"/rest/v1/{vid}/kunden", json={"id": 4, "name": "Dora", "mandant": 2}, headers=h).status_code == 403
    assert c.post(f"/rest/v1/{vid}/kunden", json={"id": 4, "name": "Dora"}, headers=h).status_code == 201
    assert c.get(f"/rest/v1/{vid}/kunden/4", headers=h).json()["mandant"] == 1  # erzwungen


def test_anlegen_aendern_loeschen_und_protokoll(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "*", "rolle": "admin"}])
    assert c.post(f"/rest/v1/{vid}/kunden", json={"id": 7, "name": "Emil"}, headers=h).status_code == 201
    assert c.patch(f"/rest/v1/{vid}/kunden/7", json={"ort": "Bremen"}, headers=h).json()["betroffen"] == 1
    assert c.get(f"/rest/v1/{vid}/kunden/7", headers=h).json()["ort"] == "Bremen"
    assert c.patch(f"/rest/v1/{vid}/kunden/7", json={"id": 8}, headers=h).status_code == 400
    assert c.delete(f"/rest/v1/{vid}/kunden/7", headers=h).status_code == 200
    aktionen = [p.get("aktion") for p in c.get("/api/rest/protokoll").json()]
    assert {"anlegen", "aendern", "loeschen"} <= set(aktionen)


def test_injection_ueber_namen_und_operatoren(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "*", "rolle": "leser"}])
    assert c.get(f"/rest/v1/{vid}/kunden;DROP TABLE kunden", headers=h).status_code in (403, 404)
    assert c.get(f"/rest/v1/{vid}/kunden?order=name;DROP", headers=h).status_code == 400
    assert c.get(f"/rest/v1/{vid}/kunden?name=or.1=1", headers=h).status_code == 400
    r = c.get(f"/rest/v1/{vid}/kunden?name=eq.' OR '1'='1", headers=h)
    assert r.status_code == 200 and r.json()["daten"] == []  # Wert ist nur ein Wert
    assert len(c.get(f"/rest/v1/{vid}/kunden", headers=h).json()["daten"]) == 3


def test_schreibschutz_und_rate_limit(umgebung, tmp_path):
    c, vid = umgebung
    v = c.get("/api/verbindungen").json()[0]
    c.post("/api/verbindungen", json={**{k: v[k] for k in ("id", "name", "art", "datei")}, "schreibschutz": True}, headers=K)
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "*", "rolle": "admin"}], limit_minute=3)
    assert c.post(f"/rest/v1/{vid}/kunden", json={"id": 9, "name": "Z"}, headers=h).status_code == 403
    codes = [c.get(f"/rest/v1/{vid}/kunden", headers=h).status_code for _ in range(4)]
    assert 429 in codes


def test_openapi_nur_erlaubte_tabellen(umgebung):
    c, vid = umgebung
    h, _ = _schluessel(c, [{"verbindung": vid, "tabelle": "kunden", "rolle": "leser", "spalten_gesperrt": ["passwort"]}])
    doc = c.get("/rest/v1/openapi.json", headers=h).json()
    assert list(doc["paths"]) == [f"/rest/v1/{vid}/kunden", f"/rest/v1/{vid}/kunden/{{pk}}"]
    assert "post" not in doc["paths"][f"/rest/v1/{vid}/kunden"]
    assert c.get("/rest/v1/openapi.json").status_code == 401


def test_ungueltige_regel_abgelehnt(umgebung):
    c, vid = umgebung
    r = c.post("/api/rest/schluessel", json={"name": "x", "regeln": [{"verbindung": vid, "aktionen": ["drop"]}]}, headers=K)
    assert r.status_code == 400
