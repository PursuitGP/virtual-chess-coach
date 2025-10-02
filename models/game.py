from pydantic import BaseModel
from typing import List, Dict, Optional

class MoveEval(BaseModel):
    score_cp: int
    winrate: float
    pv: List[str]

class MoveData(BaseModel):
    ply: int
    san: str
    uci: str
    fen_before: str
    fen_after: str
    stockfish_eval: List[MoveEval]
    lichess_stats: Dict

class GameReview(BaseModel):
    headers: Dict[str, str]
    moves: List[MoveData]
