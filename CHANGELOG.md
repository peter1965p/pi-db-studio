# Changelog

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
