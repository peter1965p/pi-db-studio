"""0.2.1: Schema-Automatik, Arbeitsschema, EF-Core-Abbildung (SQL Server über Metadaten-Attrappe)."""

import pytest

from dbstudio import efcore, erm
from dbstudio.treiber import Spalte


# --- Schema-Automatik ---------------------------------------------------------------------------------------------
def test_bestes_schema_logik_ohne_server():
    class Attrappe:
        standard_schema = staticmethod(lambda: "public")
    from dbstudio.treiber import Treiber
    t = Treiber()
    t.standard_schema = lambda: "public"
    zahlen = {"public": 0, "js_abc": 15, "leer": 0, "andere": 3}
    assert t.bestes_schema(None, zahlen) == ("js_abc", "„public“ ist leer – zeige Schema „js_abc“.")
    assert t.bestes_schema("andere", zahlen) == ("andere", "")       # gemerkt gewinnt
    assert t.bestes_schema("weg", zahlen)[0] == "js_abc"             # gemerkt existiert nicht mehr
    assert t.bestes_schema(None, {"public": 2, "x": 9}) == ("public", "")  # Standard mit Tabellen bleibt
    assert t.bestes_schema(None, {"public": 0, "x": 0}) == ("public", "")  # alles leer


def test_duckdb_leeres_main_waehlt_schema_und_setzt_arbeitsschema(tmp_path):
    from dbstudio import treiber
    t = treiber.oeffne({"art": "duckdb", "datei": str(tmp_path / "d.duckdb")})
    t.abfrage("CREATE SCHEMA app")
    t.abfrage("CREATE TABLE app.kunden (id INTEGER PRIMARY KEY, name VARCHAR)")
    t.abfrage("INSERT INTO app.kunden VALUES (1, 'A')")
    zahlen = t.tabellen_zahlen()
    assert zahlen["app"] == 1 and zahlen["main"] == 0
    schema, hinweis = t.bestes_schema(None, zahlen)
    assert schema == "app" and "main" in hinweis
    t.setze_schema(schema)
    assert t.abfrage("SELECT name FROM kunden").zeilen == [("A",)]   # unqualifiziert
    t.schliessen()


def test_postgres_search_path(db):
    if db.art != "postgresql":
        pytest.skip("nur PostgreSQL")
    s = db._test_schema
    db.abfrage(f"CREATE TABLE {s}.firmen (id bigint PRIMARY KEY, name text)")
    zahlen = db.tabellen_zahlen()
    assert zahlen[s] == 1
    db.abfrage("SET search_path TO public")
    db.setze_schema(s)
    assert db.abfrage("SELECT count(*) FROM firmen").zeilen == [(0,)]
    assert db.aktuelles_schema == s


# --- EF Core --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tabelle,klasse", [
    ("firmen", "Firma"), ("entwuerfe", "Entwurf"), ("fakten", "Fakt"), ("dokumente", "Dokument"),
    ("ereignisse", "Ereignis"), ("berichte", "Bericht"), ("regeln", "Regel"), ("cv_stationen", "CvStation"),
    ("kunden", "Kunde"), ("bestellungen", "Bestellung"), ("artikel", "Artikel"), ("OrderItems", "OrderItem"),
    ("categories", "Category"), ("schlagworte", "Schlagwort"), ("firmen_schlagworte", "FirmenSchlagwort"), ("person", "Person"), ("nacht_gesehen", "NachtGesehen"), ("einstellungen", "Einstellung"),
])
def test_klassenname(tabelle, klasse):
    assert efcore.klassenname(tabelle) == klasse


@pytest.mark.parametrize("typ,nullbar,pk,cs", [
    ("int", False, True, "int"), ("bigint", True, False, "long?"), ("nvarchar(200)", False, False, "string"),
    ("nvarchar(max)", True, False, "string?"), ("bit", False, False, "bool"), ("datetime2", True, False, "DateTime?"),
    ("datetimeoffset", False, False, "DateTimeOffset"), ("decimal(18,2)", False, False, "decimal"),
    ("uniqueidentifier", False, False, "Guid"), ("varbinary(max)", True, False, "byte[]?"), ("date", False, False, "DateOnly"),
    ("smallint", False, False, "short"), ("float", False, False, "double"), ("real", False, False, "float"),
])
def test_cs_typ(typ, nullbar, pk, cs):
    assert efcore.cs_typ(Spalte(name="x", typ=typ, nullbar=nullbar, pk=pk)) == cs


