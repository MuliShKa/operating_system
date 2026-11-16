"""Run the automated OS5 unit and integration scenarios."""

from __future__ import annotations

import os
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"


def main() -> int:
    """Run every OS5 test module and return a process-friendly status code."""
    os.chdir(PROJECT_ROOT)
    suite = unittest.defaultTestLoader.discover(
        str(TESTS_DIR),
        pattern="test_*.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
