#!/usr/bin/env python3
"""Benchmark the bundled PGNs through the evidence pipeline.

Use --offline to isolate local Stockfish and motif performance from Lichess
network latency.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import analysis  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=14)
    parser.add_argument("--plies", type=int, default=20)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Treat Lichess as unavailable to measure local compute only.",
    )
    args = parser.parse_args()

    paths = sorted((ROOT / "pgns").glob("*.pgn"))
    if not paths:
        print("No PGN fixtures found.")
        return 1

    failures = 0
    for path in paths:
        started = time.monotonic()
        try:
            if args.offline:
                with patch.object(
                    analysis,
                    "fetch_lichess_explorer",
                    side_effect=requests.Timeout(),
                ):
                    result = analysis.build_analysis(
                        path.read_bytes(),
                        max_plies=args.plies,
                        stockfish_depth=args.depth,
                    )
            else:
                result = analysis.build_analysis(
                    path.read_bytes(),
                    max_plies=args.plies,
                    stockfish_depth=args.depth,
                )
            elapsed = time.monotonic() - started
            print(
                f"{path.name:28} {elapsed:6.2f}s "
                f"{result['analyzed_plies']:2}/{result['total_plies']:2} plies "
                f"warnings={len(result['warnings'])}"
            )
        except Exception as exc:
            failures += 1
            print(f"{path.name:28} FAILED {type(exc).__name__}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
