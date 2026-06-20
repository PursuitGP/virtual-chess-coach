#!/usr/bin/env python3
"""Verify external providers without exposing credentials."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "backend" / ".env")

from backend.ai_coach import verify_gemini_connection  # noqa: E402
from backend.analysis import verify_lichess_connection  # noqa: E402


def main() -> int:
    results = {
        "gemini": verify_gemini_connection(),
        "lichess": verify_lichess_connection(),
    }
    print(json.dumps(results, indent=2))
    return 0 if all(value.get("verified") for value in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
