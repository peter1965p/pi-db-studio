"""SQL-Dump importieren: Struktur-Exporte (z. B. Supabase „Schema“) lauffähig machen und in PostgreSQL einspielen.

Supabase exportiert das Schema „nur zur Ansicht“: Tabellen stehen nicht in Abhängigkeitsreihenfolge, Sequenzen fehlen,
Arrays heißen nur `ARRAY`, `uuid_generate_v4()` braucht eine Erweiterung, und Fremdschlüssel zeigen auf `auth.users`,
das es nur bei Supabase gibt. `vorbereiten` macht daraus eine ausführbare Liste und erklärt jede Änderung:

1. Sequenzen aus `nextval('…')` anlegen (CREATE SEQUENCE IF NOT EXISTS).
2. `ARRAY` → Elementtyp aus dem Standardwert (`'{}'::text[]` → `text[]`), sonst `text[]`.
3. `uuid_generate_v4()` → `gen_random_uuid()` (in PostgreSQL ab 13 eingebaut).
4. Fremdschlüssel aus den Tabellen lösen und am Ende per ALTER TABLE anlegen – dann spielt die Reihenfolge keine Rolle.
5. Verweise auf Schemata, die der Dump nicht anlegt (z. B. auth.users): Ersatztabelle anlegen oder Fremdschlüssel weglassen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import treiber

_CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?((?:\"?[\w]+\"?\.)?\"?[\w]+\"?)\s*\((.*)\)\s*$", re.S | re.I)
_FK = re.compile(r"^\s*CONSTRAINT\s+(\"?[\w]+\"?)\s+FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+((?:\"?\w+\"?\.)?\"?\w+\"?)\s*\(([^)]*)\)(.*)$",
                 re.S | re.I)
_NEXTVAL = re.compile(r"nextval\('([^']+)'(?:::regclass)?\)", re.I)


@dataclass
class Plan:
    anweisungen: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    tabellen: list[str] = field(default_factory=list)
    fks: int = 0
    fremde_ziele: list[str] = field(default_factory=list)


def _teile(rumpf: str) -> list[str]:
    """Spalten-/Constraint-Definitionen an Kommas auf oberster Klammerebene trennen."""
    teile, tiefe, start, im_text = [], 0, 0, False
    for i, z in enumerate(rumpf):
        if z == "'":
            im_text = not im_text
        elif not im_text:
            if z == "(":
                tiefe += 1
            elif z == ")":
                tiefe -= 1
            elif z == "," and tiefe == 0:
                teile.append(rumpf[start:i].strip())
                start = i + 1
    rest = rumpf[start:].strip()
    if rest:
        teile.append(rest)
    return teile


def _schema(name: str) -> str:
    return name.split(".")[0].strip('"') if "." in name else "public"


def _ohne_kommentare(sql: str) -> str:
    """Entfernt -- und /* */ Kommentare, aber nie innerhalb von '…'."""
    aus, i, im_text = [], 0, False
    while i < len(sql):
        z = sql[i]
        if z == "'":
            im_text = not im_text
        elif not im_text and sql.startswith("--", i):
            ende = sql.find("\n", i)
            i = len(sql) if ende < 0 else ende
            continue
        elif not im_text and sql.startswith("/*", i):
            ende = sql.find("*/", i + 2)
            i = len(sql) if ende < 0 else ende + 2
            continue
        aus.append(z)
        i += 1
    return "".join(aus)


def vorbereiten(sql: str, fremde: str = "ersatz") -> Plan:
    """fremde: "ersatz" legt für fremde Ziele (z. B. auth.users) eine Ersatztabelle mit dem Ziel-Schlüssel an,
    "weglassen" lässt diese Fremdschlüssel weg."""
    if fremde not in ("ersatz", "weglassen"):
        raise ValueError("fremde: ersatz oder weglassen")
    plan = Plan()
    tabellen, fks, sonstige, sequenzen, schemata = [], [], [], [], []
    for anw in treiber.anweisungen(_ohne_kommentare(sql)):
        m = _CREATE.match(anw)
        if not m:
            sonstige.append(anw)
            continue
        name, rumpf = m.group(1), m.group(2)
        plan.tabellen.append(name)
        if _schema(name) not in schemata and _schema(name) != "public":
            schemata.append(_schema(name))
        behalten = []
        for teil in _teile(rumpf):
            fk = _FK.match(teil)
            if fk:
                fks.append((name, fk.group(1), fk.group(2), fk.group(3), fk.group(4), fk.group(5).strip()))
                continue
            for seq in _NEXTVAL.findall(teil):
                if seq not in sequenzen:
                    sequenzen.append(seq)
            neu = re.sub(r"\bARRAY\s+DEFAULT\s+('[^']*'::(\w+(?:\s+\w+)?)\[\])", r"\2[] DEFAULT \1", teil, flags=re.I)
            neu = re.sub(r"^(\s*\"?\w+\"?\s+)ARRAY\b", r"\1text[]", neu, flags=re.I)
            neu = re.sub(r"\buuid_generate_v4\(\)", "gen_random_uuid()", neu, flags=re.I)
            behalten.append(neu)
        tabellen.append(f"CREATE TABLE IF NOT EXISTS {name} (\n  " + ",\n  ".join(behalten) + "\n)")

    if re.search(r"\w\s+ARRAY\b(?!\s*\[)", sql):
        plan.hinweise.append("ARRAY ohne Elementtyp → Typ aus dem Standardwert übernommen (sonst text[]).")
    if re.search(r"uuid_generate_v4", sql, re.I):
        plan.hinweise.append("uuid_generate_v4() → gen_random_uuid() (eingebaut, keine Erweiterung nötig).")
    if sequenzen:
        plan.hinweise.append(f"{len(sequenzen)} fehlende Sequenzen werden angelegt.")

    norm = lambda n: (n if "." in n else f"public.{n}").lower().replace('"', "")  # noqa: E731
    eigene = {norm(t) for t in plan.tabellen}
    fremd = sorted({f[3] for f in fks if norm(f[3]) not in eigene})
    plan.fremde_ziele = fremd
    ersatz = []
    if fremd:
        if fremde == "ersatz":
            for ziel in fremd:
                spalten = {f[4] for f in fks if f[3] == ziel}
                sp = sorted(spalten)[0] if spalten else "id"
                if _schema(ziel) != "public" and _schema(ziel) not in schemata:
                    schemata.append(_schema(ziel))
                ersatz.append(f"CREATE TABLE IF NOT EXISTS {ziel} ({sp} uuid PRIMARY KEY)")
            plan.hinweise.append(f"Fremde Ziele {', '.join(fremd)}: Ersatztabelle mit nur dem Schlüssel angelegt "
                                 f"(bei Supabase verwaltet auth die Benutzer). Fremdschlüssel bleiben erhalten.")
        else:
            vorher = len(fks)
            fks = [f for f in fks if f[3] not in fremd]
            plan.hinweise.append(f"{vorher - len(fks)} Fremdschlüssel auf {', '.join(fremd)} weggelassen – diese "
                                 f"Spalten verweisen danach ohne Constraint.")
    plan.fks = len(fks)
    plan.hinweise.append(f"{len(plan.tabellen)} Tabellen, {len(fks)} Fremdschlüssel (am Ende angelegt, Reihenfolge egal).")
    plan.anweisungen = ([f"CREATE SCHEMA IF NOT EXISTS {s}" for s in schemata]
                        + [f"CREATE SEQUENCE IF NOT EXISTS {s}" for s in sequenzen]
                        + ersatz + tabellen + sonstige
                        + [f"ALTER TABLE {t} ADD CONSTRAINT {n} FOREIGN KEY ({sp}) REFERENCES {z} ({zs}){(' ' + rest) if rest else ''}"
                           for t, n, sp, z, zs, rest in fks])
    return plan


def einspielen(t: treiber.Treiber, plan: Plan) -> int:
    """Alles in einer Transaktion: Entweder steht danach die ganze Struktur oder nichts."""
    if t.art != "postgresql":
        raise ValueError("Der Import von SQL-Dumps unterstützt derzeit PostgreSQL als Ziel.")
    t.beginnen()
    try:
        for a in plan.anweisungen:
            t.abfrage(a)
        t.bestaetigen()
    except Exception:
        t.zuruecknehmen()
        raise
    return len(plan.anweisungen)
