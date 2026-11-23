"""Visueller Beziehungsdesigner: ER-Diagramm mit Krähenfuß-Notation, Bearbeiten als DDL-Vorschau, Export PNG/SVG."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
                               QHeaderView, QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import erm, ki, sqlschutz, treiber, verbindungen
from ..treiber import Spalte
from . import arbeiter, theme
from .bausteine import Kopf, knopf, label, leiste, meldung, rueckfrage, zeile

BREITE = 250
KOPF_H = 34
ZEILE_H = 22
TYPEN = ["ganzzahl", "grosse_ganzzahl", "text", "kommazahl", "dezimal", "wahrheitswert", "datum", "zeitstempel",
         "zeit", "binaer", "json", "uuid"]
PRODUKTIV = "#e05252"


def _farbe(name: str) -> QColor:
    return QColor(theme.AKTUELL[name])


# --- Grafik-Elemente ------------------------------------------------------------------------------------------------
class TabellenKarte(QGraphicsObject):
    bewegt = Signal()
    losgelassen = Signal()
    beziehung_gezogen = Signal(str, str, str, str)  # von_tabelle, von_spalte, nach_tabelle, nach_spalte
    spalte_doppelklick = Signal(str, str)

    def __init__(self, tabelle: erm.Tabelle, fk_spalten: set[str], zwischen: bool):
        super().__init__()
        self.t, self.fk_spalten, self.zwischen = tabelle, fk_spalten, zwischen
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(2)
        self._ziehlinie: QGraphicsPathItem | None = None
        self._zieh_von: str | None = None
        self.setToolTip("Kopf ziehen = verschieben · von einer Spalte auf eine Spalte einer anderen Tabelle ziehen = "
                        "Beziehung · Doppelklick auf Spalte = ändern")

    @property
    def hoehe(self) -> float:
        return KOPF_H + ZEILE_H * len(self.t.spalten) + 8

    def boundingRect(self) -> QRectF:
        return QRectF(-1, -1, BREITE + 2, self.hoehe + 2)

    def spalte_y(self, name: str) -> float:
        for i, s in enumerate(self.t.spalten):
            if s.name == name:
                return KOPF_H + ZEILE_H * i + ZEILE_H / 2
        return KOPF_H / 2

    def spalte_bei(self, y: float) -> str | None:
        i = int((y - KOPF_H) // ZEILE_H)
        return self.t.spalten[i].name if y > KOPF_H and 0 <= i < len(self.t.spalten) else None

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.Antialiasing)
        rand = _farbe("akzent") if self.isSelected() else _farbe("rand")
        p.setPen(QPen(rand, 2 if self.isSelected() else 1))
        p.setBrush(_farbe("karte"))
        p.drawRoundedRect(QRectF(0, 0, BREITE, self.hoehe), 10, 10)
        kopf = QPainterPath()
        kopf.addRoundedRect(QRectF(0, 0, BREITE, KOPF_H), 10, 10)
        kopf.addRect(QRectF(0, KOPF_H - 10, BREITE, 10))
        p.fillPath(kopf, _farbe("blau" if self.zwischen else "aktiv"))
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.setPen(_farbe("auf_akzent") if self.zwischen else _farbe("akzent"))
        titel = self.t.name + ("   n:m" if self.zwischen else "")
        p.drawText(QRectF(12, 0, BREITE - 24, KOPF_H), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(f).elidedText(titel, Qt.ElideRight, BREITE - 24))
        normal, fett, klein = QFont(), QFont(), QFont()
        normal.setPointSizeF(9.5)
        fett.setPointSizeF(9.5)
        fett.setBold(True)
        klein.setPointSizeF(8.5)
        for i, s in enumerate(self.t.spalten):
            y = KOPF_H + ZEILE_H * i
            zeile = QRectF(0, y, BREITE, ZEILE_H)
            symbol = "🔑" if s.pk else ("↗" if s.name in self.fk_spalten else "")
            p.setFont(normal)
            p.setPen(_farbe("akzent") if s.pk else _farbe("blau"))
            p.drawText(QRectF(8, y, 20, ZEILE_H), Qt.AlignVCenter | Qt.AlignHCenter, symbol)
            p.setFont(fett if not s.nullbar else normal)
            p.setPen(_farbe("text"))
            p.drawText(QRectF(30, y, 120, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetricsF(p.font()).elidedText(s.name, Qt.ElideRight, 120))
            p.setFont(klein)
            p.setPen(_farbe("gedimmt"))
            typ = (s.typ or "").lower() + ("" if s.nullbar else " ·NN")
            p.drawText(QRectF(152, y, BREITE - 160, ZEILE_H), Qt.AlignVCenter | Qt.AlignRight,
                       QFontMetricsF(klein).elidedText(typ, Qt.ElideRight, BREITE - 160))
            if i:
                p.setPen(QPen(_farbe("rand"), 0.5))
                p.drawLine(zeile.topLeft() + QPointF(8, 0), zeile.topRight() - QPointF(8, 0))

    def itemChange(self, change, wert):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.bewegt.emit()
        return super().itemChange(change, wert)

    # Ziehen: Kopf verschiebt, Spalte zieht eine Beziehung
    def mousePressEvent(self, e):
        spalte = self.spalte_bei(e.pos().y())
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


class BeziehungsLinie(QGraphicsPathItem):
    """Linie vom FK (Kind, „viele“) zur referenzierten Spalte (Eltern, „eins“) mit Krähenfuß."""

    def __init__(self, fk: erm.Fremdschluessel, kind: TabellenKarte, eltern: TabellenKarte, art: str):
        super().__init__()
        self.fk, self.kind, self.eltern, self.art = fk, kind, eltern, art
        self.setZValue(1)
        self.setToolTip(f"{fk.tabelle}.{', '.join(fk.spalten)} → {fk.ziel}.{', '.join(fk.ziel_spalten)}  ({art})\n"
                        f"ON DELETE {fk.bei_loeschen} · ON UPDATE {fk.bei_aendern}")
        self.aktualisieren()

    def _seite(self, karte: TabellenKarte, spalte: str, rechts: bool) -> QPointF:
        return karte.mapToScene(QPointF(BREITE if rechts else 0, karte.spalte_y(spalte)))

    def aktualisieren(self):
        kx = self.kind.scenePos().x()
        ex = self.eltern.scenePos().x()
        if self.kind is self.eltern:  # Selbstbezug: Schleife rechts
            a = self._seite(self.kind, self.fk.spalten[0], True)
            b = self._seite(self.kind, self.fk.ziel_spalten[0], True)
            pfad = QPainterPath(a)
            pfad.cubicTo(a + QPointF(60, 0), b + QPointF(60, 0), b)
            richtung_a = richtung_b = 1
        else:
            kind_rechts = kx + BREITE / 2 < ex + BREITE / 2
            a = self._seite(self.kind, self.fk.spalten[0], kind_rechts)
            b = self._seite(self.eltern, self.fk.ziel_spalten[0], not kind_rechts)
            richtung_a = 1 if kind_rechts else -1
            richtung_b = -richtung_a
            dx = max(40.0, abs(b.x() - a.x()) / 2)
            pfad = QPainterPath(a)
            pfad.cubicTo(a + QPointF(richtung_a * dx, 0), b + QPointF(richtung_b * dx, 0), b)
        # Enden: „viele“ (Krähenfuß) beim Kind, „eins“ (Strich) beim Eltern; 1:1 beidseitig Strich
        self._eins(pfad, b, richtung_b)
        if self.art == "1:1":
            self._eins(pfad, a, richtung_a)
        else:
            self._kraehenfuss(pfad, a, richtung_a)
        self.setPath(pfad)
        self.setPen(QPen(_farbe("blau"), 1.6))

    @staticmethod
    def _eins(pfad: QPainterPath, p: QPointF, r: int):
        for d in (10, 15):
            pfad.moveTo(p + QPointF(r * d, -7))
            pfad.lineTo(p + QPointF(r * d, 7))

    @staticmethod
    def _kraehenfuss(pfad: QPainterPath, p: QPointF, r: int):
        spitze = p + QPointF(r * 14, 0)
        for dy in (-8, 0, 8):
            pfad.moveTo(spitze)
            pfad.lineTo(p + QPointF(0, dy))


class Ansicht(QGraphicsView):
    """Strg+Mausrad zoomt, Ziehen auf freier Fläche verschiebt."""

    def __init__(self, szene):
        super().__init__(szene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            faktor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            neu = self.transform().m11() * faktor
            if 0.15 < neu < 4:
                self.scale(faktor, faktor)
            return
        super().wheelEvent(e)

    def zoom(self) -> float:
        return self.transform().m11()


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
        export.setMenu(m)
        self.info = label("", "gedimmt")
        lay.addLayout(zeile(label("Schema", "gedimmt"), self.schema, knopf("Aktualisieren", self.laden),
                            knopf("Automatisch anordnen", self.auto_anordnen), self.k_neu, self.k_spalte, self.k_ki,
                            export, None, self.info, dehnen=False))
        self.szene = QGraphicsScene(self)
        self.ansicht = Ansicht(self.szene)
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
        self.schema.clear()
        self.szene.clear()
        self.karten, self.linien, self.modell = {}, [], None
        t = self.h.t
        if not t:
            self.info.setText("")
            return
        arbeiter.starte(lambda: (t.schemas(), t.standard_schema()), self._schemas_da,
                        lambda f: self.info.setText(f"Fehler: {f}"))

    def _schemas_da(self, d):
        schemas, standard = d
        self.schema.clear()
        self.schema.addItems(schemas)
        if standard in schemas:
            self.schema.setCurrentText(standard)
        self.laden()

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
        auto = erm.auto_layout(m, BREITE, hoehe=lambda t: KOPF_H + ZEILE_H * len(t.spalten) + 8)
        for n, t in m.tabellen.items():
            k = TabellenKarte(t, m.fk_spalten(n), m.zwischentabelle(n))
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
            self.szene.addItem(k)
            self.karten[n] = k
        for f in m.fks:
            if f.tabelle in self.karten and f.ziel in self.karten and f.spalten and f.ziel_spalten:
                lin = BeziehungsLinie(f, self.karten[f.tabelle], self.karten[f.ziel], m.kardinalitaet(f))
                self.szene.addItem(lin)
                self.linien.append(lin)
        self.szene.setSceneRect(self.szene.itemsBoundingRect().adjusted(-200, -200, 400, 400))
        nm = len(m.n_zu_m())
        self.info.setText(f"{len(m.tabellen)} Tabellen · {len(m.fks)} Beziehungen" + (f" · {nm} n:m" if nm else ""))

    def _linien_nachziehen(self):
        for lin in self.linien:
            lin.aktualisieren()

    def _positionen_merken(self):
        if self.modell:
            erm.positionen_speichern(self.h.cfg.get("id", ""), self.modell.schema,
                                     {n: (k.pos().x(), k.pos().y()) for n, k in self.karten.items()})

    def auto_anordnen(self):
        if not self.modell:
            return
        pos = erm.auto_layout(self.modell, BREITE, hoehe=lambda t: KOPF_H + ZEILE_H * len(t.spalten) + 8)
        for n, k in self.karten.items():
            k.setPos(*pos[n])
        self._positionen_merken()
        self.ansicht.fitInView(self.szene.itemsBoundingRect().adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)

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

