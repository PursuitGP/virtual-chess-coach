"""Gemini-backed synthesis and strict response validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any


PROMPT_VERSION = "2026-06-21.10"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
VALID_PERSPECTIVES = {"white", "black", "both"}
MAX_EXPLANATION_WORDS = 150


class AIConfigurationError(Exception):
    pass


class AIProviderError(Exception):
    pass


class AIResponseError(Exception):
    pass


def _model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def _api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _provider_attempts() -> int:
    try:
        return max(1, min(int(os.getenv("GEMINI_PROVIDER_ATTEMPTS", "2")), 3))
    except (TypeError, ValueError):
        return 2


def _is_transient_provider_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "503",
            "unavailable",
            "high demand",
            "temporarily",
            "timeout",
            "timed out",
            "connection reset",
            "500 internal",
        )
    )


def _load_genai():
    try:
        from google import genai
    except ImportError as exc:
        raise AIConfigurationError(
            "The maintained google-genai SDK is not installed."
        ) from exc
    return genai


def gemini_status() -> dict[str, Any]:
    configured = bool(_api_key())
    sdk_available = True
    try:
        _load_genai()
    except AIConfigurationError:
        sdk_available = False
    return {
        "configured": configured,
        "sdk_available": sdk_available,
        "ready": configured and sdk_available,
        "available": configured and sdk_available,
        "verified": False,
        "model": _model_name(),
    }


def verify_gemini_connection() -> dict[str, Any]:
    status = gemini_status()
    if not status["ready"]:
        return {
            **status,
            "verified": False,
            "error": "Gemini is not fully configured.",
        }

    genai = _load_genai()
    try:
        client = genai.Client(api_key=_api_key())
        response = client.models.generate_content(
            model=_model_name(),
            contents='Return only this JSON object: {"ok": true}',
            config={"response_mime_type": "application/json"},
        )
        payload = json.loads(_extract_json_text(response))
        verified = payload.get("ok") is True
        return {
            **status,
            "verified": verified,
            "error": None if verified else "Gemini returned an unexpected response.",
        }
    except Exception as exc:
        return {
            **status,
            "verified": False,
            "error": _safe_provider_error(exc),
        }


def _stockfish_summary(stockfish: dict[str, Any] | None) -> dict[str, Any]:
    stockfish = stockfish or {}
    return {
        "evaluation": stockfish.get("evaluation"),
        "eval_delta_cp": stockfish.get("eval_delta_cp"),
        "mover_loss_cp": stockfish.get("mover_loss_cp"),
        "best_move": stockfish.get("best_move"),
        "top_lines": [
            {
                "rank": line.get("rank"),
                "evaluation": line.get("evaluation"),
                "moves_san": (line.get("moves_san") or [])[:8],
                "moves_uci": (line.get("moves_uci") or [])[:8],
            }
            for line in (stockfish.get("top_lines") or [])[:4]
            if isinstance(line, dict)
        ],
    }


def _motif_summary(motifs: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": motif.get("id"),
            "name": motif.get("name"),
            "side": motif.get("side"),
            "severity": motif.get("severity"),
            "confidence": motif.get("confidence"),
            "extra": motif.get("extra") or {},
        }
        for motif in (motifs or [])
        if isinstance(motif, dict)
    ]


def _lichess_summary(lichess: dict[str, Any] | None) -> dict[str, Any]:
    lichess = lichess or {}

    def database_summary(name: str) -> dict[str, Any]:
        database = lichess.get(name) or {}
        return {
            "available": database.get("available"),
            "position_games_before": database.get("position_games_before"),
            "played_move": database.get("played_move"),
            "continuations": (database.get("continuations") or [])[:3],
        }

    return {
        "opening": lichess.get("opening"),
        "theory_status": lichess.get("theory_status"),
        "practical_signal": lichess.get("practical_signal"),
        "practical_candidates": (lichess.get("practical_candidates") or [])[:3],
        "masters": database_summary("masters"),
        "players": database_summary("players"),
    }


def _context_summary(position: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(position, dict):
        return None
    stockfish = position.get("stockfish") or {}
    decision = position.get("decision_context") or {}
    engine_choice = decision.get("engine_first_choice") or {}
    move_classification = decision.get("move_classification") or {}
    return {
        "ply": position.get("ply"),
        "side": position.get("side"),
        "played_move": position.get("played_move"),
        "fen": position.get("fen"),
        "stockfish": {
            "evaluation": stockfish.get("evaluation"),
            "eval_delta_cp": stockfish.get("eval_delta_cp"),
            "mover_loss_cp": stockfish.get("mover_loss_cp"),
            "first_line_san": (
                ((stockfish.get("top_lines") or [{}])[0].get("moves_san") or [])
                [:4]
            ),
        },
        "decision_context": {
            "assessment_after": decision.get("assessment_after"),
            "move_quality": decision.get("move_quality"),
            "move_classification": {
                "label": move_classification.get("label"),
                "centipawn_loss": move_classification.get("centipawn_loss"),
                "estimated_win_probability_loss_pct": move_classification.get(
                    "estimated_win_probability_loss_pct"
                ),
            },
            "engine_first_choice": {
                "san": engine_choice.get("san"),
                "uci": engine_choice.get("uci"),
            },
            "played_matches_engine_first": decision.get(
                "played_matches_engine_first"
            ),
        },
        "motifs": _motif_summary(position.get("motifs"))[:5],
    }


def _required_coaching_points(position: dict[str, Any]) -> list[str]:
    points = []
    decision = position.get("decision_context") or {}
    before = decision.get("assessment_before") or {}
    after = decision.get("assessment_after") or {}
    engine_choice = decision.get("engine_first_choice") or {}
    material = decision.get("material_after") or {}
    stockfish = position.get("stockfish") or {}
    best_reply = ((stockfish.get("top_lines") or [{}])[0].get("moves_san") or [])
    motifs = position.get("motifs") or []
    move_choice = decision.get("move_choice") or {}
    move_classification = decision.get("move_classification") or {}
    move_effects = decision.get("move_effects") or {}
    reply_tactics = decision.get("reply_tactics") or {}
    engine_effects = decision.get("engine_choice_effects") or {}

    points.append(
        "Lead with the concrete board reason the move works or fails. A verdict "
        "without the mechanism is not useful coaching."
    )
    tactical_reply = (
        reply_tactics.get("actual_reply")
        if reply_tactics.get("actual_matches_best")
        else None
    ) or reply_tactics.get("best_reply") or reply_tactics.get("actual_reply") or {}
    moved_defender = tactical_reply.get("moved_piece_was_lost_defender")
    reply_move = (tactical_reply.get("move") or {}).get("san")
    if moved_defender:
        target_square = tactical_reply.get("target_square")
        consequence = (
            ", which delivers checkmate"
            if tactical_reply.get("gives_checkmate")
            else ""
        )
        points.append(
            f"Explain that moving the {moved_defender.get('piece')} away from "
            f"{moved_defender.get('square')} abandons its defense of "
            f"{target_square}, allowing {reply_move}{consequence}."
        )

    new_pins = tactical_reply.get("new_absolute_pins") or []
    if new_pins:
        pin = new_pins[0]
        attacked = pin.get("attacked_enemy_pieces_before_pin") or []
        target = attacked[0] if attacked else {}
        pressure = target.get("attacks_friendly_pieces") or []
        pressure_text = (
            f", which keeps pressure on the {pressure[0].get('piece')} on "
            f"{pressure[0].get('square')}"
            if pressure
            else ""
        )
        points.append(
            f"Explain that {reply_move} pins the {pin.get('piece')} on "
            f"{pin.get('square')} to the king on {pin.get('king')}. Before the "
            f"pin it attacked the {target.get('piece')} on "
            f"{target.get('square')}; after the pin that attack is unusable"
            f"{pressure_text}."
        )

    engine_move = (engine_effects.get("move") or {}).get("san")
    newly_defended_by_engine = [
        piece
        for piece in (
            engine_effects.get("newly_defended_friendly_pieces") or []
        )
        if piece.get("under_enemy_pressure")
        and piece.get("piece") in {"queen", "rook", "bishop", "knight"}
    ]
    if engine_move and newly_defended_by_engine:
        defended = newly_defended_by_engine[0]
        defender = (defended.get("new_defenders") or [{}])[0]
        development = (
            " develops a new minor piece and"
            if engine_effects.get("develops_minor_piece")
            else ""
        )
        points.append(
            f"Contrast the played move with {engine_move}: it{development} makes "
            f"the {defender.get('piece')} on {defender.get('square')} a new "
            f"defender of the {defended.get('piece')} on "
            f"{defended.get('square')}."
        )

    classification = move_classification.get("label")
    if classification in {"inaccuracy", "mistake", "blunder"}:
        points.append(
            f"Use the deterministic label {classification!r} at most once. Do "
            "not explain the classification thresholds, centipawn loss, or "
            "modeled winning-chance percentage in the coaching prose."
        )
    if decision.get("move_quality") == "allows_forced_mate":
        points.append(
            "In no more than one sentence, state that this was not a forced "
            f"mate before the move, contrast it with the new forced mate, and name "
            f"{engine_choice.get('san')} as the engine's first defense. Spend "
            "the remaining explanation on the mating mechanism, not repeated "
            "verdict language."
        )
    if decision.get("only_move") is True:
        alternatives = move_choice.get("alternatives") or []
        second_move = (
            alternatives[1].get("move_san")
            if len(alternatives) > 1
            else None
        )
        subject = (
            f"the played move {position.get('played_move', {}).get('san')}"
            if decision.get("played_matches_engine_first")
            else f"the engine defense {engine_choice.get('san')}"
        )
        reason = {
            "uniquely_prevents_forced_mate": "uniquely prevents forced mate",
            "uniquely_forces_mate": "uniquely preserves the forced mating line",
            "uniquely_preserves_a_playable_position": (
                "is the only compared move that preserves a playable evaluation"
            ),
        }.get(move_choice.get("reason"), "is uniquely necessary")
        comparison = (
            f"; the next-best engine move is {second_move}"
            if second_move
            else ""
        )
        points.append(
            f"Explain that {subject} {reason}{comparison}, using the supplied "
            "MultiPV comparison rather than opening memory."
        )
    elif move_choice.get("classification") == "clearly_best":
        points.append(
            "Explain the concrete engine gap that makes the first choice clearly "
            "better than the alternatives, but do not call it the only move."
        )
    elif decision.get("critical_engine_response"):
        points.append(
            "Explain why this is a critical engine-first response to the "
            "tactical threat, without calling it the only move."
        )

    for motif in motifs:
        if motif.get("id") == "fork":
            extra = motif.get("extra") or {}
            attacker = extra.get("forking_piece") or {}
            targets = extra.get("targets") or []
            if isinstance(attacker, dict) and targets:
                target_text = ", ".join(
                    f"{target.get('piece')} on {target.get('square')}"
                    for target in targets
                )
                points.append(
                    f"Explain the {attacker.get('piece')} on "
                    f"{attacker.get('square')} attacking {target_text}."
                )
                if extra.get("includes_check") and best_reply:
                    points.append(
                        f"Name {best_reply[0]} as the engine's best reply to "
                        "the check."
                    )
        if motif.get("id") == "forced_mate":
            extra = motif.get("extra") or {}
            safe_count = extra.get("safe_adjacent_square_count")
            king_square = extra.get("defending_king_square")
            line = extra.get("mate_line_san") or []
            if not (
                moved_defender
                and tactical_reply.get("gives_checkmate")
            ):
                points.append(
                    f"Explain that the king on {king_square} has {safe_count} "
                    "immediately safe adjacent squares and connect that "
                    "confinement to the mating attack."
                )
            if line:
                points.append(
                    "Use the supplied mating line: " + " ".join(line) + "."
                )
        if motif.get("id") == "f2_f7_weakness":
            extra = motif.get("extra") or {}
            threat = extra.get("threat_move_san")
            fork_targets = extra.get("fork_targets") or []
            if threat and fork_targets:
                targets = " and ".join(
                    f"{target.get('piece')} on {target.get('square')}"
                    for target in fork_targets
                )
                points.append(
                    f"State that {threat} is threatened and would fork "
                    f"{targets}; do not describe the pressure on "
                    f"{extra.get('target_square')} only in general terms."
                )

    newly_defended = [
        piece
        for piece in (
            move_effects.get("newly_defended_friendly_pieces") or []
        )
        if piece.get("under_enemy_pressure")
    ]
    if newly_defended and classification not in {
        "inaccuracy",
        "mistake",
        "blunder",
    }:
        moved_piece = move_effects.get("moved_piece") or {}
        defended = ", ".join(
            f"{piece.get('piece')} on {piece.get('square')}"
            for piece in newly_defended[:2]
        )
        points.append(
            f"Recognize that the {moved_piece.get('piece')} on "
            f"{moved_piece.get('to')} now defends the friendly {defended}; "
            "do not call that piece newly vulnerable."
        )

    objective_leader = after.get("leader")
    material_leader = material.get("leader")
    if (
        objective_leader
        and material_leader
        and objective_leader != material_leader
        and material.get("advantage_pawns")
    ):
        points.append(
            f"Distinguish {material_leader}'s "
            f"{material.get('advantage_pawns')}-point material edge from "
            f"{objective_leader}'s {after.get('classification')} engine edge."
        )

    if (
        not decision.get("critical_tactical_position")
        and (position.get("ply") or 0) <= 4
    ):
        points.append(
            "Treat this as a routine opening move: emphasize its human purpose "
            "and omit generic engine endorsement."
        )
    return points[:8]


def _coaching_focus(position: dict[str, Any]) -> list[dict[str, Any]]:
    """Select structured, time-scoped facts without writing coaching prose."""
    decision = position.get("decision_context") or {}
    reply_tactics = decision.get("reply_tactics") or {}
    reply = (
        reply_tactics.get("best_reply")
        if reply_tactics.get("actual_matches_best")
        else reply_tactics.get("actual_reply")
    ) or reply_tactics.get("best_reply") or {}
    focus: list[dict[str, Any]] = []

    moved_defender = reply.get("moved_piece_was_lost_defender")
    if moved_defender:
        focus.append(
            {
                "type": "defensive_duty_lost_after_played_move",
                "timing": "position_after_played_move",
                "played_move": position.get("played_move"),
                "defender_before_move": moved_defender,
                "defended_square": reply.get("target_square"),
                "opponent_reply": reply.get("move"),
                "reply_gives_check": reply.get("gives_check"),
                "reply_gives_checkmate": reply.get("gives_checkmate"),
            }
        )

    for pin in (reply.get("new_absolute_pins") or [])[:2]:
        focus.append(
            {
                "type": "absolute_pin_created_by_opponent_reply",
                "timing": "position_after_opponent_reply",
                "played_move": position.get("played_move"),
                "opponent_reply": reply.get("move"),
                "pinned_piece": {
                    "piece": pin.get("piece"),
                    "square": pin.get("square"),
                },
                "king_square": pin.get("king"),
                "targets_attacked_before_pin": pin.get(
                    "attacked_enemy_pieces_before_pin"
                )
                or [],
            }
        )

    engine_effects = decision.get("engine_choice_effects") or {}
    classification = (decision.get("move_classification") or {}).get("label")
    has_tactical_reason = bool(focus or classification in {"mistake", "blunder"})
    if has_tactical_reason:
        useful_defenses = [
            piece
            for piece in (
                engine_effects.get("newly_defended_friendly_pieces") or []
            )
            if piece.get("under_enemy_pressure")
            and piece.get("piece") in {"queen", "rook", "bishop", "knight"}
        ]
        if engine_effects.get("move") and (
            useful_defenses or engine_effects.get("develops_minor_piece")
        ):
            focus.append(
                {
                    "type": "engine_alternative_board_effects",
                    "timing": "alternative_from_position_before_played_move",
                    "engine_move": engine_effects.get("move"),
                    "moved_piece": engine_effects.get("moved_piece"),
                    "develops_minor_piece": engine_effects.get(
                        "develops_minor_piece"
                    ),
                    "newly_defended_friendly_pieces": useful_defenses[:3],
                    "newly_attacked_enemy_pieces": (
                        engine_effects.get("newly_attacked_enemy_pieces") or []
                    )[:3],
                }
            )
    return focus


def _condense_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    source_positions = analysis.get("positions", [])
    positions = []
    for index, position in enumerate(source_positions):
        previous_position = (
            source_positions[index - 1]
            if index > 0
            else {
                "ply": 0,
                "side": None,
                "played_move": None,
                "fen": position.get("previous_fen"),
                "stockfish": analysis.get("initial_stockfish") or {},
                "motifs": [],
            }
        )
        next_position = (
            source_positions[index + 1]
            if index + 1 < len(source_positions)
            else None
        )
        positions.append(
            {
                "ply": position.get("ply"),
                "fullmove_number": position.get("fullmove_number"),
                "side": position.get("side"),
                "played_move": position.get("played_move"),
                "previous_fen": position.get("previous_fen"),
                "fen": position.get("fen"),
                "stockfish": _stockfish_summary(position.get("stockfish")),
                "decision_context": position.get("decision_context"),
                "lichess": _lichess_summary(position.get("lichess")),
                "study": position.get("study"),
                "motifs": _motif_summary(position.get("motifs")),
                "motifs_available": position.get("motifs_available"),
                "sequence_context": {
                    "previous_position": _context_summary(previous_position),
                    "next_position": _context_summary(next_position),
                },
                "coaching_focus": _coaching_focus(position),
                "available_evidence_refs": sorted(
                    _allowed_refs(
                        position,
                        previous_position=previous_position,
                        next_position=next_position,
                    )
                ),
            }
        )
    return {
        "analysis_id": analysis.get("analysis_id"),
        "metadata": analysis.get("metadata", {}),
        "moves": analysis.get("moves", []),
        "warnings": analysis.get("warnings", []),
        "positions": positions,
    }


def _coaching_focus_briefing(positions: list[dict[str, Any]]) -> str:
    """Render coaching_focus items as a human-readable tactical briefing.

    The briefing surfaces the structured facts that most need to appear in
    the coaching prose so the model sees them as plain English before reading
    the JSON evidence package.
    """
    lines: list[str] = []
    for pos in positions:
        focus = pos.get("coaching_focus") or []
        if not focus:
            continue
        ply = pos.get("ply")
        played_san = (pos.get("played_move") or {}).get("san", "")
        side = pos.get("side", "")
        for item in focus:
            item_type = item.get("type")
            if item_type == "absolute_pin_created_by_opponent_reply":
                reply_san = (item.get("opponent_reply") or {}).get("san", "")
                pinned = item.get("pinned_piece") or {}
                pinned_piece = pinned.get("piece", "")
                pinned_sq = pinned.get("square", "")
                king_sq = item.get("king_square", "")
                targets = item.get("targets_attacked_before_pin") or []
                target_clause = ""
                if targets:
                    t = targets[0]
                    pressure = t.get("attacks_friendly_pieces") or []
                    target_clause = (
                        f" Before the pin the {pinned_piece} on {pinned_sq} was"
                        f" attacking the {t.get('piece')} on {t.get('square')}"
                        f" and can no longer do so."
                    )
                    if pressure:
                        p = pressure[0]
                        target_clause += (
                            f" That keeps pressure on the {p.get('piece')}"
                            f" on {p.get('square')}."
                        )
                lines.append(
                    f"Ply {ply} ({played_san}, {side}): {reply_san} creates an"
                    f" absolute pin on the {pinned_piece} on {pinned_sq} to the"
                    f" king on {king_sq} — this pin exists only AFTER {reply_san},"
                    f" not after {played_san}.{target_clause}"
                )
            elif item_type == "defensive_duty_lost_after_played_move":
                reply_san = (item.get("opponent_reply") or {}).get("san", "")
                defended_sq = item.get("defended_square", "")
                checkmate = item.get("reply_gives_checkmate")
                consequence = "delivering checkmate" if checkmate else reply_san
                lines.append(
                    f"Ply {ply} ({played_san}, {side}): {played_san} removes the"
                    f" defender of {defended_sq}, enabling {consequence}."
                )
            elif item_type == "engine_alternative_board_effects":
                engine_move = (item.get("engine_move") or {}).get("san", "")
                defended = item.get("newly_defended_friendly_pieces") or []
                develops = item.get("develops_minor_piece")
                if not engine_move:
                    continue
                effects: list[str] = []
                if develops:
                    moved_piece = item.get("moved_piece") or {}
                    effects.append(
                        f"develops the {moved_piece.get('piece')} from"
                        f" {moved_piece.get('from')}"
                    )
                for d in defended[:2]:
                    new_def = (d.get("new_defenders") or [{}])[0]
                    effects.append(
                        f"makes the {new_def.get('piece')} on"
                        f" {new_def.get('square')} a new defender of the"
                        f" {d.get('piece')} on {d.get('square')}"
                    )
                if effects:
                    lines.append(
                        f"Ply {ply} ({played_san}, {side}): Alternative"
                        f" {engine_move} "
                        + " and ".join(effects)
                        + "."
                    )
    if not lines:
        return ""
    header = (
        "TACTICAL BRIEFING — the following facts are grounded in the evidence"
        " and must appear when they are relevant to the position being coached."
        " Use the exact pieces, squares, and timing stated here:"
    )
    return header + "\n" + "\n".join(f"  • {line}" for line in lines)


def _build_prompt(analysis: dict[str, Any], perspective: str) -> str:
    evidence = _condense_analysis(analysis)
    perspective_instruction = {
        "white": "Coach from White's perspective at every ply.",
        "black": "Coach from Black's perspective at every ply.",
        "both": "Explain what each played move means for both players, emphasizing the side that just moved.",
    }[perspective]
    briefing = _coaching_focus_briefing(evidence.get("positions") or [])

    return f"""
