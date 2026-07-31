#!/usr/bin/env python3
"""Deprecated entrypoint — use ``examples/run_search.py``.

Kept so older docs/scripts that invoke ``examples/fast_suggest.py`` still work.
"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("run_search.py")), run_name="__main__")
