"""Objektbaum (Schemas → Tabellen, Views, Indizes, Funktionen) und Datenraster mit Seiten, Filter, Bearbeiten."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHeaderView, QLineEdit, QMenu, QSpinBox, QSplitter, QTreeWidget,
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
        self.k_neue_db = knopf("＋ Datenbank", self.datenbank_neu)
        self.k_neue_db.setToolTip("Neue Datenbank auf diesem Server. Rechtsklick auf eine Datenbank: umbenennen, löschen, Eigenschaften.")
        self.k_neue_db.hide()
        lv.addLayout(zeile(knopf("Aktualisieren", self.neu_laden), self.k_neue_db, dehnen=False))
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
        self._laedt_schema = True
        self.h.editor.setze_schemas(list(zahlen))
        eltern = None
        try:
            darf = bool(dbs) and self.h.t.server_rechte()["createdb"] and not self.h.t.schreibschutz
        except Exception:
            darf = False
        self.k_neue_db.setVisible(darf)
        if dbs:  # PostgreSQL: Server oben, darunter alle Datenbanken, die aktuelle aufgeklappt
            cfg = self.h.cfg
            server = QTreeWidgetItem([f"🖥  {cfg.get('host') or 'localhost'}:{cfg.get('port') or 5432}"])
            server.setData(0, ROLLE, ("server",))
            server.setToolTip(0, f"{cfg.get('_version', '')} · angemeldet als {cfg.get('benutzer', '')} · Rechtsklick: neue Datenbank")
            self.baum.addTopLevelItem(server)
            for d in dbs:
                di = QTreeWidgetItem([f"🗄  {d}" + ("   ●" if d == aktuell else "")])
                di.setData(0, ROLLE, ("datenbank", d))
                server.addChild(di)
                if d == aktuell:
                    eltern = di
                    di.setToolTip(0, "Aktuelle Datenbank")
                else:
                    di.addChild(QTreeWidgetItem(["lädt …"]))
            server.setExpanded(True)
        for s, n in zahlen.items():
            item = QTreeWidgetItem([f"{s}  ({n})"])
            item.setData(0, ROLLE, ("schema", s))
            item.setToolTip(0, f"{s}: {n} Tabelle{'n' if n != 1 else ''}")
            item.addChild(QTreeWidgetItem(["lädt …"]))
            if eltern is not None:
                eltern.addChild(item)
            else:
                self.baum.addTopLevelItem(item)
            if s == std:
                self._objekte_da(item, objekte)
                item.setExpanded(True)
                self.baum.setCurrentItem(item)
        if eltern is not None:
            eltern.setExpanded(True)
        self._laedt_schema = False
        self.status.setText(hinweis)
        self.h.schema_gewaehlt(std, objekte, merken=False)

    def _aufgeklappt(self, item):
        art = item.data(0, ROLLE)
        if art and art[0] in ("datenbank", "fschema") and not getattr(self, "_laedt_schema", False):
            return self._fremd_aufgeklappt(item, art)
        if not art or art[0] != "schema" or getattr(self, "_laedt_schema", False):
            return
        t, s = self.h.t, art[1]
        geladen = not (item.childCount() == 1 and not item.child(0).data(0, ROLLE))

        def da(o):
            if not geladen:
                self._objekte_da(item, o)
            self.h.schema_gewaehlt(s, o)
        arbeiter.starte(lambda: t.objekte(s), da, lambda f: self.status.setText(f"Fehler: {f}"))

    # --- Andere Datenbanken desselben Servers (nur lesen; Öffnen wechselt die Verbindung) -----------------------------
    def _fremd_aufgeklappt(self, item, art):
        if not (item.childCount() == 1 and not item.child(0).data(0, ROLLE)):
            return  # schon geladen
        db = art[1]
        if art[0] == "datenbank":
            def lauf():
                t = self.h.nebenverbindung(db)
                return t.tabellen_zahlen()

            def da(zahlen):
                item.takeChildren()
                for s_, n in zahlen.items():
                    c = QTreeWidgetItem([f"{s_}  ({n})"])
                    c.setData(0, ROLLE, ("fschema", db, s_))
                    c.addChild(QTreeWidgetItem(["lädt …"]))
                    item.addChild(c)
                if not zahlen:
                    item.addChild(QTreeWidgetItem(["(leer)"]))
        else:
            s_ = art[2]

            def lauf():
                return self.h.nebenverbindung(db).objekte(s_)

            def da(objekte):
                item.takeChildren()
                for schluessel, name in GRUPPEN:
                    namen = objekte.get(schluessel, [])
                    g = QTreeWidgetItem([f"{name}  ({len(namen)})"])
                    g.setData(0, ROLLE, ("fgruppe", db, s_, schluessel))
                    for n in namen:
                        c = QTreeWidgetItem([n])
                        c.setData(0, ROLLE, ("f" + schluessel, db, s_, n))
                        g.addChild(c)
                    item.addChild(g)
                    if schluessel == "tabellen":
                        g.setExpanded(True)
                self._filtern(self.suche.text())
        arbeiter.starte(lauf, da, lambda f: (item.takeChildren(), item.addChild(QTreeWidgetItem([f"Fehler: {f}"]))))

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
        """Filtert die Objekte in allen Gruppen (auch unter Server/Datenbank), Gruppen mit Treffern klappen auf."""
        text = text.lower().strip()

        def gruppen(item):
            art = item.data(0, ROLLE)
            if art and art[0] in ("gruppe", "fgruppe"):
                yield item
            for j in range(item.childCount()):
                yield from gruppen(item.child(j))
        for i in range(self.baum.topLevelItemCount()):
            for gruppe in gruppen(self.baum.topLevelItem(i)):
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
        elif art and art[0] in ("ftabellen", "fviews"):
            self.h.datenbank_wechseln(art[1], (art[2], art[3]))
        elif art and art[0] == "datenbank" and item.childCount() and not item.text(0).endswith("●"):
            pass  # Aufklappen genügt; Wechseln per Kontextmenü

    def _kontextmenue(self, punkt):
        item = self.baum.itemAt(punkt)
        art = item.data(0, ROLLE) if item else None
        if art and art[0] in ("server", "datenbank"):
            return self._server_menue(art, punkt)
        if art and art[0] in ("ftabellen", "fviews"):
            m = QMenu(self)
            m.addAction("Öffnen (wechselt in diese Datenbank)", lambda: self.h.datenbank_wechseln(art[1], (art[2], art[3])))
            m.exec(self.baum.viewport().mapToGlobal(punkt))
            return
        if art and art[0] in ("schema", "gruppe"):
            m = QMenu(self)
            m.addAction("✨ Vorlage einspielen …", self.vorlage_einspielen).setEnabled(not self.h.t.schreibschutz)
            m.addAction("Aktualisieren", self.neu_laden)
            m.exec(self.baum.viewport().mapToGlobal(punkt))
            return
        if not art or art[0] not in ("tabellen", "views"):
            return
        m = QMenu(self)
        m.addAction("Öffnen", lambda: self.oeffnen(art[1], art[2]))
        m.addAction("SELECT im Editor", lambda: self.h.editor.neuer_tab(
            f"SELECT * FROM {self.h.t.voll(art[1], art[2])} LIMIT 100;" if self.h.t.art != "mssql"
            else f"SELECT TOP 100 * FROM {self.h.t.voll(art[1], art[2])};"))
        m.addAction("In andere Verbindung kopieren …", lambda: self.h.austausch.kopieren_vorbelegen(art[1], art[2]))
        m.exec(self.baum.viewport().mapToGlobal(punkt))

    # --- Server: Datenbanken anlegen, umbenennen, löschen ----------------------------------------------------------
    def _server_menue(self, art, punkt):
        t = self.h.t
        try:
            rechte = t.server_rechte()
        except Exception:
            rechte = {"createdb": False, "superuser": False}
        m = QMenu(self)
        a = m.addAction("＋ Neue Datenbank …", self.datenbank_neu)
        a.setEnabled(rechte["createdb"] and not t.schreibschutz)
        if art[0] == "datenbank":
            db = art[1]
            m.addSeparator()
            if db != self.h.cfg.get("datenbank"):
                m.addAction("Hierhin wechseln", lambda: self.h.datenbank_wechseln(db))
            m.addAction("Eigenschaften …", lambda: self.datenbank_eigenschaften(db))
            for text, f in (("Umbenennen …", lambda: self.datenbank_umbenennen(db)), ("🗑 Löschen …", lambda: self.datenbank_loeschen(db))):
                a = m.addAction(text, f)
                a.setEnabled(rechte["createdb"] and not t.schreibschutz and db not in ("postgres", "template0", "template1"))
        m.addSeparator()
        m.addAction("Aktualisieren", self.neu_laden)
        m.exec(self.baum.viewport().mapToGlobal(punkt))

    def datenbank_neu(self):
        """Neue Datenbank mit Vorlage oder KI-Entwurf: anlegen, Schema einspielen, hinwechseln."""
        from .dialog_vorlage import VorlagenDialog
        t = self.h.t
        try:
            rollen = t.rollen()
        except Exception:
            rollen = []
        d = VorlagenDialog(self, t.art, neu=True, rollen=rollen, benutzer=self.h.cfg.get("benutzer", ""))
        if not d.exec():
            return
        name, besitzer, anweisungen = d.ergebnis()

        def lauf():
            t.datenbank_anlegen(name, besitzer)
            if anweisungen:
                from .. import vorlagen
                neben = self.h.nebenverbindung(name)
                if besitzer:  # Tabellen sollen der Besitzer-Rolle gehören, nicht dem Admin
                    neben.abfrage(f"SET ROLE {neben.zitiere(besitzer)}")
                vorlagen.einspielen(neben, anweisungen)
            return len(anweisungen)

        def da(n):
            self.h.nebenverbindungen_schliessen()
            self.status.setText(f"Datenbank {name} angelegt" + (f", {n} Anweisungen eingespielt" if n else ""))
            self.h.datenbank_wechseln(name)
        self.status.setText(f"Lege {name} an …")
        arbeiter.starte(lauf, da, lambda f: meldung(self, "Neue Datenbank", f"{f}\n\nFalls die Datenbank schon angelegt wurde, "
                                                                       "steht sie leer im Baum.", True))

    def vorlage_einspielen(self):
        """Vorlage oder KI-Entwurf in die aktuelle Datenbank (alle Datenbankarten, z. B. SQLite)."""
        from .. import vorlagen
        from .dialog_vorlage import VorlagenDialog
        t = self.h.t
        if t is None:
            return
        d = VorlagenDialog(self, t.art, neu=False)
        if not d.exec():
            return
        _, _, anweisungen = d.ergebnis()
        arbeiter.starte(lambda: vorlagen.einspielen(t, anweisungen),
                        lambda n: (self.status.setText(f"{n} Anweisungen eingespielt"), self.neu_laden()),
                        lambda f: meldung(self, "Vorlage einspielen", f"{f}\n\nNichts wurde übernommen (Transaktion zurückgenommen)."
                                          if t.art != "mysql" else str(f), True))

    def datenbank_eigenschaften(self, db):
        t = self.h.t

        def da(i):
            meldung(self, f"Datenbank {db}", f"Besitzer: {i['besitzer']}\nGröße: {i['groesse']}\nKodierung: {i['kodierung']}\n"
                                             f"Sortierung: {i['sortierung']}\nAndere offene Verbindungen: {i['verbindungen']}")
        arbeiter.starte(lambda: t.datenbank_info(db), da, lambda f: meldung(self, "Eigenschaften", f, True))

    def _ausweichen(self, db, weiter):
        """Die eigene Datenbank lässt sich nicht umbenennen oder löschen: vorher nach „postgres“ wechseln."""
        if db == self.h.cfg.get("datenbank"):
            self.h.datenbank_wechseln("postgres", nach=weiter)
        else:
            weiter()

    def datenbank_umbenennen(self, db):
        from PySide6.QtWidgets import QInputDialog
        neu, ok = QInputDialog.getText(self, "Datenbank umbenennen", f"Neuer Name für „{db}“:", text=db)
        if not ok or not neu.strip() or neu.strip() == db:
            return

        def los():
            arbeiter.starte(lambda: self.h.t.datenbank_umbenennen(db, neu),
                            lambda sql: (self.status.setText(f"Umbenannt: {sql}"), self.neu_laden()),
                            lambda f: meldung(self, "Umbenennen", f + "\n\nHinweis: Umbenennen geht nur, wenn niemand mit der "
                                                                     "Datenbank verbunden ist.", True))
        self.h.nebenverbindungen_schliessen()
        self._ausweichen(db, los)

    def datenbank_loeschen(self, db):
        """Folgen-Analyse vor dem Löschen: Größe, Tabellen, offene Verbindungen; Bestätigung durch Eintippen des Namens."""
        from PySide6.QtWidgets import QInputDialog

        def lauf():
            info = self.h.t.datenbank_info(db)
            try:
                info["tabellen"] = sum(self.h.nebenverbindung(db).tabellen_zahlen().values())
            except Exception:
                info["tabellen"] = None
            return info

        def da(i):
            tab = "unbekannt" if i["tabellen"] is None else str(i["tabellen"])
            text = (f"Das löscht die Datenbank „{db}“ endgültig, mit allem darin:\n\n"
                    f"• Größe: {i['groesse']}\n• Tabellen: {tab}\n• Besitzer: {i['besitzer']}\n"
                    f"• Andere offene Verbindungen: {i['verbindungen']}" +
                    ("  – die werden getrennt" if i["verbindungen"] else "") +
                    "\n\nZum Bestätigen den Namen eintippen:")
            antwort, ok = QInputDialog.getText(self, "Datenbank löschen", text)
            if not ok:
                return
            if antwort.strip() != db:
                return meldung(self, "Datenbank löschen", "Name stimmt nicht überein – nichts gelöscht.", True)
            self.h.nebenverbindungen_schliessen()

            def los():
                arbeiter.starte(lambda: self.h.t.datenbank_loeschen(db, erzwingen=bool(i["verbindungen"])),
                                lambda sql: (self.status.setText(f"Gelöscht: {sql}"), self.neu_laden()),
                                lambda f: meldung(self, "Datenbank löschen", f, True))
            self._ausweichen(db, los)
        arbeiter.starte(lauf, da, lambda f: meldung(self, "Datenbank löschen", f, True))

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


