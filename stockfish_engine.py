import chess.engine

def analyze_position(board, depth=20):
    with chess.engine.SimpleEngine.popen_uci("/usr/local/bin/stockfish") as engine:
        result = engine.analyse(board, chess.engine.Limit(depth=depth))
    return result
