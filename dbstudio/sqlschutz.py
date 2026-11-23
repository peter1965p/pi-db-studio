"""Erkennt, ob SQL nur liest oder etwas ändert, und warnt vor gefährlichen Anweisungen.

Grundlage ist der Text ohne Kommentare und Stringinhalte, damit ein „DELETE“ in einem String nichts auslöst.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .treiber import anweisungen

LESEND = {"select", "with", "show", "explain", "describe", "desc", "pragma", "values", "table"}
DDL = {"create", "alter", "drop", "truncate", "rename", "comment", "grant", "revoke"}
AENDERND = {"insert", "update", "delete", "merge", "upsert", "replace", "copy", "call", "exec", "execute", "do",
            "vacuum", "reindex", "analyze", "set", "begin", "commit", "rollback", "attach", "detach", "load", "install"}


@dataclass
class Pruefung:
    aendert: bool = False
    warnungen: list[str] = field(default_factory=list)

    @property
    def gefaehrlich(self) -> bool:
        return bool(self.warnungen)


def ohne_literale(sql: str) -> str:
    """Kommentare entfernen, Strings und Bezeichner durch Platzhalter ersetzen."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"\$([A-Za-z_]*)\$.*?\$\1\$", " '' ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", " '' ", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', ' "x" ', sql)
    sql = re.sub(r"`[^`]*`", " `x` ", sql)
    sql = re.sub(r"\[[^\]]*\]", " [x] ", sql)
    return sql


def erstes_wort(sql: str) -> str:
    m = re.match(r"\s*\(*\s*([A-Za-z_]+)", ohne_literale(sql))
    return m.group(1).lower() if m else ""


def pruefe(sql: str) -> Pruefung:
    p = Pruefung()
    for anw in anweisungen(sql):
        rein = ohne_literale(anw)
        klein = " ".join(rein.lower().split())
        wort = erstes_wort(anw)
        if wort == "with":
            # WITH … UPDATE/DELETE/INSERT ändert trotzdem
            if re.search(r"\)\s*(insert|update|delete|merge)\b", klein):
                wort = re.search(r"\)\s*(insert|update|delete|merge)\b", klein).group(1)
        if wort == "explain" and " analyze" in klein[:40]:
            rest = re.sub(r"^explain\s*(\([^)]*\))?\s*(analyze\s+)?(verbose\s+)?", "", klein)
            if rest.split(" ", 1)[0] in AENDERND | DDL:
                p.aendert = True
                p.warnungen.append("EXPLAIN ANALYZE führt die ändernde Anweisung wirklich aus.")
            continue
        if wort in LESEND:
            if re.search(r"\binto\s+(?!outfile)\w", klein) and wort == "select":
                p.aendert = True  # SELECT … INTO neue_tabelle
            continue
        p.aendert = True
        if wort in ("update", "delete") and not re.search(r"\bwhere\b", klein):
            p.warnungen.append(f"{wort.upper()} ohne WHERE betrifft alle Zeilen der Tabelle.")
        if wort == "drop":
            p.warnungen.append("DROP löscht das Objekt samt Inhalt.")
        if wort == "truncate":
            p.warnungen.append("TRUNCATE leert die Tabelle vollständig.")
        if wort == "alter" and re.search(r"\bdrop\b", klein):
            p.warnungen.append("ALTER … DROP entfernt Spalten oder Einschränkungen.")
    return p
