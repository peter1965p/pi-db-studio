"""Dialog „Neue Datenbank“ bzw. „Vorlage einspielen“: Vorlage wählen oder mit KI beschreiben, Vorschau, SQL prüfen."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QTabWidget, QVBoxLayout)

from .. import ki, treiber, verbindungen, vorlagen
from . import arbeiter
from .bausteine import knopf, label, meldung, zeile

KI_EIGEN = "__ki__"


class VorlagenDialog(QDialog):
    """neu=True: Name und Besitzer der neuen Datenbank; sonst wird in die aktuelle Datenbank eingespielt."""

    def __init__(self, eltern, art: str, neu: bool = True, rollen: list[str] | None = None, benutzer: str = ""):
        super().__init__(eltern)
        self.art, self.neu = art, neu
        self.modell: vorlagen.Modell | None = None
        self.setWindowTitle("Neue Datenbank" if neu else "Vorlage einspielen")
        self.resize(1100, 720)
        haupt = QHBoxLayout(self)
        links = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(9)
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. fahrradverleih")
        self.besitzer = QComboBox()
        for r in [benutzer] + [r for r in (rollen or []) if r != benutzer]:
            self.besitzer.addItem(r)
        if neu:
            form.addRow("Name", self.name)
            if art == "postgresql":
                form.addRow("Besitzer", self.besitzer)
        self.vorlage = QComboBox()
        self.vorlage.addItem("Leer – ohne Tabellen", "")
        for k, m in vorlagen.VORLAGEN.items():
            self.vorlage.addItem(f"{m.name}  ·  {len(m.tabellen)} Tabellen", k)
        self.vorlage.addItem("✨ Nur aus meiner Beschreibung (KI)", KI_EIGEN)
        self.vorlage.currentIndexChanged.connect(self._vorlage_gewaehlt)
        form.addRow("Vorlage", self.vorlage)
        links.addLayout(form)
        self.vorlage_text = label("", "gedimmt", True)
        links.addWidget(self.vorlage_text)
        links.addWidget(label("Mit KI anpassen oder neu entwerfen", "karteTitel"))
        self.wunsch = QPlainTextEdit()
        self.wunsch.setPlaceholderText("Beschreibe in eigenen Worten, z. B.:\n„Fahrradverleih: Kunden, Räder mit Rahmennummer und "
                                       "Kategorie, Buchungen mit Zeitraum und Preis, Wartungen je Rad, Gutscheine.“\n\n"
                                       "Mit gewählter Vorlage: „zusätzlich Lieferanten und Mehrsprachigkeit für Produkte“.")
        links.addWidget(self.wunsch, 1)
        self.beispiele = QCheckBox("Beispieldaten anlegen")
        self.beispiele.setChecked(True)
        links.addWidget(self.beispiele)
        e = verbindungen.einstellungen()
        self.anbieter, self.ki_modell = e.get("ki_anbieter") or "", e.get("ki_modell", "")
        if not self.anbieter or (self.anbieter == "claude-api" and not ki.api_schluessel()):
            # Nichts eingestellt (oder API ohne Schlüssel): den ersten Anbieter nehmen, der auf diesem Rechner geht
            vorhanden = [k for k, _ in ki.anbieter_liste() if k != "claude-api" or ki.api_schluessel()]
            self.anbieter = vorhanden[0] if vorhanden else "claude-api"
        name = dict(ki.anbieter_liste()).get(self.anbieter, self.anbieter) if hasattr(ki, "anbieter_liste") else self.anbieter
        self.k_ki = knopf("✨ Mit KI entwerfen", self.mit_ki, "primaer")
        links.addLayout(zeile(knopf("Vorschau", self.vorschau), self.k_ki))
        links.addWidget(label(f"KI: {name} (Einstellungen). An die KI gehen nur Vorlage und Beschreibung, keine Daten.", "gedimmt", True))
        haupt.addLayout(links, 2)

        rechts = QVBoxLayout()
        self.tabs = QTabWidget()
        self.ueber = QPlainTextEdit()
        self.ueber.setReadOnly(True)
        self.sql = QPlainTextEdit()
        self.sql.setPlaceholderText("Hier erscheint das SQL – vor dem Anlegen änderbar.")
        self.tabs.addTab(self.ueber, "Übersicht")
        self.tabs.addTab(self.sql, f"SQL ({treiber.ARTEN.get(art, art)})")
        rechts.addWidget(self.tabs, 1)
        self.status = label("", "gedimmt", True)
        rechts.addWidget(self.status)
        self.k_anlegen = knopf("Datenbank anlegen" if neu else "Einspielen", self._anlegen, "primaer")
        rechts.addLayout(zeile(None, knopf("Abbrechen", self.reject), self.k_anlegen))
        haupt.addLayout(rechts, 3)
        self._vorlage_gewaehlt()

    # --- Modell → Vorschau
    def _vorlage_gewaehlt(self, *_):
        k = self.vorlage.currentData()
        if k in vorlagen.VORLAGEN:
            m = vorlagen.VORLAGEN[k]
            self.vorlage_text.setText(m.beschreibung)
            self.k_ki.setText("✨ Vorlage mit KI anpassen")
            self._zeige(vorlagen.vorlage(k), [])
        else:
            self.vorlage_text.setText("Die KI entwirft das Schema aus deiner Beschreibung." if k == KI_EIGEN else "Eine leere Datenbank.")
            self.k_ki.setText("✨ Mit KI entwerfen")
            self.modell = None
            self.ueber.setPlainText("")
            self.sql.setPlainText("")

    def _zeige(self, m: vorlagen.Modell, hinweise: list[str]):
        if not self.beispiele.isChecked():
            m.daten = {}
        self.modell = m
        try:
            sql = vorlagen.ddl(m, self.art)
        except vorlagen.VorlagenFehler as e:
            return self.status.setText(str(e))
        kopf = f"{m.name}: {len(m.tabellen)} Tabellen, {sum(len(z) for z in m.daten.values())} Beispielzeilen\n{m.beschreibung}\n\n"
        self.ueber.setPlainText(kopf + vorlagen.uebersicht(m) + ("\n\nGeprüft und angepasst:\n• " + "\n• ".join(hinweise) if hinweise else ""))
        self.sql.setPlainText(";\n\n".join(sql) + (";" if sql else ""))
        self.status.setText(f"{len(sql)} Anweisungen. Prüfe sie – ausgeführt wird erst mit „{self.k_anlegen.text()}“.")

    def vorschau(self):
        k = self.vorlage.currentData()
        if k in vorlagen.VORLAGEN:
            self._zeige(vorlagen.vorlage(k), [])

    def mit_ki(self):
        k = self.vorlage.currentData()
        wunsch = self.wunsch.toPlainText().strip()
        basis = vorlagen.vorlage(k) if k in vorlagen.VORLAGEN else None
        if not wunsch and not basis:
            self.wunsch.setFocus()
            return self.status.setText("Beschreibe kurz, was die Datenbank können soll.")
        aufgabe = vorlagen.ki_aufgabe(wunsch, basis, treiber.ARTEN.get(self.art, self.art), self.beispiele.isChecked())
        self.k_ki.setEnabled(False)
        self.status.setText("Die KI entwirft das Schema … (das dauert je nach Modell bis zu einer Minute)")

        def da(antwort):
            self.k_ki.setEnabled(True)
            try:
                m, hinweise = vorlagen.aus_ki_antwort(antwort)
            except vorlagen.VorlagenFehler as e:
                return self.status.setText(str(e))
            self._zeige(m, hinweise)
            self.tabs.setCurrentIndex(0)

        def fehler(f):
            self.k_ki.setEnabled(True)
            self.status.setText(f"KI: {f}")
        arbeiter.starte(lambda: ki.frage(self.anbieter, "vorlage", "", self.ki_modell, aufgabe=aufgabe), da, fehler)

    # --- Ergebnis
    def _anlegen(self):
        if self.neu and not self.name.text().strip():
            self.name.setFocus()
            return self.status.setText("Bitte einen Namen für die Datenbank angeben.")
        if not self.neu and not self.sql.toPlainText().strip():
            return self.status.setText("Erst eine Vorlage wählen oder mit der KI entwerfen.")
        self.accept()

    def ergebnis(self) -> tuple[str, str, list[str]]:
        """(Name, Besitzer, Anweisungen) – die Anweisungen so, wie sie im SQL-Feld stehen (ggf. von Hand geändert)."""
        anweisungen = treiber.anweisungen(self.sql.toPlainText()) if self.sql.toPlainText().strip() else []
        besitzer = self.besitzer.currentText() if self.besitzer.currentIndex() > 0 else ""
        return self.name.text().strip(), besitzer, anweisungen


def zeige_fehler(eltern, f):
    meldung(eltern, "Vorlage", str(f), True)
