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
from .seite_server import ServerSeite
from .seite_verbindungen import VerbindungenSeite

NAV = [("ARBEIT", None), ("Verbindungen", "verbindungen"), ("Datenbank", "explorer"), ("Diagramm", "diagramm"), ("SQL-Editor", "editor"),
       ("Import && Kopieren", "austausch"), ("SYSTEM", None), ("Server", "server"), ("Einstellungen", "einstellungen")]


class Hauptfenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pi DB Studio")
        self.setWindowIcon(QIcon(str(theme.ICON)))
        self.resize(1440, 880)
        self.t: treiber.Treiber | None = None
        self.cfg: dict = {}
        self._danach_tabelle = None   # Tabellenname oder (Schema, Tabelle), nach dem Verbinden öffnen
        self._danach = None
        self._neben: dict = {}         # Nebenverbindungen je Datenbank (Serverbaum)
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
        self.server = ServerSeite(self)
        self.seiten = {"verbindungen": self.verbindungen, "explorer": self.explorer, "diagramm": self.diagramm, "editor": self.editor,
                       "austausch": self.austausch, "server": self.server,
                       "einstellungen": self.einstellungen}
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
    def schema_gewaehlt(self, schema: str, objekte: dict | None = None, merken: bool = True):
        """Arbeitsschema setzen (search_path/USE), merken, Editor und Diagramm informieren."""
        t = self.t
        if not t or not schema:
            return
        if merken and schema != t.aktuelles_schema:
            from . import arbeiter as _a
            _a.starte(lambda: t.setze_schema(schema), lambda _r: None)
        t.aktuelles_schema = schema
        if merken:
            verbindungen.merke_schema(self.cfg, schema)
        self.editor.schema_gewaehlt(schema, objekte)

    def status_text(self) -> str:
        if not self.t:
            return ""
        db = self.cfg.get("datenbank") if self.cfg.get("art") == "postgresql" else ""
        return f"{self.cfg.get('name')}{' · ' + db if db else ''} · {self.cfg.get('_version', '')}" + (" · nur lesen" if self.t.schreibschutz else "")

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
        self.nebenverbindungen_schliessen()
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
        if self._danach_tabelle:
            tab, self._danach_tabelle = self._danach_tabelle, None
            if isinstance(tab, tuple):
                self.explorer.oeffnen(*tab)
            else:
                self.explorer.oeffnen(t.aktuelles_schema or t.standard_schema(), tab)
        if self._danach:
            f, self._danach = self._danach, None
            f()
        self.austausch.verbindung_gewechselt()
        self.diagramm.verbindung_gewechselt()
        self.server.verbindung_gewechselt()
        self.zeige(self.explorer)

    def datenbank_wechseln(self, name: str, tabelle: tuple | None = None, nach=None):
        """Andere Datenbank auf demselben Server, gleiche Anmeldung (Passwort der Verbindung aus dem Schlüsselbund).
        `tabelle` (Schema, Name) wird danach geöffnet, `nach` danach aufgerufen."""
        cfg = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        cfg["datenbank"] = name
        self._danach_tabelle = tabelle
        self._danach = nach
        self.verbinden(cfg)

    def nebenverbindung(self, db: str):
        """Zweite Verbindung zum selben Server für eine andere Datenbank (nur zum Anzeigen im Baum)."""
        offen = self._neben.get(db)
        if offen is not None:
            return offen
        cfg = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        cfg["datenbank"] = db
        pw = verbindungen.passwort(self.cfg) or verbindungen.passwort_gleiches_konto(self.cfg)
        t = treiber.oeffne(cfg, pw)
        self._neben[db] = t
        return t

    def nebenverbindungen_schliessen(self):
        for t in self._neben.values():
            try:
                t.schliessen()
            except Exception:
                pass
        self._neben = {}

    def oeffne_von_aussen(self, werte: dict, tabelle: str | None = None) -> dict | None:
        """Start mit --verbindung (z. B. aus Visual Death Studio): Verbindung übernehmen bzw. wiederfinden, fehlt das
        Passwort, den Verbindungsdialog zeigen, dann verbinden und optional gleich die Tabelle öffnen."""
        from .seite_verbindungen import VerbindungDialog
        try:
            liste, v, neu = verbindungen.uebernehmen(self.verbindungen.liste, werte)
        except ValueError as e:
            meldung(self, "Verbindung", str(e), True)
            return None
        if neu:
            self.verbindungen.liste = liste
            verbindungen.speichern(liste)
            self.verbindungen.zeichnen()
        if v["art"] not in treiber.DATEI_ARTEN and not verbindungen.passwort(v):
            geerbt = verbindungen.passwort_gleiches_konto(v, self.verbindungen.liste)
            if geerbt:
                verbindungen.setze_passwort(v, geerbt)
        if v["art"] not in treiber.DATEI_ARTEN and not verbindungen.passwort(v):
            d = VerbindungDialog(self, v)
            if not d.exec():
                return None
            v = d.ergebnis
            self.verbindungen.liste = [d.ergebnis if x["id"] == v["id"] else x for x in self.verbindungen.liste]
            verbindungen.speichern(self.verbindungen.liste)
            self.verbindungen.zeichnen()
        self._danach_tabelle = tabelle
        self.verbinden(v)
        return v

    def _nicht_verbunden(self, fehler):
        self.aktiv_name.setText(self.cfg.get("name") if self.t else "Nicht verbunden")
        self.aktiv_info.setText("")
        meldung(self, "Verbindung fehlgeschlagen", fehler, True)

    def trennen(self):
        self.nebenverbindungen_schliessen()
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
        self.server.verbindung_gewechselt()
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
