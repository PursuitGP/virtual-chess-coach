"""Deterministic chess evidence collection for the coaching pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
from functools import lru_cache
from typing import Any

import chess
import chess.engine
import chess.pgn
import requests

try:
    from .motifs import detect_motifs
    from .opening_context import context_for_opening
except ImportError:
    from motifs import detect_motifs
    from opening_context import context_for_opening


LICHESS_EXPLORER_URL = os.getenv(
    "LICHESS_EXPLORER_URL",
    "https://explorer.lichess.org",
).rstrip("/")
LICHESS_TIMEOUT_SECONDS = float(os.getenv("LICHESS_TIMEOUT_SECONDS", "5"))
LICHESS_MOVE_LIMIT = int(os.getenv("LICHESS_MOVE_LIMIT", "10"))
MIN_MASTER_GAMES = int(os.getenv("MIN_MASTER_GAMES", "20"))
SOUND_MOVE_LOSS_CP = int(os.getenv("SOUND_MOVE_LOSS_CP", "40"))
MISTAKE_MOVE_LOSS_CP = int(os.getenv("MISTAKE_MOVE_LOSS_CP", "100"))
COMMON_PLAYER_MOVE_PCT = float(os.getenv("COMMON_PLAYER_MOVE_PCT", "5"))
ALLOWED_RATING_GROUPS = {
    0,
    1000,
    1200,
    1400,
    1600,
    1800,
    2000,
    2200,
    2500,
}
ALLOWED_SPEEDS = {
    "ultraBullet",
    "bullet",
    "blitz",
    "rapid",
    "classical",
    "correspondence",
}

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


def create_stockfish():
    path = find_stockfish_path()
    if not path:
        raise AnalysisError(
            "Stockfish is not installed or STOCKFISH_PATH is invalid.",
            code="stockfish_unavailable",
            status_code=503,
            retryable=False,
        )
    return chess.engine.SimpleEngine.popen_uci(path)


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


def _normalize_engine_score(score: chess.engine.PovScore) -> dict[str, Any]:
    white_score = score.white()
    mate = white_score.mate()
    if mate is not None:
        display = f"{'-' if mate < 0 else ''}M{abs(mate)}"
        return {
            "type": "mate",
            "value": int(mate),
            "pawns": None,
            "display": display,
        }

    value = white_score.score()
    if isinstance(value, int):
        pawns = value / 100.0
        return {
            "type": "cp",
            "value": int(value),
            "pawns": round(pawns, 2),
            "display": f"{pawns:+.2f}",
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
) -> dict[str, Any]:
    engine = create_stockfish()

    def evaluate_position(fen: str) -> dict[str, Any]:
        board = chess.Board(fen)
        try:
            infos = engine.analyse(
                board,
                chess.engine.Limit(depth=depth),
                multipv=3,
            )
        except Exception as exc:
            raise AnalysisError(
                "Stockfish could not evaluate a position in the uploaded game.",
                code="stockfish_failed",
                status_code=502,
                retryable=True,
            ) from exc

        if isinstance(infos, dict):
            infos = [infos]
        top_lines = []
        for rank, info in enumerate(infos, start=1):
            if "score" not in info:
                continue
            pv = info.get("pv") or []
            line_board = board.copy()
            moves_san = []
            for move in pv[:8]:
                try:
                    moves_san.append(line_board.san(move))
                    line_board.push(move)
                except (AssertionError, ValueError):
                    break
            top_lines.append(
                {
                    "rank": rank,
                    "evaluation": _normalize_engine_score(info["score"]),
                    "moves_uci": [move.uci() for move in pv[:8]],
                    "moves_san": moves_san,
                }
            )
        if not top_lines:
            raise AnalysisError(
                "Stockfish did not return an analysis line.",
                code="stockfish_invalid_response",
                status_code=502,
                retryable=True,
            )
        return {
            "depth": depth,
            "evaluation": top_lines[0]["evaluation"],
            "best_move": (
                top_lines[0]["moves_uci"][0]
                if top_lines[0]["moves_uci"]
                else None
            ),
            "top_lines": top_lines,
        }

    try:
        initial = evaluate_position(records[0]["previous_fen"])
        previous_eval = initial["evaluation"]

        for record in records:
            stockfish = evaluate_position(record["fen"])
            current_eval = stockfish["evaluation"]
            previous_cp = (
                previous_eval["value"]
                if previous_eval["type"] == "cp"
                else None
            )
            current_cp = (
                current_eval["value"]
                if current_eval["type"] == "cp"
                else None
            )
            delta_cp = (
                current_cp - previous_cp
                if current_cp is not None and previous_cp is not None
                else None
            )
            mover_loss_cp = None
            if delta_cp is not None:
                mover_loss_cp = max(
                    0,
                    -delta_cp if record["side"] == "white" else delta_cp,
                )
            stockfish.update(
                {
                    "eval_delta_cp": delta_cp,
                    "eval_delta_pawns": round(delta_cp / 100.0, 2)
                    if delta_cp is not None
                    else None,
                    "mover_loss_cp": mover_loss_cp,
                    "mover_loss_pawns": round(mover_loss_cp / 100.0, 2)
                    if mover_loss_cp is not None
                    else None,
                }
            )
            record["stockfish"] = stockfish
            previous_eval = current_eval
        return initial
    finally:
        try:
            engine.quit()
        except Exception:
            pass


def _lichess_headers() -> dict[str, str]:
    headers = dict(_session.headers)
    token = os.getenv("LICHESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def lichess_status() -> dict[str, Any]:
    return {
        "configured": bool(os.getenv("LICHESS_TOKEN", "").strip()),
        "endpoint": LICHESS_EXPLORER_URL,
        "rating_groups": sorted(ALLOWED_RATING_GROUPS),
    }


def verify_lichess_connection() -> dict[str, Any]:
    status = lichess_status()
    if not status["configured"]:
        return {
            **status,
            "verified": False,
            "error": "LICHESS_TOKEN is not configured.",
        }
    try:
        starting_fen = chess.Board().fen()
        masters = fetch_lichess_explorer(starting_fen, "masters")
        players = fetch_lichess_explorer(starting_fen, "lichess")
        return {
            **status,
            "verified": True,
            "error": None,
            "masters_games": _games_count(masters),
            "player_games": _games_count(players),
        }
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else None
        message = (
            "Lichess rejected LICHESS_TOKEN."
            if code == 401
            else f"Lichess returned HTTP {code or 'error'}."
        )
        return {
            **status,
            "verified": False,
            "error": message,
        }
    except requests.RequestException:
        return {
            **status,
            "verified": False,
            "error": "Lichess Opening Explorer could not be reached.",
        }


def normalize_rating_groups(
    rating_groups: tuple[int, ...] | list[int] | None,
) -> tuple[int, ...]:
    if not rating_groups:
        return ()
    normalized = tuple(sorted({int(value) for value in rating_groups}))
    if any(value not in ALLOWED_RATING_GROUPS for value in normalized):
        raise AnalysisError(
            "Unsupported Lichess rating group.",
            code="invalid_lichess_rating",
        )
    return normalized


def normalize_speeds(
    speeds: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if not speeds:
        return ()
    normalized = tuple(dict.fromkeys(str(value) for value in speeds))
    if any(value not in ALLOWED_SPEEDS for value in normalized):
        raise AnalysisError(
            "Unsupported Lichess speed filter.",
            code="invalid_lichess_speed",
        )
    return normalized


@lru_cache(maxsize=4096)
def fetch_lichess_explorer(
    fen: str,
    database: str,
    rating_groups: tuple[int, ...] = (),
    speeds: tuple[str, ...] = (),
) -> dict[str, Any]:
    if database not in {"masters", "lichess"}:
        raise ValueError(f"Unsupported Lichess database: {database}")
    params: dict[str, Any] = {
        "fen": fen,
        "moves": LICHESS_MOVE_LIMIT,
        "topGames": 0,
    }
    if database == "lichess":
        params["recentGames"] = 0
        if rating_groups:
            params["ratings"] = ",".join(str(value) for value in rating_groups)
        if speeds:
            params["speeds"] = ",".join(speeds)

    response = _session.get(
        f"{LICHESS_EXPLORER_URL}/{database}",
        params=params,
        headers=_lichess_headers(),
        timeout=LICHESS_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        retry_after = min(int(response.headers.get("Retry-After", "1")), 5)
        time.sleep(max(retry_after, 1))
        response = _session.get(
            f"{LICHESS_EXPLORER_URL}/{database}",
            params=params,
            headers=_lichess_headers(),
            timeout=LICHESS_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _games_count(data: dict[str, Any]) -> int:
    return sum(int(data.get(key, 0) or 0) for key in ("white", "draws", "black"))


def _move_summary(
    move: dict[str, Any],
    total_games: int,
    rank: int,
    side_to_move: str,
) -> dict[str, Any]:
    played = _games_count(move)
    denominator = total_games or 1
    white_win_pct = round(
        (int(move.get("white", 0) or 0) / (played or 1)) * 100,
        2,
    )
    draw_pct = round(
        (int(move.get("draws", 0) or 0) / (played or 1)) * 100,
        2,
    )
    black_win_pct = round(
        (int(move.get("black", 0) or 0) / (played or 1)) * 100,
        2,
    )
    mover_win_pct = white_win_pct if side_to_move == "white" else black_win_pct
    mover_loss_pct = black_win_pct if side_to_move == "white" else white_win_pct
    return {
        "rank": rank,
        "uci": move.get("uci"),
        "san": move.get("san"),
        "games": played,
        "popularity_pct": round((played / denominator) * 100, 2),
        "white_win_pct": white_win_pct,
        "draw_pct": draw_pct,
        "black_win_pct": black_win_pct,
        "mover_win_pct": mover_win_pct,
        "mover_loss_pct": mover_loss_pct,
        "mover_score_pct": round(mover_win_pct + draw_pct / 2, 2),
        "average_rating": move.get("averageRating"),
    }


def summarize_explorer(data: dict[str, Any], fen: str) -> dict[str, Any]:
    total_games = _games_count(data)
    side_to_move = "white" if chess.Board(fen).turn == chess.WHITE else "black"
    moves = [
        _move_summary(move, total_games, rank, side_to_move)
        for rank, move in enumerate(data.get("moves") or [], start=1)
        if isinstance(move, dict)
    ]
    opening = data.get("opening")
    return {
        "available": True,
        "total_games": total_games,
        "side_to_move": side_to_move,
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


def _practical_signal(
    record: dict[str, Any],
    masters_before: dict[str, Any],
    players_before: dict[str, Any],
    master_move: dict[str, Any] | None,
    player_move: dict[str, Any] | None,
) -> dict[str, Any]:
    loss_cp = record["stockfish"].get("mover_loss_cp")
    sound = loss_cp is not None and loss_cp <= SOUND_MOVE_LOSS_CP
    mistake = loss_cp is not None and loss_cp >= MISTAKE_MOVE_LOSS_CP
    master_rank = master_move.get("rank") if master_move else None
    player_popularity = (
        player_move.get("popularity_pct") if player_move else 0
    )

    if not masters_before.get("available"):
        classification = "statistics-unavailable"
    elif masters_before.get("total_games", 0) < MIN_MASTER_GAMES:
        classification = "insufficient-master-sample"
    elif master_rank and master_rank <= 3 and sound:
        classification = "master-aligned-and-sound"
    elif master_move is None and sound:
        classification = "sound-novelty-candidate"
    elif master_rank and master_rank > 3 and sound:
        classification = "sound-rare-master-alternative"
    elif (
        mistake
        and players_before.get("available")
        and player_popularity >= COMMON_PLAYER_MOVE_PCT
    ):
        classification = "common-rating-pool-mistake"
    elif mistake:
        classification = "engine-identified-mistake"
    elif (
        players_before.get("available")
        and player_popularity >= COMMON_PLAYER_MOVE_PCT
    ):
        classification = "common-rating-pool-choice"
    else:
        classification = "unclear-or-low-sample"

    return {
        "classification": classification,
        "engine_sound": sound,
        "engine_mistake": mistake,
        "mover_loss_cp": loss_cp,
        "master_rank": master_rank,
        "player_popularity_pct": player_popularity,
        "note": (
            "Novelty labels are candidates only: absence from the selected "
            "Lichess sample does not prove a move is historically new."
        ),
    }


def _practical_candidates(
    record: dict[str, Any],
    masters_after: dict[str, Any],
    players_after: dict[str, Any],
) -> list[dict[str, Any]]:
    master_by_uci = {
        move.get("uci"): move for move in masters_after.get("moves", [])
    }
    player_by_uci = {
        move.get("uci"): move for move in players_after.get("moves", [])
    }
    candidates = []
    for line in record["stockfish"].get("top_lines", []):
        moves = line.get("moves_uci") or []
        if not moves:
            continue
        uci = moves[0]
        master = master_by_uci.get(uci)
        player = player_by_uci.get(uci)
        master_popularity = master.get("popularity_pct", 0) if master else 0
        player_popularity = player.get("popularity_pct", 0) if player else 0
        if not (
            masters_after.get("available")
            or players_after.get("available")
        ):
            label = "engine-top-line-statistics-unavailable"
        elif line["rank"] == 1 and max(master_popularity, player_popularity) < 5:
            label = "engine-first-rare-practical-option"
        elif master and master.get("rank", 99) <= 3:
            label = "engine-and-master-supported"
        elif player and player.get("popularity_pct", 0) >= 5:
            label = "engine-supported-common-player-choice"
        else:
            label = "engine-supported-alternative"
        candidates.append(
            {
                "uci": uci,
                "label": label,
                "stockfish_rank": line["rank"],
                "stockfish_evaluation": line.get("evaluation"),
                "stockfish_line_uci": moves,
                "stockfish_line_san": line.get("moves_san") or [],
                "masters": master,
                "players": player,
            }
        )
    return candidates


def add_lichess_evidence(
    records: list[dict[str, Any]],
    warnings: list[str],
    *,
    rating_groups: tuple[int, ...] = (),
    speeds: tuple[str, ...] = (),
) -> None:
    unique_fens = {
        fen
        for record in records
        for fen in (record["previous_fen"], record["fen"])
    }
    explorer_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def load_explorer(fen: str, database: str):
        try:
            raw = fetch_lichess_explorer(
                fen,
                database,
                rating_groups if database == "lichess" else (),
                speeds if database == "lichess" else (),
            )
            return summarize_explorer(raw, fen)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                reason = (
                    "Lichess Opening Explorer requires a valid LICHESS_TOKEN."
                )
            else:
                reason = "Lichess Opening Explorer was unavailable."
            return _unavailable_explorer(reason)
        except (requests.RequestException, ValueError):
            return _unavailable_explorer(
                "Lichess Opening Explorer was unavailable."
            )

    # Lichess explicitly asks API clients to make one request at a time.
    for fen in sorted(unique_fens):
        for database in ("masters", "lichess"):
            explorer_cache[(fen, database)] = load_explorer(fen, database)

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
        opening_context = context_for_opening(opening)
        practical_signal = _practical_signal(
            record,
            before_masters,
            before_players,
            played_masters,
            played_players,
        )
        practical_candidates = _practical_candidates(
            record,
            after_masters,
            after_players,
        )

        record["lichess"] = {
            "opening": opening,
            "opening_context": opening_context,
            "theory_status": _theory_status(before_masters, played_masters),
            "filters": {
                "rating_groups": list(rating_groups),
                "speeds": list(speeds),
            },
            "practical_signal": practical_signal,
            "practical_candidates": practical_candidates,
            "masters": {
                "available": before_masters.get("available", False),
                "unavailable_reason": before_masters.get("reason"),
                "position_games_before": before_masters.get("total_games", 0),
                "played_move": played_masters,
                "continuations": after_masters.get("moves", [])[:5],
            },
            "players": {
                "available": before_players.get("available", False),
                "unavailable_reason": before_players.get("reason"),
                "position_games_before": before_players.get("total_games", 0),
                "played_move": played_players,
                "continuations": after_players.get("moves", [])[:5],
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
            "pv": (
                record["stockfish"]["top_lines"][0]["moves_uci"]
                if record["stockfish"].get("top_lines")
                else []
            ),
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
    lichess_ratings: tuple[int, ...] | list[int] | None = None,
    lichess_speeds: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    game, _raw_text, warnings = _parse_game(pgn_bytes)
    positions, total_plies = _position_records(game, max_plies=max_plies)
    rating_groups = normalize_rating_groups(lichess_ratings)
    speeds = normalize_speeds(lichess_speeds)

    initial_stockfish = evaluate_with_stockfish(
        positions,
        depth=stockfish_depth,
    )
    add_lichess_evidence(
        positions,
        warnings,
        rating_groups=rating_groups,
        speeds=speeds,
    )
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
            **lichess_status(),
            "available": any(
                position["lichess"]["masters"]["available"]
                or position["lichess"]["players"]["available"]
                for position in positions
            ),
            "filters": {
                "rating_groups": list(rating_groups),
                "speeds": list(speeds),
            },
        },
        "motifs": {
            "available": any(
                position.get("motifs_available", False) for position in positions
            )
        },
    }
    result: dict[str, Any] = {
        "schema_version": 2,
        "metadata": metadata,
        "filters": {
            "lichess_rating_groups": list(rating_groups),
            "lichess_speeds": list(speeds),
        },
        "initial_stockfish": initial_stockfish,
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
