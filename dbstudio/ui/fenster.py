"""Hauptfenster: Sidebar wie im Job Agent, Seiten für Verbindungen, Datenbank, SQL, Import und Einstellungen."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__, treiber, verbindungen
from . import arbeiter, theme
from .bausteine import label, meldung, rueckfrage
from .seite_austausch import AustauschSeite
from .seite_diagramm import DiagrammSeite
from .seite_editor import EditorSeite
from .seite_einstellungen import EinstellungenSeite
from .seite_explorer import ExplorerSeite
from .seite_verbindungen import VerbindungenSeite

NAV = [("ARBEIT", None), ("Verbindungen", "verbindungen"), ("Datenbank", "explorer"), ("Diagramm", "diagramm"), ("SQL-Editor", "editor"),
       ("Import && Kopieren", "austausch"), ("SYSTEM", None), ("Einstellungen", "einstellungen")]


class Hauptfenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pi DB Studio")
        self.setWindowIcon(QIcon(str(theme.ICON)))
        self.resize(1440, 880)
        self.t: treiber.Treiber | None = None
        self.cfg: dict = {}
        self.thema = verbindungen.einstellungen().get("thema", "dunkel")
        self._thema_setzen()

        mitte = QWidget()
        mitte.setObjectName("inhalt")
        h = QHBoxLayout(mitte)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        self.stapel = QStackedWidget()
        h.addWidget(self.stapel, 1)
        self.setCentralWidget(mitte)

        self.verbindungen = VerbindungenSeite()
        self.verbindungen.verbinden.connect(self.verbinden)
        self.editor = EditorSeite(self)
        self.explorer = ExplorerSeite(self)
        self.austausch = AustauschSeite(self)
        self.diagramm = DiagrammSeite(self)
        self.einstellungen = EinstellungenSeite(self)
        self.seiten = {"verbindungen": self.verbindungen, "explorer": self.explorer, "diagramm": self.diagramm, "editor": self.editor,
                       "austausch": self.austausch, "einstellungen": self.einstellungen}
        for s in self.seiten.values():
            self.stapel.addWidget(s)
        self.austausch.ziele_auffuellen()
        self.zeige(self.verbindungen)

    # --- Sidebar ------------------------------------------------------------------------------------------------
    def _sidebar(self) -> QFrame:
        s = QFrame()
        s.setObjectName("sidebar")
        s.setFixedWidth(232)
        v = QVBoxLayout(s)
        v.setContentsMargins(12, 16, 12, 14)
        v.setSpacing(2)
        kopf = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(theme.BILDER / "logo-128.png")).scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        kopf.addWidget(logo)
        namen = QVBoxLayout()
        namen.setSpacing(0)
        t = label("Pi DB Studio", "titel")
        namen.addWidget(t)
        namen.addWidget(label("Päffgen IT · Daten mit KI", "sidebarUnter"))
        kopf.addLayout(namen)
        kopf.addStretch(1)
        v.addLayout(kopf)
        v.addSpacing(10)
        self.nav_gruppe = QButtonGroup(self)
        self.nav_gruppe.setExclusive(True)
        self.nav: dict[str, QPushButton] = {}
        for text, schluessel in NAV:
            if schluessel is None:
                v.addWidget(label(text, "navSektion"))
                continue
            b = QPushButton(text)
            b.setObjectName("navEintrag")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=schluessel: self.zeige(self.seiten[k]))
            self.nav_gruppe.addButton(b)
            self.nav[schluessel] = b
            v.addWidget(b)
        v.addStretch(1)
        self.aktiv_box = QFrame()
        self.aktiv_box.setObjectName("karte")
        av = QVBoxLayout(self.aktiv_box)
        av.setContentsMargins(10, 8, 10, 8)
        self.aktiv_name = label("Nicht verbunden", "karteTitel")
        self.aktiv_info = label("", "gedimmt", True)
        av.addWidget(self.aktiv_name)
        av.addWidget(self.aktiv_info)
        self.k_trennen = QPushButton("Trennen")
        self.k_trennen.clicked.connect(self.trennen)
        self.k_trennen.hide()
        av.addWidget(self.k_trennen)
        v.addWidget(self.aktiv_box)
        self.k_thema = QPushButton()
        self.k_thema.setObjectName("themaKnopf")
        self.k_thema.clicked.connect(self._thema_wechseln)
        v.addWidget(self.k_thema)
        v.addWidget(label(f"Version {__version__}", "sidebarUnter"))
        self._thema_knopf()
        return s

    def zeige(self, seite):
        self.stapel.setCurrentWidget(seite)
        for k, s in self.seiten.items() if hasattr(self, "seiten") else []:
            if s is seite:
                self.nav[k].setChecked(True)

    # --- Thema --------------------------------------------------------------------------------------------------
    def _thema_setzen(self):
        QApplication.instance().setStyleSheet(theme.stylesheet(theme.DUNKEL if self.thema == "dunkel" else theme.HELL))

    def _thema_knopf(self):
        self.k_thema.setText("☀  Helles Design" if self.thema == "dunkel" else "☾  Dunkles Design")

    def _thema_wechseln(self):
        self.thema = "hell" if self.thema == "dunkel" else "dunkel"
        verbindungen.setze_einstellungen({"thema": self.thema})
        self._thema_setzen()
        self._thema_knopf()
        for i in range(self.editor.tabs.count()):
            self.editor.tabs.widget(i).hervorhebung.neu_einfaerben()

    # --- Verbindung ---------------------------------------------------------------------------------------------
    def status_text(self) -> str:
        if not self.t:
            return ""
        return f"{self.cfg.get('name')} · {self.cfg.get('_version', '')}" + (" · nur lesen" if self.t.schreibschutz else "")

    def verbinden(self, cfg: dict):
        if self.explorer.modell.geaendert and not rueckfrage(self, "Ungespeicherte Änderungen", "Änderungen im Datenraster verwerfen?", "Verwerfen"):
            return
        pw = verbindungen.passwort(cfg)
        self.aktiv_name.setText("Verbinde …")
        self.aktiv_info.setText(cfg.get("name", ""))

        def lauf():
            t = treiber.oeffne(cfg, pw)
            return t, t.version()
        arbeiter.starte(lauf, lambda d: self._verbunden(cfg, *d), self._nicht_verbunden)

    def _verbunden(self, cfg, t, version):
        if self.t:
            self.t.schliessen()
        self.t, self.cfg = t, dict(cfg, _version=version)
        self.aktiv_name.setText(cfg.get("name", ""))
        farbe = cfg.get("farbe")
        if farbe:
            self.aktiv_box.setStyleSheet(f"#karte {{ border-left: 4px solid {farbe}; }}")
        else:
            self.aktiv_box.setStyleSheet("")
        self.aktiv_info.setText(f"{treiber.ARTEN.get(cfg['art'])}\n{version}" + ("\nSchreibschutz an" if t.schreibschutz else ""))
        self.k_trennen.show()
        self.verbindungen.markiere(cfg["id"])
        for s in (self.explorer, self.diagramm, self.editor, self.austausch):
            s.kopf.status(self.status_text(), "pillWarn" if t.schreibschutz else "pill")
        self.explorer.neu_laden()
        self.austausch.verbindung_gewechselt()
        self.diagramm.verbindung_gewechselt()
        self.zeige(self.explorer)

    def _nicht_verbunden(self, fehler):
        self.aktiv_name.setText(self.cfg.get("name") if self.t else "Nicht verbunden")
        self.aktiv_info.setText("")
        meldung(self, "Verbindung fehlgeschlagen", fehler, True)

    def trennen(self):
        if self.t:
            self.t.schliessen()
        self.t, self.cfg = None, {}
        self.aktiv_name.setText("Nicht verbunden")
        self.aktiv_info.setText("")
        self.aktiv_box.setStyleSheet("")
        self.k_trennen.hide()
        self.verbindungen.markiere("")
        self.explorer.baum.clear()
        self.diagramm.verbindung_gewechselt()
        for s in (self.explorer, self.diagramm, self.editor, self.austausch):
            s.kopf.status("")

    def closeEvent(self, e):
        if self.explorer.modell.geaendert and not rueckfrage(self, "Ungespeicherte Änderungen",
                                                              "Im Datenraster sind Änderungen nicht übernommen. Trotzdem schließen?", "Schließen"):
            e.ignore()
            return
        if self.t:
            self.t.abbrechen()
        arbeiter.warte_alle(3000)
        if self.t:
            self.t.schliessen()
        super().closeEvent(e)
