"""Legt auf dem PostgreSQL-Server (CT 103) die Admin-Rolle für Pi DB Studio an und trägt die Verbindung ein.

Aufruf (auf dem PC, als Peter):  ~/Dev/db-studio/venv/bin/python ~/Dev/db-studio/deploy/pg-admin-rolle.py [rolle]

- Rolle (Standard „peter“) mit LOGIN und SUPERUSER; Zugang bleibt wie alle anderen: nur LAN, nur TLS (hostssl), scram.
- Das Passwort wird verdeckt abgefragt (leer lassen: zufällig erzeugen), per SSH-stdin gesetzt und im Schlüsselbund
  abgelegt – nie ausgegeben. Im eigenen Terminal starten, nicht über die Claude-Sitzung.
- In Pi DB Studio erscheint die Verbindung „PostgreSQL-Server (Admin)“ (rot markiert, Datenbank postgres).
"""
import getpass
import secrets
import string
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dbstudio import verbindungen  # noqa: E402

HOST, SSH = "192.168.178.214", "postgres"
rolle = sys.argv[1] if len(sys.argv) > 1 else "peter"
if not rolle.isidentifier():
    sys.exit("Ungültiger Rollenname.")
pw = getpass.getpass(f"Passwort für die Rolle {rolle} (leer: zufällig erzeugen): ")
if pw and getpass.getpass("Noch einmal: ") != pw:
    sys.exit("Die beiden Eingaben stimmen nicht überein.")
if not pw:
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
pw_sql = pw.replace("'", "''")
sql = (f"DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rolle}') THEN CREATE ROLE {rolle} LOGIN SUPERUSER; END IF; END$$;\n"
       f"ALTER ROLE {rolle} WITH LOGIN SUPERUSER PASSWORD '{pw_sql}';\n")
r = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH, "cd /tmp && su postgres -c 'psql -q -v ON_ERROR_STOP=1'"],
                   input=sql, text=True, capture_output=True)
if r.returncode:
    sys.exit("psql fehlgeschlagen: " + r.stderr.strip()[:300])
liste = verbindungen.laden()
v = next((x for x in liste if x.get("benutzer") == rolle and x.get("host") == HOST), None)
if not v:
    v = verbindungen.neu(name="PostgreSQL-Server (Admin)", art="postgresql", host=HOST, port="5432", datenbank="postgres",
                         benutzer=rolle, sslmode="require", farbe="#e05252")
    liste.append(v)
    verbindungen.speichern(liste)
verbindungen.setze_passwort(v, pw)
print(f"Rolle {rolle} angelegt, Verbindung „{v['name']}“ eingetragen, Passwort im Schlüsselbund: {bool(verbindungen.passwort(v))}")
print("Pi DB Studio neu starten, dann erscheint die Karte unter Verbindungen.")
