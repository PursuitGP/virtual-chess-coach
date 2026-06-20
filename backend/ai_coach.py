"""Gemini-backed synthesis and strict response validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any


PROMPT_VERSION = "2026-06-20.4"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
VALID_PERSPECTIVES = {"white", "black", "both"}


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


def _context_summary(position: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(position, dict):
        return None
    stockfish = position.get("stockfish") or {}
    return {
        "ply": position.get("ply"),
        "side": position.get("side"),
        "played_move": position.get("played_move"),
        "fen": position.get("fen"),
        "stockfish": {
            "evaluation": stockfish.get("evaluation"),
            "eval_delta_cp": stockfish.get("eval_delta_cp"),
            "mover_loss_cp": stockfish.get("mover_loss_cp"),
        },
        "decision_context": position.get("decision_context"),
        "motifs": position.get("motifs") or [],
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

    points.append(
        "Describe what the played move concretely changes on this board."
    )
    if decision.get("move_quality") == "allows_forced_mate":
        points.extend(
            [
                (
                    "State that before this move the position was "
                    f"{before.get('classification')} for "
                    f"{before.get('leader') or 'neither side'}, not a forced mate."
                ),
                (
                    f"Name {engine_choice.get('san')} as the engine's first "
                    "defensive choice instead of the played move."
                ),
                (
                    "State that the played move changes the evaluation to "
                    f"forced mate for {after.get('leader')}."
                ),
            ]
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
            points.append(
                f"Explain that the king on {king_square} has {safe_count} "
                "immediately safe adjacent squares and connect that confinement "
                "to the mating attack."
            )
            if line:
                points.append(
                    "Use the supplied mating line: " + " ".join(line) + "."
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
    return points[:6]


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
                "stockfish": position.get("stockfish"),
                "decision_context": position.get("decision_context"),
                "lichess": position.get("lichess"),
                "motifs": position.get("motifs"),
                "motifs_available": position.get("motifs_available"),
                "sequence_context": {
                    "previous_position": _context_summary(previous_position),
                    "next_position": _context_summary(next_position),
                },
                "required_coaching_points": _required_coaching_points(position),
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


def _build_prompt(analysis: dict[str, Any], perspective: str) -> str:
    evidence = _condense_analysis(analysis)
    perspective_instruction = {
        "white": "Coach from White's perspective at every ply.",
        "black": "Coach from Black's perspective at every ply.",
        "both": "Explain what each played move means for both players, emphasizing the side that just moved.",
    }[perspective]

    return f"""
You are the synthesis layer in an evidence-grounded chess coaching system.
{perspective_instruction}

The evidence package was produced by Stockfish, Lichess Opening Explorer, and
custom chess motif detectors. Chess claims must be grounded in that package.
Do not independently reconstruct the game or invent analysis.

Rules:
1. Return JSON only, with this shape:
   {{"explanations": [{{
     "ply": 1,
     "move": "e4",
     "side": "white",
     "explanation": "Position-specific coaching in 4-6 complete sentences.",
     "lesson": "One concise practical lesson.",
     "evidence_refs": ["stockfish.evaluation", "lichess.players.played_move"]
   }}]}}
2. Return exactly one object for every supplied position, in the same order.
3. Copy ply, move, and side exactly from the evidence package.
4. Write exactly 4-6 complete sentences in explanation. Make them earn their
   space: explain what the move changed, the concrete target or motif, the
   opponent's practical problem, and why the engine/context supports the
   conclusion. Do not pad the answer with generic opening principles.
   Every item in required_coaching_points is mandatory. Combine related items
   into one sentence when needed, but do not omit one.
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
13. Never say "only move" unless decision_context.only_move is true. When it is
    null, use "engine's first choice" or "critical response" only if
    critical_engine_response is true. Avoid empty superlatives such as "most
    forcing" when the evidence supplies no comparison.
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
18. Explain evaluation changes naturally, but numeric values may be used when
   they improve clarity.
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
28. Use opening_context only when a project-curated description is present.
    Do not browse the internet or invent historical opening background.

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
    opening_context = lichess.get("opening_context") or {}
    if opening_context.get("description"):
        refs.add("lichess.opening_context")
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
    if previous_position:
        refs.add("context.previous_position")
    if next_position:
        refs.add("context.next_position")
    return refs


def _sentence_count(text: str) -> int:
    return len(_split_sentences(text))


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


