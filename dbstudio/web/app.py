"""Pi DB Studio – Web-Oberfläche (FastAPI). Nutzt den Kern der Desktop-App: Treiber, Metadaten, Schutzregeln,
Import/Export, KI, ER-Modell/DDL und EF-Core – hier liegt nur die HTTP-Schicht mit Anmeldung und Sitzungen."""

from __future__ import annotations

import datetime as dt
import decimal
import os
import secrets
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .. import __version__, austausch, efcore, erm, ki, sqlschutz, treiber
from ..treiber import ARTEN, GENERISCH, Spalte
from .speicher import Speicher, aus_umgebung

STATISCH = Path(__file__).parent / "static"
COOKIE = "pi_sitzung"
SITZUNG_DAUER = 12 * 3600
PRODUKTIV_FARBE = "#e05252"


# --- Hilfen -----------------------------------------------------------------------------------------------------------
def wert(v):
    """Datenbankwert -> JSON."""
    if v is None or isinstance(v, (bool, int, float, str)):
        if isinstance(v, float):
            return None if v != v else float(f"{v:.12g}")  # 389.20000000000005 -> 389.2
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        return "\\x" + b[:64].hex() + ("…" if len(b) > 64 else "")
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (list, dict)):
        return v
    return str(v)


def ergebnis_json(e: treiber.Ergebnis, handle: str | None = None) -> dict:
    return {"spalten": e.spalten, "zeilen": [[wert(x) for x in z] for z in e.zeilen], "betroffen": e.betroffen,
            "dauer": round(e.dauer, 4), "mehr": e.mehr, "handle": handle if e.mehr else None}


class Sitzung:
    def __init__(self, benutzer: str):
        self.benutzer = benutzer
        self.ablauf = time.time() + SITZUNG_DAUER
        self.verbindungen: dict[str, treiber.Treiber] = {}
        self.handles: dict[str, tuple[str, treiber.Ergebnis]] = {}
        self.sperre = threading.RLock()

    def schliessen(self):
        for e in [e for _, e in self.handles.values()]:
            e.schliessen()
        self.handles.clear()
        for t in self.verbindungen.values():
            try:
                t.schliessen()
            except Exception:
                pass
        self.verbindungen.clear()


# --- Modelle ----------------------------------------------------------------------------------------------------------
class Login(BaseModel):
    benutzer: str = Field(max_length=64)
    passwort: str = Field(max_length=256)


class VerbindungIn(BaseModel):
    id: str = ""
    name: str = Field("", max_length=120)
    art: str
    host: str = ""
    port: str | int = ""
    datenbank: str = ""
    benutzer: str = ""
    sslmode: str = "prefer"
    datei: str = ""
    farbe: str = ""
    schreibschutz: bool = False
    passwort: str | None = None
    passwort_loeschen: bool = False


class SqlIn(BaseModel):
    sql: str = Field(max_length=2_000_000)
    schema_: str = Field("", alias="schema")
    bestaetigt: bool = False
    limit: int = Field(500, ge=1, le=10000)


class Aenderung(BaseModel):
    art: str  # update | insert | delete
    pk: dict = {}
    werte: dict = {}


class AenderungenIn(BaseModel):
    schema_: str = Field("", alias="schema")
    tabelle: str
    aenderungen: list[Aenderung]


class KiIn(BaseModel):
    art: str
    schema_: str = Field("", alias="schema")
    text: str = ""
    sql: str = ""
    fehler: str = ""
    beispiele: bool = False


class SpalteIn(BaseModel):
    name: str
    typ: str = "text"
    pk: bool = False
    nullbar: bool = True


class DdlIn(BaseModel):
    aktion: str  # tabelle | spalte | spalte_aendern | fk
    schema_: str = Field("", alias="schema")
    tabelle: str = ""
    spalten: list[SpalteIn] = []
    spalte: SpalteIn | None = None
    alt: str = ""
    fk_spalten: list[str] = []
    ziel: str = ""
    ziel_spalten: list[str] = []
    bei_loeschen: str = "NO ACTION"
    bei_aendern: str = "NO ACTION"


