from __future__ import annotations

import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from backend.ai_coach import (
    AIConfigurationError,
    AIResponseError,
    build_explanation_cache_key,
    generate_explanations,
    validate_explanations,
)


def sample_analysis():
    return {
        "analysis_id": "analysis-1",
        "positions": [
            {
                "ply": 1,
                "side": "white",
                "played_move": {"san": "e4", "uci": "e2e4"},
                "stockfish": {
                    "evaluation": {"type": "cp", "value": 20},
                    "eval_delta_cp": None,
                    "best_move": "e2e4",
                    "pv": ["e2e4"],
                },
                "lichess": {
                    "opening": None,
                    "theory_status": "common-master-move",
                    "masters": {
                        "played_move": None,
                        "continuations": [],
                    },
                    "players": {
                        "played_move": None,
                        "continuations": [],
                    },
                },
                "motifs": [{"id": "take_center", "name": "Take the Center"}],
            }
        ],
    }


def valid_payload():
    return {
        "explanations": [
            {
                "ply": 1,
                "move": "e4",
                "side": "white",
                "explanation": (
                    "White occupies the center and opens lines for both the queen "
                    "and bishop. The supplied engine evidence supports this move."
                ),
                "lesson": "Use central pawn moves to unlock development.",
                "evidence_refs": [
                    "stockfish.evaluation",
                    "motifs.take_center",
                ],
            }
        ]
    }


class AICoachValidationTests(unittest.TestCase):
    def test_accepts_aligned_evidence_grounded_output(self):
        result = validate_explanations(valid_payload(), sample_analysis())
        self.assertEqual(result[0]["move"], "e4")
        self.assertEqual(result[0]["evidence_refs"][-1], "motifs.take_center")

    def test_rejects_wrong_ply_count_or_move(self):
        with self.assertRaises(AIResponseError):
            validate_explanations({"explanations": []}, sample_analysis())

        payload = valid_payload()
        payload["explanations"][0]["move"] = "d4"
        with self.assertRaisesRegex(AIResponseError, "move not found"):
            validate_explanations(payload, sample_analysis())

    def test_rejects_invented_evidence_reference(self):
        payload = valid_payload()
        payload["explanations"][0]["evidence_refs"] = ["lichess.fake.statistic"]
        with self.assertRaisesRegex(AIResponseError, "unavailable evidence"):
            validate_explanations(payload, sample_analysis())

    def test_cache_key_changes_with_perspective(self):
        white = build_explanation_cache_key(sample_analysis(), "white")
        black = build_explanation_cache_key(sample_analysis(), "black")
        self.assertNotEqual(white, black)

    def test_generate_explanations_uses_structured_json_response(self):
        response = SimpleNamespace(
            text=__import__("json").dumps(valid_payload())
        )
        models = SimpleNamespace(generate_content=lambda **_kwargs: response)
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(models=models)
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            result = generate_explanations(sample_analysis(), "white")
        self.assertEqual(result["perspective"], "white")
        self.assertEqual(result["explanations"][0]["ply"], 1)

    def test_missing_key_and_malformed_json_are_explicit_failures(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AIConfigurationError):
                generate_explanations(sample_analysis(), "both")

        models = SimpleNamespace(
            generate_content=lambda **_kwargs: SimpleNamespace(text="not json")
        )
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(models=models)
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            with self.assertRaisesRegex(AIResponseError, "malformed"):
                generate_explanations(sample_analysis(), "both")


if __name__ == "__main__":
    unittest.main()
