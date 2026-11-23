"""Beziehungsdesigner: Fremdschlüssel lesen (SQLite/DuckDB/Postgres), Kardinalität, Layout, DDL je Dialekt, Diagramm-Aufbau."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from dbstudio import erm, treiber, verbindungen  # noqa: E402
from dbstudio.treiber import Spalte  # noqa: E402
from tests.conftest import schema_von  # noqa: E402

SHOP = [
    "CREATE TABLE kunden (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL)",
    "CREATE TABLE bestellungen (id INTEGER PRIMARY KEY, kunde_id INTEGER NOT NULL REFERENCES kunden(id), datum DATE)",
    "CREATE TABLE profile (kunde_id INTEGER PRIMARY KEY REFERENCES kunden(id), bio VARCHAR(200))",
    "CREATE TABLE artikel (id INTEGER PRIMARY KEY, titel VARCHAR(80))",
    "CREATE TABLE bestellpositionen (bestellung_id INTEGER REFERENCES bestellungen(id), "
    "artikel_id INTEGER REFERENCES artikel(id), menge INTEGER, PRIMARY KEY (bestellung_id, artikel_id))",
    "CREATE TABLE lieferungen (id INTEGER PRIMARY KEY, bestellungen_id INTEGER)",
]


def _shop(t):
    for s in SHOP:
        t.abfrage(s)
    return erm.lade(t, schema_von(t))


def test_fremdschluessel_und_kardinalitaet(db):
    m = _shop(db)
    assert set(m.tabellen) >= {"kunden", "bestellungen", "profile", "artikel", "bestellpositionen", "lieferungen"}
    paare = {(f.tabelle, tuple(f.spalten), f.ziel, tuple(f.ziel_spalten)) for f in m.fks}
    assert ("bestellungen", ("kunde_id",), "kunden", ("id",)) in paare
    assert ("bestellpositionen", ("artikel_id",), "artikel", ("id",)) in paare
    fk = {f.tabelle: f for f in m.fks if f.ziel == "kunden"}
    assert m.kardinalitaet(fk["bestellungen"]) == "1:n"
    assert m.kardinalitaet(fk["profile"]) == "1:1"
    assert m.zwischentabelle("bestellpositionen")
    assert not m.zwischentabelle("bestellungen")
    assert ("artikel", "bestellpositionen", "bestellungen") in m.n_zu_m()


def test_layout_und_positionen(db):
    m = _shop(db)
    e = erm.ebenen(m)
    assert e["kunden"] < e["bestellungen"] < e["bestellpositionen"]
    hoehe = lambda t: 40 + 22 * len(t.spalten)  # noqa: E731
    pos = erm.auto_layout(m, 260, hoehe=hoehe)
    assert set(pos) == set(m.tabellen)
    rechtecke = {n: (x, y, x + 260, y + hoehe(m.tabellen[n])) for n, (x, y) in pos.items()}
    namen = list(rechtecke)
    for i, a in enumerate(namen):  # keine Überlappungen
        for b in namen[i + 1:]:
            ax1, ay1, ax2, ay2 = rechtecke[a]
            bx1, by1, bx2, by2 = rechtecke[b]
            assert ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1, (a, b)
    erm.positionen_speichern("v1", "s", {"kunden": (10.0, 20.0)})
    assert erm.positionen_laden("v1", "s") == {"kunden": (10.0, 20.0)}
    assert erm.positionen_laden("v1", "anders") == {}


def test_vorschlag_per_namensregel(db):
    m = _shop(db)
    v = erm.vorschlaege(m)
    assert [(f.tabelle, f.spalten, f.ziel) for f in v] == [("lieferungen", ["bestellungen_id"], "bestellungen")]


def test_fk_anlegen_und_ausfuehren(db):
    m = _shop(db)
    t = db
    t.abfrage(f"INSERT INTO {t.voll(None if t.art != 'postgresql' else m.schema, 'kunden')} VALUES (1, 'A')"
              if t.art != "postgresql" else "INSERT INTO kunden VALUES (1, 'A')")
    t.abfrage("INSERT INTO bestellungen VALUES (5, 1, NULL)")
    t.abfrage("INSERT INTO lieferungen VALUES (1, 5)")
    fk = erm.Fremdschluessel("lieferungen", ["bestellungen_id"], "bestellungen", ["id"], bei_loeschen="CASCADE")
    anw = erm.ddl_fk_neu(m, fk)
    if t.art in erm.OHNE_ALTER_FK:
        assert any("__neu" in a for a in anw)
    else:
        assert anw[0].startswith("ALTER TABLE") and "ON DELETE CASCADE" in anw[0]
    erm.ausfuehren(t, anw)
    m2 = erm.lade(t, m.schema)
    assert any(f.tabelle == "lieferungen" and f.ziel == "bestellungen" for f in m2.fks)
    assert t.abfrage("SELECT count(*) FROM lieferungen").zeilen[0][0] == 1  # Daten beim Neuaufbau erhalten


def test_fehler_rollt_zurueck(db):
    m = _shop(db)
    with pytest.raises(Exception):
        erm.ausfuehren(db, [erm.ddl_tabelle_neu(db.art, m.schema, "neu_t", [Spalte("a", "text")])[0],
                            "CREATE TABLE kunden (x INTEGER)"])  # zweite Anweisung scheitert
    assert "neu_t" not in db.objekte(m.schema)["tabellen"]


def test_schreibschutz_sperrt(db):
    m = _shop(db)
    db.schreibschutz = True
    with pytest.raises(PermissionError):
        erm.ausfuehren(db, erm.ddl_tabelle_neu(db.art, m.schema, "x", [Spalte("a", "text")]))


@pytest.mark.parametrize("art", list(treiber.KLASSEN))
def test_ddl_dialekte(art):
    sp = [Spalte("id", "grosse_ganzzahl", False, True), Spalte("name", "text", False)]
    neu = erm.ddl_tabelle_neu(art, "s", "t", sp)[0]
    assert "PRIMARY KEY" in neu and erm.typ_nativ(art, "grosse_ganzzahl") in neu
    add = erm.ddl_spalte_neu(art, "s", "t", Spalte("x", "ganzzahl"))[0]
    assert ("ADD COLUMN" in add) == (art != "mssql")
    m = erm.Modell(art, "s", {"t": erm.Tabelle("t", [Spalte("id", "BIGINT", False, True), Spalte("n", "TEXT")]),
                              "u": erm.Tabelle("u", [Spalte("id", "BIGINT", False, True), Spalte("t_id", "BIGINT")])})
    fk = erm.ddl_fk_neu(m, erm.Fremdschluessel("u", ["t_id"], "t", ["id"], bei_aendern="CASCADE"))
    if art in erm.OHNE_ALTER_FK:
        assert fk[0].startswith("CREATE TABLE") and "REFERENCES" in fk[0] and fk[-1].endswith(erm.dialekt(art).zitiere("u"))
    else:
        assert "FOREIGN KEY" in fk[0] and "ON UPDATE CASCADE" in fk[0]
    um = erm.ddl_spalte_aendern(m, "t", "n", Spalte("titel", "TEXT"))
    assert um and ("sp_rename" in um[0] if art == "mssql" else "RENAME COLUMN" in um[0])
    typ = erm.ddl_spalte_aendern(m, "t", "n", Spalte("n", "ganzzahl", False))
    if art == "sqlite":
        assert any("__neu" in a for a in typ)
    elif art == "mysql":
        assert typ == [f"ALTER TABLE `s`.`t` MODIFY COLUMN `n` INT NOT NULL"]
    else:
        assert len(typ) >= 1


def test_sqlite_not_null_braucht_standard():
    with pytest.raises(ValueError):
        erm.ddl_spalte_neu("sqlite", "main", "t", Spalte("x", "text", False))
    assert "DEFAULT 'a'" in erm.ddl_spalte_neu("sqlite", "main", "t", Spalte("x", "text", False), "'a'")[0]


def test_sqlite_typwechsel_mit_daten(tmp_path):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "x.db")})
    t.abfrage("CREATE TABLE a (id INTEGER PRIMARY KEY, wert TEXT)")
    t.abfrage("INSERT INTO a VALUES (1, '42')")
    m = erm.lade(t, "main")
    erm.ausfuehren(t, erm.ddl_spalte_aendern(m, "a", "wert", Spalte("zahl", "ganzzahl", False)))
    sp = {s.name: s for s in t.spalten("main", "a")}
    assert sp["zahl"].typ.upper() == "INTEGER" and not sp["zahl"].nullbar
    assert t.abfrage("SELECT zahl FROM a").zeilen == [(42,)]
    t.schliessen()


# --- Oberfläche -----------------------------------------------------------------------------------------------------
@pytest.fixture
def fenster(qtbot, tmp_path, monkeypatch):
    import keyring
    monkeypatch.setattr(keyring, "get_password", lambda d, k: None)
    db = tmp_path / "shop.db"
    t = treiber.oeffne({"art": "sqlite", "datei": str(db)})
    for s in SHOP:
        t.abfrage(s)
    t.schliessen()
    v = verbindungen.neu(name="Shop", art="sqlite", datei=str(db))
    verbindungen.speichern([v])
    from dbstudio.ui import arbeiter
    from dbstudio.ui.fenster import Hauptfenster
    f = Hauptfenster()
    qtbot.addWidget(f)
    f.verbinden(v)
    qtbot.waitUntil(lambda: bool(f.diagramm.karten), timeout=15000)
    yield f
    arbeiter.warte_alle(5000)
    if f.t:
        f.t.schliessen()


def test_diagramm_aufbau_und_export(qtbot, fenster, tmp_path):
    d = fenster.diagramm
    assert set(d.karten) >= {"kunden", "bestellungen", "bestellpositionen"}
    assert len(d.linien) == 4
    arten = {(l.fk.tabelle, l.fk.ziel): l.art for l in d.linien}
    assert arten[("profile", "kunden")] == "1:1" and arten[("bestellungen", "kunden")] == "1:n"
    assert d.karten["bestellpositionen"].zwischen
    assert "n:m" in d.info.text()
    alt = d.linien[0].path().boundingRect()
    karte = d.karten[d.linien[0].fk.ziel]
    karte.setPos(karte.pos().x() + 300, karte.pos().y() + 120)
    assert d.linien[0].path().boundingRect() != alt  # Linie folgt der Karte
    d.exportieren("png", str(tmp_path / "d.png"))
    d.exportieren("svg", str(tmp_path / "d.svg"))
    assert (tmp_path / "d.png").stat().st_size > 1000 and "<svg" in (tmp_path / "d.svg").read_text()


def test_diagramm_beziehung_per_vorschau(qtbot, fenster, monkeypatch):
    from dbstudio.ui import seite_diagramm
    d = fenster.diagramm
    monkeypatch.setattr(seite_diagramm.BeziehungDialog, "exec", lambda self: seite_diagramm.QDialog.Accepted)
    monkeypatch.setattr(seite_diagramm.DDLVorschau, "exec", lambda self: seite_diagramm.QDialog.Accepted)
    monkeypatch.setattr(seite_diagramm, "rueckfrage", lambda *a, **k: True)
    d.beziehung_neu("lieferungen", "bestellungen_id", "bestellungen", "id")
    qtbot.waitUntil(lambda: any(l.fk.tabelle == "lieferungen" for l in d.linien), timeout=15000)


def test_diagramm_abbrechen_aendert_nichts(qtbot, fenster, monkeypatch):
    from dbstudio.ui import seite_diagramm
    d = fenster.diagramm
    monkeypatch.setattr(seite_diagramm.BeziehungDialog, "exec", lambda self: seite_diagramm.QDialog.Accepted)
    monkeypatch.setattr(seite_diagramm.DDLVorschau, "exec", lambda self: seite_diagramm.QDialog.Rejected)
    d.beziehung_neu("lieferungen", "bestellungen_id", "bestellungen", "id")
    assert not any(f.tabelle == "lieferungen" for f in erm.lade(fenster.t, "main").fks)


def test_diagramm_schreibschutz(qtbot, fenster, monkeypatch):
    from dbstudio.ui import seite_diagramm
    gemeldet = []
    monkeypatch.setattr(seite_diagramm, "meldung", lambda *a, **k: gemeldet.append(a[1]))
    fenster.t.schreibschutz = True
    fenster.diagramm.beziehung_neu("lieferungen", "bestellungen_id", "bestellungen", "id")
    assert gemeldet == ["Schreibschutz"]
