"""Vorlagen-Engine für neue Datenbanken – fertige Vorlagen und KI-Entwurf in einem Modell.

Ein Modell ist dialektfrei: Tabellen mit Spalten (generische Typen), Primärschlüssel, Pflicht, Eindeutig, Standardwert und
Verweis auf eine andere Tabelle, dazu optional Beispieldaten. `ddl()` macht daraus SQL für PostgreSQL, MySQL/MariaDB,
SQLite, SQL Server oder DuckDB (Tabellen in Abhängigkeitsreihenfolge, Indizes auf Fremdschlüssel).

Die KI liefert dasselbe Modell als JSON. `pruefen()` prüft und bereinigt alles, was von außen kommt (Namen, Typen, Verweise,
Mengen) – ausgeführt wird erst, was die Person in der Vorschau gesehen hat.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

TYPEN = ("ganzzahl", "grosse_ganzzahl", "dezimal", "kommazahl", "text", "langtext", "wahrheitswert", "datum",
         "zeitstempel", "zeit", "json", "uuid")
_NATIV = {
    "postgresql": {"ganzzahl": "integer", "grosse_ganzzahl": "bigint", "dezimal": "numeric(12,2)", "kommazahl": "double precision",
                   "text": "varchar(255)", "langtext": "text", "wahrheitswert": "boolean", "datum": "date",
                   "zeitstempel": "timestamp", "zeit": "time", "json": "jsonb", "uuid": "uuid"},
    "mysql": {"ganzzahl": "INT", "grosse_ganzzahl": "BIGINT", "dezimal": "DECIMAL(12,2)", "kommazahl": "DOUBLE",
              "text": "VARCHAR(255)", "langtext": "TEXT", "wahrheitswert": "TINYINT(1)", "datum": "DATE",
              "zeitstempel": "DATETIME", "zeit": "TIME", "json": "JSON", "uuid": "CHAR(36)"},
    "sqlite": {"ganzzahl": "INTEGER", "grosse_ganzzahl": "INTEGER", "dezimal": "NUMERIC", "kommazahl": "REAL",
               "text": "TEXT", "langtext": "TEXT", "wahrheitswert": "INTEGER", "datum": "TEXT", "zeitstempel": "TEXT",
               "zeit": "TEXT", "json": "TEXT", "uuid": "TEXT"},
    "mssql": {"ganzzahl": "INT", "grosse_ganzzahl": "BIGINT", "dezimal": "DECIMAL(12,2)", "kommazahl": "FLOAT",
              "text": "NVARCHAR(255)", "langtext": "NVARCHAR(MAX)", "wahrheitswert": "BIT", "datum": "DATE",
              "zeitstempel": "DATETIME2", "zeit": "TIME", "json": "NVARCHAR(MAX)", "uuid": "UNIQUEIDENTIFIER"},
    "duckdb": {"ganzzahl": "INTEGER", "grosse_ganzzahl": "BIGINT", "dezimal": "DECIMAL(12,2)", "kommazahl": "DOUBLE",
               "text": "VARCHAR", "langtext": "VARCHAR", "wahrheitswert": "BOOLEAN", "datum": "DATE",
               "zeitstempel": "TIMESTAMP", "zeit": "TIME", "json": "JSON", "uuid": "UUID"},
}
_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MAX_TABELLEN, MAX_SPALTEN, MAX_ZEILEN = 60, 60, 50


class VorlagenFehler(Exception):
    pass


@dataclass
class Modell:
    name: str
    beschreibung: str = ""
    tabellen: list[dict] = field(default_factory=list)  # {name, beschreibung, spalten: [{name, typ, pk, auto, pflicht, eindeutig, standard, verweis, kaskade}]}
    daten: dict = field(default_factory=dict)           # {tabelle: [{spalte: wert}]}

    def als_json(self) -> dict:
        return {"name": self.name, "beschreibung": self.beschreibung, "tabellen": self.tabellen, "daten": self.daten}


# --- Kurzschreibweise für die eingebauten Vorlagen ------------------------------------------------------------------
# „name text!“ Pflicht · „email text! u“ eindeutig · „kunde_id ->kunden“ Verweis (ganzzahl) · „->>“ mit Löschen kaskadierend
# · „angelegt zeitstempel=jetzt“ Standardwert. Jede Tabelle bekommt automatisch „id“ als Schlüssel.
def _t(name: str, beschreibung: str, *spalten: str) -> dict:
    out = [{"name": "id", "typ": "ganzzahl", "pk": True, "auto": True, "pflicht": True}]
    for s in spalten:
        m = re.fullmatch(r"(\w+)\s*(\w+)?(!)?(\s+u)?\s*(?:(->>?)(\w+))?\s*(?:=(\S+))?", s.strip())
        if not m:
            raise ValueError(s)
        n, typ, pflicht, eindeutig, pfeil, ziel, standard = m.groups()
        sp = {"name": n, "typ": typ or ("ganzzahl" if ziel else "text"), "pk": False, "auto": False, "pflicht": bool(pflicht),
              "eindeutig": bool(eindeutig)}
        if ziel:
            sp["verweis"], sp["kaskade"] = ziel, pfeil == "->>"
        if standard:
            sp["standard"] = standard
        out.append(sp)
    return {"name": name, "beschreibung": beschreibung, "spalten": out}


VORLAGEN: dict[str, Modell] = {
    "shop": Modell("Online-Shop", "Kunden, Produkte mit Kategorien, Bestellungen mit Positionen, Zahlungen, Gutscheine", [
        _t("kunden", "Kundenkonten", "email text! u", "vorname text!", "nachname text!", "telefon text", "angelegt zeitstempel=jetzt"),
        _t("adressen", "Liefer- und Rechnungsadressen", "kunde_id ->>kunden", "art text!", "strasse text!", "plz text!", "ort text!", "land text!=DE"),
        _t("kategorien", "Produktkategorien (verschachtelt)", "name text!", "eltern_id ->kategorien"),
        _t("produkte", "Artikel", "sku text! u", "name text!", "beschreibung langtext", "preis dezimal!", "mwst_satz dezimal!=19",
           "bestand ganzzahl!=0", "aktiv wahrheitswert!=wahr", "kategorie_id ->kategorien"),
        _t("gutscheine", "Rabattcodes", "code text! u", "rabatt_prozent dezimal", "rabatt_betrag dezimal", "gueltig_bis datum", "aktiv wahrheitswert!=wahr"),
        _t("bestellungen", "Bestellkopf", "kunde_id ->kunden", "status text!=offen", "bestellt zeitstempel!=jetzt",
           "lieferadresse_id ->adressen", "gutschein_id ->gutscheine", "summe dezimal!=0"),
        _t("bestellpositionen", "Bestellte Artikel", "bestellung_id ->>bestellungen", "produkt_id ->produkte", "menge ganzzahl!=1", "einzelpreis dezimal!"),
        _t("zahlungen", "Zahlungseingänge", "bestellung_id ->bestellungen", "betrag dezimal!", "methode text!", "bezahlt zeitstempel", "referenz text"),
    ], {"kategorien": [{"id": 1, "name": "Bücher"}, {"id": 2, "name": "Elektronik"}],
        "produkte": [{"id": 1, "sku": "B-001", "name": "Datenbanken für Einsteiger", "preis": 29.9, "mwst_satz": 7, "bestand": 12, "kategorie_id": 1},
                     {"id": 2, "sku": "E-001", "name": "USB-Stick 64 GB", "preis": 12.5, "mwst_satz": 19, "bestand": 40, "kategorie_id": 2}],
        "kunden": [{"id": 1, "email": "anna@example.org", "vorname": "Anna", "nachname": "Beispiel"}]}),
    "crm": Modell("CRM", "Firmen, Kontakte, Verkaufschancen, Aktivitäten und Notizen", [
        _t("benutzer", "Vertriebsmitarbeiter", "email text! u", "name text!"),
        _t("firmen", "Organisationen", "name text!", "branche text", "website text", "ort text", "verantwortlich_id ->benutzer"),
        _t("kontakte", "Ansprechpartner", "firma_id ->firmen", "vorname text!", "nachname text!", "email text", "telefon text", "position text"),
        _t("chancen", "Verkaufschancen (Pipeline)", "firma_id ->firmen", "titel text!", "phase text!=neu", "wert dezimal",
           "wahrscheinlichkeit ganzzahl", "abschluss_geplant datum", "verantwortlich_id ->benutzer"),
        _t("aktivitaeten", "Anrufe, Termine, Mails", "kontakt_id ->kontakte", "chance_id ->chancen", "art text!", "betreff text!",
           "faellig zeitstempel", "erledigt wahrheitswert!=falsch", "benutzer_id ->benutzer"),
        _t("notizen", "Freie Notizen", "firma_id ->>firmen", "text langtext!", "angelegt zeitstempel!=jetzt", "benutzer_id ->benutzer"),
    ]),
    "cms": Modell("Blog / CMS", "Seiten und Beiträge mit Autoren, Kategorien, Schlagwörtern, Kommentaren und Medien", [
        _t("autoren", "Redaktion", "email text! u", "name text!", "bio langtext"),
        _t("kategorien", "Rubriken", "name text!", "slug text! u"),
        _t("beitraege", "Artikel und Seiten", "titel text!", "slug text! u", "inhalt langtext", "status text!=entwurf",
           "veroeffentlicht zeitstempel", "autor_id ->autoren", "kategorie_id ->kategorien"),
        _t("schlagwoerter", "Tags", "name text! u"),
        _t("beitrag_schlagwoerter", "Zuordnung Beitrag ↔ Tag", "beitrag_id ->>beitraege", "schlagwort_id ->>schlagwoerter"),
        _t("kommentare", "Leserkommentare", "beitrag_id ->>beitraege", "name text!", "email text", "text langtext!",
           "freigegeben wahrheitswert!=falsch", "angelegt zeitstempel!=jetzt"),
        _t("medien", "Bilder und Dateien", "dateiname text!", "titel text", "mime text", "groesse ganzzahl", "hochgeladen zeitstempel!=jetzt"),
    ]),
    "lager": Modell("Lager & Warenwirtschaft", "Artikel, Lagerorte, Bestände, Bewegungen, Lieferanten und Bestellungen", [
        _t("lieferanten", "Bezugsquellen", "name text!", "email text", "telefon text"),
        _t("artikel", "Stammdaten", "artikelnummer text! u", "bezeichnung text!", "einheit text!=Stk", "mindestbestand ganzzahl!=0",
           "einkaufspreis dezimal", "lieferant_id ->lieferanten"),
        _t("lagerorte", "Regale und Plätze", "bezeichnung text! u"),
        _t("bestaende", "Bestand je Lagerort", "artikel_id ->>artikel", "lagerort_id ->lagerorte", "menge dezimal!=0"),
        _t("bewegungen", "Zu- und Abgänge", "artikel_id ->artikel", "lagerort_id ->lagerorte", "menge dezimal!", "art text!",
           "zeitpunkt zeitstempel!=jetzt", "beleg text"),
        _t("einkauf", "Bestellungen beim Lieferanten", "lieferant_id ->lieferanten", "bestellt datum!", "status text!=offen"),
        _t("einkaufspositionen", "Bestellte Artikel", "einkauf_id ->>einkauf", "artikel_id ->artikel", "menge dezimal!", "preis dezimal"),
    ]),
    "tickets": Modell("Ticketsystem", "Kunden, Tickets mit Status und Priorität, Antworten, Agenten und SLAs", [
        _t("agenten", "Support-Team", "email text! u", "name text!"),
        _t("kunden", "Anfragende", "email text! u", "name text!", "firma text"),
        _t("tickets", "Anfragen", "kunde_id ->kunden", "betreff text!", "status text!=neu", "prioritaet text!=normal",
           "zugewiesen_id ->agenten", "eroeffnet zeitstempel!=jetzt", "geschlossen zeitstempel"),
        _t("antworten", "Verlauf", "ticket_id ->>tickets", "agent_id ->agenten", "text langtext!", "intern wahrheitswert!=falsch",
           "angelegt zeitstempel!=jetzt"),
        _t("slas", "Reaktionszeiten je Priorität", "prioritaet text! u", "reaktion_stunden ganzzahl!", "loesung_stunden ganzzahl!"),
    ], {"slas": [{"id": 1, "prioritaet": "hoch", "reaktion_stunden": 2, "loesung_stunden": 8},
                 {"id": 2, "prioritaet": "normal", "reaktion_stunden": 8, "loesung_stunden": 48}]}),
    "verein": Modell("Vereinsverwaltung", "Mitglieder, Beiträge, Abteilungen, Termine und Anwesenheit", [
        _t("abteilungen", "Sparten", "name text! u"),
        _t("mitglieder", "Mitgliederliste", "mitgliedsnummer text! u", "vorname text!", "nachname text!", "geburtsdatum datum",
           "email text", "eintritt datum!", "austritt datum", "abteilung_id ->abteilungen"),
        _t("beitraege", "Beitragsarten", "bezeichnung text!", "betrag dezimal!", "intervall text!=jaehrlich"),
        _t("zahlungen", "Beitragszahlungen", "mitglied_id ->>mitglieder", "beitrag_id ->beitraege", "betrag dezimal!", "datum datum!"),
        _t("termine", "Training, Versammlung, Feste", "titel text!", "beginn zeitstempel!", "ort text", "abteilung_id ->abteilungen"),
        _t("anwesenheit", "Wer war da", "termin_id ->>termine", "mitglied_id ->>mitglieder", "anwesend wahrheitswert!=wahr"),
    ]),
    "personal": Modell("Personal & Zeiterfassung", "Mitarbeiter, Abteilungen, Arbeitszeiten, Urlaub und Krankmeldungen", [
        _t("abteilungen", "Organisation", "name text! u", "leitung_id ->mitarbeiter"),
        _t("mitarbeiter", "Personalstamm", "personalnummer text! u", "vorname text!", "nachname text!", "email text u",
           "eintritt datum!", "wochenstunden dezimal!=40", "urlaubstage ganzzahl!=30", "abteilung_id ->abteilungen"),
        _t("arbeitszeiten", "Kommen und Gehen", "mitarbeiter_id ->>mitarbeiter", "beginn zeitstempel!", "ende zeitstempel", "pause_minuten ganzzahl!=0"),
        _t("abwesenheiten", "Urlaub, Krankheit, Fortbildung", "mitarbeiter_id ->>mitarbeiter", "art text!", "von datum!", "bis datum!",
           "genehmigt wahrheitswert!=falsch"),
    ]),
    "projekte": Modell("Projekte & Aufgaben", "Projekte, Aufgaben mit Status, Zuständigen, Zeitbuchungen und Kommentaren", [
        _t("personen", "Team", "email text! u", "name text!"),
        _t("projekte", "Projekte", "name text!", "kunde text", "start datum", "ende datum", "status text!=aktiv"),
        _t("aufgaben", "To-dos", "projekt_id ->>projekte", "titel text!", "beschreibung langtext", "status text!=offen",
           "prioritaet ganzzahl!=2", "faellig datum", "zustaendig_id ->personen", "eltern_id ->aufgaben"),
        _t("zeitbuchungen", "Erfasste Zeit", "aufgabe_id ->>aufgaben", "person_id ->personen", "datum datum!", "stunden dezimal!", "notiz text"),
        _t("kommentare", "Diskussion", "aufgabe_id ->>aufgaben", "person_id ->personen", "text langtext!", "angelegt zeitstempel!=jetzt"),
    ]),
}


def vorlage(schluessel: str) -> Modell:
    return copy.deepcopy(VORLAGEN[schluessel])


# --- Prüfen (für KI und Hand) ---------------------------------------------------------------------------------------
def _sauber(name) -> str:
    n = re.sub(r"[^a-z0-9_]", "_", str(name or "").strip().lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    n = re.sub(r"_+", "_", n).strip("_")
    if n and n[0].isdigit():
        n = "t_" + n
    return n[:63]


def pruefen(roh: dict) -> tuple[Modell, list[str]]:
    """Bereinigt ein Modell von außen und sagt, was geändert wurde. Wirft VorlagenFehler, wenn nichts Brauchbares übrig bleibt."""
    hinweise: list[str] = []
    if not isinstance(roh, dict) or not isinstance(roh.get("tabellen"), list):
        raise VorlagenFehler("Kein Datenmodell erkannt (erwartet: tabellen als Liste).")
    tabellen, namen = [], set()
    for t in roh["tabellen"][:MAX_TABELLEN]:
        if not isinstance(t, dict):
            continue
        tn = _sauber(t.get("name"))
        if not tn or tn in namen:
            hinweise.append(f"Tabelle „{t.get('name')}“ übersprungen (Name leer oder doppelt).")
            continue
        if tn != t.get("name"):
            hinweise.append(f"Tabelle „{t.get('name')}“ heißt jetzt {tn}.")
        spalten, sn = [], set()
        for s in (t.get("spalten") or [])[:MAX_SPALTEN]:
            if not isinstance(s, dict):
                continue
            n = _sauber(s.get("name"))
            if not n or n in sn:
                continue
            typ = str(s.get("typ") or "text").lower()
            if typ not in TYPEN:
                hinweise.append(f"{tn}.{n}: Typ „{typ}“ unbekannt → text.")
                typ = "text"
            sp = {"name": n, "typ": typ, "pk": bool(s.get("pk")), "auto": bool(s.get("auto")), "pflicht": bool(s.get("pflicht") or s.get("pk")),
                  "eindeutig": bool(s.get("eindeutig"))}
            if s.get("verweis"):
                sp["verweis"], sp["kaskade"] = _sauber(str(s["verweis"]).split(".")[0]), bool(s.get("kaskade"))
            if s.get("standard") not in (None, ""):
                sp["standard"] = str(s["standard"])[:100]
            spalten.append(sp)
            sn.add(n)
        if not any(s["pk"] for s in spalten):
            if "id" in sn:
                next(s for s in spalten if s["name"] == "id").update(pk=True, pflicht=True)
            else:
                spalten.insert(0, {"name": "id", "typ": "ganzzahl", "pk": True, "auto": True, "pflicht": True, "eindeutig": False})
                hinweise.append(f"{tn}: Primärschlüssel id ergänzt.")
        pks = [s for s in spalten if s["pk"]]
        for s in pks:
            if s["auto"] and (len(pks) > 1 or s["typ"] not in ("ganzzahl", "grosse_ganzzahl")):
                s["auto"] = False
        tabellen.append({"name": tn, "beschreibung": str(t.get("beschreibung") or "")[:200], "spalten": spalten})
        namen.add(tn)
    if not tabellen:
        raise VorlagenFehler("Das Modell enthält keine brauchbare Tabelle.")
    for t in tabellen:
        for s in t["spalten"]:
            if "verweis" in s and s["verweis"] not in namen:
                hinweise.append(f"{t['name']}.{s['name']}: Verweis auf unbekannte Tabelle „{s['verweis']}“ entfernt.")
                s.pop("verweis"), s.pop("kaskade", None)
            elif "verweis" in s:
                ziel = next(x for x in tabellen if x["name"] == s["verweis"])
                zpk = [p for p in ziel["spalten"] if p["pk"]]
                if len(zpk) != 1:
                    hinweise.append(f"{t['name']}.{s['name']}: Ziel {s['verweis']} hat keinen einfachen Schlüssel – Verweis entfernt.")
                    s.pop("verweis"), s.pop("kaskade", None)
                else:
                    s["typ"] = zpk[0]["typ"]
    daten = {}
    for tn, zeilen in (roh.get("daten") or {}).items() if isinstance(roh.get("daten"), dict) else []:
        tn = _sauber(tn)
        t = next((x for x in tabellen if x["name"] == tn), None)
        if not t or not isinstance(zeilen, list):
            continue
        erlaubt = {s["name"] for s in t["spalten"]}
        daten[tn] = [{_sauber(k): v for k, v in z.items() if _sauber(k) in erlaubt and isinstance(v, (str, int, float, bool, type(None)))}
                     for z in zeilen[:MAX_ZEILEN] if isinstance(z, dict)]
    name = str(roh.get("name") or "Neue Datenbank")[:80]
    return Modell(name, str(roh.get("beschreibung") or "")[:300], tabellen, daten), hinweise


# --- SQL erzeugen ---------------------------------------------------------------------------------------------------
def _reihenfolge(m: Modell) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Tabellen so sortiert, dass Verweisziele vorher entstehen. Verweise in Zyklen (oder auf sich selbst) kommen als
    nachträgliche Fremdschlüssel zurück."""
    rest, fertig, spaeter = list(m.tabellen), [], []
    while rest:
        for t in rest:
            offen = {s["verweis"] for s in t["spalten"] if s.get("verweis") and s["verweis"] != t["name"]} - {x["name"] for x in fertig}
            if not offen:
                break
        else:  # Zyklus: die erste Tabelle nehmen, ihre offenen Verweise später anlegen
            t = rest[0]
        erledigt = {x["name"] for x in fertig} | {t["name"]}
        for s in t["spalten"]:
            if s.get("verweis") and (s["verweis"] not in erledigt or s["verweis"] == t["name"]):
                spaeter.append((t, s))
        fertig.append(t)
        rest.remove(t)
    return fertig, spaeter