You are the synthesis layer in an evidence-grounded chess coaching system.
{perspective_instruction}

The evidence package was produced by Stockfish, Lichess Opening Explorer,
custom chess motif detectors, and an optional project-authored study database.
Chess claims must be grounded in that package. Do not independently reconstruct
the game or invent analysis.

Rules:
1. Return JSON only, with this shape:
   {{"explanations": [{{
     "ply": 1,
     "move": "e4",
     "side": "white",
     "explanation": "Position-specific coaching, usually 45-110 words.",
     "lesson": "One concise practical lesson.",
     "evidence_refs": ["stockfish.evaluation", "lichess.players.played_move"]
   }}]}}
2. Return exactly one object for every supplied position, in the same order.
3. Copy ply, move, and side exactly from the evidence package.
4. Aim for 45-110 words in explanation, with a hard maximum of 150 words.
   Sentence count is flexible; use as many clear sentences as the position
   genuinely needs. Explain what the move changed, the concrete target or
   motif, the opponent's practical problem, and why the engine/context
   supports the conclusion. Do not pad the answer with generic opening
   principles. coaching_focus contains selected structured facts that are
   especially useful for explaining the position. Use the relevant facts
   naturally; do not turn every field into a sentence.
   Lead with the causal mechanism. Mention the move label or evaluation change
   at most once, then make every remaining sentence add a new piece, square,
   threat, defensive duty, or useful alternative. Never paraphrase "the move
   is bad and the position is worse" in several different ways.
