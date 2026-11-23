"""Import aus CSV/JSON/Excel mit Spaltenzuordnung und Vorschau; Tabelle in eine andere Verbindung kopieren."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QTableWidget,
                               QTableWidgetItem, QWidget)

from .. import austausch, treiber, verbindungen
from . import arbeiter
from .bausteine import Kopf, karte, knopf, label, leiste, meldung, rueckfrage, tabelle, zeile
from .raster import ErgebnisModell
from .schalter import Schalter


class AustauschSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        self.quell_spalten, self.quell_zeilen, self.pfad = [], [], ""
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("Import & Kopieren", "CSV, JSON und Excel einlesen · Tabellen zwischen Datenbanken kopieren (Typen werden umgesetzt)")
        lay.addWidget(self.kopf)
        reihe = QHBoxLayout()
        reihe.setSpacing(14)
        reihe.addWidget(self._import_karte(), 3)
        reihe.addWidget(self._kopier_karte(), 2)
        lay.addLayout(reihe, 1)

    # --- Import -------------------------------------------------------------------------------------------------
    def _import_karte(self):
        f, l = karte("Import in die aktive Verbindung")
        self.datei = label("Keine Datei gewählt", "gedimmt")
        l.addLayout(zeile(knopf("Datei wählen …", self._datei, "zweit"), self.datei))
        self.vorschau_modell = ErgebnisModell(self)
        self.vorschau = tabelle()
        self.vorschau.setModel(self.vorschau_modell)
        self.vorschau.setMaximumHeight(200)
        l.addWidget(label("Vorschau (erste 50 Zeilen)", "gedimmt"))
        l.addWidget(self.vorschau)
        self.zuordnung = QTableWidget(0, 2)
        self.zuordnung.setHorizontalHeaderLabels(["Spalte in der Datei", "Zielspalte (leer = auslassen)"])
        self.zuordnung.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.zuordnung.verticalHeader().hide()
        l.addWidget(self.zuordnung, 1)
        self.ziel_schema = QComboBox()
        self.ziel_tabelle = QComboBox()
        self.ziel_tabelle.setEditable(True)
        self.ziel_tabelle.setMinimumWidth(200)
        self.ziel_schema.currentTextChanged.connect(self._tabellen_laden)
        self.ziel_tabelle.currentTextChanged.connect(self._ziel_gewechselt)
        self.neu_anlegen = Schalter("Neue Tabelle anlegen (Typen aus den Daten)")
        l.addLayout(zeile(label("Ziel"), self.ziel_schema, self.ziel_tabelle, self.neu_anlegen))
        self.import_status = label("", "gedimmt", True)
        l.addLayout(zeile(knopf("Importieren", self._importieren, "primaer"), self.import_status))
        return f

    def verbindung_gewechselt(self):
        self.ziel_schema.clear()
        t = self.h.t
        if not t:
            return
        arbeiter.starte(lambda: (t.schemas(), t.standard_schema()), self._schemas_da)
        self.quelle_schema_laden()

    def _schemas_da(self, d):
        schemas, std = d
        self.ziel_schema.blockSignals(True)
        self.ziel_schema.clear()
        self.ziel_schema.addItems(schemas)
        self.ziel_schema.setCurrentText(std)
        self.ziel_schema.blockSignals(False)
        self._tabellen_laden(std)
        self.q_schema.blockSignals(True)
        self.q_schema.clear()
        self.q_schema.addItems(schemas)
        self.q_schema.setCurrentText(std)
        self.q_schema.blockSignals(False)
        self._q_tabellen(std)

    def _tabellen_laden(self, schema):
        t = self.h.t
        if not t or not schema:
            return
        arbeiter.starte(lambda: t.objekte(schema)["tabellen"], self._tabellen_da)

    def _tabellen_da(self, namen):
        text = self.ziel_tabelle.currentText()
        self.ziel_tabelle.blockSignals(True)
        self.ziel_tabelle.clear()
        self.ziel_tabelle.addItems(namen)
        self.ziel_tabelle.setEditText(text)
        self.ziel_tabelle.blockSignals(False)
        self._ziel_gewechselt(text)

    def _datei(self):
        pfad, _ = QFileDialog.getOpenFileName(self, "Datei importieren", "", "Daten (*.csv *.json *.jsonl *.xlsx);;Alle (*)")
        if not pfad:
            return
        self.pfad = pfad
        self.datei.setText(pfad)
        self.import_status.setText("Lese Datei …")
        arbeiter.starte(lambda: austausch.lesen(pfad), self._gelesen, lambda f: self.import_status.setText(f"Fehler: {f}"))

    def _gelesen(self, d):
        self.quell_spalten, self.quell_zeilen = d
        self.vorschau_modell.setze(self.quell_spalten, [tuple(z) for z in self.quell_zeilen[:50]])
        self.import_status.setText(f"{len(self.quell_zeilen):,} Zeilen, {len(self.quell_spalten)} Spalten.".replace(",", "."))
        if not self.ziel_tabelle.currentText():
            from pathlib import Path
            self.ziel_tabelle.setEditText(Path(self.pfad).stem.lower().replace(" ", "_").replace("-", "_"))
        self._ziel_gewechselt(self.ziel_tabelle.currentText())

    def _ziel_gewechselt(self, name):
        t = self.h.t
        vorhanden = self.ziel_tabelle.findText(name) >= 0
        self.neu_anlegen.setChecked(not vorhanden)
        if vorhanden and t:
            schema = self.ziel_schema.currentText()
            arbeiter.starte(lambda: [s.name for s in t.spalten(schema, name)], self._zuordnung_fuellen)
        else:
            self._zuordnung_fuellen(None)

    def _zuordnung_fuellen(self, ziel_spalten):
        self.zuordnung.setRowCount(len(self.quell_spalten))
        for r, q in enumerate(self.quell_spalten):
            self.zuordnung.setItem(r, 0, QTableWidgetItem(q))
            box = QComboBox()
            box.setEditable(ziel_spalten is None)
            box.addItem("")
            if ziel_spalten is None:
                box.setEditText(q.strip().lower().replace(" ", "_"))
            else:
                box.addItems(ziel_spalten)
                treffer = next((z for z in ziel_spalten if z.lower() == q.strip().lower()), "")
                box.setCurrentText(treffer)
            self.zuordnung.setCellWidget(r, 1, box)

    def _importieren(self):
        t = self.h.t
        if not t or not self.quell_spalten:
            meldung(self, "Import", "Verbindung und Datei wählen.")
            return
        if t.schreibschutz:
            meldung(self, "Schreibschutz", "Diese Verbindung ist schreibgeschützt.", True)
            return
        zuordnung = {self.zuordnung.item(r, 0).text(): self.zuordnung.cellWidget(r, 1).currentText().strip()
                     for r in range(self.zuordnung.rowCount())}
        schema, tab, neu = self.ziel_schema.currentText() or None, self.ziel_tabelle.currentText().strip(), self.neu_anlegen.isChecked()
        if not tab:
            meldung(self, "Import", "Zieltabelle angeben.")
            return
        if not rueckfrage(self, "Importieren", f"{len(self.quell_zeilen):,} Zeilen nach „{tab}“ schreiben{' (neue Tabelle)' if neu else ''}?".replace(",", "."), "Importieren"):
            return
        spalten, zeilen = self.quell_spalten, self.quell_zeilen
        self.import_status.setText("Importiere …")
        arbeiter.starte(lambda: austausch.importieren(t, schema, tab, spalten, zeilen, zuordnung, neu),
                        lambda n: (self.import_status.setText(f"{n:,} Zeilen importiert.".replace(",", ".")), self.h.explorer.neu_laden()),
                        lambda f: self.import_status.setText(f"Nicht importiert (zurückgerollt): {f}"))

    # --- Kopieren -----------------------------------------------------------------------------------------------
    def _kopier_karte(self):
        f, l = karte("Tabelle in andere Verbindung kopieren")
        l.addWidget(label("Quelle ist die aktive Verbindung. Spaltentypen werden auf das Zielsystem abgebildet "
                          "(z. B. SQLite → PostgreSQL), Zeilen in Stapeln und als eine Transaktion geschrieben.", "gedimmt", True))
        self.q_schema, self.q_tabelle = QComboBox(), QComboBox()
        self.q_schema.currentTextChanged.connect(self._q_tabellen)
        self.q_tabelle.currentTextChanged.connect(lambda n: self.z_name.setText(n))
        l.addLayout(zeile(label("Quelle"), self.q_schema, self.q_tabelle))
        self.z_verbindung = QComboBox()
        self.z_schema, self.z_name = QLineEdit(), QLineEdit()
        self.z_schema.setPlaceholderText("Schema (leer = Standard)")
        self.z_name.setPlaceholderText("Name im Ziel")
        l.addLayout(zeile(label("Ziel"), self.z_verbindung))
        l.addLayout(zeile(self.z_schema, self.z_name))
        self.ersetzen = Schalter("Vorhandene Tabelle im Ziel ersetzen")
        l.addWidget(self.ersetzen)
        self.kopier_status = label("", "gedimmt", True)
        l.addLayout(zeile(knopf("Kopieren", self._kopieren, "primaer"), self.kopier_status))
        l.addStretch(1)
        return f

    def ziele_auffuellen(self):
        self.z_verbindung.clear()
        for v in self.h.verbindungen.liste:
            self.z_verbindung.addItem(f"{v.get('name')} ({treiber.ARTEN.get(v.get('art'), '')})", v["id"])

    def quelle_schema_laden(self):
        self.ziele_auffuellen()

    def _q_tabellen(self, schema):
        t = self.h.t
        if t and schema:
            arbeiter.starte(lambda: t.objekte(schema)["tabellen"], lambda n: (self.q_tabelle.clear(), self.q_tabelle.addItems(n)))

    def kopieren_vorbelegen(self, schema, tabelle):
        self.q_schema.setCurrentText(schema)
        self.h.zeige(self)
        arbeiter.starte(lambda: self.h.t.objekte(schema)["tabellen"],
                        lambda n: (self.q_tabelle.clear(), self.q_tabelle.addItems(n), self.q_tabelle.setCurrentText(tabelle)))

    def _kopieren(self):
        quelle = self.h.t
        vid = self.z_verbindung.currentData()
        if not quelle or not vid or not self.q_tabelle.currentText():
            meldung(self, "Kopieren", "Quelle und Ziel wählen.")
            return
        ziel_cfg = next(v for v in self.h.verbindungen.liste if v["id"] == vid)
        if ziel_cfg.get("schreibschutz"):
            meldung(self, "Schreibschutz", "Die Zielverbindung ist schreibgeschützt.", True)
            return
        qs, qt, zs, zn, ers = (self.q_schema.currentText(), self.q_tabelle.currentText(), self.z_schema.text().strip() or None,
                               self.z_name.text().strip() or self.q_tabelle.currentText(), self.ersetzen.isChecked())
        if ers and not rueckfrage(self, "Ersetzen", f"„{zn}“ im Ziel wird gelöscht und neu angelegt.", "Ersetzen"):
            return
        pw = verbindungen.passwort(ziel_cfg)
        self.kopier_status.setText("Kopiere …")

        def lauf():
            if ziel_cfg["id"] == self.h.cfg.get("id"):
                return austausch.tabelle_kopieren(quelle, qs, qt, quelle, zs, zn, ers)
            ziel = treiber.oeffne(ziel_cfg, pw)
            try:
                return austausch.tabelle_kopieren(quelle, qs, qt, ziel, zs, zn, ers)
            finally:
                ziel.schliessen()
        arbeiter.starte(lauf, lambda n: self.kopier_status.setText(f"{n:,} Zeilen kopiert.".replace(",", ".")),
                        lambda f: self.kopier_status.setText(f"Fehler: {f}"))


