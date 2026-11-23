"""SQL-Editor mit Tabs, Ergebnisraster, EXPLAIN, Verlauf, Abbrechen und KI-Leiste."""

from __future__ import annotations

import datetime as dt
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QMenu, QPlainTextEdit, QSplitter, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import austausch, ki, sqlschutz, treiber, verbindungen
from . import arbeiter
from .bausteine import Kopf, karte, knopf, label, leiste, meldung, rueckfrage, tabelle, zeile
from .editor import SqlEditor
from .raster import ErgebnisModell
from .schalter import Schalter


class EditorSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        self.tabellen: list[str] = []
        self.spalten_je: dict[str, list[str]] = {}
        self.ergebnis: treiber.Ergebnis | None = None
        self.letzter_fehler = ("", "")
        self.laeuft = False
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("SQL-Editor", "Strg+Enter führt die Markierung aus, sonst alles. Strg+Leertaste ergänzt Namen.")
        lay.addWidget(self.kopf)

        teiler = QSplitter(Qt.Horizontal)
        mitte = QSplitter(Qt.Vertical)
        oben = QWidget()
        ov = QVBoxLayout(oben)
        ov.setContentsMargins(0, 0, 0, 0)
        self.k_los = knopf("▶ Ausführen", self.ausfuehren, "primaer", "Strg+Enter")
        self.k_explain = knopf("EXPLAIN", self.explain, "zweit")
        self.k_stopp = knopf("■ Abbrechen", self.abbrechen, "gefahr")
        self.k_stopp.setEnabled(False)
        self.k_verlauf = knopf("Verlauf")
        self.k_verlauf.clicked.connect(self._verlauf_menue)
        self.schema_wahl = QComboBox()
        self.schema_wahl.setToolTip("Arbeitsschema: unqualifizierte Tabellennamen beziehen sich darauf "
                                    "(PostgreSQL search_path, MySQL USE, DuckDB SET schema)")
        self.schema_wahl.setMinimumWidth(170)
        self.schema_wahl.currentTextChanged.connect(self._schema_gewechselt)
        ov.addLayout(zeile(self.k_los, self.k_explain, self.k_stopp, None, label("Schema", "gedimmt"), self.schema_wahl,
                           self.k_verlauf, knopf("+ Tab", lambda: self.neuer_tab(""))))
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._tab_zu)
        ov.addWidget(self.tabs, 1)
        unten = QWidget()
        uv = QVBoxLayout(unten)
        uv.setContentsMargins(0, 0, 0, 0)
        self.ergebnis_tabs = QTabWidget()
        self.modell = ErgebnisModell(self)
        self.ansicht = tabelle()
        self.ansicht.setModel(self.modell)
        self.meldungen = QPlainTextEdit()
        self.meldungen.setReadOnly(True)
        self.meldungen.setObjectName("sqlEditor")
        self.ergebnis_tabs.addTab(self.ansicht, "Ergebnis")
        self.ergebnis_tabs.addTab(self.meldungen, "Meldungen")
        uv.addWidget(self.ergebnis_tabs, 1)
        self.status = label("", "gedimmt")
        self.k_mehr = knopf("Weitere 1.000 laden", self._mehr)
        self.k_mehr.hide()
        export = knopf("Export …")
        menue = QMenu(export)
        for k, n in austausch.FORMATE.items():
            menue.addAction(n.split(" (")[0], lambda k=k: self._export(k))
        export.setMenu(menue)
        uv.addLayout(zeile(self.status, None, self.k_mehr, export))
        mitte.addWidget(oben)
        mitte.addWidget(unten)
        mitte.setSizes([330, 420])
        teiler.addWidget(mitte)
        teiler.addWidget(self._ki_leiste())
        teiler.setSizes([900, 360])
        lay.addWidget(teiler, 1)
        QShortcut(QKeySequence("Ctrl+T"), self, lambda: self.neuer_tab(""))
        QShortcut(QKeySequence("F5"), self, self.ausfuehren)
        self.neuer_tab("")

    # --- Tabs ----------------------------------------------------------------------------------------------------
    def neuer_tab(self, text: str, von_ki: bool = False):
        ed = SqlEditor()
        ed.setPlainText(text)
        ed.ausfuehren.connect(self.ausfuehren)
        ed.setze_namen(self.tabellen, self.spalten_je)
        ed.von_ki = von_ki
        ed.textChanged.connect(lambda: setattr(ed, "von_ki", ed.von_ki and bool(ed.toPlainText().strip())))
        self.tabs.addTab(ed, f"Abfrage {self.tabs.count() + 1}" + (" · KI" if von_ki else ""))
        self.tabs.setCurrentWidget(ed)
        if hasattr(self.h, "seiten"):
            self.h.zeige(self)
        ed.setFocus()
        return ed

    def _tab_zu(self, i):
        self.tabs.removeTab(i)
        if not self.tabs.count():
            self.neuer_tab("")

    def editor(self) -> SqlEditor:
        return self.tabs.currentWidget()

    def setze_schemas(self, schemas: list[str]):
        self.schema_wahl.blockSignals(True)
        self.schema_wahl.clear()
        self.schema_wahl.addItems(schemas)
        self.schema_wahl.blockSignals(False)

    def schema_gewaehlt(self, schema: str, objekte: dict | None = None):
        """Vom Fenster: Arbeitsschema hat gewechselt -> Auswahl + Autovervollständigung nachziehen."""
        self.schema_wahl.blockSignals(True)
        if self.schema_wahl.findText(schema) < 0:
            self.schema_wahl.addItem(schema)
        self.schema_wahl.setCurrentText(schema)
        self.schema_wahl.blockSignals(False)
        if objekte is not None:
            self.namen_aktualisieren(schema, objekte)
            return
        t = self.h.t
        if t:
            arbeiter.starte(lambda: t.objekte(schema), lambda o: self.namen_aktualisieren(schema, o))

    def _schema_gewechselt(self, schema: str):
        if schema and self.h.t:
            self.h.schema_gewaehlt(schema)

    def namen_aktualisieren(self, schema: str, objekte: dict):
        """Tabellen sofort, Spalten im Hintergrund – für die Autovervollständigung."""
        self.tabellen = list(objekte.get("tabellen", [])) + list(objekte.get("views", []))
        self.spalten_je = {}
        self._namen_an_editoren()
        t = self.h.t
        namen = self.tabellen[:300]

        def lauf():
            return {n: [s.name for s in t.spalten(schema, n)] for n in namen}
        arbeiter.starte(lauf, self._spalten_da)

    def _spalten_da(self, spalten):
        self.spalten_je = spalten
        self._namen_an_editoren()

    def _namen_an_editoren(self):
        for i in range(self.tabs.count()):
            self.tabs.widget(i).setze_namen(self.tabellen, self.spalten_je)

    # --- Ausführen -----------------------------------------------------------------------------------------------
    def _bereit(self) -> bool:
        if not self.h.t:
            meldung(self, "Keine Verbindung", "Erst unter „Verbindungen“ verbinden.")
            return False
        return not self.laeuft

    def ausfuehren(self):
        if not self._bereit():
            return
        ed = self.editor()
        sql = ed.sql_zum_ausfuehren()
        if not sql:
            return
        p = sqlschutz.pruefe(sql)
        t = self.h.t
        if p.aendert and t.schreibschutz:
            meldung(self, "Schreibschutz", "Diese Verbindung ist schreibgeschützt. Ändernde Anweisungen sind gesperrt.", True)
            return
        gruende = list(p.warnungen)
        if p.aendert and getattr(ed, "von_ki", False):
            gruende.append("Das SQL stammt vom KI-Assistenten und ändert Daten oder Struktur.")
        if p.aendert and self.h.cfg.get("farbe") == "#e05252":
            gruende.append("Die Verbindung ist als produktiv markiert.")
        if gruende and not rueckfrage(self, "Wirklich ausführen?", "\n".join(f"• {g}" for g in gruende)):
            return
        anweisungen = treiber.anweisungen(sql)
        limit = int(verbindungen.einstellungen().get("zeilenlimit", 1000))
        self._laufstart(f"Führe {len(anweisungen)} Anweisung(en) aus …")

        def lauf():
            protokoll, letztes = [], None
            for anw in anweisungen:
                erg = t.abfrage(anw, limit=limit)
                if erg.spalten:
                    if letztes:
                        letztes.schliessen()
                    letztes = erg
                    protokoll.append(f"✓ {len(erg.zeilen)}{'+' if erg.mehr else ''} Zeilen in {erg.dauer * 1000:.0f} ms")
                else:
                    protokoll.append(f"✓ {erg.betroffen if erg.betroffen >= 0 else 'OK'}"
                                     f"{' Zeile(n) betroffen' if erg.betroffen >= 0 else ''} in {erg.dauer * 1000:.0f} ms")
            return letztes, protokoll
        arbeiter.starte(lauf, lambda d: self._fertig(sql, d), lambda f: self._fehler(sql, f))

    def _laufstart(self, text):
        self.laeuft = True
        self.k_los.setEnabled(False)
        self.k_explain.setEnabled(False)
        self.k_stopp.setEnabled(True)
        self.status.setObjectName("gedimmt")
        self.status.setText(text)

    def _laufende(self):
        self.laeuft = False
        self.k_los.setEnabled(True)
        self.k_explain.setEnabled(True)
        self.k_stopp.setEnabled(False)

    def _fertig(self, sql, daten):
        self._laufende()
        erg, protokoll = daten
        if self.ergebnis:
            self.ergebnis.schliessen()
        self.ergebnis = erg
        self.meldungen.setPlainText("\n".join(protokoll))
        if erg:
            self.modell.setze(erg.spalten, erg.zeilen)
            self._spaltenbreiten()
            self.ergebnis_tabs.setCurrentIndex(0)
            self.status.setText(f"{len(erg.zeilen):,}{' (weitere vorhanden)' if erg.mehr else ''} Zeilen · {erg.dauer * 1000:.0f} ms".replace(",", "."))
        else:
            self.modell.setze([], [])
            self.ergebnis_tabs.setCurrentIndex(1)
            self.status.setText(protokoll[-1] if protokoll else "Fertig")
        self.k_mehr.setVisible(bool(erg and erg.mehr))
        self._verlauf_schreiben(sql, True)
        self.letzter_fehler = ("", "")
        if sqlschutz.pruefe(sql).aendert:
            self.h.explorer.neu_laden()

    def _fehler(self, sql, text):
        self._laufende()
        self.status.setObjectName("fehlertext")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText("Fehler – Details unter „Meldungen“. Die KI-Leiste kann ihn erklären.")
        self.meldungen.setPlainText(f"✗ {text}")
        self.ergebnis_tabs.setCurrentIndex(1)
        self.letzter_fehler = (sql, text)
        self._verlauf_schreiben(sql, False)

    def _spaltenbreiten(self):
        self.ansicht.resizeColumnsToContents()
        for c in range(self.modell.columnCount()):
            self.ansicht.setColumnWidth(c, min(max(self.ansicht.columnWidth(c), 60), 340))

    def _mehr(self):
        erg = self.ergebnis
        if not erg or not erg.mehr:
            return
        self.k_mehr.setEnabled(False)

        def fertig(neu):
            self.modell.anhaengen(neu)
            self.k_mehr.setEnabled(True)
            self.k_mehr.setVisible(erg.mehr)
            self.status.setText(f"{len(self.modell.zeilen):,} Zeilen{' (weitere vorhanden)' if erg.mehr else ''}".replace(",", "."))
        arbeiter.starte(lambda: erg.weitere(1000), fertig, lambda f: self.status.setText(f"Fehler: {f}"))

    def abbrechen(self):
        if self.h.t:
            self.h.t.abbrechen()
            self.status.setText("Abbruch angefordert …")

    def explain(self):
        if not self._bereit():
            return
        sql = self.editor().sql_zum_ausfuehren()
        if not sql:
            return
        anw = treiber.anweisungen(sql)[0]
        if sqlschutz.pruefe(anw).aendert and not rueckfrage(self, "EXPLAIN", "Die Anweisung ändert Daten. Nur den Plan anzeigen (ohne ANALYZE)?", "Plan zeigen"):
            return
        t = self.h.t
        self._laufstart("Erstelle Ausführungsplan …")

        def fertig(erg):
            self._laufende()
            self.modell.setze(erg.spalten, erg.zeilen)
            self._spaltenbreiten()
            self.meldungen.setPlainText("\n".join(" | ".join(treiber_text(v) for v in z) for z in erg.zeilen))
            self.ergebnis_tabs.setCurrentIndex(1)
            self.status.setText("Ausführungsplan")
            self.letzter_plan = self.meldungen.toPlainText()
        arbeiter.starte(lambda: t.explain(anw), fertig, lambda f: self._fehler(anw, f))

    # --- Verlauf -------------------------------------------------------------------------------------------------
    def _verlauf_schreiben(self, sql, ok):
        try:
            with verbindungen.verlauf_datei().open("a", encoding="utf-8") as f:
                f.write(json.dumps({"zeit": dt.datetime.now().isoformat(timespec="seconds"), "verbindung": self.h.cfg.get("name", ""),
                                    "ok": ok, "sql": sql[:4000]}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def verlauf(self, anzahl=30) -> list[dict]:
        try:
            zeilen = verbindungen.verlauf_datei().read_text(encoding="utf-8").splitlines()[-500:]
        except OSError:
            return []
        eintraege, gesehen = [], set()
        for z in reversed(zeilen):
            try:
                e = json.loads(z)
            except ValueError:
                continue
            if e["sql"] not in gesehen:
                gesehen.add(e["sql"])
                eintraege.append(e)
            if len(eintraege) >= anzahl:
                break
        return eintraege

    def _verlauf_menue(self):
        m = QMenu(self)
        eintraege = self.verlauf()
        if not eintraege:
            m.addAction("Noch kein Verlauf").setEnabled(False)
        for e in eintraege:
            kurz = " ".join(e["sql"].split())[:90]
            m.addAction(f"{'✓' if e['ok'] else '✗'} {e['zeit'][11:16]}  {kurz}", lambda s=e["sql"]: self.editor().setPlainText(s))
        m.exec(self.k_verlauf.mapToGlobal(self.k_verlauf.rect().bottomLeft()))

    def _export(self, fmt):
        if not self.modell.spalten:
            meldung(self, "Export", "Erst eine Abfrage ausführen.")
            return
        pfad, _ = QFileDialog.getSaveFileName(self, "Ergebnis exportieren", f"ergebnis.{fmt}", austausch.FORMATE[fmt])
        if pfad:
            n = austausch.exportieren(pfad, self.modell.spalten, self.modell.zeilen, fmt, "ergebnis",
                                      self.h.t.zitiere if self.h.t else (lambda s: s))
            self.status.setText(f"{n:,} Zeilen exportiert{' (nur die geladenen)' if self.ergebnis and self.ergebnis.mehr else ''}.".replace(",", "."))

    # --- KI ------------------------------------------------------------------------------------------------------
    def _ki_leiste(self) -> QFrame:
        f, l = karte("KI-Assistent")
        f.setMinimumWidth(300)
        self.ki_anbieter = label("", "gedimmt", True)
        l.addWidget(self.ki_anbieter)
        self.ki_frage = QPlainTextEdit()
        self.ki_frage.setPlaceholderText("Was möchtest du wissen? z. B. „Umsatz je Kunde im letzten Monat, absteigend“")
        self.ki_frage.setMaximumHeight(90)
        l.addWidget(self.ki_frage)
        l.addLayout(zeile(knopf("SQL erzeugen", lambda: self._ki("sql"), "primaer"), knopf("Erklären", lambda: self._ki("erklaeren"))))
        l.addLayout(zeile(knopf("Optimieren", lambda: self._ki("optimieren")), knopf("Fehler erklären", lambda: self._ki("fehler"), "zweit")))
        self.ki_beispiele = Schalter("Beispielzeilen mitsenden")
        self.ki_beispiele.setToolTip("Aus: Die KI sieht nur Tabellen, Spalten und Typen – keine Daten.")
        l.addWidget(self.ki_beispiele)
        l.addWidget(label("Standard: nur das Schema geht an die KI. SQL der KI wird nie von selbst ausgeführt.", "gedimmt", True))
        self.ki_antwort = QTextBrowser()
        self.ki_antwort.setOpenExternalLinks(False)
        l.addWidget(self.ki_antwort, 1)
        self.k_ki_uebernehmen = knopf("SQL in neuen Tab übernehmen", self._ki_uebernehmen, "primaer")
        self.k_ki_uebernehmen.setEnabled(False)
        l.addWidget(self.k_ki_uebernehmen)
        self.ki_sql = ""
        self.ki_anbieter_anzeigen()
        return f

    def ki_anbieter_anzeigen(self):
        e = verbindungen.einstellungen()
        anbieter = e.get("ki_anbieter", "claude-api")
        name = dict(ki.anbieter_liste()).get(anbieter, anbieter) if anbieter else "keiner"
        self.ki_anbieter.setText(f"Anbieter: {name}" + (f" · {e.get('ki_modell')}" if e.get("ki_modell") else ""))

    def _ki(self, art):
        if not self.h.t:
            meldung(self, "Keine Verbindung", "Die KI braucht das Schema einer verbundenen Datenbank.")
            return
        e = verbindungen.einstellungen()
        anbieter, modell = e.get("ki_anbieter", "claude-api"), e.get("ki_modell", "")
        werte = {}
        if art == "sql":
            werte["text"] = self.ki_frage.toPlainText().strip()
            if not werte["text"]:
                self.ki_frage.setFocus()
                return
        elif art == "fehler":
            sql, fehler = self.letzter_fehler
            if not fehler:
                meldung(self, "Kein Fehler", "Es gibt gerade keinen Fehler zu erklären.")
                return
            werte.update(sql=sql, fehler=fehler)
        else:
            werte["sql"] = self.editor().sql_zum_ausfuehren()
            if not werte["sql"]:
                meldung(self, "Kein SQL", "Erst eine Abfrage in den Editor schreiben oder markieren.")
                return
        t = self.h.t
        schema = t.aktuelles_schema or self.h.explorer.schema or t.standard_schema()
        beispiele = 3 if self.ki_beispiele.isChecked() else 0
        self.ki_antwort.setMarkdown("_Denke nach …_")
        self.k_ki_uebernehmen.setEnabled(False)

        def lauf():
            kontext = ki.schema_kontext(t, schema, beispielzeilen=beispiele)
            if art == "optimieren":
                try:
                    werte["plan"] = "\n".join(" | ".join(treiber_text(v) for v in z) for z in t.explain(werte["sql"]).zeilen)[:6000]
                except Exception:
                    werte["plan"] = ""
            return ki.frage(anbieter, art, kontext, modell, **werte)
        arbeiter.starte(lauf, self._ki_da, lambda f: self.ki_antwort.setMarkdown(f"**Fehler:** {f}"))

    def _ki_da(self, text):
        self.ki_antwort.setMarkdown(text)
        self.ki_sql = ki.sql_aus_antwort(text)
        self.k_ki_uebernehmen.setEnabled(bool(self.ki_sql))

    def _ki_uebernehmen(self):
        if self.ki_sql:
            self.neuer_tab(self.ki_sql, von_ki=True)


def treiber_text(v) -> str:
    return "NULL" if v is None else str(v)
