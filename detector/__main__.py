"""Allows running the tool as `python -m detector`."""
import sys

from detector.cli import main

if __name__ == "__main__":
    sys.exit(main())
