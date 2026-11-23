"""Visueller Beziehungsdesigner: ER-Diagramm mit Krähenfuß-Notation, Bearbeiten als DDL-Vorschau, Export PNG/SVG."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QLabel,
                               QPushButton,
                               QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
                               QHeaderView, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import efcore, erm, ki, sqlschutz, treiber, verbindungen
from ..treiber import Spalte
from . import arbeiter, theme
from .bausteine import Kopf, knopf, label, leiste, meldung, rueckfrage, zeile

BREITE = 250
KOPF_H = 34
KOPF_EF = 44
ZEILE_H = 22
TYPEN = ["ganzzahl", "grosse_ganzzahl", "text", "kommazahl", "dezimal", "wahrheitswert", "datum", "zeitstempel",
         "zeit", "binaer", "json", "uuid"]
PRODUKTIV = "#e05252"


def _farbe(name: str) -> QColor:
    return QColor(theme.AKTUELL[name])


# --- Grafik-Elemente ------------------------------------------------------------------------------------------------
RASTER = 20
EINKLAPP_AB = 12      # Karten mit mehr Spalten starten eingeklappt
EINGEKLAPPT_ZEIGEN = 8
MODI = {"alle": "Alle Spalten", "schluessel": "Nur Schlüssel", "namen": "Nur Tabellennamen"}
ART_FARBE = {"1:n": "blau", "1:1": "akzent", "n:m": "neon"}
ART_TEXT = {"1:n": "1:n – eins zu vielen", "1:1": "1:1 – eins zu eins", "n:m": "n:m – viele zu vielen (über Zwischentabelle)",
            "optional": "0..1 – optional (FK darf leer sein)"}


def _einzahl(name: str) -> str:
    """Grobe Einzahl für Tooltips: firmen → Firma, entwuerfe → Entwurf, kunden → Kunde."""
    n = name.replace("_", " ")
    for endung, ersatz in (("ungen", "ung"), ("uerfe", "urf"), ("eien", "ei"), ("men", "ma"), ("nen", "n"),
                           ("en", "e"), ("ies", "y"), ("es", "e"), ("s", ""), ("e", "e")):
        if n.endswith(endung) and len(n) > len(endung) + 2:
            n = n[: -len(endung)] + ersatz
            break
    return n[:1].upper() + n[1:]


def _mehrzahl(name: str) -> str:
    n = name.replace("_", " ")
    return n[:1].upper() + n[1:]


def runde_ecken(punkte: list[QPointF], r: float = 8) -> QPainterPath:
    """Polylinie mit abgerundeten Ecken."""
    pfad = QPainterPath(punkte[0])
    for i in range(1, len(punkte) - 1):
        a, b, c = punkte[i - 1], punkte[i], punkte[i + 1]
        d1 = QPointF(b.x() - a.x(), b.y() - a.y())
        d2 = QPointF(c.x() - b.x(), c.y() - b.y())
        l1 = max(1e-6, (d1.x() ** 2 + d1.y() ** 2) ** 0.5)
        l2 = max(1e-6, (d2.x() ** 2 + d2.y() ** 2) ** 0.5)
        rr = min(r, l1 / 2, l2 / 2)
        vor = QPointF(b.x() - d1.x() / l1 * rr, b.y() - d1.y() / l1 * rr)
        nach = QPointF(b.x() + d2.x() / l2 * rr, b.y() + d2.y() / l2 * rr)
        pfad.lineTo(vor)
        pfad.quadTo(b, nach)
    pfad.lineTo(punkte[-1])
    return pfad


class TabellenKarte(QGraphicsObject):
    bewegt = Signal()
    losgelassen = Signal()
    beziehung_gezogen = Signal(str, str, str, str)  # von_tabelle, von_spalte, nach_tabelle, nach_spalte
    spalte_doppelklick = Signal(str, str)
    schwebt = Signal(str)  # Tabellenname oder "" beim Verlassen
    groesse_geaendert = Signal()

    def __init__(self, tabelle: erm.Tabelle, fk_spalten: set[str], zwischen: bool, modus: str = "alle",
                 stil: str = "db", schema: str = "", navs: list | None = None):
        super().__init__()
        self.t, self.fk_spalten, self.zwischen = tabelle, fk_spalten, zwischen
        self.modus = modus
        self.stil, self.schema_name, self.navs = stil, schema, navs or []
        self.eingeklappt = len(tabelle.spalten) > EINKLAPP_AB
        self.einrasten = True
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(2)
        self._ziehlinie: QGraphicsPathItem | None = None
        self._zieh_von: str | None = None
        self.setToolTip("Kopf ziehen = verschieben · von einer Spalte auf eine Spalte einer anderen Tabelle ziehen = "
                        "Beziehung · Doppelklick auf Spalte = ändern · ▾/▸ = ein-/ausklappen")

    # Sichtbarkeit
    def einklappbar(self) -> bool:
        return self.modus == "alle" and len(self.t.spalten) > EINGEKLAPPT_ZEIGEN

    def sichtbar(self) -> list:
        if self.modus == "namen":
            return []
        if self.modus == "schluessel":
            return [s for s in self.t.spalten if s.pk or s.name in self.fk_spalten]
        if self.eingeklappt and self.einklappbar():
            wichtig = [s for s in self.t.spalten if s.pk or s.name in self.fk_spalten]
            rest = [s for s in self.t.spalten if s not in wichtig]
            return (wichtig + rest)[:max(EINGEKLAPPT_ZEIGEN, len(wichtig))]
        return list(self.t.spalten)

    def versteckt(self) -> int:
        return len(self.t.spalten) - len(self.sichtbar()) if self.modus == "alle" else 0

    def setze_modus(self, modus: str):
        self.prepareGeometryChange()
        self.modus = modus
        self.update()
        self.groesse_geaendert.emit()

    def setze_stil(self, stil: str):
        self.prepareGeometryChange()
        self.stil = stil
        self.update()
        self.groesse_geaendert.emit()

    @property
    def kopf_h(self) -> float:
        return KOPF_EF if self.stil == "ef" else KOPF_H

    def zeilen(self) -> list[tuple]:
        """Sichtbare Zeilen der Karte: („sp“, Spalte) | („mehr“, n) | („abschnitt“, Text) | („nav“, Name, Typ)."""
        sp = [("sp", x) for x in self.sichtbar()]
        mehr = [("mehr", self.versteckt())] if self.versteckt() else []
        if self.stil != "ef":
            return sp + mehr
        if self.modus == "namen":
            return []
        z = ([("abschnitt", "Eigenschaften")] + sp + mehr) if sp or mehr else []
        if self.navs:
            z += [("abschnitt", "Navigationen")] + [("nav", n, t) for n, t, _ in self.navs]
        return z

    def umklappen(self):
        self.prepareGeometryChange()
        self.eingeklappt = not self.eingeklappt
        self.update()
        self.groesse_geaendert.emit()

    @property
    def hoehe(self) -> float:
        n = len(self.zeilen())
        return self.kopf_h + ZEILE_H * n + (8 if n else 0)

    def boundingRect(self) -> QRectF:
        return QRectF(-1, -1, BREITE + 2, self.hoehe + 2)

    def rechteck(self) -> QRectF:
        return self.mapRectToScene(QRectF(0, 0, BREITE, self.hoehe))

    def spalte_y(self, name: str) -> float:
        for i, z in enumerate(self.zeilen()):
            if z[0] == "sp" and z[1].name == name:
                return self.kopf_h + ZEILE_H * i + ZEILE_H / 2
        return self.kopf_h / 2

    def zeile_bei(self, y: float) -> tuple | None:
        z = self.zeilen()
        i = int((y - self.kopf_h) // ZEILE_H)
        return z[i] if y > self.kopf_h and 0 <= i < len(z) else None

    def spalte_bei(self, y: float) -> str | None:
        z = self.zeile_bei(y)
        return z[1].name if z and z[0] == "sp" else None

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.Antialiasing)
        kh = self.kopf_h
        rand = _farbe("akzent") if self.isSelected() else (_farbe("neon") if self.zwischen else _farbe("rand"))
        p.setPen(QPen(rand, 2 if self.isSelected() else 1))
        p.setBrush(_farbe("karte"))
        p.drawRoundedRect(QRectF(0, 0, BREITE, self.hoehe), 10, 10)
        kopf = QPainterPath()
        kopf.addRoundedRect(QRectF(0, 0, BREITE, kh), 10, 10)
        if self.hoehe > kh + 2:
            kopf.addRect(QRectF(0, kh - 10, BREITE, 10))
        p.fillPath(kopf, _farbe("aktiv"))
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.setPen(_farbe("akzent"))
        rechts_frei = 30 if self.einklappbar() else 12
        titelbreite = BREITE - 12 - rechts_frei - (52 if self.zwischen else 0)
        if self.stil == "ef":
            titel = efcore.klassenname(self.t.name)
            p.drawText(QRectF(12, 4, titelbreite, 22), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(f).elidedText(titel, Qt.ElideRight, titelbreite))
            k = QFont()
            k.setPointSizeF(8)
            p.setFont(k)
            p.setPen(_farbe("gedimmt"))
            unter = f"[{self.schema_name}].[{self.t.name}]" if self.schema_name else f"[{self.t.name}]"
            p.drawText(QRectF(12, 24, titelbreite, 16), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(k).elidedText(unter, Qt.ElideRight, titelbreite))
        else:
            p.drawText(QRectF(12, 0, titelbreite, kh), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(f).elidedText(self.t.name, Qt.ElideRight, titelbreite))
        if self.zwischen:  # Plakette n:m
            plakette(p, QPointF(BREITE - rechts_frei - 26, kh / 2), "n:m", _farbe("neon"))
        if self.einklappbar():
            p.setPen(_farbe("gedimmt"))
            p.setFont(f)
            p.drawText(QRectF(BREITE - 28, 0, 22, kh), Qt.AlignCenter, "▸" if self.eingeklappt else "▾")
        normal, fett, klein = QFont(), QFont(), QFont()
        normal.setPointSizeF(9.5)
        fett.setPointSizeF(9.5)
        fett.setBold(True)
        klein.setPointSizeF(8.5)
        for i, z in enumerate(self.zeilen()):
            y = kh + ZEILE_H * i
            zeile_r = QRectF(0, y, BREITE, ZEILE_H)
            if i and z[0] != "abschnitt":
                p.setPen(QPen(_farbe("rand"), 0.5))
                p.drawLine(zeile_r.topLeft() + QPointF(8, 0), zeile_r.topRight() - QPointF(8, 0))
            if z[0] == "abschnitt":
                p.setFont(klein)
                p.setPen(_farbe("blau"))
                p.drawText(QRectF(10, y, BREITE - 20, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft, z[1].upper())
                p.setPen(QPen(_farbe("rand"), 1))
                p.drawLine(QPointF(10, y + ZEILE_H - 2), QPointF(BREITE - 10, y + ZEILE_H - 2))
                continue
            if z[0] == "mehr":
                p.setFont(klein)
                p.setPen(_farbe("gedimmt"))
                p.drawText(QRectF(30, y, BREITE - 40, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft,
                           f"… {z[1]} weitere {'Eigenschaften' if self.stil == 'ef' else 'Spalten'} (klicken)")
                continue
            if z[0] == "nav":
                p.setFont(normal)
                p.setPen(_farbe("blau"))
                p.drawText(QRectF(8, y, 20, ZEILE_H), Qt.AlignVCenter | Qt.AlignHCenter, "⇢")
                p.setPen(_farbe("text"))
                p.drawText(QRectF(30, y, 110, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft,
                           QFontMetricsF(normal).elidedText(z[1], Qt.ElideRight, 110))
                p.setFont(klein)
                p.setPen(_farbe("gedimmt"))
                p.drawText(QRectF(142, y, BREITE - 150, ZEILE_H), Qt.AlignVCenter | Qt.AlignRight,
                           QFontMetricsF(klein).elidedText(z[2], Qt.ElideRight, BREITE - 150))
                continue
            s = z[1]
            symbol = "🔑" if s.pk else ("↗" if s.name in self.fk_spalten else "")
            p.setFont(normal)
            p.setPen(_farbe("akzent") if s.pk else _farbe("blau"))
            p.drawText(QRectF(8, y, 20, ZEILE_H), Qt.AlignVCenter | Qt.AlignHCenter, symbol)
            p.setFont(fett if not s.nullbar else normal)
            p.setPen(_farbe("text"))
            name = efcore.eigenschaft(s.name) if self.stil == "ef" else s.name
            p.drawText(QRectF(30, y, 120, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(p.font()).elidedText(name, Qt.ElideRight, 120))
            p.setFont(klein)
            p.setPen(_farbe("gedimmt"))
            typ = efcore.cs_typ(s) if self.stil == "ef" else (s.typ or "").lower() + ("" if s.nullbar else " ·NN")
            p.drawText(QRectF(152, y, BREITE - 160, ZEILE_H), Qt.AlignVCenter | Qt.AlignRight,
                       QFontMetricsF(klein).elidedText(typ, Qt.ElideRight, BREITE - 160))

    def itemChange(self, change, wert):
        if change == QGraphicsItem.ItemPositionChange and self.einrasten and self.scene() is not None:
            return QPointF(round(wert.x() / RASTER) * RASTER, round(wert.y() / RASTER) * RASTER)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.bewegt.emit()
        return super().itemChange(change, wert)

    def hoverEnterEvent(self, e):
        self.schwebt.emit(self.t.name)
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        self.schwebt.emit("")
        super().hoverLeaveEvent(e)

    # Ziehen: Kopf verschiebt, Spalte zieht eine Beziehung
    def mousePressEvent(self, e):
        pos = e.pos()
        z = self.zeile_bei(pos.y())
        if e.button() == Qt.LeftButton and ((self.einklappbar() and pos.y() < self.kopf_h and pos.x() > BREITE - 30)
                                             or (z and z[0] == "mehr")):
            self.umklappen()
            e.accept()
            return
        spalte = self.spalte_bei(pos.y())
        if e.button() == Qt.LeftButton and spalte:
            self._zieh_von = spalte
            self._ziehlinie = QGraphicsPathItem()
            self._ziehlinie.setPen(QPen(_farbe("akzent"), 2, Qt.DashLine))
            self._ziehlinie.setZValue(5)
            self.scene().addItem(self._ziehlinie)
            e.accept()
            return
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._ziehlinie is not None:
            start = self.mapToScene(QPointF(BREITE, self.spalte_y(self._zieh_von)))
            pfad = QPainterPath(start)
            pfad.lineTo(e.scenePos())
            self._ziehlinie.setPath(pfad)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._ziehlinie is not None:
            self.scene().removeItem(self._ziehlinie)
            self._ziehlinie = None
            von, self._zieh_von = self._zieh_von, None
            for item in self.scene().items(e.scenePos()):
                if isinstance(item, TabellenKarte) and item is not self:
                    nach = item.spalte_bei(item.mapFromScene(e.scenePos()).y())
                    if nach:
                        self.beziehung_gezogen.emit(self.t.name, von, item.t.name, nach)
                    break
            return
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)
        self.losgelassen.emit()

    def mouseDoubleClickEvent(self, e):
        spalte = self.spalte_bei(e.pos().y())
        if spalte:
            self.spalte_doppelklick.emit(self.t.name, spalte)


def plakette(p: QPainter, mitte: QPointF, text: str, farbe: QColor):
    """Kleine runde Beschriftung („1“, „n“, „0..1“, „n:m“) mit Rand in der Linienfarbe."""
    f = QFont()
    f.setBold(True)
    f.setPointSizeF(8.5)
    breite = QFontMetricsF(f).horizontalAdvance(text) + 10
    r = QRectF(mitte.x() - breite / 2, mitte.y() - 9, breite, 18)
    p.setPen(QPen(farbe, 1.4))
    p.setBrush(_farbe("bg"))
    p.drawRoundedRect(r, 9, 9)
    p.setFont(f)
    p.setPen(farbe)
    p.drawText(r, Qt.AlignCenter, text)


class BeziehungsLinie(QGraphicsPathItem):
    """Rechtwinklige Linie vom FK (Kind, „viele“) zur referenzierten Spalte (Eltern, „eins“) mit Krähenfuß und
    Plaketten an beiden Enden. Farbe je Art: 1:n Blau, 1:1 Orange, n:m (über Zwischentabelle) Neon-Grün gestrichelt."""

    def __init__(self, fk: erm.Fremdschluessel, kind: TabellenKarte, eltern: TabellenKarte, art: str,
                 optional: bool = False, n_zu_m: bool = False, stil: str = "db", ef_mult: tuple[str, str] = ("1", "*")):
        super().__init__()
        self.fk, self.kind, self.eltern = fk, kind, eltern
        self.stil, self.ef_mult = stil, ef_mult
        self.art = "n:m" if n_zu_m else art
        self.basis_art, self.optional = art, optional
        self.versatz = 0.0
        self.betont = False
        self._plaketten: list[tuple[QPointF, str]] = []
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setToolTip(self.tooltip())
        self.aktualisieren()

    def tooltip(self) -> str:
        f = self.fk
        kurz = "1:1" if self.basis_art == "1:1" else "n:1"
        technik = (f"{f.tabelle}.{', '.join(f.spalten)} → {f.ziel}.{', '.join(f.ziel_spalten)}  "
                   f"({kurz}{', optional' if self.optional else ''}, ON DELETE {f.bei_loeschen}, ON UPDATE {f.bei_aendern})")
        if self.basis_art == "1:1":
            worte = f"Eine {_einzahl(f.ziel)} hat höchstens eine {_einzahl(f.tabelle)}."
        else:
            worte = f"Eine {_einzahl(f.ziel)} hat viele {_mehrzahl(f.tabelle)}."
        if self.optional:
            worte += f" Eine {_einzahl(f.tabelle)} kann auch ohne {_einzahl(f.ziel)} existieren."
        if self.art == "n:m":
            worte += f"  ({f.tabelle} ist Zwischentabelle einer n:m-Beziehung.)"
        return f"{worte}\n{technik}"

    def farbe(self) -> QColor:
        return _farbe(ART_FARBE.get(self.art, "blau"))

    def aktualisieren(self):
        kr, er = self.kind.rechteck(), self.eltern.rechteck()
        ky = self.kind.mapToScene(QPointF(0, self.kind.spalte_y(self.fk.spalten[0]))).y()
        ey = self.eltern.mapToScene(QPointF(0, self.eltern.spalte_y(self.fk.ziel_spalten[0]))).y()
        abstand = 28.0
        if self.kind is self.eltern:
            a, b = QPointF(kr.right(), ky), QPointF(kr.right(), ey)
            mx = kr.right() + abstand + self.versatz
            punkte = [a, QPointF(mx, a.y()), QPointF(mx, b.y()), b]
            ra = rb = 1
        elif kr.right() + 2 * abstand <= er.left():      # Kind links vom Eltern
            a, b = QPointF(kr.right(), ky), QPointF(er.left(), ey)
            mx = (b.x() - abstand if b.x() - a.x() > 4 * abstand else (a.x() + b.x()) / 2) + self.versatz
            punkte = [a, QPointF(mx, a.y()), QPointF(mx, b.y()), b]
            ra, rb = 1, -1
        elif er.right() + 2 * abstand <= kr.left():      # Kind rechts vom Eltern
            a, b = QPointF(kr.left(), ky), QPointF(er.right(), ey)
            mx = (b.x() + abstand if a.x() - b.x() > 4 * abstand else (a.x() + b.x()) / 2) - self.versatz
            punkte = [a, QPointF(mx, a.y()), QPointF(mx, b.y()), b]
            ra, rb = -1, 1
        else:                                             # übereinander: außen rechts herum
            a, b = QPointF(kr.right(), ky), QPointF(er.right(), ey)
            mx = max(kr.right(), er.right()) + abstand + self.versatz
            punkte = [a, QPointF(mx, a.y()), QPointF(mx, b.y()), b]
            ra = rb = 1
        if abs(punkte[1].y() - punkte[2].y()) < 1:
            punkte = [punkte[0], punkte[3]]
        pfad = runde_ecken(punkte)
        if self.stil == "ef":  # EF/DGML: Pfeil zur Hauptentität, Multiplizität „1“/„0..1“ ↔ „*“
            pfad.moveTo(b + QPointF(rb * 14, -7))
            pfad.lineTo(b)
            pfad.lineTo(b + QPointF(rb * 14, 7))
            self._plaketten = [(b + QPointF(rb * 30, -13), self.ef_mult[0]), (a + QPointF(ra * 22, -13), self.ef_mult[1])]
            self.setPath(pfad)
            stift = QPen(self.farbe(), 2.6 if self.betont else 1.9)
            if self.art == "n:m":
                stift.setStyle(Qt.DashLine)
            self.setPen(stift)
            self.update()
            return
        # Enden: Eltern „eins“ (Doppelstrich bzw. Kreis+Strich bei optional), Kind „viele“ (Krähenfuß) oder „eins“
        if self.optional:
            self._kreis(pfad, b, rb)
            self._strich(pfad, b, rb, 18)
        else:
            self._strich(pfad, b, rb, 12)
            self._strich(pfad, b, rb, 18)
        if self.basis_art == "1:1":
            self._strich(pfad, a, ra, 12)
            self._strich(pfad, a, ra, 18)
        else:
            self._kraehenfuss(pfad, a, ra)
            self._strich(pfad, a, ra, 22)
        self._plaketten = [(b + QPointF(rb * 34, -13), "0..1" if self.optional else "1"),
                           (a + QPointF(ra * 36, -13), "1" if self.basis_art == "1:1" else "n")]
        self.setPath(pfad)
        stift = QPen(self.farbe(), 2.6 if self.betont else 1.9)
        if self.art == "n:m":
            stift.setStyle(Qt.DashLine)
        stift.setCapStyle(Qt.RoundCap)
        self.setPen(stift)
        self.update()

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-40, -24, 40, 24)

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(self.path())

    def paint(self, p: QPainter, option, widget=None):
        super().paint(p, option, widget)
        p.setRenderHint(QPainter.Antialiasing)
        for pos, text in self._plaketten:
            plakette(p, pos, text, self.farbe())

    def hoverEnterEvent(self, e):
        self.betont = True
        self.aktualisieren()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        self.betont = False
        self.aktualisieren()
        super().hoverLeaveEvent(e)

    @staticmethod
    def _strich(pfad: QPainterPath, p: QPointF, r: int, d: float):
        pfad.moveTo(p + QPointF(r * d, -8))
        pfad.lineTo(p + QPointF(r * d, 8))

    @staticmethod
    def _kreis(pfad: QPainterPath, p: QPointF, r: int):
        pfad.addEllipse(p + QPointF(r * 9, 0), 5, 5)
        pfad.moveTo(p)

    @staticmethod
    def _kraehenfuss(pfad: QPainterPath, p: QPointF, r: int):
        spitze = p + QPointF(r * 16, 0)
        for dy in (-10, 0, 10):
            pfad.moveTo(spitze)
            pfad.lineTo(p + QPointF(0, dy))


class Minikarte(QGraphicsView):
    """Übersicht unten rechts; Rechteck = sichtbarer Ausschnitt, Klick springt dorthin."""

    def __init__(self, haupt: "Ansicht"):
        super().__init__(haupt.scene(), haupt)
        self.haupt = haupt
        self.setFixedSize(220, 140)
        self.setInteractive(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.Antialiasing)
        self.setObjectName("minikarte")
        self.setStyleSheet(f"#minikarte {{ background: {theme.AKTUELL['feld']}; border: 1px solid {theme.AKTUELL['rand']};"
                           " border-radius: 8px; }")

    def anpassen(self):
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        self.viewport().update()

    def drawForeground(self, p: QPainter, rect):
        sicht = self.haupt.mapToScene(self.haupt.viewport().rect()).boundingRect()
        p.setPen(QPen(_farbe("akzent"), 0))
        farbe = _farbe("akzent")
        farbe.setAlpha(40)
        p.setBrush(farbe)
        p.drawRect(sicht)

    def mousePressEvent(self, e):
        self.haupt.centerOn(self.mapToScene(e.position().toPoint()))

    def mouseMoveEvent(self, e):
        if e.buttons():
            self.haupt.centerOn(self.mapToScene(e.position().toPoint()))


class Ansicht(QGraphicsView):
    """Strg+Mausrad zoomt, Ziehen auf freier Fläche verschiebt; Minikarte unten rechts."""

    def __init__(self, szene):
        super().__init__(szene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.minikarte = Minikarte(self)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.minikarte.viewport().update())
        self.verticalScrollBar().valueChanged.connect(lambda _: self.minikarte.viewport().update())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = self.minikarte
        m.move(self.viewport().width() - m.width() - 12, self.viewport().height() - m.height() - 12)
        m.viewport().update()
        leg = getattr(self, "legende", None)
        if leg is not None:
            leg.adjustSize()
            leg.move(self.viewport().width() - leg.width() - 12, 12)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            faktor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            neu = self.transform().m11() * faktor
            if 0.1 < neu < 4:
                self.scale(faktor, faktor)
                self.minikarte.viewport().update()
            return
        super().wheelEvent(e)

    def anpassen(self):
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-40, -150, 40, 170), Qt.KeepAspectRatio)  # Platz für Legende/Minikarte
            if self.transform().m11() > 1.2:
                self.resetTransform()
                self.centerOn(r.center())
        self.minikarte.anpassen()

    def zoom(self) -> float:
        return self.transform().m11()


class Legende(QFrame):
    """Ein-/ausklappbare Legende oben rechts."""

    def __init__(self, eltern):
        super().__init__(eltern)
        self.setObjectName("legende")
        self.offen = True
        self.setStyleSheet(f"#legende {{ background: {theme.AKTUELL['karte']}; border: 1px solid {theme.AKTUELL['rand']};"
                           " border-radius: 8px; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 4, 8, 6)
        v.setSpacing(3)
        self.knopf = QPushButton("Legende ▾")
        self.knopf.setFlat(True)
        self.knopf.setStyleSheet("padding: 2px 6px; font-size: 8.5pt; border: none; text-align: left;")
        self.knopf.clicked.connect(self.umschalten)
        v.addWidget(self.knopf)
        self.inhalt = QWidget()
        iv = QVBoxLayout(self.inhalt)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(3)
        for art, farbe, gestrichelt in (("1:1", "akzent", False), ("1:n", "blau", False), ("n:m", "neon", True),
                                         ("optional", "blau", False)):
            z = QLabel()
            stil = "dashed" if gestrichelt else "solid"
            z.setText(f"<span style='color:{theme.AKTUELL[farbe]}; font-size:8.5pt'><b>{'╍╍' if gestrichelt else '━━'}"
                      f"</b>&nbsp; {ART_TEXT[art]}</span>")
            iv.addWidget(z)
        v.addWidget(self.inhalt)
        self.adjustSize()

    def umschalten(self):
        self.offen = not self.offen
        self.inhalt.setVisible(self.offen)
        self.knopf.setText("Legende ▾" if self.offen else "Legende ▸")
        self.adjustSize()
        e = self.parentWidget()
        if e is not None:
            self.move(e.viewport().width() - self.width() - 12, 12)


# --- Dialoge --------------------------------------------------------------------------------------------------------
class DDLVorschau(QDialog):
    """Zeigt die erzeugten Anweisungen; ausgeführt wird nur nach Klick auf „Ausführen“."""

    def __init__(self, eltern, titel: str, anweisungen: list[str], hinweise: list[str], gesperrt: str = ""):
        super().__init__(eltern)
        self.setWindowTitle(titel)
        self.resize(760, 460)
        v = QVBoxLayout(self)
        v.addWidget(label("Vorschau – noch ist nichts geändert. Das SQL lässt sich hier anpassen.", "gedimmt", True))
        self.text = QPlainTextEdit(";\n\n".join(anweisungen) + (";" if anweisungen else ""))
        self.text.setObjectName("sqlEditor")
        v.addWidget(self.text, 1)
        for h in hinweise:
            v.addWidget(label("⚠ " + h, "hinweis", True))
        if gesperrt:
            v.addWidget(label(gesperrt, "fehlertext", True))
        knoepfe = QDialogButtonBox()
        self.k_los = knoepfe.addButton("Ausführen", QDialogButtonBox.AcceptRole)
        self.k_los.setObjectName("primaer")
        self.k_los.setEnabled(not gesperrt)
        knoepfe.addButton("In SQL-Editor", QDialogButtonBox.ActionRole).clicked.connect(lambda: self.done(2))
        knoepfe.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        knoepfe.accepted.connect(self.accept)
        knoepfe.rejected.connect(self.reject)
        v.addWidget(knoepfe)

    def sql(self) -> str:
        return self.text.toPlainText()


class TabelleDialog(QDialog):
    def __init__(self, eltern):
        super().__init__(eltern)
        self.setWindowTitle("Neue Tabelle")
        self.resize(620, 420)
        v = QVBoxLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name der Tabelle")
        v.addWidget(self.name)
        self.tab = QTableWidget(0, 4)
        self.tab.setHorizontalHeaderLabels(["Spalte", "Typ", "Primärschlüssel", "NOT NULL"])
        self.tab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self.tab, 1)
        v.addLayout(zeile(knopf("+ Spalte", lambda: self.zeile_neu()), knopf("Spalte entfernen", self._weg)))
        self.zeile_neu("id", "grosse_ganzzahl", True, True)
        self.zeile_neu("name", "text", False, True)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Vorschau")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        v.addWidget(b)

    def zeile_neu(self, name="", typ="text", pk=False, nn=False):
        r = self.tab.rowCount()
        self.tab.insertRow(r)
        self.tab.setItem(r, 0, QTableWidgetItem(name))
        c = QComboBox()
        c.setEditable(True)
        c.addItems(TYPEN)
        c.setCurrentText(typ)
        self.tab.setCellWidget(r, 1, c)
        for i, an in ((2, pk), (3, nn)):
            k = QCheckBox()
            k.setChecked(an)
            self.tab.setCellWidget(r, i, k)

    def _weg(self):
        if self.tab.currentRow() >= 0:
            self.tab.removeRow(self.tab.currentRow())

    def spalten(self) -> list[Spalte]:
        erg = []
        for r in range(self.tab.rowCount()):
            n = (self.tab.item(r, 0).text() if self.tab.item(r, 0) else "").strip()
            if n:
                pk = self.tab.cellWidget(r, 2).isChecked()
                erg.append(Spalte(n, self.tab.cellWidget(r, 1).currentText().strip(),
                                  not (self.tab.cellWidget(r, 3).isChecked() or pk), pk))
        return erg


class SpalteDialog(QDialog):
    def __init__(self, eltern, titel: str, s: Spalte | None = None, mit_standard: bool = True):
        super().__init__(eltern)
        self.setWindowTitle(titel)
        f = QFormLayout(self)
        self.name = QLineEdit(s.name if s else "")
        self.typ = QComboBox()
        self.typ.setEditable(True)
        self.typ.addItems(TYPEN)
        self.typ.setCurrentText(s.typ if s else "text")
        self.nn = QCheckBox("NOT NULL")
        self.nn.setChecked(bool(s and not s.nullbar))
        self.standard = QLineEdit()
        self.standard.setPlaceholderText("z. B. 0 oder 'offen' (optional)")
        f.addRow("Name", self.name)
        f.addRow("Typ", self.typ)
        f.addRow("", self.nn)
        if mit_standard:
            f.addRow("Standardwert", self.standard)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Vorschau")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def spalte(self) -> Spalte:
        return Spalte(self.name.text().strip(), self.typ.currentText().strip(), not self.nn.isChecked())


class BeziehungDialog(QDialog):
    def __init__(self, eltern, fk: erm.Fremdschluessel):
        super().__init__(eltern)
        self.setWindowTitle("Neue Beziehung")
        f = QFormLayout(self)
        f.addRow(label(f"{fk.tabelle}.{fk.spalten[0]}  →  {fk.ziel}.{fk.ziel_spalten[0]}", "karteTitel"))
        f.addRow(label("Die Spalte links verweist auf die Spalte rechts (viele → eins).", "gedimmt", True))
        self.name = QLineEdit(erm.fk_name(fk))
        self.loeschen, self.aendern = QComboBox(), QComboBox()
        for c in (self.loeschen, self.aendern):
            c.addItems(erm.AKTIONEN)
        f.addRow("Name", self.name)
        f.addRow("ON DELETE", self.loeschen)
        f.addRow("ON UPDATE", self.aendern)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Vorschau")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        f.addRow(b)


# --- Seite ----------------------------------------------------------------------------------------------------------
class DiagrammSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        self.modell: erm.Modell | None = None
        self.karten: dict[str, TabellenKarte] = {}
        self.linien: list[BeziehungsLinie] = []
        lay = leiste()
        self.setLayout(lay)
        self.kopf = Kopf("Diagramm", "Tabellen und Beziehungen. Kopf ziehen = verschieben, Spalte auf Spalte ziehen = "
                                     "Beziehung, Strg+Mausrad = Zoom.")
        lay.addWidget(self.kopf)
        self.schema = QComboBox()
        self.schema.setMinimumWidth(160)
        self.schema.activated.connect(lambda _: self.laden())
        self.k_neu = knopf("+ Tabelle", self.tabelle_neu, "primaer")
        self.k_spalte = knopf("+ Spalte", self.spalte_neu, tipp="Spalte zur markierten Tabelle hinzufügen")
        self.k_ki = knopf("Beziehungen vorschlagen", self.vorschlagen, "zweit",
                          "Fehlende Fremdschlüssel anhand von Namen und Typen – nur das Schema geht an die KI")
        export = knopf("Export …")
        from PySide6.QtWidgets import QMenu
        m = QMenu(export)
        m.addAction("PNG …", lambda: self.exportieren("png"))
        m.addAction("SVG …", lambda: self.exportieren("svg"))
        m.addSeparator()
        m.addAction("DbContext (C#, EF Core) …", self.dbcontext_exportieren)
        export.setMenu(m)
        self.info = label("", "gedimmt")
        self.modus = QComboBox()
        for k, n in MODI.items():
            self.modus.addItem(n, k)
        self.modus.currentIndexChanged.connect(self._modus_gewechselt)
        self.stil = QComboBox()
        self.stil.addItem("Datenbank-Stil", "db")
        self.stil.addItem("EF-Core-Stil", "ef")
        self.stil.setToolTip("EF-Core-Stil: Entitäten mit C#-Typen und Navigationen wie in EF Core Power Tools")
        self.stil.activated.connect(lambda _: self._stil_gewechselt())
        lay.addLayout(zeile(label("Schema", "gedimmt"), self.schema, knopf("Aktualisieren", self.laden),
                            knopf("Automatisch anordnen", self.auto_anordnen),
                            knopf("An Fenster anpassen", lambda: self.ansicht.anpassen()), self.modus, self.stil,
                            self.k_neu, self.k_spalte, self.k_ki, export, None, self.info, dehnen=False))
        self.szene = QGraphicsScene(self)
        self.szene.selectionChanged.connect(self._fokus_aktualisieren)
        self.ansicht = Ansicht(self.szene)
        self.legende = Legende(self.ansicht)
        self.ansicht.legende = self.legende
        self._schwebend = ""
        lay.addWidget(self.ansicht, 1)
        self._knoepfe()

    # Verbindung
    def _knoepfe(self):
        da = self.h.t is not None
        schreiben = da and not self.h.t.schreibschutz
        for k in (self.k_neu, self.k_spalte):
            k.setEnabled(schreiben)
        self.k_ki.setEnabled(da)

    def verbindung_gewechselt(self):
        self._knoepfe()
        if self.h.t is not None:
            self.stil.setCurrentIndex(self.stil.findData("ef" if self.h.t.art == "mssql" else "db"))
        self.schema.clear()
        self.szene.clear()
        self.karten, self.linien, self.modell = {}, [], None
        t = self.h.t
        if not t:
            self.info.setText("")
            return
        gemerkt = verbindungen.gemerktes_schema(self.h.cfg)

        def lauf():
            zahlen = t.tabellen_zahlen()
            return list(zahlen), *t.bestes_schema(gemerkt, zahlen)
        arbeiter.starte(lauf, self._schemas_da, lambda f: self.info.setText(f"Fehler: {f}"))

    def _schemas_da(self, d):
        schemas, standard, hinweis = d
        self.schema.blockSignals(True)
        self.schema.clear()
        self.schema.addItems(schemas)
        if standard in schemas:
            self.schema.setCurrentText(standard)
        self.schema.blockSignals(False)
        self.laden()
        if hinweis:
            self._hinweis = hinweis

    def laden(self):
        t = self.h.t
        if not t or not self.schema.currentText():
            return
        schema = self.schema.currentText()
        self.info.setText("Lade Schema …")
        arbeiter.starte(lambda: erm.lade(t, schema), self.zeichnen, lambda f: self.info.setText(f"Fehler: {f}"))

    # Zeichnen
    def zeichnen(self, m: erm.Modell):
        alte = {n: k.pos() for n, k in self.karten.items()}
        self.modell = m
        self.szene.clear()
        self.karten, self.linien = {}, []
        gespeichert = erm.positionen_laden(self.h.cfg.get("id", ""), m.schema)
        modus = self.modus.currentData() or "alle"
        stil = self.stil.currentData() or "db"
        navs = efcore.navigationen(m)
        karten_neu = {n: TabellenKarte(t, m.fk_spalten(n), m.zwischentabelle(n), modus, stil, m.schema, navs.get(n))
                      for n, t in m.tabellen.items()}
        auto = erm.auto_layout(m, BREITE, hoehe=lambda t: karten_neu[t.name].hoehe)
        for n, t in m.tabellen.items():
            k = karten_neu[n]
            if n in alte:
                k.setPos(alte[n])
            elif n in gespeichert:
                k.setPos(*gespeichert[n])
            else:
                k.setPos(*auto[n])
            k.bewegt.connect(self._linien_nachziehen)
            k.losgelassen.connect(self._positionen_merken)
            k.beziehung_gezogen.connect(self.beziehung_neu)
            k.spalte_doppelklick.connect(self.spalte_aendern)
            k.schwebt.connect(self._schweben)
            k.groesse_geaendert.connect(self._linien_nachziehen)
            self.szene.addItem(k)
            self.karten[n] = k
        for f in m.fks:
            if f.tabelle in self.karten and f.ziel in self.karten and f.spalten and f.ziel_spalten:
                nullbar = {s.name: s.nullbar for s in m.tabellen[f.tabelle].spalten}
                optional = any(nullbar.get(sp, False) for sp in f.spalten)
                lin = BeziehungsLinie(f, self.karten[f.tabelle], self.karten[f.ziel], m.kardinalitaet(f),
                                      optional=optional, n_zu_m=m.zwischentabelle(f.tabelle), stil=stil,
                                      ef_mult=efcore.multiplizitaet(m, f))
                self.szene.addItem(lin)
                self.linien.append(lin)
        self._versatz_verteilen()
        self.szene.setSceneRect(self.szene.itemsBoundingRect().adjusted(-200, -200, 400, 400))
        QTimer.singleShot(0, self.ansicht.anpassen)
        nm = len(m.n_zu_m())
        hinweis, self._hinweis = getattr(self, "_hinweis", ""), ""
        self.info.setText((hinweis + "  ·  " if hinweis else "")
                          + f"{len(m.tabellen)} Tabellen · {len(m.fks)} Beziehungen" + (f" · {nm} n:m" if nm else ""))

    def _linien_nachziehen(self):
        for lin in self.linien:
            lin.aktualisieren()
        self.ansicht.minikarte.viewport().update()

    def _versatz_verteilen(self):
        """Linien, die an derselben Karte enden, seitlich gestaffelt führen, damit sie sich nicht überdecken."""
        gruppen: dict[str, list[BeziehungsLinie]] = {}
        for lin in self.linien:
            gruppen.setdefault(lin.fk.ziel, []).append(lin)
        for liste in gruppen.values():
            liste.sort(key=lambda l: l.kind.scenePos().y())
            for i, lin in enumerate(liste):
                lin.versatz = (i - (len(liste) - 1) / 2) * 12
                lin.aktualisieren()

    def _schweben(self, name: str):
        self._schwebend = name
        self._fokus_aktualisieren()

    def _fokus_aktualisieren(self):
        """Schwebende oder markierte Tabelle + Nachbarn + Linien betonen, Rest dimmen."""
        try:
            markiert = [n for n, k in self.karten.items() if k.isSelected()]
        except RuntimeError:
            return
        fokus = self._schwebend or (markiert[0] if markiert else "")
        if not fokus:
            for k in self.karten.values():
                k.setOpacity(1.0)
            for lin in self.linien:
                lin.setOpacity(1.0)
            return
        nah = {fokus}
        for lin in self.linien:
            if fokus in (lin.fk.tabelle, lin.fk.ziel):
                nah |= {lin.fk.tabelle, lin.fk.ziel}
        for n, k in self.karten.items():
            k.setOpacity(1.0 if n in nah else 0.25)
        for lin in self.linien:
            lin.setOpacity(1.0 if fokus in (lin.fk.tabelle, lin.fk.ziel) else 0.12)

    def _stil_gewechselt(self):
        if self.modell:
            self._stil_manuell = True
            self.zeichnen(self.modell)
            self.auto_anordnen()

    def dbcontext_exportieren(self, pfad: str | None = None) -> str | None:
        if not self.modell:
            return None
        if pfad is None:
            pfad, _ = QFileDialog.getSaveFileName(self, "DbContext exportieren", f"{efcore.pascal(self.modell.schema or 'App')}DbContext.cs",
                                                  "C#-Datei (*.cs)")
            if not pfad:
                return None
        code = efcore.dbcontext(self.modell, namespace="Daten", context=f"{efcore.pascal(self.modell.schema or 'App')}DbContext")
        with open(pfad, "w", encoding="utf-8") as d:
            d.write(code)
        self.info.setText(f"DbContext gespeichert: {pfad}")
        return pfad

    def _modus_gewechselt(self, _i):
        modus = self.modus.currentData() or "alle"
        for k in self.karten.values():
            k.setze_modus(modus)
        if self.modell:
            self.auto_anordnen()

    def _positionen_merken(self):
        if self.modell:
            erm.positionen_speichern(self.h.cfg.get("id", ""), self.modell.schema,
                                     {n: (k.pos().x(), k.pos().y()) for n, k in self.karten.items()})

    def auto_anordnen(self):
        if not self.modell:
            return
        pos = erm.auto_layout(self.modell, BREITE, hoehe=lambda t: self.karten[t.name].hoehe)
        for n, k in self.karten.items():
            k.einrasten = False
            k.setPos(*pos[n])
            k.einrasten = True
        self._versatz_verteilen()
        self._positionen_merken()
        self.szene.setSceneRect(self.szene.itemsBoundingRect().adjusted(-200, -200, 400, 400))
        self.ansicht.anpassen()

    # Bearbeiten → DDL-Vorschau
    def _markierte(self) -> str | None:
        for n, k in self.karten.items():
            if k.isSelected():
                return n
        return None

    def tabelle_neu(self):
        if not self._bereit_schreiben():
            return
        d = TabelleDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        name, spalten = d.name.text().strip(), d.spalten()
        if not name or not spalten:
            meldung(self, "Unvollständig", "Name und mindestens eine Spalte angeben.")
            return
        self.vorschau("Neue Tabelle", erm.ddl_tabelle_neu(self.modell.art, self.modell.schema, name, spalten))

    def spalte_neu(self):
        if not self._bereit_schreiben():
            return
        tab = self._markierte()
        if not tab:
            meldung(self, "Keine Tabelle markiert", "Erst eine Tabelle im Diagramm anklicken.")
            return
        d = SpalteDialog(self, f"Neue Spalte in {tab}")
        if d.exec() != QDialog.Accepted or not d.name.text().strip():
            return
        try:
            anw = erm.ddl_spalte_neu(self.modell.art, self.modell.schema, tab, d.spalte(), d.standard.text().strip())
        except ValueError as e:
            meldung(self, "Nicht möglich", str(e), True)
            return
        self.vorschau(f"Spalte in {tab}", anw)

    def spalte_aendern(self, tab: str, spalte: str):
        if not self._bereit_schreiben():
            return
        s = next(x for x in self.modell.tabellen[tab].spalten if x.name == spalte)
        d = SpalteDialog(self, f"{tab}.{spalte} ändern", s, mit_standard=False)
        if d.exec() != QDialog.Accepted:
            return
        anw = erm.ddl_spalte_aendern(self.modell, tab, spalte, d.spalte())
        if not anw:
            meldung(self, "Keine Änderung", "Name, Typ und NOT NULL sind unverändert.")
            return
        self.vorschau(f"{tab}.{spalte} ändern", anw)

    def beziehung_neu(self, von_tab: str, von_sp: str, nach_tab: str, nach_sp: str):
        if not self._bereit_schreiben():
            return
        fk = erm.Fremdschluessel(von_tab, [von_sp], nach_tab, [nach_sp])
        d = BeziehungDialog(self, fk)
        if d.exec() != QDialog.Accepted:
            return
        fk.name = d.name.text().strip() or erm.fk_name(fk)
        fk.bei_loeschen, fk.bei_aendern = d.loeschen.currentText(), d.aendern.currentText()
        self.vorschau("Neue Beziehung", erm.ddl_fk_neu(self.modell, fk))

    def _bereit_schreiben(self) -> bool:
        if not self.h.t or not self.modell:
            meldung(self, "Keine Verbindung", "Erst mit einer Datenbank verbinden.")
            return False
        if self.h.t.schreibschutz:
            meldung(self, "Schreibschutz", "Diese Verbindung ist schreibgeschützt.", True)
            return False
        return True

    def vorschau(self, titel: str, anweisungen: list[str], extra_hinweise: list[str] = ()) -> None:
        t = self.h.t
        gesperrt = "Schreibschutz: Ausführen ist gesperrt." if t.schreibschutz else ""
        d = DDLVorschau(self, titel, anweisungen, [*extra_hinweise, *erm.hinweise(t.art, anweisungen)], gesperrt)
        erg = d.exec()
        sql = d.sql().strip()
        if erg == 2:
            self.h.editor.neuer_tab(sql)
            self.h.zeige(self.h.editor)
            return
        if erg != QDialog.Accepted or not sql:
            return
        p = sqlschutz.pruefe(sql)
        gruende = list(p.warnungen)
        if self.h.cfg.get("farbe") == PRODUKTIV:
            gruende.append("Die Verbindung ist als produktiv markiert.")
        if gruende and not rueckfrage(self, "Wirklich ausführen?", "\n".join(f"• {g}" for g in gruende)):
            return
        anw = treiber.anweisungen(sql)
        self.info.setText("Führe aus …")
        arbeiter.starte(lambda: erm.ausfuehren(t, anw), lambda _: self._ausgefuehrt(),
                        lambda f: (self.info.setText(""), meldung(self, "Fehlgeschlagen – nichts geändert"
                                                                  if t.art != "mysql" else "Fehlgeschlagen", f, True)))

    def _ausgefuehrt(self):
        self.info.setText("Ausgeführt.")
        self.h.explorer.neu_laden()
        self.laden()

    # Vorschläge (Heuristik + KI)
    def vorschlagen(self):
        if not self.h.t or not self.modell:
            meldung(self, "Keine Verbindung", "Erst mit einer Datenbank verbinden.")
            return
        m, t = self.modell, self.h.t
        lokal = erm.vorschlaege(m)
        e = verbindungen.einstellungen()
        anbieter, modell = e.get("ki_anbieter", "claude-api"), e.get("ki_modell", "")
        vorhanden = "\n".join(f.schluessel for f in m.fks)
        self.info.setText("KI prüft das Schema …")

        def lauf():
            kontext = ki.schema_kontext(t, m.schema)  # nur das Schema, keine Datenzeilen
            try:
                return ki.frage(anbieter, "beziehungen", kontext, modell, fks=vorhanden), ""
            except Exception as ex:
                return "", str(ex)
        arbeiter.starte(lauf, lambda d: self._vorschlaege_da(lokal, *d))

    def _vorschlaege_da(self, lokal: list[erm.Fremdschluessel], antwort: str, fehler: str):
        self.info.setText("")
        anw: list[str] = []
        for f in lokal:
            anw += [a for a in erm.ddl_fk_neu(self.modell, f) if a not in anw]
        ki_sql = ki.sql_aus_antwort(antwort) if antwort else ""
        hinweise = [f"Namensregel: {len(lokal)} Vorschlag/Vorschläge (z. B. „kunde_id“ → kunden.id)."]
        if ki_sql:
            anw.append(f"-- Vorschläge der KI:\n{ki_sql.rstrip(';')}")
            hinweise.append("Die KI-Vorschläge stehen am Ende – bitte prüfen, bevor du ausführst.")
        elif fehler:
            hinweise.append(f"KI nicht verfügbar: {fehler}")
        if not anw:
            meldung(self, "Keine Vorschläge", "Es fehlen offenbar keine Beziehungen.")
            return
        self.vorschau("Beziehungen vorschlagen", anw, hinweise)

    # Export
    def bild(self, skalierung: float = 2.0) -> QImage:
        rahmen = self.szene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        img = QImage(QSize(int(rahmen.width() * skalierung), int(rahmen.height() * skalierung)), QImage.Format_ARGB32)
        img.fill(_farbe("bg"))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.szene.clearSelection()
        self.szene.render(p, QRectF(0, 0, img.width(), img.height()), rahmen)
        p.end()
        return img

    def exportieren(self, art: str, pfad: str | None = None):
        if not self.karten:
            meldung(self, "Leer", "Kein Diagramm geladen.")
            return
        if pfad is None:
            pfad, _ = QFileDialog.getSaveFileName(self, "Diagramm exportieren", f"diagramm.{art}", f"*.{art}")
            if not pfad:
                return
        if art == "png":
            self.bild().save(pfad)
        else:
            from PySide6.QtSvg import QSvgGenerator
            rahmen = self.szene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
            g = QSvgGenerator()
            g.setFileName(pfad)
            g.setSize(rahmen.size().toSize())
            g.setViewBox(QRectF(0, 0, rahmen.width(), rahmen.height()))
            g.setTitle("Pi DB Studio – Diagramm")
            p = QPainter(g)
            p.fillRect(QRectF(0, 0, rahmen.width(), rahmen.height()), _farbe("bg"))
            self.szene.clearSelection()
            self.szene.render(p, QRectF(0, 0, rahmen.width(), rahmen.height()), rahmen)
            p.end()
        self.info.setText(f"Exportiert: {pfad}")

