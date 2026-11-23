"""Beziehungsmodell für den Diagramm-Designer: Tabellen, Fremdschlüssel, Kardinalität, Layout und DDL je Dialekt.

Nichts hier führt selbst Änderungen aus. ``ddl_*`` liefert Anweisungen als Text (Vorschau); ausgeführt wird erst nach
Bestätigung über :func:`ausfuehren` in einer Transaktion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import verbindungen
from .treiber import KLASSEN, NATIV, Spalte, Treiber

AKTIONEN = ["NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"]
# Dialekte, die Fremdschlüssel nicht per ALTER TABLE hinzufügen können → Tabelle wird neu aufgebaut
OHNE_ALTER_FK = {"sqlite", "duckdb"}


@dataclass
class Fremdschluessel:
    tabelle: str
    spalten: list[str]
    ziel: str
    ziel_spalten: list[str]
    name: str = ""
    bei_loeschen: str = "NO ACTION"
    bei_aendern: str = "NO ACTION"

    @property
    def schluessel(self) -> str:
        return f"{self.tabelle}({','.join(self.spalten)})->{self.ziel}({','.join(self.ziel_spalten)})"


@dataclass
class Tabelle:
    name: str
    spalten: list[Spalte] = field(default_factory=list)
    eindeutig: list[tuple[str, ...]] = field(default_factory=list)  # PK und UNIQUE-Gruppen

    @property
    def pk(self) -> list[str]:
        return [s.name for s in self.spalten if s.pk]


@dataclass
class Modell:
    art: str
    schema: str
    tabellen: dict[str, Tabelle] = field(default_factory=dict)
    fks: list[Fremdschluessel] = field(default_factory=list)

    def fk_spalten(self, tabelle: str) -> set[str]:
        return {s for f in self.fks if f.tabelle == tabelle for s in f.spalten}

    def kardinalitaet(self, fk: Fremdschluessel) -> str:
        """„1:1“, wenn die FK-Spalten selbst eindeutig sind, sonst „1:n“."""
        t = self.tabellen.get(fk.tabelle)
        if t and any(set(g) == set(fk.spalten) for g in t.eindeutig):
            return "1:1"
        return "1:n"

    def zwischentabelle(self, name: str) -> bool:
        """n:m-Verbindungstabelle: mindestens zwei FKs, und der Primärschlüssel besteht nur aus FK-Spalten."""
        t = self.tabellen.get(name)
        eigene = [f for f in self.fks if f.tabelle == name]
        if not t or len(eigene) < 2 or not t.pk:
            return False
        return set(t.pk) <= self.fk_spalten(name) and len({f.ziel for f in eigene}) >= 2

    def n_zu_m(self) -> list[tuple[str, str, str]]:
        """(tabelle_a, zwischentabelle, tabelle_b) für jede erkannte n:m-Beziehung."""
        erg = []
        for name in self.tabellen:
            if self.zwischentabelle(name):
                ziele = sorted({f.ziel for f in self.fks if f.tabelle == name})
                erg.append((ziele[0], name, ziele[1]))
        return erg


# --- Metadaten lesen ----------------------------------------------------------------------------------------------
def _sqlite(t: Treiber, schema: str, tabellen: list[str]):
    with t.sperre:
        return _sqlite_gesperrt(t, schema, tabellen)


def _sqlite_gesperrt(t: Treiber, schema: str, tabellen: list[str]):
    s = t.zitiere(schema or "main")
    fks, eind = [], {}
    for tab in tabellen:
        gruppen: dict[int, list] = {}
        for r in t.conn.execute(f"PRAGMA {s}.foreign_key_list({t.zitiere(tab)})").fetchall():
            gruppen.setdefault(r[0], []).append(r)
        for nr, zeilen in sorted(gruppen.items()):
            zeilen.sort(key=lambda r: r[1])
            ziel = zeilen[0][2]
            ziel_sp = [r[4] for r in zeilen]
            if any(z is None for z in ziel_sp):  # REFERENCES ziel ohne Spalte = dessen Primärschlüssel
                ziel_sp = [x.name for x in t.spalten(schema, ziel) if x.pk]
            fks.append(Fremdschluessel(tab, [r[3] for r in zeilen], ziel, ziel_sp, f"fk_{tab}_{nr}",
                                       zeilen[0][6] or "NO ACTION", zeilen[0][5] or "NO ACTION"))
        g = []
        for idx in t.conn.execute(f"PRAGMA {s}.index_list({t.zitiere(tab)})").fetchall():
            if idx[2]:
                g.append(tuple(r[2] for r in t.conn.execute(f"PRAGMA {s}.index_info({t.zitiere(idx[1])})").fetchall()))
        eind[tab] = g
    return fks, eind


def _duckdb(t: Treiber, schema: str, tabellen: list[str]):
    fks, eind = [], {n: [] for n in tabellen}
    for tab, typ, sp, ziel, ziel_sp, name in t._q(
            "SELECT table_name, constraint_type, constraint_column_names, referenced_table, referenced_column_names, "
            "constraint_name FROM duckdb_constraints() WHERE schema_name = ? AND constraint_type IN "
            "('FOREIGN KEY','PRIMARY KEY','UNIQUE')", [schema]):
        if tab not in eind:
            continue
        if typ == "FOREIGN KEY":
            fks.append(Fremdschluessel(tab, list(sp), ziel, list(ziel_sp), name or ""))
        else:
            eind[tab].append(tuple(sp))
    return fks, eind


AKTION_PG = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


def _postgres(t: Treiber, schema: str, tabellen: list[str]):
    fks, eind = [], {n: [] for n in tabellen}
    rows = t.abfrage(
        "SELECT c.conname, c.contype, cl.relname, ziel.relname, c.confdeltype, c.confupdtype, "
        "ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, i) JOIN pg_attribute a "
        "      ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.i), "
        "ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n, i) JOIN pg_attribute a "
        "      ON a.attrelid = c.confrelid AND a.attnum = k.n ORDER BY k.i) "
        "FROM pg_constraint c JOIN pg_class cl ON cl.oid = c.conrelid JOIN pg_namespace n ON n.oid = cl.relnamespace "
        "LEFT JOIN pg_class ziel ON ziel.oid = c.confrelid "
        "WHERE n.nspname = %s AND c.contype IN ('f','p','u') ORDER BY c.conname", (schema,), 100000).zeilen
    for name, typ, tab, ziel, d, u, sp, zsp in rows:
        if tab not in eind:
            continue
        if typ == "f":
            fks.append(Fremdschluessel(tab, list(sp), ziel, list(zsp or []), name, AKTION_PG.get(d, "NO ACTION"),
                                       AKTION_PG.get(u, "NO ACTION")))
        else:
            eind[tab].append(tuple(sp))
    return fks, eind


def _mysql(t: Treiber, schema: str, tabellen: list[str]):
    fks, eind = {}, {n: [] for n in tabellen}
    for name, tab, sp, ziel, zsp, d, u in t.abfrage(
            "SELECT k.CONSTRAINT_NAME, k.TABLE_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME, "
            "r.DELETE_RULE, r.UPDATE_RULE FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA "
            "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION", (schema,), 100000).zeilen:
        f = fks.setdefault((tab, name), Fremdschluessel(tab, [], ziel, [], name, d, u))
        f.spalten.append(sp)
        f.ziel_spalten.append(zsp)
    gruppen: dict = {}
    for tab, idx, sp in t.abfrage(
            "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s "
            "AND NON_UNIQUE = 0 ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX", (schema,), 100000).zeilen:
        gruppen.setdefault((tab, idx), []).append(sp)
    for (tab, _), sp in gruppen.items():
        if tab in eind:
            eind[tab].append(tuple(sp))
    return [f for f in fks.values() if f.tabelle in eind], eind


AKTION_MS = {"NO_ACTION": "NO ACTION", "CASCADE": "CASCADE", "SET_NULL": "SET NULL", "SET_DEFAULT": "SET DEFAULT"}


def _mssql(t: Treiber, schema: str, tabellen: list[str]):
    fks, eind = {}, {n: [] for n in tabellen}
    for name, tab, sp, ziel, zsp, d, u in t.abfrage(
            "SELECT fk.name, tp.name, cp.name, tr.name, cr.name, fk.delete_referential_action_desc, "
            "fk.update_referential_action_desc FROM sys.foreign_keys fk "
            "JOIN sys.foreign_key_columns fc ON fc.constraint_object_id = fk.object_id "
            "JOIN sys.tables tp ON tp.object_id = fk.parent_object_id JOIN sys.schemas s ON s.schema_id = tp.schema_id "
            "JOIN sys.columns cp ON cp.object_id = fc.parent_object_id AND cp.column_id = fc.parent_column_id "
            "JOIN sys.tables tr ON tr.object_id = fk.referenced_object_id "
            "JOIN sys.columns cr ON cr.object_id = fc.referenced_object_id AND cr.column_id = fc.referenced_column_id "
            "WHERE s.name = %s ORDER BY fk.name, fc.constraint_column_id", (schema,), 100000).zeilen:
        f = fks.setdefault((tab, name), Fremdschluessel(tab, [], ziel, [], name, AKTION_MS.get(d, "NO ACTION"),
                                                       AKTION_MS.get(u, "NO ACTION")))
        f.spalten.append(sp)
        f.ziel_spalten.append(zsp)
    gruppen: dict = {}
    for tab, idx, sp in t.abfrage(
            "SELECT t.name, i.name, c.name FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id JOIN sys.index_columns ic ON ic.object_id = i.object_id "
            "AND ic.index_id = i.index_id JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
            "WHERE s.name = %s AND i.is_unique = 1 ORDER BY t.name, i.name, ic.key_ordinal", (schema,), 100000).zeilen:
        gruppen.setdefault((tab, idx), []).append(sp)
    for (tab, _), sp in gruppen.items():
        if tab in eind:
            eind[tab].append(tuple(sp))
    return [f for f in fks.values() if f.tabelle in eind], eind


LESER = {"sqlite": _sqlite, "duckdb": _duckdb, "postgresql": _postgres, "mysql": _mysql, "mssql": _mssql}


def lade(t: Treiber, schema: str) -> Modell:
    """Liest Tabellen, Spalten, eindeutige Schlüssel und Fremdschlüssel eines Schemas."""
    namen = t.objekte(schema)["tabellen"]
    m = Modell(t.art, schema)
    for n in namen:
        m.tabellen[n] = Tabelle(n, t.spalten(schema, n))
    fks, eind = LESER[t.art](t, schema, namen)
    m.fks = [f for f in fks if f.ziel in m.tabellen]
    for n, g in eind.items():
        if n in m.tabellen:
            pk = tuple(m.tabellen[n].pk)
            m.tabellen[n].eindeutig = list(dict.fromkeys([*( [pk] if pk else []), *g]))
    return m


# --- Layout ---------------------------------------------------------------------------------------------------------
def ebenen(m: Modell) -> dict[str, int]:
    """Schicht je Tabelle: Tabellen ohne Fremdschlüssel links, abhängige rechts davon (Zyklen werden aufgebrochen)."""
    abh = {n: {f.ziel for f in m.fks if f.tabelle == n and f.ziel != n} for n in m.tabellen}
    ebene: dict[str, int] = {}
    rest = set(m.tabellen)
    stufe = 0
    while rest:
        frei = sorted(n for n in rest if not (abh[n] & rest))
        if not frei:  # Zyklus: die Tabelle mit den wenigsten offenen Abhängigkeiten zuerst
            frei = [min(sorted(rest), key=lambda n: len(abh[n] & rest))]
        for n in frei:
            ebene[n] = stufe
        rest -= set(frei)
        stufe += 1
    return ebene


def auto_layout(m: Modell, breite: float = 260, abstand_x: float = 120, abstand_y: float = 40,
                hoehe=lambda t: 40 + 22 * len(t.spalten)) -> dict[str, tuple[float, float]]:
    """Ruhiges Layout: je zusammenhängender Gruppe steht die meistreferenzierte Tabelle in der Mitte, abhängige
    Tabellen in Spalten links und rechts daneben (Abstand nach Beziehungs-Entfernung). Tabellen ohne Beziehung
    stehen kompakt in einem Raster rechts daneben. Spaltenweise gestapelt -> keine Überlappungen."""
    from collections import deque
    from math import ceil, sqrt

    nachbarn = {n: set() for n in m.tabellen}
    rein = {n: 0 for n in m.tabellen}
    for f in m.fks:
        if f.tabelle in nachbarn and f.ziel in nachbarn and f.tabelle != f.ziel:
            nachbarn[f.tabelle].add(f.ziel)
            nachbarn[f.ziel].add(f.tabelle)
            rein[f.ziel] += 1
    rang = lambda n: (-rein[n], -len(nachbarn[n]), n)  # noqa: E731
    h = {n: hoehe(t) for n, t in m.tabellen.items()}
    raster = breite + abstand_x

    gruppen, gesehen = [], set()
    for start in sorted(nachbarn, key=rang):
        if start in gesehen or not nachbarn[start]:
            continue
        gruppe, stapel = [], [start]
        while stapel:
            x = stapel.pop()
            if x not in gesehen:
                gesehen.add(x)
                gruppe.append(x)
                stapel.extend(nachbarn[x] - gesehen)
        gruppen.append(gruppe)
    gruppen.sort(key=lambda g: (-len(g), rang(min(g, key=rang))))

    pos: dict[str, tuple[float, float]] = {}
    x0 = 0.0
    for gruppe in gruppen:
        hub = min(gruppe, key=rang)
        spalte = {hub: 0}
        hoehe_seite = {-1: 0.0, 1: 0.0}
        reihenfolge = [hub]
        q = deque([hub])
        while q:
            x = q.popleft()
            for k in sorted(nachbarn[x] - set(spalte), key=rang):
                if spalte[x] == 0:
                    seite = 1 if hoehe_seite[1] <= hoehe_seite[-1] else -1
                    hoehe_seite[seite] += h[k] + abstand_y
                    spalte[k] = seite
                else:
                    spalte[k] = spalte[x] + (1 if spalte[x] > 0 else -1)
                reihenfolge.append(k)
                q.append(k)
        je_spalte: dict[int, list[str]] = {}
        for n in reihenfolge:
            je_spalte.setdefault(spalte[n], []).append(n)
        links = min(je_spalte)
        for c, namen in je_spalte.items():
            gesamt = sum(h[n] for n in namen) + abstand_y * (len(namen) - 1)
            y = -gesamt / 2
            for n in namen:
                pos[n] = (x0 + (c - links) * raster, y)
                y += h[n] + abstand_y
        x0 += (max(je_spalte) - links + 1) * raster + abstand_x

    einzeln = sorted((n for n in nachbarn if not nachbarn[n]), key=lambda n: n)
    if einzeln:
        oben = min((y for _, y in pos.values()), default=0.0)
        spalten = max(1, ceil(sqrt(len(einzeln) / 2)))
        y_je = [oben] * spalten
        for n in sorted(einzeln, key=lambda n: -h[n]):
            c = y_je.index(min(y_je))
            pos[n] = (x0 + c * (breite + abstand_x / 2), y_je[c])
            y_je[c] += h[n] + abstand_y / 2
    if pos:
        dy = min(y for _, y in pos.values())
        pos = {n: (x, y - dy) for n, (x, y) in pos.items()}
    return pos


LAYOUT_VERSION = 2  # Positionen aus älterem Layout werden ignoriert (neu angeordnet)


def _positions_datei():
    return verbindungen.ordner() / "diagramme.json"


def positionen_laden(verbindung_id: str, schema: str) -> dict[str, tuple[float, float]]:
    try:
        alle = json.loads(_positions_datei().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {k: tuple(v) for k, v in alle.get(f"{verbindung_id}|{schema}|{LAYOUT_VERSION}", {}).items()}


def positionen_speichern(verbindung_id: str, schema: str, pos: dict[str, tuple[float, float]]) -> None:
    d = _positions_datei()
    try:
        alle = json.loads(d.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        alle = {}
    alle[f"{verbindung_id}|{schema}|{LAYOUT_VERSION}"] = {k: [round(x, 1), round(y, 1)] for k, (x, y) in pos.items()}
    d.write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
    d.chmod(0o600)


# --- DDL je Dialekt -------------------------------------------------------------------------------------------------
def dialekt(art: str) -> Treiber:
    """Unverbundener Treiber nur zum Zitieren von Bezeichnern."""
    return KLASSEN[art]()


def typ_nativ(art: str, typ: str) -> str:
    """Generischer Typ (z. B. „ganzzahl“) → Dialekt; sonst der eingegebene Typ unverändert."""
    return NATIV[art].get(typ, typ)


def _spalte_def(d: Treiber, s: Spalte, standard: str = "") -> str:
    teil = f"{d.zitiere(s.name)} {typ_nativ(d.art, s.typ)}"
    if standard:
        teil += f" DEFAULT {standard}"
    if not s.nullbar:
        teil += " NOT NULL"
    return teil


def _fk_def(d: Treiber, schema: str, f: Fremdschluessel, mit_name: bool = True) -> str:
    name = f"CONSTRAINT {d.zitiere(f.name)} " if mit_name and f.name else ""
    regeln = ""
    if d.art == "duckdb":  # DuckDB kennt nur NO ACTION/RESTRICT
        pass
    elif f.bei_loeschen and f.bei_loeschen != "NO ACTION":
        regeln += f" ON DELETE {f.bei_loeschen}"
    if f.bei_aendern and f.bei_aendern != "NO ACTION":
        regeln += f" ON UPDATE {f.bei_aendern}"
    ziel = d.zitiere(f.ziel) if d.art == "sqlite" else d.voll(schema, f.ziel)
    return (f"{name}FOREIGN KEY ({', '.join(d.zitiere(s) for s in f.spalten)}) REFERENCES {ziel} "
            f"({', '.join(d.zitiere(s) for s in f.ziel_spalten)}){regeln}")


def ddl_tabelle_neu(art: str, schema: str, name: str, spalten: list[Spalte], fks: list[Fremdschluessel] = ()) -> list[str]:
    d = dialekt(art)
    teile = [_spalte_def(d, s) for s in spalten]
    pks = [d.zitiere(s.name) for s in spalten if s.pk]
    if pks:
        teile.append(f"PRIMARY KEY ({', '.join(pks)})")
    teile += [_fk_def(d, schema, f) for f in fks]
    return [f"CREATE TABLE {d.voll(schema, name)} (\n  " + ",\n  ".join(teile) + "\n)"]


def ddl_spalte_neu(art: str, schema: str, tabelle: str, s: Spalte, standard: str = "") -> list[str]:
    d = dialekt(art)
    if art == "sqlite" and not s.nullbar and not standard:
        raise ValueError("SQLite kann eine NOT-NULL-Spalte nur mit Standardwert nachträglich hinzufügen.")
    add = "ADD" if art == "mssql" else "ADD COLUMN"
    return [f"ALTER TABLE {d.voll(schema, tabelle)} {add} {_spalte_def(d, s, standard)}"]


def ddl_spalte_aendern(m: Modell, tabelle: str, alt: str, neu: Spalte) -> list[str]:
    """Umbenennen und/oder Typ/NULL ändern. SQLite: Umbenennen direkt, alles andere per Neuaufbau."""
    art, schema, d = m.art, m.schema, dialekt(m.art)
    t = m.tabellen[tabelle]
    vorher = next(s for s in t.spalten if s.name == alt)
    voll = d.voll(schema, tabelle)
    aus: list[str] = []
    umbenennen = neu.name != alt
    typ_neu = typ_nativ(art, neu.typ)
    typ_anders = typ_neu.lower() != (vorher.typ or "").lower()
    null_anders = neu.nullbar != vorher.nullbar
    if art == "sqlite":
        if typ_anders or null_anders:
            spalten = [Spalte(neu.name, typ_neu, neu.nullbar, s.pk) if s.name == alt else s for s in t.spalten]
            zuordnung = {s.name: (neu.name if s.name == alt else s.name) for s in t.spalten}
            fks = [Fremdschluessel(f.tabelle, [zuordnung.get(c, c) for c in f.spalten], f.ziel, f.ziel_spalten, f.name,
                                   f.bei_loeschen, f.bei_aendern) for f in m.fks if f.tabelle == tabelle]
            return neuaufbau(m, tabelle, spalten, fks, zuordnung)
        if umbenennen:
            aus.append(f"ALTER TABLE {voll} RENAME COLUMN {d.zitiere(alt)} TO {d.zitiere(neu.name)}")
        return aus
    name = alt
    if umbenennen:
        if art == "mssql":
            aus.append(f"EXEC sp_rename '{schema}.{tabelle}.{alt}', '{neu.name}', 'COLUMN'")
        else:
            aus.append(f"ALTER TABLE {voll} RENAME COLUMN {d.zitiere(alt)} TO {d.zitiere(neu.name)}")
        name = neu.name
    q = d.zitiere(name)
    if art == "postgresql" or art == "duckdb":
        if typ_anders:
            aus.append(f"ALTER TABLE {voll} ALTER COLUMN {q} TYPE {typ_neu}"
                       + (f" USING {q}::{typ_neu}" if art == "postgresql" else ""))
        if null_anders:
            aus.append(f"ALTER TABLE {voll} ALTER COLUMN {q} {'DROP' if neu.nullbar else 'SET'} NOT NULL")
    elif art == "mysql":
        if typ_anders or null_anders:
            aus.append(f"ALTER TABLE {voll} MODIFY COLUMN {q} {typ_neu}{'' if neu.nullbar else ' NOT NULL'}")
    elif art == "mssql":
        if typ_anders or null_anders:
            aus.append(f"ALTER TABLE {voll} ALTER COLUMN {q} {typ_neu} {'NULL' if neu.nullbar else 'NOT NULL'}")
    return aus


def fk_name(f: Fremdschluessel) -> str:
    roh = f"fk_{f.tabelle}_{'_'.join(f.spalten)}"
    return re.sub(r"\W+", "_", roh)[:60]


def ddl_fk_neu(m: Modell, f: Fremdschluessel) -> list[str]:
    if not f.name:
        f.name = fk_name(f)
    if m.art in OHNE_ALTER_FK:
        t = m.tabellen[f.tabelle]
        alte = [x for x in m.fks if x.tabelle == f.tabelle]
        return neuaufbau(m, f.tabelle, t.spalten, alte + [f], {s.name: s.name for s in t.spalten})
    d = dialekt(m.art)
    return [f"ALTER TABLE {d.voll(m.schema, f.tabelle)} ADD {_fk_def(d, m.schema, f)}"]


def neuaufbau(m: Modell, tabelle: str, spalten: list[Spalte], fks: list[Fremdschluessel],
              zuordnung: dict[str, str]) -> list[str]:
    """Für SQLite/DuckDB: neue Tabelle anlegen, Daten kopieren, alte löschen, umbenennen."""
    d = dialekt(m.art)
    tmp = f"{tabelle}__neu"
    neu = ddl_tabelle_neu(m.art, m.schema, tmp, spalten, fks)
    alt_sp = [a for a in zuordnung]
    neu_sp = [zuordnung[a] for a in alt_sp]
    return [*neu,
            f"INSERT INTO {d.voll(m.schema, tmp)} ({', '.join(d.zitiere(s) for s in neu_sp)}) "
            f"SELECT {', '.join(d.zitiere(s) for s in alt_sp)} FROM {d.voll(m.schema, tabelle)}",
            f"DROP TABLE {d.voll(m.schema, tabelle)}",
            f"ALTER TABLE {d.voll(m.schema, tmp)} RENAME TO {d.zitiere(tabelle)}"]


def hinweise(art: str, anweisungen: list[str]) -> list[str]:
    h = []
    if art == "mysql":
        h.append("MySQL/MariaDB bestätigt DDL sofort – ein Zurückrollen bei Fehlern ist nicht möglich.")
    if any("__neu" in a for a in anweisungen):
        h.append(f"{'SQLite' if art == 'sqlite' else 'DuckDB'} kann das nicht per ALTER TABLE – die Tabelle wird neu "
                 "aufgebaut (anlegen, Daten kopieren, alte löschen, umbenennen).")
        if art == "duckdb":
            h.append("DuckDB unterstützt bei Fremdschlüsseln kein CASCADE/SET NULL – es gilt immer NO ACTION.")
            h.append("DuckDB lehnt das Löschen ab, wenn andere Tabellen auf diese Tabelle verweisen.")
    return h


def ausfuehren(t: Treiber, anweisungen: list[str]) -> None:
    """Führt DDL in einer Transaktion aus; bei Fehler alles zurück. SQLite: Fremdschlüsselprüfung während des Umbaus aus."""
    if t.schreibschutz:
        raise PermissionError("Die Verbindung ist schreibgeschützt.")
    sqlite_umbau = t.art == "sqlite" and any("__neu" in a for a in anweisungen)
    if sqlite_umbau:
        t.abfrage("PRAGMA foreign_keys = OFF")
    try:
        t.beginnen()
        try:
            for a in anweisungen:
                t.abfrage(a)
            if sqlite_umbau:
                fehler = t.abfrage("PRAGMA foreign_key_check").zeilen
                if fehler:
                    raise ValueError(f"Fremdschlüssel verletzt: {len(fehler)} Zeile(n) passen nicht zur Zieltabelle.")
            t.bestaetigen()
        except Exception:
            try:
                t.zuruecknehmen()
            except Exception:
                pass
            raise
    finally:
        if sqlite_umbau:
            t.abfrage("PRAGMA foreign_keys = ON")


# --- Vorschläge ohne KI (Heuristik) ---------------------------------------------------------------------------------
def vorschlaege(m: Modell) -> list[Fremdschluessel]:
    """Spalten wie „kunde_id“/„kundeId“, die auf den Primärschlüssel einer Tabelle „kunde(n)“ passen, aber kein FK sind."""
    vorhanden = {(f.tabelle, tuple(f.spalten)) for f in m.fks}
    erg = []
    for tab in m.tabellen.values():
        for s in tab.spalten:
            if (tab.name, (s.name,)) in vorhanden or s.pk and len(tab.pk) == 1:
                continue
            mt = re.match(r"(.+?)_?[iI][dD]$", s.name)
            if not mt:
                continue
            stamm = mt.group(1).lower().rstrip("_")
            for ziel in m.tabellen.values():
                zn = ziel.name.lower()
                if ziel.name == tab.name or len(ziel.pk) != 1:
                    continue
                if zn in (stamm, stamm + "s", stamm + "n", stamm + "en", stamm + "e") or stamm in (zn.rstrip("s"), zn.rstrip("n")):
                    erg.append(Fremdschluessel(tab.name, [s.name], ziel.name, ziel.pk))
                    break
    for f in erg:
        f.name = fk_name(f)
    return erg
