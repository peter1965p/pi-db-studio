"""API-Tests der Web-Oberfläche (FastAPI-TestClient) gegen SQLite, DuckDB und – falls erreichbar – PostgreSQL."""

import io
import os

import pytest
from fastapi.testclient import TestClient

from dbstudio import treiber
from dbstudio.web.app import erstelle_app
from dbstudio.web.speicher import Speicher, neuer_schluessel

from .conftest import PG_DB, PG_HOST, PG_USER, _pg_passwort

PW = "ein-sehr-geheimes-pw"
K = {"X-Pi-Anfrage": "1"}


@pytest.fixture
def speicher(tmp_path):
    sp = Speicher(tmp_path / "web", neuer_schluessel())
    sp.benutzer_setzen("admin", PW)
    return sp


@pytest.fixture
def client(speicher):
    with TestClient(erstelle_app(speicher), base_url="https://testserver") as c:
        r = c.post("/api/anmelden", json={"benutzer": "admin", "passwort": PW}, headers=K)
        assert r.status_code == 200
        yield c


def _verbindung(art, tmp_path):
    if art == "sqlite":
        return {"name": "t", "art": "sqlite", "datei": str(tmp_path / "w.db")}, None, None
    if art == "duckdb":
        return {"name": "t", "art": "duckdb", "datei": str(tmp_path / "w.duckdb")}, None, None
    pw = _pg_passwort()
    if not pw:
        pytest.skip("Kein Passwort für die Postgres-Test-DB")
    cfg = {"name": "t", "art": "postgresql", "host": PG_HOST, "port": "5432", "datenbank": PG_DB, "benutzer": PG_USER,
           "sslmode": "require"}
    try:
        t = treiber.oeffne(cfg, pw)
    except treiber.DBFehler as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    schema = "w_" + os.urandom(4).hex()
    t.abfrage(f"CREATE SCHEMA {schema}")
    return cfg, pw, (t, schema)


@pytest.fixture(params=["sqlite", "duckdb", "postgresql"])
def verbunden(request, client, tmp_path):
    cfg, pw, pg = _verbindung(request.param, tmp_path)
    v = client.post("/api/verbindungen", json={**cfg, "passwort": pw}, headers=K).json()
    info = client.post(f"/api/v/{v['id']}/oeffnen", json={}, headers=K).json()
    schema = pg[1] if pg else info["schema"]
    client.post(f"/api/v/{v['id']}/schema", json={"schema": schema}, headers=K)
    sql = ("CREATE TABLE kunden (id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL);"
           "CREATE TABLE bestellungen (id INTEGER PRIMARY KEY, kunde_id INTEGER REFERENCES kunden(id), betrag INTEGER);"
           "INSERT INTO kunden VALUES (1, 'Anna'), (2, 'Ben');"
           "INSERT INTO bestellungen VALUES (10, 1, 5), (11, 1, 7), (12, 2, 9);")
    r = client.post(f"/api/v/{v['id']}/sql", json={"sql": sql, "schema": schema}, headers=K)
    assert r.status_code == 200, r.text
    yield client, v["id"], schema
    client.post(f"/api/v/{v['id']}/schliessen", json={}, headers=K)
    if pg:
        pg[0].abfrage(f"DROP SCHEMA {pg[1]} CASCADE")
        pg[0].schliessen()


# --- Anmeldung und Schutz ----------------------------------------------------------------------------------------------
def test_ohne_anmeldung_gesperrt(speicher):
    with TestClient(erstelle_app(speicher), base_url="https://testserver") as c:
        assert c.get("/api/verbindungen").status_code == 401
        assert c.post("/api/anmelden", json={"benutzer": "admin", "passwort": "falsch"}, headers=K).status_code == 401
        assert c.get("/api/gesundheit").json()["ok"] is True


def test_post_ohne_kennung_abgelehnt(client):
    assert client.post("/api/verbindungen", json={"art": "sqlite"}).status_code == 403


def test_cookie_sicher(speicher):
    with TestClient(erstelle_app(speicher), base_url="https://testserver") as c:
        r = c.post("/api/anmelden", json={"benutzer": "admin", "passwort": PW}, headers=K)
        kopf = r.headers["set-cookie"].lower()
        assert "httponly" in kopf and "secure" in kopf and "samesite=strict" in kopf