def _standard(art: str, s: dict) -> str:
    w = str(s["standard"])
    if w.lower() in ("jetzt", "now", "current_timestamp"):
        return " DEFAULT CURRENT_TIMESTAMP" if s["typ"] in ("zeitstempel", "datum") or art != "sqlite" else " DEFAULT CURRENT_TIMESTAMP"
    if s["typ"] == "wahrheitswert":
        an = w.lower() in ("wahr", "true", "1", "ja")
        return f" DEFAULT {('TRUE' if an else 'FALSE') if art in ('postgresql', 'duckdb') else (1 if an else 0)}"
    if s["typ"] in ("ganzzahl", "grosse_ganzzahl", "dezimal", "kommazahl") and re.fullmatch(r"-?\d+(\.\d+)?", w):
        return f" DEFAULT {w}"
    return " DEFAULT '" + w.replace("'", "''") + "'"


def _q(art: str, n: str) -> str:
    if art == "mysql":
        return f"`{n}`"
    if art == "mssql":
        return f"[{n}]"
    return f'"{n}"'


def ddl(m: Modell, art: str, mit_daten: bool = True) -> list[str]:
    if art not in _NATIV:
        raise VorlagenFehler(f"Für {art} gibt es keine Vorlagen.")
    nativ, q = _NATIV[art], (lambda n: _q(art, n))
    tabellen, spaeter = _reihenfolge(m)
    spaet_ids = {(t["name"], s["name"]) for t, s in spaeter}
    out = []
    for t in tabellen:
        teile, pks = [], [s for s in t["spalten"] if s["pk"]]
        for s in t["spalten"]:
            typ = nativ[s["typ"]]
            if s.get("auto") and len(pks) == 1 and s["pk"]:
                teile.append({"postgresql": f"{q(s['name'])} {typ} GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                              "mysql": f"{q(s['name'])} {typ} AUTO_INCREMENT PRIMARY KEY",
                              "sqlite": f"{q(s['name'])} INTEGER PRIMARY KEY AUTOINCREMENT",
                              "mssql": f"{q(s['name'])} {typ} IDENTITY(1,1) PRIMARY KEY",
                              "duckdb": f"{q(s['name'])} {typ} PRIMARY KEY DEFAULT nextval('seq_{t['name']}')"}[art])
                continue
            z = f"{q(s['name'])} {typ}" + (" NOT NULL" if s.get("pflicht") else "")
            if "standard" in s:
                z += _standard(art, s)
            if s.get("eindeutig") and not s["pk"]:
                z += " UNIQUE"
            teile.append(z)
        if not any(s.get("auto") for s in pks) or len(pks) > 1:
            teile.append(f"PRIMARY KEY ({', '.join(q(s['name']) for s in pks)})")
        for s in t["spalten"]:
            if s.get("verweis") and (t["name"], s["name"]) not in spaet_ids:
                teile.append(_fk(art, t, s, q))
        if art == "duckdb" and any(s.get("auto") for s in pks):
            out.append(f"CREATE SEQUENCE IF NOT EXISTS seq_{t['name']} START 1")
        out.append(f"CREATE TABLE {q(t['name'])} (\n  " + ",\n  ".join(teile) + "\n)" + (" ENGINE=InnoDB" if art == "mysql" else ""))
    for t, s in spaeter:
        if art in ("sqlite", "duckdb"):
            continue  # nachträgliche Fremdschlüssel kann SQLite/DuckDB nicht; der Verweis bleibt als Spalte
        out.append(f"ALTER TABLE {q(t['name'])} ADD {_fk(art, t, s, q)}")
    for t in tabellen:  # Indizes auf Fremdschlüssel (PostgreSQL legt sie nicht selbst an)
        for s in t["spalten"]:
            if s.get("verweis") and art in ("postgresql", "sqlite", "duckdb", "mssql"):
                out.append(f"CREATE INDEX {q('ix_' + t['name'] + '_' + s['name'])[:70]} ON {q(t['name'])} ({q(s['name'])})")
    if mit_daten:
        out += daten_sql(m, art)
    return out


