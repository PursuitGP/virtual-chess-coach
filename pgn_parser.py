# backend/pgn_parser.py
import chess.pgn
import io

print("Script started")

def parse_pgn_to_fens_from_text(pgn_text):
    """
    Parse PGN text into FEN strings.
    Returns a list like:
    [
        { "move": 1, "fen": "..." },  # after move 1
        { "move": 2, "fen": "..." },  # after move 2
        ...
    ]
    Only parses one game in the PGN text.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        print("No valid game found in PGN")
        return []

    board = game.board()
    fens = []
    move_number = 0
    for move in game.mainline_moves():
        board.push(move)
        move_number += 1
        fens.append({
            "move": move_number,
            "fen": board.fen()
        })
    return fens

def parse_pgn_file(path):
    """
    Opens a PGN file and parses it into FENs.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_pgn_to_fens_from_text(f.read())
    except FileNotFoundError:
        print(f"File not found: {path}")
        return []
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return []

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pgn_parser.py path/to/game.pgn")
        sys.exit(1)

    data = parse_pgn_file(sys.argv[1])
    if not data:
        print("No moves parsed.")
        sys.exit(0)

    for item in data:
        print(f"Move {item['move']}: {item['fen']}")
