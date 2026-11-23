"""Start: python -m dbstudio.web            -> Server (Einstellungen aus der Umgebung)
       python -m dbstudio.web benutzer NAME -> Benutzer anlegen/Passwort setzen (Passwort über stdin)
       python -m dbstudio.web schluessel    -> neuen Verschlüsselungsschlüssel ausgeben (nur bei der Einrichtung)

Umgebung: DBSTUDIO_SCHLUESSEL (Pflicht), DBSTUDIO_WEB_DATEN, DBSTUDIO_HOST, DBSTUDIO_PORT,
          DBSTUDIO_ZERTIFIKAT / DBSTUDIO_ZERT_SCHLUESSEL (HTTPS)."""

import os
import sys


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["schluessel"]:
        from .speicher import neuer_schluessel
        print(neuer_schluessel())
        return
    if args[:1] == ["benutzer"] and len(args) == 2:
        from .speicher import aus_umgebung
        pw = sys.stdin.readline().rstrip("\n")
        aus_umgebung().benutzer_setzen(args[1], pw)
        print(f"Benutzer „{args[1]}“ gesetzt.")
        return
    import uvicorn
    from .app import erstelle_app
    uvicorn.run(erstelle_app(), host=os.environ.get("DBSTUDIO_HOST", "0.0.0.0"),
                port=int(os.environ.get("DBSTUDIO_PORT", "443")), proxy_headers=False,
                ssl_certfile=os.environ.get("DBSTUDIO_ZERTIFIKAT") or None,
                ssl_keyfile=os.environ.get("DBSTUDIO_ZERT_SCHLUESSEL") or None,
                server_header=False, log_level="info")


if __name__ == "__main__":
    main()
