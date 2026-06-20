from __future__ import annotations

import io
import unittest

import chess.pgn

from backend.analysis import (
    _position_records,
    evaluate_with_stockfish,
    find_stockfish_path,
)


@unittest.skipUnless(find_stockfish_path(), "Stockfish is not installed")
class StockfishIntegrationTests(unittest.TestCase):
    def test_real_engine_returns_multipv_lines(self):
        game = chess.pgn.read_game(io.StringIO("1. e4 e5 *"))
        records, _total = _position_records(game, max_plies=2)
        initial = evaluate_with_stockfish(records, depth=8)

        self.assertTrue(initial["top_lines"])
        self.assertTrue(records[0]["stockfish"]["top_lines"])
        self.assertIsNotNone(records[0]["stockfish"]["mover_loss_cp"])
        self.assertTrue(
            records[0]["stockfish"]["top_lines"][0]["moves_uci"]
        )
        self.assertTrue(
            records[0]["stockfish"]["top_lines"][0]["moves_san"]
        )


if __name__ == "__main__":
    unittest.main()
