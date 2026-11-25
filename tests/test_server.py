"""Server-Verwaltung: SCRAM-Verifier, Namensprüfung, Schreibschutz; Live-Teile gegen die Test-DBs (PostgreSQL/MySQL)."""
import base64
import hashlib
import hmac

import pytest

from dbstudio import server, treiber


def test_scram_verifier_entspricht_postgresql():
    v = server.scram_verifier("pencil", base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ=="), 4096)
    kopf, schluessel = v.split("$", 1)[1].split("$")
    assert v.startswith("SCRAM-SHA-256$4096:W22ZaJ0SNY7soEsUEjb6gQ==$")
    stored, srv = (base64.b64decode(x) for x in schluessel.split(":"))
    gesalzen = hashlib.pbkdf2_hmac("sha256", b"pencil", base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ=="), 4096)
    assert stored == hashlib.sha256(hmac.new(gesalzen, b"Client Key", "sha256").digest()).digest()
    assert srv == hmac.new(gesalzen, b"Server Key", "sha256").digest()
    assert "pencil" not in v


def test_namen_und_schreibschutz(db):
    if not server.unterstuetzt(db):
        with pytest.raises(treiber.DBFehler):
            server.status(db)
        return
    with pytest.raises(treiber.DBFehler):
        server._name("1; DROP")
    db.schreibschutz = True
    try:
        for f in (lambda: server.benutzer_anlegen(db, "x_test", "pw", {}), lambda: server.verbindung_trennen(db, 1),
                  lambda: server.passwort_setzen(db, "x_test", "pw")):
            with pytest.raises(treiber.DBFehler):
                f()
    finally:
        db.schreibschutz = False


def test_status_verbindungen_benutzer_variablen(db):
    if not server.unterstuetzt(db):
        return
    st = server.status(db)
    assert st["kennzahlen"][0][0] == "Version" and st["groessen"][1]
    sp, zeilen = server.verbindungen(db)
    assert sp[0] == "PID" and any(z[-1] for z in zeilen)          # die eigene Verbindung ist dabei
    sp, zeilen = server.benutzer(db)
    assert sp[0] == "Rolle" and zeilen
    sp, zeilen = server.variablen(db)
    assert len(zeilen) > 50
