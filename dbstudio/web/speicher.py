"""Ablage der Web-Oberfläche: Verbindungen, Benutzer, KI-Einstellungen.

Alles liegt im Datenordner (Standard /var/lib/dbstudio-web, Rechte 700). Passwörter der Verbindungen und der
KI-Schlüssel werden mit Fernet (AES-128-CBC + HMAC) verschlüsselt; der Schlüssel kommt aus der Umgebung
(DBSTUDIO_SCHLUESSEL, aus der 600-Datei des Dienstes) und liegt nie im Datenordner. Nichts davon geht je an den Browser.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

FELDER = ("name", "art", "host", "port", "datenbank", "benutzer", "sslmode", "datei", "farbe", "schreibschutz")
ARTEN_OK = {"postgresql", "mysql", "sqlite", "duckdb", "mssql"}


class Speicher:
    def __init__(self, ordner: str | Path, schluessel: str | bytes):
        self.ordner = Path(ordner)
        self.ordner.mkdir(parents=True, exist_ok=True)
        try:
            self.ordner.chmod(0o700)
        except OSError:
            pass
        self.fernet = Fernet(schluessel)
        self.hasher = PasswordHasher()
        self.sperre = threading.RLock()

    # --- Dateien ---------------------------------------------------------------------------------------------------
    def _lies(self, name: str, leer):
        try:
            return json.loads((self.ordner / name).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return leer

    def _schreib(self, name: str, daten) -> None:
        d = self.ordner / name
        tmp = d.with_suffix(".tmp")
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(d)

    def _ver(self, text: str | None) -> str:
        return self.fernet.encrypt(text.encode()).decode() if text else ""

    def _ent(self, token: str) -> str | None:
        if not token:
            return None
        try:
            return self.fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None

    # --- Benutzer --------------------------------------------------------------------------------------------------
    def benutzer_setzen(self, name: str, passwort: str) -> None:
        if len(passwort) < 12:
            raise ValueError("Passwort braucht mindestens 12 Zeichen.")
        with self.sperre:
            alle = self._lies("benutzer.json", {})
            alle[name] = self.hasher.hash(passwort)
            self._schreib("benutzer.json", alle)

    def benutzer_pruefen(self, name: str, passwort: str) -> bool:
        h = self._lies("benutzer.json", {}).get(name)
        if not h:
            self.hasher.hash(passwort)  # gleiche Laufzeit wie bei vorhandenem Benutzer
            return False
        try:
            self.hasher.verify(h, passwort)
        except (VerificationError, InvalidHashError):
            return False
        if self.hasher.check_needs_rehash(h):
            self.benutzer_setzen(name, passwort)
        return True

    def hat_benutzer(self) -> bool:
        return bool(self._lies("benutzer.json", {}))

    # --- Verbindungen ----------------------------------------------------------------------------------------------
    def verbindungen(self) -> list[dict]:
        """Ohne Passwörter – so dürfen sie an den Browser."""
        out = []
        for v in self._lies("verbindungen.json", []):
            o = {k: v.get(k) for k in ("id", *FELDER)}
            o["hat_passwort"] = bool(v.get("pw"))
            out.append(o)
        return out

    def verbindung(self, vid: str) -> tuple[dict, str | None]:
        for v in self._lies("verbindungen.json", []):
            if v.get("id") == vid:
                return {k: v.get(k) for k in ("id", *FELDER)}, self._ent(v.get("pw", ""))
        raise KeyError(vid)

    def verbindung_speichern(self, werte: dict, passwort: str | None = None, passwort_loeschen: bool = False) -> dict:
        art = werte.get("art", "")
        if art not in ARTEN_OK:
            raise ValueError("Unbekannte Datenbankart.")
        with self.sperre:
            liste = self._lies("verbindungen.json", [])
            vid = werte.get("id") or uuid.uuid4().hex[:12]
            alt = next((v for v in liste if v.get("id") == vid), None)
            neu = {"id": vid, **{k: werte.get(k, "" if k != "schreibschutz" else False) for k in FELDER}}
            neu["schreibschutz"] = bool(neu["schreibschutz"])
            neu["pw"] = "" if passwort_loeschen else (self._ver(passwort) if passwort else (alt or {}).get("pw", ""))
            liste = [neu if v.get("id") == vid else v for v in liste] if alt else [*liste, neu]
            self._schreib("verbindungen.json", liste)
        return next(v for v in self.verbindungen() if v["id"] == vid)

    def verbindung_loeschen(self, vid: str) -> None:
        with self.sperre:
            self._schreib("verbindungen.json", [v for v in self._lies("verbindungen.json", []) if v.get("id") != vid])

    # --- Einstellungen (KI usw.) -------------------------------------------------------------------------------------
    def einstellungen(self) -> dict:
        e = self._lies("einstellungen.json", {})
        return {"ki_anbieter": e.get("ki_anbieter", "claude-api"), "ki_modell": e.get("ki_modell", ""),
                "ollama_url": e.get("ollama_url", "http://localhost:11434"), "hat_api_schluessel": bool(e.get("api"))}

    def einstellungen_setzen(self, werte: dict) -> dict:
        with self.sperre:
            e = self._lies("einstellungen.json", {})
            for k in ("ki_anbieter", "ki_modell", "ollama_url"):
                if k in werte:
                    e[k] = str(werte[k] or "")
            if werte.get("api_schluessel_loeschen"):
                e["api"] = ""
            elif werte.get("api_schluessel"):
                e["api"] = self._ver(werte["api_schluessel"])
            self._schreib("einstellungen.json", e)
        return self.einstellungen()

    def api_schluessel(self) -> str | None:
        return self._ent(self._lies("einstellungen.json", {}).get("api", ""))

    # --- Diagramm-Positionen -----------------------------------------------------------------------------------------
    def positionen(self, vid: str, schema: str) -> dict:
        return self._lies("diagramme.json", {}).get(f"{vid}|{schema}", {})

    def positionen_setzen(self, vid: str, schema: str, pos: dict) -> None:
        with self.sperre:
            alle = self._lies("diagramme.json", {})
            alle[f"{vid}|{schema}"] = {str(k): [round(float(x), 1), round(float(y), 1)] for k, (x, y) in pos.items()}
            self._schreib("diagramme.json", alle)


def neuer_schluessel() -> str:
    return Fernet.generate_key().decode()


def aus_umgebung() -> Speicher:
    ordner = os.environ.get("DBSTUDIO_WEB_DATEN", "/var/lib/dbstudio-web")
    schluessel = os.environ.get("DBSTUDIO_SCHLUESSEL")
    if not schluessel:
        raise SystemExit("DBSTUDIO_SCHLUESSEL fehlt (Fernet-Schlüssel aus der Geheimnis-Datei des Dienstes).")
    return Speicher(ordner, schluessel)
