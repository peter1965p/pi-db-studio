"""Access-Import: Northwind (.mdb) mit echten Typen, Schlüsseln, Währungen, Beziehungen und Views."""
import pytest

from dbstudio import access, treiber

pytest.importorskip("access_parser")


@pytest.fixture(scope="module")
def tabellen():
    return {t.name: t for t in access.lesen(str(access.NORTHWIND))}


def test_tabellen_typen_und_schluessel(tabellen):
    assert {n for n, t in tabellen.items() if not t.fehler} == {
        "Categories", "Customers", "Employees", "Order Details", "Orders", "Products", "Shippers", "Suppliers"}
    assert tabellen["Order Details"].pk == ["OrderID", "ProductID"]
    assert tabellen["Products"].typen["UnitPrice"] == "dezimal"
    assert len(tabellen["Order Details"].zeilen) == 2155


def test_beschaedigte_tabelle_wird_erkannt(tabellen):
    assert "beschädigt" in tabellen["Umsätze"].fehler


def test_demo_komplett(tmp_path):
    r = access.demo_northwind(tmp_path / "nw.db")
    assert r["neu"] and r["tabellen"] == 8 and r["zeilen"] == 3202 and len(r["beziehungen"]) == 6
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "nw.db")}, None)
    try:
        assert t.abfrage('SELECT UnitPrice FROM Products WHERE ProductName = \'Chai\'').zeilen[0][0] == 18
        umsatz = t.abfrage('SELECT round(sum(UnitPrice*Quantity*(1-Discount)), 2) FROM "Order Details"').zeilen[0][0]
        assert umsatz == pytest.approx(1265793.04)
        assert t.abfrage('SELECT count(*) FROM "Current Product List"').zeilen[0][0] == 69
        assert t.abfrage('SELECT count(*) FROM "Invoices"').zeilen[0][0] == 2155
    finally:
        t.schliessen()
    assert access.demo_northwind(tmp_path / "nw.db")["neu"] is False  # zweiter Aufruf legt nichts doppelt an


def test_import_in_vorhandene_tabelle_wird_abgelehnt(tmp_path, tabellen):
    t = treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "x.db")}, None)
    t.abfrage('CREATE TABLE "Shippers" (id INTEGER)')
    with pytest.raises(ValueError, match="Gibt es schon"):
        access.importieren(t, None, [tabellen["Shippers"]])
    t.schliessen()