class AusfuehrenIn(BaseModel):
    anweisungen: list[str]
    bestaetigt: bool = False


# --- App --------------------------------------------------------------------------------------------------------------
def erstelle_app(speicher: Speicher | None = None, cookie_secure: bool = True) -> FastAPI:
    sp = speicher or aus_umgebung()
    os.environ.setdefault("DB_STUDIO_CONFIG", str(sp.ordner / "kern"))
    ki.api_schluessel = sp.api_schluessel  # KI-Schlüssel kommt verschlüsselt aus dem Speicher, nicht aus dem Keyring

    app = FastAPI(title="Pi DB Studio", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    sitzungen: dict[str, Sitzung] = {}
    versuche: dict[str, deque] = defaultdict(deque)
    sperre = threading.Lock()

    @app.middleware("http")
    async def kopfzeilen(request: Request, call_next):
        if request.method not in ("GET", "HEAD") and request.url.path.startswith("/api/") \
                and request.headers.get("x-pi-anfrage") != "1":
            return JSONResponse({"detail": "Anfrage ohne Kennung abgelehnt."}, status_code=403)
        antwort = await call_next(request)
        antwort.headers["X-Content-Type-Options"] = "nosniff"
        antwort.headers["X-Frame-Options"] = "DENY"
        antwort.headers["Referrer-Policy"] = "no-referrer"
        antwort.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if request.url.path.startswith("/api/"):
            antwort.headers["Cache-Control"] = "no-store"
        return antwort

    # Sitzungen ---------------------------------------------------------------------------------------------------
    def sitzung(request: Request) -> Sitzung:
        token = request.cookies.get(COOKIE, "")
        with sperre:
            s = sitzungen.get(token)
            if not s or s.ablauf < time.time():
                if s:
                    s.schliessen()
                    sitzungen.pop(token, None)
                raise HTTPException(401, "Bitte anmelden.")
            s.ablauf = time.time() + SITZUNG_DAUER
        return s

    def verbindung(s: Sitzung, vid: str) -> tuple[treiber.Treiber, dict]:
        try:
            cfg, pw = sp.verbindung(vid)
        except KeyError:
            raise HTTPException(404, "Verbindung unbekannt.")
        with s.sperre:
            t = s.verbindungen.get(vid)
            if t is None:
                try:
                    t = treiber.oeffne(cfg, pw)
                except treiber.DBFehler as e:
                    raise HTTPException(502, str(e))
                except Exception as e:
                    raise HTTPException(502, f"Verbindung fehlgeschlagen: {type(e).__name__}")
                s.verbindungen[vid] = t
            t.schreibschutz = bool(cfg.get("schreibschutz"))
        return t, cfg

    def schema_von(t: treiber.Treiber, schema: str) -> str:
        return schema or t.aktuelles_schema or t.standard_schema()

    def db_fehler(e: Exception) -> HTTPException:
        if isinstance(e, PermissionError):
            return HTTPException(403, str(e))
        if isinstance(e, (treiber.DBFehler, ValueError, ki.KIFehler)):
            return HTTPException(400, str(e))
        return HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")

    @app.get("/api/gesundheit")
    def gesundheit():
        return {"ok": True, "version": __version__}

    @app.post("/api/anmelden")
    def anmelden(daten: Login, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        jetzt = time.time()
        with sperre:
            q = versuche[ip]
            while q and q[0] < jetzt - 300:
                q.popleft()
            if len(q) >= 8:
                raise HTTPException(429, "Zu viele Versuche – bitte 5 Minuten warten.")
            q.append(jetzt)
        if not sp.benutzer_pruefen(daten.benutzer, daten.passwort):
            raise HTTPException(401, "Benutzer oder Passwort falsch.")
        token = secrets.token_urlsafe(32)
        with sperre:
            versuche.pop(ip, None)
            sitzungen[token] = Sitzung(daten.benutzer)
        response.set_cookie(COOKIE, token, max_age=SITZUNG_DAUER, httponly=True, secure=cookie_secure,
                            samesite="strict", path="/")
        return {"benutzer": daten.benutzer}

    @app.post("/api/abmelden")
    def abmelden(request: Request, response: Response):
        with sperre:
            s = sitzungen.pop(request.cookies.get(COOKIE, ""), None)
        if s:
            s.schliessen()
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/ich")
    def ich(s: Sitzung = Depends(sitzung)):
        return {"benutzer": s.benutzer, "version": __version__, "arten": ARTEN, "typen": list(GENERISCH)}

    # Verbindungen ------------------------------------------------------------------------------------------------
    @app.get("/api/verbindungen")
    def verbindungen_liste(s: Sitzung = Depends(sitzung)):
        return [{**v, "offen": v["id"] in s.verbindungen, "treiber_fehlt": treiber.verfuegbar(v["art"])}
                for v in sp.verbindungen()]

    @app.post("/api/verbindungen")
    def verbindung_speichern(v: VerbindungIn, s: Sitzung = Depends(sitzung)):
        werte = v.model_dump(exclude={"passwort", "passwort_loeschen"})
        try:
            neu = sp.verbindung_speichern(werte, v.passwort, v.passwort_loeschen)
        except ValueError as e:
            raise HTTPException(400, str(e))
        with s.sperre:  # geänderte Daten -> beim nächsten Zugriff neu verbinden
            t = s.verbindungen.pop(neu["id"], None)
        if t:
            t.schliessen()
        return neu

    @app.delete("/api/verbindungen/{vid}")
    def verbindung_loeschen(vid: str, s: Sitzung = Depends(sitzung)):
        with s.sperre:
            t = s.verbindungen.pop(vid, None)
        if t:
            t.schliessen()
        sp.verbindung_loeschen(vid)
        return {"ok": True}

    @app.post("/api/verbindungen/test")
    def verbindung_testen(v: VerbindungIn, s: Sitzung = Depends(sitzung)):
        cfg = v.model_dump(exclude={"passwort", "passwort_loeschen"})
        pw = v.passwort
        if not pw and v.id:
            try:
                pw = sp.verbindung(v.id)[1]
            except KeyError:
                pw = None
        try:
            t = treiber.oeffne(cfg, pw)
        except Exception as e:
            return {"ok": False, "meldung": str(e)[:300]}
        try:
            return {"ok": True, "meldung": t.version()}
        finally:
            t.schliessen()

    @app.post("/api/v/{vid}/oeffnen")
    def oeffnen(vid: str, s: Sitzung = Depends(sitzung)):
        t, cfg = verbindung(s, vid)
        try:
            zahlen = t.tabellen_zahlen()
            schema, hinweis = t.bestes_schema(None, zahlen)
            if schema:
                t.setze_schema(schema)
            return {"version": t.version(), "schemas": [{"name": k, "tabellen": n} for k, n in zahlen.items()],
                    "schema": schema, "hinweis": hinweis, "schreibschutz": t.schreibschutz,
                    "produktiv": cfg.get("farbe") == PRODUKTIV_FARBE, "art": t.art}
        except Exception as e:
            raise db_fehler(e)

    @app.post("/api/v/{vid}/schliessen")
    def schliessen(vid: str, s: Sitzung = Depends(sitzung)):
        with s.sperre:
            t = s.verbindungen.pop(vid, None)
            for h in [h for h, (v, _) in s.handles.items() if v == vid]:
                s.handles.pop(h)[1].schliessen()
        if t:
            t.schliessen()
        return {"ok": True}

    @app.post("/api/v/{vid}/schema")
    def schema_setzen(vid: str, daten: dict, s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        try:
            t.setze_schema(str(daten.get("schema", "")))
        except Exception as e:
            raise db_fehler(e)
        return {"schema": t.aktuelles_schema}

    @app.get("/api/v/{vid}/objekte")
    def objekte(vid: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        try:
            return t.objekte(schema_von(t, schema))
        except Exception as e:
            raise db_fehler(e)

    @app.get("/api/v/{vid}/spalten")
    def spalten(vid: str, tabelle: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        try:
            return [{"name": c.name, "typ": c.typ, "pk": c.pk, "nullbar": c.nullbar}
                    for c in t.spalten(schema_von(t, schema), tabelle)]
        except Exception as e:
            raise db_fehler(e)

    @app.get("/api/v/{vid}/vervollstaendigung")
    def vervollstaendigung(vid: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        """Tabellen -> Spalten für die Autovervollständigung im Editor (höchstens 300 Tabellen)."""
        t, _ = verbindung(s, vid)
        sch = schema_von(t, schema)
        try:
            o = t.objekte(sch)
            erg = {}
            for n in (o.get("tabellen", []) + o.get("views", []))[:300]:
                try:
                    erg[n] = [c.name for c in t.spalten(sch, n)]
                except Exception:
                    erg[n] = []
            return erg
        except Exception as e:
            raise db_fehler(e)

    # Datenraster -------------------------------------------------------------------------------------------------
    @app.get("/api/v/{vid}/zeilen")
    def zeilen(vid: str, tabelle: str, schema: str = "", offset: int = 0, limit: int = 100, sortierung: str = "",
               richtung: str = "asc", filter: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        sch = schema_von(t, schema)
        limit = max(1, min(limit, 1000))
        try:
            sp_ = t.spalten(sch, tabelle)
            namen = {c.name for c in sp_}
            sort = ""
            if sortierung:
                if sortierung not in namen:
                    raise HTTPException(400, "Unbekannte Spalte zum Sortieren.")
                sort = f"{t.zitiere(sortierung)} {'DESC' if richtung == 'desc' else 'ASC'}"
            if filter and sqlschutz.pruefe(f"SELECT 1 WHERE {filter}").aendert:
                raise HTTPException(400, "Filter darf nichts ändern.")
            if filter and ";" in sqlschutz.ohne_literale(filter):
                raise HTTPException(400, "Filter darf nur eine Bedingung sein.")
            e = t.zeilen(sch, tabelle, offset, limit, sort, filter)
            e.schliessen()
            gesamt = t.anzahl(sch, tabelle, filter)
            return {**ergebnis_json(e), "gesamt": gesamt,
                    "spalteninfo": [{"name": c.name, "typ": c.typ, "pk": c.pk, "nullbar": c.nullbar} for c in sp_],
                    "bearbeitbar": any(c.pk for c in sp_) and not t.schreibschutz}
        except HTTPException:
            raise
        except Exception as e:
            raise db_fehler(e)

    @app.post("/api/v/{vid}/aenderungen")
    def aenderungen(vid: str, daten: AenderungenIn, s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        if t.schreibschutz:
            raise HTTPException(403, "Die Verbindung ist schreibgeschützt.")
        sch = schema_von(t, daten.schema_)
        sp_ = t.spalten(sch, daten.tabelle)
        namen = {c.name for c in sp_}
        pk = [c.name for c in sp_ if c.pk]
        if not pk:
            raise HTTPException(400, "Ohne Primärschlüssel ist die Tabelle nur lesbar.")
        ph, ziel = t.platzhalter, t.voll(sch, daten.tabelle)
        anweisungen: list[tuple[str, tuple]] = []
        for a in daten.aenderungen:
            if set(a.werte) - namen or set(a.pk) - namen:
                raise HTTPException(400, "Unbekannte Spalte.")
            if a.art in ("update", "delete") and set(a.pk) != set(pk):
                raise HTTPException(400, "Zeile ohne vollständigen Primärschlüssel.")
            wo = " AND ".join(f"{t.zitiere(k)} = {ph}" for k in pk)
            if a.art == "update" and a.werte:
                setz = ", ".join(f"{t.zitiere(k)} = {ph}" for k in a.werte)
                anweisungen.append((f"UPDATE {ziel} SET {setz} WHERE {wo}", (*a.werte.values(), *(a.pk[k] for k in pk))))
            elif a.art == "insert" and a.werte:
                anweisungen.append((t.einfuegen_sql(sch, daten.tabelle, list(a.werte)), tuple(a.werte.values())))
            elif a.art == "delete":
                anweisungen.append((f"DELETE FROM {ziel} WHERE {wo}", tuple(a.pk[k] for k in pk)))
        with t.sperre:
            try:
                t.beginnen()
                for sql, params in anweisungen:
                    e = t.abfrage(sql, params)
                    if e.betroffen == 0:
                        raise treiber.DBFehler("Eine Zeile wurde inzwischen geändert oder gelöscht – bitte neu laden.")
                t.bestaetigen()
            except Exception as e:
                try:
                    t.zuruecknehmen()
                except Exception:
                    pass
                raise db_fehler(e)
        return {"ok": True, "anzahl": len(anweisungen)}

    # SQL-Editor --------------------------------------------------------------------------------------------------
    @app.post("/api/v/{vid}/sql")
    def sql_ausfuehren(vid: str, daten: SqlIn, s: Sitzung = Depends(sitzung)):
        t, cfg = verbindung(s, vid)
        if daten.schema_:
            try:
                t.setze_schema(daten.schema_)
            except Exception as e:
                raise db_fehler(e)
        p = sqlschutz.pruefe(daten.sql)
        if p.aendert and t.schreibschutz:
            raise HTTPException(403, "Schreibschutz: Diese Verbindung erlaubt nur lesende Abfragen.")
        warnungen = list(p.warnungen)
        if p.aendert and cfg.get("farbe") == PRODUKTIV_FARBE:
            warnungen.append("Produktiv-Verbindung: Die Abfrage ändert Daten.")
        if warnungen and not daten.bestaetigt:
            return JSONResponse({"rueckfrage": warnungen}, status_code=409)
        teile = treiber.anweisungen(daten.sql) or [daten.sql]
        letzte, meldungen, start = None, [], time.perf_counter()
        for i, anw in enumerate(teile):
            try:
                e = t.abfrage(anw, limit=daten.limit)
            except Exception as ex:
                raise HTTPException(400, f"Anweisung {i + 1}: {ex}" if len(teile) > 1 else str(ex))
            if e.spalten:
                if letzte and letzte.mehr:
                    letzte.schliessen()
                letzte = e
            else:
                meldungen.append(f"{e.betroffen if e.betroffen >= 0 else '–'} Zeile(n) betroffen")
        handle = None
        if letzte and letzte.mehr:
            handle = uuid.uuid4().hex
            with s.sperre:
                s.handles[handle] = (vid, letzte)
        out = ergebnis_json(letzte, handle) if letzte else {"spalten": [], "zeilen": [], "mehr": False, "handle": None}
        out["meldungen"] = meldungen
        out["dauer"] = round(time.perf_counter() - start, 4)
        out["anweisungen"] = len(teile)
        return out

    @app.post("/api/abfrage/{handle}/weitere")
    def weitere(handle: str, daten: dict | None = None, s: Sitzung = Depends(sitzung)):
        with s.sperre:
            eintrag = s.handles.get(handle)
        if not eintrag:
            raise HTTPException(404, "Ergebnis ist abgelaufen – Abfrage neu ausführen.")
        n = max(1, min(int((daten or {}).get("anzahl", 500)), 10000))
        try:
            neu = eintrag[1].weitere(n)
        except Exception as e:
            raise db_fehler(e)
        if not eintrag[1].mehr:
            with s.sperre:
                s.handles.pop(handle, None)
        return {"zeilen": [[wert(x) for x in z] for z in neu], "mehr": eintrag[1].mehr}

    @app.post("/api/v/{vid}/abbrechen")
    def abbrechen(vid: str, s: Sitzung = Depends(sitzung)):
        t = s.verbindungen.get(vid)
        if t:
            try:
                t.abbrechen()
            except Exception:
                pass
        return {"ok": True}

    @app.post("/api/v/{vid}/explain")
    def explain(vid: str, daten: SqlIn, s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        if sqlschutz.pruefe(daten.sql).aendert:
            raise HTTPException(400, "EXPLAIN nur für lesende Abfragen.")
        try:
            return ergebnis_json(t.explain(treiber.anweisungen(daten.sql)[0] if treiber.anweisungen(daten.sql) else daten.sql))
        except Exception as e:
            raise db_fehler(e)

    # KI ----------------------------------------------------------------------------------------------------------
    @app.get("/api/einstellungen")
    def einstellungen(s: Sitzung = Depends(sitzung)):
        e = sp.einstellungen()
        anbieter = [("claude-api", "Claude (API-Schlüssel)" + ("" if e["hat_api_schluessel"] else " – Schlüssel fehlt"))]
        if ki.claude_pfad():
            anbieter.append(("claude-code", "Claude (Claude Code)"))
        anbieter += [(f"ollama:{m}", f"Lokal: {m}") for m in ki.ollama_modelle(e["ollama_url"])]
        return {**e, "anbieter": [{"id": a, "name": n} for a, n in anbieter]}

    @app.post("/api/einstellungen")
    def einstellungen_setzen(daten: dict, s: Sitzung = Depends(sitzung)):
        return sp.einstellungen_setzen(daten)

    @app.post("/api/v/{vid}/ki")
    def ki_fragen(vid: str, daten: KiIn, s: Sitzung = Depends(sitzung)):
        if daten.art not in ("sql", "erklaeren", "optimieren", "fehler"):
            raise HTTPException(400, "Unbekannte KI-Aufgabe.")
        t, _ = verbindung(s, vid)
        e = sp.einstellungen()
        try:
            kontext = ki.schema_kontext(t, schema_von(t, daten.schema_), beispielzeilen=5 if daten.beispiele else 0)
            werte = {"text": daten.text, "sql": daten.sql, "fehler": daten.fehler}
            if daten.art == "optimieren" and daten.sql and not sqlschutz.pruefe(daten.sql).aendert:
                try:
                    plan = t.explain(daten.sql)
                    werte["plan"] = "\n".join(" | ".join(str(x) for x in z) for z in plan.zeilen[:60])
                except Exception:
                    pass
            anbieter = e["ki_anbieter"]
            if anbieter.startswith("ollama:"):
                antwort = ki._ollama(anbieter.split(":", 1)[1], ki._aufgabe(daten.art, kontext, **werte), e["ollama_url"])
            else:
                antwort = ki.frage(anbieter, daten.art, kontext, e["ki_modell"], **werte)
        except Exception as ex:
            raise db_fehler(ex)
        return {"antwort": antwort, "sql": ki.sql_aus_antwort(antwort), "nur_schema": not daten.beispiele}

    # ER-Diagramm -------------------------------------------------------------------------------------------------
    def modell(t: treiber.Treiber, schema: str) -> erm.Modell:
        try:
            return erm.lade(t, schema)
        except Exception as e:
            raise db_fehler(e)

    @app.get("/api/v/{vid}/erm")
    def erm_lesen(vid: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        sch = schema_von(t, schema)
        m = modell(t, sch)
        nav = efcore.navigationen(m)
        tabellen = []
        for n, tab in m.tabellen.items():
            fk = m.fk_spalten(n)
            tabellen.append({
                "name": n, "klasse": efcore.klassenname(n), "zwischentabelle": m.zwischentabelle(n),
                "spalten": [{"name": c.name, "typ": c.typ, "pk": c.pk, "fk": c.name in fk, "nullbar": c.nullbar,
                             "cs_typ": efcore.cs_typ(c), "eigenschaft": efcore.eigenschaft(c.name)} for c in tab.spalten],
                "navigationen": [{"name": a, "typ": b, "sammlung": c} for a, b, c in nav.get(n, [])]})
        fks = []
        for f in m.fks:
            haupt, abh = efcore.multiplizitaet(m, f)
            optional = haupt == "0..1"
            kard = "n:m" if m.zwischentabelle(f.tabelle) else m.kardinalitaet(f)
            ziel_k, kind_k = efcore.klassenname(f.ziel), efcore.klassenname(f.tabelle)
            worte = (f"Eine {ziel_k} hat {'eine' if kard == '1:1' else 'viele'} {kind_k if kard == '1:1' else efcore.mehrzahl_name(kind_k, f.tabelle)}.")
            fks.append({"name": f.name, "tabelle": f.tabelle, "spalten": f.spalten, "ziel": f.ziel,
                        "ziel_spalten": f.ziel_spalten, "art": kard, "optional": optional,
                        "haupt": haupt, "abhaengig": abh, "bei_loeschen": f.bei_loeschen, "bei_aendern": f.bei_aendern,
                        "worte": worte})
        gemerkt = sp.positionen(vid, sch)
        auto = erm.auto_layout(m, breite=260, hoehe=lambda tb: 38 + 22 * len(tb.spalten))
        pos = {n: gemerkt.get(n, auto.get(n, (0, 0))) for n in m.tabellen}
        return {"schema": sch, "art": t.art, "tabellen": tabellen, "fks": fks, "positionen": pos,
                "auto": {n: list(p) for n, p in auto.items()}, "n_zu_m": m.n_zu_m(),
                "schreibschutz": t.schreibschutz, "typen": list(GENERISCH)}

    @app.post("/api/v/{vid}/erm/positionen")
    def erm_positionen(vid: str, daten: dict, s: Sitzung = Depends(sitzung)):
        sp.positionen_setzen(vid, str(daten.get("schema", "")), daten.get("positionen") or {})
        return {"ok": True}

    @app.post("/api/v/{vid}/erm/ddl")
    def erm_ddl(vid: str, d: DdlIn, s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        sch = schema_von(t, d.schema_)
        sp_ = lambda x: Spalte(x.name, x.typ, x.nullbar, x.pk)  # noqa: E731
        try:
            if d.aktion == "tabelle":
                if not d.tabelle or not d.spalten:
                    raise ValueError("Name und mindestens eine Spalte nötig.")
                anw = erm.ddl_tabelle_neu(t.art, sch, d.tabelle, [sp_(x) for x in d.spalten])
            elif d.aktion == "spalte" and d.spalte:
                anw = erm.ddl_spalte_neu(t.art, sch, d.tabelle, sp_(d.spalte))
            elif d.aktion == "spalte_aendern" and d.spalte:
                anw = erm.ddl_spalte_aendern(modell(t, sch), d.tabelle, d.alt, sp_(d.spalte))
            elif d.aktion == "fk":
                f = erm.Fremdschluessel(d.tabelle, d.fk_spalten, d.ziel, d.ziel_spalten, "", d.bei_loeschen, d.bei_aendern)
                f.name = erm.fk_name(f)
                anw = erm.ddl_fk_neu(modell(t, sch), f)
            else:
                raise ValueError("Unbekannte Aktion.")
        except HTTPException:
            raise
        except Exception as e:
            raise db_fehler(e)
        return {"anweisungen": anw, "hinweise": erm.hinweise(t.art, anw)}

    @app.post("/api/v/{vid}/erm/ausfuehren")
    def erm_ausfuehren(vid: str, d: AusfuehrenIn, s: Sitzung = Depends(sitzung)):
        t, cfg = verbindung(s, vid)
        if t.schreibschutz:
            raise HTTPException(403, "Die Verbindung ist schreibgeschützt.")
        warnungen = [w for a in d.anweisungen for w in sqlschutz.pruefe(a).warnungen]
        if cfg.get("farbe") == PRODUKTIV_FARBE:
            warnungen.append("Produktiv-Verbindung: Die Struktur wird geändert.")
        if warnungen and not d.bestaetigt:
            return JSONResponse({"rueckfrage": list(dict.fromkeys(warnungen))}, status_code=409)
        try:
            erm.ausfuehren(t, d.anweisungen)
        except Exception as e:
            raise db_fehler(e)
        return {"ok": True}

    @app.get("/api/v/{vid}/erm/vorschlaege")
    def erm_vorschlaege(vid: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        m = modell(t, schema_von(t, schema))
        out = []
        for f in erm.vorschlaege(m):
            try:
                anw = erm.ddl_fk_neu(m, f)
            except Exception:
                continue
            out.append({"tabelle": f.tabelle, "spalten": f.spalten, "ziel": f.ziel, "ziel_spalten": f.ziel_spalten,
                        "anweisungen": anw})
        return out

    @app.get("/api/v/{vid}/dbcontext")
    def dbcontext(vid: str, schema: str = "", s: Sitzung = Depends(sitzung)):
        t, _ = verbindung(s, vid)
        code = efcore.dbcontext(modell(t, schema_von(t, schema)))
        return PlainTextResponse(code, headers={"Content-Disposition": 'attachment; filename="AppDbContext.cs"'})

    # Import/Export -----------------------------------------------------------------------------------------------
    @app.get("/api/v/{vid}/export")
    def export(vid: str, format: str = "csv", tabelle: str = "", schema: str = "", sql: str = "",
               s: Sitzung = Depends(sitzung)):
        if format not in ("csv", "json", "xlsx", "sql"):
            raise HTTPException(400, "Format: csv, json, xlsx oder sql.")
        t, _ = verbindung(s, vid)
        sch = schema_von(t, schema)
        if sql:
            if sqlschutz.pruefe(sql).aendert:
                raise HTTPException(400, "Export nur für lesende Abfragen.")
            abfrage, name = sql, "abfrage"
        elif tabelle:
            abfrage, name = f"SELECT * FROM {t.voll(sch, tabelle)}", tabelle
        else:
            raise HTTPException(400, "Tabelle oder Abfrage angeben.")
        try:
            e = t.abfrage(abfrage, limit=1000)
        except Exception as ex:
            raise db_fehler(ex)

        def alle():
            yield from e.zeilen
            while e.mehr:
                yield from e.weitere(2000)

        fd, pfad = tempfile.mkstemp(suffix="." + format)
        os.close(fd)
        try:
            austausch.exportieren(pfad, e.spalten, alle(), format, tabelle=name, zitiere=t.zitiere)
        except Exception as ex:
            os.unlink(pfad)
            raise db_fehler(ex)
        finally:
            e.schliessen()
        return FileResponse(pfad, filename=f"{name}.{format}", background=BackgroundTask(os.unlink, pfad))

    @app.post("/api/v/{vid}/import")
    async def importieren(vid: str, datei: UploadFile = File(...), tabelle: str = Form(...), schema_: str = Form("", alias="schema"),
                          neu: bool = Form(False), nur_vorschau: bool = Form(False), s: Sitzung = Depends(sitzung)):
        endung = Path(datei.filename or "").suffix.lower()
        if endung not in (".csv", ".json", ".jsonl", ".xlsx"):
            raise HTTPException(400, "Erlaubt: CSV, JSON, JSON Lines, Excel.")
        fd, pfad = tempfile.mkstemp(suffix=endung)
        try:
            with os.fdopen(fd, "wb") as f:
                groesse = 0
                while chunk := await datei.read(1 << 20):
                    groesse += len(chunk)
                    if groesse > 100 << 20:
                        raise HTTPException(413, "Datei größer als 100 MB.")
                    f.write(chunk)
            t, _ = verbindung(s, vid)
            sch = schema_von(t, schema_)
            try:
                kopf, zeilen_ = austausch.lesen(pfad, max_zeilen=20 if nur_vorschau else None)
            except Exception as e:
                raise HTTPException(400, f"Datei nicht lesbar: {e}")
            if nur_vorschau:
                return {"spalten": kopf, "zeilen": [[wert(x) for x in z] for z in zeilen_[:20]]}
            if t.schreibschutz:
                raise HTTPException(403, "Die Verbindung ist schreibgeschützt.")
            if neu:
                zuordnung = {k: k for k in kopf}
            else:
                ziel = {c.name.lower(): c.name for c in t.spalten(sch, tabelle)}
                zuordnung = {k: ziel[k.lower()] for k in kopf if k.lower() in ziel}
            try:
                n = austausch.importieren(t, sch, tabelle, kopf, zeilen_, zuordnung, neu_anlegen=neu)
            except Exception as e:
                raise db_fehler(e)
            return {"ok": True, "zeilen": n, "spalten": len(zuordnung)}
        finally:
            if os.path.exists(pfad):
                os.unlink(pfad)

    # Statische Oberfläche ----------------------------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATISCH), name="static")

    @app.get("/")
    def start():
        return FileResponse(STATISCH / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.png")
    def favicon():
        return FileResponse(Path(__file__).parent.parent / "icon.png")

    return app
