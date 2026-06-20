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
        self.id = {"name": "Stockfish Test"}
        self.options = {}

    def configure(self, options):
        self.options.update(options)

    def analyse(self, board, _limit, multipv, **_kwargs):
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
                    "depth": 14,
                    "seldepth": 18,
                    "nodes": 1000,
                    "time": 0.01,
                }
            ]
        return [
            {
                "score": chess.engine.PovScore(
                    chess.engine.Cp(self.calls * 20 - rank * 5),
                    chess.WHITE,
                ),
                "pv": [move],
                "depth": 14,
                "seldepth": 18,
                "nodes": 1000,
                "time": 0.01,
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
        self.assertEqual(result["providers"]["stockfish"]["engine"], "Stockfish Test")
        self.assertEqual(result["providers"]["stockfish"]["achieved_depth"]["minimum"], 14)
        self.assertEqual(
            result["providers"]["stockfish"]["total_time_budget_seconds"],
            16.0,
        )

    def test_terminal_mate_score_uses_board_winner(self):
        game = chess.pgn.read_game(io.StringIO("1. f3 e5 2. g4 Qh4#"))
        board = game.end().board()
        evaluation = analysis._normalize_engine_score(
            chess.engine.PovScore(chess.engine.Mate(0), chess.WHITE),
            board,
        )
        self.assertEqual(evaluation["display"], "Checkmate")
        self.assertEqual(evaluation["winner"], "black")

    def test_decision_context_distinguishes_best_defense_from_mate_blunder(self):
        game = chess.pgn.read_game(
            io.StringIO(
                "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 "
                "5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Kg8 *"
            )
        )
        records, _total = analysis._position_records(game, max_plies=20)
        initial = {
            "evaluation": {
                "type": "cp",
                "value": 20,
                "pawns": 0.2,
                "display": "+0.20",
            },
            "top_lines": [
                {"moves_uci": ["e2e4"], "moves_san": ["e4"]}
            ],
        }
        for index, record in enumerate(records):
            next_record = records[index + 1] if index + 1 < len(records) else None
            record["stockfish"] = {
                "evaluation": {
                    "type": "cp",
                    "value": 20,
                    "pawns": 0.2,
                    "display": "+0.20",
                },
                "mover_loss_cp": 0,
                "top_lines": [
                    {
                        "moves_uci": (
                            [next_record["played_move"]["uci"]]
                            if next_record
                            else []
                        ),
                        "moves_san": (
                            [next_record["played_move"]["san"]]
                            if next_record
                            else []
                        ),
                    }
                ],
            }
            record["motifs"] = []

        records[11]["stockfish"]["evaluation"] = {
            "type": "cp",
            "value": 95,
            "pawns": 0.95,
            "display": "+0.95",
        }
        records[11]["stockfish"]["top_lines"] = [
            {
                "moves_uci": ["d1f3", "f7e6"],
                "moves_san": ["Qf3+", "Ke6"],
            }
        ]
        records[12]["stockfish"]["evaluation"] = {
            "type": "cp",
            "value": 105,
            "pawns": 1.05,
            "display": "+1.05",
        }
        records[12]["stockfish"]["top_lines"] = [
            {
                "moves_uci": ["f7e6", "b1c3"],
                "moves_san": ["Ke6", "Nc3"],
            }
        ]
        records[13]["stockfish"]["evaluation"] = {
            "type": "mate",
            "value": 3,
            "pawns": None,
            "display": "M3",
            "winner": "white",
        }
        records[13]["stockfish"]["mover_loss_cp"] = None

        analysis.add_decision_context(records, initial)

        qf3 = records[12]["decision_context"]
        self.assertTrue(qf3["played_matches_engine_first"])
        self.assertEqual(qf3["assessment_after"]["classification"], "slight_edge")
        self.assertEqual(qf3["material_after"]["leader"], "black")
        self.assertEqual(qf3["material_after"]["advantage_pawns"], 2)

        kg8 = records[13]["decision_context"]
        self.assertFalse(kg8["played_matches_engine_first"])
        self.assertEqual(kg8["engine_first_choice"]["san"], "Ke6")
        self.assertEqual(kg8["move_quality"], "allows_forced_mate")
        self.assertEqual(kg8["assessment_before"]["classification"], "slight_edge")
        self.assertEqual(kg8["assessment_after"]["classification"], "forced_mate")

    def test_total_stockfish_budget_bounds_long_openings(self):
        pgn = (ROOT / "pgns" / "immortal_game_clean.pgn").read_bytes()
        result = self.build(pgn, max_plies=20)
        provider = result["providers"]["stockfish"]
        self.assertAlmostEqual(
            provider["time_limit_seconds_per_position"],
            16 / 21,
        )

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
                analysis._sessions["lichess"],
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
            ) as fetch,
        ):
            result = analysis.build_analysis(b"1. e4 e5 *")
        self.assertEqual(fetch.call_count, 2)
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
