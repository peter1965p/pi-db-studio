"""Microsoft-Access-Dateien (.mdb, .accdb) übernehmen – ohne Access und ohne Windows.

Liest Tabellen und Daten mit `access-parser` (reines Python), legt sie in der Zielverbindung an (Typen aus den Werten
geschätzt, Primärschlüssel aus „ID“ bzw. „<Tabelle>ID“) und schlägt danach Beziehungen über die Namen vor
(„CategoryID“ → Categories). Die in Access gepflegten Beziehungen (MSysRelationships) liest die Bibliothek nicht;
darum werden Fremdschlüssel nur angelegt, wenn der Bestand dazu passt (keine verwaisten Verweise).
"""
from __future__ import annotations

import contextlib
import io
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import austausch, erm, treiber
from .treiber import NATIV, Spalte

# Demo: Microsofts klassische Beispieldatenbank „Northwind“ (Access-Fassung aus den mdbtools-Testdaten).
NORTHWIND = Path(__file__).parent / "demo" / "northwind.mdb"


@dataclass
class AccessTabelle:
    name: str
    spalten: list[str]
    zeilen: list[list]
    typen: dict[str, str] = field(default_factory=dict)
    pk: list[str] = field(default_factory=list)
    fehler: str = ""


# Access-Spaltentypen (access_parser.utils) → generische Typen von Pi DB Studio
_TYPEN = {1: "wahrheitswert", 2: "ganzzahl", 3: "ganzzahl", 4: "ganzzahl", 5: "dezimal", 6: "kommazahl", 7: "kommazahl",
          8: "zeitstempel", 9: "binaer", 10: "text", 11: "binaer", 12: "text", 15: "text", 16: "dezimal", 18: "ganzzahl"}


class _Zaehler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.kaputt = 0

    def emit(self, record):
        if "did not parse correctly" in record.getMessage():
            self.kaputt += 1


