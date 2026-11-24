"""Generische REST-API mit Berechtigungen für Pi DB Studio (Web).

Jede Tabelle jeder gespeicherten Verbindung ist unter /rest/v1/{verbindung}/{tabelle} erreichbar, aber nur mit einem
API-Schlüssel, der dafür eine Regel hat. Anmeldung: `Authorization: Bearer pi_…`.

Sicherheit:
- Tabellen- und Spaltennamen werden gegen das echte Schema geprüft und vom Treiber zitiert; Werte gehen nur als
  gebundene Parameter in die Datenbank. Freies SQL gibt es über diese Schnittstelle nicht.
- Schlüssel liegen nur als SHA-256-Hash vor (sie sind zufällig, 32 Byte), angezeigt wird der Schlüssel genau einmal.
- Regeln je Schlüssel: Verbindung, Tabelle (oder *), Aktionen (lesen, anlegen, aendern, loeschen), gesperrte Spalten
  und ein Zeilenfilter (Spalte = Wert), der für alle Aktionen gilt und beim Anlegen erzwungen wird.
- Verbindungen mit Schreibschutz erlauben nur Lesen. Rate-Limit je Schlüssel, Änderungen und Ablehnungen im Protokoll.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import treiber

AKTIONEN = ("lesen", "anlegen", "aendern", "loeschen")
ROLLEN = {"leser": ["lesen"], "schreiber": ["lesen", "anlegen", "aendern"], "admin": list(AKTIONEN)}
OPERATOREN = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "like": "LIKE"}
RESERVIERT = {"select", "order", "limit", "offset", "schema"}
MAX_LIMIT = 1000
PRAEFIX = "pi_"


def _hash(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode()).hexdigest()


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Schluesselablage:
    """API-Schlüssel und Regeln im Datenordner (rest.json, 600), Protokoll als rest_protokoll.jsonl."""

    def __init__(self, speicher):
        self.sp = speicher
        self.sperre = threading.RLock()

    def alle(self) -> list[dict]:
        return self.sp._lies("rest.json", [])

    def _speichern(self, liste: list[dict]) -> None:
        self.sp._schreib("rest.json", liste)

    def oeffentlich(self) -> list[dict]:
        return [{k: v for k, v in s.items() if k != "hash"} for s in self.alle()]

    def anlegen(self, name: str, regeln: list[dict], limit_minute: int = 120) -> tuple[dict, str]:
        roh = PRAEFIX + secrets.token_urlsafe(32)
        eintrag = {"id": uuid.uuid4().hex[:12], "name": name.strip()[:80] or "API-Schlüssel", "hash": _hash(roh),
                   "anfang": roh[:10], "regeln": [pruefe_regel(r) for r in regeln], "aktiv": True,
                   "limit_minute": max(1, min(int(limit_minute), 6000)), "erstellt": _jetzt(), "zuletzt": None}
        with self.sperre:
            liste = self.alle()
            liste.append(eintrag)
            self._speichern(liste)
        return {k: v for k, v in eintrag.items() if k != "hash"}, roh

    def aendern(self, sid: str, werte: dict) -> dict:
        with self.sperre:
            liste = self.alle()
            for s in liste:
                if s["id"] == sid:
                    if "name" in werte:
                        s["name"] = str(werte["name"]).strip()[:80] or s["name"]
                    if "aktiv" in werte:
                        s["aktiv"] = bool(werte["aktiv"])
                    if "limit_minute" in werte:
                        s["limit_minute"] = max(1, min(int(werte["limit_minute"]), 6000))
                    if "regeln" in werte:
                        s["regeln"] = [pruefe_regel(r) for r in werte["regeln"]]
                    self._speichern(liste)
                    return {k: v for k, v in s.items() if k != "hash"}
        raise KeyError(sid)

    def loeschen(self, sid: str) -> None:
        with self.sperre:
            liste = [s for s in self.alle() if s["id"] != sid]
            self._speichern(liste)

    def finde(self, roh: str) -> dict | None:
        if not roh.startswith(PRAEFIX):
            return None
        h = _hash(roh)
        for s in self.alle():
            if hmac.compare_digest(s["hash"], h):
                return s
        return None

    def merke_nutzung(self, sid: str) -> None:
        with self.sperre:
            liste = self.alle()
            for s in liste:
                if s["id"] == sid:
                    s["zuletzt"] = _jetzt()
            self._speichern(liste)

    def protokolliere(self, eintrag: dict) -> None:
        datei = self.sp.ordner / "rest_protokoll.jsonl"
        with self.sperre:
            with datei.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"zeit": _jetzt(), **eintrag}, ensure_ascii=False) + "\n")
            datei.chmod(0o600)

    def protokoll(self, anzahl: int = 200) -> list[dict]:
        datei = self.sp.ordner / "rest_protokoll.jsonl"
        try:
            zeilen = datei.read_text(encoding="utf-8").splitlines()[-anzahl:]
        except FileNotFoundError:
            return []
        return [json.loads(z) for z in reversed(zeilen) if z.strip()]


def pruefe_regel(r: dict) -> dict:
    """Normalisiert eine Regel und lehnt Unsinn ab."""
    if not isinstance(r, dict) or not r.get("verbindung"):
        raise ValueError("Eine Regel braucht eine Verbindung.")
    aktionen = r.get("aktionen") or ROLLEN.get(r.get("rolle", ""), [])
    if not aktionen or any(a not in AKTIONEN for a in aktionen):
        raise ValueError(f"Aktionen nur aus {', '.join(AKTIONEN)}.")
    filter_ = r.get("zeilenfilter") or {}
    if not isinstance(filter_, dict) or any(not isinstance(v, (str, int, float, bool)) for v in filter_.values()):
        raise ValueError("Zeilenfilter: Spalte → einfacher Wert.")
    return {"verbindung": str(r["verbindung"]), "schema": str(r.get("schema") or ""), "tabelle": str(r.get("tabelle") or "*"),
            "aktionen": list(dict.fromkeys(aktionen)), "spalten_gesperrt": [str(s) for s in r.get("spalten_gesperrt") or []],
            "zeilenfilter": filter_}


def regel_fuer(schluessel: dict, vid: str, tabelle: str, aktion: str) -> dict | None:
    """Die spezifischste Regel (Tabelle vor *), die die Aktion erlaubt."""
    passend = [r for r in schluessel.get("regeln", []) if r["verbindung"] == vid and r["tabelle"] in (tabelle, "*")]
    passend.sort(key=lambda r: r["tabelle"] == "*")
    for r in passend:
        return r if aktion in r["aktionen"] else None
    return None


# --- Router ------------------------------------------------------------------------------------------------------------

def erstelle_router(sp, ablage: Schluesselablage) -> APIRouter:
    router = APIRouter(prefix="/rest/v1")
    treiber_je_vid: dict[str, treiber.Treiber] = {}
    sperre = threading.Lock()
    zaehler: dict[str, deque] = defaultdict(deque)

    def ablehnen(code: int, text: str, request: Request, schluessel: dict | None = None, **mehr):
        ablage.protokolliere({"schluessel": (schluessel or {}).get("id"), "methode": request.method,
                              "pfad": request.url.path, "status": code, "grund": text, **mehr})
        raise HTTPException(code, text)

    def anmelden(request: Request) -> dict:
        kopf = request.headers.get("authorization", "")
        roh = kopf[7:].strip() if kopf.lower().startswith("bearer ") else ""
        s = ablage.finde(roh) if roh else None
        if not s or not s.get("aktiv"):
            ablehnen(401, "Gültiger API-Schlüssel nötig (Authorization: Bearer pi_…).", request)
        jetzt = time.monotonic()
        with sperre:
            q = zaehler[s["id"]]
            while q and jetzt - q[0] > 60:
                q.popleft()
            if len(q) >= s.get("limit_minute", 120):
                ablehnen(429, "Zu viele Anfragen, bitte kurz warten.", request, s)
            q.append(jetzt)
        return s

    def oeffne(vid: str) -> tuple[treiber.Treiber, dict]:
        try:
            cfg, pw = sp.verbindung(vid)
        except KeyError:
            raise HTTPException(404, "Verbindung unbekannt.")
        with sperre:
            t = treiber_je_vid.get(vid)
            if t is None:
                try:
                    t = treiber.oeffne(cfg, pw)
                except Exception as e:
                    raise HTTPException(502, f"Verbindung fehlgeschlagen: {type(e).__name__}")
                treiber_je_vid[vid] = t
        return t, cfg

    def ziel(request: Request, vid: str, tabelle: str, aktion: str):
        """Prüft Schlüssel, Regel, Tabelle und liefert alles für die Abfrage."""
        s = anmelden(request)
        regel = regel_fuer(s, vid, tabelle, aktion)
        if regel is None:
            ablehnen(403, f"Keine Berechtigung: {aktion} auf {tabelle}.", request, s)
        t, cfg = oeffne(vid)
        if aktion != "lesen" and cfg.get("schreibschutz"):
            ablehnen(403, "Die Verbindung ist schreibgeschützt.", request, s)
        schema = request.query_params.get("schema") or regel["schema"] or t.aktuelles_schema or t.standard_schema()
        if regel["schema"] and schema != regel["schema"]:
            ablehnen(403, "Kein Zugriff auf dieses Schema.", request, s)
        try:
            tabellen = t.objekte(schema)
        except Exception:
            raise HTTPException(404, "Schema unbekannt.")
        if tabelle not in tabellen.get("tabellen", []) + tabellen.get("views", []):
            raise HTTPException(404, "Tabelle unbekannt.")
        spalten = {sp_.name: sp_ for sp_ in t.spalten(schema, tabelle)}
        sichtbar = [n for n in spalten if n not in regel["spalten_gesperrt"]]
        return s, regel, t, schema, spalten, sichtbar

    def bedingungen(t, regel, spalten, sichtbar, filter_: dict[str, str]) -> tuple[list[str], list]:
        teile, werte = [], []
        for spalte, wert_ in regel["zeilenfilter"].items():  # Pflicht aus der Regel, nicht abwählbar
            if spalte not in spalten:
                raise HTTPException(500, "Regel nennt eine unbekannte Spalte.")
            teile.append(f"{t.zitiere(spalte)} = {t.platzhalter}")
            werte.append(wert_)
        for spalte, ausdruck in filter_.items():
            if spalte not in sichtbar:
                raise HTTPException(400, f"Unbekannte oder gesperrte Spalte: {spalte}")
            op, _, wert_ = ausdruck.partition(".")
            if op == "is" and wert_ in ("null", "notnull"):
                teile.append(f"{t.zitiere(spalte)} IS {'NOT ' if wert_ == 'notnull' else ''}NULL")
                continue
            if op not in OPERATOREN:
                raise HTTPException(400, f"Operator {op!r} unbekannt. Erlaubt: {', '.join(OPERATOREN)}, is.null")
            teile.append(f"{t.zitiere(spalte)} {OPERATOREN[op]} {t.platzhalter}")
            werte.append(wert_)
        return teile, werte

    def pk_von(spalten) -> str:
        pks = [n for n, s_ in spalten.items() if s_.pk]
        if len(pks) != 1:
            raise HTTPException(400, "Einzelzugriff braucht genau eine Primärschlüssel-Spalte.")
        return pks[0]

    def zeilen_json(erg, erlaubt: list[str]) -> list[dict]:
        from .app import wert
        idx = [i for i, n in enumerate(erg.spalten) if n in erlaubt]
        return [{erg.spalten[i]: wert(z[i]) for i in idx} for z in erg.zeilen]

    def schreib_werte(daten, sichtbar, regel) -> dict:
        if not isinstance(daten, dict) or not daten:
            raise HTTPException(400, "Erwartet ein JSON-Objekt mit Spalten.")
        unbekannt = [k for k in daten if k not in sichtbar]
        if unbekannt:
            raise HTTPException(400, f"Unbekannte oder gesperrte Spalten: {', '.join(unbekannt[:5])}")
        for spalte, wert_ in regel["zeilenfilter"].items():
            if spalte in daten and str(daten[spalte]) != str(wert_):
                raise HTTPException(403, f"{spalte} ist durch die Regel festgelegt.")
        return daten

    @router.get("/{vid}/{tabelle}")
    def liste(vid: str, tabelle: str, request: Request):
        s, regel, t, schema, spalten, sichtbar = ziel(request, vid, tabelle, "lesen")
        q = request.query_params
        auswahl = [x for x in (q.get("select") or "").split(",") if x] or sichtbar
        if any(x not in sichtbar for x in auswahl):
            raise HTTPException(400, "select nennt unbekannte oder gesperrte Spalten.")
        filter_ = {k: v for k, v in q.items() if k not in RESERVIERT}
        teile, werte = bedingungen(t, regel, spalten, sichtbar, filter_)
        sql = f"SELECT {', '.join(t.zitiere(x) for x in auswahl)} FROM {t.voll(schema, tabelle)}"
        if teile:
            sql += " WHERE " + " AND ".join(teile)
        ordnung = []
        for teil in [x for x in (q.get("order") or "").split(",") if x]:
            spalte, _, richtung = teil.partition(".")
            if spalte not in sichtbar or richtung not in ("", "asc", "desc"):
                raise HTTPException(400, "order: spalte.asc oder spalte.desc")
            ordnung.append(f"{t.zitiere(spalte)} {'DESC' if richtung == 'desc' else 'ASC'}")
        if ordnung:
            sql += " ORDER BY " + ", ".join(ordnung)
        try:
            limit = max(1, min(int(q.get("limit", 100)), MAX_LIMIT))
            offset = max(0, int(q.get("offset", 0)))
        except ValueError:
            raise HTTPException(400, "limit und offset sind Zahlen.")
        sql += t.seite(offset, limit, bool(ordnung))
        try:
            erg = t.abfrage(sql, werte or None, limit=limit)
        except treiber.DBFehler as e:
            raise HTTPException(400, str(e))
        ablage.merke_nutzung(s["id"])
        return {"daten": zeilen_json(erg, auswahl), "limit": limit, "offset": offset, "weitere": erg.mehr}

    @router.get("/{vid}/{tabelle}/{pk}")
    def einzeln(vid: str, tabelle: str, pk: str, request: Request):
        s, regel, t, schema, spalten, sichtbar = ziel(request, vid, tabelle, "lesen")
        pkname = pk_von(spalten)
        teile, werte = bedingungen(t, regel, spalten, sichtbar, {})
        teile.insert(0, f"{t.zitiere(pkname)} = {t.platzhalter}")
        werte.insert(0, pk)
        sql = f"SELECT {', '.join(t.zitiere(x) for x in sichtbar)} FROM {t.voll(schema, tabelle)} WHERE " + " AND ".join(teile)
        try:
            erg = t.abfrage(sql, werte, limit=1)
        except treiber.DBFehler as e:
            raise HTTPException(400, str(e))
        daten = zeilen_json(erg, sichtbar)
        if not daten:
            raise HTTPException(404, "Kein Datensatz.")
        return daten[0]

    def schreiben(request, s, t, sql, werte, aktion, vid, tabelle):
        try:
            erg = t.abfrage(sql, werte)
        except treiber.DBFehler as e:
            ablage.protokolliere({"schluessel": s["id"], "methode": request.method, "pfad": request.url.path,
                                  "status": 400, "grund": str(e)[:200]})
            raise HTTPException(400, str(e))
        ablage.protokolliere({"schluessel": s["id"], "name": s["name"], "aktion": aktion, "verbindung": vid,
                              "tabelle": tabelle, "betroffen": erg.betroffen, "status": 200})
        ablage.merke_nutzung(s["id"])
        return erg.betroffen

    @router.post("/{vid}/{tabelle}")
    async def anlegen(vid: str, tabelle: str, request: Request):
        s, regel, t, schema, spalten, sichtbar = ziel(request, vid, tabelle, "anlegen")
        daten = schreib_werte(await request.json(), sichtbar, regel)
        daten = {**daten, **regel["zeilenfilter"]}  # Zeilenfilter wird beim Anlegen erzwungen
        sql = t.einfuegen_sql(schema, tabelle, list(daten))
        n = schreiben(request, s, t, sql, list(daten.values()), "anlegen", vid, tabelle)
        return JSONResponse({"ok": True, "betroffen": n}, status_code=201)

    @router.patch("/{vid}/{tabelle}/{pk}")
    async def aendern(vid: str, tabelle: str, pk: str, request: Request):
        s, regel, t, schema, spalten, sichtbar = ziel(request, vid, tabelle, "aendern")
        pkname = pk_von(spalten)
        daten = schreib_werte(await request.json(), sichtbar, regel)
        if pkname in daten:
            raise HTTPException(400, "Der Primärschlüssel wird nicht geändert.")
        teile, werte = bedingungen(t, regel, spalten, sichtbar, {})
        setzen = ", ".join(f"{t.zitiere(k)} = {t.platzhalter}" for k in daten)
        sql = (f"UPDATE {t.voll(schema, tabelle)} SET {setzen} WHERE "
               + " AND ".join([f"{t.zitiere(pkname)} = {t.platzhalter}", *teile]))
        n = schreiben(request, s, t, sql, [*daten.values(), pk, *werte], "aendern", vid, tabelle)
        if n == 0:
            raise HTTPException(404, "Kein Datensatz.")
        return {"ok": True, "betroffen": n}

    @router.delete("/{vid}/{tabelle}/{pk}")
    def loeschen(vid: str, tabelle: str, pk: str, request: Request):
        s, regel, t, schema, spalten, sichtbar = ziel(request, vid, tabelle, "loeschen")
        pkname = pk_von(spalten)
        teile, werte = bedingungen(t, regel, spalten, sichtbar, {})
        sql = f"DELETE FROM {t.voll(schema, tabelle)} WHERE " + " AND ".join([f"{t.zitiere(pkname)} = {t.platzhalter}", *teile])
        n = schreiben(request, s, t, sql, [pk, *werte], "loeschen", vid, tabelle)
        if n == 0:
            raise HTTPException(404, "Kein Datensatz.")
        return {"ok": True, "betroffen": n}

    return router


def openapi_fuer(sp, schluessel: dict, version: str) -> dict:
    """OpenAPI-3-Beschreibung genau der Tabellen, die dieser Schlüssel sehen darf."""
    pfade = {}
    for r in schluessel.get("regeln", []):
        try:
            cfg, pw = sp.verbindung(r["verbindung"])
            t = treiber.oeffne(cfg, pw)
        except Exception:
            continue
        try:
            schema = r["schema"] or t.standard_schema()
            tabellen = t.objekte(schema)["tabellen"] if r["tabelle"] == "*" else [r["tabelle"]]
            for tab in tabellen:
                eigenschaften = {s.name: {"type": {"ganzzahl": "integer", "grosse_ganzzahl": "integer", "kommazahl": "number",
                                                   "dezimal": "number", "wahrheitswert": "boolean"}.get(s.generisch, "string")}
                                 for s in t.spalten(schema, tab) if s.name not in r["spalten_gesperrt"]}
                basis = f"/rest/v1/{r['verbindung']}/{tab}"
                obj = {"type": "object", "properties": eigenschaften}
                ops = {}
                if "lesen" in r["aktionen"]:
                    ops["get"] = {"summary": f"{tab} lesen", "responses": {"200": {"description": "Liste"}}}
                if "anlegen" in r["aktionen"]:
                    ops["post"] = {"summary": f"{tab} anlegen", "requestBody": {"content": {"application/json": {"schema": obj}}},
                                   "responses": {"201": {"description": "angelegt"}}}
                pfade[basis] = ops
                einzel = {}
                if "lesen" in r["aktionen"]:
                    einzel["get"] = {"summary": f"{tab} nach Primärschlüssel", "responses": {"200": {"description": "Datensatz"}}}
                if "aendern" in r["aktionen"]:
                    einzel["patch"] = {"summary": f"{tab} ändern", "requestBody": {"content": {"application/json": {"schema": obj}}},
                                       "responses": {"200": {"description": "geändert"}}}
                if "loeschen" in r["aktionen"]:
                    einzel["delete"] = {"summary": f"{tab} löschen", "responses": {"200": {"description": "gelöscht"}}}
                if einzel:
                    pfade[basis + "/{pk}"] = {**einzel, "parameters": [{"name": "pk", "in": "path", "required": True,
                                                                         "schema": {"type": "string"}}]}
        finally:
            t.schliessen()
    return {"openapi": "3.1.0", "info": {"title": "Pi DB Studio REST", "version": version},
            "components": {"securitySchemes": {"schluessel": {"type": "http", "scheme": "bearer"}}},
            "security": [{"schluessel": []}], "paths": pfade}