5. Never invent moves, variations, probabilities, opening names, evaluations,
   or tactical claims.
6. A move or variation may be named only when it appears in stockfish.top_lines,
   lichess.practical_candidates, sequence_context.next_position.played_move, or
   a motif's structured extra data such as threat_move_san. Prefer SAN for
   human-readable notation and use UCI only for exact alignment.
7. Use sequence_context to connect the previous position, the played move, and
   the opponent's actual next response. The next move is outcome context, not
   proof that it was best. Explain resulting evaluation changes only when the
   supplied values support that claim.
8. When a motif's extra data names attackers, target squares, a threat move, or
   fork targets, surface those concrete pieces and squares instead of reducing
   the idea to a generic motif label.
9. Use decision_context as the authority for what changed across the move:
   evaluation_before is the position the player faced, evaluation_after is the
   result of the move, and engine_first_choice is the best move from the
   position before the move. Never treat the best reply after a move as though
   it were the move the player should have chosen.
   move_classification is the sole authority for labels such as inaccuracy,
   mistake, and blunder. Never infer or upgrade one of those labels yourself.
   move_effects identifies friendly pieces newly defended by the moved piece;
   do not call one of those pieces newly loose or vulnerable.
   reply_tactics identifies concrete consequences of the best or actual reply,
   including abandoned defensive squares and newly created absolute pins.
   engine_choice_effects explains useful board changes made by the engine's
   preferred alternative.
   Timing is strict: the played move produces position_after_played_move. An
   opponent reply then produces position_after_opponent_reply. A motif marked
   position_after_opponent_reply does not exist immediately after the played
   move. Say that the played move "allows" or "permits" the reply; attribute
   the resulting pin, fork, check, or mate to the reply itself.
