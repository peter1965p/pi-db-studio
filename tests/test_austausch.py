import datetime as dt
import json

import pytest

from dbstudio import austausch, treiber

from .conftest import schema_von

SPALTEN = ["id", "name", "betrag", "tag"]
ZEILEN = [(1, "Äpfel; rot", 1.5, dt.date(2026, 1, 2)), (2, 'Zitat "x"', None, dt.date(2026, 2, 3)), (3, "O'Brien", 3.25, None)]


@pytest.mark.parametrize("fmt", ["csv", "json", "xlsx"])
def test_export_und_wieder_einlesen(tmp_path, fmt):
    pfad = tmp_path / f"daten.{fmt}"
    assert austausch.exportieren(pfad, SPALTEN, iter(ZEILEN)) == 3
    spalten, zeilen = austausch.lesen(pfad)
    assert spalten == SPALTEN
    assert len(zeilen) == 3
    assert str(zeilen[0][1]) == "Äpfel; rot"
    assert zeilen[1][2] in (None, "")
    assert str(zeilen[2][1]) == "O'Brien"


def test_sql_export(tmp_path):
    pfad = tmp_path / "d.sql"
    austausch.exportieren(pfad, SPALTEN, ZEILEN, tabelle="obst")
    text = pfad.read_text()
    assert text.count("INSERT INTO \"obst\"") == 3
    assert "'O''Brien'" in text and "NULL" in text
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "s.db")})
    t.abfrage('CREATE TABLE obst (id INTEGER, name TEXT, betrag REAL, tag TEXT)')
    for anw in treiber.anweisungen(text):
        t.abfrage(anw)
    assert t.anzahl("main", "obst") == 3


def test_jsonl_lesen(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"a": 1, "b": {"x": 2}}\n{"a": 2, "c": "z"}\n')
    spalten, zeilen = austausch.lesen(p)
    assert spalten == ["a", "b", "c"]
    assert json.loads(zeilen[0][1]) == {"x": 2} and zeilen[1][2] == "z"


def test_typ_schaetzen():
    assert austausch.typ_schaetzen(["1", "2", None]) == "ganzzahl"
    assert austausch.typ_schaetzen(["1,5", "2"]) == "kommazahl"
    assert austausch.typ_schaetzen(["2026-01-02", "2025-12-31"]) == "datum"
    assert austausch.typ_schaetzen(["ja", "x"]) == "text"


def test_import_mit_zuordnung_und_neuer_tabelle(db, tmp_path):
    pfad = tmp_path / "in.csv"
    austausch.exportieren(pfad, SPALTEN, ZEILEN)
    spalten, zeilen = austausch.lesen(pfad)
    s = schema_von(db)
    ziel_schema = s if db.art == "postgresql" else None
    n = austausch.importieren(db, ziel_schema, "importiert", spalten, zeilen,
                              {"id": "nr", "name": "bezeichnung", "betrag": "", "tag": "tag"}, neu_anlegen=True)
    assert n == 3
    sp = [x.name for x in db.spalten(s, "importiert")]
    assert sp == ["nr", "bezeichnung", "tag"]
    erg = db.zeilen(s, "importiert", sortierung=db.zitiere("nr"))
    assert erg.zeilen[2][1] == "O'Brien" and erg.zeilen[0][0] == 1


def test_import_rollt_bei_fehler_zurueck(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "s.db")})
    t.abfrage("CREATE TABLE z (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    with pytest.raises(treiber.DBFehler):
        austausch.importieren(t, None, "z", ["id", "name"], [[1, "a"], [2, None]], {"id": "id", "name": "name"})
    assert t.anzahl("main", "z") == 0


def test_tabelle_kopieren_sqlite_nach_duckdb(tmp_path):
    q = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "q.db")})
    q.abfrage("CREATE TABLE artikel (id INTEGER PRIMARY KEY, name TEXT NOT NULL, preis REAL, anlage TEXT)")
    q.ausfuehren_viele("INSERT INTO artikel VALUES (?, ?, ?, ?)", [(i, f"A{i}", i / 10, "2026-01-01") for i in range(2500)])
    z = treiber.oeffne({"art": "duckdb", "datei": str(tmp_path / "z.duckdb")})
    assert austausch.tabelle_kopieren(q, "main", "artikel", z, None, "artikel", stapel=700) == 2500
    sp = {s.name: s for s in z.spalten("main", "artikel")}
    assert sp["id"].pk and sp["preis"].generisch == "kommazahl"
    assert z.anzahl("main", "artikel") == 2500
    with pytest.raises(ValueError):
        austausch.tabelle_kopieren(q, "main", "artikel", z, None, "artikel")
    assert austausch.tabelle_kopieren(q, "main", "artikel", z, None, "artikel", ersetzen=True) == 2500


def test_tabelle_kopieren_nach_postgres(tmp_path, db):
    if db.art != "postgresql":
        pytest.skip("nur Postgres-Ziel")
    q = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "q.db")})
    q.abfrage("CREATE TABLE t (id INTEGER PRIMARY KEY, aktiv BOOLEAN, wert REAL)")
    q.ausfuehren_viele("INSERT INTO t VALUES (?, ?, ?)", [(1, 1, 0.5), (2, 0, None)])
    assert austausch.tabelle_kopieren(q, "main", "t", db, db._test_schema, "t") == 2
    assert db.abfrage(f"SELECT aktiv FROM {db._test_schema}.t ORDER BY id").zeilen == [(True,), (False,)]
