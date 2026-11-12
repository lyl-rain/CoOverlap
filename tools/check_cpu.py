"""Compatibility entry point for the function-organized CPU checks."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.runner import main

if __name__ == '__main__':
    raise SystemExit(main())
