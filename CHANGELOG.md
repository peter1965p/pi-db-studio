# Changelog

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
