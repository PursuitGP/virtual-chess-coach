from services.parser import parse_pgn
from services.stockfish import evaluate_fen
from services.lichess import get_lichess_data
from utils.winrate import cp_to_winrate

async def build_review(pgn_text: str):
    headers, moves = parse_pgn(pgn_text)
    if not moves:
        return {"error": "Invalid PGN"}

    review_data = {
        "headers": dict(headers),
        "moves": []
    }

    for move in moves:
        stockfish_eval = await evaluate_fen(move["fen_after"], multipv=3)
        lichess_data = await get_lichess_data(move["fen_after"])

        move_data = {
            **move,
            "stockfish_eval": [
                {
                    "score_cp": e["score"],
                    "winrate": cp_to_winrate(e["score"]),
                    "pv": e["pv"]
                } for e in stockfish_eval
            ],
            "lichess_stats": lichess_data
        }
        review_data["moves"].append(move_data)

    return review_data
