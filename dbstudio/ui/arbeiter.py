"""Alles, was die Datenbank oder die KI anfasst, läuft im Hintergrund – die Oberfläche friert nie ein."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_LAUFEND: set = set()  # hält Signalobjekte am Leben, bis der Lauf fertig ist


class _Signale(QObject):
    fertig = Signal(object)
    fehler = Signal(str)


class _Lauf(QRunnable):
    def __init__(self, funktion, signale):
        super().__init__()
        self.funktion, self.signale = funktion, signale

    def run(self):
        try:
            erg = self.funktion()
        except Exception as e:  # Meldung an die Oberfläche statt Absturz
            text = str(e).strip() or type(e).__name__
            self.signale.fehler.emit(text)
        else:
            self.signale.fertig.emit(erg)


def starte(funktion, fertig=None, fehler=None) -> _Signale:
    s = _Signale()
    _LAUFEND.add(s)
    if fertig:
        s.fertig.connect(fertig)
    if fehler:
        s.fehler.connect(fehler)
    s.fertig.connect(lambda _: _LAUFEND.discard(s))
    s.fehler.connect(lambda _: _LAUFEND.discard(s))
    QThreadPool.globalInstance().start(_Lauf(funktion, s))
    return s


def warte_alle(ms: int = 30000) -> bool:
    return QThreadPool.globalInstance().waitForDone(ms)
