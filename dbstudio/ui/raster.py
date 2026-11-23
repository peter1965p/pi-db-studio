"""Tabellenmodelle: Ergebnisraster (nur lesen) und bearbeitbares Datenraster mit Übernehmen/Verwerfen."""

from __future__ import annotations

import datetime as dt
import json

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..austausch import _umwandeln
from . import theme

NULL_TEXT = "NULL"


def anzeige(w) -> str:
    if w is None:
        return NULL_TEXT
    if isinstance(w, (bytes, bytearray, memoryview)):
        b = bytes(w)
        return f"<{len(b)} Bytes> " + b[:16].hex()
    if isinstance(w, (dict, list)):
        return json.dumps(w, ensure_ascii=False)
    if isinstance(w, (dt.datetime, dt.date, dt.time)):
        return w.isoformat(sep=" ") if isinstance(w, dt.datetime) else w.isoformat()
    if isinstance(w, bool):
        return "true" if w else "false"
    return str(w)


class ErgebnisModell(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.spalten: list[str] = []
        self.zeilen: list[tuple] = []

    def setze(self, spalten, zeilen):
        self.beginResetModel()
        self.spalten, self.zeilen = list(spalten), list(zeilen)
        self.endResetModel()

    def anhaengen(self, zeilen):
        if not zeilen:
            return
        self.beginInsertRows(QModelIndex(), len(self.zeilen), len(self.zeilen) + len(zeilen) - 1)
        self.zeilen.extend(zeilen)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.zeilen)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.spalten)

    def wert(self, r, c):
        return self.zeilen[r][c]

    def data(self, index, rolle=Qt.DisplayRole):
        if not index.isValid():
            return None
        w = self.wert(index.row(), index.column())
        if rolle in (Qt.DisplayRole, Qt.EditRole):
            text = anzeige(w)
            return text if rolle == Qt.EditRole or len(text) <= 300 else text[:300] + " …"
        if rolle == Qt.ToolTipRole and w is not None and len(anzeige(w)) > 60:
            return anzeige(w)[:2000]
        if rolle == Qt.ForegroundRole and w is None:
            return QColor(theme.AKTUELL["gedimmt"])
        if rolle == Qt.FontRole and w is None:
            f = QFont()
            f.setItalic(True)
            return f
        if rolle == Qt.TextAlignmentRole and isinstance(w, (int, float)) and not isinstance(w, bool):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, abschnitt, richtung, rolle=Qt.DisplayRole):
        if rolle != Qt.DisplayRole:
            return None
        if richtung == Qt.Horizontal:
            return self.spalten[abschnitt] if abschnitt < len(self.spalten) else None
        return str(abschnitt + 1)


class TabellenModell(ErgebnisModell):
    """Bearbeitbar, wenn die Tabelle einen Primärschlüssel hat. Änderungen sammeln sich, bis übernommen wird."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meta = []          # list[Spalte]
        self.pk: list[int] = []
        self.aenderungen: dict[tuple[int, int], object] = {}
        self.geloescht: set[int] = set()
        self.neu_ab = 0         # Index, ab dem Zeilen neu sind
        self.nur_lesen = True

    def setze_tabelle(self, meta, zeilen, nur_lesen: bool):
        self.meta = list(meta)
        self.pk = [i for i, s in enumerate(meta) if s.pk]
        self.nur_lesen = nur_lesen or not self.pk
        self.aenderungen, self.geloescht = {}, set()
        self.setze([s.name for s in meta], zeilen)
        self.neu_ab = len(self.zeilen)

    @property
    def geaendert(self) -> bool:
        return bool(self.aenderungen or self.geloescht or len(self.zeilen) > self.neu_ab)

    def wert(self, r, c):
        return self.aenderungen.get((r, c), self.zeilen[r][c])

    def flags(self, index):
        f = super().flags(index)
        if not self.nur_lesen and index.row() not in self.geloescht:
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, wert, rolle=Qt.EditRole):
        if rolle != Qt.EditRole or self.nur_lesen:
            return False
        r, c = index.row(), index.column()
        neu = None if wert == NULL_TEXT else _umwandeln(wert, self.meta[c].generisch) if self.meta else wert
        if anzeige(self.zeilen[r][c]) == anzeige(neu):
            self.aenderungen.pop((r, c), None)
        else:
            self.aenderungen[(r, c)] = neu
        self.dataChanged.emit(index, index)
        return True

    def data(self, index, rolle=Qt.DisplayRole):
        if rolle == Qt.BackgroundRole:
            r = index.row()
            if r in self.geloescht:
                return QColor(theme.AKTUELL["warn_bg"])
            if r >= self.neu_ab:
                return QColor(theme.AKTUELL["ok_bg"])
            if (r, index.column()) in self.aenderungen:
                return QColor(theme.AKTUELL["aktiv"])
        if rolle == Qt.FontRole and index.row() in self.geloescht:
            f = QFont()
            f.setStrikeOut(True)
            return f
        if rolle == Qt.ForegroundRole and (index.row(), index.column()) in self.aenderungen:
            return QColor(theme.AKTUELL["akzent"])
        return super().data(index, rolle)

    def zeile_neu(self) -> int:
        r = len(self.zeilen)
        self.beginInsertRows(QModelIndex(), r, r)
        self.zeilen.append(tuple(None for _ in self.spalten))
        self.endInsertRows()
        return r

    def zeilen_loeschen(self, reihen: list[int]):
        for r in sorted(set(reihen), reverse=True):
            if r >= self.neu_ab:
                self.beginRemoveRows(QModelIndex(), r, r)
                del self.zeilen[r]
                self.aenderungen = {(rr if rr < r else rr - 1, c): v for (rr, c), v in self.aenderungen.items() if rr != r}
                self.endRemoveRows()
            else:
                self.geloescht ^= {r}
        if self.zeilen:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.zeilen) - 1, len(self.spalten) - 1))

    def verwerfen(self):
        self.beginResetModel()
        self.zeilen = self.zeilen[: self.neu_ab]
        self.aenderungen, self.geloescht = {}, set()
        self.endResetModel()

    def aenderungs_sql(self, t, schema, tabelle) -> list[tuple[str, tuple]]:
        """UPDATE/INSERT/DELETE mit Platzhaltern, über den Primärschlüssel."""
        ph, voll = t.platzhalter, t.voll(schema, tabelle)
        z = t.zitiere
        anweisungen = []
        wo = " AND ".join(f"{z(self.spalten[i])} = {ph}" for i in self.pk)
        for r in sorted(self.geloescht):
            anweisungen.append((f"DELETE FROM {voll} WHERE {wo}", tuple(self.zeilen[r][i] for i in self.pk)))
        reihen = sorted({r for r, _ in self.aenderungen if r < self.neu_ab and r not in self.geloescht})
        for r in reihen:
            cols = sorted(c for rr, c in self.aenderungen if rr == r)
            setz = ", ".join(f"{z(self.spalten[c])} = {ph}" for c in cols)
            werte = tuple(self.aenderungen[(r, c)] for c in cols) + tuple(self.zeilen[r][i] for i in self.pk)
            anweisungen.append((f"UPDATE {voll} SET {setz} WHERE {wo}", werte))
        for r in range(self.neu_ab, len(self.zeilen)):
            cols = [c for c in range(len(self.spalten)) if (r, c) in self.aenderungen]
            if not cols:
                continue
            anweisungen.append((t.einfuegen_sql(schema, tabelle, [self.spalten[c] for c in cols]),
                                tuple(self.aenderungen[(r, c)] for c in cols)))
        return anweisungen
