#!/usr/bin/env python3
"""Resolve the runtime from this plugin copy, independently of checkout cwd."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from ai_sow_lite.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
