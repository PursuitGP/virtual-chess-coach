from __future__ import annotations

import io
import unittest

import chess.engine
import chess.pgn

from backend.analysis import _position_records, add_motif_evidence
from backend.motifs import detect_motifs


FRIED_LIVER = (
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 "
    "5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Kg8 *"
)


def add_engine_fixtures(records, *, mark_last_mate=False):
    evaluations = [
        25,
        30,
        29,
        35,
        25,
        18,
        29,
        29,
        16,
        125,
        106,
        134,
        102,
    ]
    for record, value in zip(records, evaluations):
        record["stockfish"] = {
            "evaluation": {
                "type": "cp",
                "value": value,
                "pawns": value / 100,
                "display": f"{value / 100:+.2f}",
            },
            "top_lines": [{"moves_uci": [], "moves_san": []}],
        }
    if mark_last_mate:
        records[-1]["stockfish"] = {
            "evaluation": {
                "type": "mate",
                "value": 3,
                "pawns": None,
                "display": "M3",
            },
            "top_lines": [{"moves_uci": [], "moves_san": []}],
        }


class MotifConfidenceTests(unittest.TestCase):
    def test_terminal_checkmate_is_attributed_to_the_winner(self):
        game = chess.pgn.read_game(
            io.StringIO("1. f3 e5 2. g4 Qh4#")
        )
        board = game.end().board()
        motifs = detect_motifs(
            board=board,
            move_number=4,
            eval_cp=0,
            sf_raw={"type": "mate", "value": 0, "winner": "black"},
            last_move_uci="d8h4",
        )
        self.assertEqual(motifs[0]["name"], "Checkmate")
        self.assertEqual(motifs[0]["side"], "black")
        self.assertIn("Black has delivered checkmate", motifs[0]["explanation"])

    def test_quiet_move_is_not_an_equal_trade(self):
        previous = chess.Board()
        board = previous.copy()
        board.push_uci("e2e4")
        motifs = detect_motifs(
            board=board,
            prev_board=previous,
            move_number=1,
            eval_cp=20,
            prev_eval=18,
            last_move_uci="e2e4",
        )
        self.assertNotIn("equal_trade", {motif["id"] for motif in motifs})

    def test_fried_liver_publishes_grounded_motifs(self):
        game = chess.pgn.read_game(io.StringIO(FRIED_LIVER))
        records, _total = _position_records(game, max_plies=20)
        add_engine_fixtures(records, mark_last_mate=True)
        warnings = []
        add_motif_evidence(records, warnings)
        by_ply = {
            record["ply"]: {motif["id"] for motif in record["motifs"]}
            for record in records
        }

        self.assertIn("diagonal_pressure", by_ply[5])
        self.assertIn("f2_f7_weakness", by_ply[7])
        self.assertIn("fork", by_ply[11])
        self.assertIn("attraction", by_ply[12])
        self.assertIn("absolute_pin", by_ply[12])
        self.assertEqual(by_ply[14], {"forced_mate"})

    def test_experimental_hanging_detector_is_suppressed(self):
        game = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3 *"))
        records, _total = _position_records(game, max_plies=3)
        add_engine_fixtures(records)
        warnings = []
        add_motif_evidence(records, warnings)
        ids = {motif["id"] for motif in records[-1]["motifs"]}
        self.assertNotIn("hanging_piece", ids)
        self.assertGreater(records[-1]["motif_candidates_suppressed"], 0)


if __name__ == "__main__":
    unittest.main()
