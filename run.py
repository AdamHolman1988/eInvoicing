"""Entry point for PyInstaller (one-file exe)."""
import sys

from msgvalidator.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
