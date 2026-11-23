"""Import und Export (CSV, JSON, Excel, SQL-INSERT) sowie Tabelle zwischen Verbindungen kopieren."""

from __future__ import annotations

import base64
import csv
import datetime as dt
import decimal
import json
import uuid
from pathlib import Path
from typing import Iterable

from .treiber import NATIV, Spalte, Treiber, generischer_typ

FORMATE = {"csv": "CSV (*.csv)", "json": "JSON (*.json)", "xlsx": "Excel (*.xlsx)", "sql": "SQL-INSERT (*.sql)"}


def format_aus_pfad(pfad: str | Path) -> str:
    endung = Path(pfad).suffix.lower().lstrip(".")
    return {"xls": "xlsx", "jsonl": "json"}.get(endung, endung)


# --- Werte -------------------------------------------------------------------------------------------------------------
def _json_wert(w):
    if isinstance(w, (dt.datetime, dt.date, dt.time)):
        return w.isoformat()
    if isinstance(w, decimal.Decimal):
        return int(w) if w == w.to_integral_value() else float(w)
    if isinstance(w, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(w)).decode()
    if isinstance(w, uuid.UUID):
        return str(w)
    if isinstance(w, (dict, list, str, int, float, bool)) or w is None:
        return w
    return str(w)


def sql_literal(w) -> str:
    if w is None:
        return "NULL"
    if isinstance(w, bool):
        return "TRUE" if w else "FALSE"
    if isinstance(w, (int, float, decimal.Decimal)):
        return str(w)
    if isinstance(w, (bytes, bytearray, memoryview)):
        return "X'" + bytes(w).hex() + "'"
    if isinstance(w, (dict, list)):
        w = json.dumps(w, ensure_ascii=False)
    return "'" + str(_json_wert(w)).replace("'", "''") + "'"


# --- Export -----------------------------------------------------------------------------------------------------------
def exportieren(pfad: str | Path, spalten: list[str], zeilen: Iterable[tuple], format_: str | None = None,
                tabelle: str = "daten", zitiere=lambda n: '"' + n.replace('"', '""') + '"') -> int:
    """Schreibt die Zeilen in die Datei, gibt die Anzahl zurück. `zeilen` darf ein Generator sein."""
    pfad = Path(pfad)
    format_ = format_ or format_aus_pfad(pfad)
    n = 0
    if format_ == "csv":
        with pfad.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(spalten)
            for z in zeilen:
                w.writerow(["" if v is None else _json_wert(v) if not isinstance(v, (int, float, str)) else v for v in z])
                n += 1
    elif format_ == "json":
        with pfad.open("w", encoding="utf-8") as f:
            f.write("[\n")
            for z in zeilen:
                f.write((",\n" if n else "") + "  " + json.dumps({s: _json_wert(v) for s, v in zip(spalten, z)}, ensure_ascii=False))
                n += 1
            f.write("\n]\n")
    elif format_ == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(tabelle[:31] or "Daten")
        ws.append(spalten)
        for z in zeilen:
            ws.append([v if isinstance(v, (int, float, str, bool, dt.datetime, dt.date)) or v is None else str(_json_wert(v))
                       for v in z])
            n += 1
        wb.save(pfad)
    elif format_ == "sql":
        kopf = f"INSERT INTO {zitiere(tabelle)} ({', '.join(zitiere(s) for s in spalten)}) VALUES "
        with pfad.open("w", encoding="utf-8") as f:
            for z in zeilen:
                f.write(kopf + "(" + ", ".join(sql_literal(v) for v in z) + ");\n")
                n += 1
    else:
        raise ValueError(f"Unbekanntes Format: {format_}")
    return n


