#!/usr/bin/env python3
"""Development entrypoint; command ownership lives in micros_tooling."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from micros_tooling.cli import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
