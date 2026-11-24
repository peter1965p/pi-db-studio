"""SQL-Dump-Import: Supabase-Schema-Export aufbereiten und (falls erreichbar) in PostgreSQL einspielen."""
import os

import pytest

from dbstudio import sqlimport, treiber

from .conftest import PG_DB, PG_HOST, PG_USER, _pg_passwort

SUPABASE = """-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.bestellungen (
  id integer NOT NULL DEFAULT nextval('bestellungen_id_seq'::regclass),
  kunde_id uuid,
  tags ARRAY DEFAULT '{}'::text[],
  art text CHECK (art = ANY (ARRAY['a'::text, 'b'::text])),
  CONSTRAINT bestellungen_pkey PRIMARY KEY (id),
  CONSTRAINT bestellungen_kunde_fkey FOREIGN KEY (kunde_id) REFERENCES public.kunden(id)
);
CREATE TABLE public.kunden (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  name text, -- Kommentar, mit Komma
  user_id uuid,
  CONSTRAINT kunden_pkey PRIMARY KEY (id),
  CONSTRAINT kunden_user_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
"""


def test_aufbereitung_supabase():
    p = sqlimport.vorbereiten(SUPABASE)
    text = ";\n".join(p.anweisungen)
    assert p.tabellen == ["public.bestellungen", "public.kunden"] and p.fks == 2 and p.fremde_ziele == ["auth.users"]
    assert "CREATE SEQUENCE IF NOT EXISTS bestellungen_id_seq" in p.anweisungen
    assert "tags text[] DEFAULT '{}'::text[]" in text and "ARRAY['a'::text" in text  # CHECK bleibt unberührt
    assert "gen_random_uuid()" in text and "uuid_generate_v4" not in text
    assert "CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY)" in p.anweisungen
    # Fremdschlüssel erst nach allen Tabellen
    letzte_tabelle = max(i for i, a in enumerate(p.anweisungen) if a.startswith("CREATE TABLE"))
    assert all(i > letzte_tabelle for i, a in enumerate(p.anweisungen) if "FOREIGN KEY" in a)


def test_fremde_weglassen():
    p = sqlimport.vorbereiten(SUPABASE, "weglassen")
    assert p.fks == 1 and not any("auth.users" in a for a in p.anweisungen)


def test_einspielen_postgres():
    pw = _pg_passwort()
    if not pw:
        pytest.skip("Kein Passwort für die Postgres-Test-DB")
    cfg = {"art": "postgresql", "host": PG_HOST, "port": "5432", "datenbank": PG_DB, "benutzer": PG_USER, "sslmode": "require"}
    try:
        t = treiber.oeffne(cfg, pw)
    except treiber.DBFehler as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    schema = "imp_" + os.urandom(4).hex()
    sql = SUPABASE.replace("public.", f"{schema}.").replace("auth.users", f"{schema}_auth.users")
    try:
        n = sqlimport.einspielen(t, sqlimport.vorbereiten(sql))
        assert n > 5
        fks = t.abfrage("SELECT count(*) FROM information_schema.table_constraints WHERE constraint_type='FOREIGN KEY' "
                        "AND table_schema = %s", [schema]).zeilen[0][0]
        assert fks == 2
    finally:
        t.abfrage(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        t.abfrage(f"DROP SCHEMA IF EXISTS {schema}_auth CASCADE")
        t.schliessen()
