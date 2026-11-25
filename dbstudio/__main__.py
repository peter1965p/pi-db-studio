"""Start: python -m dbstudio"""

import argparse
import json
import sys


def argumente(argv: list[str]) -> argparse.Namespace:
    """--verbindung '{"art": "sqlite", "datei": "…"}' [--tabelle Orders] – Passwörter nie hier, die liegen im Schlüsselbund."""
    p = argparse.ArgumentParser(prog="dbstudio", add_help=True)
    p.add_argument("--verbindung", help="Verbindung als JSON: art, host, port, datenbank, benutzer, datei, name")
    p.add_argument("--tabelle", help="nach dem Verbinden diese Tabelle öffnen")
    a, _rest = p.parse_known_args(argv)
    if a.verbindung:
        a.verbindung = json.loads(a.verbindung)
        if not isinstance(a.verbindung, dict) or "passwort" in a.verbindung:
            raise SystemExit("--verbindung: JSON-Objekt ohne Passwort erwartet")
    return a


def main() -> int:
    from PySide6.QtWidgets import QApplication

    args = argumente(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("Pi DB Studio")
    app.setOrganizationName("Päffgen IT")
    app.setDesktopFileName("db-studio")
    from PySide6.QtGui import QIcon
    from .ui import theme
    app.setWindowIcon(QIcon(str(theme.ICON)))
    from .ui.fenster import Hauptfenster

    fenster = Hauptfenster()
    fenster.show()
    if args.verbindung:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: fenster.oeffne_von_aussen(args.verbindung, args.tabelle))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