def test_rate_limit(speicher):
    with TestClient(erstelle_app(speicher), base_url="https://testserver") as c:
        codes = [c.post("/api/anmelden", json={"benutzer": "x", "passwort": "y"}, headers=K).status_code for _ in range(9)]
        assert codes[-1] == 429


def test_passwort_nie_an_browser(client, speicher, tmp_path):
    client.post("/api/verbindungen", json={"name": "pg", "art": "postgresql", "host": "h", "passwort": "geheim123"}, headers=K)
    text = client.get("/api/verbindungen").text
    assert "geheim123" not in text and '"hat_passwort":true' in text
    roh = (speicher.ordner / "verbindungen.json").read_text()
    assert "geheim123" not in roh
    vid = client.get("/api/verbindungen").json()[0]["id"]
    assert speicher.verbindung(vid)[1] == "geheim123"


def test_sicherheitskoepfe(client):
    r = client.get("/")
    assert r.status_code == 200 and "Pi DB Studio" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


# --- Datenbank ---------------------------------------------------------------------------------------------------------
def test_objekte_und_zeilen(verbunden):
    c, vid, schema = verbunden
    o = c.get(f"/api/v/{vid}/objekte", params={"schema": schema}).json()
    assert {"kunden", "bestellungen"} <= set(o["tabellen"])
    z = c.get(f"/api/v/{vid}/zeilen", params={"tabelle": "kunden", "schema": schema, "sortierung": "name", "richtung": "desc"}).json()
    assert z["gesamt"] == 2 and z["zeilen"][0][1] == "Ben" and z["bearbeitbar"] is True
    assert c.get(f"/api/v/{vid}/zeilen", params={"tabelle": "kunden", "schema": schema, "sortierung": "x; drop"}).status_code == 400
    assert c.get(f"/api/v/{vid}/zeilen", params={"tabelle": "kunden", "schema": schema, "filter": "1=1; DELETE FROM kunden"}).status_code == 400


def test_aenderungen_als_transaktion(verbunden):
    c, vid, schema = verbunden
    r = c.post(f"/api/v/{vid}/aenderungen", headers=K, json={"schema": schema, "tabelle": "kunden", "aenderungen": [
        {"art": "update", "pk": {"id": 1}, "werte": {"name": "Anna B."}},
        {"art": "insert", "werte": {"id": 3, "name": "Cem"}}]})
    assert r.status_code == 200, r.text
    namen = [z[1] for z in c.get(f"/api/v/{vid}/zeilen", params={"tabelle": "kunden", "schema": schema, "sortierung": "id"}).json()["zeilen"]]
    assert namen == ["Anna B.", "Ben", "Cem"]
    # Fehler mittendrin -> nichts übernommen
    r = c.post(f"/api/v/{vid}/aenderungen", headers=K, json={"schema": schema, "tabelle": "kunden", "aenderungen": [
        {"art": "update", "pk": {"id": 2}, "werte": {"name": "Benedikt"}},
        {"art": "update", "pk": {"id": 99}, "werte": {"name": "gibt es nicht"}}]})
    assert r.status_code == 400
    namen = [z[1] for z in c.get(f"/api/v/{vid}/zeilen", params={"tabelle": "kunden", "schema": schema, "sortierung": "id"}).json()["zeilen"]]
    assert namen[1] == "Ben"


def test_sql_rueckfrage_und_paging(verbunden):
    c, vid, schema = verbunden
    r = c.post(f"/api/v/{vid}/sql", json={"sql": "DELETE FROM bestellungen", "schema": schema}, headers=K)
    assert r.status_code == 409 and "WHERE" in r.json()["rueckfrage"][0]
    r = c.post(f"/api/v/{vid}/sql", json={"sql": "SELECT id FROM bestellungen ORDER BY id", "schema": schema, "limit": 2}, headers=K).json()
    assert r["zeilen"] == [[10], [11]] and r["mehr"] and r["handle"]
    w = c.post(f"/api/abfrage/{r['handle']}/weitere", json={"anzahl": 10}, headers=K).json()
    assert w["zeilen"] == [[12]] and w["mehr"] is False
    assert c.post(f"/api/v/{vid}/sql", json={"sql": "SELECT * FROM gibtsnicht", "schema": schema}, headers=K).status_code == 400


