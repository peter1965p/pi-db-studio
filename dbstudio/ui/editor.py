"""SQL-Editor: Syntax-Hervorhebung, Autovervollständigung (Schlüsselwörter, Tabellen, Spalten), Strg+Enter."""

from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from . import theme

SCHLUESSELWOERTER = """select from where and or not in is null like ilike between join inner left right full outer cross on using
group by order having limit offset fetch next rows only distinct as case when then else end union all intersect except
insert into values update set delete create table view index unique primary key foreign references drop alter add column
rename to truncate begin commit rollback transaction with recursive returning explain analyze exists any some desc asc
nulls first last default constraint check if cascade restrict schema database grant revoke over partition window
filter lateral true false coalesce cast count sum avg min max now current_date current_timestamp interval
varchar text integer bigint boolean numeric decimal date timestamp json jsonb serial""".split()
FUNKTIONEN = {"count", "sum", "avg", "min", "max", "coalesce", "cast", "now", "lower", "upper", "length", "substring",
              "round", "date_trunc", "extract", "string_agg", "array_agg", "json_agg", "row_number", "rank", "concat"}


class SqlHervorhebung(QSyntaxHighlighter):
    def __init__(self, dokument):
        super().__init__(dokument)
        self.neu_einfaerben()

    def neu_einfaerben(self):
        t = theme.AKTUELL

        def fmt(farbe, fett=False, kursiv=False):
            f = QTextCharFormat()
            f.setForeground(QColor(t[farbe]))
            if fett:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(kursiv)
            return f
        woerter = "|".join(w for w in SCHLUESSELWOERTER if w not in FUNKTIONEN)
        self.regeln = [
            (QRegularExpression(rf"\b({woerter})\b", QRegularExpression.CaseInsensitiveOption), fmt("s_wort", True)),
            (QRegularExpression(rf"\b({'|'.join(FUNKTIONEN)})(?=\s*\()", QRegularExpression.CaseInsensitiveOption), fmt("s_funktion")),
            (QRegularExpression(r"\b\d+(\.\d+)?\b"), fmt("s_zahl")),
            (QRegularExpression(r"'(?:[^']|'')*'"), fmt("s_text")),
            (QRegularExpression(r"--[^\n]*"), fmt("s_kommentar", kursiv=True)),
        ]
        self.kommentar = fmt("s_kommentar", kursiv=True)
        self.rehighlight()

    def highlightBlock(self, text):
        for muster, f in self.regeln:
            it = muster.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), f)
        # Blockkommentare über mehrere Zeilen
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start >= 0:
            ende = text.find("*/", start + (0 if self.previousBlockState() == 1 and start == 0 else 2))
            if ende < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.kommentar)
                break
            self.setFormat(start, ende - start + 2, self.kommentar)
            start = text.find("/*", ende + 2)


class SqlEditor(QPlainTextEdit):
    ausfuehren = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sqlEditor")
        self.setTabStopDistance(28)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText("SQL eingeben … Strg+Enter führt aus (Markierung oder alles). Strg+Leertaste ergänzt.")
        self.hervorhebung = SqlHervorhebung(self.document())
        self._liste = QStringListModel()
        self.completer = QCompleter(self._liste, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setFilterMode(Qt.MatchStartsWith)
        self.completer.activated.connect(self._einsetzen)
        self.setze_namen([], {})

    def setze_namen(self, tabellen: list[str], spalten: dict[str, list[str]]):
        self.tabellen, self.spalten_je = tabellen, spalten
        alle = {w.upper() for w in SCHLUESSELWOERTER} | set(tabellen) | {s for l in spalten.values() for s in l if s}
        self._liste.setStringList(sorted(alle, key=str.lower))

    def sql_zum_ausfuehren(self) -> str:
        c = self.textCursor()
        return (c.selectedText().replace(" ", "\n") if c.hasSelection() else self.toPlainText()).strip()

    def _wort_vor_cursor(self) -> str:
        c = self.textCursor()
        text = c.block().text()[: c.positionInBlock()]
        m = re.search(r"[\w.]*$", text)
        return m.group(0) if m else ""

    def _einsetzen(self, wort: str):
        c = self.textCursor()
        rest = self._wort_vor_cursor().split(".")[-1]
        c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(rest))
        c.insertText(wort)
        self.setTextCursor(c)

    def _zeige_vorschlaege(self, erzwingen=False):
        wort = self._wort_vor_cursor()
        if "." in wort:  # tabelle.spa → Spalten dieser Tabelle
            tab, praefix = wort.rsplit(".", 1)
            self.completer.setModel(QStringListModel(self.spalten_je.get(tab, []), self.completer))
        else:
            praefix = wort
            if self.completer.model() is not self._liste:
                self.completer.setModel(self._liste)
        if not erzwingen and len(praefix) < 2:
            self.completer.popup().hide()
            return
        self.completer.setCompletionPrefix(praefix)
        if self.completer.completionCount() == 0:
            self.completer.popup().hide()
            return
        r = self.cursorRect()
        r.setWidth(self.completer.popup().sizeHintForColumn(0) + self.completer.popup().verticalScrollBar().sizeHint().width() + 20)
        self.completer.complete(r)

    def keyPressEvent(self, e):
        popup = self.completer.popup()
        if popup.isVisible() and e.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Escape):
            e.ignore()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.ausfuehren.emit()
            return
        if e.key() == Qt.Key_Space and e.modifiers() & Qt.ControlModifier:
            self._zeige_vorschlaege(True)
            return
        super().keyPressEvent(e)
        if e.text() and (e.text().isalnum() or e.text() in "_."):
            self._zeige_vorschlaege()
        elif popup.isVisible() and not e.text().isalnum():
            popup.hide()
