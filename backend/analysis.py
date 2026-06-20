"""Deterministic chess evidence collection for the coaching pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any

import chess
import chess.pgn
import requests
from stockfish import Stockfish

try:
    from .motifs import detect_motifs
except ImportError:
    from motifs import detect_motifs


LICHESS_EXPLORER_URL = "https://explorer.lichess.ovh"
LICHESS_TIMEOUT_SECONDS = float(os.getenv("LICHESS_TIMEOUT_SECONDS", "5"))
LICHESS_MOVE_LIMIT = int(os.getenv("LICHESS_MOVE_LIMIT", "8"))
MIN_MASTER_GAMES = int(os.getenv("MIN_MASTER_GAMES", "20"))

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": "VirtualChessCoach/2.0 (portfolio project)",
        "Accept": "application/json",
    }
)


class AnalysisError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


def find_stockfish_path() -> str | None:
    configured = os.getenv("STOCKFISH_PATH")
    candidates = [
        configured,
        shutil.which("stockfish"),
        "/opt/homebrew/bin/stockfish",
        "/usr/local/bin/stockfish",
        "/usr/bin/stockfish",
        "/usr/games/stockfish",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def create_stockfish(depth: int) -> Stockfish:
    path = find_stockfish_path()
    if not path:
        raise AnalysisError(
            "Stockfish is not installed or STOCKFISH_PATH is invalid.",
            code="stockfish_unavailable",
            status_code=503,
            retryable=False,
        )
    return Stockfish(path=path, depth=depth)


def _decode_pgn(pgn_bytes: bytes) -> str:
    if not pgn_bytes:
        raise AnalysisError("The uploaded PGN is empty.", code="empty_pgn")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return pgn_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return pgn_bytes.decode("utf-8", errors="replace")


def _parse_game(pgn_bytes: bytes) -> tuple[chess.pgn.Game, str, list[str]]:
    text = _decode_pgn(pgn_bytes)
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        raise AnalysisError("The uploaded text is not a valid PGN.", code="invalid_pgn")

    moves = list(game.mainline_moves())
    if not moves:
        raise AnalysisError(
            "The PGN does not contain any legal moves.",
            code="pgn_has_no_moves",
        )

    warnings: list[str] = []
    if getattr(game, "errors", None):
        warnings.append(
            "The PGN parser recovered from one or more notation errors; verify the move list."
        )
    return game, text, warnings


def _position_records(
    game: chess.pgn.Game,
    *,
    max_plies: int,
) -> tuple[list[dict[str, Any]], int]:
    all_moves = list(game.mainline_moves())
    selected_moves = all_moves[:max_plies]
    board = game.board()
    records: list[dict[str, Any]] = []

    for index, move in enumerate(selected_moves):
        previous_fen = board.fen()
        side = "white" if board.turn == chess.WHITE else "black"
        fullmove_number = board.fullmove_number
        san = board.san(move)
        previous_move_uci = records[-1]["played_move"]["uci"] if records else None
        board.push(move)
        records.append(
            {
                "ply": index + 1,
                "fullmove_number": fullmove_number,
                "side": side,
                "played_move": {"san": san, "uci": move.uci()},
                "previous_move_uci": previous_move_uci,
                "previous_fen": previous_fen,
                "fen": board.fen(),
            }
        )
    return records, len(all_moves)


def _normalize_evaluation(raw: dict[str, Any]) -> dict[str, Any]:
    evaluation_type = raw.get("type")
    value = raw.get("value")
    if evaluation_type == "cp" and isinstance(value, (int, float)):
        pawns = value / 100.0
        return {
            "type": "cp",
            "value": int(value),
            "pawns": round(pawns, 2),
            "display": f"{pawns:+.2f}",
        }
    if evaluation_type == "mate" and isinstance(value, (int, float)):
        value = int(value)
        display = f"{'-' if value < 0 else ''}M{abs(value)}"
        return {
            "type": "mate",
            "value": value,
            "pawns": None,
            "display": display,
        }
    raise AnalysisError(
        "Stockfish returned an unsupported evaluation.",
        code="stockfish_invalid_response",
        status_code=502,
        retryable=True,
    )


def evaluate_with_stockfish(
    records: list[dict[str, Any]],
    *,
    depth: int,
) -> None:
    engine = create_stockfish(depth)
    previous_cp: int | None = None

    for record in records:
        try:
            engine.set_fen_position(record["fen"])
            raw = engine.get_evaluation()
            top_moves = engine.get_top_moves(3) or []
            best_move = engine.get_best_move()
        except Exception as exc:
            raise AnalysisError(
                "Stockfish could not evaluate the uploaded game.",
                code="stockfish_failed",
                status_code=502,
                retryable=True,
            ) from exc

        evaluation = _normalize_evaluation(raw)
        current_cp = evaluation["value"] if evaluation["type"] == "cp" else None
        delta_cp = (
            current_cp - previous_cp
            if current_cp is not None and previous_cp is not None
            else None
        )
        record["stockfish"] = {
            "depth": depth,
            "evaluation": evaluation,
            "eval_delta_cp": delta_cp,
            "eval_delta_pawns": round(delta_cp / 100.0, 2)
            if delta_cp is not None
            else None,
            "best_move": best_move,
            "pv": [
                move.get("Move")
                for move in top_moves
                if isinstance(move, dict) and move.get("Move")
            ],
        }
        if current_cp is not None:
            previous_cp = current_cp


@lru_cache(maxsize=4096)
def fetch_lichess_explorer(fen: str, database: str) -> dict[str, Any]:
    if database not in {"masters", "lichess"}:
        raise ValueError(f"Unsupported Lichess database: {database}")
    response = _session.get(
        f"{LICHESS_EXPLORER_URL}/{database}",
        params={
            "fen": fen,
            "moves": LICHESS_MOVE_LIMIT,
            "topGames": 0,
            "recentGames": 0,
        },
        timeout=LICHESS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _games_count(data: dict[str, Any]) -> int:
    return sum(int(data.get(key, 0) or 0) for key in ("white", "draws", "black"))


def _move_summary(move: dict[str, Any], total_games: int, rank: int) -> dict[str, Any]:
    played = _games_count(move)
    denominator = total_games or 1
    return {
        "rank": rank,
        "uci": move.get("uci"),
        "san": move.get("san"),
        "games": played,
        "popularity_pct": round((played / denominator) * 100, 2),
        "white_win_pct": round((int(move.get("white", 0) or 0) / (played or 1)) * 100, 2),
        "draw_pct": round((int(move.get("draws", 0) or 0) / (played or 1)) * 100, 2),
        "black_win_pct": round((int(move.get("black", 0) or 0) / (played or 1)) * 100, 2),
        "average_rating": move.get("averageRating"),
    }


def summarize_explorer(data: dict[str, Any]) -> dict[str, Any]:
    total_games = _games_count(data)
    moves = [
        _move_summary(move, total_games, rank)
        for rank, move in enumerate(data.get("moves") or [], start=1)
        if isinstance(move, dict)
    ]
    opening = data.get("opening")
    return {
        "available": True,
        "total_games": total_games,
        "opening": {
            "eco": opening.get("eco"),
            "name": opening.get("name"),
        }
        if isinstance(opening, dict)
        else None,
        "moves": moves,
    }


def _unavailable_explorer(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "total_games": 0,
        "opening": None,
        "moves": [],
    }


def _played_move(explorer: dict[str, Any], uci: str) -> dict[str, Any] | None:
    for move in explorer.get("moves", []):
        if move.get("uci") == uci:
            return move
    return None


def _theory_status(
    masters_before: dict[str, Any],
    played_move: dict[str, Any] | None,
) -> str:
    if not masters_before.get("available"):
        return "unavailable"
    if masters_before.get("total_games", 0) < MIN_MASTER_GAMES:
        return "insufficient-data"
    if played_move is None:
        return "not-in-sample"
    if played_move.get("rank", 99) <= 3:
        return "common-master-move"
    return "rare-master-move"


def add_lichess_evidence(records: list[dict[str, Any]], warnings: list[str]) -> None:
    unique_fens = {
        fen
        for record in records
        for fen in (record["previous_fen"], record["fen"])
    }
    explorer_cache: dict[tuple[str, str], dict[str, Any]] = {}

    requests_to_make = [
        (fen, database)
        for fen in unique_fens
        for database in ("masters", "lichess")
    ]

    def load_explorer(fen: str, database: str):
        try:
            raw = fetch_lichess_explorer(fen, database)
            return fen, database, summarize_explorer(raw)
        except (requests.RequestException, ValueError):
            return (
                fen,
                database,
                _unavailable_explorer(
                    "Lichess Opening Explorer was unavailable."
                ),
            )

    with ThreadPoolExecutor(
        max_workers=min(6, len(requests_to_make))
    ) as executor:
        futures = {
            executor.submit(load_explorer, fen, database): (fen, database)
            for fen, database in requests_to_make
        }
        for future in as_completed(futures):
            try:
                fen, database, summary = future.result()
                explorer_cache[(fen, database)] = summary
            except Exception:
                # The worker already converts expected provider failures. This
                # branch is a final guard that preserves the rest of analysis.
                fen, database = futures[future]
                explorer_cache[(fen, database)] = _unavailable_explorer(
                    "Lichess Opening Explorer was unavailable."
                )

    if any(
        not value.get("available") for value in explorer_cache.values()
    ):
        warnings.append(
            "Some Lichess Opening Explorer data was unavailable; coaching will identify missing statistical context."
        )

    for record in records:
        before_masters = explorer_cache[(record["previous_fen"], "masters")]
        before_players = explorer_cache[(record["previous_fen"], "lichess")]
        after_masters = explorer_cache[(record["fen"], "masters")]
        after_players = explorer_cache[(record["fen"], "lichess")]
        uci = record["played_move"]["uci"]
        played_masters = _played_move(before_masters, uci)
        played_players = _played_move(before_players, uci)
        opening = after_masters.get("opening") or after_players.get("opening")

        record["lichess"] = {
            "opening": opening,
            "theory_status": _theory_status(before_masters, played_masters),
            "masters": {
                "available": before_masters.get("available", False),
                "position_games_before": before_masters.get("total_games", 0),
                "played_move": played_masters,
                "continuations": after_masters.get("moves", [])[:3],
            },
            "players": {
                "available": before_players.get("available", False),
                "position_games_before": before_players.get("total_games", 0),
                "played_move": played_players,
                "continuations": after_players.get("moves", [])[:3],
            },
        }


def add_motif_evidence(records: list[dict[str, Any]], warnings: list[str]) -> None:
    previous_eval_cp: int | None = None
    motif_failures = 0

    for record in records:
        current_board = chess.Board(record["fen"])
        previous_board = chess.Board(record["previous_fen"])
        evaluation = record["stockfish"]["evaluation"]
        eval_cp = evaluation["value"] if evaluation["type"] == "cp" else 0
        sf_raw = {
            "type": evaluation["type"],
            "value": evaluation["value"],
            "pv": record["stockfish"]["pv"],
        }
        try:
            record["motifs"] = detect_motifs(
                board=current_board,
                prev_board=previous_board,
                move_number=record["ply"],
                eval_cp=eval_cp,
                prev_eval=previous_eval_cp,
                sf_raw=sf_raw,
                last_move_uci=record["played_move"]["uci"],
                prev_move_uci=record["previous_move_uci"],
            )
            record["motifs_available"] = True
        except Exception:
            motif_failures += 1
            record["motifs"] = []
            record["motifs_available"] = False
        if evaluation["type"] == "cp":
            previous_eval_cp = evaluation["value"]

    if motif_failures:
        warnings.append(
            f"Motif detection was unavailable for {motif_failures} analyzed position(s)."
        )


def _analysis_id(
    metadata: dict[str, str],
    positions: list[dict[str, Any]],
) -> str:
    stable_payload = {
        "metadata": metadata,
        "positions": [
            {
                "ply": position["ply"],
                "move": position["played_move"],
                "fen": position["fen"],
                "stockfish": position["stockfish"],
                "lichess": position["lichess"],
                "motifs": position["motifs"],
            }
            for position in positions
        ],
    }
    encoded = json.dumps(
        stable_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_analysis(
    pgn_bytes: bytes,
    *,
    max_plies: int = 20,
    stockfish_depth: int = 18,
) -> dict[str, Any]:
    game, _raw_text, warnings = _parse_game(pgn_bytes)
    positions, total_plies = _position_records(game, max_plies=max_plies)

    evaluate_with_stockfish(positions, depth=stockfish_depth)
    add_lichess_evidence(positions, warnings)
    add_motif_evidence(positions, warnings)

    metadata = {
        key: value
        for key, value in dict(game.headers).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    analyzed_plies = len(positions)
    truncated = total_plies > analyzed_plies
    if truncated:
        warnings.append(
            f"Opening-focused analysis stopped after {analyzed_plies} plies out of {total_plies}."
        )

    providers = {
        "stockfish": {"available": True, "depth": stockfish_depth},
        "lichess": {
            "available": any(
                position["lichess"]["masters"]["available"]
                or position["lichess"]["players"]["available"]
                for position in positions
            )
        },
        "motifs": {
            "available": any(
                position.get("motifs_available", False) for position in positions
            )
        },
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "metadata": metadata,
        "moves": [position["played_move"]["san"] for position in positions],
        "total_plies": total_plies,
        "analyzed_plies": analyzed_plies,
        "truncated": truncated,
        "warnings": list(dict.fromkeys(warnings)),
        "providers": providers,
        "positions": positions,
    }
    result["analysis_id"] = _analysis_id(metadata, positions)
    return result
