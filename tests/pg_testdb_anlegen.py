"""Einmalig: Benutzer dbstudio + Test-DB dbstudio_test auf CT 103 anlegen; Passwort nur im Keyring.

Aufruf: venv/bin/python tests/pg_testdb_anlegen.py
"""
import secrets
import subprocess

import keyring

HOST = "192.168.178.214"
SCHLUESSEL = f"postgres:dbstudio@{HOST}"

pw = keyring.get_password("db-studio", SCHLUESSEL)
if not pw:
    pw = secrets.token_urlsafe(32)
    keyring.set_password("db-studio", SCHLUESSEL, pw)
sql = f"""
DO $$BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dbstudio') THEN CREATE ROLE dbstudio LOGIN; END IF;
END$$;
ALTER ROLE dbstudio WITH LOGIN PASSWORD '{pw}';
SELECT 'CREATE DATABASE dbstudio_test OWNER dbstudio' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'dbstudio_test')\\gexec
REVOKE ALL ON DATABASE dbstudio_test FROM PUBLIC;
"""
r = subprocess.run(["ssh", "-o", "BatchMode=yes", "postgres", "su - postgres -c 'psql -q -v ON_ERROR_STOP=1'"],
                   input=sql, text=True, capture_output=True)
print("ok" if r.returncode == 0 else "FEHLER: " + r.stderr.strip()[:300])
