import io
import chess.pgn

def parse_pgn(pgn_text: str):
    """
    Parse PGN into moves, SAN, UCI, and FENs.
    Returns: list of moves with metadata.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return None, []

    board = game.board()
    moves = []
    for ply, move in enumerate(game.mainline_moves(), start=1):
        san = board.san(move)
        uci = move.uci()
        fen_before = board.fen()
        board.push(move)
        fen_after = board.fen()
        moves.append({
            "ply": ply,
            "san": san,
            "uci": uci,
            "fen_before": fen_before,
            "fen_after": fen_after
        })
    return game.headers, moves
