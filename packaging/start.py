"""Einstieg für die gepackten Versionen (PyInstaller): startet Pi DB Studio wie `python -m dbstudio`."""
import sys

from dbstudio.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
