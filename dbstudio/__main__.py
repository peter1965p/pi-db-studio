"""Start: python -m dbstudio"""

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Pi DB Studio")
    app.setOrganizationName("Päffgen IT")
    app.setDesktopFileName("db-studio")
    from .ui.fenster import Hauptfenster

    fenster = Hauptfenster()
    fenster.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
