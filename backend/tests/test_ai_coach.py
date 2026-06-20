from __future__ import annotations

import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from backend.ai_coach import (
    AIConfigurationError,
    AIResponseError,
    _build_prompt,
    _condense_analysis,
    _ground_explanation,
    _required_coaching_points,
    _response_json_schema,
    build_explanation_cache_key,
    generate_explanations,
    validate_explanations,
    verify_gemini_connection,
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
                    "top_lines": [
                        {
                            "rank": 1,
                            "moves_uci": ["e2e4", "e7e5"],
                        }
                    ],
                },
                "decision_context": {
                    "assessment_before": {
                        "classification": "roughly_equal",
                        "leader": None,
                    },
                    "assessment_after": {
                        "classification": "slight_edge",
                        "leader": "white",
                    },
                    "move_quality": "sound",
                    "critical_tactical_position": False,
                    "critical_engine_response": False,
                    "only_move": None,
                },
                "lichess": {
                    "opening": {"eco": "C20", "name": "King's Pawn Game"},
                    "opening_context": {
                        "description": "A central opening family.",
                    },
                    "theory_status": "common-master-move",
                    "practical_signal": {
                        "classification": "master-aligned-and-sound"
                    },
                    "practical_candidates": [
                        {"uci": "e7e5", "stockfish_rank": 1}
                    ],
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
                    "and bishop. The supplied engine evidence supports this move "
                    "without showing a meaningful concession. Black must now "
                    "decide how to challenge the central pawn and complete "
                    "development. This gives White useful space while keeping "
                    "several sound plans available."
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

    def test_accepts_practical_lichess_evidence_references(self):
        payload = valid_payload()
        payload["explanations"][0]["evidence_refs"] = [
            "lichess.opening_context",
            "lichess.practical_signal",
            "lichess.practical_candidates",
            "stockfish.top_lines",
        ]
        result = validate_explanations(payload, sample_analysis())
        self.assertEqual(len(result[0]["evidence_refs"]), 4)

    def test_prompt_lists_only_refs_available_for_each_ply(self):
        prompt = _build_prompt(sample_analysis(), "both")
        self.assertIn('"available_evidence_refs"', prompt)
        self.assertIn('"motifs.take_center"', prompt)
        self.assertIn('"sequence_context"', prompt)
        self.assertIn('"decision_context"', prompt)
        self.assertIn('"required_coaching_points"', prompt)
        self.assertIn("Never say \"only move\"", prompt)
        self.assertIn("4-6 complete sentences", prompt)
        self.assertNotIn('"lichess.fake.statistic"', prompt)

    def test_condensed_analysis_includes_adjacent_position_context(self):
        analysis = sample_analysis()
        second = {
            **analysis["positions"][0],
            "ply": 2,
            "side": "black",
            "played_move": {"san": "e5", "uci": "e7e5"},
        }
        analysis["positions"].append(second)
        condensed = _condense_analysis(analysis)
        first = condensed["positions"][0]
        second_condensed = condensed["positions"][1]
        self.assertEqual(
            first["sequence_context"]["next_position"]["played_move"]["san"],
            "e5",
        )
        self.assertIn("context.next_position", first["available_evidence_refs"])
        self.assertIn(
            "context.previous_position",
            second_condensed["available_evidence_refs"],
        )

    def test_rejects_surface_level_two_sentence_coaching(self):
        payload = valid_payload()
        payload["explanations"][0]["explanation"] = (
            "White occupies the center with e4. This is an active opening move."
        )
        with self.assertRaisesRegex(AIResponseError, "too short|4 to 6"):
            validate_explanations(payload, sample_analysis())

    def test_response_schema_requires_one_structured_object_per_position(self):
        analysis = sample_analysis()
        schema = _response_json_schema(analysis)
        explanations = schema["properties"]["explanations"]
        self.assertEqual(explanations["minItems"], 1)
        self.assertEqual(explanations["maxItems"], 1)
        item = explanations["prefixItems"][0]
        self.assertEqual(item["type"], "object")
        self.assertIn("explanation", item["required"])
        self.assertEqual(item["properties"]["move"]["enum"], ["e4"])
        self.assertIn(
            "motifs.take_center",
            item["properties"]["evidence_refs"]["items"]["enum"],
        )
        self.assertIn(
            "decision_context",
            item["properties"]["evidence_refs"]["items"]["enum"],
        )

    def test_required_points_force_mate_blunder_contrast(self):
        position = {
            "ply": 14,
            "decision_context": {
                "assessment_before": {
                    "classification": "slight_edge",
                    "leader": "white",
                },
                "assessment_after": {
                    "classification": "forced_mate",
                    "leader": "white",
                },
                "move_quality": "allows_forced_mate",
                "engine_first_choice": {"san": "Ke6"},
                "material_after": {
                    "leader": "black",
                    "advantage_pawns": 2,
                },
            },
            "stockfish": {
                "top_lines": [{"moves_san": ["Bxd5+", "Qxd5", "Qxd5+"]}]
            },
            "motifs": [
                {
                    "id": "forced_mate",
                    "extra": {
                        "defending_king_square": "g8",
                        "safe_adjacent_square_count": 0,
                        "mate_line_san": [
                            "Bxd5+",
                            "Qxd5",
                            "Qxd5+",
                            "Be6",
                            "Qxe6#",
                        ],
                    },
                }
            ],
        }
        points = _required_coaching_points(position)
        self.assertTrue(any("not a forced mate" in point for point in points))
        self.assertTrue(any("Ke6" in point for point in points))
        self.assertTrue(any("0 immediately safe" in point for point in points))
        self.assertTrue(any("Bxd5+" in point for point in points))

    def test_grounding_adds_best_defense_and_material_context(self):
        position = {
            "ply": 13,
            "side": "white",
            "stockfish": {
                "top_lines": [{"moves_san": ["Ke6", "Nc3"]}]
            },
            "decision_context": {
                "assessment_after": {
                    "classification": "slight_edge",
                    "leader": "white",
                },
                "material_after": {
                    "leader": "black",
                    "advantage_pawns": 2,
                },
                "only_move": None,
            },
            "motifs": [
                {
                    "id": "fork",
                    "extra": {
                        "includes_check": True,
                        "forking_piece": {
                            "piece": "queen",
                            "square": "f3",
                        },
                        "targets": [
                            {"piece": "king", "square": "f7"},
                            {"piece": "knight", "square": "d5"},
                        ],
                    },
                }
            ],
        }
        explanation, refs = _ground_explanation(
            "White checks with the queen on f3. The queen also attacks the "
            "knight on d5. Black must answer the check immediately. White "
            "keeps the initiative in a sharp position.",
            position,
        )
        self.assertIn("Ke6", explanation)
        self.assertIn("2 points ahead in material", explanation)
        self.assertIn("only a slight edge for white", explanation)
        self.assertIn("decision_context", refs)
        self.assertIn("motifs.fork", refs)

    def test_grounding_removes_routine_engine_applause(self):
        explanation, _refs = _ground_explanation(
            "White claims the center with e4. The pawn opens the bishop and "
            "queen. Black must decide how to challenge the center. The engine "
            "evaluation confirms this is a sound opening move.",
            {
                "ply": 1,
                "decision_context": {
                    "critical_tactical_position": False,
                    "only_move": None,
                },
                "motifs": [],
            },
        )
        self.assertNotIn("confirms this is a sound", explanation)
        self.assertIn("not a numerical verdict", explanation)

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

    def test_provider_verification_reports_success_without_exposing_key(self):
        response = SimpleNamespace(text='{"ok": true}')
        models = SimpleNamespace(generate_content=lambda **_kwargs: response)
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(models=models)
        )
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            status = verify_gemini_connection()
        self.assertTrue(status["verified"])
        self.assertNotIn("test-key", str(status))


if __name__ == "__main__":
    unittest.main()
