"""KI-Brücke: reicht Anfragen der Web-Version (CT 104) an das angemeldete Claude Code auf dem PC weiter.

    python -m dbstudio.claude_bruecke            # läuft als User-Dienst (deploy/claude-bruecke.service)

Nimmt nur POST /frage von erlaubten Adressen (Standard 192.168.178.215) mit passendem Kopf „X-Bruecke-Token“ an.
Token im Schlüsselbund (Dienst „db-studio“, Eintrag „claude-bruecke“) oder in DBSTUDIO_CLAUDE_BRUECKE_TOKEN.
Claude läuft ohne Werkzeuge (`claude -p --tools ""`), eine Anfrage zur Zeit, Zeitlimit wie in ki.ZEIT.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ki

EINTRAG = "claude-bruecke"
MAX_GROESSE = 512 * 1024


def token() -> str:
    t = os.environ.get("DBSTUDIO_CLAUDE_BRUECKE_TOKEN", "")
    if not t:
        try:
            import keyring
            t = keyring.get_password(ki.DIENST, EINTRAG) or ""
        except Exception:
            t = ""
    return t


def baue_handler(geheim: str, erlaubt: set[str], frage=None):
    frage = frage or ki._claude_code
    eine = threading.Semaphore(1)

    class H(BaseHTTPRequestHandler):
        server_version = "db-studio-bruecke"
        sys_version = ""

        def log_message(self, fmt, *args):  # keine Prompts/Köpfe ins Protokoll
            sys.stderr.write(f"{self.client_address[0]} {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

        def antworte(self, code: int, daten: dict):
            roh = json.dumps(daten).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

        def do_GET(self):
            self.antworte(404, {"fehler": "nicht gefunden"})

        def do_POST(self):
            if self.client_address[0] not in erlaubt:
                return self.antworte(403, {"fehler": "Adresse nicht erlaubt"})
            if not geheim or not hmac.compare_digest(self.headers.get("X-Bruecke-Token", "").encode(), geheim.encode()):
                return self.antworte(401, {"fehler": "Token falsch"})
            if self.path != "/frage":
                return self.antworte(404, {"fehler": "nicht gefunden"})
            try:
                laenge = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                laenge = -1
            if not 0 < laenge <= MAX_GROESSE:
                return self.antworte(413, {"fehler": "Anfrage zu groß"})
            try:
                daten = json.loads(self.rfile.read(laenge))
                prompt, modell = str(daten["prompt"]), str(daten.get("modell") or "")
            except (ValueError, KeyError, TypeError):
                return self.antworte(400, {"fehler": "Ungültige Anfrage"})
            if modell and not re.fullmatch(r"[A-Za-z0-9._\[\]-]{1,60}", modell):
                return self.antworte(400, {"fehler": "Ungültiges Modell"})
            if not eine.acquire(timeout=30):
                return self.antworte(429, {"fehler": "Claude ist gerade beschäftigt – gleich nochmal."})
            try:
                return self.antworte(200, {"antwort": frage(modell, prompt)})
            except ki.KIFehler as e:
                return self.antworte(502, {"fehler": str(e)})
            finally:
                eine.release()

    return H


def main() -> int:
    geheim = token()
    if len(geheim) < 24:
        print("Kein (ausreichend langes) Token für die Brücke im Schlüsselbund.", file=sys.stderr)
        return 1
    erlaubt = {a.strip() for a in os.environ.get("DBSTUDIO_BRUECKE_ERLAUBT", "192.168.178.215").split(",") if a.strip()}
    adresse = os.environ.get("DBSTUDIO_BRUECKE_ADRESSE", "192.168.178.86")
    port = int(os.environ.get("DBSTUDIO_BRUECKE_PORT", "8791"))
    server = ThreadingHTTPServer((adresse, port), baue_handler(geheim, erlaubt))
    print(f"KI-Brücke lauscht auf {adresse}:{port}, erlaubt: {', '.join(sorted(erlaubt))}", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
