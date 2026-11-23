# Changelog

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