# --- Import -----------------------------------------------------------------------------------------------------------
def lesen(pfad: str | Path, format_: str | None = None, max_zeilen: int | None = None) -> tuple[list[str], list[list]]:
    """Liest Spaltennamen und Zeilen aus CSV, JSON oder Excel (erste Tabelle)."""
    pfad = Path(pfad)
    format_ = format_ or format_aus_pfad(pfad)
    if format_ == "csv":
        text = pfad.read_text(encoding="utf-8-sig", errors="replace")
        try:
            dialekt = csv.Sniffer().sniff(text[:20000], delimiters=";,\t|")
        except csv.Error:
            dialekt = csv.excel
            dialekt.delimiter = ";" if text.count(";") > text.count(",") else ","
        leser = csv.reader(text.splitlines(), dialekt)
        spalten = next(leser, [])
        zeilen = []
        for z in leser:
            if max_zeilen is not None and len(zeilen) >= max_zeilen:
                break
            zeilen.append([None if v == "" else v for v in z] + [None] * (len(spalten) - len(z)))
        return spalten, zeilen
    if format_ == "json":
        text = pfad.read_text(encoding="utf-8")
        try:
            daten = json.loads(text)
        except ValueError:
            daten = [json.loads(z) for z in text.splitlines() if z.strip()]  # JSON Lines
        if isinstance(daten, dict):
            daten = next((v for v in daten.values() if isinstance(v, list)), [daten])
        spalten: list[str] = []
        for obj in daten[: max_zeilen or None]:
            for k in obj:
                if k not in spalten:
                    spalten.append(k)
        zeilen = [[_flach(obj.get(s)) for s in spalten] for obj in daten[: max_zeilen or None]]
        return spalten, zeilen
    if format_ == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(pfad, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        spalten = [str(s) if s is not None else f"spalte_{i + 1}" for i, s in enumerate(next(it, []))]
        zeilen = []
        for z in it:
            if max_zeilen is not None and len(zeilen) >= max_zeilen:
                break
            if any(v is not None for v in z):
                zeilen.append(list(z) + [None] * (len(spalten) - len(z)))
        wb.close()
        return spalten, zeilen
    raise ValueError(f"Import aus {format_} wird nicht unterstützt.")


def _flach(w):
    return json.dumps(w, ensure_ascii=False) if isinstance(w, (dict, list)) else w


def typ_schaetzen(werte: list) -> str:
    """Generischer Typ für eine Spalte aus Beispielwerten (für neue Zieltabellen)."""
    gesehen = [w for w in werte if w not in (None, "")]
    if not gesehen:
        return "text"

    def alle(pruef):
        try:
            return all(pruef(w) for w in gesehen)
        except Exception:
            return False
    if alle(lambda w: isinstance(w, bool) or str(w).lower() in ("true", "false")):
        return "wahrheitswert"
    if alle(lambda w: isinstance(w, int) and not isinstance(w, bool) or (isinstance(w, str) and w.lstrip("-").isdigit())):
        return "grosse_ganzzahl" if any(abs(int(w)) > 2_000_000_000 for w in gesehen) else "ganzzahl"
    if alle(lambda w: isinstance(w, float) or float(str(w).replace(",", ".")) is not None):
        return "kommazahl"
    if alle(lambda w: isinstance(w, dt.datetime) or dt.datetime.fromisoformat(str(w)) and len(str(w)) > 10):
        return "zeitstempel"
    if alle(lambda w: isinstance(w, dt.date) or dt.date.fromisoformat(str(w))):
        return "datum"
    return "text"


def _umwandeln(w, generisch: str):
    if w is None or w == "":
        return None
    try:
        if generisch in ("ganzzahl", "grosse_ganzzahl"):
            return int(w)
        if generisch == "kommazahl":
            return float(str(w).replace(",", ".")) if isinstance(w, str) else float(w)
        if generisch == "wahrheitswert":
            return w if isinstance(w, bool) else str(w).strip().lower() in ("1", "true", "ja", "wahr", "t", "y", "yes")
    except (ValueError, TypeError):
        return w
    return w


def importieren(t: Treiber, schema: str | None, tabelle: str, quell_spalten: list[str], zeilen: list[list],
                zuordnung: dict[str, str], neu_anlegen: bool = False, stapel: int = 500,
                melde=lambda n: None) -> int:
    """Schreibt Zeilen in eine Tabelle. `zuordnung`: Quellspalte -> Zielspalte (leer = auslassen)."""
    paare = [(i, ziel) for i, q in enumerate(quell_spalten) if (ziel := zuordnung.get(q))]
    if not paare:
        raise ValueError("Keine Spalte zugeordnet.")
    if neu_anlegen:
        spalten = [Spalte(ziel, NATIV[t.art][typ_schaetzen([z[i] for z in zeilen[:500]])]) for i, ziel in paare]
        t.abfrage(t.ddl_tabelle(schema, tabelle, spalten))
    ziel_typen = {s.name: s.generisch for s in t.spalten(schema or t.standard_schema(), tabelle)}
    sql = t.einfuegen_sql(schema, tabelle, [z for _, z in paare])
    n = 0
    t.beginnen()
    try:
        for start in range(0, len(zeilen), stapel):
            teil = [tuple(_umwandeln(z[i], ziel_typen.get(ziel, "text")) for i, ziel in paare) for z in zeilen[start:start + stapel]]
            t.ausfuehren_viele(sql, teil)
            n += len(teil)
            melde(n)
        t.bestaetigen()
    except Exception:
        t.zuruecknehmen()
        raise
    return n


def tabelle_kopieren(quelle: Treiber, q_schema: str, q_tabelle: str, ziel: Treiber, z_schema: str | None,
                     z_tabelle: str, ersetzen: bool = False, stapel: int = 1000, melde=lambda n: None) -> int:
    """Legt die Tabelle im Ziel mit abgebildeten Typen an und kopiert alle Zeilen in Stapeln."""
    spalten = quelle.spalten(q_schema, q_tabelle)
    if not spalten:
        raise ValueError(f"Tabelle {q_tabelle} hat keine Spalten oder existiert nicht.")
    vorhanden = z_tabelle in ziel.objekte(z_schema or ziel.standard_schema())["tabellen"]
    if vorhanden and not ersetzen:
        raise ValueError(f"Im Ziel gibt es „{z_tabelle}“ schon. Ersetzen ankreuzen oder anderen Namen wählen.")
    if vorhanden:
        ziel.abfrage(f"DROP TABLE {ziel.voll(z_schema, z_tabelle)}")
    ziel.abfrage(ziel.ddl_tabelle(z_schema, z_tabelle, spalten))
    typen = [s.generisch for s in spalten]
    sql = ziel.einfuegen_sql(z_schema, z_tabelle, [s.name for s in spalten])
    erg = quelle.abfrage(f"SELECT * FROM {quelle.voll(q_schema, q_tabelle)}", limit=stapel)
    n = 0
    ziel.beginnen()
    try:
        teil = erg.zeilen
        while teil:
            ziel.ausfuehren_viele(sql, [tuple(_fuer_ziel(v, typ, ziel.art) for v, typ in zip(z, typen)) for z in teil])
            n += len(teil)
            melde(n)
            erg.zeilen = []
            teil = erg.weitere(stapel)
        ziel.bestaetigen()
    except Exception:
        ziel.zuruecknehmen()
        raise
    finally:
        erg.schliessen()
    return n


def _fuer_ziel(w, generisch: str, art: str):
    if w is None:
        return None
    if generisch == "json" and isinstance(w, (dict, list)):
        return json.dumps(w, ensure_ascii=False)
    if generisch == "wahrheitswert" and art == "postgresql" and isinstance(w, int):
        return bool(w)
    if art == "sqlite" and isinstance(w, (dt.date, dt.datetime, dt.time, decimal.Decimal, uuid.UUID)):
        return str(w)
    if generisch == "uuid" and art in ("postgresql",) and isinstance(w, str):
        return w
    return w


__all__ = ["FORMATE", "exportieren", "lesen", "importieren", "tabelle_kopieren", "typ_schaetzen", "generischer_typ"]
