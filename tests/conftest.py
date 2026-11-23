import os

import pytest

from dbstudio import treiber

PG_HOST = os.environ.get("DBSTUDIO_TEST_PG_HOST", "192.168.178.214")
PG_DB = os.environ.get("DBSTUDIO_TEST_PG_DB", "dbstudio_test")
PG_USER = os.environ.get("DBSTUDIO_TEST_PG_USER", "dbstudio")


@pytest.fixture(autouse=True)
def eigene_konfig(tmp_path, monkeypatch):
    """Tests schreiben nie in die echte ~/.config/db-studio."""
    monkeypatch.setenv("DB_STUDIO_CONFIG", str(tmp_path / "konfig"))


def _pg_passwort():
    pw = os.environ.get("DBSTUDIO_TEST_PG_PASSWORT")
    if pw:
        return pw
    try:
        import keyring
        return keyring.get_password("db-studio", f"postgres:{PG_USER}@{PG_HOST}")
    except Exception:
        return None


def _oeffne_sqlite(tmp_path):
    return treiber.oeffne({"art": "sqlite", "datei": str(tmp_path / "t.db")})


def _oeffne_duckdb(tmp_path):
    return treiber.oeffne({"art": "duckdb", "datei": str(tmp_path / "t.duckdb")})


def _oeffne_pg(tmp_path):
    pw = _pg_passwort()
    if not pw:
        pytest.skip("Kein Passwort für die Postgres-Test-DB")
    try:
        t = treiber.oeffne({"art": "postgresql", "host": PG_HOST, "port": 5432, "datenbank": PG_DB,
                            "benutzer": PG_USER, "sslmode": "require"}, pw)
    except treiber.DBFehler as e:
        pytest.skip(f"Postgres-Test-DB nicht erreichbar: {e}")
    schema = "t_" + os.urandom(4).hex()
    t.abfrage(f"CREATE SCHEMA {schema}")
    t.abfrage(f"SET search_path TO {schema}")
    t._test_schema = schema
    return t


MY_HOST = os.environ.get("DBSTUDIO_TEST_MY_HOST", "192.168.178.216")
MS_HOST = os.environ.get("DBSTUDIO_TEST_MS_HOST", "192.168.178.216")
TEST_DB = "dbstudio_test"


def _passwort(umgebung: str, schluessel: str):
    pw = os.environ.get(umgebung)
    if pw:
        return pw
    try:
        import keyring
        return keyring.get_password("db-studio", schluessel)
    except Exception:
        return None


def _leeren(t):
    """Test-DB vor/nach jedem Test leeren (MySQL/SQL Server teilen sich eine Datenbank)."""
    if t.art == "mysql":
        t.abfrage("SET FOREIGN_KEY_CHECKS = 0")
        for (name, art) in t.abfrage("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()").zeilen:
            t.abfrage(f"DROP {'VIEW' if art == 'VIEW' else 'TABLE'} IF EXISTS `{name}`")
        t.abfrage("SET FOREIGN_KEY_CHECKS = 1")
    elif t.art == "mssql":
        for (sql,) in t.abfrage("SELECT 'ALTER TABLE [' + s.name + '].[' + o.name + '] DROP CONSTRAINT [' + f.name + ']' "
                                "FROM sys.foreign_keys f JOIN sys.objects o ON o.object_id = f.parent_object_id "
                                "JOIN sys.schemas s ON s.schema_id = o.schema_id").zeilen:
            t.abfrage(sql)
        for (sql,) in t.abfrage("SELECT 'DROP VIEW [' + TABLE_SCHEMA + '].[' + TABLE_NAME + ']' FROM INFORMATION_SCHEMA.VIEWS").zeilen:
            t.abfrage(sql)
        for (sql,) in t.abfrage("SELECT 'DROP TABLE [' + TABLE_SCHEMA + '].[' + TABLE_NAME + ']' FROM INFORMATION_SCHEMA.TABLES "
                                "WHERE TABLE_TYPE = 'BASE TABLE'").zeilen:
            t.abfrage(sql)


def _oeffne_mysql(tmp_path):
    pw = _passwort("DBSTUDIO_TEST_MY_PASSWORT", f"mysql:dbstudio@{MY_HOST}")
    if not pw:
        pytest.skip("Kein Passwort für die MySQL-Test-DB")
    try:
        t = treiber.oeffne({"art": "mysql", "host": MY_HOST, "port": 3306, "datenbank": TEST_DB,
                            "benutzer": "dbstudio", "sslmode": "require"}, pw)
    except treiber.DBFehler as e:
        pytest.skip(f"MySQL-Test-DB nicht erreichbar: {e}")
    _leeren(t)
    return t


def _oeffne_mssql(tmp_path):
    pw = _passwort("DBSTUDIO_TEST_MS_PASSWORT", f"mssql:dbstudio@{MS_HOST}")
    if not pw:
        pytest.skip("Kein Passwort für die SQL-Server-Test-DB")
    try:
        t = treiber.oeffne({"art": "mssql", "host": MS_HOST, "port": 1433, "datenbank": TEST_DB,
                            "benutzer": "dbstudio"}, pw)
    except treiber.DBFehler as e:
        pytest.skip(f"SQL-Server-Test-DB nicht erreichbar: {e}")
    _leeren(t)
    return t


@pytest.fixture(params=["sqlite", "duckdb", "postgresql", "mysql", "mssql"])
def db(request, tmp_path):
    t = {"sqlite": _oeffne_sqlite, "duckdb": _oeffne_duckdb, "postgresql": _oeffne_pg,
         "mysql": _oeffne_mysql, "mssql": _oeffne_mssql}[request.param](tmp_path)
    yield t
    if t.art == "postgresql":
        t.abfrage(f"DROP SCHEMA {t._test_schema} CASCADE")
    elif t.art in ("mysql", "mssql"):
        _leeren(t)
    t.schliessen()


def schema_von(t):
    return getattr(t, "_test_schema", None) or t.standard_schema()
