"""Server: Administration wie in der MySQL Workbench, im Look von Pi DB Studio.

Status · Client-Verbindungen · Benutzer und Rechte · Variablen · Sicherung – für PostgreSQL und MySQL/MariaDB.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QInputDialog, QLineEdit, QTabWidget, QVBoxLayout, QWidget)

from .. import server, verbindungen
from . import arbeiter
from .bausteine import Kopf, karte, knopf, label, leiste, meldung, rueckfrage, tabelle, zeile
from .raster import ErgebnisModell


def _raster(suche: bool = True):
    """Ergebnisraster mit Suchfeld (filtert über alle Spalten)."""
    modell = ErgebnisModell()
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(modell)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    ansicht = tabelle()
    ansicht.setModel(proxy)
    ansicht.setSortingEnabled(True)
    ansicht.sortByColumn(-1, Qt.AscendingOrder)           # zuerst die Reihenfolge des Servers
    ansicht.horizontalHeader().setStretchLastSection(True)
    feld = None
    if suche:
        feld = QLineEdit()
        feld.setPlaceholderText("Suchen …")
        feld.setClearButtonEnabled(True)
        feld.textChanged.connect(proxy.setFilterFixedString)
    return modell, proxy, ansicht, feld


def _ja(w) -> str:
    return "✓" if w is True else ("" if w is False else str(w if w is not None else ""))


class RolleDialog(QDialog):
    def __init__(self, eltern, art: str, name: str = "", rechte: dict | None = None, neu: bool = True):
        super().__init__(eltern)
        self.setWindowTitle("Neue Rolle" if neu else f"Rolle {name}")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setReadOnly(not neu)
        self.name.setPlaceholderText("z. B. app_leser" if art == "postgresql" else "benutzer@host  (ohne @host: alle Hosts)")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Passwort" if neu else "leer = unverändert")
        form.addRow("Name", self.name)
        form.addRow("Passwort", self.pw)
        self.schalter = {}
        if art == "postgresql":
            for k, text in (("login", "Darf sich anmelden (LOGIN)"), ("createdb", "Datenbanken anlegen"),
                            ("createrole", "Rollen anlegen"), ("superuser", "Superuser (darf alles)")):
                c = QCheckBox(text)
                c.setChecked(bool((rechte or {"login": True}).get(k)))
                self.schalter[k] = c
                form.addRow("", c)
        lay.addLayout(form)
        if art == "postgresql":
            lay.addWidget(label("Das Passwort wird als SCRAM-Verifier gesendet – im Klartext erreicht es den Server nicht.", "gedimmt", True))
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self.accept)
        knoepfe.rejected.connect(self.reject)
        lay.addWidget(knoepfe)

    def werte(self) -> tuple[str, str, dict]:
        return self.name.text().strip(), self.pw.text(), {k: c.isChecked() for k, c in self.schalter.items()}


class ServerSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("Server", "Status, Verbindungen, Benutzer und Rechte, Variablen und Sicherung – PostgreSQL und MySQL/MariaDB.")
        lay.addWidget(self.kopf)
        self.hinweis = label("Mit einem PostgreSQL- oder MySQL/MariaDB-Server verbinden, dann erscheint hier die Verwaltung.", "gedimmt", True)
        lay.addWidget(self.hinweis)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._status_tab()
        self._verbindungen_tab()
        self._benutzer_tab()
        self._variablen_tab()
        self._sicherung_tab()
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(lambda: self.tabs.currentIndex() == 1 and self.auto.isChecked() and self.lade_verbindungen())
        self.timer.start()
        self.tabs.currentChanged.connect(lambda _: self.aktualisieren())
        self.verbindung_gewechselt()

    # --- Rahmen
    def verbindung_gewechselt(self):
        ok = server.unterstuetzt(self.h.t)
        self.tabs.setVisible(ok)
        self.hinweis.setVisible(not ok)
        if ok:
            self.kopf.status(self.h.status_text(), "pillWarn" if self.h.t.schreibschutz else "pill")
            self.aktualisieren()

    def showEvent(self, e):
        super().showEvent(e)
        self.verbindung_gewechselt()

    def aktualisieren(self):
        if not server.unterstuetzt(self.h.t) or not self.isVisible():
            return
        [self.lade_status, self.lade_verbindungen, self.lade_benutzer, self.lade_variablen, self.lade_sicherung][self.tabs.currentIndex()]()

    def _fehler(self, f):
        meldung(self, "Server", str(f), True)

    # --- Status
    def _status_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.kacheln = QGridLayout()
        self.kacheln.setSpacing(12)
        v.addLayout(self.kacheln)
        f, l = karte("Datenbanken nach Größe")
        self.groessen, _, ansicht, _ = _raster(False)
        l.addWidget(ansicht)
        v.addWidget(f, 1)
        v.addLayout(zeile(knopf("Aktualisieren", self.lade_status)))
        self.tabs.addTab(w, "Status")

    def lade_status(self):
        t = self.h.t

        def da(st):
            while self.kacheln.count():
                x = self.kacheln.takeAt(0).widget()
                if x:
                    x.deleteLater()
            for i, (titel, wert, unter) in enumerate(st["kennzahlen"]):
                f, l = karte(rand=12)
                l.addWidget(label(titel, "gedimmt"))
                l.addWidget(label(str(wert), "karteTitel", True))
                if unter:
                    l.addWidget(label(unter, "gedimmt"))
                self.kacheln.addWidget(f, i // 4, i % 4)
            sp, zeilen = st["groessen"]
            self.groessen.setze([s for s in sp if s != "Bytes"], [tuple(z[:3]) + tuple(z[4:]) for z in zeilen])
        arbeiter.starte(lambda: server.status(t), da, self._fehler)

    # --- Client-Verbindungen
    def _verbindungen_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.verb, self.verb_proxy, self.verb_ansicht, suche = _raster()
        self.auto = QCheckBox("alle 5 s aktualisieren")
        self.auto.setChecked(True)
        v.addLayout(zeile(suche, self.auto, knopf("Aktualisieren", self.lade_verbindungen), dehnen=False))
        v.addWidget(self.verb_ansicht, 1)
        self.k_abbrechen = knopf("Abfrage abbrechen", lambda: self._verb_aktion("abbrechen"))
        self.k_trennen = knopf("Verbindung trennen", lambda: self._verb_aktion("trennen"), "gefahr")
        self.verb_info = label("", "gedimmt")
        v.addLayout(zeile(self.k_abbrechen, self.k_trennen, self.verb_info))
        self.tabs.addTab(w, "Client-Verbindungen")

    def lade_verbindungen(self):
        t = self.h.t
        if t is None:
            return

        def da(r):
            sp, zeilen = r
            self.verb.setze(sp[:-1], [tuple(z[:-1]) for z in zeilen])
            self._eigene = {z[0] for z in zeilen if z[-1]}
            aktiv = sum(1 for z in zeilen if str(z[5]).lower() in ("active", "query", "execute"))
            self.verb_info.setText(f"{len(zeilen)} Verbindungen, {aktiv} aktiv")
        arbeiter.starte(lambda: server.verbindungen(t), da, lambda f: self.verb_info.setText(f"Fehler: {f}"))

    def _gewaehlte_pid(self):
        i = self.verb_ansicht.currentIndex()
        if not i.isValid():
            meldung(self, "Verbindungen", "Bitte erst eine Verbindung in der Liste wählen.")
            return None
        return self.verb.zeilen[self.verb_proxy.mapToSource(i).row()][0]

    def _verb_aktion(self, art):
        pid = self._gewaehlte_pid()
        if pid is None:
            return
        if pid in getattr(self, "_eigene", set()):
            return meldung(self, "Verbindungen", "Das ist die Verbindung von Pi DB Studio selbst.", True)
        if art == "trennen" and not rueckfrage(self, "Verbindung trennen", f"Verbindung {pid} trennen? Offene Transaktionen werden zurückgenommen.", "Trennen"):
            return
        f = server.abfrage_abbrechen if art == "abbrechen" else server.verbindung_trennen
        arbeiter.starte(lambda: f(self.h.t, pid), lambda sql: (self.verb_info.setText(sql), self.lade_verbindungen()), self._fehler)

    # --- Benutzer und Rechte
    def _benutzer_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.ben, self.ben_proxy, self.ben_ansicht, suche = _raster()
        self.ben_ansicht.doubleClicked.connect(lambda _: self.rolle_bearbeiten())
        v.addLayout(zeile(suche, knopf("Aktualisieren", self.lade_benutzer), dehnen=False))
        v.addWidget(self.ben_ansicht, 1)
        self.ben_info = label("", "gedimmt")
        v.addLayout(zeile(knopf("＋ Neue Rolle", self.rolle_neu, "primaer"), knopf("Bearbeiten …", self.rolle_bearbeiten),
                          knopf("Passwort setzen …", self.rolle_passwort), knopf("Zugriff auf Datenbank …", self.rolle_zugriff),
                          knopf("Löschen …", self.rolle_loeschen, "gefahr"), self.ben_info))
        self.tabs.addTab(w, "Benutzer und Rechte")

    def lade_benutzer(self):
        t = self.h.t

        def da(r):
            sp, zeilen = r
            self.ben.setze(sp, [tuple(("unbegrenzt" if i == 6 and x in (-1, 0) else _ja(x)) for i, x in enumerate(z)) for z in zeilen])
            self._rollen_roh = {z[0]: z for z in zeilen}
            self.ben_info.setText(f"{len(zeilen)} Rollen")
        arbeiter.starte(lambda: server.benutzer(t), da, self._fehler)

    def _gewaehlte_rolle(self):
        i = self.ben_ansicht.currentIndex()
        if not i.isValid():
            meldung(self, "Benutzer", "Bitte erst eine Rolle in der Liste wählen.")
            return None
        return self.ben.zeilen[self.ben_proxy.mapToSource(i).row()][0]

    def _erledigt(self, sql):
        self.ben_info.setText(sql)
        self.lade_benutzer()

    def rolle_neu(self):
        d = RolleDialog(self, self.h.t.art)
        if d.exec():
            name, pw, rechte = d.werte()
            arbeiter.starte(lambda: server.benutzer_anlegen(self.h.t, name, pw, rechte), self._erledigt, self._fehler)

    def rolle_bearbeiten(self):
        name = self._gewaehlte_rolle()
        if not name:
            return
        if self.h.t.art != "postgresql":
            return self.rolle_passwort()
        z = self._rollen_roh.get(name)
        rechte = {"login": z[1], "superuser": z[2], "createdb": z[3], "createrole": z[4]} if z else {}
        d = RolleDialog(self, "postgresql", name, rechte, neu=False)
        if d.exec():
            _, pw, rechte = d.werte()

            def lauf():
                sql = server.benutzer_aendern(self.h.t, name, rechte)
                return sql + ("; " + server.passwort_setzen(self.h.t, name, pw) if pw else "")
            arbeiter.starte(lauf, self._erledigt, self._fehler)

    def rolle_passwort(self):
        name = self._gewaehlte_rolle()
        if not name:
            return
        pw, ok = QInputDialog.getText(self, "Passwort setzen", f"Neues Passwort für {name}:", QLineEdit.Password)
        if ok and pw:
            arbeiter.starte(lambda: server.passwort_setzen(self.h.t, name, pw), self._erledigt, self._fehler)

    def rolle_zugriff(self):
        name = self._gewaehlte_rolle()
        if not name:
            return
        try:
            dbs = self.h.t.datenbanken() or [d for d, *_ in server.status(self.h.t)["groessen"][1]]
        except Exception as e:
            return self._fehler(e)
        db, ok = QInputDialog.getItem(self, "Zugriff auf Datenbank", f"Datenbank für {name}:", dbs, 0, False)
        if not ok:
            return
        art, ok = QInputDialog.getItem(self, "Zugriff auf Datenbank", f"{name} auf {db}:", ["erlauben", "entziehen"], 0, False)
        if ok:
            arbeiter.starte(lambda: server.verbinden_erlauben(self.h.t, name, db, art == "erlauben"), self._erledigt, self._fehler)

    def rolle_loeschen(self):
        name = self._gewaehlte_rolle()
        if not name:
            return
        if name == self.h.cfg.get("benutzer"):
            return meldung(self, "Rolle löschen", "Die eigene Rolle lässt sich hier nicht löschen.", True)

        def da(folgen):
            text = f"Rolle „{name}“ löschen?"
            if folgen:
                text += "\n\nFolgen:\n• " + "\n• ".join(folgen)
            if rueckfrage(self, "Rolle löschen", text, "Löschen"):
                arbeiter.starte(lambda: server.benutzer_loeschen(self.h.t, name), self._erledigt, self._fehler)
        arbeiter.starte(lambda: server.folgen_benutzer_loeschen(self.h.t, name), da, self._fehler)

    # --- Variablen
    def _variablen_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.var, self.var_proxy, ansicht, suche = _raster()
        self.nur_geaendert = QCheckBox("nur geänderte")
        self.nur_geaendert.toggled.connect(lambda _: self.lade_variablen())
        v.addLayout(zeile(suche, self.nur_geaendert, knopf("Aktualisieren", self.lade_variablen), dehnen=False))
        v.addWidget(ansicht, 1)
        v.addWidget(label("Ändern über ALTER SYSTEM bzw. SET GLOBAL im SQL-Editor; „Wirksam“ sagt, ob ein Neustart nötig ist.", "gedimmt", True))
        self.tabs.addTab(w, "Variablen")

    def lade_variablen(self):
        t = self.h.t
        nur = self.nur_geaendert.isChecked()

        def da(r):
            sp, zeilen = r
            if nur:
                zeilen = [z for z in zeilen if z[5]]
            self.var.setze(sp, [tuple(_ja(x) for x in z) for z in zeilen])
        arbeiter.starte(lambda: server.variablen(t), da, self._fehler)

    # --- Sicherung
    def _sicherung_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        f, l = karte("Datenbank sichern (SQL-Dump)")
        self.sich_db = QComboBox()
        self.sich_struktur = QCheckBox("nur Struktur (ohne Daten)")
        self.sich_info = label("", "gedimmt", True)
        l.addLayout(zeile(label("Datenbank"), self.sich_db, self.sich_struktur))
        l.addLayout(zeile(knopf("Sichern unter …", self.sichern, "primaer"), self.sich_info))
        l.addWidget(label("Nutzt pg_dump bzw. mysqldump auf diesem Rechner; das Passwort geht über die Umgebung, nie über die "
                          "Kommandozeile. Zurückspielen: Import & Kopieren → SQL-Dump.", "gedimmt", True))
        v.addWidget(f)
        v.addStretch(1)
        self.tabs.addTab(w, "Sicherung")

    def lade_sicherung(self):
        t = self.h.t
        self.sich_db.clear()
        try:
            dbs = t.datenbanken() or [d for d, *_ in server.status(t)["groessen"][1]]
        except Exception:
            dbs = []
        self.sich_db.addItems(dbs)
        i = self.sich_db.findText(self.h.cfg.get("datenbank", ""))
        self.sich_db.setCurrentIndex(max(i, 0))
        prog = server.sicherungsprogramm(t)
        self.sich_info.setText(f"Programm: {prog}" if prog else "pg_dump/mysqldump fehlt auf diesem Rechner.")

    def sichern(self):
        db = self.sich_db.currentText()
        if not db:
            return
        from datetime import datetime
        vorschlag = str(Path.home() / f"{db}-{datetime.now():%Y-%m-%d_%H%M}.sql")
        ziel, _ = QFileDialog.getSaveFileName(self, "Sicherung speichern", vorschlag, "SQL (*.sql)")
        if not ziel:
            return
        cfg = self.h.cfg
        pw = verbindungen.passwort(cfg) or verbindungen.passwort_gleiches_konto(cfg)
        self.sich_info.setText("Sichere …")
        arbeiter.starte(lambda: server.sicherung(self.h.t, cfg, pw, db, Path(ziel), self.sich_struktur.isChecked()),
                        lambda p: self.sich_info.setText(f"Gesichert: {p} ({p.stat().st_size / 1048576:.1f} MB)"),
                        lambda f: self.sich_info.setText(f"Fehler: {f}"))
