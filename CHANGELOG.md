# Changelog

## 0.4.4 – 2026-11-25

- **Start mit Verbindung:** `python -m dbstudio --verbindung '{"art": "sqlite", "datei": "…"}' [--tabelle Orders]` –
  vorhandene Verbindung mit gleichem Ziel wird wiederverwendet, sonst angelegt; fehlt bei Servern das Passwort, öffnet
  sich der Verbindungsdialog. Passwörter werden über die Kommandozeile abgelehnt. Genutzt von Visual Death Studio
  („🛠 In DB Studio bearbeiten“).

## 0.4.3 – 2026-11-24

- **Access-Import (.mdb, .accdb)** ohne Access und ohne Windows (Paket `access-parser`): echte Spaltentypen und
  Primärschlüssel (auch zusammengesetzte), Währungsfelder korrekt umgerechnet, kaputte Datumswerte werden NULL,
  beschädigte Tabellen erkannt und übersprungen. Beziehungen über die Namen (jetzt auch Plural „-ies“), als
  Fremdschlüssel nur, wenn keine Verweise ins Leere zeigen. Web: „Import & Export“, mit Vorschau.
- **Demo „Northwind“** (Desktop und Web: „🧪 Demo: Northwind“): Microsofts klassische Beispieldatenbank aus der
  Access-Fassung – 8 Tabellen, 3.202 Zeilen, 6 Fremdschlüssel und 9 bekannte Abfragen als Views (Invoices,
  Category Sales, Order Subtotals …).

## 0.4.2 – 2026-11-24

- **Löschen mit Folgen-Analyse** (Desktop: Menü „…“, Web: „🗑 Löschen …“): Tabelle, Spalte oder Fremdschlüssel.
  Vorher zählt die Vorschau, wer danach ohne Bezugspunkt wäre – auch über Beziehungen ohne Constraint – und wie viele
  Zeilen bzw. Werte verloren gehen. SQLite/DuckDB per Neuaufbau, MySQL mit DROP FOREIGN KEY, sonst DROP CONSTRAINT.
- **Datenbank-Dump importieren (.sql)** unter „Import & Export“: macht Struktur-Exporte wie das Supabase-Schema
  lauffähig (fehlende Sequenzen, `ARRAY` ohne Typ, `uuid_generate_v4` → `gen_random_uuid`, Fremdschlüssel am Ende,
  Verweise auf `auth.users` als Ersatztabelle oder weggelassen, Kommentare) und spielt alles in einer Transaktion ein.

## 0.4.1 – 2026-11-24

- **Folgen-Analyse im ER-Designer** (Desktop und Web): Beim Anlegen einer Beziehung oder beim Ändern einer Spalte
  zählt Pi DB Studio im Bestand, welche Datensätze ihren Bezugspunkt verlieren oder schon verloren haben – mit
  Beispielwerten. Berücksichtigt auch Beziehungen ohne Constraint, die nur über den Namen bestehen (`kunde_id` → `kunden`).
  Warnt u. a. bei verwaisten Verweisen vor einem neuen Fremdschlüssel, beim Umbenennen oder Typwechsel eines
  Primärschlüssels, auf den andere verweisen, und bei NOT NULL auf Spalten mit leeren Werten.

## 0.4.0 – 2026-11-24

- **Generische REST-API** (Web) unter `/rest/v1/{verbindung}/{tabelle}` für alle Verbindungsarten: Lesen mit Filtern
  (`spalte=eq|neq|gt|gte|lt|lte|like.wert`, `is.null`), `select`, `order`, `limit`/`offset`; Einzelzugriff, Ändern und
  Löschen über den Primärschlüssel, Anlegen per POST. Nur gebundene Parameter, Namen gegen das echte Schema geprüft.
- **Berechtigungen:** API-Schlüssel (nur als SHA-256-Hash gespeichert, einmal angezeigt) mit Regeln je Verbindung und
  Tabelle, Rollen Leser/Schreiber/Admin, gesperrte Spalten, Zeilenfilter (beim Anlegen erzwungen), Rate-Limit je Schlüssel,
  Schreibschutz der Verbindung gilt auch hier. Änderungen und Ablehnungen im Protokoll.
- **OpenAPI** je Schlüssel unter `/rest/v1/openapi.json`, nur mit den erlaubten Tabellen und Aktionen.
- **Seite „API & Rechte“:** Schlüssel anlegen, sperren, löschen; Benutzung mit Beispielen; Protokoll.

## Davor

