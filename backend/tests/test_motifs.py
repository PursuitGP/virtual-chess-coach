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

FRIED_LIVER_FULL = (
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 "
    "5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Kg8 "
    "8. Qxd5+ Qxd5 9. Bxd5+ Be6 10. Bxe6# *"
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


def add_neutral_engine_fixtures(records):
    for record in records:
        board = chess.Board(record["fen"])
        if board.is_checkmate():
            evaluation = {
                "type": "mate",
                "value": 0,
                "winner": "white" if board.turn == chess.BLACK else "black",
                "pawns": None,
                "display": "#",
            }
        else:
            evaluation = {
                "type": "cp",
                "value": 0,
                "pawns": 0,
                "display": "+0.00",
            }
        record["stockfish"] = {
            "evaluation": evaluation,
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

        weakness = next(
            motif
            for motif in records[6]["motifs"]
            if motif["id"] == "f2_f7_weakness"
        )
        self.assertEqual(weakness["extra"]["threat_move_san"], "Nxf7")
        self.assertEqual(
            {target["square"] for target in weakness["extra"]["fork_targets"]},
            {"d8", "h8"},
        )
        self.assertIn("bishop on c4", weakness["explanation"])
        self.assertIn("knight on g5", weakness["explanation"])

        queen_fork = next(
            motif
            for motif in records[12]["motifs"]
            if motif["id"] == "fork"
        )
        self.assertEqual(
            queen_fork["extra"]["forking_piece"],
            {"piece": "queen", "square": "f3"},
        )
        self.assertEqual(
            {target["square"] for target in queen_fork["extra"]["targets"]},
            {"d5", "f7"},
        )
        self.assertTrue(queen_fork["extra"]["includes_check"])

        forced_mate = records[13]["motifs"][0]
        self.assertEqual(
            forced_mate["extra"]["defending_king_square"],
            "g8",
        )
        self.assertEqual(
            forced_mate["extra"]["safe_adjacent_square_count"],
            0,
        )
        self.assertEqual(
            forced_mate["extra"]["adjacent_square_status"]["h7"]["status"],
            "friendly_occupied",
        )

    def test_full_fried_liver_emits_structured_evidence(self):
        game = chess.pgn.read_game(io.StringIO(FRIED_LIVER_FULL))
        records, _total = _position_records(game, max_plies=30)
        add_neutral_engine_fixtures(records)
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
        self.assertIn("fork", by_ply[13])
        self.assertIn("fork", by_ply[15])
        self.assertIn("fork", by_ply[17])
        self.assertIn("absolute_pin", by_ply[18])
        self.assertEqual(by_ply[19], {"forced_mate"})

        diagonal = next(
            motif
            for motif in records[4]["motifs"]
            if motif["id"] == "diagonal_pressure"
        )
        self.assertEqual(diagonal["extra"]["ray"], ["c4", "d5", "e6", "f7"])
        self.assertEqual(diagonal["extra"]["pressure_type"], "direct")

        f7 = next(
            motif
            for motif in records[6]["motifs"]
            if motif["id"] == "f2_f7_weakness"
        )
        self.assertEqual(f7["status"], "threatened")
        self.assertEqual(f7["extra"]["target_pawn"]["square"], "f7")
        self.assertEqual(f7["extra"]["candidate_follow_up"]["motif"], "fork")

        knight_fork = next(
            motif
            for motif in records[10]["motifs"]
            if motif["id"] == "fork"
        )
        self.assertEqual(
            knight_fork["extra"]["forking_piece"],
            {"piece": "knight", "square": "f7"},
        )
        self.assertEqual(
            {target["square"] for target in knight_fork["extra"]["targets"]},
            {"d8", "h8"},
        )
        self.assertNotIsInstance(knight_fork["extra"]["from"], int)

        pin = next(
            motif
            for motif in records[11]["motifs"]
            if motif["id"] == "absolute_pin"
        )
        self.assertEqual(pin["extra"]["pin_type"], "absolute")
        self.assertEqual(pin["extra"]["pinning_piece"]["square"], "c4")
        self.assertEqual(pin["extra"]["anchor_piece"]["square"], "f7")
        self.assertEqual(pin["extra"]["ray"], ["c4", "d5", "e6", "f7"])
        self.assertGreater(pin["extra"]["illegal_off_ray_move_count"], 0)

        attraction = next(
            motif
            for motif in records[11]["motifs"]
            if motif["id"] == "attraction"
        )
        self.assertEqual(attraction["extra"]["king_from"], "e8")
        self.assertEqual(attraction["extra"]["king_to"], "f7")
        self.assertTrue(attraction["extra"]["is_king_attraction"])

        mate = records[-1]["motifs"][0]
        self.assertEqual(mate["id"], "forced_mate")
        self.assertEqual(mate["status"], "played")
        self.assertEqual(mate["extra"]["checking_piece"]["square"], "e6")
        self.assertFalse(mate["extra"]["can_capture_checker"])
        self.assertFalse(mate["extra"]["can_block_check"])

    def test_absolute_pin_keeps_same_ray_mobility_detail(self):
        board = chess.Board("k3r3/8/8/8/8/8/4Q3/4K3 w - - 0 1")
        motifs = detect_motifs(
            board=board,
            prev_board=board.copy(stack=False),
            move_number=1,
            eval_cp=0,
            prev_eval=0,
            include_experimental=True,
        )
        pin = next(motif for motif in motifs if motif["id"] == "absolute_pin")

        self.assertEqual(pin["side"], "white")
        self.assertEqual(pin["extra"]["pinning_piece"]["square"], "e8")
        self.assertEqual(pin["extra"]["pinned_piece_detail"]["square"], "e2")
        self.assertEqual(pin["extra"]["anchor_piece"]["square"], "e1")
        self.assertEqual(pin["extra"]["pin_type"], "absolute")
        self.assertEqual(pin["extra"]["leave_line_status"], "illegal_exposes_king")
        self.assertTrue(pin["extra"]["legal_along_ray_moves"])
        self.assertNotIn("relative_pin", {motif["id"] for motif in motifs})

    def test_blocked_bishop_does_not_publish_diagonal_pressure(self):
        previous = chess.Board(
            "rnbqkbnr/ppp2ppp/8/3pp3/4P3/8/PPPP1PPP/RNBQKBNR "
            "w KQkq - 0 3"
        )
        board = previous.copy()
        board.push_uci("f1c4")
        motifs = detect_motifs(
            board=board,
            prev_board=previous,
            move_number=5,
            eval_cp=0,
            prev_eval=0,
            last_move_uci="f1c4",
        )
        self.assertNotIn("diagonal_pressure", {motif["id"] for motif in motifs})

    def test_non_sacrificial_king_capture_is_not_attraction(self):
        previous = chess.Board("4k3/5N2/8/8/8/8/8/4K3 b - - 0 1")
        board = previous.copy()
        board.push_uci("e8f7")
        motifs = detect_motifs(
            board=board,
            prev_board=previous,
            move_number=1,
            eval_cp=0,
            prev_eval=0,
            last_move_uci="e8f7",
            prev_move_uci="a2a3",
        )
        self.assertNotIn("attraction", {motif["id"] for motif in motifs})

    def test_single_target_attack_is_not_a_fork(self):
        board = chess.Board("k7/8/8/5q2/3N4/8/8/4K3 w - - 0 1")
        motifs = detect_motifs(
            board=board,
            prev_board=board.copy(stack=False),
            move_number=1,
            eval_cp=0,
            prev_eval=0,
        )
        self.assertNotIn("fork", {motif["id"] for motif in motifs})

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
