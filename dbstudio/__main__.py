"""Start: python -m dbstudio"""

import argparse
import json
import sys


def argumente(argv: list[str]) -> argparse.Namespace:
    """--verbindung '{"art": "sqlite", "datei": "…"}' [--tabelle Orders] – Passwörter nie hier, die liegen im Schlüsselbund."""
    p = argparse.ArgumentParser(prog="dbstudio", add_help=True)
    p.add_argument("--verbindung", help="Verbindung als JSON: art, host, port, datenbank, benutzer, datei, name")
    p.add_argument("--tabelle", help="nach dem Verbinden diese Tabelle öffnen")
    p.add_argument("--version", action="store_true", help="Version ausgeben")
    p.add_argument("--selbsttest", action="store_true", help="Programm ohne Fenster laden und prüfen (für Builds)")
    a, _rest = p.parse_known_args(argv)
    if a.verbindung:
        a.verbindung = json.loads(a.verbindung)
        if not isinstance(a.verbindung, dict) or "passwort" in a.verbindung:
            raise SystemExit("--verbindung: JSON-Objekt ohne Passwort erwartet")
    return a


def selbsttest() -> int:
    """Lädt alles, was die App braucht (Treiber, Oberfläche, Bilder, Demo-Daten), öffnet das Hauptfenster unsichtbar und
    eine SQLite- und DuckDB-Datenbank im Speicher. Für die Build-Pipeline: Fehlt im Paket etwas, scheitert es hier."""
    import os
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("DB_STUDIO_CONFIG", tempfile.mkdtemp(prefix="dbstudio-selbsttest-"))
    from PySide6.QtWidgets import QApplication
    from . import __version__, access, treiber, vorlagen
    app = QApplication(sys.argv)
    from .ui import theme
    from .ui.fenster import Hauptfenster
    assert theme.ICON.exists() and access.NORTHWIND.exists(), "Bilder oder Demo-Daten fehlen im Paket"
    fenster = Hauptfenster()
    for art in ("sqlite", "duckdb"):
        t = treiber.oeffne({"art": art, "datei": ":memory:"})
        vorlagen.einspielen(t, vorlagen.ddl(vorlagen.vorlage("shop"), art))
        t.schliessen()
    for art in ("postgresql", "mysql", "mssql"):
        fehlt = treiber.verfuegbar(art)
        assert not fehlt, f"{art}: {fehlt}"
    fenster.close()
    app.quit()
    print(f"Pi DB Studio {__version__}: Selbsttest bestanden")
    return 0


def main() -> int:
    from PySide6.QtWidgets import QApplication

    args = argumente(sys.argv[1:])
    if args.version:
        from . import __version__
        print(f"Pi DB Studio {__version__}")
        return 0
    if args.selbsttest:
        return selbsttest()
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
