from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from backend.study_database import (
    StudyDatabaseError,
    context_for_position,
    load_study_database,
    validate_study_database,
)


class StudyDatabaseTests(unittest.TestCase):
    def tearDown(self):
        load_study_database.cache_clear()

    def test_exact_opening_entry_wins_over_family_entry(self):
        context = context_for_position(
            opening={
                "name": "Italian Game: Two Knights Defense, Knight Attack"
            },
            previous_fen=chess.Board().fen(),
            fen=chess.Board().fen(),
            move_uci="e2e4",
        )
        self.assertEqual(
            context["id"],
            "italian-two-knights-knight-attack",
        )
        self.assertGreater(context["match_specificity"]["opening_fields"], 0)

    def test_position_and_move_entry_wins_over_opening_family(self):
        board = chess.Board()
        after = board.copy()
        after.push_uci("e2e4")
        payload = {
            "schema_version": 1,
            "entries": [
                {
                    "id": "family",
                    "match": {"opening_name_prefix": "King's Pawn Game"},
                    "title": "Family",
                    "summary": "Broad context.",
                },
                {
                    "id": "position",
                    "match": {
                        "before_epd": board.epd(),
                        "move_uci": "e2e4",
                    },
                    "title": "Position",
                    "summary": "Exact context.",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "studies.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(
                os.environ,
                {"STUDY_DATABASE_PATH": str(path)},
            ):
                load_study_database.cache_clear()
                context = context_for_position(
                    opening={"name": "King's Pawn Game"},
                    previous_fen=board.fen(),
                    fen=after.fen(),
                    move_uci="e2e4",
                )
        self.assertEqual(context["id"], "position")
        self.assertEqual(context["match_specificity"]["position_fields"], 2)

    def test_rejects_invalid_database(self):
        with self.assertRaises(StudyDatabaseError):
            validate_study_database(
                {
                    "schema_version": 1,
                    "entries": [
                        {
                            "id": "bad",
                            "match": {"before_epd": "not a position"},
                            "title": "Bad",
                            "summary": "Bad data.",
                        }
                    ],
                }
            )
