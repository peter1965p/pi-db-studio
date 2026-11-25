"""Kleine Bausteine, damit alle Seiten gleich aussehen (Karten, Knöpfe, Kopfzeile, Rückfragen)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QTableView,
                               QVBoxLayout, QWidget, QAbstractItemView)


def knopf(text: str, aktion=None, art: str = "", tipp: str = "") -> QPushButton:
    b = QPushButton(text)
    if art:
        b.setObjectName(art)
    if tipp:
        b.setToolTip(tipp)
    b.setCursor(Qt.PointingHandCursor)
    if aktion:
        b.clicked.connect(aktion)
    return b


def label(text: str = "", name: str = "", umbruch: bool = False) -> QLabel:
    l = QLabel(text)
    if name:
        l.setObjectName(name)
    l.setWordWrap(umbruch)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return l


def karte(titel: str = "", rand: int = 16) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("karte")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(rand, rand - 2, rand, rand)
    lay.setSpacing(10)
    if titel:
        lay.addWidget(label(titel, "karteTitel"))
    return f, lay


def zeile(*widgets, abstand: int = 8, dehnen: bool = True) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(abstand)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    if dehnen and None not in widgets:
        h.addStretch(1)
    return h


class Kopf(QWidget):
    """Seitentitel links, Status-Pille rechts."""

    def __init__(self, titel: str, unter: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        links = QVBoxLayout()
        links.setSpacing(2)
        links.addWidget(label(titel, "titel"))
        self.unter = label(unter, "gedimmt")
        links.addWidget(self.unter)
        lay.addLayout(links)
        lay.addStretch(1)
        self.pill = QLabel("")
        self.pill.setObjectName("pillWarn")
        self.pill.hide()
        lay.addWidget(self.pill, 0, Qt.AlignTop)

    def status(self, text: str, art: str = "pill"):
        self.pill.setText(text)
        self.pill.setObjectName(art)
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        self.pill.setVisible(bool(text))


def tabelle() -> QTableView:
    v = QTableView()
    v.setAlternatingRowColors(True)
    v.setSelectionBehavior(QAbstractItemView.SelectItems)
    v.horizontalHeader().setStretchLastSection(False)
    v.horizontalHeader().setDefaultSectionSize(140)
    v.horizontalHeader().setMinimumSectionSize(40)
    v.verticalHeader().setDefaultSectionSize(26)
    v.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    v.setWordWrap(False)
    return v


def rueckfrage(eltern, titel: str, text: str, ja: str = "Ausführen") -> bool:
    box = QMessageBox(eltern)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(titel)
    box.setText(text)
    jak = box.addButton(ja, QMessageBox.AcceptRole)
    box.addButton("Abbrechen", QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is jak


def meldung(eltern, titel: str, text: str, fehler: bool = False):
    (QMessageBox.warning if fehler else QMessageBox.information)(eltern, titel, text)


def trenner() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: transparent; background: transparent; max-height: 1px;")
    return f


def leiste() -> QVBoxLayout:
    v = QVBoxLayout()
    v.setContentsMargins(24, 20, 24, 20)
    v.setSpacing(12)
    return v


class KiWahlDialog(QDialog):
    """Erste KI-Nutzung: Abo (Pro/Max über Claude Code), API-Schlüssel oder lokal – nie still gewählt."""

    def __init__(self, eltern=None):
        from PySide6.QtWidgets import QButtonGroup, QDialogButtonBox, QLineEdit, QRadioButton, QVBoxLayout
        from .. import ki
        super().__init__(eltern)
        self.setWindowTitle("KI einrichten")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.addWidget(label("Wie möchtest du die KI in Pi DB Studio nutzen?", "karteTitel"))
        v.addWidget(label("Gesendet werden nur das Schema bzw. deine Beschreibung, Datenzeilen nur auf ausdrücklichen Wunsch. "
                          "Ändern lässt sich das jederzeit unter Einstellungen → KI.", "gedimmt", True))
        self.gruppe = QButtonGroup(self)
        self.abo = QRadioButton("Ich habe ein Claude-Abo (Pro oder Max) – über Claude Code")
        self.api = QRadioButton("Ich nutze einen Anthropic-API-Schlüssel (Abrechnung je Anfrage)")
        self.lokal = QRadioButton("Lokal mit Ollama – nichts verlässt den Rechner")
        for b in (self.abo, self.api, self.lokal):
            self.gruppe.addButton(b)
        claude = ki.claude_pfad()
        self.modelle = [k for k, _ in ki.anbieter_liste() if k.startswith("ollama:")]
        v.addWidget(self.abo)
        if not claude:
            self.abo.setEnabled(False)
            v.addWidget(label("    Claude Code ist hier nicht installiert: npm install -g @anthropic-ai/claude-code, "
                              "dann einmal „claude“ starten und anmelden.", "gedimmt", True))
        v.addWidget(self.api)
        self.schluessel = QLineEdit()
        self.schluessel.setEchoMode(QLineEdit.Password)
        self.schluessel.setPlaceholderText("sk-ant-…  (landet im Schlüsselbund, nie in einer Datei)")
        self.schluessel.setEnabled(False)
        self.api.toggled.connect(self.schluessel.setEnabled)
        v.addWidget(self.schluessel)
        v.addWidget(self.lokal)
        if not self.modelle:
            self.lokal.setEnabled(False)
            v.addWidget(label("    Kein lokales Modell gefunden (Ollama nicht gestartet oder kein Modell geladen).", "gedimmt", True))
        (self.abo if claude else self.api).setChecked(True)
        self.fehler = label("", "fehlertext", True)
        v.addWidget(self.fehler)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        knoepfe.accepted.connect(self._ok)
        knoepfe.rejected.connect(self.reject)
        v.addWidget(knoepfe)
        self.anbieter = ""

    def _ok(self):
        from .. import ki
        if self.abo.isChecked():
            self.anbieter = "claude-code"
        elif self.api.isChecked():
            wert = self.schluessel.text().strip()
            if not wert and not ki.api_schluessel():
                return self.fehler.setText("Bitte den API-Schlüssel eintragen.")
            if wert:
                ki.setze_api_schluessel(wert)
            self.anbieter = "claude-api"
        elif self.lokal.isChecked() and self.modelle:
            self.anbieter = self.modelle[0]
        else:
            return
        self.accept()


def ki_anbieter_klaeren(eltern) -> tuple[str, str] | None:
    """(Anbieter, Modell) aus den Einstellungen. Ist noch keiner gewählt, wird einmal nachgefragt – nie still gewählt,
    denn je nach Anbieter gehen Schema und Beschreibung an einen Dienst außerhalb des Rechners."""
    from .. import verbindungen
    e = verbindungen.einstellungen()
    if e.get("ki_anbieter"):
        return e["ki_anbieter"], e.get("ki_modell", "")
    d = KiWahlDialog(eltern)
    if not d.exec() or not d.anbieter:
        return None
    verbindungen.setze_einstellungen({"ki_anbieter": d.anbieter})
    return d.anbieter, e.get("ki_modell", "")
