"""Farben und Stylesheet – dieselben Werte wie Job Agent und Päffgen-IT-Dashboard (Orange, Blau, Neon-Grün nur für NEU)."""

from pathlib import Path

DUNKEL = {
    "bg": "#1a1c22", "sidebar": "#1c1e24", "karte": "#252833", "feld": "#1d1f26", "rand": "#383b47",
    "text": "#e7e8ec", "gedimmt": "#9a9eab", "akzent": "#f5a623", "aktiv": "#2c303b", "blau": "#5aa0e6",
    "ok_bg": "#1c3b30", "ok": "#3ecf8e", "warn_bg": "#3f2a12", "warn": "#f5a623", "fehler": "#f0716a",
    "auf_akzent": "#1a1c22", "neon": "#39ff14", "code": "#16181d",
    # Syntaxfarben
    "s_wort": "#f5a623", "s_text": "#9fd36b", "s_zahl": "#5aa0e6", "s_kommentar": "#6b7080", "s_funktion": "#8cc4ff",
}
HELL = {
    "bg": "#f4f5f7", "sidebar": "#ebedf1", "karte": "#ffffff", "feld": "#f7f8fa", "rand": "#d5d8df",
    "text": "#1f2229", "gedimmt": "#5f6470", "akzent": "#b86e00", "aktiv": "#dcdfe6", "blau": "#1f5fa8",
    "ok_bg": "#d9f2e5", "ok": "#116b43", "warn_bg": "#fdebd0", "warn": "#8a5200", "fehler": "#b3261e",
    "auf_akzent": "#ffffff", "neon": "#1a8a00", "code": "#fbfbfc",
    "s_wort": "#b86e00", "s_text": "#2f7d1f", "s_zahl": "#1f5fa8", "s_kommentar": "#8a8f9c", "s_funktion": "#1f5fa8",
}
AKTUELL = DUNKEL
BILDER = Path(__file__).parent / "bilder"
PFEIL_HOCH = (BILDER / "pfeil_hoch.svg").as_posix()
PFEIL_RUNTER = (BILDER / "pfeil_runter.svg").as_posix()


