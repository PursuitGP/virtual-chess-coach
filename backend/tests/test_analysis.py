from __future__ import annotations

import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import chess
import chess.engine

from backend import analysis


ROOT = Path(__file__).resolve().parents[2]


class FakeStockfish:
    def __init__(self):
        self.fen = None
        self.calls = 0

    def analyse(self, board, _limit, multipv):
        self.calls += 1
        moves = list(board.legal_moves)[:multipv]
        if not moves:
            return [
                {
                    "score": chess.engine.PovScore(
                        chess.engine.Cp(self.calls * 20),
                        chess.WHITE,
                    ),
                    "pv": [],
                }
            ]
        return [
            {
                "score": chess.engine.PovScore(
                    chess.engine.Cp(self.calls * 20 - rank * 5),
                    chess.WHITE,
                ),
                "pv": [move],
            }
            for rank, move in enumerate(moves)
        ]

    def quit(self):
        return None


def explorer_fixture(fen, database, rating_groups=(), speeds=()):
    starting = fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP")
    if starting:
        return {
            "white": 60,
            "draws": 20,
            "black": 20,
            "moves": [
                {
                    "uci": "e2e4",
                    "san": "e4",
                    "white": 40,
                    "draws": 10,
                    "black": 10,
                    "averageRating": 2100,
                },
                {
                    "uci": "d2d4",
                    "san": "d4",
                    "white": 20,
                    "draws": 10,
                    "black": 10,
                },
            ],
        }
    return {
        "white": 40,
        "draws": 20,
        "black": 40,
        "opening": {"eco": "B00", "name": "King's Pawn Game"},
        "moves": [
            {
                "uci": "e7e5",
                "san": "e5",
                "white": 20,
                "draws": 10,
                "black": 30,
            }
        ],
    }