def _fk(art, t, s, q) -> str:
    ziel = s["verweis"]
    return (f"CONSTRAINT {q('fk_' + t['name'] + '_' + s['name'])} FOREIGN KEY ({q(s['name'])}) REFERENCES {q(ziel)} ({q('id')})"
            + (" ON DELETE CASCADE" if s.get("kaskade") and art != "duckdb" else ""))  # DuckDB kennt kein CASCADE


def _literal(art: str, wert, typ: str) -> str:
    if wert is None:
        return "NULL"
    if isinstance(wert, bool) or typ == "wahrheitswert":
        an = wert if isinstance(wert, bool) else str(wert).lower() in ("true", "wahr", "1", "ja")
        return ("TRUE" if an else "FALSE") if art in ("postgresql", "duckdb") else ("1" if an else "0")
    if isinstance(wert, (int, float)) and typ not in ("text", "langtext", "datum", "zeitstempel", "zeit", "uuid", "json"):
        return repr(wert)
    if isinstance(wert, (date, datetime)):
        wert = wert.isoformat(" ")
    return "'" + str(wert).replace("'", "''") + "'"


def daten_sql(m: Modell, art: str) -> list[str]:
    q = lambda n: _q(art, n)  # noqa: E731
    tabellen, _ = _reihenfolge(m)
    out = []
    for t in tabellen:
        zeilen = m.daten.get(t["name"]) or []
        typen = {s["name"]: s["typ"] for s in t["spalten"]}
        mit_id = False
        for z in zeilen:
            spalten = [k for k in z if k in typen]
            if not spalten:
                continue
            mit_id = mit_id or "id" in spalten
            out.append(f"INSERT INTO {q(t['name'])} ({', '.join(q(s) for s in spalten)}) VALUES "
                       f"({', '.join(_literal(art, z[s], typen[s]) for s in spalten)})")
        if mit_id and art == "postgresql":  # Identity hinter die eingefügten ids setzen
            out.append(f"SELECT setval(pg_get_serial_sequence('{t['name']}', 'id'), (SELECT max(id) FROM {q(t['name'])}))")
        if mit_id and art == "mssql":
            out[-len(zeilen):] = [f"SET IDENTITY_INSERT {q(t['name'])} ON"] + out[-len(zeilen):] + [f"SET IDENTITY_INSERT {q(t['name'])} OFF"]
    return out