def _mssql_modell() -> erm.Modell:
    """Metadaten-Attrappe wie aus einem SQL Server (dbo) gelesen – ohne Server."""
    m = erm.Modell(art="mssql", schema="dbo")
    m.tabellen["firmen"] = erm.Tabelle("firmen", [Spalte("id", "int", False, True), Spalte("name", "nvarchar(200)", False, False)],
                                       [("id",)])
    m.tabellen["entwuerfe"] = erm.Tabelle("entwuerfe", [Spalte("id", "int", False, True), Spalte("firma_id", "int", False, False),
                                                        Spalte("betreff", "nvarchar(max)", True, False)], [("id",)])
    m.tabellen["notizen"] = erm.Tabelle("notizen", [Spalte("id", "int", False, True), Spalte("firma_id", "int", True, False)], [("id",)])
    m.fks.append(erm.Fremdschluessel("entwuerfe", ["firma_id"], "firmen", ["id"], bei_loeschen="CASCADE"))
    m.fks.append(erm.Fremdschluessel("notizen", ["firma_id"], "firmen", ["id"], bei_loeschen="SET NULL"))
    return m


def test_navigationen_und_multiplizitaet():
    m = _mssql_modell()
    nav = efcore.navigationen(m)
    assert ("Firma", "Firma", False) in nav["entwuerfe"]
    assert ("Firma", "Firma?", False) in nav["notizen"]
    assert ("Entwuerfe", "ICollection<Entwurf>", True) in nav["firmen"]
    assert ("Notizen", "ICollection<Notiz>", True) in nav["firmen"]
    assert efcore.multiplizitaet(m, m.fks[0]) == ("1", "*")
    assert efcore.multiplizitaet(m, m.fks[1]) == ("0..1", "*")


def test_dbcontext_code():
    code = efcore.dbcontext(_mssql_modell(), context="ShopDbContext")
    assert "public class Firma" in code and "public class Entwurf" in code
    assert "public virtual ICollection<Entwurf> Entwuerfe { get; set; } = new List<Entwurf>();" in code
    assert "public string? Betreff { get; set; }" in code
    assert 'e.ToTable("firmen", "dbo");' in code
    assert "HasOne(x => x.Firma).WithMany(x => x.Entwuerfe).HasForeignKey(x => x.FirmaId).OnDelete(DeleteBehavior.Cascade);" in code
    assert ".OnDelete(DeleteBehavior.SetNull)" in code
    assert 'e.Property(x => x.FirmaId).HasColumnName("firma_id");' in code
    assert code.count("{") == code.count("}")


def test_diagramm_ef_stil(qtbot):
    from dbstudio.ui.seite_diagramm import BeziehungsLinie, TabellenKarte
    m = _mssql_modell()
    navs = efcore.navigationen(m)
    k = TabellenKarte(m.tabellen["firmen"], set(), False, "alle", "ef", "dbo", navs["firmen"])
    arten = [z[0] for z in k.zeilen()]
    assert arten[0] == "abschnitt" and "nav" in arten and arten.count("abschnitt") == 2
    kind = TabellenKarte(m.tabellen["entwuerfe"], {"firma_id"}, False, "alle", "ef", "dbo", navs["entwuerfe"])
    kind.setPos(400, 0)
    lin = BeziehungsLinie(m.fks[0], kind, k, m.kardinalitaet(m.fks[0]), stil="ef", ef_mult=efcore.multiplizitaet(m, m.fks[0]))
    assert [t for _, t in lin._plaketten] == ["1", "*"]
    assert "Eine Firma hat viele Entwuerfe" in lin.tooltip()