class AnalysisTests(unittest.TestCase):
    def build(self, pgn: bytes, max_plies: int = 20):
        with (
            patch.object(
                analysis,
                "create_stockfish",
                return_value=FakeStockfish(),
            ),
            patch.object(
                analysis,
                "fetch_lichess_explorer",
                side_effect=explorer_fixture,
            ),
        ):
            return analysis.build_analysis(
                pgn,
                max_plies=max_plies,
                stockfish_depth=14,
            )

    def test_builds_aligned_position_evidence(self):
        result = self.build(b"1. e4 e5 2. Nf3 Nc6 *")
        first = result["positions"][0]
        second = result["positions"][1]

        self.assertEqual(result["analyzed_plies"], 4)
        self.assertEqual(first["played_move"]["san"], "e4")
        self.assertEqual(first["side"], "white")
        self.assertEqual(first["stockfish"]["evaluation"]["display"], "+0.40")
        self.assertEqual(first["stockfish"]["eval_delta_cp"], 20)
        self.assertEqual(second["stockfish"]["eval_delta_cp"], 20)
        self.assertEqual(
            first["lichess"]["theory_status"],
            "common-master-move",
        )
        self.assertEqual(
            first["lichess"]["opening"]["name"],
            "King's Pawn Game",
        )
        self.assertEqual(
            first["lichess"]["opening_context"]["family"],
            "King's Pawn Game",
        )
        self.assertIn(
            first["lichess"]["practical_signal"]["classification"],
            {
                "master-aligned-and-sound",
                "common-rating-pool-choice",
            },
        )
        self.assertTrue(first["stockfish"]["top_lines"])

    def test_rating_filter_and_outcome_context_are_preserved(self):
        calls = []

        def fixture(fen, database, rating_groups=(), speeds=()):
            calls.append((database, rating_groups, speeds))
            return explorer_fixture(fen, database, rating_groups, speeds)

        with (
            patch.object(
                analysis,
                "create_stockfish",
                return_value=FakeStockfish(),
            ),
            patch.object(
                analysis,
                "fetch_lichess_explorer",
                side_effect=fixture,
            ),
        ):
            result = analysis.build_analysis(
                b"1. e4 e5 *",
                lichess_ratings=(1600,),
                lichess_speeds=("rapid",),
            )

        self.assertIn(("lichess", (1600,), ("rapid",)), calls)
        self.assertIn(("masters", (), ()), calls)
        played = result["positions"][0]["lichess"]["players"]["played_move"]
        self.assertIn("mover_score_pct", played)
        self.assertEqual(
            result["filters"]["lichess_rating_groups"],
            [1600],
        )

    def test_live_request_shape_uses_token_rating_and_speed_filters(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "white": 1,
            "draws": 0,
            "black": 0,
            "moves": [],
        }
        response.raise_for_status.return_value = None
        analysis.fetch_lichess_explorer.cache_clear()

        with (
            patch.dict(os.environ, {"LICHESS_TOKEN": "secret-token"}),
            patch.object(
                analysis._session,
                "get",
                return_value=response,
            ) as get,
        ):
            analysis.fetch_lichess_explorer(
                chess.Board().fen(),
                "lichess",
                (1600,),
                ("rapid",),
            )

        request = get.call_args
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer secret-token",
        )
        self.assertEqual(request.kwargs["params"]["ratings"], "1600")
        self.assertEqual(request.kwargs["params"]["speeds"], "rapid")
        self.assertTrue(
            request.args[0].startswith("https://explorer.lichess.org/")
        )

    def test_rejects_invalid_rating_group(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "rating"):
            analysis.normalize_rating_groups((1750,))

    def test_truncates_to_opening_window(self):
        pgn = (ROOT / "pgns" / "immortal_game_clean.pgn").read_bytes()
        result = self.build(pgn, max_plies=6)
        self.assertEqual(result["analyzed_plies"], 6)
        self.assertGreater(result["total_plies"], 6)
        self.assertTrue(result["truncated"])
        self.assertTrue(
            any("stopped after 6 plies" in warning for warning in result["warnings"])
        )

    def test_accepts_unicode_headers_and_headerless_pgn(self):
        unicode_result = self.build(
            '[White "José"]\n[Black "Zoë"]\n\n1. e4 e5 *'.encode("utf-8")
        )
        headerless_result = self.build(b"1. d4 d5 2. c4 *")
        self.assertEqual(unicode_result["metadata"]["White"], "José")
        self.assertEqual(headerless_result["positions"][0]["played_move"]["san"], "d4")

    def test_rejects_empty_and_move_less_input(self):
        with self.assertRaisesRegex(analysis.AnalysisError, "empty"):
            self.build(b"")
        with self.assertRaisesRegex(analysis.AnalysisError, "legal moves"):
            self.build(b"this is not a chess game")

    def test_lichess_timeout_preserves_stockfish_and_motifs(self):
        with (
            patch.object(
                analysis,
                "create_stockfish",
                return_value=FakeStockfish(),
            ),
            patch.object(
                analysis,
                "fetch_lichess_explorer",
                side_effect=requests.Timeout(),
            ),
        ):
            result = analysis.build_analysis(b"1. e4 e5 *")
        self.assertTrue(result["providers"]["stockfish"]["available"])
        self.assertFalse(result["providers"]["lichess"]["available"])
        self.assertTrue(any("Lichess" in warning for warning in result["warnings"]))
        self.assertEqual(
            result["positions"][0]["lichess"]["practical_signal"]["classification"],
            "statistics-unavailable",
        )

    def test_bundled_pgns_parse_and_motifs_do_not_crash(self):
        for path in sorted((ROOT / "pgns").glob("*.pgn")):
            with self.subTest(path=path.name):
                result = self.build(path.read_bytes(), max_plies=4)
                self.assertGreater(result["analyzed_plies"], 0)
                self.assertIn("motifs", result["positions"][0])


if __name__ == "__main__":
    unittest.main()
