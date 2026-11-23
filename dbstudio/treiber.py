"""Einheitliche Treiber-Schnittstelle für PostgreSQL, MySQL/MariaDB, SQLite, DuckDB und SQL Server.

Jeder Treiber liefert Metadaten (Schemas, Tabellen, Views, Indizes, Funktionen, Spalten), führt SQL aus
(Ergebnis mit Nachladen statt alles auf einmal), kann seitenweise Tabellenzeilen holen und eine laufende
Abfrage abbrechen. Typen werden auf eine kleine gemeinsame Menge abgebildet, damit Tabellen zwischen
Systemen kopiert werden können.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

ARTEN = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL / MariaDB",
    "sqlite": "SQLite",
    "duckdb": "DuckDB",
    "mssql": "SQL Server",
}
STANDARD_PORT = {"postgresql": 5432, "mysql": 3306, "mssql": 1433}
DATEI_ARTEN = {"sqlite", "duckdb"}


class DBFehler(Exception):
    """Fehler aus der Datenbank, mit lesbarer Meldung."""


def verfuegbar(art: str) -> str:
    """Leer, wenn der Python-Treiber da ist, sonst der Hinweis zum Nachinstallieren."""
    modul = {"postgresql": "psycopg", "mysql": "pymysql", "duckdb": "duckdb", "mssql": "pymssql"}.get(art)
    if not modul:
        return ""
    try:
        __import__(modul)
    except ImportError:
        paket = {"psycopg": "psycopg[binary]", "pymysql": "PyMySQL"}.get(modul, modul)
        return f"Treiber fehlt: pip install {paket}"
    return ""


@dataclass
class Spalte:
    name: str
    typ: str
    nullbar: bool = True
    pk: bool = False

    @property
    def generisch(self) -> str:
        return generischer_typ(self.typ)


@dataclass
class Ergebnis:
    spalten: list[str] = field(default_factory=list)
    zeilen: list[tuple] = field(default_factory=list)
    betroffen: int = -1
    dauer: float = 0.0
    mehr: bool = False
    meldung: str = ""
    _cursor: object = None
    _treiber: "Treiber | None" = None
    _puffer: list = field(default_factory=list)  # die eine vorausgelesene Zeile, an der „mehr“ erkannt wurde

    def weitere(self, anzahl: int = 1000) -> list[tuple]:
        """Lädt die nächsten Zeilen nach (Streaming statt alles auf einmal)."""
        if not self.mehr or self._cursor is None:
            return []
        with self._treiber.sperre:
            neu = self._puffer + [tuple(z) for z in self._cursor.fetchmany(anzahl + 1 - len(self._puffer))]
        self.mehr = len(neu) > anzahl
        self._puffer = neu[anzahl:anzahl + 1]
        neu = neu[:anzahl]
        self.zeilen.extend(neu)
        if not self.mehr:
            self.schliessen()
        return neu

    def schliessen(self):
        if self._cursor is not None:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None


# --- Typen ------------------------------------------------------------------------------------------------------------
GENERISCH = ("ganzzahl", "grosse_ganzzahl", "kommazahl", "dezimal", "text", "wahrheitswert", "datum", "zeitstempel",
             "zeit", "binaer", "json", "uuid")


def generischer_typ(typ: str) -> str:
    t = (typ or "").lower()
    if any(k in t for k in ("bigint", "int8", "hugeint", "ubigint")):
        return "grosse_ganzzahl"
    if t in ("bool", "boolean", "bit", "tinyint(1)") or t.startswith("bool"):
        return "wahrheitswert"
    if "int" in t or t in ("serial", "integer"):
        return "ganzzahl"
    if any(k in t for k in ("numeric", "decimal", "money")):
        return "dezimal"
    if any(k in t for k in ("real", "double", "float")):
        return "kommazahl"
    if "uuid" in t or "uniqueidentifier" in t:
        return "uuid"
    if "json" in t:
        return "json"
    if any(k in t for k in ("timestamp", "datetime")):
        return "zeitstempel"
    if t.startswith("date"):
        return "datum"
    if t.startswith("time"):
        return "zeit"
    if any(k in t for k in ("blob", "bytea", "binary", "image")):
        return "binaer"
    return "text"


NATIV = {
    "postgresql": {"ganzzahl": "integer", "grosse_ganzzahl": "bigint", "kommazahl": "double precision",
                   "dezimal": "numeric", "text": "text", "wahrheitswert": "boolean", "datum": "date",
                   "zeitstempel": "timestamp", "zeit": "time", "binaer": "bytea", "json": "jsonb", "uuid": "uuid"},
    "mysql": {"ganzzahl": "INT", "grosse_ganzzahl": "BIGINT", "kommazahl": "DOUBLE", "dezimal": "DECIMAL(38,10)",
              "text": "TEXT", "wahrheitswert": "TINYINT(1)", "datum": "DATE", "zeitstempel": "DATETIME",
              "zeit": "TIME", "binaer": "LONGBLOB", "json": "JSON", "uuid": "CHAR(36)"},
    "sqlite": {"ganzzahl": "INTEGER", "grosse_ganzzahl": "INTEGER", "kommazahl": "REAL", "dezimal": "NUMERIC",
               "text": "TEXT", "wahrheitswert": "INTEGER", "datum": "TEXT", "zeitstempel": "TEXT", "zeit": "TEXT",
               "binaer": "BLOB", "json": "TEXT", "uuid": "TEXT"},
    "duckdb": {"ganzzahl": "INTEGER", "grosse_ganzzahl": "BIGINT", "kommazahl": "DOUBLE", "dezimal": "DECIMAL(38,10)",
               "text": "VARCHAR", "wahrheitswert": "BOOLEAN", "datum": "DATE", "zeitstempel": "TIMESTAMP",
               "zeit": "TIME", "binaer": "BLOB", "json": "JSON", "uuid": "UUID"},
    "mssql": {"ganzzahl": "INT", "grosse_ganzzahl": "BIGINT", "kommazahl": "FLOAT", "dezimal": "DECIMAL(38,10)",
              "text": "NVARCHAR(MAX)", "wahrheitswert": "BIT", "datum": "DATE", "zeitstempel": "DATETIME2",
              "zeit": "TIME", "binaer": "VARBINARY(MAX)", "json": "NVARCHAR(MAX)", "uuid": "UNIQUEIDENTIFIER"},
}


# --- Hilfen -----------------------------------------------------------------------------------------------------------
def anweisungen(sql: str) -> list[str]:
    """Teilt ein Skript an Semikolons, die nicht in Strings, Bezeichnern, Kommentaren oder $$-Blöcken stehen."""
    teile, puffer, i, n = [], [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            puffer.append(sql[i:j + 1]); i = j + 1; continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            puffer.append(sql[i:j]); i = j; continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            puffer.append(sql[i:j]); i = j; continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                marke = m.group(0)
                j = sql.find(marke, i + len(marke))
                j = n if j < 0 else j + len(marke)
                puffer.append(sql[i:j]); i = j; continue
        if c == ";":
            teile.append("".join(puffer)); puffer = []; i += 1; continue
        puffer.append(c); i += 1
    teile.append("".join(puffer))
    return [t.strip() for t in teile if re.sub(r"--[^\n]*|/\*.*?\*/", "", t, flags=re.S).strip()]


# --- Basis ------------------------------------------------------------------------------------------------------------
class Treiber:
    art = ""
    platzhalter = "?"
    zitat = '"'

    def __init__(self):
        self.conn = None
        self.sperre = threading.RLock()
        self.schreibschutz = False
        self.aktuelles_schema: str | None = None

    # Verbindung
    def verbinden(self, cfg: dict, passwort: str | None) -> "Treiber":
        raise NotImplementedError

    def schliessen(self):
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None

    def version(self) -> str:
        return ""

    # Bezeichner
    def zitiere(self, name: str) -> str:
        z = self.zitat
        return z + name.replace(z, z + z) + z

    def voll(self, schema: str | None, tabelle: str) -> str:
        return f"{self.zitiere(schema)}.{self.zitiere(tabelle)}" if schema else self.zitiere(tabelle)

    # Metadaten
    def schemas(self) -> list[str]:
        raise NotImplementedError

    def objekte(self, schema: str) -> dict[str, list[str]]:
        raise NotImplementedError

    def spalten(self, schema: str, tabelle: str) -> list[Spalte]:
        raise NotImplementedError

    def standard_schema(self) -> str:
        s = self.schemas()
        return s[0] if s else ""

    def tabellen_zahlen(self) -> dict[str, int]:
        """Schema -> Anzahl Tabellen (Reihenfolge wie schemas())."""
        return {s: len(self.objekte(s).get("tabellen", [])) for s in self.schemas()}

    def bestes_schema(self, gemerkt: str | None = None, zahlen: dict[str, int] | None = None) -> tuple[str, str]:
        """Schema, das beim Verbinden gezeigt wird, und ein Hinweis, falls vom Standard abgewichen wurde.

        Reihenfolge: zuletzt gewähltes Schema (falls noch vorhanden) > Standardschema, wenn es Tabellen hat >
        Schema mit den meisten Tabellen > Standardschema."""
        zahlen = self.tabellen_zahlen() if zahlen is None else zahlen
        std = self.standard_schema()
        if gemerkt and gemerkt in zahlen:
            return gemerkt, ""
        if not zahlen or zahlen.get(std, 0) > 0:
            return std, ""
        reihenfolge = list(zahlen)
        best = max(reihenfolge, key=lambda s: (zahlen[s], -reihenfolge.index(s)))
        if zahlen[best] == 0:
            return std, ""
        return best, f"„{std}“ ist leer – zeige Schema „{best}“."

    def setze_schema(self, schema: str) -> None:
        """Arbeitsschema für unqualifizierte Namen (search_path/USE/...). Basis: nur merken."""
        self.aktuelles_schema = schema

    # Ausführen
    def _cursor(self):
        return self.conn.cursor()

    def abfrage(self, sql: str, params=None, limit: int = 1000) -> Ergebnis:
        start = time.perf_counter()
        with self.sperre:
            cur = self._cursor()
            try:
                if params is None:
                    cur.execute(sql)
                else:
                    cur.execute(sql, params)
            except Exception as e:
                try:
                    cur.close()
                except Exception:
                    pass
                self._nach_fehler()
                raise DBFehler(self.fehlertext(e)) from e
            erg = Ergebnis(_treiber=self)
            if cur.description:
                erg.spalten = [d[0] for d in cur.description]
                zeilen = [tuple(z) for z in cur.fetchmany(limit + 1)]
                erg.mehr = len(zeilen) > limit
                erg.zeilen = zeilen[:limit]
                if erg.mehr:
                    erg._cursor, erg._puffer = cur, zeilen[limit:]
                else:
                    cur.close()
            else:
                erg.betroffen = getattr(cur, "rowcount", -1)
                cur.close()
            self._nach_anweisung()
        erg.dauer = time.perf_counter() - start
        return erg

    def ausfuehren_viele(self, sql: str, zeilen: list[tuple]):
        with self.sperre:
            cur = self._cursor()
            try:
                cur.executemany(sql, zeilen)
            except Exception as e:
                self._nach_fehler()
                raise DBFehler(self.fehlertext(e)) from e
            finally:
                cur.close()

    def _nach_anweisung(self):
        """Im Autocommit-Betrieb nichts; SQLite/DuckDB bestätigen sofort, außer in einer offenen Transaktion."""

    def _nach_fehler(self):
        pass

    # Transaktionen (für Bearbeitungen im Datenraster)
    def beginnen(self):
        self.abfrage("BEGIN")

    def bestaetigen(self):
        self.abfrage("COMMIT")

    def zuruecknehmen(self):
        self.abfrage("ROLLBACK")

    def abbrechen(self):
        """Bricht die laufende Abfrage ab (aus einem anderen Thread aufgerufen)."""

    def fehlertext(self, e: Exception) -> str:
        text = str(e).strip() or type(e).__name__
        return text.splitlines()[0][:400] if len(text) > 400 else text

    # Tabellen seitenweise
    def zeilen(self, schema: str, tabelle: str, offset: int = 0, limit: int = 200, sortierung: str = "",
               filter_: str = "") -> Ergebnis:
        sql = f"SELECT * FROM {self.voll(schema, tabelle)}"
        if filter_.strip():
            sql += f" WHERE {filter_}"
        if sortierung:
            sql += f" ORDER BY {sortierung}"
        sql += self.seite(offset, limit, bool(sortierung))
        return self.abfrage(sql, limit=limit)

    def seite(self, offset: int, limit: int, sortiert: bool) -> str:
        return f" LIMIT {int(limit)} OFFSET {int(offset)}"

    def anzahl(self, schema: str, tabelle: str, filter_: str = "") -> int:
        sql = f"SELECT COUNT(*) FROM {self.voll(schema, tabelle)}"
        if filter_.strip():
            sql += f" WHERE {filter_}"
        return int(self.abfrage(sql).zeilen[0][0])

    def explain(self, sql: str) -> Ergebnis:
        return self.abfrage(f"EXPLAIN {sql}")

    def ddl_tabelle(self, schema: str | None, tabelle: str, spalten: list[Spalte]) -> str:
        nativ = NATIV[self.art]
        teile = [f"{self.zitiere(s.name)} {nativ[s.generisch]}{'' if s.nullbar else ' NOT NULL'}" for s in spalten]
        pks = [self.zitiere(s.name) for s in spalten if s.pk]
        if pks:
            teile.append(f"PRIMARY KEY ({', '.join(pks)})")
        return f"CREATE TABLE {self.voll(schema, tabelle)} ({', '.join(teile)})"

    def einfuegen_sql(self, schema: str | None, tabelle: str, spalten: list[str]) -> str:
        ph = ", ".join([self.platzhalter] * len(spalten))
        return f"INSERT INTO {self.voll(schema, tabelle)} ({', '.join(self.zitiere(s) for s in spalten)}) VALUES ({ph})"


# --- SQLite -----------------------------------------------------------------------------------------------------------
class SQLite(Treiber):
    art = "sqlite"

    def verbinden(self, cfg, passwort=None):
        pfad = cfg.get("datei") or ":memory:"
        try:
            self.conn = sqlite3.connect(pfad, check_same_thread=False, isolation_level=None)
        except Exception as e:
            raise DBFehler(self.fehlertext(e)) from e
        self.conn.execute("PRAGMA foreign_keys = ON")
        return self

    def version(self):
        return "SQLite " + sqlite3.sqlite_version

    def voll(self, schema, tabelle):
        return self.zitiere(tabelle) if schema in (None, "", "main") else super().voll(schema, tabelle)

    def schemas(self):
        with self.sperre:
            return [r[1] for r in self.conn.execute("PRAGMA database_list").fetchall()]

    def objekte(self, schema):
        s = self.zitiere(schema)
        with self.sperre:  # eine Verbindung, mehrere Hintergrund-Threads: Metadaten nie verschränkt lesen
            rows = self.conn.execute(f"SELECT type, name FROM {s}.sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        o = {"tabellen": [], "views": [], "indizes": [], "funktionen": []}
        for typ, name in rows:
            {"table": o["tabellen"], "view": o["views"], "index": o["indizes"]}.get(typ, []).append(name)
        return o

    def spalten(self, schema, tabelle):
        with self.sperre:
            rows = self.conn.execute(f"PRAGMA {self.zitiere(schema or 'main')}.table_info({self.zitiere(tabelle)})").fetchall()
        return [Spalte(r[1], r[2] or "", not r[3], bool(r[5])) for r in rows]

    def standard_schema(self):
        return "main"

    def abbrechen(self):
        if self.conn is not None:
            self.conn.interrupt()

    def explain(self, sql):
        return self.abfrage(f"EXPLAIN QUERY PLAN {sql}")


# --- DuckDB -----------------------------------------------------------------------------------------------------------
class DuckDB(Treiber):
    art = "duckdb"

    def verbinden(self, cfg, passwort=None):
        import duckdb
        try:
            self.conn = duckdb.connect(cfg.get("datei") or ":memory:", read_only=bool(cfg.get("nur_lesen_datei")))
        except Exception as e:
            raise DBFehler(self.fehlertext(e)) from e
        return self

    def version(self):
        return "DuckDB " + self._q("SELECT version()")[0][0]

    def _cursor(self):
        # DuckDB-Cursor sind eigene Verbindungen; eine Transaktion gälte nur dort. Also alles über die Hauptverbindung.
        return _DuckCursor(self.conn)

    def _q(self, sql, params=None):
        with self.sperre:
            return self.conn.execute(sql, params or []).fetchall()

    def schemas(self):
        return [r[0] for r in self._q(
            "SELECT schema_name FROM information_schema.schemata WHERE catalog_name = current_database() "
            "AND schema_name NOT IN ('information_schema', 'pg_catalog') ORDER BY 1")]

    def standard_schema(self):
        return "main"

    def setze_schema(self, schema):
        super().setze_schema(schema)
        with self.sperre:
            self.conn.execute(f"SET schema = '{schema.replace(chr(39), chr(39) * 2)}'")

    def objekte(self, schema):
        o = {"tabellen": [], "views": [], "indizes": [], "funktionen": []}
        for name, typ in self._q(
                "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = ? "
                "AND table_catalog = current_database() ORDER BY 1", [schema]):
            (o["views"] if typ == "VIEW" else o["tabellen"]).append(name)
        o["indizes"] = [r[0] for r in self._q(
            "SELECT index_name FROM duckdb_indexes() WHERE schema_name = ? ORDER BY 1", [schema])]
        o["funktionen"] = [r[0] for r in self._q(
            "SELECT DISTINCT function_name FROM duckdb_functions() WHERE schema_name = ? AND NOT internal ORDER BY 1",
            [schema])]
        return o

    def spalten(self, schema, tabelle):
        pk = {r[0] for r in self._q(
            "SELECT unnest(constraint_column_names) FROM duckdb_constraints() WHERE schema_name = ? AND table_name = ? "
            "AND constraint_type = 'PRIMARY KEY'", [schema, tabelle])}
        rows = self._q(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = ? "
            "AND table_name = ? ORDER BY ordinal_position", [schema, tabelle])
        return [Spalte(n, t, nb == "YES", n in pk) for n, t, nb in rows]

    def abbrechen(self):
        if self.conn is not None:
            self.conn.interrupt()

    def ausfuehren_viele(self, sql, zeilen):
        with self.sperre:
            try:
                self.conn.executemany(sql, zeilen)
            except Exception as e:
                raise DBFehler(self.fehlertext(e)) from e


class _DuckCursor:
    def __init__(self, conn):
        self.conn, self.description, self.rowcount = conn, None, -1

    def execute(self, sql, params=None):
        if params is not None:
            self.conn.execute(sql, params)
        else:
            self.conn.execute(sql)
        self.description = self.conn.description
        self.rowcount = -1
        if self.description and [d[0] for d in self.description] == ["Count"] and \
                sql.lstrip()[:6].lower() in ("insert", "update", "delete"):
            self.rowcount = int(self.conn.fetchone()[0])
            self.description = None
        return self

    def executemany(self, sql, zeilen):
        self.conn.executemany(sql, zeilen)

    def fetchmany(self, n):
        return self.conn.fetchmany(n)

    def fetchall(self):
        return self.conn.fetchall()

    def close(self):
        pass


# --- PostgreSQL -------------------------------------------------------------------------------------------------------
class PostgreSQL(Treiber):
    art = "postgresql"
    platzhalter = "%s"

    def verbinden(self, cfg, passwort=None):
        import psycopg
        try:
            self.conn = psycopg.connect(
                host=cfg.get("host") or "localhost", port=int(cfg.get("port") or 5432), dbname=cfg.get("datenbank") or None,
                user=cfg.get("benutzer") or None, password=passwort or None, sslmode=cfg.get("sslmode") or "prefer",
                connect_timeout=10, autocommit=True, application_name="Pi DB Studio")
        except Exception as e:
            raise DBFehler(self.fehlertext(e)) from e
        return self

    def version(self):
        return self.abfrage("SELECT version()").zeilen[0][0].split(" on ")[0]

    def schemas(self):
        return [r[0] for r in self.abfrage(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' "
            "ORDER BY nspname = 'public' DESC, 1").zeilen]

    def standard_schema(self):
        s = self.schemas()
        return "public" if "public" in s else (s[0] if s else "public")

    def tabellen_zahlen(self):
        zahl = dict(self.abfrage(
            "SELECT n.nspname, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r','p','f') GROUP BY 1", limit=100000).zeilen)
        return {s: int(zahl.get(s, 0)) for s in self.schemas()}

    def setze_schema(self, schema):
        super().setze_schema(schema)
        pfad = self.zitiere(schema) + (", public" if schema != "public" else "")
        self.abfrage(f"SET search_path TO {pfad}")

    def objekte(self, schema):
        o = {"tabellen": [], "views": [], "indizes": [], "funktionen": []}
        for name, kind in self.abfrage(
                "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m','i','f') ORDER BY 1", (schema,), 100000).zeilen:
            {"r": o["tabellen"], "p": o["tabellen"], "f": o["tabellen"], "v": o["views"], "m": o["views"],
             "i": o["indizes"]}[kind].append(name)
        o["funktionen"] = [r[0] for r in self.abfrage(
            "SELECT DISTINCT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "LEFT JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e' "
            "WHERE n.nspname = %s AND d.objid IS NULL ORDER BY 1", (schema,), 100000).zeilen]
        return o

    def spalten(self, schema, tabelle):
        rows = self.abfrage(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
            "COALESCE(a.attnum = ANY(i.indkey), false) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary "
            "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
            (schema, tabelle), 100000).zeilen
        return [Spalte(n, t, nb, pk) for n, t, nb, pk in rows]

    def beginnen(self):
        with self.sperre:
            self.conn.autocommit = False

    def bestaetigen(self):
        with self.sperre:
            self.conn.commit()
            self.conn.autocommit = True

    def zuruecknehmen(self):
        with self.sperre:
            self.conn.rollback()
            self.conn.autocommit = True

    def _nach_fehler(self):
        if self.conn is not None and not self.conn.autocommit:
            # eine fehlgeschlagene Anweisung macht die Transaktion unbrauchbar; zurück auf sauberen Stand
            self.conn.rollback()
            self.conn.autocommit = True

    def abbrechen(self):
        if self.conn is not None:
            try:
                self.conn.cancel_safe(timeout=3)
            except AttributeError:
                self.conn.cancel()

    def explain(self, sql):
        return self.abfrage(f"EXPLAIN (FORMAT TEXT) {sql}", limit=100000)

    def fehlertext(self, e):
        diag = getattr(e, "diag", None)
        text = (getattr(diag, "message_primary", None) or str(e)).strip()
        hinweis = getattr(diag, "message_hint", None)
        return f"{text} (Hinweis: {hinweis})" if hinweis else text


# --- MySQL / MariaDB --------------------------------------------------------------------------------------------------
class MySQL(Treiber):
    art = "mysql"
    platzhalter = "%s"
    zitat = "`"

    def verbinden(self, cfg, passwort=None):
        import pymysql
        ssl = {"ssl": {}} if cfg.get("sslmode") in ("require", "verify-ca", "verify-full") else {}
        self._cfg, self._pw = cfg, passwort
        try:
            self.conn = pymysql.connect(host=cfg.get("host") or "localhost", port=int(cfg.get("port") or 3306),
                                        user=cfg.get("benutzer") or None, password=passwort or "",
                                        database=cfg.get("datenbank") or None, autocommit=True, connect_timeout=10,
                                        charset="utf8mb4", **ssl)
        except Exception as e:
            raise DBFehler(self.fehlertext(e)) from e
        return self

    def version(self):
        return "MySQL/MariaDB " + self.abfrage("SELECT VERSION()").zeilen[0][0]

    def schemas(self):
        return [r[0] for r in self.abfrage(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN "
            "('information_schema','mysql','performance_schema','sys') ORDER BY 1").zeilen]

    def standard_schema(self):
        db = self.abfrage("SELECT DATABASE()").zeilen[0][0]
        return db or super().standard_schema()

    def tabellen_zahlen(self):
        zahl = dict(self.abfrage("SELECT table_schema, count(*) FROM information_schema.tables "
                                 "WHERE table_type = 'BASE TABLE' GROUP BY 1", limit=100000).zeilen)
        return {s: int(zahl.get(s, 0)) for s in self.schemas()}

    def setze_schema(self, schema):
        super().setze_schema(schema)
        self.abfrage(f"USE {self.zitiere(schema)}")

    def objekte(self, schema):
        o = {"tabellen": [], "views": [], "indizes": [], "funktionen": []}
        for name, typ in self.abfrage("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s "
                                      "ORDER BY 1", (schema,), 100000).zeilen:
            (o["views"] if typ == "VIEW" else o["tabellen"]).append(name)
        o["indizes"] = [r[0] for r in self.abfrage(
            "SELECT DISTINCT CONCAT(table_name, '.', index_name) FROM information_schema.statistics WHERE table_schema = %s "
            "ORDER BY 1", (schema,), 100000).zeilen]
        o["funktionen"] = [r[0] for r in self.abfrage(
            "SELECT routine_name FROM information_schema.routines WHERE routine_schema = %s ORDER BY 1", (schema,), 100000).zeilen]
        return o

    def spalten(self, schema, tabelle):
        rows = self.abfrage("SELECT column_name, column_type, is_nullable, column_key FROM information_schema.columns "
                            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, tabelle), 100000).zeilen
        return [Spalte(n, t, nb == "YES", k == "PRI") for n, t, nb, k in rows]

    def beginnen(self):
        with self.sperre:
            self.conn.begin()

    def bestaetigen(self):
        with self.sperre:
            self.conn.commit()

    def zuruecknehmen(self):
        with self.sperre:
            self.conn.rollback()

    def abbrechen(self):
        import pymysql
        try:
            tid = self.conn.thread_id()
            k = pymysql.connect(host=self._cfg.get("host") or "localhost", port=int(self._cfg.get("port") or 3306),
                                user=self._cfg.get("benutzer") or None, password=self._pw or "", connect_timeout=5)
            with k.cursor() as c:
                c.execute(f"KILL QUERY {int(tid)}")
            k.close()
        except Exception:
            pass


# --- SQL Server -------------------------------------------------------------------------------------------------------
class SQLServer(Treiber):
    art = "mssql"
    platzhalter = "%s"

    def zitiere(self, name):
        return "[" + name.replace("]", "]]") + "]"

    def verbinden(self, cfg, passwort=None):
        import pymssql
        try:
            self.conn = pymssql.connect(server=cfg.get("host") or "localhost", port=str(cfg.get("port") or 1433),
                                        user=cfg.get("benutzer") or None, password=passwort or None,
                                        database=cfg.get("datenbank") or "", autocommit=True, login_timeout=10)
        except Exception as e:
            raise DBFehler(self.fehlertext(e)) from e
        return self

    def version(self):
        return self.abfrage("SELECT @@VERSION").zeilen[0][0].splitlines()[0]

    def schemas(self):
        return [r[0] for r in self.abfrage(
            "SELECT name FROM sys.schemas WHERE principal_id < 16384 AND name NOT IN "
            "('sys','INFORMATION_SCHEMA','guest') AND name NOT LIKE 'db[_]%' ORDER BY CASE name WHEN 'dbo' THEN 0 ELSE 1 END, name").zeilen]

    def standard_schema(self):
        return "dbo"

    def tabellen_zahlen(self):
        zahl = dict(self.abfrage("SELECT TABLE_SCHEMA, count(*) FROM INFORMATION_SCHEMA.TABLES "
                                 "WHERE TABLE_TYPE = 'BASE TABLE' GROUP BY TABLE_SCHEMA", limit=100000).zeilen)
        return {s: int(zahl.get(s, 0)) for s in self.schemas()}

    def objekte(self, schema):
        o = {"tabellen": [], "views": [], "indizes": [], "funktionen": []}
        for name, typ in self.abfrage("SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s "
                                      "ORDER BY 1", (schema,), 100000).zeilen:
            (o["views"] if typ == "VIEW" else o["tabellen"]).append(name)
        o["indizes"] = [r[0] for r in self.abfrage(
            "SELECT t.name + '.' + i.name FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id WHERE s.name = %s AND i.name IS NOT NULL ORDER BY 1",
            (schema,), 100000).zeilen]
        o["funktionen"] = [r[0] for r in self.abfrage(
            "SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_SCHEMA = %s ORDER BY 1", (schema,), 100000).zeilen]
        return o

    def spalten(self, schema, tabelle):
        pk = {r[0] for r in self.abfrage(
            "SELECT k.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS c JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k "
            "ON k.CONSTRAINT_NAME = c.CONSTRAINT_NAME WHERE c.CONSTRAINT_TYPE = 'PRIMARY KEY' AND c.TABLE_SCHEMA = %s "
            "AND c.TABLE_NAME = %s", (schema, tabelle), 100000).zeilen}
        rows = self.abfrage("SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s "
                            "AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION", (schema, tabelle), 100000).zeilen
        return [Spalte(n, t, nb == "YES", n in pk) for n, t, nb in rows]

    def seite(self, offset, limit, sortiert):
        return ("" if sortiert else " ORDER BY (SELECT NULL)") + f" OFFSET {int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY"

    def beginnen(self):
        with self.sperre:
            self.conn.autocommit(False)

    def bestaetigen(self):
        with self.sperre:
            self.conn.commit()
            self.conn.autocommit(True)

    def zuruecknehmen(self):
        with self.sperre:
            self.conn.rollback()
            self.conn.autocommit(True)

    def explain(self, sql):
        with self.sperre:
            cur = self.conn.cursor()
            try:
                cur.execute("SET SHOWPLAN_TEXT ON")
                cur.execute(sql)
                zeilen = [tuple(z) for z in cur.fetchall()] if cur.description else []
                spalten = [d[0] for d in cur.description] if cur.description else ["Plan"]
            except Exception as e:
                raise DBFehler(self.fehlertext(e)) from e
            finally:
                try:
                    cur.execute("SET SHOWPLAN_TEXT OFF")
                except Exception:
                    pass
                cur.close()
        return Ergebnis(spalten, zeilen)

    def abbrechen(self):
        try:
            self.conn.cancel()
        except Exception:
            pass


KLASSEN = {"postgresql": PostgreSQL, "mysql": MySQL, "sqlite": SQLite, "duckdb": DuckDB, "mssql": SQLServer}


def oeffne(cfg: dict, passwort: str | None = None) -> Treiber:
    art = cfg.get("art", "")
    if art not in KLASSEN:
        raise DBFehler(f"Unbekannte Datenbankart: {art}")
    fehlt = verfuegbar(art)
    if fehlt:
        raise DBFehler(fehlt)
    t = KLASSEN[art]().verbinden(cfg, passwort)
    t.schreibschutz = bool(cfg.get("schreibschutz"))
    return t