def stylesheet(t: dict) -> str:
    global AKTUELL
    AKTUELL = t
    return f"""
    QWidget {{ color: {t['text']}; font-size: 13px; }}
    QMainWindow, #inhalt, QScrollArea, #scrollinhalt, QStackedWidget {{ background: {t['bg']}; border: none; }}
    #sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['rand']}; }}
    #gedimmt, #sidebarUnter {{ color: {t['gedimmt']}; }}
    #navSektion {{ color: {t['gedimmt']}; font-size: 11px; font-weight: 700; padding: 12px 0 4px 14px; }}
    #navEintrag {{ background: transparent; border: none; border-radius: 8px; padding: 9px 14px; text-align: left; }}
    #navEintrag:hover {{ background: {t['aktiv']}; }}
    #navEintrag:checked {{ background: {t['aktiv']}; color: {t['akzent']}; }}
    #titel {{ font-size: 21px; font-weight: 700; }}
    #karte {{ background: {t['karte']}; border: 1px solid {t['rand']}; border-radius: 12px; }}
    #karteTitel {{ font-size: 14px; font-weight: 700; }}
    #pill {{ background: {t['ok_bg']}; color: {t['ok']}; border-radius: 13px; padding: 5px 14px; }}
    #pillWarn {{ background: {t['warn_bg']}; color: {t['warn']}; border-radius: 13px; padding: 5px 14px; }}
    #pillFehler {{ background: {t['warn_bg']}; color: {t['fehler']}; border-radius: 13px; padding: 5px 14px; }}
    #pillNeu {{ color: {t['neon']}; font-weight: 700; }}
    #fehlertext {{ color: {t['fehler']}; }} #hinweis {{ color: {t['warn']}; }} #okText {{ color: {t['ok']}; }}
    #blau {{ color: {t['blau']}; }}
    QPushButton, QToolButton {{ background: transparent; border: 1px solid {t['rand']}; border-radius: 8px; padding: 6px 13px; }}
    QPushButton:hover, QToolButton:hover {{ background: {t['aktiv']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t['gedimmt']}; }}
    #primaer {{ border: 1px solid {t['akzent']}; color: {t['akzent']}; }}
    #primaer:disabled {{ border: 1px solid {t['rand']}; color: {t['gedimmt']}; }}
    #zweit {{ border: 1px solid {t['blau']}; color: {t['blau']}; }}
    #gefahr {{ border: 1px solid {t['fehler']}; color: {t['fehler']}; }}
    #zweit:disabled, #gefahr:disabled {{ border: 1px solid {t['rand']}; color: {t['gedimmt']}; }}
    #themaKnopf {{ background: transparent; border: none; color: {t['gedimmt']}; padding: 6px 10px; text-align: left; }}
    Schalter {{
        qproperty-farbeAn: {t['akzent']}; qproperty-farbeAus: {t['rand']}; qproperty-farbeKnopf: {t['auf_akzent']};
        qproperty-farbeSchrift: {t['text']}; qproperty-farbeGedimmt: {t['gedimmt']};
    }}
    QDialog, QMessageBox, QInputDialog {{ background: {t['karte']}; }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {t['feld']}; border: 1px solid {t['rand']}; border-radius: 8px; padding: 6px 10px;
        selection-background-color: {t['akzent']}; selection-color: {t['auf_akzent']};
    }}
    QPlainTextEdit, QTextEdit {{
        background: {t['feld']}; border: 1px solid {t['rand']}; border-radius: 8px; padding: 6px;
        selection-background-color: {t['akzent']}; selection-color: {t['auf_akzent']};
    }}
    #sqlEditor {{ background: {t['code']}; font-family: "JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace; font-size: 13px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {t['akzent']}; }}
    QSpinBox {{ padding-right: 22px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; height: 11px; background: transparent; }}
    QSpinBox::up-arrow {{ image: url({PFEIL_HOCH}); width: 8px; height: 5px; }}
    QSpinBox::down-arrow {{ image: url({PFEIL_RUNTER}); width: 8px; height: 5px; }}
    QComboBox QAbstractItemView {{ background: {t['karte']}; selection-background-color: {t['aktiv']}; }}
    QTableView, QTreeWidget, QListWidget {{
        background: {t['karte']}; border: 1px solid {t['rand']}; border-radius: 10px; gridline-color: {t['rand']};
        alternate-background-color: {t['feld']}; outline: none;
        selection-background-color: {t['aktiv']}; selection-color: {t['akzent']};
    }}
    QTreeWidget::item {{ padding: 3px 2px; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {t['aktiv']}; color: {t['akzent']}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: {t['feld']}; color: {t['gedimmt']}; border: none; border-bottom: 1px solid {t['rand']};
        border-right: 1px solid {t['rand']}; padding: 5px 8px; font-weight: 700;
    }}
    QTableCornerButton::section {{ background: {t['feld']}; border: none; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; border: none; padding: 7px 14px; color: {t['gedimmt']}; }}
    QTabBar::tab:selected {{ color: {t['akzent']}; border-bottom: 2px solid {t['akzent']}; }}
    QTabBar::tab:hover {{ color: {t['text']}; }}
    QSplitter::handle {{ background: {t['bg']}; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; }}
    QScrollBar::handle:vertical {{ background: {t['rand']}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; }}
    QScrollBar::handle:horizontal {{ background: {t['rand']}; border-radius: 4px; min-width: 24px; }}
    QProgressBar {{ background: {t['feld']}; border: 1px solid {t['rand']}; border-radius: 6px; text-align: center; height: 14px; }}
    QProgressBar::chunk {{ background: {t['akzent']}; border-radius: 5px; }}
    QToolTip {{ background: {t['karte']}; color: {t['text']}; border: 1px solid {t['rand']}; }}
    QMenu {{ background: {t['karte']}; border: 1px solid {t['rand']}; }}
    QMenu::item:selected {{ background: {t['aktiv']}; color: {t['akzent']}; }}
    """
