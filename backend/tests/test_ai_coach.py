from __future__ import annotations

import unittest
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.ai_coach import (
    AIConfigurationError,
    AIResponseError,
    _build_prompt,
    _coaching_focus_briefing,
    _condense_analysis,
    _ground_explanation,
    _ground_lesson,
    _motif_summary,
    _required_coaching_points,
    _response_json_schema,
    _word_count,
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
                "study": {
                    "id": "kings-pawn-game-family",
                    "title": "King's Pawn Game family",
                    "summary": "A central opening family.",
                    "ideas": ["Develop quickly."],
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


def englund_pin_analysis():
    return {
        "analysis_id": "englund-pin",
        "positions": [
            {
                "ply": 11,
                "side": "white",
                "played_move": {"san": "Bc3", "uci": "d2c3"},
                "stockfish": {
                    "evaluation": {"type": "cp", "value": -520},
                    "top_lines": [
                        {
                            "moves_san": ["Bb4", "Bd2", "Qxa1"],
                            "moves_uci": ["f8b4", "c3d2", "b2a1"],
                        }
                    ],
                },
                "decision_context": {
                    "move_classification": {"label": "blunder"},
                    "engine_first_choice": {"san": "Nc3", "uci": "b1c3"},
                    "reply_tactics": {
                        "actual_matches_best": True,
                        "best_reply": {
                            "move": {"san": "Bb4", "uci": "f8b4"},
                            "new_absolute_pins": [
                                {
                                    "piece": "bishop",
                                    "square": "c3",
                                    "king": "e1",
                                    "attacked_enemy_pieces_before_pin": [
                                        {
                                            "piece": "queen",
                                            "square": "b2",
                                            "attacks_friendly_pieces": [
                                                {
                                                    "piece": "rook",
                                                    "square": "a1",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    },
                    "engine_choice_effects": {
                        "move": {"san": "Nc3", "uci": "b1c3"},
                        "moved_piece": {
                            "piece": "knight",
                            "from": "b1",
                            "to": "c3",
                        },
                        "develops_minor_piece": True,
                        "newly_defended_friendly_pieces": [
                            {
                                "piece": "rook",
                                "square": "a1",
                                "under_enemy_pressure": True,
                                "new_defenders": [
                                    {"piece": "queen", "square": "d1"}
                                ],
                            }
                        ],
                    },
                },
                "lichess": {},
                "motifs": [],
            }
        ],
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

    def test_discards_invented_evidence_reference(self):
        payload = valid_payload()
        payload["explanations"][0]["evidence_refs"] = ["lichess.fake.statistic"]
        result = validate_explanations(payload, sample_analysis())
        self.assertEqual(
            result[0]["evidence_refs"],
            ["decision_context"],
        )

    def test_cache_key_changes_with_perspective(self):
        white = build_explanation_cache_key(sample_analysis(), "white")
        black = build_explanation_cache_key(sample_analysis(), "black")
        self.assertNotEqual(white, black)

    def test_accepts_practical_lichess_evidence_references(self):
        payload = valid_payload()
        payload["explanations"][0]["evidence_refs"] = [
            "study.context",
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
        self.assertIn('"coaching_focus"', prompt)
        self.assertIn("position_after_opponent_reply", prompt)
        self.assertIn("Never say \"only move\"", prompt)
        self.assertIn('"study"', prompt)
        self.assertIn("45-110 words", prompt)
        self.assertIn("hard maximum of 150 words", prompt)
        self.assertIn("Do not explain centipawn thresholds", prompt)
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

    def test_condensed_analysis_scopes_reply_created_pin_after_reply(self):
        condensed = _condense_analysis(englund_pin_analysis())
        focus = condensed["positions"][0]["coaching_focus"]
        pin = next(
            item
            for item in focus
            if item["type"] == "absolute_pin_created_by_opponent_reply"
        )
        self.assertEqual(pin["timing"], "position_after_opponent_reply")
        self.assertEqual(pin["opponent_reply"]["san"], "Bb4")
        self.assertEqual(pin["pinned_piece"]["square"], "c3")

    def test_rejects_surface_level_two_sentence_coaching(self):
        payload = valid_payload()
        payload["explanations"][0]["explanation"] = (
            "White occupies the center with e4. This is an active opening move."
        )
        with self.assertRaisesRegex(AIResponseError, "too short"):
            validate_explanations(payload, sample_analysis())

    def test_rejects_pin_attributed_to_played_move_before_reply(self):
        payload = {
            "explanations": [
                {
                    "ply": 11,
                    "move": "Bc3",
                    "side": "white",
                    "explanation": (
                        "By moving the bishop to c3, White pins the bishop to "
                        "the king on e1, creating a tactical weakness. Black "
                        "then plays Bb4 and keeps pressure on the rook at a1. "
                        "The better move was Nc3, which develops the knight and "
                        "helps White coordinate the queenside."
                    ),
                    "lesson": (
                        "When attacking a queen, check whether the opponent can "
                        "create a pin that neutralizes your attacking piece."
                    ),
                    "evidence_refs": [
                        "decision_context",
                        "stockfish.top_lines",
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(
            AIResponseError,
            "exists only after Bb4",
        ):
            validate_explanations(payload, englund_pin_analysis())

    def test_accepts_pin_attributed_to_opponent_reply_without_rewriting(self):
        explanation = (
            "Bc3 attacks the queen on b2, but it allows Black's reply Bb4. "
            "Bb4 pins the bishop on c3 to the king on e1, so the bishop can no "
            "longer chase the queen and the rook on a1 remains under pressure. "
            "Nc3 was stronger because it develops the knight while helping the "
            "queen on d1 defend the rook."
        )
        payload = {
            "explanations": [
                {
                    "ply": 11,
                    "move": "Bc3",
                    "side": "white",
                    "explanation": explanation,
                    "lesson": (
                        "Before attacking a queen, check whether a pin after the "
                        "reply can make your attacking piece unable to move."
                    ),
                    "evidence_refs": [
                        "decision_context",
                        "stockfish.top_lines",
                    ],
                }
            ]
        }
        result = validate_explanations(payload, englund_pin_analysis())
        self.assertEqual(result[0]["explanation"], explanation)

    def test_rejects_generic_lesson_when_tactical_focus_is_available(self):
        payload = {
            "explanations": [
                {
                    "ply": 11,
                    "move": "Bc3",
                    "side": "white",
                    "explanation": (
                        "Bc3 attacks the queen on b2, but it allows Black's "
                        "reply Bb4. Bb4 pins the bishop on c3 to the king on e1, "
                        "so the bishop cannot continue attacking the queen and "
                        "the rook on a1 remains under pressure. Nc3 develops the "
                        "knight and gives White a more useful defense."
                    ),
                    "lesson": "Always be aware of tactics.",
                    "evidence_refs": ["decision_context"],
                }
            ]
        }
        with self.assertRaisesRegex(AIResponseError, "lesson was generic"):
            validate_explanations(payload, englund_pin_analysis())

    def test_preserves_natural_sentence_count_with_word_ceiling(self):
        seven = valid_payload()
        seven["explanations"][0]["explanation"] = (
            "White occupies the center with e4. The pawn opens the queen. "
            "It also opens the bishop. Black must challenge the center. "
            "White has several development choices. King safety still matters. "
            "This seventh sentence should be removed."
        )
        seven_result = validate_explanations(seven, sample_analysis())
        self.assertIn(
            "seventh sentence",
            seven_result[0]["explanation"],
        )

        oversized = valid_payload()
        oversized["explanations"][0]["explanation"] = " ".join(
            [
                (
                    f"Sentence {index} explains how White coordinates the "
                    "central pawn, development, king safety, and practical "
                    "choices without relying on generic engine praise."
                )
                for index in range(1, 18)
            ]
        )
        with self.assertRaisesRegex(
            AIResponseError,
            "readability limit",
        ):
            validate_explanations(oversized, sample_analysis())

    def test_response_schema_requires_one_structured_object_per_position(self):
        analysis = sample_analysis()
        schema = _response_json_schema(analysis)
        explanations = schema["properties"]["explanations"]
        self.assertEqual(explanations["minItems"], 1)
        self.assertEqual(explanations["maxItems"], 1)
        item = explanations["items"]
        self.assertEqual(item["type"], "object")
        self.assertIn("explanation", item["required"])
        self.assertEqual(
            item["properties"]["evidence_refs"]["items"],
            {"type": "string"},
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

    def test_required_points_attribute_only_move_to_engine_choice(self):
        position = {
            "played_move": {"san": "Kg8", "uci": "f7g8"},
            "decision_context": {
                "only_move": True,
                "played_matches_engine_first": False,
                "engine_first_choice": {"san": "Ke6"},
                "move_choice": {
                    "reason": "uniquely_prevents_forced_mate",
                    "alternatives": [
                        {"rank": 1, "move_san": "Ke6"},
                        {"rank": 2, "move_san": "Kg8"},
                    ],
                },
            },
            "stockfish": {"top_lines": []},
            "motifs": [],
        }
        points = _required_coaching_points(position)
        self.assertTrue(any("engine defense Ke6" in point for point in points))
        self.assertFalse(any("played move Kg8 uniquely" in point for point in points))

    def test_required_points_surface_f7_fork_threat_and_new_defense(self):
        position = {
            "played_move": {"san": "Ng5", "uci": "f3g5"},
            "decision_context": {
                "move_classification": {"label": "good"},
                "move_effects": {
                    "moved_piece": {
                        "piece": "knight",
                        "from": "f3",
                        "to": "g5",
                    },
                    "newly_defended_friendly_pieces": [
                        {
                            "piece": "pawn",
                            "square": "e4",
                            "under_enemy_pressure": True,
                        }
                    ],
                },
            },
            "stockfish": {"top_lines": []},
            "motifs": [
                {
                    "id": "f2_f7_weakness",
                    "extra": {
                        "target_square": "f7",
                        "threat_move_san": "Nxf7",
                        "fork_targets": [
                            {"piece": "queen", "square": "d8"},
                            {"piece": "rook", "square": "h8"},
                        ],
                    },
                }
            ],
        }
        points = _required_coaching_points(position)
        self.assertTrue(any("Nxf7" in point and "fork" in point for point in points))
        self.assertTrue(any("e4" in point and "defends" in point for point in points))

    def test_grounding_corrects_ng5_fork_and_e4_defense(self):
        position = {
            "played_move": {"san": "Ng5", "uci": "f3g5"},
            "decision_context": {
                "move_classification": {"label": "good"},
                "move_effects": {
                    "moved_piece": {
                        "piece": "knight",
                        "from": "f3",
                        "to": "g5",
                    },
                    "newly_defended_friendly_pieces": [
                        {
                            "piece": "pawn",
                            "square": "e4",
                            "under_enemy_pressure": True,
                        }
                    ],
                },
            },
            "motifs": [
                {
                    "id": "f2_f7_weakness",
                    "extra": {
                        "target_square": "f7",
                        "threat_move_san": "Nxf7",
                        "fork_targets": [
                            {"piece": "queen", "square": "d8"},
                            {"piece": "rook", "square": "h8"},
                        ],
                    },
                }
            ],
        }
        explanation, refs = _ground_explanation(
            "White increases pressure on f7 with the knight and bishop. "
            "The e4 pawn is potentially vulnerable after this aggressive move. "
            "Black must respond accurately to the kingside pressure.",
            position,
        )
        self.assertIn("Nxf7", explanation)
        self.assertIn("fork", explanation)
        self.assertIn("now defended", explanation)
        self.assertIn("motifs.f2_f7_weakness", refs)

    def test_grounding_enforces_quality_label_without_metric_noise(self):
        position = {
            "decision_context": {
                "move_classification": {
                    "label": "inaccuracy",
                    "centipawn_loss": 62,
                    "estimated_win_probability_loss_pct": 5.7,
                    "consequence": "sound",
                },
                "assessment_after": {
                    "classification": "slight_edge",
                    "leader": "white",
                },
            },
            "motifs": [],
        }
        explanation, refs = _ground_explanation(
            "Black centralizes the knight with a natural recapture. This is a "
            "mistake because White keeps the initiative. White now has a clear "
            "advantage and can continue attacking.",
            position,
        )
        self.assertIn("inaccuracy", explanation)
        self.assertNotIn("centipawns", explanation)
        self.assertNotIn("win probability", explanation)
        self.assertNotIn("mistake", explanation)
        self.assertNotIn("clear advantage", explanation)
        self.assertEqual(refs, set())

    def test_grounding_explains_abandoned_mate_square_and_specific_lesson(self):
        position = {
            "played_move": {"san": "Qxc3", "uci": "d2c3"},
            "decision_context": {
                "move_quality": "allows_forced_mate",
                "move_classification": {"label": "blunder"},
                "assessment_before": {
                    "classification": "decisive_advantage",
                    "leader": "black",
                },
                "engine_first_choice": {"san": "Nxc3"},
                "reply_tactics": {
                    "actual_matches_best": True,
                    "actual_reply": {
                        "move": {"san": "Qc1#", "uci": "b2c1"},
                        "gives_checkmate": True,
                        "target_square": "c1",
                        "defenders_before_played_move": [
                            {"piece": "queen", "square": "d2"}
                        ],
                        "defenders_after_played_move": [],
                        "moved_piece_was_lost_defender": {
                            "piece": "queen",
                            "square": "d2",
                        },
                        "new_absolute_pins": [],
                    },
                },
            },
            "stockfish": {
                "top_lines": [{"moves_san": ["Qc1#"]}]
            },
            "motifs": [
                {
                    "id": "forced_mate",
                    "extra": {
                        "defending_king_square": "e1",
                        "safe_adjacent_square_count": 0,
                        "mate_line_san": ["Qc1#"],
                    },
                }
            ],
        }
        explanation, refs = _ground_explanation(
            "Capturing the bishop on c3 with the queen is a blunder that "
            "allows black to deliver a forced mate. By taking the bishop, "
            "white walks into a tactical trap and loses the game immediately. "
            "This move is a significant error that changes the evaluation. "
            "It is a critical blunder that overlooks the tactical threats.",
            position,
        )
        lesson = _ground_lesson(
            "Always be aware of tactical threats.",
            position,
        )

        self.assertIn("c1 loses its only defender", explanation)
        self.assertIn("Qc1#", explanation)
        self.assertEqual(explanation.lower().count("blunder"), 1)
        self.assertNotIn("changes the evaluation", explanation)
        self.assertIn("decision_context", refs)
        self.assertIn("guarding c1", lesson)

    def test_grounding_explains_pin_that_neutralizes_queen_attack(self):
        position = {
            "played_move": {"san": "Bc3", "uci": "d2c3"},
            "decision_context": {
                "move_classification": {"label": "blunder"},
                "engine_first_choice": {"san": "Nc3"},
                "engine_choice_effects": {
                    "move": {"san": "Nc3", "uci": "b1c3"},
                    "moved_piece": {
                        "piece": "knight",
                        "from": "b1",
                        "to": "c3",
                    },
                    "develops_minor_piece": True,
                    "newly_defended_friendly_pieces": [
                        {
                            "piece": "rook",
                            "square": "a1",
                            "under_enemy_pressure": True,
                            "new_defenders": [
                                {"piece": "queen", "square": "d1"}
                            ],
                        }
                    ],
                },
                "reply_tactics": {
                    "actual_matches_best": True,
                    "actual_reply": {
                        "move": {"san": "Bb4", "uci": "f8b4"},
                        "new_absolute_pins": [
                            {
                                "piece": "bishop",
                                "square": "c3",
                                "king": "e1",
                                "attacked_enemy_pieces_before_pin": [
                                    {
                                        "piece": "queen",
                                        "square": "b2",
                                        "attacks_friendly_pieces": [
                                            {
                                                "piece": "rook",
                                                "square": "a1",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                },
            },
            "motifs": [],
        }
        explanation, _refs = _ground_explanation(
            "Moving the bishop to c3 is a blunder that allows black to gain a "
            "decisive advantage. The position collapses and White is worse.",
            position,
        )

        self.assertIn("Bb4 pins the bishop on c3", explanation)
        self.assertIn("queen on b2", explanation)
        self.assertIn("rook on a1", explanation)
        self.assertIn("Nc3 develops the knight from b1", explanation)
        self.assertIn("queen on d1", explanation)

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

    def test_generate_explanations_retries_transient_provider_failure(self):
        response = SimpleNamespace(
            text=__import__("json").dumps(valid_payload())
        )
        generate = Mock(
            side_effect=[RuntimeError("503 high demand"), response]
        )
        models = SimpleNamespace(generate_content=generate)
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(models=models)
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_PROVIDER_ATTEMPTS": "2",
                },
                clear=True,
            ),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
            patch("backend.ai_coach.time.sleep"),
        ):
            result = generate_explanations(sample_analysis(), "white")
        self.assertEqual(result["explanations"][0]["ply"], 1)
        self.assertEqual(generate.call_count, 2)

    def test_generate_explanations_retries_invalid_coaching_response(self):
        invalid = valid_payload()
        invalid["explanations"][0]["explanation"] = (
            "White plays e4, and under this review's thresholds Stockfish shows "
            "20 centipawns of advantage. The move is acceptable because the "
            "modeled winning-chance change stays small. Black can respond in "
            "the center while White continues normal development."
        )
        generate = Mock(
            side_effect=[
                SimpleNamespace(text=__import__("json").dumps(invalid)),
                SimpleNamespace(text=__import__("json").dumps(valid_payload())),
            ]
        )
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(
                models=SimpleNamespace(generate_content=generate)
            )
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_PROVIDER_ATTEMPTS": "2",
                },
                clear=True,
            ),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            result = generate_explanations(sample_analysis(), "white")

        self.assertEqual(generate.call_count, 2)
        retry_prompt = generate.call_args_list[1].kwargs["contents"]
        self.assertIn("previous response failed validation", retry_prompt)
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

    def test_briefing_surfaces_pin_with_timing_and_targets(self):
        condensed = _condense_analysis(englund_pin_analysis())
        briefing = _coaching_focus_briefing(condensed["positions"])
        self.assertIn("TACTICAL BRIEFING", briefing)
        self.assertIn("Bb4", briefing)
        self.assertIn("c3", briefing)
        self.assertIn("e1", briefing)
        self.assertIn("AFTER Bb4", briefing)
        self.assertIn("queen on b2", briefing)

    def test_condensed_reply_pin_preserves_enriched_evidence(self):
        analysis = englund_pin_analysis()
        pin = analysis["positions"][0]["decision_context"]["reply_tactics"][
            "best_reply"
        ]["new_absolute_pins"][0]
        pin.update(
            {
                "pinning_piece": {
                    "piece": "bishop",
                    "square": "b4",
                    "color": "black",
                },
                "anchor_piece": {
                    "piece": "king",
                    "square": "e1",
                    "color": "white",
                },
                "ray": ["b4", "c3", "d2", "e1"],
                "legal_along_ray_moves": [],
            }
        )
        condensed = _condense_analysis(analysis)
        focus = next(
            item
            for item in condensed["positions"][0]["coaching_focus"]
            if item["type"] == "absolute_pin_created_by_opponent_reply"
        )

        self.assertEqual(focus["pinning_piece"]["square"], "b4")
        self.assertEqual(focus["anchor_piece"]["square"], "e1")
        self.assertEqual(focus["ray"], ["b4", "c3", "d2", "e1"])

    def test_motif_summary_preserves_enriched_extra(self):
        extra = {
            "definition": "A fork attacks multiple valuable targets.",
            "forking_piece": {"piece": "knight", "square": "f7"},
            "targets": [
                {"piece": "queen", "square": "d8"},
                {"piece": "rook", "square": "h8"},
            ],
            "includes_check": False,
        }
        summary = _motif_summary(
            [
                {
                    "id": "fork",
                    "name": "Fork",
                    "side": "white",
                    "severity": "tactical",
                    "confidence": "medium",
                    "extra": extra,
                }
            ]
        )

        self.assertEqual(summary[0]["extra"], extra)

    def test_briefing_is_empty_when_no_tactical_focus(self):
        condensed = _condense_analysis(sample_analysis())
        briefing = _coaching_focus_briefing(condensed["positions"])
        self.assertEqual(briefing, "")

    def test_prompt_includes_briefing_for_englund_pin(self):
        prompt = _build_prompt(englund_pin_analysis(), "white")
        self.assertIn("TACTICAL BRIEFING", prompt)
        self.assertIn("Bb4", prompt)
        self.assertIn("AFTER Bb4", prompt)

    def test_prompt_omits_briefing_section_when_no_tactical_focus(self):
        prompt = _build_prompt(sample_analysis(), "both")
        self.assertNotIn("TACTICAL BRIEFING", prompt)

    def test_retry_prompt_names_briefing_when_coaching_was_generic(self):
        generic_payload = {
            "explanations": [
                {
                    "ply": 11,
                    "move": "Bc3",
                    "side": "white",
                    "explanation": (
                        "Bc3 attacks the queen but this is a blunder that allows "
                        "Black to gain a decisive advantage through tactical play. "
                        "The position becomes difficult for White who must now "
                        "defend against multiple threats. Nc3 was the better "
                        "choice that would have maintained equality for White."
                    ),
                    "lesson": "Always be aware of tactics.",
                    "evidence_refs": ["decision_context"],
                }
            ]
        }
        generate = Mock(
            side_effect=[
                SimpleNamespace(
                    text=__import__("json").dumps(generic_payload)
                ),
                SimpleNamespace(
                    text=__import__("json").dumps(
                        {
                            "explanations": [
                                {
                                    "ply": 11,
                                    "move": "Bc3",
                                    "side": "white",
                                    "explanation": (
                                        "Bc3 attacks the queen on b2 but allows "
                                        "Bb4 in reply. Bb4 pins the bishop on c3 "
                                        "to the king on e1, so the bishop can no "
                                        "longer chase the queen and the rook on a1 "
                                        "remains under pressure. Nc3 was stronger."
                                    ),
                                    "lesson": (
                                        "Before attacking a queen, check whether "
                                        "the reply creates a pin that neutralizes "
                                        "your attacking piece."
                                    ),
                                    "evidence_refs": ["decision_context"],
                                }
                            ]
                        }
                    )
                ),
            ]
        )
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(
                models=SimpleNamespace(generate_content=generate)
            )
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_PROVIDER_ATTEMPTS": "2",
                },
                clear=True,
            ),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            result = generate_explanations(englund_pin_analysis(), "white")

        self.assertEqual(generate.call_count, 2)
        retry_prompt = generate.call_args_list[1].kwargs["contents"]
        self.assertIn("TACTICAL BRIEFING", retry_prompt)
        self.assertIn("coaching stayed generic", retry_prompt)
        self.assertIn("exact squares and moves", retry_prompt)
        self.assertIn("Bb4 pins the bishop on c3", result["explanations"][0]["explanation"])

    def test_retry_prompt_names_timing_rule_on_chronology_error(self):
        bad_chronology = {
            "explanations": [
                {
                    "ply": 11,
                    "move": "Bc3",
                    "side": "white",
                    "explanation": (
                        "By moving the bishop to c3, White pins the bishop to "
                        "the king on e1, creating a tactical weakness. Black "
                        "then plays Bb4 and keeps pressure on the rook at a1. "
                        "The better move was Nc3, which develops the knight and "
                        "helps White coordinate the queenside."
                    ),
                    "lesson": (
                        "When attacking a queen, check whether a pin to the king "
                        "can make that attack unusable."
                    ),
                    "evidence_refs": ["decision_context"],
                }
            ]
        }
        generate = Mock(
            side_effect=[
                SimpleNamespace(
                    text=__import__("json").dumps(bad_chronology)
                ),
                SimpleNamespace(
                    text=__import__("json").dumps(
                        {
                            "explanations": [
                                {
                                    "ply": 11,
                                    "move": "Bc3",
                                    "side": "white",
                                    "explanation": (
                                        "Bc3 attacks the queen on b2 but allows "
                                        "Bb4. Bb4 pins the bishop on c3 to the "
                                        "king on e1; the bishop can no longer "
                                        "chase the queen and pressure on the rook "
                                        "on a1 continues. Nc3 develops the knight "
                                        "and adds a defender via the queen on d1."
                                    ),
                                    "lesson": (
                                        "Before attacking a queen, check whether "
                                        "the reply creates a pin that neutralizes "
                                        "your attacking piece."
                                    ),
                                    "evidence_refs": ["decision_context"],
                                }
                            ]
                        }
                    )
                ),
            ]
        )
        fake_genai = SimpleNamespace(
            Client=lambda **_kwargs: SimpleNamespace(
                models=SimpleNamespace(generate_content=generate)
            )
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GEMINI_PROVIDER_ATTEMPTS": "2",
                },
                clear=True,
            ),
            patch("backend.ai_coach._load_genai", return_value=fake_genai),
        ):
            generate_explanations(englund_pin_analysis(), "white")

        self.assertEqual(generate.call_count, 2)
        retry_prompt = generate.call_args_list[1].kwargs["contents"]
        self.assertIn("exists only after", retry_prompt)
        self.assertIn("position_after_opponent_reply", retry_prompt)
        self.assertIn("allows", retry_prompt)


if __name__ == "__main__":
    unittest.main()