def test_schreibschutz(verbunden):
    c, vid, schema = verbunden
    v = next(x for x in c.get("/api/verbindungen").json() if x["id"] == vid)
    c.post("/api/verbindungen", json={**v, "schreibschutz": True}, headers=K)
    c.post(f"/api/v/{vid}/oeffnen", json={}, headers=K)
    assert c.post(f"/api/v/{vid}/sql", json={"sql": "UPDATE kunden SET name='x' WHERE id=1", "schema": schema}, headers=K).status_code == 403
    assert c.post(f"/api/v/{vid}/aenderungen", headers=K, json={"schema": schema, "tabelle": "kunden",
                  "aenderungen": [{"art": "delete", "pk": {"id": 1}}]}).status_code == 403
    assert c.post(f"/api/v/{vid}/sql", json={"sql": "SELECT 1", "schema": schema}, headers=K).status_code == 200


def test_erm_ddl_und_efcore(verbunden):
    c, vid, schema = verbunden
    m = c.get(f"/api/v/{vid}/erm", params={"schema": schema}).json()
    namen = {t["name"] for t in m["tabellen"]}
    assert {"kunden", "bestellungen"} <= namen
    if m["fks"]:  # DuckDB/SQLite/PG liefern den FK
        f = m["fks"][0]
        assert f["ziel"] == "kunden" and f["art"] == "1:n" and f["abhaengig"] == "*"
        assert "Kunde" in f["worte"]
    ef = next(t for t in m["tabellen"] if t["name"] == "kunden")
    assert ef["klasse"] == "Kunde"
    assert set(m["positionen"]) == namen
    r = c.post(f"/api/v/{vid}/erm/ddl", headers=K, json={"aktion": "tabelle", "schema": schema, "tabelle": "lieferanten",
               "spalten": [{"name": "id", "typ": "grosse_ganzzahl", "pk": True, "nullbar": False}, {"name": "firma", "typ": "text"}]}).json()
    assert "CREATE TABLE" in r["anweisungen"][0]
    assert c.post(f"/api/v/{vid}/erm/ausfuehren", headers=K, json={"anweisungen": r["anweisungen"]}).status_code == 200
    assert "lieferanten" in c.get(f"/api/v/{vid}/objekte", params={"schema": schema}).json()["tabellen"]
    cs = c.get(f"/api/v/{vid}/dbcontext", params={"schema": schema}).text
    assert "class Kunde" in cs and "DbContext" in cs


def test_export_import(verbunden, tmp_path):
    c, vid, schema = verbunden
    r = c.get(f"/api/v/{vid}/export", params={"tabelle": "kunden", "schema": schema, "format": "csv"})
    assert r.status_code == 200 and "Anna" in r.text
    assert c.get(f"/api/v/{vid}/export", params={"sql": "DELETE FROM kunden", "format": "csv"}).status_code == 400
    csv = b"code,titel\nA,Eins\nB,Zwei\n"
    v = c.post(f"/api/v/{vid}/import", headers=K, data={"tabelle": "neu_import", "schema": schema, "neu": "true", "nur_vorschau": "true"},
               files={"datei": ("x.csv", io.BytesIO(csv), "text/csv")}).json()
    assert v["spalten"] == ["code", "titel"]
    r = c.post(f"/api/v/{vid}/import", headers=K, data={"tabelle": "neu_import", "schema": schema, "neu": "true"},
               files={"datei": ("x.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 200 and r.json()["zeilen"] == 2


def test_vorschlaege(verbunden):
    c, vid, schema = verbunden
    c.post(f"/api/v/{vid}/sql", headers=K, json={"sql": "CREATE TABLE notizen (id INTEGER PRIMARY KEY, kunden_id INTEGER, text VARCHAR(20))", "schema": schema})
    v = c.get(f"/api/v/{vid}/erm/vorschlaege", params={"schema": schema}).json()
    assert any(x["tabelle"] == "notizen" and x["ziel"] == "kunden" for x in v)
