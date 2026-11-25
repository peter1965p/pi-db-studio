"""Server-Verwaltung (angelehnt an die Administration der MySQL Workbench): Status, Client-Verbindungen, Benutzer und
Rechte, Servervariablen, Sicherung – für PostgreSQL und MySQL/MariaDB.

Alle Listen kommen als (Spalten, Zeilen) für das Ergebnisraster. Passwörter von PostgreSQL-Rollen werden vor dem Senden
zu einem SCRAM-SHA-256-Verifier gerechnet: Das Klartext-Passwort erreicht den Server nie (auch nicht dessen Log).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from .treiber import DBFehler, Treiber

UNTERSTUETZT = ("postgresql", "mysql")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.-]{0,62}$")


def unterstuetzt(t: Treiber | None) -> bool:
    return t is not None and t.art in UNTERSTUETZT


def _name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME.match(name):
        raise DBFehler("Name: Buchstaben, Ziffern, _ $ . -, höchstens 63 Zeichen, nicht mit einer Ziffer beginnen.")
    return name


def _schreiben(t: Treiber) -> None:
    if t.schreibschutz:
        raise DBFehler("Die Verbindung ist schreibgeschützt.")


def scram_verifier(passwort: str, salz: bytes | None = None, runden: int = 4096) -> str:
    """Wie PostgreSQL ihn speichert (SCRAM-SHA-256$<runden>:<salz>$<StoredKey>:<ServerKey>)."""
    pw = unicodedata.normalize("NFKC", passwort).encode("utf-8")
    salz = salz or os.urandom(16)
    gesalzen = hashlib.pbkdf2_hmac("sha256", pw, salz, runden)
    client = hmac.new(gesalzen, b"Client Key", "sha256").digest()
    stored = hashlib.sha256(client).digest()
    server = hmac.new(gesalzen, b"Server Key", "sha256").digest()
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return f"SCRAM-SHA-256${runden}:{b(salz)}${b(stored)}:{b(server)}"


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# --- Status --------------------------------------------------------------------------------------------------------

def status(t: Treiber) -> dict:
    """Kennzahlen [(Bezeichnung, Wert, Hinweis)] und Größen der Datenbanken (Spalten, Zeilen)."""
    if t.art == "postgresql":
        q = lambda sql: t.abfrage(sql).zeilen[0][0]  # noqa: E731
        version = q("SELECT version()").split(" on ")[0]
        sek = int(q("SELECT extract(epoch FROM now() - pg_postmaster_start_time())::bigint"))
        laufzeit = _dauer(sek)
        verb = t.abfrage("SELECT count(*), count(*) FILTER (WHERE state = 'active'), current_setting('max_connections')::int "
                         "FROM pg_stat_activity WHERE backend_type = 'client backend'").zeilen[0]
        stat = t.abfrage("SELECT coalesce(sum(blks_hit),0), coalesce(sum(blks_read),0), coalesce(sum(xact_commit),0), "
                         "coalesce(sum(xact_rollback),0), coalesce(sum(deadlocks),0) FROM pg_stat_database").zeilen[0]
        treffer = 100 * int(stat[0]) / max(1, int(stat[0]) + int(stat[1]))
        kennzahlen = [
            ("Version", version, ""), ("Läuft seit", laufzeit, ""),
            ("Verbindungen", f"{verb[0]} von {verb[2]}", f"{verb[1]} aktiv"),
            ("Cache-Trefferquote", f"{treffer:.1f} %", "über 99 % ist gut"),
            ("Transaktionen", f"{int(stat[2]):,}".replace(",", "."), f"{int(stat[3]):,} zurückgenommen".replace(",", ".")),
            ("Deadlocks", str(stat[4]), ""),
            ("Datenverzeichnis", q("SELECT current_setting('data_directory')") if _darf_lesen(t) else "–", ""),
        ]
        # Größe nur, wo die Anmeldung verbinden darf (sonst verweigert PostgreSQL pg_database_size)
        groesse = "CASE WHEN has_database_privilege(datname, 'CONNECT') THEN pg_database_size(datname) END"
        g = t.abfrage(f"SELECT datname, pg_get_userbyid(datdba), coalesce(pg_size_pretty({groesse}), 'kein Zugriff'), "
                      f"{groesse}, (SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname) "
                      f"FROM pg_database d WHERE NOT datistemplate ORDER BY {groesse} DESC NULLS LAST", limit=1000)
        groessen = (["Datenbank", "Besitzer", "Größe", "Bytes", "Verbindungen"], g.zeilen)
        return {"kennzahlen": kennzahlen, "groessen": groessen}
    if t.art == "mysql":
        st = dict(t.abfrage("SHOW GLOBAL STATUS", limit=5000).zeilen)
        var = dict(t.abfrage("SHOW GLOBAL VARIABLES WHERE Variable_name IN ('version','version_comment','max_connections','datadir')").zeilen)
        sek = int(st.get("Uptime", 0))
        lesen = int(st.get("Innodb_buffer_pool_reads", 0))
        anfr = int(st.get("Innodb_buffer_pool_read_requests", 0))
        kennzahlen = [
            ("Version", f"{var.get('version', '')} ({var.get('version_comment', '')})", ""),
            ("Läuft seit", _dauer(sek), ""),
            ("Verbindungen", f"{st.get('Threads_connected', 0)} von {var.get('max_connections', '?')}", f"{st.get('Threads_running', 0)} aktiv"),
            ("Cache-Trefferquote", f"{100 * (1 - lesen / max(1, anfr)):.1f} %", "InnoDB-Puffer"),
            ("Abfragen", f"{int(st.get('Questions', 0)):,}".replace(",", "."), f"{st.get('Slow_queries', 0)} langsam"),
            ("Datenverzeichnis", var.get("datadir", "–"), ""),
        ]
        g = t.abfrage("SELECT s.schema_name, '', concat(round(coalesce(sum(tb.data_length + tb.index_length),0)/1048576, 1), ' MB'), "
                      "coalesce(sum(tb.data_length + tb.index_length),0), "
                      "(SELECT count(*) FROM information_schema.processlist p WHERE p.db = s.schema_name) "
                      "FROM information_schema.schemata s LEFT JOIN information_schema.tables tb ON tb.table_schema = s.schema_name "
                      "GROUP BY s.schema_name ORDER BY 4 DESC", limit=1000)
        return {"kennzahlen": kennzahlen, "groessen": (["Datenbank", "Besitzer", "Größe", "Bytes", "Verbindungen"], g.zeilen)}
    raise DBFehler("Server-Verwaltung gibt es für PostgreSQL und MySQL/MariaDB.")


def _dauer(sek: int) -> str:
    tage, rest = divmod(int(sek), 86400)
    return (f"{tage} Tag{'e' if tage != 1 else ''}, " if tage else "") + f"{rest // 3600} Std. {rest % 3600 // 60} Min."


def _darf_lesen(t: Treiber) -> bool:
    try:
        return bool(t.abfrage("SELECT rolsuper OR pg_has_role(current_user, 'pg_read_all_settings', 'member') "
                              "FROM pg_roles WHERE rolname = current_user").zeilen[0][0])
    except Exception:
        return False


# --- Client-Verbindungen -----------------------------------------------------------------------------------------

def verbindungen(t: Treiber) -> tuple[list, list]:
    if t.art == "postgresql":
        e = t.abfrage("SELECT pid, usename, datname, coalesce(client_addr::text, 'lokal'), application_name, state, "
                      "date_trunc('second', now() - coalesce(query_start, backend_start))::text, "
                      "left(regexp_replace(query, '\\s+', ' ', 'g'), 300), pid = pg_backend_pid() "
                      "FROM pg_stat_activity WHERE backend_type = 'client backend' ORDER BY state = 'active' DESC, query_start", limit=2000)
        return (["PID", "Benutzer", "Datenbank", "Client", "Programm", "Status", "Seit", "Abfrage", "Eigene"], e.zeilen)
    e = t.abfrage("SELECT id, user, db, host, '', command, time, left(coalesce(info, ''), 300), id = connection_id() "
                  "FROM information_schema.processlist ORDER BY command <> 'Sleep' DESC, time DESC", limit=2000)
    return (["PID", "Benutzer", "Datenbank", "Client", "Programm", "Status", "Seit", "Abfrage", "Eigene"], e.zeilen)


def abfrage_abbrechen(t: Treiber, pid: int) -> str:
    _schreiben(t)
    sql = f"SELECT pg_cancel_backend({int(pid)})" if t.art == "postgresql" else f"KILL QUERY {int(pid)}"
    t.abfrage(sql)
    return sql


def verbindung_trennen(t: Treiber, pid: int) -> str:
    _schreiben(t)
    sql = f"SELECT pg_terminate_backend({int(pid)})" if t.art == "postgresql" else f"KILL {int(pid)}"
    t.abfrage(sql)
    return sql


# --- Benutzer und Rechte -----------------------------------------------------------------------------------------

RECHTE_PG = {"login": "LOGIN", "createdb": "CREATEDB", "createrole": "CREATEROLE", "superuser": "SUPERUSER"}


def benutzer(t: Treiber) -> tuple[list, list]:
    if t.art == "postgresql":
        e = t.abfrage(
            "SELECT r.rolname, r.rolcanlogin, r.rolsuper, r.rolcreatedb, r.rolcreaterole, "
            "coalesce(to_char(r.rolvaliduntil, 'YYYY-MM-DD'), ''), r.rolconnlimit, "
            "coalesce((SELECT string_agg(g.rolname, ', ') FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
            "WHERE m.member = r.oid), ''), "
            "coalesce((SELECT string_agg(d.datname, ', ' ORDER BY d.datname) FROM pg_database d WHERE NOT d.datistemplate "
            "AND has_database_privilege(r.oid, d.oid, 'CONNECT')), '') "
            "FROM pg_roles r WHERE r.rolname !~ '^pg_' ORDER BY r.rolcanlogin DESC, r.rolname", limit=2000)
        return (["Rolle", "Login", "Superuser", "DB anlegen", "Rollen anlegen", "Gültig bis", "Max. Verb.", "Mitglied von",
                 "Darf verbinden mit"], e.zeilen)
    try:
        e = t.abfrage("SELECT concat(user, '@', host), account_locked = 'N', super_priv = 'Y', create_priv = 'Y', "
                      "create_user_priv = 'Y', '', max_user_connections, '', '' FROM mysql.user ORDER BY user", limit=2000)
    except DBFehler:
        # Ohne Leserecht auf mysql.user: nur das eigene Konto (für alle Konten braucht die Anmeldung SELECT auf mysql.*)
        e = t.abfrage("SELECT current_user(), 1, 0, 0, 0, '', 0, '', 'nur eigenes Konto sichtbar'")
    return (["Rolle", "Login", "Superuser", "DB anlegen", "Rollen anlegen", "Gültig bis", "Max. Verb.", "Mitglied von",
             "Darf verbinden mit"], e.zeilen)


def _mysql_konto(name: str) -> str:
    benutzer_, _, host = name.partition("@")
    return f"{_literal(_name(benutzer_))}@{_literal(host or '%')}"


def benutzer_anlegen(t: Treiber, name: str, passwort: str, rechte: dict) -> str:
    """rechte: login, createdb, createrole, superuser (bool). Gibt das SQL ohne Passwort zurück."""
    _schreiben(t)
    if t.art == "postgresql":
        name = _name(name)
        attr = " ".join(v if rechte.get(k) else "NO" + v for k, v in RECHTE_PG.items())
        sql = f"CREATE ROLE {t.zitiere(name)} {attr}"
        t.abfrage(sql + (f" PASSWORD {_literal(scram_verifier(passwort))}" if passwort else ""))
        return sql + (" PASSWORD '***'" if passwort else "")
    konto = _mysql_konto(name)
    t.abfrage(f"CREATE USER {konto} IDENTIFIED BY %s", (passwort,))
    return f"CREATE USER {konto} IDENTIFIED BY '***'"


def benutzer_aendern(t: Treiber, name: str, rechte: dict) -> str:
    _schreiben(t)
    if t.art != "postgresql":
        raise DBFehler("Rechte-Schalter gibt es für PostgreSQL; bei MySQL über GRANT im SQL-Editor.")
    attr = " ".join(v if rechte.get(k) else "NO" + v for k, v in RECHTE_PG.items())
    sql = f"ALTER ROLE {t.zitiere(_name(name))} {attr}"
    t.abfrage(sql)
    return sql


def passwort_setzen(t: Treiber, name: str, passwort: str) -> str:
    _schreiben(t)
    if not passwort:
        raise DBFehler("Bitte ein Passwort angeben.")
    if t.art == "postgresql":
        t.abfrage(f"ALTER ROLE {t.zitiere(_name(name))} PASSWORD {_literal(scram_verifier(passwort))}")
        return f"ALTER ROLE {name} PASSWORD '***' (als SCRAM-Verifier, Klartext erreicht den Server nicht)"
    konto = _mysql_konto(name)
    t.abfrage(f"ALTER USER {konto} IDENTIFIED BY %s", (passwort,))
    return f"ALTER USER {konto} IDENTIFIED BY '***'"


def benutzer_loeschen(t: Treiber, name: str) -> str:
    _schreiben(t)
    if t.art == "postgresql":
        sql = f"DROP ROLE {t.zitiere(_name(name))}"
    else:
        sql = f"DROP USER {_mysql_konto(name)}"
    t.abfrage(sql)
    return sql


def folgen_benutzer_loeschen(t: Treiber, name: str) -> list[str]:
    """Was einer Rolle gehört oder an ihr hängt – PostgreSQL verweigert DROP ROLE, solange ihr etwas gehört."""
    if t.art != "postgresql":
        return []
    z = t.abfrage("SELECT (SELECT string_agg(datname, ', ') FROM pg_database WHERE datdba = r.oid), "
                  "(SELECT count(*) FROM pg_stat_activity a WHERE a.usename = r.rolname), "
                  "(SELECT string_agg(m2.rolname, ', ') FROM pg_auth_members m JOIN pg_roles m2 ON m2.oid = m.member WHERE m.roleid = r.oid) "
                  "FROM pg_roles r WHERE r.rolname = %s", (name,)).zeilen
    if not z:
        return []
    dbs, verb, mitglieder = z[0]
    out = []
    if dbs:
        out.append(f"Besitzer der Datenbank(en): {dbs} – erst einen anderen Besitzer setzen")
    if verb:
        out.append(f"{verb} offene Verbindung(en) dieser Rolle")
    if mitglieder:
        out.append(f"Diese Rollen erben von ihr: {mitglieder}")
    return out


def verbinden_erlauben(t: Treiber, rolle: str, datenbank: str, erlauben: bool) -> str:
    _schreiben(t)
    if t.art == "postgresql":
        sql = (f"GRANT CONNECT ON DATABASE {t.zitiere(datenbank)} TO {t.zitiere(_name(rolle))}" if erlauben else
               f"REVOKE CONNECT ON DATABASE {t.zitiere(datenbank)} FROM {t.zitiere(_name(rolle))}")
    else:
        sql = (f"GRANT ALL PRIVILEGES ON {t.zitiere(datenbank)}.* TO {_mysql_konto(rolle)}" if erlauben else
               f"REVOKE ALL PRIVILEGES ON {t.zitiere(datenbank)}.* FROM {_mysql_konto(rolle)}")
    t.abfrage(sql)
    return sql


# --- Variablen -----------------------------------------------------------------------------------------------------

def variablen(t: Treiber) -> tuple[list, list]:
    if t.art == "postgresql":
        e = t.abfrage("SELECT name, setting, coalesce(unit, ''), category, short_desc, source <> 'default', context "
                      "FROM pg_settings ORDER BY category, name", limit=5000)
        return (["Name", "Wert", "Einheit", "Bereich", "Beschreibung", "Geändert", "Wirksam"], e.zeilen)
    e = t.abfrage("SHOW GLOBAL VARIABLES", limit=5000)
    return (["Name", "Wert", "Einheit", "Bereich", "Beschreibung", "Geändert", "Wirksam"],
            [(n, w, "", "", "", False, "") for n, w in e.zeilen])


# --- Sicherung -----------------------------------------------------------------------------------------------------

def sicherungsprogramm(t: Treiber) -> str | None:
    return shutil.which("pg_dump" if t.art == "postgresql" else "mysqldump") or (
        shutil.which("mariadb-dump") if t.art == "mysql" else None)


def sicherung(t: Treiber, cfg: dict, passwort: str | None, datenbank: str, ziel: Path, nur_struktur: bool = False) -> Path:
    """SQL-Dump einer Datenbank mit pg_dump bzw. mysqldump. Das Passwort geht per Umgebung, nie auf die Kommandozeile."""
    prog = sicherungsprogramm(t)
    if not prog:
        raise DBFehler("pg_dump bzw. mysqldump ist nicht installiert (Paket postgresql bzw. mariadb-clients).")
    ziel = Path(ziel)
    env = dict(os.environ)
    host, port, user = cfg.get("host") or "localhost", str(cfg.get("port") or ""), cfg.get("benutzer") or ""
    if t.art == "postgresql":
        env.update(PGPASSWORD=passwort or "", PGSSLMODE=cfg.get("sslmode") or "prefer")
        args = [prog, "-h", host, "-p", port or "5432", "-U", user, "-d", datenbank, "--no-password", "-f", str(ziel)]
        if nur_struktur:
            args.append("--schema-only")
    else:
        env["MYSQL_PWD"] = passwort or ""
        args = [prog, "-h", host, "-P", port or "3306", "-u", user, "--single-transaction", "--routines", f"--result-file={ziel}", datenbank]
        if nur_struktur:
            args.insert(-1, "--no-data")
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=3600)
    if r.returncode:
        ziel.unlink(missing_ok=True)
        raise DBFehler((r.stderr or "Sicherung fehlgeschlagen").strip()[:500])
    return ziel
