"""Kleine Bausteine, damit alle Seiten gleich aussehen (Karten, Knöpfe, Kopfzeile, Rückfragen)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QTableView,
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