def _ground_explanation(
    explanation: str,
    position: dict[str, Any],
) -> tuple[str, set[str]]:
    sentences = _split_sentences(explanation)
    extra_refs: set[str] = set()
    decision = position.get("decision_context") or {}
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

    if decision.get("move_quality") == "allows_forced_mate":
        engine_choice = (decision.get("engine_first_choice") or {}).get("san")
        before = decision.get("assessment_before") or {}
        missing_contrast = (
            "not a forced mate" not in explanation_lower
            or (
                engine_choice
                and engine_choice.lower() not in explanation_lower
            )
        )
        if missing_contrast:
            additions.append(
                f"Before this move the position was "
                f"{_assessment_phrase(before)}, not a forced mate; "
                f"{engine_choice} was the engine's best defense."
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
            if safe_count is not None and not mentions_confinement:
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
            if mate_line and mate_line[0].lower() not in explanation_lower:
                additions.append(
                    "The concrete mating line is " + " ".join(mate_line) + "."
                )
                extra_refs.update({"motifs.forced_mate", "stockfish.top_lines"})

    while additions and len(sentences) + len(additions) > 6:
        sentences.pop()
    sentences.extend(additions)
    return " ".join(sentences), extra_refs


def _response_json_schema(analysis: dict[str, Any]) -> dict[str, Any]:
    positions = analysis.get("positions") or []
    item_schemas = []
    for index, position in enumerate(positions):
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
        allowed_refs = sorted(
            _allowed_refs(
                position,
                previous_position=previous_position,
                next_position=next_position,
            )
        )
        item_schemas.append(
            {
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
                    "ply": {
                        "type": "integer",
                        "enum": [position.get("ply")],
                    },
                    "move": {
                        "type": "string",
                        "enum": [
                            (position.get("played_move") or {}).get("san")
                        ],
                    },
                    "side": {
                        "type": "string",
                        "enum": [position.get("side")],
                    },
                    "explanation": {"type": "string"},
                    "lesson": {"type": "string"},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                            "type": "string",
                            "enum": allowed_refs,
                        },
                    },
                },
            }
        )

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
                "prefixItems": item_schemas,
            }
        },
    }


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
        explanation, grounded_refs = _ground_explanation(
            explanation.strip(),
            expected,
        )
        sentence_count = _sentence_count(explanation)
        if sentence_count < 4 or sentence_count > 6:
            raise AIResponseError(
                "A coaching explanation must contain 4 to 6 complete sentences."
            )
        if not isinstance(lesson, str) or not lesson.strip():
            raise AIResponseError("A coaching lesson was missing.")
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
            if not isinstance(ref, str) or ref not in allowed:
                raise AIResponseError(
                    f"Gemini cited unavailable evidence for ply {expected.get('ply')}."
                )
            if ref not in normalized_refs:
                normalized_refs.append(ref)
        for ref in sorted(grounded_refs):
            if ref in allowed and ref not in normalized_refs:
                normalized_refs.append(ref)

        validated.append(
            {
                "ply": expected["ply"],
                "move": expected_move,
                "side": expected["side"],
                "explanation": explanation,
                "lesson": lesson.strip(),
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

    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=_model_name(),
            contents=_build_prompt(analysis, perspective),
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=_response_json_schema(analysis),
                max_output_tokens=8192,
                temperature=0.2,
                thinking_config=genai_types.ThinkingConfig(
                    thinking_level=genai_types.ThinkingLevel.MINIMAL,
                ),
            ),
        )
    except AIConfigurationError:
        raise
    except Exception as exc:
        raise AIProviderError(
            f"{_safe_provider_error(exc)} Your analysis is preserved; please retry."
        ) from exc

    text = _extract_json_text(response)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIResponseError(
            "Gemini returned malformed coaching data. Please retry."
        ) from exc

    explanations = validate_explanations(payload, analysis)
    return {
        "analysis_id": analysis.get("analysis_id"),
        "perspective": perspective,
        "model": _model_name(),
        "prompt_version": PROMPT_VERSION,
        "explanations": explanations,
    }


def _safe_provider_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "api key" in text or "unauthenticated" in text or "permission" in text:
        return "Gemini rejected the configured API key."
    if "quota" in text or "resource_exhausted" in text or "429" in text:
        return "Gemini quota or rate limits were exceeded."
    if "model" in text and ("not found" in text or "404" in text):
        return f"Gemini model {_model_name()} is unavailable for this project."
    return "Gemini could not generate coaching."
