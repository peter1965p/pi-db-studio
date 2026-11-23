"""0.2.2: Zoom (Mausrad, Tasten, Grenzen), Anpassen mit Lesbarkeit, Layout-Lücke, Layout-Version."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from dbstudio import erm
from dbstudio.treiber import Spalte
from dbstudio.ui.seite_diagramm import ZOOM_LESBAR, ZOOM_MAX, ZOOM_MIN, Ansicht


def _ansicht(qtbot, breite=4000, hoehe=3000):
    s = QGraphicsScene()
    s.addItem(QGraphicsRectItem(QRectF(0, 0, breite, hoehe)))
    a = Ansicht(s)
    a._test_szene = s  # Szene am Leben halten
    a.resize(1000, 700)
    qtbot.addWidget(a)
    a.show()
    return a


def _rad(a, dy, mod=Qt.NoModifier):
    pos = QPointF(500, 350)
    ev = QWheelEvent(pos, a.mapToGlobal(QPoint(500, 350)).toPointF(), QPoint(0, 0), QPoint(0, dy), Qt.NoButton, mod,
                     Qt.NoScrollPhase, False)
    a.wheelEvent(ev)


def test_zoom_grenzen_und_schritte(qtbot):
    a = _ansicht(qtbot)
    a.setze_zoom(1.0)
    a.zoom_schritt(1)
    assert a.zoom() > 1.0
    a.setze_zoom(99)
    assert abs(a.zoom() - ZOOM_MAX) < 1e-6
    a.setze_zoom(0.001)
    assert abs(a.zoom() - ZOOM_MIN) < 1e-6
    a.setze_zoom(1.0)
    assert a.zoomleiste.k_prozent.text() == "100 %"


def test_mausrad_zoomt_ohne_strg_shift_scrollt(qtbot):
    a = _ansicht(qtbot)
    a.setze_zoom(1.0)
    _rad(a, 120)
    assert a.zoom() > 1.0
    z = a.zoom()
    h = a.horizontalScrollBar().value()
    _rad(a, -120, Qt.ShiftModifier)
    assert a.zoom() == z and a.horizontalScrollBar().value() != h


def test_anpassen_lesbar_und_voll(qtbot):
    a = _ansicht(qtbot, 6000, 4000)
    a.anpassen(lesbar=True)
    assert a.zoom() >= ZOOM_LESBAR - 1e-6          # nicht winzig – lieber scrollen
    a.anpassen(lesbar=False)
    assert a.zoom() < ZOOM_LESBAR                   # „Anpassen“-Knopf zeigt alles
    klein = _ansicht(qtbot, 300, 200)
    klein.anpassen(lesbar=True)
    assert klein.zoom() <= 1.0                      # kleine Diagramme nicht aufblasen


def test_unverbundene_tabellen_neben_dem_block():
    m = erm.Modell(art="sqlite", schema="main")
    def t(n, k=3):
        m.tabellen[n] = erm.Tabelle(n, [Spalte("id", "integer", False, True)] + [Spalte(f"s{i}", "text") for i in range(k)])
    for n in ("firmen", "entwuerfe", "fakten", "chunks", "lektionen", "a", "b", "c", "d", "e"):
        t(n, 8)
    for kind in ("entwuerfe", "fakten", "chunks", "lektionen"):
        m.tabellen[kind].spalten.append(Spalte("firma_id", "integer"))
        m.fks.append(erm.Fremdschluessel(kind, ["firma_id"], "firmen", ["id"]))
    h = lambda tab: 40 + 22 * len(tab.spalten)  # noqa: E731
    pos = erm.auto_layout(m, 250, hoehe=h)
    block = ("firmen", "entwuerfe", "fakten", "chunks", "lektionen")
    block_rechts = max(pos[n][0] for n in block) + 250
    block_oben = min(pos[n][1] for n in block)
    block_unten = max(pos[n][1] + h(m.tabellen[n]) for n in block)
    for n in "abcde":
        assert pos[n][0] >= block_rechts                       # rechts daneben …
        assert pos[n][1] <= block_unten                       # … nicht weit darunter
        assert pos[n][1] >= block_oben - 1
    fx = pos["firmen"][0]
    assert min(pos[n][0] for n in block) < fx < max(pos[n][0] for n in block)  # Hub in der Mitte


def test_alte_positionen_werden_ignoriert(tmp_path):
    import json
    from dbstudio import verbindungen
    d = verbindungen.ordner() / "diagramme.json"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps({"v1|s": {"firmen": [0, 5000]}}))
    assert erm.positionen_laden("v1", "s") == {}
    erm.positionen_speichern("v1", "s", {"firmen": (1.0, 2.0)})
    assert erm.positionen_laden("v1", "s") == {"firmen": (1.0, 2.0)}


def test_zoomleiste_ziehen_merken_zuruecksetzen(qtbot):
    from dbstudio import verbindungen
    a = _ansicht(qtbot)
    z, m = a.zoomleiste, a.minikarte
    start, mini = z.pos(), m.pos()
    z.verschiebe_nach(QPoint(40, 30))
    z.position_merken()
    assert z.pos() == QPoint(40, 30) and m.pos() == mini
    z.verschiebe_nach(QPoint(-500, 99999))  # bleibt im Sichtbereich
    assert z.x() == 0 and z.y() == a.viewport().height() - z.height()
    z.verschiebe_nach(QPoint(40, 30))
    z.position_merken()
    b = _ansicht(qtbot)  # neue Ansicht liest die gemerkte Position
    b._platzieren()
    assert b.zoomleiste.pos() == QPoint(40, 30)
    z.griff.mouseDoubleClickEvent(type("E", (), {"accept": lambda self: None})())
    assert z.pos() == start and verbindungen.einstellungen()["zoomleiste_abstand"] is None
