"""KI-Assistent: natürliche Sprache -> SQL, Abfrage erklären/optimieren, Fehler erklären.

Anbieter (wie im Job Agent):
- „claude-api“: Anthropic-API, Schlüssel im Keyring (Dienst „db-studio“, Eintrag „anthropic-api“)
- „claude-code“: das angemeldete Claude Code auf diesem Rechner (Abo statt API-Schlüssel)
- „ollama:<modell>“: lokales Modell, nichts verlässt den Rechner
- „claude-bruecke“: (nur Web) Claude Code auf dem PC über die KI-Brücke (dbstudio.claude_bruecke, Token-geschützt)

An die KI geht standardmäßig nur das Schema (Tabellen, Spalten, Typen). Datenzeilen nur, wenn der Schalter
„Beispielzeilen mitsenden“ an ist. Erzeugtes SQL wird nie automatisch ausgeführt.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from .treiber import ARTEN, Treiber

DIENST = "db-studio"
API_EINTRAG = "anthropic-api"
STANDARD_MODELL = "claude-opus-5-5"
OLLAMA_URL = "http://localhost:11434"
ZEIT = 180


class KIFehler(Exception):
    pass


# --- Kontext ------------------------------------------------------------------------------------------------------
def schema_kontext(t: Treiber, schema: str, max_tabellen: int = 80, beispielzeilen: int = 0) -> str:
    """Kompakte Schema-Beschreibung für das Modell; Datenzeilen nur auf ausdrücklichen Wunsch."""
    o = t.objekte(schema)
    zeilen = [f"Datenbank: {ARTEN.get(t.art, t.art)}, Schema: {schema}"]
    for name in (o["tabellen"] + o["views"])[:max_tabellen]:
        try:
            sp = t.spalten(schema, name)
        except Exception:
            continue
        art = "VIEW " if name in o["views"] else ""
        zeilen.append(f"{art}{name}(" + ", ".join(f"{s.name} {s.typ}{' PK' if s.pk else ''}" for s in sp) + ")")
        if beispielzeilen:
            try:
                erg = t.zeilen(schema, name, 0, beispielzeilen)
                for z in erg.zeilen:
                    zeilen.append("  Beispiel: " + json.dumps([str(v)[:40] if v is not None else None for v in z], ensure_ascii=False))
            except Exception:
                pass
    rest = len(o["tabellen"]) + len(o["views"]) - max_tabellen
    if rest > 0:
        zeilen.append(f"… und {rest} weitere Tabellen/Views")
    return "\n".join(zeilen)


SYSTEM = ("Du bist der SQL-Assistent im Pi DB Studio. Antworte auf Deutsch, knapp und fachlich. "
          "Schreibe SQL im Dialekt der genannten Datenbank und nur gegen Tabellen und Spalten aus dem Schema. "
          "Wenn du SQL lieferst, dann genau einen Block ```sql … ```. Erfinde keine Spalten; fehlt etwas, sag es.")


def _aufgabe(art: str, kontext: str, **w) -> str:
    if art == "sql":
        return f"{kontext}\n\nAufgabe: Schreibe eine SQL-Abfrage für: {w['text']}\nErkläre danach in einem Satz, was sie tut."
    if art == "erklaeren":
        return f"{kontext}\n\nErkläre diese Abfrage Schritt für Schritt in einfachen Worten:\n```sql\n{w['sql']}\n```"
    if art == "optimieren":
        plan = f"\n\nAusführungsplan (EXPLAIN):\n{w['plan']}" if w.get("plan") else ""
        return (f"{kontext}\n\nPrüfe diese Abfrage auf Geschwindigkeit und Lesbarkeit. Nenne die wichtigsten Punkte "
                f"(z. B. fehlende Indizes mit CREATE INDEX) und liefere die verbesserte Fassung:\n```sql\n{w['sql']}\n```{plan}")
    if art == "fehler":
        return (f"{kontext}\n\nDiese Abfrage schlug fehl:\n```sql\n{w['sql']}\n```\nFehlermeldung: {w['fehler']}\n"
                "Erkläre kurz die Ursache und liefere die korrigierte Abfrage.")
    if art == "beziehungen":
        return (f"{kontext}\n\nVorhandene Fremdschlüssel:\n{w.get('fks') or '(keine)'}\n\n"
                "Welche Fremdschlüssel fehlen vermutlich (anhand von Spaltennamen und Typen)? Nenne je Vorschlag kurz den "
                "Grund und liefere alle als EINEN ```sql```-Block mit ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY "
                "(im Dialekt der Datenbank). Schlage nur Beziehungen zwischen vorhandenen Spalten vor.")
    if art == "vorlage":  # Datenmodell für eine neue Datenbank (vorlagen.ki_aufgabe baut die Aufgabe)
        return w["aufgabe"]
    raise ValueError(art)


def sql_aus_antwort(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*\n(.*?)```", text, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


# --- Anbieter -----------------------------------------------------------------------------------------------------
def api_schluessel() -> str | None:
    try:
        import keyring
        return keyring.get_password(DIENST, API_EINTRAG)
    except Exception:
        return None


def setze_api_schluessel(wert: str | None) -> None:
    import keyring
    if wert:
        keyring.set_password(DIENST, API_EINTRAG, wert)
    else:
        try:
            keyring.delete_password(DIENST, API_EINTRAG)
        except Exception:
            pass


def claude_pfad() -> str | None:
    gefunden = shutil.which("claude")
    if gefunden:
        return gefunden
    lokal = Path.home() / ".local/bin/claude"
    return str(lokal) if lokal.is_file() else None


def ollama_modelle(url: str = OLLAMA_URL) -> list[str]:
    try:
        r = httpx.get(f"{url}/api/tags", timeout=3)
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []


def anbieter_liste() -> list[tuple[str, str]]:
    """(kennung, beschriftung) – nur was hier wirklich nutzbar ist."""
    liste = [("claude-api", "Claude (API-Schlüssel)" + ("" if api_schluessel() else " – Schlüssel fehlt"))]
    if claude_pfad():
        liste.append(("claude-code", "Claude (Claude Code, Abo)"))
    liste += [(f"ollama:{m}", f"Lokal: {m}") for m in ollama_modelle()]
    return liste


def _claude_api(modell: str, nutzer: str) -> str:
    schluessel = api_schluessel()
    if not schluessel:
        raise KIFehler("Kein API-Schlüssel hinterlegt (Einstellungen → KI).")
    import anthropic
    client = anthropic.Anthropic(api_key=schluessel, timeout=ZEIT)
    try:
        antwort = client.messages.create(model=modell or STANDARD_MODELL, max_tokens=16000, system=SYSTEM,
                                         output_config={"effort": "low"},
                                         messages=[{"role": "user", "content": nutzer}])
    except anthropic.AuthenticationError as e:
        raise KIFehler("API-Schlüssel ungültig.") from e
    except anthropic.RateLimitError as e:
        raise KIFehler("Zu viele Anfragen – kurz warten.") from e
    except anthropic.APIStatusError as e:
        raise KIFehler(f"Claude-API meldet {e.status_code}.") from e
    except anthropic.APIConnectionError as e:
        raise KIFehler("Claude-API nicht erreichbar.") from e
    if antwort.stop_reason == "refusal":
        raise KIFehler("Claude hat die Anfrage abgelehnt.")
    return "".join(b.text for b in antwort.content if getattr(b, "type", "") == "text").strip()


def _claude_code(modell: str, nutzer: str) -> str:
    pfad = claude_pfad()
    if not pfad:
        raise KIFehler("Claude Code ist nicht installiert.")
    befehl = [pfad, "-p", "--output-format", "json", "--no-session-persistence", "--tools", "",
              "--strict-mcp-config", "--setting-sources", "", "--system-prompt", SYSTEM]
    if modell:
        befehl += ["--model", modell]
    try:
        lauf = subprocess.run(befehl, input=nutzer, capture_output=True, text=True, timeout=ZEIT, cwd=Path.home())
    except subprocess.TimeoutExpired as e:
        raise KIFehler(f"Claude hat nach {ZEIT} s nicht geantwortet.") from e
    try:
        daten = json.loads(lauf.stdout)
    except ValueError as e:
        raise KIFehler(f"Claude Code meldet: {(lauf.stderr or lauf.stdout)[:200]}") from e
    if daten.get("is_error"):
        raise KIFehler(f"Claude meldet: {str(daten.get('result'))[:200]}")
    return str(daten.get("result") or "").strip()


def _ollama(modell: str, nutzer: str, url: str = OLLAMA_URL) -> str:
    try:
        r = httpx.post(f"{url}/api/chat", timeout=ZEIT, json={
            "model": modell, "stream": False, "options": {"temperature": 0.1},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": nutzer}]})
    except httpx.HTTPError as e:
        raise KIFehler("Ollama ist nicht erreichbar (läuft `ollama serve`?).") from e
    if r.status_code == 404:
        raise KIFehler(f"Modell „{modell}“ fehlt: ollama pull {modell}")
    if r.status_code != 200:
        raise KIFehler(f"Ollama meldet {r.status_code}.")
    return r.json().get("message", {}).get("content", "").strip()


def bruecke_konfig() -> tuple[str, str]:
    """Adresse und Token der Claude-Code-Brücke (Web: aus der Geheimnisdatei des Dienstes)."""
    return os.environ.get("DBSTUDIO_CLAUDE_BRUECKE_URL", "").rstrip("/"), os.environ.get("DBSTUDIO_CLAUDE_BRUECKE_TOKEN", "")


def _claude_bruecke(modell: str, nutzer: str) -> str:
    url, token = bruecke_konfig()
    if not url or not token:
        raise KIFehler("Claude-Code-Brücke ist nicht eingerichtet.")
    try:
        r = httpx.post(f"{url}/frage", timeout=ZEIT + 15, headers={"X-Bruecke-Token": token},
                       json={"prompt": nutzer, "modell": modell or ""})
    except httpx.HTTPError as e:
        raise KIFehler("Claude-Code-Brücke auf dem PC nicht erreichbar (PC aus oder Dienst gestoppt?).") from e
    if r.status_code == 200:
        return str(r.json().get("antwort", "")).strip()
    try:
        meldung = r.json().get("fehler", "")
    except ValueError:
        meldung = ""
    raise KIFehler(meldung or f"Claude-Code-Brücke meldet {r.status_code}.")


def frage(anbieter: str, art: str, kontext: str, modell: str = "", **werte) -> str:
    nutzer = _aufgabe(art, kontext, **werte)
    if anbieter == "claude-api":
        return _claude_api(modell or STANDARD_MODELL, nutzer)
    if anbieter == "claude-code":
        return _claude_code(modell, nutzer)
    if anbieter == "claude-bruecke":
        return _claude_bruecke(modell, nutzer)
    if anbieter.startswith("ollama:"):
        return _ollama(anbieter.split(":", 1)[1], nutzer)
    raise KIFehler("Kein KI-Anbieter gewählt (Einstellungen → KI).")
