"""Versioned, repository-native chess study context.

The study database is optional coaching context. It never overrides Stockfish,
motif evidence, or the moves contained in the submitted game.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import chess


DEFAULT_STUDY_DATABASE_PATH = (
    Path(__file__).resolve().parent / "data" / "studies.json"
)


class StudyDatabaseError(ValueError):
    pass


def _database_path() -> Path:
    configured = os.getenv("STUDY_DATABASE_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_STUDY_DATABASE_PATH


def _normalized_epd(fen_or_epd: str | None) -> str | None:
    if not isinstance(fen_or_epd, str) or not fen_or_epd.strip():
        return None
    try:
        return chess.Board(fen_or_epd).epd()
    except ValueError:
        fields = fen_or_epd.split()
        if len(fields) == 4:
            try:
                return chess.Board(f"{fen_or_epd} 0 1").epd()
            except ValueError:
                return None
        return None


def _validate_text_list(value: Any, field: str, entry_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise StudyDatabaseError(
            f"Study entry {entry_id!r} has an invalid {field!r} list."
        )
    return [item.strip() for item in value]


def validate_study_database(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StudyDatabaseError("The study database must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise StudyDatabaseError("The study database schema_version must be 1.")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise StudyDatabaseError("The study database must contain an entries list.")

    validated_entries = []
    seen_ids = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise StudyDatabaseError("Every study entry must be a JSON object.")
        entry_id = raw_entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise StudyDatabaseError("Every study entry requires a non-empty id.")
        entry_id = entry_id.strip()
        if entry_id in seen_ids:
            raise StudyDatabaseError(f"Duplicate study entry id: {entry_id}.")
        seen_ids.add(entry_id)

        match = raw_entry.get("match")
        if not isinstance(match, dict):
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} requires a match object."
            )
        supported_match = {
            "before_epd",
            "after_epd",
            "move_uci",
            "opening_name",
            "opening_name_prefix",
        }
        if not any(match.get(key) for key in supported_match):
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} has no supported match criterion."
            )
        unknown_match = set(match) - supported_match
        if unknown_match:
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} has unknown match fields: "
                f"{', '.join(sorted(unknown_match))}."
            )

        normalized_match = dict(match)
        for field in ("before_epd", "after_epd"):
            if field in normalized_match:
                normalized = _normalized_epd(normalized_match[field])
                if not normalized:
                    raise StudyDatabaseError(
                        f"Study entry {entry_id!r} has an invalid {field}."
                    )
                normalized_match[field] = normalized
        move_uci = normalized_match.get("move_uci")
        if move_uci:
            try:
                chess.Move.from_uci(move_uci)
            except ValueError as exc:
                raise StudyDatabaseError(
                    f"Study entry {entry_id!r} has an invalid move_uci."
                ) from exc

        title = raw_entry.get("title")
        summary = raw_entry.get("summary")
        if not isinstance(title, str) or not title.strip():
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} requires a title."
            )
        if not isinstance(summary, str) or not summary.strip():
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} requires a summary."
            )

        source = raw_entry.get("source") or {}
        if not isinstance(source, dict):
            raise StudyDatabaseError(
                f"Study entry {entry_id!r} has an invalid source object."
            )

        validated_entries.append(
            {
                "id": entry_id,
                "match": normalized_match,
                "title": title.strip(),
                "summary": summary.strip(),
                "ideas": _validate_text_list(
                    raw_entry.get("ideas"), "ideas", entry_id
                ),
                "common_mistakes": _validate_text_list(
                    raw_entry.get("common_mistakes"),
                    "common_mistakes",
                    entry_id,
                ),
                "source": source,
            }
        )

    return {
        "schema_version": 1,
        "name": str(payload.get("name") or "Project study database"),
        "entries": validated_entries,
    }


@lru_cache(maxsize=4)
def load_study_database(path: str | None = None) -> dict[str, Any]:
    database_path = Path(path) if path else _database_path()
    try:
        payload = json.loads(database_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StudyDatabaseError(
            f"Study database could not be read: {database_path}."
        ) from exc
    except json.JSONDecodeError as exc:
        raise StudyDatabaseError(
            f"Study database contains invalid JSON: {database_path}."
        ) from exc
    return validate_study_database(payload)


def study_database_status() -> dict[str, Any]:
    path = _database_path()
    try:
        database = load_study_database(str(path))
        return {
            "available": True,
            "schema_version": database["schema_version"],
            "entries": len(database["entries"]),
            "path": str(path),
            "error": None,
        }
    except StudyDatabaseError as exc:
        return {
            "available": False,
            "schema_version": None,
            "entries": 0,
            "path": str(path),
            "error": str(exc),
        }


def _entry_matches(
    entry: dict[str, Any],
    *,
    opening_name: str | None,
    before_epd: str | None,
    after_epd: str | None,
    move_uci: str | None,
) -> bool:
    match = entry["match"]
    comparisons = {
        "before_epd": before_epd,
        "after_epd": after_epd,
        "move_uci": move_uci,
        "opening_name": opening_name,
    }
    for field, actual in comparisons.items():
        expected = match.get(field)
        if expected is not None and expected != actual:
            return False
    prefix = match.get("opening_name_prefix")
    if prefix is not None and (
        not opening_name
        or not (
            opening_name == prefix
            or opening_name.startswith(f"{prefix}:")
        )
    ):
        return False
    return True


def _specificity(entry: dict[str, Any]) -> tuple[int, int]:
    match = entry["match"]
    position_fields = sum(
        bool(match.get(field))
        for field in ("before_epd", "after_epd", "move_uci")
    )
    opening_fields = sum(
        bool(match.get(field))
        for field in ("opening_name", "opening_name_prefix")
    )
    return position_fields, opening_fields


def context_for_position(
    *,
    opening: dict[str, Any] | None,
    previous_fen: str | None,
    fen: str | None,
    move_uci: str | None,
) -> dict[str, Any] | None:
    database = load_study_database()
    opening_name = (
        opening.get("name")
        if isinstance(opening, dict) and isinstance(opening.get("name"), str)
        else None
    )
    before_epd = _normalized_epd(previous_fen)
    after_epd = _normalized_epd(fen)
    matches = [
        entry
        for entry in database["entries"]
        if _entry_matches(
            entry,
            opening_name=opening_name,
            before_epd=before_epd,
            after_epd=after_epd,
            move_uci=move_uci,
        )
    ]
    if not matches:
        return None

    selected = max(matches, key=_specificity)
    return {
        "id": selected["id"],
        "title": selected["title"],
        "summary": selected["summary"],
        "ideas": selected["ideas"],
        "common_mistakes": selected["common_mistakes"],
        "source": selected["source"],
        "match_specificity": {
            "position_fields": _specificity(selected)[0],
            "opening_fields": _specificity(selected)[1],
        },
    }