- **KI-Brücke:** optionale Felder `system` (eigener Systemprompt) und `json_schema` (strukturierte Ausgabe) für den
  Job Agent Web (CT 106). Ohne diese Felder verhält sich die Brücke wie bisher. Erlaubte Adressen per Drop-in
  `~/.config/systemd/user/claude-bruecke.service.d/jobagent.conf` (192.168.178.215, 192.168.178.217).

## 0.3.3 – 2026-11-23

- **ER-Diagramm (Desktop und Web):** Zoomleiste per Griff links (⋮⋮) frei verschiebbar, bleibt im Sichtbereich,
  Position wird gemerkt (Desktop: Einstellungen, Web: im Browser) und wandert beim Größerziehen mit;
  Doppelklick auf den Griff setzt sie nach unten rechts zurück. Die Minikarte bleibt an ihrem Platz.

## 0.3.2 – 2026-11-23

- **KI-Anbieter „Claude (Claude Code auf dem PC)“ für die Web-Version:** KI-Brücke `python -m dbstudio.claude_bruecke`
  als User-Dienst auf dem PC (192.168.178.86:8791, `deploy/claude-bruecke.service`). Nimmt nur Anfragen von CT 104
  (192.168.178.215) mit Token an (PC: Schlüsselbund `db-studio`/`claude-bruecke`, CT 104: `/etc/dbstudio-web.env`),
  ruft `claude -p` ohne Werkzeuge auf, eine Anfrage zur Zeit, Zeitlimit 180 s. Kein API-Schlüssel nötig.