10. If decision_context.move_quality is "allows_forced_mate", explicitly say
    that the position was not previously lost by force, name the engine's best
    defense, and explain the new mating mechanism from the forced_mate motif
    and Stockfish line. If it is "creates_forced_mate", explain the move that
    starts the forced sequence.
11. Evaluation vocabulary is strict. "roughly_equal" means neither side is
    winning. "slight_edge" means only a modest preference. Do not use "winning",
    "overwhelming", "completely lost", or "forced mate" unless assessment_after
    is decisive_advantage or forced_mate and the wording matches that evidence.
12. Material and objective evaluation are different. If material_before or
    material_after favors one side while the engine favors the other, explain
    that distinction when it is central to the position.
13. Never say "only move" unless decision_context.only_move is true. This field
    describes engine_first_choice. If played_matches_engine_first is false,
    apply "only move" to the engine choice, never to the played move. Use
    move_choice.reason and alternatives to explain the comparison. When
    only_move is null, no alternatives were compared. Avoid empty superlatives
    such as "most forcing" when the evidence supplies no comparison.
14. On routine early moves with no critical_tactical_position, explain the
    move's board purpose and human plan. Do not spend a sentence merely saying
    the engine supports a standard move.
15. When sequence_context.next_position.played_move matches the first SAN move
   in stockfish.top_lines, describe it as an engine-supported response when it
   helps the lesson.
16. Treat motif findings as heuristic context, not infallible truth. A "high"
   confidence motif has a literal board-state definition. A "medium" confidence
   motif is useful context but must be phrased cautiously and corroborated with
   Stockfish where it affects move quality.
17. Distinguish engine-backed conclusions from coaching interpretation.
18. Do not explain centipawn thresholds, modeled winning-chance percentages, or
    the move-classification formula in coaching prose. Those metrics belong in
    supporting analysis. Use a number only when it directly clarifies a mate
    distance, material count, or concrete variation.
19. Avoid generic advice that is not tied to this position.
20. Every evidence_refs item must identify evidence actually used. For each
    ply, copy references only from that position's available_evidence_refs
    list. Never cite a field merely because it exists on another ply.
21. Cite context.previous_position or context.next_position when the explanation
    uses adjacent-position evidence.
22. If Lichess or motif evidence is unavailable, rely on the available
    Stockfish evidence and say nothing about the missing source.
23. Lichess statistics describe human results, not objective move quality.
    Never call a move objectively best because it has a high win rate.
24. Reward a master-aligned move only when the Stockfish evidence also says it
    is sound. A common rating-pool mistake may be reassuringly described as
    understandable, but it must still be corrected clearly.
25. "sound-novelty-candidate" means absent from the selected sample while
    remaining engine-sound. Never claim historical novelty.
26. Practical continuation recommendations must come from
    lichess.practical_candidates, where Stockfish lines are already joined to
    master and selected-rating statistics.
27. Use an opening name only when it appears in lichess.opening. PGN metadata
    such as Event is descriptive user input, not proof of an opening name.
28. Use study only when a project-authored study entry is present. Study notes
    are optional human context and never override Stockfish, the actual board,
    or structured motifs. Do not browse the internet or invent historical
    opening background.
