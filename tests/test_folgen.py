"""Folgen von Schlüssel- und Beziehungsänderungen: verwaiste Datensätze, auch ohne Constraints."""
import pytest

from dbstudio import erm, treiber
from dbstudio.treiber import Spalte


@pytest.fixture
def db(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "f.db")}, None)
    for sql in ("CREATE TABLE kunden (id INTEGER PRIMARY KEY, name TEXT)",
                "CREATE TABLE bestellungen (id INTEGER PRIMARY KEY, kunde_id INTEGER, notiz TEXT)",  # kein Constraint
                "INSERT INTO kunden VALUES (1, 'Anna'), (2, 'Bert')",
                "INSERT INTO bestellungen VALUES (10, 1, 'a'), (11, 2, NULL), (12, 7, 'b'), (13, 9, 'c'), (14, NULL, 'd')"):
        t.abfrage(sql)
    yield t, erm.lade(t, "main")
    t.schliessen()


def test_beziehung_ohne_constraint_wird_erkannt(db):
    t, m = db
    assert [(f.tabelle, f.ziel, echt) for f, echt in erm.beziehungen(m)] == [("bestellungen", "kunden", False)]


def test_neuer_fk_zeigt_verwaiste_mit_beispielen(db):
    t, m = db
    f = erm.Fremdschluessel("bestellungen", ["kunde_id"], "kunden", ["id"])
    folgen = erm.folgen_fk(t, m, f)
    assert folgen[0].stufe == "gefahr" and "2 Zeilen" in folgen[0].text and "7" in folgen[0].text and "9" in folgen[0].text


def test_neuer_fk_ohne_waisen_ist_nur_hinweis(db):
    t, m = db
    t.abfrage("DELETE FROM bestellungen WHERE kunde_id IN (7, 9)")
    f = erm.Fremdschluessel("bestellungen", ["kunde_id"], "kunden", ["id"])
    assert [x.stufe for x in erm.folgen_fk(t, m, f)] == ["hinweis"]


def test_pk_umbenennen_warnt_vor_beziehung_ohne_constraint(db):
    t, m = db
    folgen = erm.folgen_spalte(t, m, "kunden", "id", Spalte("kunden_nr", "INTEGER", True, True))
    gefahr = [f.text for f in folgen if f.stufe == "gefahr"]
    assert any("bestellungen.kunde_id" in x and "ohne Bezugspunkt" in x for x in gefahr)


def test_verweis_spalte_zeigt_bestehende_waisen(db):
    t, m = db
    folgen = erm.folgen_spalte(t, m, "bestellungen", "kunde_id", Spalte("kunde", "INTEGER", True, False))
    texte = " ".join(f.text for f in folgen)
    assert "Schon jetzt zeigen 2 Zeilen" in texte and "nicht mehr erkennen" in texte


def test_not_null_mit_leeren_werten(db):
    t, m = db
    folgen = erm.folgen_spalte(t, m, "bestellungen", "notiz", Spalte("notiz", "TEXT", False, False))
    assert folgen and folgen[0].stufe == "gefahr" and "1 Zeilen" in folgen[0].text


def test_tabelle_loeschen_warnt_vor_waisen_ohne_constraint(db):
    t, m = db
    folgen = erm.folgen_tabelle_loeschen(t, m, "kunden")
    texte = " ".join(f.text for f in folgen if f.stufe == "gefahr")
    assert "2 Zeilen" in texte and "4 Zeilen in bestellungen.kunde_id" in texte and "ins Leere" in texte
    assert erm.ddl_tabelle_loeschen(m, "kunden")[0].startswith("DROP TABLE")


def test_spalte_loeschen_pk_und_verweis(db):
    t, m = db
    folgen = erm.folgen_spalte_loeschen(t, m, "kunden", "id")
    assert any("Primärschlüssel" in f.text for f in folgen)
    assert any("4 Zeilen in bestellungen.kunde_id" in f.text and f.stufe == "gefahr" for f in folgen)


def test_spalte_loeschen_sqlite_per_neuaufbau(db):
    t, m = db
    anw = erm.ddl_spalte_loeschen(m, "bestellungen", "notiz")
    erm.ausfuehren(t, anw)
    assert [s.name for s in t.spalten("main", "bestellungen")] == ["id", "kunde_id"]
    assert t.anzahl("main", "bestellungen") == 5


def test_fk_loeschen_mit_echtem_fremdschluessel(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "g.db")}, None)
    t.abfrage("CREATE TABLE a (id INTEGER PRIMARY KEY)")
    t.abfrage("CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id))")
    t.abfrage("INSERT INTO a VALUES (1)")
    t.abfrage("INSERT INTO b VALUES (1, 1)")
    m = erm.lade(t, "main")
    f = m.fks[0]
    assert erm.folgen_fk_loeschen(t, m, f)[0].stufe == "gefahr"
    erm.ausfuehren(t, erm.ddl_fk_loeschen(m, f))
    assert erm.lade(t, "main").fks == []
    t.schliessen()


def test_letzte_spalte_nicht_loeschbar(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "h.db")}, None)
    t.abfrage("CREATE TABLE x (id INTEGER)")
    with pytest.raises(ValueError):
        erm.ddl_spalte_loeschen(erm.lade(t, "main"), "x", "id")
    t.schliessen()
