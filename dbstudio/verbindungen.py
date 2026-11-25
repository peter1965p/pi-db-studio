"""Gespeicherte Verbindungen: Einstellungen in ~/.config/db-studio/verbindungen.json (Rechte 600),
Passwörter ausschließlich im Keyring (Dienst „db-studio“)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

DIENST = "db-studio"
FARBEN = {"": "keine", "#e05252": "rot (produktiv)", "#f5a623": "orange (Test)", "#5aa0e6": "blau (Entwicklung)",
          "#3ecf8e": "grün (lokal)", "#9a9eab": "grau"}


def ordner() -> Path:
    basis = Path(os.environ.get("DB_STUDIO_CONFIG") or (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "db-studio"))
    basis.mkdir(parents=True, exist_ok=True)
    try:
        basis.chmod(0o700)
    except OSError:
        pass
    return basis


def _datei() -> Path:
    return ordner() / "verbindungen.json"


def laden() -> list[dict]:
    try:
        daten = json.loads(_datei().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [v for v in daten.get("verbindungen", []) if isinstance(v, dict)]


def speichern(liste: list[dict]) -> None:
    d = _datei()
    tmp = d.with_suffix(".tmp")
    sauber = [{k: v for k, v in v.items() if k != "passwort"} for v in liste]  # nie ein Passwort in die Datei
    tmp.write_text(json.dumps({"verbindungen": sauber}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(d)


def neu(**werte) -> dict:
    v = {"id": uuid.uuid4().hex[:12], "name": "", "art": "postgresql", "host": "", "port": "", "datenbank": "",
         "benutzer": "", "sslmode": "prefer", "datei": "", "farbe": "", "schreibschutz": False}
    v.update(werte)
    return v


_DATEI = {"sqlite", "duckdb"}
_VON_AUSSEN = ("name", "art", "host", "port", "datenbank", "benutzer", "datei")


def uebernehmen(liste: list[dict], werte: dict) -> tuple[list[dict], dict, bool]:
    """Verbindung von außen (z. B. aus Visual Death Studio): vorhandene mit gleichem Ziel wiederverwenden, sonst neu
    anlegen. Gibt (Liste, Verbindung, neu?) zurück. Passwörter kommen nie von außen – die liegen im Schlüsselbund."""
    art = werte.get("art")
    if art not in ("postgresql", "mysql", "sqlite", "duckdb", "mssql"):
        raise ValueError(f"Unbekannte Datenbankart: {art}")

    def ziel(v):
        if art in _DATEI:
            return str(Path(v.get("datei") or "").expanduser().resolve())
        return (str(v.get("host") or "").lower(), str(v.get("port") or ""), v.get("datenbank") or "", v.get("benutzer") or "")
    for v in liste:
        if v.get("art") == art and ziel(v) == ziel(werte):
            return liste, v, False
    v = neu(**{k: str(werte[k]) for k in _VON_AUSSEN if werte.get(k) not in (None, "", 0)})
    if art in _DATEI:
        v["datei"] = ziel(werte)
        v["farbe"] = v.get("farbe") or "#3ecf8e"
    if not v.get("name"):
        v["name"] = Path(v["datei"]).name if art in _DATEI else f"{v.get('benutzer')}@{v.get('host')}/{v.get('datenbank')}"
    return liste + [v], v, True


def schluessel(v: dict) -> str:
    return f"verbindung:{v['id']}"


def passwort(v: dict) -> str | None:
    try:
        import keyring
        return keyring.get_password(DIENST, schluessel(v))
    except Exception:
        return None


def setze_passwort(v: dict, pw: str | None) -> None:
    import keyring
    if pw:
        keyring.set_password(DIENST, schluessel(v), pw)
    else:
        try:
            keyring.delete_password(DIENST, schluessel(v))
        except Exception:
            pass


def entfernen(liste: list[dict], vid: str) -> list[dict]:
    rest = [v for v in liste if v["id"] != vid]
    for v in liste:
        if v["id"] == vid:
            setze_passwort(v, None)
    return rest


def einstellungen() -> dict:
    try:
        return json.loads((ordner() / "einstellungen.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def setze_einstellungen(werte: dict) -> None:
    d = ordner() / "einstellungen.json"
    alt = einstellungen()
    alt.update(werte)
    d.write_text(json.dumps(alt, ensure_ascii=False, indent=2), encoding="utf-8")
    d.chmod(0o600)


def verlauf_datei() -> Path:
    return ordner() / "verlauf.jsonl"


def gemerktes_schema(v: dict) -> str | None:
    """Zuletzt gewähltes Schema einer Verbindung (in einstellungen.json)."""
    if not v or not v.get("id"):
        return None
    return (einstellungen().get("schemas") or {}).get(v["id"])


def merke_schema(v: dict, schema: str) -> None:
    if not v or not v.get("id") or not schema:
        return
    alle = dict(einstellungen().get("schemas") or {})
    alle[v["id"]] = schema
    setze_einstellungen({"schemas": alle})
