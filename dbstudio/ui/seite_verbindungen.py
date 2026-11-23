"""Verbindungen: Karten mit Farbmarkierung, anlegen/bearbeiten/testen/verbinden."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QLineEdit, QScrollArea, QVBoxLayout, QWidget)

from .. import treiber, verbindungen
from . import arbeiter
from .bausteine import Kopf, karte, knopf, label, leiste, rueckfrage, zeile
from .schalter import Schalter

SSL = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]


def beschreibung(v: dict) -> str:
    if v.get("art") in treiber.DATEI_ARTEN:
        return v.get("datei") or "im Speicher"
    ziel = f"{v.get('benutzer') + '@' if v.get('benutzer') else ''}{v.get('host') or 'localhost'}"
    if v.get("port"):
        ziel += f":{v['port']}"
    return ziel + (f" / {v['datenbank']}" if v.get("datenbank") else "")


class VerbindungDialog(QDialog):
    def __init__(self, eltern, v: dict):
        super().__init__(eltern)
        self.setWindowTitle("Verbindung")
        self.setMinimumWidth(520)
        self.v = dict(v)
        self.pw_geaendert = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        form = QFormLayout()
        form.setSpacing(9)
        self.name = QLineEdit(v.get("name", ""))
        self.art = QComboBox()
        for k, n in treiber.ARTEN.items():
            fehlt = treiber.verfuegbar(k)
            self.art.addItem(n + (f" – {fehlt}" if fehlt else ""), k)
        self.art.setCurrentIndex(max(0, self.art.findData(v.get("art", "postgresql"))))
        self.host, self.port = QLineEdit(v.get("host", "")), QLineEdit(str(v.get("port") or ""))
        self.db, self.benutzer = QLineEdit(v.get("datenbank", "")), QLineEdit(v.get("benutzer", ""))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("liegt im Schlüsselbund – leer lassen = unverändert" if verbindungen.passwort(v) else "Passwort")
        self.pw.textEdited.connect(lambda _: setattr(self, "pw_geaendert", True))
        self.ssl = QComboBox()
        self.ssl.addItems(SSL)
        self.ssl.setCurrentText(v.get("sslmode") or "prefer")
        self.datei = QLineEdit(v.get("datei", ""))
        wahl = knopf("Datei …", self._datei_waehlen)
        self.farbe = QComboBox()
        for k, n in verbindungen.FARBEN.items():
            self.farbe.addItem(n, k)
        self.farbe.setCurrentIndex(max(0, self.farbe.findData(v.get("farbe", ""))))
        self.schutz = Schalter("Schreibschutz (nur lesen)")
        self.schutz.setChecked(bool(v.get("schreibschutz")))
        form.addRow("Name", self.name)
        form.addRow("Art", self.art)
        self._zeilen_server = [("Host", self.host), ("Port", self.port), ("Datenbank", self.db),
                               ("Benutzer", self.benutzer), ("Passwort", self.pw), ("TLS (sslmode)", self.ssl)]
        for t, w in self._zeilen_server:
            form.addRow(t, w)
        self._datei_zeile = QWidget()
        h = QHBoxLayout(self._datei_zeile)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.datei)
        h.addWidget(wahl)
        form.addRow("Datei", self._datei_zeile)
        form.addRow("Markierung", self.farbe)
        form.addRow("", self.schutz)
        self.form = form
        lay.addLayout(form)
        self.status = label("", "gedimmt", True)
        lay.addWidget(self.status)
        lay.addLayout(zeile(knopf("Verbindung testen", self._testen, "zweit"), None,
                            knopf("Abbrechen", self.reject), knopf("Speichern", self._speichern, "primaer")))
        self.art.currentIndexChanged.connect(self._art_gewechselt)
        self._art_gewechselt()

    def _art_gewechselt(self):
        art = self.art.currentData()
        datei = art in treiber.DATEI_ARTEN
        for t, w in self._zeilen_server:
            self.form.setRowVisible(w, not datei)
        self.form.setRowVisible(self._datei_zeile, datei)
        if not self.port.text() or self.port.text() in {str(p) for p in treiber.STANDARD_PORT.values()}:
            self.port.setText(str(treiber.STANDARD_PORT.get(art, "")))
        fehlt = treiber.verfuegbar(art)
        self.status.setText(fehlt)

    def _datei_waehlen(self):
        pfad, _ = QFileDialog.getSaveFileName(self, "Datenbankdatei", self.datei.text(),
                                              "Datenbanken (*.db *.sqlite *.sqlite3 *.duckdb);;Alle (*)",
                                              options=QFileDialog.DontConfirmOverwrite)
        if pfad:
            self.datei.setText(pfad)

    def werte(self) -> dict:
        v = dict(self.v)
        v.update(name=self.name.text().strip() or beschreibung(v), art=self.art.currentData(), host=self.host.text().strip(),
                 port=self.port.text().strip(), datenbank=self.db.text().strip(), benutzer=self.benutzer.text().strip(),
                 sslmode=self.ssl.currentText(), datei=self.datei.text().strip(), farbe=self.farbe.currentData(),
                 schreibschutz=self.schutz.isChecked())
        if not self.name.text().strip():
            v["name"] = beschreibung(v)
        return v

    def passwort(self) -> str | None:
        return self.pw.text() if self.pw_geaendert else verbindungen.passwort(self.v)

    def _testen(self):
        v, pw = self.werte(), self.passwort()
        self.status.setObjectName("gedimmt")
        self.status.setText("Teste …")

        def lauf():
            t = treiber.oeffne(v, pw)
            try:
                return t.version()
            finally:
                t.schliessen()
        arbeiter.starte(lauf, lambda ver: self._status(f"Verbunden: {ver}", "okText"),
                        lambda f: self._status(f"Fehler: {f}", "fehlertext"))

    def _status(self, text, art):
        self.status.setObjectName(art)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)

    def _speichern(self):
        self.ergebnis = self.werte()
        if self.pw_geaendert:
            verbindungen.setze_passwort(self.ergebnis, self.pw.text() or None)
        self.accept()


class VerbindungenSeite(QWidget):
    verbinden = Signal(dict)

    def __init__(self):
        super().__init__()
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("Verbindungen", "PostgreSQL, MySQL/MariaDB, SQLite, DuckDB und SQL Server – Passwörter liegen im Schlüsselbund.")
        lay.addWidget(self.kopf)
        lay.addLayout(zeile(knopf("+ Neue Verbindung", self.neu, "primaer")))
        self.raster = QGridLayout()
        self.raster.setSpacing(14)
        innen = QWidget()
        innen.setObjectName("scrollinhalt")
        v = QVBoxLayout(innen)
        v.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self.raster)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(innen)
        lay.addWidget(scroll, 1)
        self.liste = verbindungen.laden()
        self.aktiv_id = ""
        self.zeichnen()

    def zeichnen(self):
        while self.raster.count():
            w = self.raster.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.liste:
            f, l = karte("Noch keine Verbindung")
            l.addWidget(label("Lege oben eine an. Für einen schnellen Test reicht SQLite oder DuckDB mit einer Datei.", "gedimmt", True))
            self.raster.addWidget(f, 0, 0)
        for i, v in enumerate(self.liste):
            self.raster.addWidget(self._karte(v), i // 2, i % 2)

    def _karte(self, v):
        f, l = karte()
        if v.get("farbe"):
            f.setStyleSheet(f"#karte {{ border-left: 4px solid {v['farbe']}; }}")
        kopfzeile = [label(v.get("name") or beschreibung(v), "karteTitel")]
        if v["id"] == self.aktiv_id:
            k = label("VERBUNDEN", "pillNeu")
            kopfzeile.append(k)
        l.addLayout(zeile(*kopfzeile))
        art = treiber.ARTEN.get(v.get("art"), v.get("art"))
        l.addWidget(label(f"{art} · {beschreibung(v)}" + (" · nur lesen" if v.get("schreibschutz") else ""), "gedimmt", True))
        vid = v["id"]
        l.addLayout(zeile(knopf("Verbinden", lambda: self.verbinden.emit(self._finde(vid)), "primaer"),
                          knopf("Bearbeiten", lambda: self.bearbeiten(vid)),
                          knopf("Löschen", lambda: self.loeschen(vid), "gefahr")))
        return f

    def _finde(self, vid):
        return next(v for v in self.liste if v["id"] == vid)

    def neu(self):
        d = VerbindungDialog(self, verbindungen.neu())
        if d.exec():
            self.liste.append(d.ergebnis)
            verbindungen.speichern(self.liste)
            self.zeichnen()

    def bearbeiten(self, vid):
        d = VerbindungDialog(self, self._finde(vid))
        if d.exec():
            self.liste = [d.ergebnis if v["id"] == vid else v for v in self.liste]
            verbindungen.speichern(self.liste)
            self.zeichnen()

    def loeschen(self, vid):
        v = self._finde(vid)
        if rueckfrage(self, "Verbindung löschen", f"„{v.get('name')}“ samt gespeichertem Passwort entfernen?\n"
                      "Die Datenbank selbst bleibt unberührt.", "Löschen"):
            self.liste = verbindungen.entfernen(self.liste, vid)
            verbindungen.speichern(self.liste)
            self.zeichnen()

    def markiere(self, vid: str):
        self.aktiv_id = vid
        self.zeichnen()
