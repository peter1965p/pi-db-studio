"""Ein Schiebeschalter statt der Checkbox. Die Farben kommen aus dem Theme-Stylesheet."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton

BREITE, HOEHE, ABSTAND, RAND = 34, 18, 8, 2


class Schalter(QAbstractButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._stand = 0.0
        self._an, self._aus, self._knopf, self._schrift, self._gedimmt = (
            QColor("#f5a623"), QColor("#383b47"), QColor("#ffffff"), QColor("#e7e8ec"), QColor("#9a9eab"))
        self._animation = QPropertyAnimation(self, b"stand", self)
        self._animation.setDuration(130)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._bewege)

    def _bewege(self, an: bool):
        self._animation.stop()
        if not self.isVisible():  # Beim Vorbelegen einer Seite soll nichts sichtbar nachrutschen.
            self._stand = 1.0 if an else 0.0
            self.update()
            return
        self._animation.setStartValue(self._stand)
        self._animation.setEndValue(1.0 if an else 0.0)
        self._animation.start()

    def _lies_stand(self):
        return self._stand

    def _setze_stand(self, wert):
        self._stand = wert
        self.update()

    stand = Property(float, _lies_stand, _setze_stand)

    def _farbe(name):  # noqa: N805 - Hilfsfunktion nur beim Aufbau der Klasse.
        def lies(self):
            return getattr(self, name)

        def setze(self, wert):
            setattr(self, name, QColor(wert))
            self.update()
        return Property(QColor, lies, setze)

    farbeAn = _farbe("_an")
    farbeAus = _farbe("_aus")
    farbeKnopf = _farbe("_knopf")
    farbeSchrift = _farbe("_schrift")
    farbeGedimmt = _farbe("_gedimmt")
    del _farbe

    def sizeHint(self) -> QSize:
        text = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(BREITE + (ABSTAND + text if text else 0) + 2, max(HOEHE + 4, self.fontMetrics().height() + 4))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        oben = (self.height() - HOEHE) / 2
        bahn = QRectF(1, oben, BREITE, HOEHE)
        farbe = QColor(self._aus)
        anteil = self._stand
        farbe = QColor(round(self._aus.red() + (self._an.red() - self._aus.red()) * anteil),
                       round(self._aus.green() + (self._an.green() - self._aus.green()) * anteil),
                       round(self._aus.blue() + (self._an.blue() - self._aus.blue()) * anteil))
        if not self.isEnabled():
            farbe.setAlpha(90)
        p.setPen(QPen(self._an, 1.5) if self.hasFocus() else Qt.NoPen)
        p.setBrush(farbe)
        p.drawRoundedRect(bahn, HOEHE / 2, HOEHE / 2)
        durchmesser = HOEHE - 2 * RAND
        links = bahn.left() + RAND + (BREITE - 2 * RAND - durchmesser) * anteil
        knopf = QColor(self._knopf)
        if not self.isEnabled():
            knopf.setAlpha(120)
        p.setPen(Qt.NoPen)
        p.setBrush(knopf)
        p.drawEllipse(QRectF(links, oben + RAND, durchmesser, durchmesser))
        if self.text():
            p.setPen(self._schrift if self.isEnabled() else self._gedimmt)
            p.drawText(self.rect().adjusted(BREITE + ABSTAND + 2, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())
