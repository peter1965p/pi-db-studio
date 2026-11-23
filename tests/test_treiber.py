import threading
import time

import pytest

from dbstudio import treiber
from dbstudio.treiber import DBFehler, anweisungen, generischer_typ

from .conftest import schema_von


def _anlegen(t):
    s = schema_von(t)
    voll = t.voll(s if t.art == "postgresql" else None, "kunden")
    t.abfrage(f"CREATE TABLE {voll} (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, umsatz DOUBLE PRECISION, aktiv BOOLEAN)"
              if t.art != "sqlite" else f"CREATE TABLE {voll} (id INTEGER PRIMARY KEY, name TEXT NOT NULL, umsatz REAL, aktiv BOOLEAN)")
    sql = t.einfuegen_sql(s if t.art == "postgresql" else None, "kunden", ["id", "name", "umsatz", "aktiv"])
    t.ausfuehren_viele(sql, [(i, f"Firma {i}", i * 1.5, i % 2 == 0) for i in range(1, 251)])
    return s


def test_metadaten(db):
    s = _anlegen(db)
    db.abfrage(f"CREATE VIEW {db.voll(s if db.art == 'postgresql' else None, 'v_aktiv')} AS SELECT * FROM "
               f"{db.voll(s if db.art == 'postgresql' else None, 'kunden')} WHERE aktiv")
    db.abfrage(f"CREATE INDEX ix_name ON {db.voll(s if db.art == 'postgresql' else None, 'kunden')} (name)")
    assert s in db.schemas()
    o = db.objekte(s)
    assert "kunden" in o["tabellen"] and "v_aktiv" in o["views"]
    assert any("ix_name" in i for i in o["indizes"])
    sp = {x.name: x for x in db.spalten(s, "kunden")}
    assert list(sp) == ["id", "name", "umsatz", "aktiv"]
    assert sp["id"].pk and not sp["name"].nullbar
    assert sp["umsatz"].generisch == "kommazahl"


def test_seiten_sortieren_filtern(db):
    s = _anlegen(db)
    erg = db.zeilen(s, "kunden", offset=10, limit=20, sortierung=f"{db.zitiere('id')} DESC")
    assert len(erg.zeilen) == 20 and erg.zeilen[0][0] == 240
    assert db.anzahl(s, "kunden", f"{db.zitiere('umsatz')} > 300") == 50


def test_nachladen(db):
    _anlegen(db)
    s = schema_von(db)
    erg = db.abfrage(f"SELECT * FROM {db.voll(s if db.art == 'postgresql' else None, 'kunden')} ORDER BY 1", limit=100)
    assert len(erg.zeilen) == 100 and erg.mehr
    erg.weitere(100)
    erg.weitere(100)
    assert len(erg.zeilen) == 250 and not erg.mehr


def test_transaktion_zuruecknehmen(db):
    s = _anlegen(db)
    q = s if db.art == "postgresql" else None
    db.beginnen()
    db.abfrage(f"DELETE FROM {db.voll(q, 'kunden')} WHERE {db.zitiere('id')} <= 10")
    db.zuruecknehmen()
    assert db.anzahl(s, "kunden") == 250
    db.beginnen()
    db.abfrage(f"DELETE FROM {db.voll(q, 'kunden')} WHERE {db.zitiere('id')} <= 10")
    db.bestaetigen()
    assert db.anzahl(s, "kunden") == 240


def test_fehler_lesbar(db):
    with pytest.raises(DBFehler) as e:
        db.abfrage("SELECT * FROM gibt_es_nicht")
    assert "gibt_es_nicht" in str(e.value)
    assert db.abfrage("SELECT 1").zeilen[0][0] == 1  # Verbindung bleibt nutzbar


def test_explain(db):
    s = _anlegen(db)
    erg = db.explain(f"SELECT * FROM {db.voll(s if db.art == 'postgresql' else None, 'kunden')} WHERE {db.zitiere('id')} = 3")
    assert erg.zeilen


def test_abbrechen(db):
    if db.art == "postgresql":
        sql = "SELECT pg_sleep(20)"
    elif db.art == "duckdb":
        sql = "SELECT count(*) FROM range(10000000000) a"
    else:
        sql = "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT count(*) FROM r"
    fehler = []

    def lauf():
        try:
            db.abfrage(sql)
        except DBFehler as e:
            fehler.append(e)
    th = threading.Thread(target=lauf)
    start = time.time()
    th.start()
    time.sleep(1.0)
    db.abbrechen()
    th.join(15)
    assert not th.is_alive() and fehler and time.time() - start < 15


def test_anweisungen_teilen():
    skript = "SELECT 'a;b'; -- kommentar;\nSELECT \"x;y\" FROM t; /* ; */ CREATE FUNCTION f() AS $$ SELECT 1; $$; ;"
    teile = anweisungen(skript)
    assert len(teile) == 3
    assert teile[0] == "SELECT 'a;b'"
    assert "CREATE FUNCTION" in teile[2] and "$$ SELECT 1; $$" in teile[2]


def test_generische_typen():
    assert generischer_typ("character varying(20)") == "text"
    assert generischer_typ("BIGINT") == "grosse_ganzzahl"
    assert generischer_typ("numeric(10,2)") == "dezimal"
    assert generischer_typ("timestamp with time zone") == "zeitstempel"
    assert generischer_typ("bytea") == "binaer"
    assert generischer_typ("jsonb") == "json"


def test_unbekannte_art():
    with pytest.raises(DBFehler):
        treiber.oeffne({"art": "oracle"})