def einspielen(t, anweisungen: list[str]) -> int:
    """Alle Anweisungen in einer Transaktion (PostgreSQL/SQLite/DuckDB/SQL Server); MySQL kennt keine transaktionale DDL."""
    if getattr(t, "schreibschutz", False):
        raise VorlagenFehler("Die Verbindung ist schreibgeschützt.")
    t.beginnen()
    try:
        for a in anweisungen:
            t.abfrage(a)
        t.bestaetigen()
    except Exception:
        t.zuruecknehmen()
        raise
    return len(anweisungen)


def uebersicht(m: Modell) -> str:
    """Lesbare Kurzfassung für die Vorschau."""
    zeilen = []
    for t in m.tabellen:
        sp = []
        for s in t["spalten"]:
            x = s["name"] + (" 🔑" if s["pk"] else "") + (f" → {s['verweis']}" if s.get("verweis") else "") + ("*" if s.get("pflicht") and not s["pk"] else "")
            sp.append(x)
        n = len(m.daten.get(t["name"], []))
        zeilen.append(f"▸ {t['name']}" + (f"  – {t['beschreibung']}" if t.get("beschreibung") else "") + (f"  ({n} Beispielzeilen)" if n else ""))
        zeilen.append("    " + ", ".join(sp))
    return "\n".join(zeilen)


