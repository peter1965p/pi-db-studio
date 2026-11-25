"""Objektbaum (Schemas → Tabellen, Views, Indizes, Funktionen) und Datenraster mit Seiten, Filter, Bearbeiten."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHeaderView, QLineEdit, QMenu, QSpinBox, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import austausch, verbindungen
from . import arbeiter
from .bausteine import Kopf, knopf, label, leiste, meldung, rueckfrage, tabelle, zeile
from .raster import TabellenModell

GRUPPEN = [("tabellen", "Tabellen"), ("views", "Views"), ("indizes", "Indizes"), ("funktionen", "Funktionen")]
ROLLE = Qt.UserRole


class ExplorerSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        self.schema = self.tabelle_name = None
        self.offset, self.gesamt, self.sortierung = 0, 0, ""
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("Datenbank", "Doppelklick auf eine Tabelle öffnet sie. Zellen bearbeiten, dann übernehmen.")
        lay.addWidget(self.kopf)
        teiler = QSplitter(Qt.Horizontal)
        links = QWidget()
        lv = QVBoxLayout(links)
        lv.setContentsMargins(0, 0, 0, 0)
        self.db_wahl = QComboBox()
        self.db_wahl.setToolTip("Datenbank auf diesem Server – wechselt mit derselben Anmeldung")
        self.db_wahl.activated.connect(self._datenbank_gewaehlt)
        self.db_wahl.hide()
        lv.addWidget(self.db_wahl)
        self.suche = QLineEdit()
        self.suche.setPlaceholderText("Im Baum suchen …")
        self.suche.setClearButtonEnabled(True)
        self.suche.textChanged.connect(self._filtern)
        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.itemExpanded.connect(self._aufgeklappt)
        self.baum.itemDoubleClicked.connect(self._doppelklick)
        self.baum.setContextMenuPolicy(Qt.CustomContextMenu)
        self.baum.customContextMenuRequested.connect(self._kontextmenue)
        lv.addWidget(self.suche)
        lv.addWidget(self.baum, 1)
        lv.addLayout(zeile(knopf("Aktualisieren", self.neu_laden), dehnen=False))
        rechts = QWidget()
        rv = QVBoxLayout(rechts)
        rv.setContentsMargins(0, 0, 0, 0)
        self.tab_titel = label("Keine Tabelle geöffnet", "karteTitel")
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter, z. B.  preis > 10 AND name LIKE 'A%'   (Enter)")
        self.filter.returnPressed.connect(lambda: self._seite(0))
        self.groesse = QSpinBox()
        self.groesse.setRange(10, 10000)
        self.groesse.setSingleStep(100)
        self.groesse.setValue(200)
        self.groesse.setPrefix("je Seite ")
        self.zurueck, self.vor = knopf("◀", lambda: self._seite(self.offset - self.groesse.value())), knopf("▶", lambda: self._seite(self.offset + self.groesse.value()))
        self.seite_text = label("", "gedimmt")
        rv.addLayout(zeile(self.tab_titel, None, self.zurueck, self.seite_text, self.vor, self.groesse))
        rv.addWidget(self.filter)
        self.modell = TabellenModell(self)
        self.ansicht = tabelle()
        self.ansicht.setModel(self.modell)
        kopf = self.ansicht.horizontalHeader()
        kopf.setSectionsClickable(True)
        kopf.setSortIndicatorShown(True)
        kopf.sortIndicatorChanged.connect(self._sortieren)
        kopf.setSectionResizeMode(QHeaderView.Interactive)
        rv.addWidget(self.ansicht, 1)
        self.k_neu = knopf("+ Zeile", self._zeile_neu)
        self.k_loeschen = knopf("Zeile löschen", self._zeilen_loeschen)
        self.k_uebernehmen = knopf("Übernehmen", self._uebernehmen, "primaer")
        self.k_verwerfen = knopf("Verwerfen", self._verwerfen)
        export = knopf("Export …")
        menue = QMenu(export)
        for k, n in austausch.FORMATE.items():
            menue.addAction(n.split(" (")[0], lambda k=k: self._export(k))
        export.setMenu(menue)
        self.status = label("", "gedimmt")
        rv.addLayout(zeile(self.k_neu, self.k_loeschen, self.k_verwerfen, self.k_uebernehmen, self.status, None,
                           knopf("Als SQL öffnen", self._als_sql), export))
        teiler.addWidget(links)
        teiler.addWidget(rechts)
        teiler.setSizes([280, 900])
        lay.addWidget(teiler, 1)
        self.modell.dataChanged.connect(self._knoepfe)
        self.modell.rowsInserted.connect(self._knoepfe)
        self.modell.modelReset.connect(self._knoepfe)
        self._knoepfe()

    # --- Baum ----------------------------------------------------------------------------------------------------
    def neu_laden(self):
        self.baum.clear()
        t = self.h.t
        if not t:
            return
        self.kopf.status(self.h.status_text(), "pill")

        gemerkt = verbindungen.gemerktes_schema(self.h.cfg)

        def lauf():
            zahlen = t.tabellen_zahlen()
            schema, hinweis = t.bestes_schema(gemerkt, zahlen)
            if schema:
                t.setze_schema(schema)
            try:
                dbs = (t.datenbanken(), t.aktuelle_datenbank()) if t.art == "postgresql" else ([], "")
            except Exception:
                dbs = ([], "")
            return zahlen, schema, hinweis, t.objekte(schema) if schema else {}, dbs
        arbeiter.starte(lauf, self._schemas_da, lambda f: self.status.setText(f"Fehler: {f}"))

    def _schemas_da(self, daten):
        zahlen, std, hinweis, objekte, (dbs, aktuell) = daten
        self.db_wahl.blockSignals(True)
        self.db_wahl.clear()
        for d in dbs:
            self.db_wahl.addItem(f"🗄 {d}", d)
        self.db_wahl.setCurrentIndex(max(0, self.db_wahl.findData(aktuell)))
        self.db_wahl.blockSignals(False)
        self.db_wahl.setVisible(len(dbs) > 1)
        self._laedt_schema = True
        self.h.editor.setze_schemas(list(zahlen))
        for s, n in zahlen.items():
            item = QTreeWidgetItem([f"{s}  ({n})"])
            item.setData(0, ROLLE, ("schema", s))
            item.setToolTip(0, f"{s}: {n} Tabelle{'n' if n != 1 else ''}")
            item.addChild(QTreeWidgetItem(["lädt …"]))
            self.baum.addTopLevelItem(item)
            if s == std:
                self._objekte_da(item, objekte)
                item.setExpanded(True)
                self.baum.setCurrentItem(item)
        self._laedt_schema = False
        self.status.setText(hinweis)
        self.h.schema_gewaehlt(std, objekte, merken=False)

    def _datenbank_gewaehlt(self, _i=None):
        name = self.db_wahl.currentData()
        if name and self.h.t and name != self.h.cfg.get("datenbank"):
            self.h.datenbank_wechseln(name)

    def _aufgeklappt(self, item):
        art = item.data(0, ROLLE)
        if not art or art[0] != "schema" or getattr(self, "_laedt_schema", False):
            return
        t, s = self.h.t, art[1]
        geladen = not (item.childCount() == 1 and not item.child(0).data(0, ROLLE))

        def da(o):
            if not geladen:
                self._objekte_da(item, o)
            self.h.schema_gewaehlt(s, o)
        arbeiter.starte(lambda: t.objekte(s), da, lambda f: self.status.setText(f"Fehler: {f}"))

    def _objekte_da(self, item, objekte):
        item.takeChildren()
        s = item.data(0, ROLLE)[1]
        for schluessel, name in GRUPPEN:
            namen = objekte.get(schluessel, [])
            g = QTreeWidgetItem([f"{name}  ({len(namen)})"])
            g.setData(0, ROLLE, ("gruppe", s, schluessel))
            for n in namen:
                c = QTreeWidgetItem([n])
                c.setData(0, ROLLE, (schluessel, s, n))
                g.addChild(c)
            item.addChild(g)
            if schluessel == "tabellen":
                g.setExpanded(True)
        self._filtern(self.suche.text())

    def _filtern(self, text):
        text = text.lower().strip()
        for i in range(self.baum.topLevelItemCount()):
            schema = self.baum.topLevelItem(i)
            for j in range(schema.childCount()):
                gruppe = schema.child(j)
                sichtbar = 0
                for k in range(gruppe.childCount()):
                    c = gruppe.child(k)
                    an = not text or text in c.text(0).lower()
                    c.setHidden(not an)
                    sichtbar += an
                if text and sichtbar:
                    gruppe.setExpanded(True)

    def _doppelklick(self, item, _spalte=0):
        art = item.data(0, ROLLE)
        if art and art[0] in ("tabellen", "views"):
            self.oeffnen(art[1], art[2])

    def _kontextmenue(self, punkt):
        item = self.baum.itemAt(punkt)
        art = item.data(0, ROLLE) if item else None
        if not art or art[0] not in ("tabellen", "views"):
            return
        m = QMenu(self)
        m.addAction("Öffnen", lambda: self.oeffnen(art[1], art[2]))
        m.addAction("SELECT im Editor", lambda: self.h.editor.neuer_tab(
            f"SELECT * FROM {self.h.t.voll(art[1], art[2])} LIMIT 100;" if self.h.t.art != "mssql"
            else f"SELECT TOP 100 * FROM {self.h.t.voll(art[1], art[2])};"))
        m.addAction("In andere Verbindung kopieren …", lambda: self.h.austausch.kopieren_vorbelegen(art[1], art[2]))
        m.exec(self.baum.viewport().mapToGlobal(punkt))

    # --- Datenraster ---------------------------------------------------------------------------------------------
    def oeffnen(self, schema, tabelle):
        if self.modell.geaendert and not rueckfrage(self, "Ungespeicherte Änderungen", "Änderungen verwerfen?", "Verwerfen"):
            return
        self.schema, self.tabelle_name, self.sortierung = schema, tabelle, ""
        self.filter.clear()
        self.ansicht.horizontalHeader().blockSignals(True)
        self.ansicht.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.ansicht.horizontalHeader().blockSignals(False)
        self._seite(0)

    def _seite(self, offset):
        t = self.h.t
        if not t or not self.tabelle_name:
            return
        offset = max(0, offset)
        s, tab, groesse, filt, sort = self.schema, self.tabelle_name, self.groesse.value(), self.filter.text(), self.sortierung
        self.status.setText("Lädt …")

        def lauf():
            meta = t.spalten(s, tab)
            erg = t.zeilen(s, tab, offset, groesse, sort, filt)
            erg.schliessen()
            return meta, erg, t.anzahl(s, tab, filt)
        arbeiter.starte(lauf, lambda d: self._daten_da(offset, d), lambda f: self.status.setText(f"Fehler: {f}"))

    def _daten_da(self, offset, daten):
        meta, erg, gesamt = daten
        self.offset, self.gesamt = offset, gesamt
        ist_view = self.tabelle_name not in self.h.editor.tabellen
        self.modell.setze_tabelle(meta, erg.zeilen, nur_lesen=self.h.t.schreibschutz or ist_view)
        self.tab_titel.setText(f"{self.schema}.{self.tabelle_name}")
        bis = offset + len(erg.zeilen)
        self.seite_text.setText(f"{offset + 1 if bis else 0}–{bis} von {gesamt:,}".replace(",", "."))
        self.zurueck.setEnabled(offset > 0)
        self.vor.setEnabled(bis < gesamt)
        hinweis = ""
        if self.h.t.schreibschutz:
            hinweis = "Schreibschutz an – nur lesen."
        elif not self.modell.pk and not ist_view:
            hinweis = "Kein Primärschlüssel – Bearbeiten im Raster ist aus (per SQL möglich)."
        self.status.setText(hinweis or f"{erg.dauer * 1000:.0f} ms")
        self.ansicht.resizeColumnsToContents()
        for c in range(self.modell.columnCount()):
            self.ansicht.setColumnWidth(c, min(max(self.ansicht.columnWidth(c), 70), 320))

    def _sortieren(self, spalte, richtung):
        if spalte < 0 or not self.modell.spalten:
            return
        self.sortierung = f"{self.h.t.zitiere(self.modell.spalten[spalte])} {'DESC' if richtung == Qt.DescendingOrder else 'ASC'}"
        self._seite(0)

    def _knoepfe(self, *_):
        bearbeitbar = not self.modell.nur_lesen
        self.k_neu.setEnabled(bearbeitbar)
        self.k_loeschen.setEnabled(bearbeitbar)
        self.k_uebernehmen.setEnabled(bearbeitbar and self.modell.geaendert)
        self.k_verwerfen.setEnabled(self.modell.geaendert)

    def _zeile_neu(self):
        r = self.modell.zeile_neu()
        self.ansicht.scrollToBottom()
        self.ansicht.edit(self.modell.index(r, 0))

    def _zeilen_loeschen(self):
        reihen = sorted({i.row() for i in self.ansicht.selectionModel().selectedIndexes()})
        if reihen:
            self.modell.zeilen_loeschen(reihen)
            self._knoepfe()

    def _verwerfen(self):
        self.modell.verwerfen()

    def _uebernehmen(self):
        t = self.h.t
        anweisungen = self.modell.aenderungs_sql(t, self.schema, self.tabelle_name)
        if not anweisungen:
            return
        geloescht = len(self.modell.geloescht)
        if geloescht and not rueckfrage(self, "Zeilen löschen", f"{geloescht} Zeile(n) endgültig löschen?", "Löschen"):
            return
        if self.h.cfg.get("farbe") == "#e05252" and not rueckfrage(
                self, "Produktive Verbindung", f"{len(anweisungen)} Änderung(en) auf einer als produktiv markierten Verbindung schreiben?", "Schreiben"):
            return

        def lauf():
            t.beginnen()
            try:
                for sql, werte in anweisungen:
                    t.abfrage(sql, werte)
                t.bestaetigen()
            except Exception:
                t.zuruecknehmen()
                raise
            return len(anweisungen)
        arbeiter.starte(lauf, lambda n: (self.status.setText(f"{n} Änderung(en) übernommen."), self._seite(self.offset)),
                        lambda f: meldung(self, "Nicht übernommen", f"Die Datenbank hat abgelehnt, nichts wurde geändert:\n{f}", True))

    def _als_sql(self):
        if self.tabelle_name:
            t = self.h.t
            wo = f" WHERE {self.filter.text()}" if self.filter.text().strip() else ""
            ob = f" ORDER BY {self.sortierung}" if self.sortierung else ""
            self.h.editor.neuer_tab(f"SELECT * FROM {t.voll(self.schema, self.tabelle_name)}{wo}{ob};")

    def _export(self, fmt):
        if not self.tabelle_name:
            return
        pfad, _ = QFileDialog.getSaveFileName(self, "Exportieren", f"{self.tabelle_name}.{fmt}", austausch.FORMATE[fmt])
        if not pfad:
            return
        t, s, tab, filt, sort = self.h.t, self.schema, self.tabelle_name, self.filter.text(), self.sortierung
        self.status.setText("Exportiere …")

        def lauf():
            sql = f"SELECT * FROM {t.voll(s, tab)}" + (f" WHERE {filt}" if filt.strip() else "") + (f" ORDER BY {sort}" if sort else "")
            erg = t.abfrage(sql, limit=5000)

            def alle():
                yield from erg.zeilen
                while erg.mehr:
                    erg.zeilen = []
                    yield from erg.weitere(5000)
            try:
                return austausch.exportieren(pfad, erg.spalten, alle(), fmt, tab, t.zitiere)
            finally:
                erg.schliessen()
        arbeiter.starte(lauf, lambda n: self.status.setText(f"{n:,} Zeilen exportiert.".replace(",", ".")),
                        lambda f: self.status.setText(f"Export fehlgeschlagen: {f}"))


