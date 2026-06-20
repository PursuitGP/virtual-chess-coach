#!/usr/bin/env python3
"""Validate the repository-authored study database."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.study_database import study_database_status  # noqa: E402


def main() -> int:
    status = study_database_status()
    print(json.dumps(status, indent=2))
    return 0 if status["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
