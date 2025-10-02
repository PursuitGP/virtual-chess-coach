import pytest
from services.parser import parse_pgn

def test_simple_pgn():
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6"
    headers, moves = parse_pgn(pgn)
    assert len(moves) == 6
    assert moves[0]["san"] == "e4"
