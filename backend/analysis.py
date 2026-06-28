"""Deterministic chess evidence collection for the coaching pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

import chess
import chess.engine
import chess.pgn
import requests

try:
    from .motifs import (
        EX_ABSOLUTE_PIN,
        MOTIF_CONFIDENCE,
        build_pin_evidence,
        detect_motifs,
        pinning_piece_for_absolute_pin,
        publish_motifs,
    )
    from .study_database import (
        StudyDatabaseError,
        context_for_position,
        study_database_status,
    )
except ImportError:
    from motifs import (
        EX_ABSOLUTE_PIN,
        MOTIF_CONFIDENCE,
        build_pin_evidence,
        detect_motifs,
        pinning_piece_for_absolute_pin,
        publish_motifs,
    )
    from study_database import (
        StudyDatabaseError,
        context_for_position,
        study_database_status,
    )


LICHESS_EXPLORER_URL = os.getenv(
    "LICHESS_EXPLORER_URL",
    "https://explorer.lichess.org",
).rstrip("/")
LICHESS_TIMEOUT_SECONDS = float(os.getenv("LICHESS_TIMEOUT_SECONDS", "5"))
LICHESS_MOVE_LIMIT = int(os.getenv("LICHESS_MOVE_LIMIT", "10"))
LICHESS_WORKERS = int(os.getenv("LICHESS_WORKERS", "2"))
MIN_MASTER_GAMES = int(os.getenv("MIN_MASTER_GAMES", "20"))
SOUND_MOVE_LOSS_CP = int(os.getenv("SOUND_MOVE_LOSS_CP", "40"))
MISTAKE_MOVE_LOSS_CP = int(os.getenv("MISTAKE_MOVE_LOSS_CP", "100"))
COMMON_PLAYER_MOVE_PCT = float(os.getenv("COMMON_PLAYER_MOVE_PCT", "5"))
MATERIAL_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}
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

_sessions = {
    database: requests.Session() for database in ("masters", "lichess")
}
for _session in _sessions.values():
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


def _stockfish_boards(records: list[dict[str, Any]]) -> list[chess.Board]:
    """Rebuild the game history so Stockfish can account for repetition state."""
    if not records:
        raise AnalysisError(
            "No positions were supplied to Stockfish.",
            code="stockfish_invalid_request",
        )

    board = chess.Board(records[0]["previous_fen"])
    boards = [board.copy(stack=True)]
    for record in records:
        try:
            move = chess.Move.from_uci(record["played_move"]["uci"])
        except ValueError as exc:
            raise AnalysisError(
                "The parsed game contained an invalid move.",
                code="stockfish_invalid_request",
            ) from exc
        if move not in board.legal_moves:
            raise AnalysisError(
                "The parsed game contained an illegal move.",
                code="stockfish_invalid_request",
            )
        board.push(move)
        boards.append(board.copy(stack=True))
    return boards


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


def _normalize_engine_score(
    score: chess.engine.PovScore,
    board: chess.Board | None = None,
) -> dict[str, Any]:
    white_score = score.white()
    mate = white_score.mate()
    if mate is not None:
        if mate == 0 and board is not None and board.is_checkmate():
            winner = "black" if board.turn == chess.WHITE else "white"
            display = "Checkmate"
        else:
            winner = "white" if mate > 0 else "black"
            display = f"{'-' if mate < 0 else ''}M{abs(mate)}"
        return {
            "type": "mate",
            "value": int(mate),
            "pawns": None,
            "display": display,
            "winner": winner,
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


def _material_summary(board: chess.Board) -> dict[str, Any]:
    totals = {}
    for color, name in ((chess.WHITE, "white"), (chess.BLACK, "black")):
        totals[name] = sum(
            len(board.pieces(piece_type, color)) * value
            for piece_type, value in MATERIAL_VALUES.items()
        )
    balance = totals["white"] - totals["black"]
    return {
        **totals,
        "balance_white_pawns": balance,
        "leader": "white" if balance > 0 else "black" if balance < 0 else None,
        "advantage_pawns": abs(balance),
    }


def _evaluation_assessment(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evaluation, dict):
        return {"classification": "unavailable", "leader": None}
    if evaluation.get("type") == "mate":
        return {
            "classification": "forced_mate",
            "leader": evaluation.get("winner"),
            "mate_in": abs(int(evaluation.get("value") or 0)),
        }

    pawns = evaluation.get("pawns")
    if not isinstance(pawns, (int, float)):
        return {"classification": "unavailable", "leader": None}
    magnitude = abs(float(pawns))
    leader = "white" if pawns > 0 else "black" if pawns < 0 else None
    if magnitude < 0.35:
        classification = "roughly_equal"
    elif magnitude < 1.5:
        classification = "slight_edge"
    elif magnitude < 3:
        classification = "clear_advantage"
    else:
        classification = "decisive_advantage"
    return {
        "classification": classification,
        "leader": leader,
        "pawns": round(float(pawns), 2),
    }


def _move_quality(
    record: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> str:
    mover = record.get("side")
    before_type = (before or {}).get("type")
    after_type = (after or {}).get("type")
    if after_type == "mate":
        winner = (after or {}).get("winner")
        if winner == mover and before_type != "mate":
            return "creates_forced_mate"
        if winner != mover and before_type != "mate":
            return "allows_forced_mate"
        if winner == mover:
            return "maintains_forced_mate"
        return "fails_to_escape_forced_mate"
    if before_type == "mate" and after_type != "mate":
        winner = (before or {}).get("winner")
        return "escapes_forced_mate" if winner != mover else "misses_forced_mate"

    loss_cp = (record.get("stockfish") or {}).get("mover_loss_cp")
    if not isinstance(loss_cp, int):
        return "unclear"
    if loss_cp >= 300:
        return "blunder"
    if loss_cp >= 100:
        return "mistake"
    if loss_cp >= 50:
        return "inaccuracy"
    return "sound"


def _white_winning_chances(
    evaluation: dict[str, Any] | None,
) -> float | None:
    if not isinstance(evaluation, dict):
        return None
    if evaluation.get("type") == "mate":
        winner = evaluation.get("winner")
        if winner == "white":
            return 1.0
        if winner == "black":
            return -1.0
        return None
    value = evaluation.get("value")
    if not isinstance(value, int):
        return None
    return max(
        -1.0,
        min(1.0, 2 / (1 + math.exp(-0.00368208 * value)) - 1),
    )


def _move_classification(
    record: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    played_matches_engine_first: bool,
) -> dict[str, Any]:
    mover = record.get("side")
    before_chances = _white_winning_chances(before)
    after_chances = _white_winning_chances(after)
    chance_loss = None
    if before_chances is not None and after_chances is not None:
        chance_loss = max(
            0.0,
            (
                before_chances - after_chances
                if mover == "white"
                else after_chances - before_chances
            ),
        )

    consequence = _move_quality(record, before, after)
    if consequence in {
        "allows_forced_mate",
        "misses_forced_mate",
        "fails_to_escape_forced_mate",
    }:
        label = "blunder"
    elif chance_loss is None:
        label = "unclear"
    elif chance_loss >= 0.3:
        label = "blunder"
    elif chance_loss >= 0.2:
        label = "mistake"
    elif chance_loss >= 0.1:
        label = "inaccuracy"
    elif played_matches_engine_first:
        label = "best"
    elif chance_loss <= 0.02:
        label = "excellent"
    else:
        label = "good"

    definitions = {
        "best": "Matches Stockfish's first choice in the position.",
        "excellent": (
            "Does not match the first engine choice but changes the modeled "
            "winning chances by no more than 0.02."
        ),
        "good": (
            "Keeps the modeled winning-chance loss below the 0.10 "
            "inaccuracy threshold."
        ),
        "inaccuracy": (
            "Reduces the mover's modeled winning chances by at least 0.10 "
            "but less than 0.20."
        ),
        "mistake": (
            "Reduces the mover's modeled winning chances by at least 0.20 "
            "but less than 0.30."
        ),
        "blunder": (
            "Reduces the mover's modeled winning chances by at least 0.30 "
            "or newly allows a forced mate."
        ),
        "unclear": "The available engine scores cannot support a stable label.",
    }
    symbols = {
        "best": "✓",
        "excellent": "!",
        "good": "",
        "inaccuracy": "?!",
        "mistake": "?",
        "blunder": "??",
        "unclear": "",
    }
    return {
        "label": label,
        "display": label.capitalize(),
        "symbol": symbols[label],
        "definition": definitions[label],
        "method": "lichess-style-winning-chance-delta",
        "winning_chance_loss": (
            round(chance_loss, 3) if chance_loss is not None else None
        ),
        "estimated_win_probability_loss_pct": (
            round(chance_loss * 50, 1) if chance_loss is not None else None
        ),
        "centipawn_loss": (record.get("stockfish") or {}).get("mover_loss_cp"),
        "consequence": consequence,
    }


def _move_piece_effects(record: dict[str, Any]) -> dict[str, Any]:
    try:
        before = chess.Board(record["previous_fen"])
        after = chess.Board(record["fen"])
        move = chess.Move.from_uci(record["played_move"]["uci"])
    except (KeyError, ValueError):
        return {}

    moved_piece = after.piece_at(move.to_square)
    previous_piece = before.piece_at(move.from_square)
    if moved_piece is None or previous_piece is None:
        return {}

    previous_attacks = set(before.attacks(move.from_square))
    resulting_attacks = set(after.attacks(move.to_square))

    def piece_details(square: chess.Square) -> dict[str, Any] | None:
        piece = after.piece_at(square)
        if piece is None:
            return None
        return {
            "piece": chess.piece_name(piece.piece_type),
            "square": chess.square_name(square),
            "under_enemy_pressure": bool(
                after.attackers(not piece.color, square)
            ),
        }

    newly_defended = []
    newly_attacked = []
    for square in sorted(resulting_attacks - previous_attacks):
        piece = after.piece_at(square)
        if piece is None:
            continue
        details = piece_details(square)
        if details is None:
            continue
        if piece.color == moved_piece.color:
            newly_defended.append(details)
        else:
            newly_attacked.append(details)

    return {
        "moved_piece": {
            "piece": chess.piece_name(moved_piece.piece_type),
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
        },
        "newly_defended_friendly_pieces": newly_defended[:6],
        "newly_attacked_enemy_pieces": newly_attacked[:6],
    }


def _piece_at_details(
    board: chess.Board,
    square: chess.Square,
) -> dict[str, Any] | None:
    piece = board.piece_at(square)
    if piece is None:
        return None
    return {
        "piece": chess.piece_name(piece.piece_type),
        "square": chess.square_name(square),
    }


def _attacker_details(
    board: chess.Board,
    color: chess.Color,
    square: chess.Square,
) -> list[dict[str, Any]]:
    details = []
    for attacker in sorted(board.attackers(color, square)):
        piece = _piece_at_details(board, attacker)
        if piece:
            details.append(piece)
    return details


def _candidate_move_effects(
    fen: str,
    move_uci: str | None,
) -> dict[str, Any]:
    if not move_uci:
        return {}
    try:
        before = chess.Board(fen)
        move = chess.Move.from_uci(move_uci)
    except (TypeError, ValueError):
        return {}
    if move not in before.legal_moves:
        return {}

    moved_piece = before.piece_at(move.from_square)
    if moved_piece is None:
        return {}
    captured_piece = before.piece_at(move.to_square)
    after = before.copy(stack=False)
    after.push(move)

    newly_defended = []
    newly_attacked = []
    for square, piece in after.piece_map().items():
        if piece.color == moved_piece.color:
            previous_defenders = {
                attacker
                for attacker in before.attackers(moved_piece.color, square)
                if attacker != square
            }
            resulting_defenders = {
                attacker
                for attacker in after.attackers(moved_piece.color, square)
                if attacker != square
            }
            added = resulting_defenders - previous_defenders
            if added:
                newly_defended.append(
                    {
                        "piece": chess.piece_name(piece.piece_type),
                        "square": chess.square_name(square),
                        "under_enemy_pressure": bool(
                            after.attackers(not moved_piece.color, square)
                        ),
                        "new_defenders": [
                            detail
                            for attacker in sorted(added)
                            if (
                                detail := _piece_at_details(after, attacker)
                            )
                        ],
                    }
                )
        else:
            was_attacked = bool(
                before.attackers(moved_piece.color, square)
            )
            is_attacked = bool(after.attackers(moved_piece.color, square))
            if is_attacked and not was_attacked:
                newly_attacked.append(
                    {
                        "piece": chess.piece_name(piece.piece_type),
                        "square": chess.square_name(square),
                    }
                )

    piece_priority = {
        "queen": 5,
        "rook": 4,
        "bishop": 3,
        "knight": 3,
        "pawn": 2,
        "king": 1,
    }
    newly_defended.sort(
        key=lambda item: (
            not item["under_enemy_pressure"],
            -piece_priority.get(item["piece"], 0),
            item["square"],
        )
    )
    home_rank = 0 if moved_piece.color == chess.WHITE else 7
    develops_minor_piece = (
        moved_piece.piece_type in {chess.KNIGHT, chess.BISHOP}
        and chess.square_rank(move.from_square) == home_rank
        and chess.square_rank(move.to_square) != home_rank
    )
    return {
        "move": {
            "uci": move.uci(),
            "san": before.san(move),
        },
        "moved_piece": {
            "piece": chess.piece_name(moved_piece.piece_type),
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
        },
        "captured_piece": (
            {
                "piece": chess.piece_name(captured_piece.piece_type),
                "square": chess.square_name(move.to_square),
            }
            if captured_piece
            else None
        ),
        "develops_minor_piece": develops_minor_piece,
        "newly_defended_friendly_pieces": newly_defended[:6],
        "newly_attacked_enemy_pieces": newly_attacked[:6],
    }


def _reply_effects(
    record: dict[str, Any],
    move_uci: str | None,
    move_san: str | None = None,
) -> dict[str, Any]:
    if not move_uci:
        return {}
    try:
        before_played = chess.Board(record["previous_fen"])
        current = chess.Board(record["fen"])
        played_move = chess.Move.from_uci(record["played_move"]["uci"])
        reply = chess.Move.from_uci(move_uci)
    except (KeyError, TypeError, ValueError):
        return {}
    if reply not in current.legal_moves:
        return {}

    mover_color = not current.turn
    reply_target = reply.to_square
    defenders_before = _attacker_details(
        before_played,
        mover_color,
        reply_target,
    )
    defenders_after = _attacker_details(
        current,
        mover_color,
        reply_target,
    )
    defender_squares_after = {
        detail["square"] for detail in defenders_after
    }
    lost_defenders = [
        detail
        for detail in defenders_before
        if detail["square"] not in defender_squares_after
    ]
    moved_defender = next(
        (
            detail
            for detail in lost_defenders
            if detail["square"] == chess.square_name(played_move.from_square)
            and chess.square_name(played_move.to_square)
            not in defender_squares_after
        ),
        None,
    )

    after_reply = current.copy(stack=False)
    san = move_san or current.san(reply)
    after_reply.push(reply)
    newly_pinned = []
    for square, piece in current.piece_map().items():
        if piece.color != mover_color or piece.piece_type == chess.KING:
            continue
        if current.is_pinned(mover_color, square):
            continue
        if not after_reply.is_pinned(mover_color, square):
            continue

        attacked_enemy_pieces = []
        for target in sorted(current.attacks(square)):
            target_piece = current.piece_at(target)
            if target_piece is None or target_piece.color == mover_color:
                continue
            target_details = _piece_at_details(current, target)
            if target_details is None:
                continue
            target_details["attacks_friendly_pieces"] = [
                detail
                for attacked_square in sorted(current.attacks(target))
                if (
                    (attacked_piece := current.piece_at(attacked_square))
                    and attacked_piece.color == mover_color
                    and (
                        detail := _piece_at_details(current, attacked_square)
                    )
                )
            ][:6]
            attacked_enemy_pieces.append(target_details)

        king_square = after_reply.king(mover_color)
        pinning_square = (
            pinning_piece_for_absolute_pin(
                after_reply,
                mover_color,
                square,
                king_square,
            )
            if king_square is not None
            else None
        )
        if pinning_square is not None and king_square is not None:
            pin_evidence = build_pin_evidence(
                after_reply,
                pin_type="absolute",
                pinning_sq=pinning_square,
                pinned_sq=square,
                anchor_sq=king_square,
                defending_color=mover_color,
                definition=EX_ABSOLUTE_PIN,
                prev_board=current,
                last_move_uci=reply.uci(),
                status="created_by_reply",
                disabled_before=attacked_enemy_pieces[:4],
            )
        else:
            pin_evidence = {}
        pin_evidence.update(
            {
                "piece": chess.piece_name(piece.piece_type),
                "square": chess.square_name(square),
                "king": (
                    chess.square_name(king_square)
                    if king_square is not None
                    else None
                ),
                "attacked_enemy_pieces_before_pin": attacked_enemy_pieces[:4],
            }
        )
        newly_pinned.append(pin_evidence)

    return {
        "move": {"uci": reply.uci(), "san": san},
        "gives_check": after_reply.is_check(),
        "gives_checkmate": after_reply.is_checkmate(),
        "target_square": chess.square_name(reply_target),
        "defenders_before_played_move": defenders_before,
        "defenders_after_played_move": defenders_after,
        "lost_defenders": lost_defenders,
        "moved_piece_was_lost_defender": moved_defender,
        "new_absolute_pins": newly_pinned,
    }


def _reply_tactical_context(
    record: dict[str, Any],
    next_record: dict[str, Any] | None,
) -> dict[str, Any]:
    stockfish = record.get("stockfish") or {}
    first_line = (stockfish.get("top_lines") or [{}])[0]
    best_uci = ((first_line.get("moves_uci") or [None])[0])
    best_san = ((first_line.get("moves_san") or [None])[0])
    actual_move = (next_record or {}).get("played_move") or {}
    actual_uci = actual_move.get("uci")
    actual_san = actual_move.get("san")
    actual_matches_best = bool(
        actual_uci and best_uci and actual_uci == best_uci
    )

    best_reply = _reply_effects(record, best_uci, best_san)
    actual_reply = (
        None
        if actual_matches_best
        else _reply_effects(record, actual_uci, actual_san)
    )
    if not best_reply and not actual_reply:
        return {}
    return {
        "best_reply": best_reply or None,
        "actual_reply": actual_reply or None,
        "actual_matches_best": actual_matches_best,
    }


def _mover_engine_utility(
    evaluation: dict[str, Any] | None,
    mover: str,
) -> int | None:
    if not isinstance(evaluation, dict):
        return None
    if evaluation.get("type") == "mate":
        winner = evaluation.get("winner")
        mate_distance = abs(int(evaluation.get("value") or 0))
        if winner == mover:
            return 100_000 - mate_distance
        if winner in {"white", "black"}:
            return -100_000 + mate_distance
        return None
    value = evaluation.get("value")
    if not isinstance(value, int):
        return None
    return value if mover == "white" else -value


def _move_choice_evidence(
    stockfish_before: dict[str, Any],
    mover: str,
) -> dict[str, Any]:
    lines = stockfish_before.get("top_lines") or []
    alternatives = []
    for line in lines[:5]:
        moves_san = line.get("moves_san") or []
        moves_uci = line.get("moves_uci") or []
        alternatives.append(
            {
                "rank": line.get("rank"),
                "move_san": moves_san[0] if moves_san else None,
                "move_uci": moves_uci[0] if moves_uci else None,
                "evaluation": line.get("evaluation"),
            }
        )

    if len(lines) < 2:
        return {
            "classification": "alternatives_not_compared",
            "only_move": None,
            "reason": None,
            "best_vs_second_gap_cp": None,
            "alternatives": alternatives,
        }

    best_evaluation = lines[0].get("evaluation")
    second_evaluation = lines[1].get("evaluation")
    best_utility = _mover_engine_utility(best_evaluation, mover)
    second_utility = _mover_engine_utility(second_evaluation, mover)
    if best_utility is None or second_utility is None:
        return {
            "classification": "alternatives_inconclusive",
            "only_move": None,
            "reason": None,
            "best_vs_second_gap_cp": None,
            "alternatives": alternatives,
        }

    second_is_forced_mate_loss = (
        second_evaluation.get("type") == "mate"
        and second_evaluation.get("winner") != mover
    )
    best_is_forced_mate_loss = (
        best_evaluation.get("type") == "mate"
        and best_evaluation.get("winner") != mover
    )
    best_forces_mate = (
        best_evaluation.get("type") == "mate"
        and best_evaluation.get("winner") == mover
    )
    second_forces_mate = (
        second_evaluation.get("type") == "mate"
        and second_evaluation.get("winner") == mover
    )
    cp_gap = (
        best_utility - second_utility
        if abs(best_utility) < 90_000 and abs(second_utility) < 90_000
        else None
    )

    if second_is_forced_mate_loss and not best_is_forced_mate_loss:
        classification = "only_move"
        only_move = True
        reason = "uniquely_prevents_forced_mate"
    elif best_forces_mate and not second_forces_mate:
        classification = "only_move"
        only_move = True
        reason = "uniquely_forces_mate"
    elif (
        cp_gap is not None
        and best_utility >= -150
        and second_utility < -150
        and cp_gap >= 100
    ):
        classification = "only_move"
        only_move = True
        reason = "uniquely_preserves_a_playable_position"
    elif cp_gap is not None and cp_gap >= 100:
        classification = "clearly_best"
        only_move = False
        reason = "large_engine_gap"
    else:
        classification = "normal_best"
        only_move = False
        reason = "multiple_viable_moves"

    return {
        "classification": classification,
        "only_move": only_move,
        "reason": reason,
        "best_vs_second_gap_cp": cp_gap,
        "alternatives": alternatives,
    }


def add_decision_context(
    records: list[dict[str, Any]],
    initial_stockfish: dict[str, Any],
) -> None:
    previous_stockfish = initial_stockfish
    previous_motifs: list[dict[str, Any]] = []

    for record in records:
        previous_line = (previous_stockfish.get("top_lines") or [{}])[0]
        previous_moves_uci = previous_line.get("moves_uci") or []
        previous_moves_san = previous_line.get("moves_san") or []
        engine_first_uci = (
            previous_moves_uci[0] if previous_moves_uci else None
        )
        engine_first_san = (
            previous_moves_san[0] if previous_moves_san else None
        )
        played_uci = (record.get("played_move") or {}).get("uci")
        played_matches = bool(
            engine_first_uci and played_uci == engine_first_uci
        )
        tactical_before = any(
            motif.get("severity") in {"warning", "tactical", "critical"}
            for motif in previous_motifs
            if isinstance(motif, dict)
        )
        evaluation_before = previous_stockfish.get("evaluation")
        evaluation_after = (record.get("stockfish") or {}).get("evaluation")
        move_choice = _move_choice_evidence(previous_stockfish, record["side"])
        move_classification = _move_classification(
            record,
            evaluation_before,
            evaluation_after,
            played_matches_engine_first=played_matches,
        )

        record["decision_context"] = {
            "evaluation_before": evaluation_before,
            "evaluation_after": evaluation_after,
            "assessment_before": _evaluation_assessment(evaluation_before),
            "assessment_after": _evaluation_assessment(evaluation_after),
            "move_quality": _move_quality(
                record,
                evaluation_before,
                evaluation_after,
            ),
            "move_classification": move_classification,
            "move_effects": _move_piece_effects(record),
            "engine_first_choice": {
                "uci": engine_first_uci,
                "san": engine_first_san,
                "line_san": previous_moves_san,
                "line_uci": previous_moves_uci,
            },
            "engine_choice_effects": _candidate_move_effects(
                record["previous_fen"],
                engine_first_uci,
            ),
            "played_matches_engine_first": played_matches,
            "critical_tactical_position": tactical_before,
            "critical_engine_response": played_matches and tactical_before,
            "move_choice": move_choice,
            "only_move": move_choice["only_move"],
            "material_before": _material_summary(
                chess.Board(record["previous_fen"])
            ),
            "material_after": _material_summary(chess.Board(record["fen"])),
        }
        previous_stockfish = record["stockfish"]
        previous_motifs = record.get("motifs") or []

    for index, record in enumerate(records):
        next_record = records[index + 1] if index + 1 < len(records) else None
        record["decision_context"]["reply_tactics"] = _reply_tactical_context(
            record,
            next_record,
        )


def _analyse_stockfish_position(
    engine: Any,
    board: chess.Board,
    *,
    depth: int,
    max_seconds: float | None,
    multipv: int,
    game_token: object,
) -> dict[str, Any]:
    limit_kwargs: dict[str, Any] = {"depth": max(1, depth)}
    if max_seconds is not None and max_seconds > 0:
        limit_kwargs["time"] = max_seconds
    try:
        infos = engine.analyse(
            board,
            chess.engine.Limit(**limit_kwargs),
            multipv=max(1, multipv),
            game=game_token,
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
                "evaluation": _normalize_engine_score(
                    info["score"],
                    board,
                ),
                "depth": info.get("depth"),
                "seldepth": info.get("seldepth"),
                "nodes": info.get("nodes"),
                "time_ms": round(float(info.get("time", 0)) * 1000),
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
        "target_depth": depth,
        "depth": top_lines[0].get("depth"),
        "seldepth": top_lines[0].get("seldepth"),
        "nodes": top_lines[0].get("nodes"),
        "time_ms": top_lines[0].get("time_ms"),
        "multipv": multipv,
        "time_limit_seconds": max_seconds,
        "evaluation": top_lines[0]["evaluation"],
        "best_move": (
            top_lines[0]["moves_uci"][0]
            if top_lines[0]["moves_uci"]
            else None
        ),
        "top_lines": top_lines,
    }


def evaluate_with_stockfish(
    records: list[dict[str, Any]],
    *,
    depth: int,
    max_seconds: float | None = 1.25,
    multipv: int = 1,
    threads: int = 1,
    hash_mb: int = 64,
) -> tuple[dict[str, Any], dict[str, Any]]:
    engine = create_stockfish()
    boards = _stockfish_boards(records)
    game_token = object()
    started = time.perf_counter()

    try:
        engine.configure(
            {
                "Threads": max(1, threads),
                "Hash": max(16, hash_mb),
            }
        )
    except (chess.engine.EngineError, TypeError, AttributeError) as exc:
        try:
            engine.quit()
        except Exception:
            pass
        raise AnalysisError(
            "Stockfish rejected the configured resource limits.",
            code="stockfish_invalid_configuration",
            status_code=500,
            retryable=False,
        ) from exc

    try:
        initial = _analyse_stockfish_position(
            engine,
            boards[0],
            depth=depth,
            max_seconds=max_seconds,
            multipv=multipv,
            game_token=game_token,
        )
        previous_eval = initial["evaluation"]

        for record, board in zip(records, boards[1:]):
            stockfish = _analyse_stockfish_position(
                engine,
                board,
                depth=depth,
                max_seconds=max_seconds,
                multipv=multipv,
                game_token=game_token,
            )
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

        all_evaluations = [initial] + [
            record["stockfish"] for record in records
        ]
        achieved_depths = [
            value["depth"]
            for value in all_evaluations
            if isinstance(value.get("depth"), int) and value["depth"] > 0
        ]
        search_time_ms = sum(
            int(value.get("time_ms") or 0) for value in all_evaluations
        )
        engine_name = str(getattr(engine, "id", {}).get("name") or "Stockfish")
        provider = {
            "available": True,
            "engine": engine_name,
            "target_depth": depth,
            "time_limit_seconds_per_position": max_seconds,
            "multipv": multipv,
            "threads": threads,
            "hash_mb": hash_mb,
            "positions_evaluated": len(all_evaluations),
            "search_time_ms": search_time_ms,
            "wall_time_ms": round((time.perf_counter() - started) * 1000),
            "achieved_depth": {
                "minimum": min(achieved_depths) if achieved_depths else None,
                "median": statistics.median(achieved_depths)
                if achieved_depths
                else None,
                "maximum": max(achieved_depths) if achieved_depths else None,
            },
        }
        return initial, provider
    finally:
        try:
            engine.quit()
        except Exception:
            pass


def _critical_position_candidates(
    records: list[dict[str, Any]],
    initial_stockfish: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    previous_stockfish = initial_stockfish
    previous_motifs: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        current_stockfish = record.get("stockfish") or {}
        before = previous_stockfish.get("evaluation")
        after = current_stockfish.get("evaluation")
        move_quality = _move_quality(record, before, after)
        previous_tactical = any(
            motif.get("severity") in {"warning", "tactic", "tactical", "critical"}
            for motif in previous_motifs
            if isinstance(motif, dict)
        )
        current_tactical = any(
            motif.get("severity") in {"warning", "tactic", "tactical", "critical"}
            for motif in record.get("motifs") or []
            if isinstance(motif, dict)
        )
        mover_loss = current_stockfish.get("mover_loss_cp")
        previous_line = (previous_stockfish.get("top_lines") or [{}])[0]
        previous_moves_uci = previous_line.get("moves_uci") or []
        played_uci = (record.get("played_move") or {}).get("uci")
        played_matches_engine_first = bool(
            previous_moves_uci and played_uci == previous_moves_uci[0]
        )

        reasons = []
        priority = 0
        if move_quality in {
            "allows_forced_mate",
            "escapes_forced_mate",
            "misses_forced_mate",
            "creates_forced_mate",
        }:
            reasons.append(move_quality)
            priority += 200
        if isinstance(mover_loss, int) and mover_loss >= 80:
            reasons.append("large_evaluation_change")
            priority += min(mover_loss, 300)
        if previous_tactical:
            reasons.append("tactical_position_before_move")
            priority += 80
            if played_matches_engine_first:
                reasons.append("engine_first_tactical_response")
                priority += 80
        if current_tactical:
            reasons.append("tactical_position_after_move")
            priority += 40

        if reasons:
            candidates.append(
                {
                    "record_index": index,
                    "ply": record.get("ply"),
                    "priority": priority,
                    "reasons": reasons,
                }
            )

        previous_stockfish = current_stockfish
        previous_motifs = record.get("motifs") or []

    return sorted(
        candidates,
        key=lambda candidate: (-candidate["priority"], candidate["record_index"]),
    )


def enrich_critical_positions_with_multipv(
    records: list[dict[str, Any]],
    initial_stockfish: dict[str, Any],
    *,
    depth: int,
    max_seconds: float,
    multipv: int,
    max_positions: int,
    threads: int,
    hash_mb: int,
) -> dict[str, Any]:
    metadata = {
        "enabled": multipv >= 2 and max_positions > 0 and max_seconds > 0,
        "multipv": max(1, multipv),
        "max_positions": max(0, max_positions),
        "time_limit_seconds_per_position": max_seconds,
        "positions_selected": 0,
        "positions_analyzed": 0,
        "selected_plies": [],
        "search_time_ms": 0,
        "wall_time_ms": 0,
        "error": None,
    }
    if not metadata["enabled"]:
        return metadata

    candidates = _critical_position_candidates(records, initial_stockfish)
    selected = candidates[:max_positions]
    metadata["positions_selected"] = len(selected)
    metadata["selected_plies"] = [candidate["ply"] for candidate in selected]
    if not selected:
        return metadata

    boards = _stockfish_boards(records)
    try:
        engine = create_stockfish()
    except AnalysisError as exc:
        metadata["error"] = str(exc)
        return metadata
    game_token = object()
    started = time.perf_counter()
    try:
        engine.configure(
            {
                "Threads": max(1, threads),
                "Hash": max(16, hash_mb),
            }
        )
        for candidate in selected:
            index = candidate["record_index"]
            target = initial_stockfish if index == 0 else records[index - 1]["stockfish"]
            if len(target.get("top_lines") or []) >= multipv:
                continue
            comparison = _analyse_stockfish_position(
                engine,
                boards[index],
                depth=depth,
                max_seconds=max_seconds,
                multipv=multipv,
                game_token=game_token,
            )
            target["best_move"] = comparison["best_move"]
            target["top_lines"] = comparison["top_lines"]
            target["critical_multipv"] = {
                "performed": True,
                "reasons": candidate["reasons"],
                "multipv": multipv,
                "depth": comparison.get("depth"),
                "time_ms": comparison.get("time_ms"),
            }
            metadata["positions_analyzed"] += 1
            metadata["search_time_ms"] += int(comparison.get("time_ms") or 0)
    except Exception as exc:
        metadata["error"] = str(exc)
    finally:
        metadata["wall_time_ms"] = round(
            (time.perf_counter() - started) * 1000
        )
        try:
            engine.quit()
        except Exception:
            pass
    return metadata


def _lichess_headers() -> dict[str, str]:
    headers = {
        "User-Agent": "VirtualChessCoach/2.0 (portfolio project)",
        "Accept": "application/json",
    }
    token = os.getenv("LICHESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def lichess_status() -> dict[str, Any]:
    return {
        "configured": bool(os.getenv("LICHESS_TOKEN", "").strip()),
        "endpoint": LICHESS_EXPLORER_URL,
        "rating_groups": sorted(ALLOWED_RATING_GROUPS),
        "workers": max(1, min(LICHESS_WORKERS, 2)),
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

    session = _sessions[database]
    response = session.get(
        f"{LICHESS_EXPLORER_URL}/{database}",
        params=params,
        headers=_lichess_headers(),
        timeout=LICHESS_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        retry_after = min(int(response.headers.get("Retry-After", "1")), 5)
        time.sleep(max(retry_after, 1))
        response = session.get(
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


def collect_lichess_evidence(
    records: list[dict[str, Any]],
    *,
    rating_groups: tuple[int, ...] = (),
    speeds: tuple[str, ...] = (),
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    ordered_fens = list(
        dict.fromkeys(
            [records[0]["previous_fen"]]
            + [record["fen"] for record in records]
        )
    )
    explorer_cache: dict[tuple[str, str], dict[str, Any]] = {}
    database_failures: dict[str, str] = {}

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

    def load_database(database: str):
        results = {}
        failure_reason = None
        sample_exhausted = False
        for fen in ordered_fens:
            board = chess.Board(fen)
            if board.is_game_over():
                results[(fen, database)] = {
                    **_unavailable_explorer("Game is over."),
                    "available": True,
                    "reason": None,
                }
                continue
            if failure_reason:
                results[(fen, database)] = _unavailable_explorer(
                    failure_reason
                )
                continue
            if sample_exhausted:
                results[(fen, database)] = {
                    **_unavailable_explorer(
                        "No deeper games remain in this database sample."
                    ),
                    "available": True,
                    "reason": None,
                }
                continue

            result = load_explorer(fen, database)
            results[(fen, database)] = result
            if not result.get("available"):
                failure_reason = result.get("reason") or (
                    "Lichess Opening Explorer was unavailable."
                )
            elif result.get("total_games", 0) == 0:
                sample_exhausted = True
        return database, results, failure_reason

    with ThreadPoolExecutor(max_workers=max(1, min(LICHESS_WORKERS, 2))) as executor:
        futures = [
            executor.submit(load_database, database)
            for database in ("masters", "lichess")
        ]
        for future in futures:
            database, results, failure_reason = future.result()
            explorer_cache.update(results)
            if failure_reason:
                database_failures[database] = failure_reason

    metadata = {
        "wall_time_ms": round((time.perf_counter() - started) * 1000),
        "positions_requested": len(ordered_fens),
        "workers": max(1, min(LICHESS_WORKERS, 2)),
        "database_failures": database_failures,
    }
    return explorer_cache, metadata


def attach_lichess_evidence(
    records: list[dict[str, Any]],
    warnings: list[str],
    explorer_cache: dict[tuple[str, str], dict[str, Any]],
    *,
    rating_groups: tuple[int, ...] = (),
    speeds: tuple[str, ...] = (),
) -> None:
    if any(not value.get("available") for value in explorer_cache.values()):
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
        opening = (
            after_masters.get("opening")
            or after_players.get("opening")
            or before_masters.get("opening")
            or before_players.get("opening")
        )
        try:
            study_context = context_for_position(
                opening=opening,
                previous_fen=record["previous_fen"],
                fen=record["fen"],
                move_uci=uci,
            )
        except StudyDatabaseError:
            study_context = None
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
        record["study"] = study_context


def add_lichess_evidence(
    records: list[dict[str, Any]],
    warnings: list[str],
    *,
    rating_groups: tuple[int, ...] = (),
    speeds: tuple[str, ...] = (),
) -> dict[str, Any]:
    explorer_cache, metadata = collect_lichess_evidence(
        records,
        rating_groups=rating_groups,
        speeds=speeds,
    )
    attach_lichess_evidence(
        records,
        warnings,
        explorer_cache,
        rating_groups=rating_groups,
        speeds=speeds,
    )
    return metadata


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
            "winner": evaluation.get("winner"),
            "pv": (
                record["stockfish"]["top_lines"][0]["moves_uci"]
                if record["stockfish"].get("top_lines")
                else []
            ),
            "pv_san": (
                record["stockfish"]["top_lines"][0]["moves_san"]
                if record["stockfish"].get("top_lines")
                else []
            ),
        }
        try:
            candidates = detect_motifs(
                board=current_board,
                prev_board=previous_board,
                move_number=record["ply"],
                eval_cp=eval_cp,
                prev_eval=previous_eval_cp,
                sf_raw=sf_raw,
                last_move_uci=record["played_move"]["uci"],
                prev_move_uci=record["previous_move_uci"],
                include_experimental=True,
            )
            record["motifs"] = publish_motifs(candidates)
            publishable_candidates = [
                motif
                for motif in candidates
                if motif.get("confidence") != "experimental"
            ]
            record["motif_candidates_suppressed"] = sum(
                motif.get("confidence") == "experimental"
                for motif in candidates
            )
            record["motif_candidates_omitted_for_limit"] = max(
                0,
                len(publishable_candidates) - len(record["motifs"]),
            )
            record["motifs_available"] = True
        except Exception:
            motif_failures += 1
            record["motifs"] = []
            record["motif_candidates_suppressed"] = 0
            record["motif_candidates_omitted_for_limit"] = 0
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
                "study": position.get("study"),
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
    stockfish_depth: int = 24,
    stockfish_max_seconds: float | None = 1.25,
    stockfish_multipv: int = 1,
    stockfish_critical_multipv: int = 4,
    stockfish_critical_max_positions: int = 4,
    stockfish_critical_max_seconds: float = 0.3,
    stockfish_threads: int = 1,
    stockfish_hash_mb: int = 64,
    stockfish_total_seconds: float | None = 14.0,
    lichess_ratings: tuple[int, ...] | list[int] | None = None,
    lichess_speeds: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    analysis_started = time.perf_counter()
    game, _raw_text, warnings = _parse_game(pgn_bytes)
    positions, total_plies = _position_records(game, max_plies=max_plies)
    rating_groups = normalize_rating_groups(lichess_ratings)
    speeds = normalize_speeds(lichess_speeds)
    position_count = len(positions) + 1
    effective_stockfish_seconds = stockfish_max_seconds
    if (
        stockfish_total_seconds is not None
        and stockfish_total_seconds > 0
        and position_count > 0
    ):
        total_budget_per_position = stockfish_total_seconds / position_count
        if effective_stockfish_seconds is None:
            effective_stockfish_seconds = total_budget_per_position
        else:
            effective_stockfish_seconds = min(
                effective_stockfish_seconds,
                total_budget_per_position,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        stockfish_future = executor.submit(
            evaluate_with_stockfish,
            positions,
            depth=stockfish_depth,
            max_seconds=effective_stockfish_seconds,
            multipv=stockfish_multipv,
            threads=stockfish_threads,
            hash_mb=stockfish_hash_mb,
        )
        lichess_future = executor.submit(
            collect_lichess_evidence,
            positions,
            rating_groups=rating_groups,
            speeds=speeds,
        )
        initial_stockfish, stockfish_provider = stockfish_future.result()
        explorer_cache, lichess_metadata = lichess_future.result()
    stockfish_provider["configured_max_seconds_per_position"] = (
        stockfish_max_seconds
    )
    stockfish_provider["total_time_budget_seconds"] = stockfish_total_seconds

    attach_lichess_evidence(
        positions,
        warnings,
        explorer_cache,
        rating_groups=rating_groups,
        speeds=speeds,
    )
    add_motif_evidence(positions, warnings)
    critical_multipv = enrich_critical_positions_with_multipv(
        positions,
        initial_stockfish,
        depth=stockfish_depth,
        max_seconds=stockfish_critical_max_seconds,
        multipv=stockfish_critical_multipv,
        max_positions=stockfish_critical_max_positions,
        threads=stockfish_threads,
        hash_mb=stockfish_hash_mb,
    )
    stockfish_provider["critical_multipv"] = critical_multipv
    if critical_multipv.get("error"):
        warnings.append(
            "Alternative-move comparison was unavailable for one or more "
            "critical positions; coaching will avoid unsupported only-move claims."
        )
    add_decision_context(positions, initial_stockfish)
    studies = study_database_status()
    if not studies["available"]:
        warnings.append(
            "The optional project study database was unavailable; engine, "
            "Lichess, and motif evidence remain active."
        )

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
        "stockfish": stockfish_provider,
        "lichess": {
            **lichess_status(),
            **lichess_metadata,
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
            ),
            "published_confidence_levels": ["high", "medium"],
            "published_detector_ids": sorted(MOTIF_CONFIDENCE),
            "suppressed_experimental_candidates": sum(
                position.get("motif_candidates_suppressed", 0)
                for position in positions
            ),
        },
        "studies": studies,
    }
    result: dict[str, Any] = {
        "schema_version": 5,
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
        "analysis_wall_time_ms": round(
            (time.perf_counter() - analysis_started) * 1000
        ),
        "providers": providers,
        "positions": positions,
    }
    result["analysis_id"] = _analysis_id(metadata, positions)
    return result
