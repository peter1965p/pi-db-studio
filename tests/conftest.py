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


@pytest.fixture(params=["sqlite", "duckdb", "postgresql"])
def db(request, tmp_path):
    t = {"sqlite": _oeffne_sqlite, "duckdb": _oeffne_duckdb, "postgresql": _oeffne_pg}[request.param](tmp_path)
    yield t
    if t.art == "postgresql":
        t.abfrage(f"DROP SCHEMA {t._test_schema} CASCADE")
    t.schliessen()


def schema_von(t):
    return getattr(t, "_test_schema", None) or t.standard_schema()