29. The practical lesson must be a reusable decision check tied to this exact
    mechanism. Avoid empty advice such as "watch for tactics," "be careful,"
    "winning material is good," or "develop your pieces."
{(chr(10) + briefing + chr(10)) if briefing else ""}
Perspective: {perspective}
Prompt version: {PROMPT_VERSION}
Evidence package:
{json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))}
""".strip()


def _extract_json_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise AIResponseError("Gemini returned an empty response.")


def _allowed_refs(
    position: dict[str, Any],
    *,
    previous_position: dict[str, Any] | None = None,
    next_position: dict[str, Any] | None = None,
) -> set[str]:
    refs = {"stockfish.evaluation"}
    stockfish = position.get("stockfish") or {}
    if stockfish.get("eval_delta_cp") is not None:
        refs.add("stockfish.eval_delta")
    if stockfish.get("best_move"):
        refs.add("stockfish.best_move")
    if stockfish.get("top_lines"):
        refs.add("stockfish.top_lines")
    if position.get("decision_context"):
        refs.add("decision_context")

    lichess = position.get("lichess") or {}
    if lichess.get("opening"):
        refs.add("lichess.opening")
    if lichess.get("theory_status"):
        refs.add("lichess.theory_status")
    if lichess.get("practical_signal"):
        refs.add("lichess.practical_signal")
    if lichess.get("practical_candidates"):
        refs.add("lichess.practical_candidates")
    for database in ("masters", "players"):
        evidence = lichess.get(database) or {}
        if evidence.get("played_move"):
            refs.add(f"lichess.{database}.played_move")
        if evidence.get("continuations"):
            refs.add(f"lichess.{database}.continuations")

    for motif in position.get("motifs") or []:
        if isinstance(motif, dict) and motif.get("id"):
            refs.add(f"motifs.{motif['id']}")
    if position.get("study"):
        refs.add("study.context")
    if previous_position:
        refs.add("context.previous_position")
    if next_position:
        refs.add("context.next_position")
    return refs


def _word_count(text: str) -> int:
    return len(text.split())


def _trim_to_word_limit(text: str, max_words: int) -> str:
    if max_words <= 0:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words]).rstrip(" ,;:-")
    return trimmed if trimmed.endswith((".", "!", "?")) else f"{trimmed}."


def _split_sentences(text: str) -> list[str]:
    return [
        part
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text.strip())
        if part.strip()
    ]


def _assessment_phrase(assessment: dict[str, Any]) -> str:
    classification = assessment.get("classification")
    leader = assessment.get("leader")
    labels = {
        "roughly_equal": "roughly equal",
        "slight_edge": f"only a slight edge for {leader}",
        "clear_advantage": f"a clear advantage for {leader}",
        "decisive_advantage": f"a decisive advantage for {leader}",
        "forced_mate": f"forced mate for {leader}",
    }
    return labels.get(classification, classification or "unclear")


def _select_tactical_reply(decision: dict[str, Any]) -> dict[str, Any]:
    reply_tactics = decision.get("reply_tactics") or {}
    actual = reply_tactics.get("actual_reply") or {}
    best = reply_tactics.get("best_reply") or {}
    if reply_tactics.get("actual_matches_best"):
        return actual or best
    if (
        actual.get("moved_piece_was_lost_defender")
        or actual.get("new_absolute_pins")
    ):
        return actual
    return best or actual


def _prune_low_information_sentences(sentences: list[str]) -> list[str]:
    def is_concrete(sentence: str) -> bool:
        squares = re.findall(r"\b[a-h][1-8]\b", sentence.lower())
        mechanism = re.search(
            r"\b(?:defend|guard|pin|fork|attack|block|open(?:s|ed|ing)? "
            r"(?:a )?line|overload|trapped|cannot move|cannot chase)\b",
            sentence,
            re.I,
        )
        return len(set(squares)) >= 2 or bool(squares and mechanism)

    has_concrete_mechanism = any(is_concrete(sentence) for sentence in sentences)
    pruned = []
    verdict_seen = False
    for sentence in sentences:
        lower = sentence.lower()
        if (
            "under this review's thresholds" in lower
            or "modeled winning-chance" in lower
            or (
                "centipawn" in lower
                and (
                    "percentage point" in lower
                    or "win probability" in lower
                    or "winning chance" in lower
                )
            )
        ):
            continue

        verdict = bool(
            re.search(
                r"\b(?:inaccuracy|mistake|blunder|error|forced mate|"
                r"decisive advantage|lost position)\b",
                lower,
            )
        )
        generic_recap = bool(
            re.search(
                r"\b(?:significant error|critical (?:blunder|error)|"
                r"tactical trap|"
                r"changes? the evaluation|position collapses|"
                r"overlooks? (?:the )?tactical threats?|"
                r"leads? to (?:an )?(?:immediate )?(?:loss|lost position)|"
                r"ends? the game (?:immediately)?|"
                r"fails? to address (?:the )?(?:multiple )?threats?)\b",
                lower,
            )
        )
        if has_concrete_mechanism and verdict and not is_concrete(sentence):
            continue
        if verdict_seen and generic_recap:
            continue
        if verdict:
            verdict_seen = True
        pruned.append(sentence)
    return pruned


def _ground_lesson(lesson: str, position: dict[str, Any]) -> str:
    decision = position.get("decision_context") or {}
    reply = _select_tactical_reply(decision)
    moved_defender = reply.get("moved_piece_was_lost_defender")
    if moved_defender:
        target = reply.get("target_square")
        if (
            "defend" not in lesson.lower()
            or (target and target.lower() not in lesson.lower())
        ):
            return (
                f"Before moving a sole defender, check whether it is guarding "
                f"{target} against a forcing check or mate."
            )

    pins = reply.get("new_absolute_pins") or []
    pin_lesson_specific = (
        "pin" in lesson.lower()
        and "queen" in lesson.lower()
        and (
            "attack" in lesson.lower()
            or "move" in lesson.lower()
            or "unusable" in lesson.lower()
        )
    )
    if pins and not pin_lesson_specific:
        return (
            f"When a piece attacks a queen, check whether a pin to the king can "
            f"make that attack unusable."
        )
    return lesson.strip()


def _ground_explanation(
    explanation: str,
    position: dict[str, Any],
) -> tuple[str, set[str]]:
    sentences = _prune_low_information_sentences(
        _split_sentences(explanation)
    )
    extra_refs: set[str] = set()
    decision = position.get("decision_context") or {}
    tactical_reply = _select_tactical_reply(decision)
    if not tactical_reply.get("moved_piece_was_lost_defender"):
        sentences = [
            sentence
            for sentence in sentences
            if not re.search(
                r"\b(?:abandons?|leaves?) (?:the )?(?:defense|defence)\b",
                sentence,
                re.I,
            )
        ]
    else:
        target = tactical_reply.get("target_square")
        reply_move = (tactical_reply.get("move") or {}).get("san")
        has_fully_concrete_sentence = any(
            target
            and target.lower() in sentence.lower()
            and "defend" in sentence.lower()
            and reply_move
            and reply_move.lower() in sentence.lower()
            for sentence in sentences
        )
        if has_fully_concrete_sentence:
            sentences = [
                sentence
                for sentence in sentences
                if not (
                    target
                    and target.lower() in sentence.lower()
                    and "defend" in sentence.lower()
                    and reply_move.lower() not in sentence.lower()
                )
            ]
    routine_opening = (
        (position.get("ply") or 0) <= 4
        and not decision.get("critical_tactical_position")
    )

    if routine_opening:
        rewritten = []
        replaced_engine_praise = False
        for sentence in sentences:
            is_engine_praise = (
                re.search(r"\b(engine|stockfish|evaluation)\b", sentence, re.I)
                and re.search(
                    r"\b(sound|best|support|confirm|recommend)\w*\b",
                    sentence,
                    re.I,
                )
            )
            if is_engine_praise:
                if not replaced_engine_praise:
                    rewritten.append(
                        "At this stage, the useful lesson is the space and "
                        "development created by the move, not a numerical verdict."
                    )
                    replaced_engine_praise = True
                continue
            rewritten.append(sentence)
        sentences = rewritten

    if decision.get("only_move") is not True:
        sentences = [
            re.sub(
                r"\b(?:only|necessary|essential)\s+"
                r"(move|response|defense|continuation)\b",
                r"critical \1",
                sentence,
                flags=re.I,
            )
            for sentence in sentences
        ]
    sentences = [
        re.sub(
            r"\b(?:a\s+)?critical engine-first response\b",
            "the engine's first choice in this sharp position",
            sentence,
            flags=re.I,
        )
        for sentence in sentences
    ]

    additions = []
    classification = (decision.get("move_classification") or {}).get("label")
    if classification in {"inaccuracy", "mistake", "blunder"}:
        for wrong_label in {"inaccuracy", "mistake", "blunder"} - {
            classification
        }:
            sentences = [
                re.sub(
                    rf"\b{wrong_label}\b",
                    classification,
                    sentence,
                    flags=re.I,
                )
                for sentence in sentences
            ]
        if classification == "inaccuracy":
            sentences = [
                re.sub(
                    r"\ba inaccuracy\b",
                    "an inaccuracy",
                    sentence,
                    flags=re.I,
                )
                for sentence in sentences
            ]
        explanation_lower = " ".join(sentences).lower()
    else:
        explanation_lower = " ".join(sentences).lower()
    motifs = position.get("motifs") or []
    fork = next(
        (
            motif
            for motif in motifs
            if motif.get("id") == "fork"
            and (motif.get("extra") or {}).get("includes_check")
        ),
        None,
    )
    if fork:
        best_reply = (
            (
                ((position.get("stockfish") or {}).get("top_lines") or [{}])[0]
                .get("moves_san")
                or []
            )
            or [None]
        )[0]
        material = decision.get("material_after") or {}
        assessment = decision.get("assessment_after") or {}
        material_mismatch = (
            material.get("leader")
            and assessment.get("leader")
            and material.get("leader") != assessment.get("leader")
            and material.get("advantage_pawns")
        )
        needs_reply = best_reply and best_reply.lower() not in explanation_lower
        needs_material = material_mismatch and "material" not in explanation_lower
        if needs_reply or needs_material:
            reply_side = "Black" if position.get("side") == "white" else "White"
            clauses = []
            if needs_reply:
                clauses.append(
                    f"{reply_side}'s best defense is {best_reply}"
                )
                extra_refs.update({"stockfish.top_lines", "decision_context"})
            if needs_material:
                leader = str(material.get("leader")).capitalize()
                clauses.append(
                    f"{leader} remains {material.get('advantage_pawns')} points "
                    f"ahead in material while the engine shows "
                    f"{_assessment_phrase(assessment)}"
                )
                extra_refs.add("decision_context")
            additions.append("; ".join(clauses) + ".")
        extra_refs.add("motifs.fork")

    f_pawn_pressure = next(
        (
            motif
            for motif in motifs
            if motif.get("id") == "f2_f7_weakness"
            and (motif.get("extra") or {}).get("threat_move_san")
            and (motif.get("extra") or {}).get("fork_targets")
        ),
        None,
    )
    if f_pawn_pressure:
        extra = f_pawn_pressure.get("extra") or {}
        threat = extra.get("threat_move_san")
        targets = extra.get("fork_targets") or []
        if (
            threat.lower() not in explanation_lower
            or "fork" not in explanation_lower
        ):
            target_text = " and ".join(
                f"the {target.get('piece')} on {target.get('square')}"
                for target in targets
            )
            additions.append(
                f"The concrete threat is {threat}, which would fork "
                f"{target_text}."
            )
            extra_refs.add("motifs.f2_f7_weakness")

    move_effects = decision.get("move_effects") or {}
    newly_defended = [
        piece
        for piece in (
            move_effects.get("newly_defended_friendly_pieces") or []
        )
        if piece.get("under_enemy_pressure")
    ]
    if newly_defended and classification not in {
        "inaccuracy",
        "mistake",
        "blunder",
    }:
        moved_piece = move_effects.get("moved_piece") or {}
        defended_squares = {
            piece.get("square")
            for piece in newly_defended
            if piece.get("square")
        }
        vulnerable_pattern = "|".join(
            re.escape(square) for square in sorted(defended_squares)
        )
        if vulnerable_pattern:
            sentences = [
                re.sub(
                    rf"\b(?:the\s+)?(?:pawn\s+on\s+)?({vulnerable_pattern})"
                    r"\s+(?:pawn\s+)?(?:is|becomes|remains|looks)?\s*"
                    r"(?:potentially\s+)?vulnerable\b",
                    rf"the \1 pawn is now defended by the "
                    f"{moved_piece.get('piece')} on {moved_piece.get('to')}",
                    sentence,
                    flags=re.I,
                )
                for sentence in sentences
            ]
            explanation_lower = " ".join(sentences).lower()
        missing_defense = [
            piece
            for piece in newly_defended
            if piece.get("square")
            and piece["square"].lower() not in explanation_lower
        ]
        if missing_defense:
            defended = " and ".join(
                f"the {piece.get('piece')} on {piece.get('square')}"
                for piece in missing_defense[:2]
            )
            additions.append(
                f"The move also makes the {moved_piece.get('piece')} on "
                f"{moved_piece.get('to')} a defender of {defended}."
            )
            extra_refs.add("decision_context")

    moved_defender = tactical_reply.get("moved_piece_was_lost_defender")
    reply_move = (tactical_reply.get("move") or {}).get("san")
    if moved_defender:
        target = tactical_reply.get("target_square")
        defenders_before = tactical_reply.get(
            "defenders_before_played_move"
        ) or []
        defenders_after = tactical_reply.get(
            "defenders_after_played_move"
        ) or []
        played_move = (position.get("played_move") or {}).get("san")
        mentions_defensive_mechanism = (
            target
            and target.lower() in explanation_lower
            and "defend" in explanation_lower
        )
        mentions_reply = (
            reply_move
            and reply_move.lower() in explanation_lower
        )
        if not mentions_defensive_mechanism:
            sole = (
                "its only defender"
                if len(defenders_before) == 1 and not defenders_after
                else "a defender"
            )
            consequence = (
                "checkmate"
                if tactical_reply.get("gives_checkmate")
                else "the tactical reply"
            )
            additions.append(
                f"{played_move} moves the {moved_defender.get('piece')} away "
                f"from {moved_defender.get('square')}, so {target} loses "
                f"{sole}; {reply_move} is then {consequence}."
            )
            extra_refs.update({"decision_context", "stockfish.top_lines"})
        elif reply_move and not mentions_reply:
            additions.append(f"Black's concrete reply is {reply_move}.")
            extra_refs.update({"decision_context", "stockfish.top_lines"})

    new_pins = tactical_reply.get("new_absolute_pins") or []
    if new_pins:
        pin = new_pins[0]
        attacked = pin.get("attacked_enemy_pieces_before_pin") or []
        target = attacked[0] if attacked else {}
        pressure = target.get("attacks_friendly_pieces") or []
        mentions_pin = (
            "pin" in explanation_lower
            and pin.get("square", "").lower() in explanation_lower
            and reply_move
            and reply_move.lower() in explanation_lower
        )
        if not mentions_pin:
            sentence = (
                f"{reply_move} pins the {pin.get('piece')} on "
                f"{pin.get('square')} to the king on {pin.get('king')}. "
            )
            if target:
                sentence += (
                    f"That {pin.get('piece')} had been attacking the "
                    f"{target.get('piece')} on {target.get('square')}; once "
                    "pinned, it cannot chase that piece"
                )
                if pressure:
                    pressure_target = next(
                        (
                            piece
                            for piece in pressure
                            if piece.get("piece") in {"queen", "rook"}
                        ),
                        pressure[0],
                    )
                    sentence += (
                        f", which keeps pressure on the "
                        f"{pressure_target.get('piece')} on "
                        f"{pressure_target.get('square')}"
                    )
                sentence += "."
            additions.append(sentence)
            extra_refs.add("decision_context")

    engine_effects = decision.get("engine_choice_effects") or {}
    engine_move = (engine_effects.get("move") or {}).get("san")
    newly_defended_by_engine = [
        piece
        for piece in (
            engine_effects.get("newly_defended_friendly_pieces") or []
        )
        if piece.get("under_enemy_pressure")
        and piece.get("piece") in {"queen", "rook", "bishop", "knight"}
    ]
    should_explain_engine_choice = bool(
        engine_move
        and newly_defended_by_engine
        and (
            moved_defender
            or new_pins
            or classification in {"mistake", "blunder"}
        )
    )
    if (
        should_explain_engine_choice
        and engine_move.lower() not in explanation_lower
    ):
        defended = newly_defended_by_engine[0]
        defender = (defended.get("new_defenders") or [{}])[0]
        clauses = []
        moved_piece = engine_effects.get("moved_piece") or {}
        if engine_effects.get("develops_minor_piece"):
            clauses.append(
                f"develops the {moved_piece.get('piece')} from "
                f"{moved_piece.get('from')}"
            )
        clauses.append(
            f"makes the {defender.get('piece')} on "
            f"{defender.get('square')} a defender of the "
            f"{defended.get('piece')} on {defended.get('square')}"
        )
        additions.append(
            f"By contrast, {engine_move} " + " and ".join(clauses) + "."
        )
        extra_refs.add("decision_context")

    if decision.get("move_quality") == "allows_forced_mate":
        engine_choice = (decision.get("engine_first_choice") or {}).get("san")
        before = decision.get("assessment_before") or {}
        combined_lower = (
            explanation_lower + " " + " ".join(additions).lower()
        )
        missing_contrast = (
            "not a forced mate" not in combined_lower
            and "not previously a forced mate" not in combined_lower
        ) or (
            engine_choice
            and engine_choice.lower() not in combined_lower
        )
        if missing_contrast:
            engine_clause = (
                f"; {engine_choice} was the engine's best defense"
                if engine_choice
                and engine_choice.lower() not in combined_lower
                else ""
            )
            additions.append(
                f"Before this move the position was "
                f"{_assessment_phrase(before)}, not a forced mate"
                f"{engine_clause}."
            )
            extra_refs.add("decision_context")

        forced_mate = next(
            (motif for motif in motifs if motif.get("id") == "forced_mate"),
            None,
        )
        if forced_mate:
            extra = forced_mate.get("extra") or {}
            safe_count = extra.get("safe_adjacent_square_count")
            mentions_confinement = (
                "safe adjacent" in explanation_lower
                or "escape square" in explanation_lower
                or "no escape" in explanation_lower
            )
            direct_mate_mechanism = bool(
                moved_defender and tactical_reply.get("gives_checkmate")
            )
            if (
                safe_count is not None
                and not mentions_confinement
                and not direct_mate_mechanism
            ):
                statuses = extra.get("adjacent_square_status") or {}
                occupied = [
                    square
                    for square, status in statuses.items()
                    if status.get("status") == "friendly_occupied"
                ]
                attacked = [
                    square
                    for square, status in statuses.items()
                    if status.get("status") == "attacked"
                ]
                details = []
                if occupied:
                    details.append(
                        f"{'/'.join(occupied)} are occupied by friendly pieces"
                    )
                if attacked:
                    details.append(f"{'/'.join(attacked)} are controlled")
                suffix = f" ({'; '.join(details)})" if details else ""
                additions.append(
                    f"The king on {extra.get('defending_king_square')} has "
                    f"{safe_count} immediately safe adjacent squares{suffix}, "
                    "which makes the checking sequence forcing."
                )
                extra_refs.add("motifs.forced_mate")

            mate_line = extra.get("mate_line_san") or []
            already_added_reply = bool(
                reply_move
                and reply_move.lower()
                in " ".join(additions).lower()
            )
            if (
                mate_line
                and mate_line[0].lower() not in explanation_lower
                and not already_added_reply
            ):
                additions.append(
                    "The concrete mating line is " + " ".join(mate_line) + "."
                )
                extra_refs.update({"motifs.forced_mate", "stockfish.top_lines"})

    after_assessment = decision.get("assessment_after") or {}
    if after_assessment.get("classification") in {"roughly_equal", "slight_edge"}:
        accurate_phrase = (
            "a roughly equal position"
            if after_assessment.get("classification") == "roughly_equal"
            else "only a slight edge"
        )
        sentences = [
            re.sub(
                r"\b(?:a\s+)?(?:clear|decisive|overwhelming|significant|"
                r"substantial)\s+advantage"
                r"(?:\s+for\s+(?:white|black))?|\b(?:completely\s+)?winning\b",
                accurate_phrase,
                sentence,
                flags=re.I,
            )
            for sentence in sentences
        ]

    additions_words = _word_count(" ".join(additions))
    available_for_model = max(0, MAX_EXPLANATION_WORDS - additions_words)
    while len(sentences) > 1 and _word_count(" ".join(sentences)) > available_for_model:
        sentences.pop()
    if sentences and _word_count(" ".join(sentences)) > available_for_model:
        trimmed = _trim_to_word_limit(
            " ".join(sentences),
            available_for_model,
        )
        sentences = [trimmed] if trimmed else []
    sentences.extend(additions)
    return " ".join(sentences), extra_refs


def _response_json_schema(analysis: dict[str, Any]) -> dict[str, Any]:
    positions = analysis.get("positions") or []
    position_count = len(positions)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["explanations"],
        "properties": {
            "explanations": {
                "type": "array",
                "minItems": position_count,
                "maxItems": position_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "ply",
                        "move",
                        "side",
                        "explanation",
                        "lesson",
                        "evidence_refs",
                    ],
                    "properties": {
                        "ply": {"type": "integer"},
                        "move": {"type": "string"},
                        "side": {
                            "type": "string",
                            "enum": ["white", "black"],
                        },
                        "explanation": {"type": "string"},
                        "lesson": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                    },
                },
            }
        },
    }


def _validate_explanation_content(
    explanation: str,
    lesson: str,
    position: dict[str, Any],
) -> None:
    lower = explanation.lower()
    decision = position.get("decision_context") or {}

    if re.search(
        r"\b(?:centipawn|modeled winning-chance|win probability|"
        r"percentage points? of (?:win|winning))\b",
        lower,
    ):
        raise AIResponseError(
            "Coaching included engine-classification math instead of a board explanation."
        )

    reply = _select_tactical_reply(decision)
    reply_san = str((reply.get("move") or {}).get("san") or "")
    reply_lower = reply_san.lower()
    moved_defender = reply.get("moved_piece_was_lost_defender")
    if moved_defender:
        target = str(reply.get("target_square") or "")
        discusses_defensive_duty = bool(
            target
            and target.lower() in lower
            and re.search(
                r"\b(?:defend|guard|protect|abandon)\w*\b",
                lower,
            )
        )
        if (
            discusses_defensive_duty
            and reply_lower
            and reply_lower not in lower
        ):
            raise AIResponseError(
                "Coaching described a lost defensive duty without connecting "
                "the resulting opponent reply."
            )

    for pin in (reply.get("new_absolute_pins") or [])[:2]:
        pinned_square = str(pin.get("square") or "")
        pin_pattern = r"\bpin(?:s|ned|ning)?\b"
        for sentence in _split_sentences(explanation):
            sentence_lower = sentence.lower()
            if (
                re.search(pin_pattern, sentence_lower)
                and pinned_square.lower() in sentence_lower
                and (
                    not reply_lower
                    or reply_lower not in sentence_lower
                )
            ):
                raise AIResponseError(
                    f"At ply {position.get('ply')}, the pin on "
                    f"{pinned_square} exists only after {reply_san}. The played "
                    f"move {(position.get('played_move') or {}).get('san')} "
                    f"allows {reply_san}; it does not itself create the pin."
                )

    focus_types = {
        item.get("type")
        for item in _coaching_focus(position)
        if isinstance(item, dict)
    }
    tactical_focus = [
        item
        for item in _coaching_focus(position)
        if item.get("type")
        in {
            "defensive_duty_lost_after_played_move",
            "absolute_pin_created_by_opponent_reply",
        }
    ]
    if tactical_focus:
        focus_covered = False
        for item in tactical_focus:
            if item.get("type") == "defensive_duty_lost_after_played_move":
                target = str(item.get("defended_square") or "").lower()
                reply_move = str(
                    (item.get("opponent_reply") or {}).get("san") or ""
                ).lower()
                focus_covered = bool(
                    target
                    and target in lower
                    and reply_move
                    and reply_move in lower
                    and re.search(
                        r"\b(?:defend|guard|protect|abandon)\w*\b",
                        lower,
                    )
                )
            elif item.get("type") == "absolute_pin_created_by_opponent_reply":
                pinned_square = str(
                    (item.get("pinned_piece") or {}).get("square") or ""
                ).lower()
                reply_move = str(
                    (item.get("opponent_reply") or {}).get("san") or ""
                ).lower()
                focus_covered = bool(
                    pinned_square
                    and pinned_square in lower
                    and reply_move
                    and reply_move in lower
                    and re.search(r"\bpin(?:s|ned|ning)?\b", lower)
                )
            if focus_covered:
                break
        if not focus_covered:
            raise AIResponseError(
                f"At ply {position.get('ply')}, coaching stayed generic despite "
                "structured tactical focus. Use at least one supplied focus fact "
                "with its pieces, squares, and timing."
            )

    if focus_types.intersection(
        {
            "defensive_duty_lost_after_played_move",
            "absolute_pin_created_by_opponent_reply",
        }
    ) and re.search(
        r"\b(?:always be aware of tactics?|watch for tactics?|be careful|"
        r"double-check your moves? for tactical|winning material is good|"
        r"develop your pieces)\b",
        lesson,
        re.I,
    ):
        raise AIResponseError(
            "The practical lesson was generic despite concrete tactical evidence "
            f"at ply {position.get('ply')}."
        )


def validate_explanations(
    payload: Any,
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AIResponseError("Gemini response must be a JSON object.")
    explanations = payload.get("explanations")
    positions = analysis.get("positions")
    if not isinstance(explanations, list) or not isinstance(positions, list):
        raise AIResponseError("Gemini response is missing explanations.")
    if len(explanations) != len(positions):
        raise AIResponseError(
            "Gemini returned the wrong number of coaching explanations."
        )

    validated: list[dict[str, Any]] = []
    for index, (expected, item) in enumerate(zip(positions, explanations)):
        if not isinstance(item, dict):
            raise AIResponseError("Each coaching explanation must be an object.")

        expected_move = (expected.get("played_move") or {}).get("san")
        if item.get("ply") != expected.get("ply"):
            raise AIResponseError("Gemini returned a misaligned ply.")
        if item.get("move") != expected_move:
            raise AIResponseError("Gemini returned a move not found in the analysis.")
        if item.get("side") != expected.get("side"):
            raise AIResponseError("Gemini returned a misaligned acting side.")

        explanation = item.get("explanation")
        lesson = item.get("lesson")
        refs = item.get("evidence_refs")
        if not isinstance(explanation, str) or len(explanation.strip()) < 120:
            raise AIResponseError("A coaching explanation was missing or too short.")
        explanation = explanation.strip()
        if _word_count(explanation) > MAX_EXPLANATION_WORDS:
            raise AIResponseError(
                "A coaching explanation exceeded the readability limit at "
                f"ply {expected.get('ply')}."
            )
        if not isinstance(lesson, str) or not lesson.strip():
            raise AIResponseError("A coaching lesson was missing.")
        lesson = lesson.strip()
        _validate_explanation_content(explanation, lesson, expected)
        if not isinstance(refs, list) or not refs:
            raise AIResponseError("A coaching explanation did not cite its evidence.")

        previous_position = (
            positions[index - 1]
            if index > 0
            else {
                "ply": 0,
                "stockfish": analysis.get("initial_stockfish") or {},
            }
        )
        next_position = (
            positions[index + 1]
            if index + 1 < len(positions)
            else None
        )
        allowed = _allowed_refs(
            expected,
            previous_position=previous_position,
            next_position=next_position,
        )
        normalized_refs: list[str] = []
        for ref in refs:
            if (
                isinstance(ref, str)
                and ref in allowed
                and ref not in normalized_refs
            ):
                normalized_refs.append(ref)
        if not normalized_refs:
            normalized_refs.append(
                "decision_context"
                if "decision_context" in allowed
                else "stockfish.evaluation"
            )

        validated.append(
            {
                "ply": expected["ply"],
                "move": expected_move,
                "side": expected["side"],
                "explanation": explanation,
                "lesson": lesson,
                "evidence_refs": normalized_refs,
            }
        )
    return validated


def build_explanation_cache_key(
    analysis: dict[str, Any],
    perspective: str,
) -> str:
    value = {
        "analysis_id": analysis.get("analysis_id"),
        "positions": analysis.get("positions"),
        "perspective": perspective,
        "prompt_version": PROMPT_VERSION,
        "model": _model_name(),
    }
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_explanations(
    analysis: dict[str, Any],
    perspective: str,
) -> dict[str, Any]:
    if perspective not in VALID_PERSPECTIVES:
        raise AIResponseError("Invalid coaching perspective.")
    positions = analysis.get("positions")
    if not isinstance(positions, list) or not positions:
        raise AIResponseError("The analysis package has no positions to explain.")

    key = _api_key()
    if not key:
        raise AIConfigurationError(
            "Gemini is not configured. Add GEMINI_API_KEY and retry."
        )

    genai = _load_genai()
    from google.genai import types as genai_types

    client = genai.Client(api_key=key)
    base_prompt = _build_prompt(analysis, perspective)
    last_provider_error: Exception | None = None
    last_response_error: AIResponseError | None = None
    attempts = _provider_attempts()
    for attempt in range(attempts):
        prompt = base_prompt
        if last_response_error is not None:
            error_text = str(last_response_error)
            if "coaching stayed generic" in error_text:
                supplement = (
                    "For every position that has a TACTICAL BRIEFING entry above,"
                    " you must include the specific pieces, squares, reply move,"
                    " and timing stated there. Do not summarise them in general"
                    " terms — name the exact squares and moves."
                )
            elif "exists only after" in error_text:
                supplement = (
                    "Timing is strict: the played move produces"
                    " position_after_played_move; an opponent reply then produces"
                    " position_after_opponent_reply. A pin, fork, or mate that"
                    " appears only in position_after_opponent_reply must be"
                    " attributed to that reply, not to the played move. Say the"
                    " played move 'allows' or 'permits' the reply; attribute the"
                    " resulting tactic to the reply itself."
                )
            else:
                supplement = "Correct the factual or chronological problem."
            prompt += (
                "\n\nThe previous response failed validation for this reason: "
                f"{error_text} Regenerate the entire JSON response. "
                f"{supplement} Do not mention this validation message."
            )
        try:
            response = client.models.generate_content(
                model=_model_name(),
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=_response_json_schema(analysis),
                    max_output_tokens=8192,
                    temperature=0.2,
                    thinking_config=genai_types.ThinkingConfig(
                        thinking_level=genai_types.ThinkingLevel.LOW,
                    ),
                ),
            )
        except AIConfigurationError:
            raise
        except Exception as exc:
            last_provider_error = exc
            if (
                attempt + 1 >= attempts
                or not _is_transient_provider_error(exc)
            ):
                break
            time.sleep(1.0 * (attempt + 1))
            continue

        try:
            text = _extract_json_text(response)
            payload = json.loads(text)
            explanations = validate_explanations(payload, analysis)
        except json.JSONDecodeError as exc:
            last_response_error = AIResponseError(
                "Gemini returned malformed coaching data."
            )
            if attempt + 1 >= attempts:
                raise AIResponseError(
                    "Gemini returned malformed coaching data. Please retry."
                ) from exc
            continue
        except AIResponseError as exc:
            last_response_error = exc
            if attempt + 1 >= attempts:
                raise
            continue

        return {
            "analysis_id": analysis.get("analysis_id"),
            "perspective": perspective,
            "model": _model_name(),
            "prompt_version": PROMPT_VERSION,
            "explanations": explanations,
        }

    if last_provider_error is not None:
        raise AIProviderError(
            f"{_safe_provider_error(last_provider_error)} "
            "Your analysis is preserved; please retry."
        ) from last_provider_error
    if last_response_error is not None:
        raise last_response_error
    raise AIProviderError("Gemini could not generate coaching.")


def _safe_provider_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "api key" in text or "unauthenticated" in text or "permission" in text:
        return "Gemini rejected the configured API key."
    if "quota" in text or "resource_exhausted" in text or "429" in text:
        return "Gemini quota or rate limits were exceeded."
    if "model" in text and ("not found" in text or "404" in text):
        return f"Gemini model {_model_name()} is unavailable for this project."
    if "503" in text or "high demand" in text or "unavailable" in text:
        return "Gemini is temporarily overloaded."
    if "invalid_argument" in text or "invalid argument" in text or "400" in text:
        return "Gemini rejected the structured coaching request."
    return "Gemini could not generate coaching."