def _geld(w):
    """Währung: access_parser liefert den Rohwert in Zehntausendsteln (oder formatierten Text)."""
    if w is None or w == "":
        return None
    if isinstance(w, int):
        return Decimal(w) / 10000
    try:
        return Decimal(str(w).replace(",", "").replace("€", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def lesen(pfad: str) -> list[AccessTabelle]:
    """Tabellen mit Typen und Primärschlüsseln aus der Access-Datei. Beschädigte Tabellen kommen mit `fehler` zurück."""
    try:
        from access_parser import AccessParser
    except ImportError as e:
        raise treiber.DBFehler("Für Access-Dateien fehlt das Paket: pip install access-parser") from e
    _datum_tolerant()
    log = logging.getLogger("access_parser")
    log.setLevel(logging.WARNING)
    log.propagate = False  # Systemtabellen erzeugen viele Warnungen, die gehören nicht ins Programm-Log
    zaehler = _Zaehler()
    log.addHandler(zaehler)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            db = AccessParser(str(pfad))
            namen = [n for n in db.catalog if not n.startswith(("MSys", "~", "USys", "f_"))]
            tabellen = []
            for name in namen:
                zaehler.kaputt = 0
                try:
                    tab = db.get_table(name)
                    roh = tab.parse()
                except Exception as e:
                    tabellen.append(AccessTabelle(name, [], [], fehler=f"nicht lesbar ({type(e).__name__})"))
                    continue
                spalten = [c.col_name_str for _, c in sorted(tab.columns.items())]
                typen = {c.col_name_str: _TYPEN.get(c.type, "text") for c in tab.columns.values()}
                anzahl = max((len(v) for v in roh.values()), default=0)
                zeilen = []
                for i in range(anzahl):
                    z = []
                    for s_ in spalten:
                        w = roh[s_][i] if i < len(roh.get(s_, [])) else None
                        z.append(_geld(w) if typen[s_] == "dezimal" else w)
                    zeilen.append(z)
                pk = [p_ for p_ in (tab.primary_keys or []) if p_ in spalten]
                t = AccessTabelle(name, spalten, zeilen, typen, pk)
                if zaehler.kaputt:
                    t.fehler = f"beschädigt: {zaehler.kaputt} Datensätze nicht lesbar"
                tabellen.append(t)
    finally:
        log.removeHandler(zaehler)
    return tabellen


def _datum_tolerant() -> None:
    """Kaputte Datumswerte (NaN) brachen sonst die ganze Tabelle ab; sie werden zu NULL."""
    from access_parser import utils
    if getattr(utils.mdb_date_to_readable, "_tolerant", False):
        return
    original = utils.mdb_date_to_readable

    def tolerant(wert):
        try:
            return original(wert)
        except (ValueError, OverflowError):
            return None
    tolerant._tolerant = True
    utils.mdb_date_to_readable = tolerant


def importieren(ziel: treiber.Treiber, schema: str | None, tabellen: list[AccessTabelle], beziehungen: bool = True,
                melde=lambda text: None) -> dict:
    """Legt Tabellen an, kopiert die Daten und (optional) Fremdschlüssel, wo der Bestand passt."""
    uebersprungen = [f"{t.name}: {t.fehler}" for t in tabellen if t.fehler]
    tabellen = [t for t in tabellen if not t.fehler]
    vorhanden = set(ziel.objekte(schema or ziel.standard_schema()).get("tabellen", []))
    doppelt = [t.name for t in tabellen if t.name in vorhanden]
    if doppelt:
        raise ValueError(f"Gibt es schon: {', '.join(doppelt)}. Anderes Schema wählen oder vorher umbenennen.")
    zeilen = 0
    for t in tabellen:
        melde(f"Lege {t.name} an")
        spalten = [Spalte(s, NATIV[ziel.art][t.typen.get(s, "text")], s not in t.pk, s in t.pk) for s in t.spalten]
        ziel.abfrage(ziel.ddl_tabelle(schema, t.name, spalten))
        if t.zeilen:
            daten = t.zeilen
            if ziel.art == "sqlite":  # sqlite3 kennt kein Decimal; NUMERIC speichert ohnehin als Zahl
                daten = [[float(w) if isinstance(w, Decimal) else w for w in z] for z in t.zeilen]
            zeilen += austausch.importieren(ziel, schema, t.name, t.spalten, daten, {s: s for s in t.spalten})
    angelegt, ausgelassen = [], []
    if beziehungen:
        m = erm.lade(ziel, schema or ziel.standard_schema())
        for f in erm.vorschlaege(m):
            if f.tabelle not in {t.name for t in tabellen}:
                continue
            anzahl, _ = erm.verwaiste(ziel, m, f)
            if anzahl:
                ausgelassen.append(f"{f.tabelle}.{','.join(f.spalten)} → {f.ziel}: {anzahl} verwaiste Verweise")
                continue
            try:
                erm.ausfuehren(ziel, erm.ddl_fk_neu(m, f))
                angelegt.append(f"{f.tabelle}.{','.join(f.spalten)} → {f.ziel}")
                m = erm.lade(ziel, schema or ziel.standard_schema())
            except Exception as e:
                ausgelassen.append(f"{f.tabelle}.{','.join(f.spalten)} → {f.ziel}: {str(e)[:120]}")
    return {"tabellen": len(tabellen), "zeilen": zeilen, "beziehungen": angelegt, "ausgelassen": ausgelassen,
            "uebersprungen": uebersprungen}


def uebersicht(tabellen: list[AccessTabelle]) -> list[dict]:
    return [{"name": t.name, "zeilen": len(t.zeilen), "pk": ", ".join(t.pk), "fehler": t.fehler,
             "spalten": [{"name": s, "typ": t.typen[s]} for s in t.spalten]} for t in tabellen]


# Die bekanntesten Northwind-Abfragen als Views (die Access-Abfragen selbst liest access-parser nicht).
NORTHWIND_VIEWS = {
    "Order Details Extended": """SELECT d."OrderID", d."ProductID", p."ProductName", d."UnitPrice", d."Quantity", d."Discount",
        round(d."UnitPrice" * d."Quantity" * (1 - d."Discount"), 2) AS "ExtendedPrice"
        FROM "Order Details" d JOIN "Products" p ON p."ProductID" = d."ProductID" """,
    "Order Subtotals": """SELECT "OrderID", round(sum("UnitPrice" * "Quantity" * (1 - "Discount")), 2) AS "Subtotal"
        FROM "Order Details" GROUP BY "OrderID" """,
    "Current Product List": """SELECT "ProductID", "ProductName" FROM "Products" WHERE "Discontinued" = 0""",
    "Products Above Average Price": """SELECT "ProductName", "UnitPrice" FROM "Products"
        WHERE "UnitPrice" > (SELECT avg("UnitPrice") FROM "Products")""",
    "Products by Category": """SELECT c."CategoryName", p."ProductName", p."QuantityPerUnit", p."UnitsInStock", p."Discontinued"
        FROM "Categories" c JOIN "Products" p ON p."CategoryID" = c."CategoryID" """,
    "Customers and Suppliers by City": """SELECT "City", "CompanyName", "ContactName", 'Customers' AS "Relationship" FROM "Customers"
        UNION SELECT "City", "CompanyName", "ContactName", 'Suppliers' FROM "Suppliers" """,
    "Category Sales": """SELECT c."CategoryName", round(sum(d."UnitPrice" * d."Quantity" * (1 - d."Discount")), 2) AS "CategorySales"
        FROM "Order Details" d JOIN "Products" p ON p."ProductID" = d."ProductID"
        JOIN "Categories" c ON c."CategoryID" = p."CategoryID" GROUP BY c."CategoryName" """,
    "Employee Sales by Country": """SELECT e."Country", e."LastName", e."FirstName", o."OrderID", s."Subtotal" AS "SaleAmount"
        FROM "Employees" e JOIN "Orders" o ON o."EmployeeID" = e."EmployeeID"
        JOIN "Order Subtotals" s ON s."OrderID" = o."OrderID" """,
    "Invoices": """SELECT o."OrderID", o."OrderDate", o."ShipName", o."ShipCity", o."ShipCountry", c."CompanyName" AS "CustomerName",
        e."FirstName" || ' ' || e."LastName" AS "Salesperson", sh."CompanyName" AS "ShipperName",
        x."ProductName", x."UnitPrice", x."Quantity", x."Discount", x."ExtendedPrice", o."Freight"
        FROM "Orders" o JOIN "Customers" c ON c."CustomerID" = o."CustomerID"
        JOIN "Employees" e ON e."EmployeeID" = o."EmployeeID" LEFT JOIN "Shippers" sh ON sh."ShipperID" = o."ShipVia"
        JOIN "Order Details Extended" x ON x."OrderID" = o."OrderID" """,
}


def demo_northwind(datei: str | Path) -> dict:
    """Legt Northwind als SQLite-Datenbank an (einmalig) und gibt die Verbindungsdaten zurück."""
    datei = Path(datei)
    erg = {"neu": False}
    if not datei.exists():
        datei.parent.mkdir(parents=True, exist_ok=True)
        ziel = treiber.oeffne({"art": "sqlite", "datei": str(datei)}, None)
        try:
            erg = {"neu": True, **importieren(ziel, None, lesen(str(NORTHWIND)))}
            for name, sql in NORTHWIND_VIEWS.items():  # Reihenfolge zählt: spätere Views bauen auf früheren auf
                ziel.abfrage(f'CREATE VIEW "{name}" AS {sql}')
            erg["views"] = list(NORTHWIND_VIEWS)
        except Exception:
            ziel.schliessen()
            datei.unlink(missing_ok=True)
            raise
        ziel.schliessen()
    return {**erg, "verbindung": {"name": "Northwind (Demo aus Access)", "art": "sqlite", "datei": str(datei)}}
