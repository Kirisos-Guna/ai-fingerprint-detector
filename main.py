#!/usr/bin/env python3
"""Convenience entry point: `python main.py <url> [options]`.

Delegates to the detector package CLI (same as `python -m detector`).
"""
import sys

from detector.cli import main

if __name__ == "__main__":
    sys.exit(main())
