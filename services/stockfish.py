import chess.engine

async def evaluate_fen(fen: str, multipv=3, depth=15):
    """
    Run Stockfish evaluation for a given FEN.
    Returns top continuations with scores.
    """
    engine = await chess.engine.popen_uci("stockfish")
    board = chess.Board(fen)
    result = await engine.analyse(board, limit=chess.engine.Limit(depth=depth), multipv=multipv)
    await engine.quit()

    evaluations = []
    for r in result:
        score = r["score"].pov(chess.WHITE).score(mate_score=100000)
        pv = [m.uci() for m in r["pv"]]
        evaluations.append({
            "score": score,
            "pv": pv
        })
    return evaluations