- Desktop nutzt wie bisher direkt `claude -p` („Claude (Claude Code, Abo)“).
- Web: Ollama-Adresse auf den PC gestellt (http://192.168.178.86:11434).

## 0.3.1 – 2026-11-23

- **MySQL/MariaDB und SQL Server** jetzt mit Server-Tests (Treiber-, Diagramm- und Austauschtests gegen CT 105);
  Test-DB wird vor/nach jedem Test geleert, Passwörter nur aus Umgebung oder Schlüsselbund.
- **Abbrechen repariert:** SQL Server bricht jetzt wirklich ab (dbcancel an der _mssql-Verbindung statt des fehlenden
  `cancel()`), MySQL/MariaDB baut die KILL-QUERY-Verbindung mit derselben TLS-Einstellung auf und meldet
  „Abfrage abgebrochen“, auch wenn der Server die Anweisung still beendet.

## 0.3.0 – 2026-11-23

- **Web-Oberfläche** (`python -m dbstudio.web`, Paket `dbstudio/web/`): FastAPI + statisches Frontend ohne Build,
  im Päffgen-IT-Look (dunkel/hell, Orange/Blau, Tux-Favicon). Nutzt den Kern der Desktop-App unverändert
  (Treiber, Metadaten, Schutzregeln, Import/Export, KI, ER-Modell/DDL, EF-Core) – keine doppelte Logik.
- **Anmeldung:** eigener Benutzer (argon2), serverseitige Sitzung im Cookie (httponly, secure, SameSite=strict,
  12 h gleitend), Rate-Limit (8 Versuche / 5 min je IP), schreibende Anfragen nur mit Kennungs-Kopfzeile,
  strenge Content-Security-Policy, keine API-Doku nach außen.
- **Verbindungen:** Passwörter und KI-Schlüssel serverseitig mit Fernet verschlüsselt (Schlüssel nur in der
  600-Geheimnisdatei des Dienstes), gehen nie an den Browser zurück; Testen, Farbmarkierung, Schreibschutz.
- **Datenbank:** Objektbaum mit Schema-Auswahl und Suche, Datenraster mit Seiten, Sortieren, Filter (nur Bedingung),
  Bearbeiten per Doppelklick, neue/gelöschte Zeilen – „Übernehmen“ schreibt alles in einer Transaktion.
- **SQL-Editor:** CodeMirror (lokal ausgeliefert) mit Highlighting und Autovervollständigung für Tabellen/Spalten,
  Tabs, Strg+Enter, mehrere Anweisungen, EXPLAIN, Abbrechen, Nachladen in 500er-Schritten, Export des Ergebnisses.
  Rückfrage bei UPDATE/DELETE ohne WHERE, DROP, TRUNCATE und auf Produktiv-Verbindungen; Schreibschutz sperrt.
- **KI-Leiste:** SQL schreiben, erklären, optimieren (mit EXPLAIN), Fehler erklären; nur das Schema geht an die KI,
  KI-SQL landet in einem neuen Tab. Anbieter: Claude-API (Schlüssel verschlüsselt), Ollama (Adresse einstellbar).
- **ER-Diagramm im Browser (SVG):** Mausrad-Zoom um den Zeiger, Ziehen, Karten verschieben (Raster, Positionen
  gespeichert), rechtwinklige Linien mit Plaketten 1 / n / 0..1, Farben je Art, Legende, Hervorheben, Tooltip in
  Worten, Ansicht alle Spalten/Schlüssel/Namen, **EF-Core-Stil** (Klassen, C#-Typen, Navigationen, 1 ↔ *).
  Tabelle/Spalte anlegen und **Beziehung per Ziehen** mit DDL-Vorschau, Beziehungen vorschlagen,
  Export SVG/PNG und DbContext (C#).
- **Import/Export:** CSV, JSON, JSON Lines, Excel (Vorschau, neue Tabelle) und CSV/JSON/Excel/SQL-Download.
- **Betrieb:** `deploy/deploy-web.sh` spielt in Container 104 (192.168.178.215) ein: eigener Systembenutzer,
  systemd-Dienst mit Härtung, HTTPS auf 443 (selbstsigniert, EC), nftables im Container (443/22 nur aus
  192.168.178.0/24), Admin-Passwort nur im Schlüsselbund des PCs. `requirements-web.txt` ohne PySide6.
- Tests: `tests/test_web.py` (API gegen SQLite, DuckDB, PostgreSQL); Screenshots `docs/web_screenshots.py`.

## 0.2.2 – 2026-11-23

- **Zoom wie in gängigen Werkzeugen:** Mausrad zoomt direkt um den Mauszeiger (10–400 %), Shift+Mausrad scrollt
  waagerecht, Verschieben per Ziehen auf freier Fläche, Leertaste+Ziehen oder mittlerer Maustaste.
  Tasten +/− und Strg+Plus/Minus/0. **Zoomleiste** unten rechts: „−“, Prozent (klicken → Eingabe), „+“, „100 %“, „Anpassen“.
- **Anpassen repariert:** passt auf den tatsächlichen Inhalt (kleiner Rand), Szenengröße wächst dynamisch mit.
  Beim Öffnen nie unter 60 % (Schrift bleibt lesbar) – bei großen Schemas lieber scrollen, Start bei der zentralen Tabelle.
- **Gespeicherte Positionen aus 0.2.0** (mit unverbundenen Tabellen weit unten) werden ignoriert und neu angeordnet;
  unverbundene Tabellen stehen kompakt rechts neben dem verbundenen Block.
- **Minikarte:** Sichtbereich als dünner orangener Rahmen; Klicken/Ziehen verschiebt die Ansicht.
- **Werkzeugleiste:** Gruppen mit Symbolen (⟳ | Ansicht | ▦ Anordnen | ＋ Tabelle ＋ Spalte ✦ KI | ⇩ Export); bei Platzmangel
  wandern Knöpfe ins „…“-Menü. Hinweise („„public“ ist leer …“) stehen in einer eigenen, ausblendbaren Zeile darunter.

## 0.2.1 – 2026-11-23

- **Schema-Automatik:** Ist das Standardschema (public/main/dbo) leer, öffnen Objektbaum und Diagramm das Schema mit den
  meisten Tabellen und sagen es („„public“ ist leer – zeige Schema „…““). Das zuletzt gewählte Schema wird je Verbindung gemerkt.
- **Objektbaum:** Schemas mit Tabellenzahl („js_45b3… (15)“); Aufklappen eines Schemas macht es zum Arbeitsschema.
- **SQL-Editor:** Schema-Auswahl in der Werkzeugleiste – setzt `search_path` (PostgreSQL), `USE` (MySQL) bzw.
  `SET schema` (DuckDB), damit unqualifizierte Tabellennamen funktionieren; Autovervollständigung und KI nutzen dieses Schema.
- **Diagramm, ruhigeres Layout:** meistreferenzierte Tabelle in der Mitte, abhängige Tabellen spaltenweise links/rechts,
  Tabellen ohne Beziehung kompakt im Raster daneben; keine Überlappungen; Start mit „An Fenster anpassen“.
- **Linien:** rechtwinklig mit abgerundeten Ecken, exakt auf Höhe von FK-/PK-Zeile, an der näheren Kartenseite;
  Linien zur selben Tabelle gestaffelt. Plaketten an beiden Enden („1“, „n“, „0..1“), größere Krähenfüße.
  Farbe je Art: 1:n Blau, 1:1 Orange, n:m Neon-Grün gestrichelt; Zwischentabellen mit Plakette „n:m“.
  Tooltip in Worten („Eine Firma hat viele Entwuerfe.“) plus Technik (Spalten, n:1, ON DELETE …).
- **Hervorhebung:** Tabelle überfahren/markieren betont sie samt Nachbarn und Linien, der Rest wird gedimmt.
- **Kartenansicht:** „Alle Spalten“ / „Nur Schlüssel“ / „Nur Tabellennamen“; lange Karten ein-/ausklappbar (▾/▸).
- **Minikarte** unten rechts (Klick springt), **Legende** oben rechts (einklappbar), **Einrasten** im 20-px-Raster.
- **EF-Core-Stil** (Standard bei SQL Server, für alle Systeme umschaltbar): Entitäten mit Klassennamen (PascalCase,
  Einzahl: firmen → Firma), darunter „[schema].[tabelle]“; Abschnitte „Eigenschaften“ (C#-Typen, `?` für nullbar,
  Schlüssel/FK markiert) und „Navigationen“ (Firma.Entwuerfe : ICollection<Entwurf>, Entwurf.Firma : Firma);
  Linien mit Pfeil zur Hauptentität und Multiplizität „1“/„0..1“ ↔ „*“.
- **Export „DbContext (C#, EF Core)“:** Entitätsklassen + DbContext mit Fluent-API (ToTable, HasKey, HasColumnName,
  HasOne/WithMany/WithOne, OnDelete) als .cs-Datei.

## 0.2.0 – 2026-11-23

- **Visueller Beziehungsdesigner** (Seite „Diagramm“): ER-Diagramm je Schema mit Tabellenkarten (Primärschlüssel 🔑,
  Fremdschlüssel ↗, NOT NULL fett), Linien in Krähenfuß-Notation (1:n, 1:1), n:m-Zwischentabellen blau markiert,
  Selbstbezüge als Schleife. Zoom mit Strg+Mausrad, Verschieben per Ziehen, automatische Anordnung nach
  Abhängigkeiten; Positionen werden je Verbindung und Schema gespeichert.
- Bearbeiten im Diagramm: neue Tabelle, neue Spalte, Spalte ändern (Doppelklick), Beziehung per Ziehen von Spalte zu
  Spalte mit ON DELETE/ON UPDATE. Alles erzeugt zuerst eine DDL-Vorschau im Dialekt der Datenbank (PostgreSQL,
  MySQL/MariaDB, SQLite, DuckDB, SQL Server) und wird erst nach „Ausführen“ in einer Transaktion ausgeführt.
  SQLite/DuckDB: Fremdschlüssel und Typwechsel per Tabellen-Neuaufbau mit Datenübernahme.
  Schreibschutz und Produktiv-Markierung gelten auch hier.
- „Beziehungen vorschlagen“: Namensregel (z. B. kunde_id → kunden.id) plus KI-Vorschläge – an die KI geht nur
  das Schema; Vorschläge landen in der Vorschau, nie automatisch.
- Export des Diagramms als PNG und SVG.
- Neues App-Icon (Tux mit Datenbank), Fenster- und Starter-Icon.
- Behoben: SQLite-Metadaten wurden aus mehreren Hintergrund-Threads verschränkt gelesen (Autovervollständigung
  konnte abstürzen).

## 0.1.0 – 2026-11-23

Erste Fassung von **Pi DB Studio** (Desktop, Python/PySide6).

- Verbindungen zu PostgreSQL, MySQL/MariaDB, SQLite, DuckDB und SQL Server über eine gemeinsame Treiber-Schnittstelle
  (Metadaten, Nachladen von Ergebnissen, Transaktionen, Abbrechen, EXPLAIN, Typ-Abbildung).
- Verbindungskarten mit Farbmarkierung und Schreibschutz; Passwörter nur im Schlüsselbund.
- Objektbaum mit Suche; Datenraster mit Seiten, Sortieren, Filter und Bearbeiten (Übernehmen/Verwerfen in einer Transaktion).
- SQL-Editor mit Tabs, Hervorhebung, Autovervollständigung, Verlauf, EXPLAIN und Abbrechen; Ausführung im Hintergrund.
- Import (CSV, JSON, Excel) mit Vorschau und Spaltenzuordnung; Export (CSV, JSON, Excel, SQL-INSERT);
  Tabelle in andere Verbindung kopieren.
- KI-Assistent (Claude-API, Claude Code oder Ollama): Text → SQL, erklären, optimieren, Fehler erklären. Nur das Schema
  geht an die KI, Datenzeilen nur auf Wunsch; KI-SQL wird nie automatisch ausgeführt.
- Schutzabfragen bei gefährlichen Anweisungen.
