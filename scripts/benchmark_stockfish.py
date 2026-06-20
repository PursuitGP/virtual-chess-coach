#!/usr/bin/env python3
"""Benchmark the configured Stockfish contract without calling Lichess or Gemini."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "backend" / ".env")

from backend.analysis import (  # noqa: E402
    _parse_game,
    _position_records,
    evaluate_with_stockfish,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pgn",
        nargs="?",
        default=str(ROOT / "pgns" / "immortal_game_clean.pgn"),
    )
    parser.add_argument(
        "--plies",
        type=int,
        default=int(os.getenv("MAX_ANALYSIS_PLIES", "20")),
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=int(os.getenv("STOCKFISH_DEPTH", "24")),
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=float(os.getenv("STOCKFISH_MAX_SECONDS", "1.25")),
    )
    parser.add_argument(
        "--multipv",
        type=int,
        default=int(os.getenv("STOCKFISH_MULTIPV", "1")),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=int(os.getenv("STOCKFISH_THREADS", "1")),
    )
    parser.add_argument(
        "--hash-mb",
        type=int,
        default=int(os.getenv("STOCKFISH_HASH_MB", "64")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pgn_path = Path(args.pgn)
    game, _text, warnings = _parse_game(pgn_path.read_bytes())
    records, total_plies = _position_records(game, max_plies=args.plies)
    initial, provider = evaluate_with_stockfish(
        records,
        depth=args.depth,
        max_seconds=args.seconds,
        multipv=args.multipv,
        threads=args.threads,
        hash_mb=args.hash_mb,
    )
    print(
        json.dumps(
            {
                "pgn": str(pgn_path),
                "total_game_plies": total_plies,
                "analyzed_plies": len(records),
                "warnings": warnings,
                "provider": provider,
                "initial_evaluation": initial["evaluation"],
                "final_evaluation": records[-1]["stockfish"]["evaluation"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
