"""Gemini-backed synthesis and strict response validation."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


PROMPT_VERSION = "2026-06-19.1"
DEFAULT_MODEL = "gemini-3.5-flash"
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
        "available": configured and sdk_available,
        "model": _model_name(),
    }


def _condense_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    positions = []
    for position in analysis.get("positions", []):
        positions.append(
            {
                "ply": position.get("ply"),
                "fullmove_number": position.get("fullmove_number"),
                "side": position.get("side"),
                "played_move": position.get("played_move"),
                "fen": position.get("fen"),
                "stockfish": position.get("stockfish"),
                "lichess": position.get("lichess"),
                "motifs": position.get("motifs"),
                "motifs_available": position.get("motifs_available"),
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
     "explanation": "Position-specific coaching in 3-6 sentences.",
     "lesson": "One concise practical lesson.",
     "evidence_refs": ["stockfish.evaluation", "lichess.players.played_move"]
   }}]}}
2. Return exactly one object for every supplied position, in the same order.
3. Copy ply, move, and side exactly from the evidence package.
4. Never invent moves, variations, probabilities, opening names, evaluations,
   or tactical claims.
5. Mention a variation only when it appears in stockfish.pv.
6. Treat motif findings as heuristic context, not infallible truth.
7. Distinguish engine-backed conclusions from coaching interpretation.
8. Explain evaluation changes naturally, but numeric values may be used when
   they improve clarity.
9. Avoid generic advice that is not tied to this position.
10. Every evidence_refs item must identify evidence actually used. Allowed
    forms are stockfish.*, lichess.*, or motifs.<motif id>.
11. If Lichess or motif evidence is unavailable, rely on the available
    Stockfish evidence and say nothing about the missing source.

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


def _allowed_refs(position: dict[str, Any]) -> set[str]:
    refs = {"stockfish.evaluation"}
    stockfish = position.get("stockfish") or {}
    if stockfish.get("eval_delta_cp") is not None:
        refs.add("stockfish.eval_delta")
    if stockfish.get("best_move"):
        refs.add("stockfish.best_move")
    if stockfish.get("pv"):
        refs.add("stockfish.pv")

    lichess = position.get("lichess") or {}
    if lichess.get("opening"):
        refs.add("lichess.opening")
    if lichess.get("theory_status"):
        refs.add("lichess.theory_status")
    for database in ("masters", "players"):
        evidence = lichess.get(database) or {}
        if evidence.get("played_move"):
            refs.add(f"lichess.{database}.played_move")
        if evidence.get("continuations"):
            refs.add(f"lichess.{database}.continuations")

    for motif in position.get("motifs") or []:
        if isinstance(motif, dict) and motif.get("id"):
            refs.add(f"motifs.{motif['id']}")
    return refs


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
    for expected, item in zip(positions, explanations):
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
        if not isinstance(explanation, str) or len(explanation.strip()) < 40:
            raise AIResponseError("A coaching explanation was missing or too short.")
        if not isinstance(lesson, str) or not lesson.strip():
            raise AIResponseError("A coaching lesson was missing.")
        if not isinstance(refs, list) or not refs:
            raise AIResponseError("A coaching explanation did not cite its evidence.")

        allowed = _allowed_refs(expected)
        normalized_refs: list[str] = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in allowed:
                raise AIResponseError(
                    f"Gemini cited unavailable evidence for ply {expected.get('ply')}."
                )
            if ref not in normalized_refs:
                normalized_refs.append(ref)

        validated.append(
            {
                "ply": expected["ply"],
                "move": expected_move,
                "side": expected["side"],
                "explanation": explanation.strip(),
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
    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=_model_name(),
            contents=_build_prompt(analysis, perspective),
            config={"response_mime_type": "application/json"},
        )
    except AIConfigurationError:
        raise
    except Exception as exc:
        raise AIProviderError(
            "Gemini could not generate coaching. Your analysis is preserved; please retry."
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
