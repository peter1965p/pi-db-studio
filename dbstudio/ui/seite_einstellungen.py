"""Einstellungen: KI-Anbieter, Modell, API-Schlüssel (Schlüsselbund), Zeilenlimit."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QSpinBox, QWidget

from .. import ki, verbindungen
from .bausteine import Kopf, karte, knopf, label, leiste, zeile


class EinstellungenSeite(QWidget):
    def __init__(self, h):
        super().__init__()
        self.h = h
        lay = leiste()
        self.setLayout(lay)
        lay.addWidget(Kopf("Einstellungen", "Alles bleibt auf diesem Rechner. Schlüssel und Passwörter liegen im Schlüsselbund."))
        f, l = karte("KI-Assistent")
        form = QFormLayout()
        form.setSpacing(9)
        self.anbieter = QComboBox()
        self.modell = QLineEdit()
        self.modell.setPlaceholderText(f"leer = {ki.STANDARD_MODELL} (API) bzw. Standard von Claude Code")
        self.schluessel = QLineEdit()
        self.schluessel.setEchoMode(QLineEdit.Password)
        self.schluessel_status = label("", "gedimmt")
        form.addRow("Anbieter", self.anbieter)
        form.addRow("Modell", self.modell)
        form.addRow("Anthropic-API-Schlüssel", self.schluessel)
        form.addRow("", self.schluessel_status)
        l.addLayout(form)
        l.addWidget(label("„Claude (Claude Code)“ nutzt dein angemeldetes Claude Code statt eines API-Schlüssels. "
                          "„Lokal“ nutzt Ollama – dann verlässt nichts den Rechner.", "gedimmt", True))
        lay.addWidget(f)
        f2, l2 = karte("Ergebnisse")
        self.limit = QSpinBox()
        self.limit.setRange(100, 1_000_000)
        self.limit.setSingleStep(500)
        self.limit.setSuffix(" Zeilen je Abruf")
        l2.addLayout(zeile(label("Im SQL-Editor zuerst laden"), self.limit))
        lay.addWidget(f2)
        self.gespeichert = label("", "okText")
        lay.addLayout(zeile(knopf("Speichern", self.speichern, "primaer"), knopf("Anbieter neu suchen", self.laden), self.gespeichert))
        lay.addStretch(1)
        self.laden()

    def laden(self):
        e = verbindungen.einstellungen()
        self.anbieter.clear()
        for k, n in ki.anbieter_liste():
            self.anbieter.addItem(n, k)
        i = self.anbieter.findData(e.get("ki_anbieter", "claude-api"))
        self.anbieter.setCurrentIndex(max(i, 0))
        self.modell.setText(e.get("ki_modell", ""))
        self.limit.setValue(int(e.get("zeilenlimit", 1000)))
        self.schluessel.clear()
        self.schluessel.setPlaceholderText("leer lassen = unverändert")
        self.schluessel_status.setText("Schlüssel ist im Schlüsselbund hinterlegt." if ki.api_schluessel() else "Kein Schlüssel hinterlegt.")

    def speichern(self):
        if self.schluessel.text().strip():
            ki.setze_api_schluessel(self.schluessel.text().strip())
        verbindungen.setze_einstellungen({"ki_anbieter": self.anbieter.currentData() or "", "ki_modell": self.modell.text().strip(),
                                          "zeilenlimit": self.limit.value()})
        self.laden()
        self.h.editor.ki_anbieter_anzeigen()
        self.gespeichert.setText("Gespeichert.")