# --- KI ------------------------------------------------------------------------------------------------------------
def ki_aufgabe(beschreibung: str, basis: Modell | None, art: str, beispieldaten: bool) -> str:
    schema = {"name": "Titel", "beschreibung": "ein Satz", "tabellen": [{"name": "snake_case", "beschreibung": "kurz", "spalten": [
        {"name": "id", "typ": "ganzzahl", "pk": True, "auto": True, "pflicht": True},
        {"name": "kunde_id", "typ": "ganzzahl", "pflicht": True, "verweis": "kunden", "kaskade": False},
        {"name": "email", "typ": "text", "pflicht": True, "eindeutig": True},
        {"name": "angelegt", "typ": "zeitstempel", "standard": "jetzt"}]}],
        "daten": {"kunden": [{"id": 1, "email": "anna@example.org"}]}}
    teile = [
        f"Entwirf ein relationales Datenmodell für eine neue {art}-Datenbank.",
        f"Anforderung in eigenen Worten: {beschreibung.strip() or '(keine weitere Angabe)'}",
        "Regeln: Tabellen- und Spaltennamen deutsch oder englisch, klein, snake_case, Tabellennamen im Plural. "
        "Jede Tabelle hat id (ganzzahl, pk, auto). Beziehungen über <tabelle_singular>_id mit \"verweis\" auf die Zieltabelle; "
        "n:m über eine Zwischentabelle. \"kaskade\": true nur, wenn die Zeilen ohne den Eltern-Datensatz sinnlos sind "
        "(z. B. Bestellpositionen). Keine Passwörter im Klartext speichern (passwort_hash). Normalisiert, aber praxisnah.",
        f"Erlaubte Typen: {', '.join(TYPEN)} (text = kurz bis 255 Zeichen, langtext = beliebig lang).",
        "Standardwerte: \"jetzt\" für Zeitstempel, wahr/falsch für Wahrheitswerte, Zahlen oder kurze Texte.",
    ]
    if beispieldaten:
        teile.append(f"Lege unter \"daten\" je Tabelle 3 bis 8 realistische, erfundene Beispielzeilen an (mit expliziter id, "
                     f"Verweise passend, keine echten Personen, Mailadressen nur @example.org), höchstens {MAX_ZEILEN} je Tabelle.")
    else:
        teile.append("\"daten\" bleibt leer.")
    if basis:
        teile.append("Ausgangspunkt ist diese Vorlage – passe sie an die Anforderung an, behalte, was passt:\n"
                     + json.dumps(basis.als_json(), ensure_ascii=False))
    teile.append("Antworte NUR mit einem ```json```-Block in genau dieser Form:\n" + json.dumps(schema, ensure_ascii=False, indent=1))
    return "\n\n".join(teile)


def aus_ki_antwort(text: str) -> tuple[Modell, list[str]]:
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, flags=re.S | re.I)
    roh = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        daten = json.loads(roh)
    except ValueError as e:
        raise VorlagenFehler(f"Die KI-Antwort war kein gültiges JSON ({e.msg}). Bitte noch einmal versuchen.") from e
    return pruefen(daten)
