from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from backend import app as app_module
from backend.ai_coach import AIProviderError


SAMPLE_ANALYSIS = {
    "schema_version": 1,
    "analysis_id": "abc",
    "metadata": {},
    "moves": ["e4"],
    "total_plies": 1,
    "analyzed_plies": 1,
    "truncated": False,
    "warnings": [],
    "providers": {
        "stockfish": {"available": True},
        "lichess": {"available": True},
        "motifs": {"available": True},
    },
    "positions": [
        {
            "ply": 1,
            "side": "white",
            "played_move": {"san": "e4", "uci": "e2e4"},
            "stockfish": {},
            "lichess": {},
            "motifs": [],
        }
    ],
}

SAMPLE_COACHING = {
    "analysis_id": "abc",
    "perspective": "both",
    "model": "test-model",
    "prompt_version": "test",
    "explanations": [],
}


class AppTests(unittest.TestCase):
    def make_app(self, **overrides):
        config = {
            "TESTING": True,
            "DISABLE_RATE_LIMITS": True,
            "MAX_CONTENT_LENGTH": 1024 * 1024,
            "MAX_PGN_BYTES": 4096,
        }
        config.update(overrides)
        return app_module.create_app(config)

    def test_health_and_endpoint_validation(self):
        client = self.make_app().test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertIn(client.get("/api/ready").status_code, {200, 503})
        self.assertEqual(client.post("/api/analyze").status_code, 400)
        self.assertEqual(client.post("/api/explain", json={}).status_code, 400)

    def test_analyze_returns_evidence_without_calling_ai(self):
        app = self.make_app()
        client = app.test_client()
        with (
            patch.object(
                app_module,
                "build_analysis",
                return_value=SAMPLE_ANALYSIS,
            ) as analyze,
            patch.object(app_module, "generate_explanations") as explain,
        ):
            response = client.post(
                "/api/analyze",
                data={
                    "file": (io.BytesIO(b"1. e4 *"), "game.pgn"),
                    "rating_group": "1600",
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["analysis_id"], "abc")
        analyze.assert_called_once()
        self.assertEqual(
            analyze.call_args.kwargs["lichess_ratings"],
            (1600,),
        )
        self.assertEqual(analyze.call_args.kwargs["stockfish_multipv"], 1)
        self.assertEqual(
            analyze.call_args.kwargs["stockfish_critical_multipv"],
            4,
        )
        self.assertEqual(
            analyze.call_args.kwargs["stockfish_critical_max_positions"],
            5,
        )
        self.assertEqual(analyze.call_args.kwargs["stockfish_hash_mb"], 64)
        self.assertEqual(
            analyze.call_args.kwargs["stockfish_total_seconds"],
            16.0,
        )
        explain.assert_not_called()

    def test_oversized_upload_is_rejected(self):
        client = self.make_app(MAX_PGN_BYTES=64).test_client()
        response = client.post(
            "/api/analyze",
            data={"file": (io.BytesIO(b"x" * 128), "large.pgn")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "pgn_too_large")

    def test_explain_cache_reuses_completed_analysis(self):
        client = self.make_app().test_client()
        with patch.object(
            app_module,
            "generate_explanations",
            return_value=SAMPLE_COACHING,
        ) as generate:
            first = client.post(
                "/api/explain",
                json={"analysis": SAMPLE_ANALYSIS, "perspective": "both"},
            )
            second = client.post(
                "/api/explain",
                json={"analysis": SAMPLE_ANALYSIS, "perspective": "both"},
            )
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["cached"])
        self.assertTrue(second.get_json()["cached"])
        generate.assert_called_once()

    def test_ai_failure_is_retryable_and_does_not_create_fallback(self):
        client = self.make_app().test_client()
        with patch.object(
            app_module,
            "generate_explanations",
            side_effect=AIProviderError("provider unavailable"),
        ):
            response = client.post(
                "/api/explain",
                json={"analysis": SAMPLE_ANALYSIS, "perspective": "white"},
            )
        body = response.get_json()
        self.assertEqual(response.status_code, 502)
        self.assertTrue(body["retryable"])
        self.assertNotIn("explanations", body)

    def test_explain_requires_complete_evidence(self):
        client = self.make_app().test_client()
        incomplete = {
            **SAMPLE_ANALYSIS,
            "providers": {
                "stockfish": {"available": True},
                "lichess": {"available": False},
                "motifs": {"available": True},
            },
        }
        response = client.post(
            "/api/explain",
            json={"analysis": incomplete, "perspective": "both"},
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body["missing_providers"], ["lichess"])

    def test_separate_analysis_rate_limit(self):
        app = self.make_app(
            DISABLE_RATE_LIMITS=False,
            ANALYSIS_RATE_LIMIT=1,
            MAX_CONTENT_LENGTH=1024,
        )
        client = app.test_client()
        with patch.object(
            app_module,
            "build_analysis",
            return_value=SAMPLE_ANALYSIS,
        ):
            first = client.post(
                "/api/analyze",
                data={"file": (io.BytesIO(b"1. e4 *"), "one.pgn")},
                content_type="multipart/form-data",
            )
            second = client.post(
                "/api/analyze",
                data={"file": (io.BytesIO(b"1. d4 *"), "two.pgn")},
                content_type="multipart/form-data",
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_motif_endpoint_is_hidden_in_production(self):
        app = app_module.create_app(
            {
                "TESTING": False,
                "APP_ENV": "production",
                "ENABLE_DEV_ENDPOINTS": False,
                "DISABLE_RATE_LIMITS": True,
            }
        )
        response = app.test_client().post(
            "/api/motifs",
            json={"fen": "8/8/8/8/8/8/8/K6k w - - 0 1"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
