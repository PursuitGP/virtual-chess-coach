"""Flask entrypoint for the Virtual Chess Coach.

The API intentionally separates deterministic evidence collection from AI
coaching:

    POST /api/analyze -> Stockfish + Lichess + motif evidence
    POST /api/explain -> Gemini synthesis over a completed evidence package

If Gemini fails, the evidence remains available and the client can retry. The
server never substitutes generic prose for failed AI coaching.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from pathlib import Path
from typing import Any

import chess
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
BUILD_DIR = PROJECT_ROOT / "build"

load_dotenv(BACKEND_DIR / ".env")

try:  # Package imports (Gunicorn / tests)
    from .ai_coach import (
        AIConfigurationError,
        AIProviderError,
        AIResponseError,
        build_explanation_cache_key,
        generate_explanations,
        gemini_status,
    )
    from .analysis import (
        AnalysisError,
        build_analysis,
        find_stockfish_path,
        lichess_status,
    )
    from .motifs import detect_motifs
    from .study_database import study_database_status
except ImportError:  # Script imports (`python backend/app.py`)
    from ai_coach import (
        AIConfigurationError,
        AIProviderError,
        AIResponseError,
        build_explanation_cache_key,
        generate_explanations,
        gemini_status,
    )
    from analysis import (
        AnalysisError,
        build_analysis,
        find_stockfish_path,
        lichess_status,
    )
    from motifs import detect_motifs
    from study_database import study_database_status

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class SlidingWindowLimiter:
    """Small in-memory limiter suitable for a single portfolio deployment."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: str, identity: str, limit: int, window: int = 3600) -> bool:
        now = time.monotonic()
        cutoff = now - window
        key = (bucket, identity)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


class LruResponseCache:
    def __init__(self, max_items: int = 128) -> None:
        self.max_items = max_items
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)


def _client_identity() -> str:
    return request.remote_addr or "unknown"


def _error(message: str, status: int, code: str, **extra: Any):
    payload: dict[str, Any] = {"error": message, "code": code}
    payload.update(extra)
    return jsonify(payload), status


def _rate_limited(
    app: Flask,
    limiter: SlidingWindowLimiter,
    bucket: str,
    limit: int,
):
    if app.config["DISABLE_RATE_LIMITS"]:
        return None
    if limiter.allow(bucket, _client_identity(), limit):
        return None
    return _error(
        "Too many requests. Please wait before trying again.",
        429,
        "rate_limited",
        retryable=True,
    )


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(BUILD_DIR) if BUILD_DIR.exists() else None,
        static_url_path="",
    )
    app.config.update(
        APP_ENV=os.getenv("APP_ENV", "development"),
        MAX_CONTENT_LENGTH=_env_int("MAX_REQUEST_BYTES", 2 * 1024 * 1024),
        MAX_PGN_BYTES=_env_int("MAX_PGN_BYTES", 256 * 1024),
        MAX_ANALYSIS_PLIES=_env_int("MAX_ANALYSIS_PLIES", 20),
        STOCKFISH_DEPTH=_env_int("STOCKFISH_DEPTH", 24),
        STOCKFISH_MAX_SECONDS=_env_float("STOCKFISH_MAX_SECONDS", 1.25),
        STOCKFISH_MULTIPV=_env_int("STOCKFISH_MULTIPV", 1),
        STOCKFISH_CRITICAL_MULTIPV=_env_int(
            "STOCKFISH_CRITICAL_MULTIPV", 4
        ),
        STOCKFISH_CRITICAL_MAX_POSITIONS=_env_int(
            "STOCKFISH_CRITICAL_MAX_POSITIONS", 4
        ),
        STOCKFISH_CRITICAL_MAX_SECONDS=_env_float(
            "STOCKFISH_CRITICAL_MAX_SECONDS", 0.3
        ),
        STOCKFISH_THREADS=_env_int("STOCKFISH_THREADS", 1),
        STOCKFISH_HASH_MB=_env_int("STOCKFISH_HASH_MB", 64),
        STOCKFISH_TOTAL_SECONDS=_env_float("STOCKFISH_TOTAL_SECONDS", 14.0),
        ANALYSIS_RATE_LIMIT=_env_int("ANALYSIS_RATE_LIMIT", 20),
        EXPLAIN_RATE_LIMIT=_env_int("EXPLAIN_RATE_LIMIT", 5),
        DISABLE_RATE_LIMITS=_env_bool("DISABLE_RATE_LIMITS", False),
        TRUST_PROXY=_env_bool("TRUST_PROXY", False),
        ENABLE_DEV_ENDPOINTS=_env_bool("ENABLE_DEV_ENDPOINTS", False),
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    limiter = SlidingWindowLimiter()
    explanation_cache = LruResponseCache(
        max_items=_env_int("EXPLANATION_CACHE_ITEMS", 128)
    )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.errorhandler(413)
    def request_too_large(_error_value):
        return _error(
            "The request body is too large.",
            413,
            "request_too_large",
            max_bytes=app.config["MAX_CONTENT_LENGTH"],
        )

    @app.get("/api/health")
    def health():
        stockfish_path = find_stockfish_path()
        ai = gemini_status()
        lichess = lichess_status()
        studies = study_database_status()
        ready = bool(
            stockfish_path
            and ai["ready"]
            and lichess["configured"]
            and studies["available"]
        )
        return jsonify(
            {
                "status": "ok" if ready else "degraded",
                "ready": ready,
                "environment": app.config["APP_ENV"],
                "capabilities": {
                    "stockfish": {
                        "available": bool(stockfish_path),
                        "path": stockfish_path if app.config["APP_ENV"] != "production" else None,
                        "target_depth": app.config["STOCKFISH_DEPTH"],
                        "time_limit_seconds_per_position": app.config[
                            "STOCKFISH_MAX_SECONDS"
                        ],
                        "multipv": app.config["STOCKFISH_MULTIPV"],
                        "critical_multipv": {
                            "multipv": app.config[
                                "STOCKFISH_CRITICAL_MULTIPV"
                            ],
                            "max_positions": app.config[
                                "STOCKFISH_CRITICAL_MAX_POSITIONS"
                            ],
                            "time_limit_seconds_per_position": app.config[
                                "STOCKFISH_CRITICAL_MAX_SECONDS"
                            ],
                        },
                        "threads": app.config["STOCKFISH_THREADS"],
                        "hash_mb": app.config["STOCKFISH_HASH_MB"],
                        "total_time_budget_seconds": app.config[
                            "STOCKFISH_TOTAL_SECONDS"
                        ],
                    },
                    "gemini": ai,
                    "lichess": {
                        **lichess,
                        "verified": False,
                    },
                    "motifs": {
                        "available": True,
                        "published_confidence_levels": ["high", "medium"],
                        "experimental_detectors_published": False,
                    },
                    "studies": {
                        **studies,
                        "path": (
                            studies["path"]
                            if app.config["APP_ENV"] != "production"
                            else None
                        ),
                    },
                },
                "limits": {
                    "max_pgn_bytes": app.config["MAX_PGN_BYTES"],
                    "max_request_bytes": app.config["MAX_CONTENT_LENGTH"],
                    "max_analysis_plies": app.config["MAX_ANALYSIS_PLIES"],
                },
            }
        )

    @app.get("/api/ready")
    def ready():
        stockfish_available = bool(find_stockfish_path())
        ai_ready = gemini_status()["ready"]
        lichess_configured = lichess_status()["configured"]
        studies_available = study_database_status()["available"]
        checks = {
            "stockfish": stockfish_available,
            "gemini": ai_ready,
            "lichess": lichess_configured,
            "studies": studies_available,
        }
        is_ready = all(checks.values())
        return (
            jsonify(
                {
                    "status": "ready" if is_ready else "not_ready",
                    "checks": checks,
                }
            ),
            200 if is_ready else 503,
        )

    def analyze_request():
        limited = _rate_limited(
            app,
            limiter,
            "analysis",
            app.config["ANALYSIS_RATE_LIMIT"],
        )
        if limited:
            return limited

        uploaded = request.files.get("file")
        if uploaded is None:
            return _error("No PGN file was uploaded.", 400, "missing_pgn")

        pgn_bytes = uploaded.read(app.config["MAX_PGN_BYTES"] + 1)
        if len(pgn_bytes) > app.config["MAX_PGN_BYTES"]:
            return _error(
                "PGN upload is too large.",
                413,
                "pgn_too_large",
                max_bytes=app.config["MAX_PGN_BYTES"],
            )

        try:
            rating_value = request.form.get("rating_group", "").strip()
            ratings = (int(rating_value),) if rating_value else ()
            speed_value = request.form.get("speeds", "").strip()
            speeds = tuple(
                value
                for value in speed_value.split(",")
                if value
            )
            result = build_analysis(
                pgn_bytes,
                max_plies=app.config["MAX_ANALYSIS_PLIES"],
                stockfish_depth=app.config["STOCKFISH_DEPTH"],
                stockfish_max_seconds=app.config["STOCKFISH_MAX_SECONDS"],
                stockfish_multipv=app.config["STOCKFISH_MULTIPV"],
                stockfish_critical_multipv=app.config[
                    "STOCKFISH_CRITICAL_MULTIPV"
                ],
                stockfish_critical_max_positions=app.config[
                    "STOCKFISH_CRITICAL_MAX_POSITIONS"
                ],
                stockfish_critical_max_seconds=app.config[
                    "STOCKFISH_CRITICAL_MAX_SECONDS"
                ],
                stockfish_threads=app.config["STOCKFISH_THREADS"],
                stockfish_hash_mb=app.config["STOCKFISH_HASH_MB"],
                stockfish_total_seconds=app.config[
                    "STOCKFISH_TOTAL_SECONDS"
                ],
                lichess_ratings=ratings,
                lichess_speeds=speeds,
            )
        except ValueError:
            return _error(
                "Lichess filters were invalid.",
                400,
                "invalid_lichess_filters",
            )
        except AnalysisError as exc:
            return _error(
                str(exc),
                exc.status_code,
                exc.code,
                retryable=exc.retryable,
            )
        except Exception:
            app.logger.exception("Unexpected analysis failure")
            return _error(
                "The game could not be analyzed.",
                500,
                "analysis_failed",
                retryable=True,
            )

        return jsonify(result)

    app.add_url_rule("/api/analyze", view_func=analyze_request, methods=["POST"])
    # Temporary compatibility for older local clients; new code and docs use /api/analyze.
    app.add_url_rule(
        "/api/evaluate_pgn",
        view_func=analyze_request,
        methods=["POST"],
    )

    @app.post("/api/explain")
    def explain():
        limited = _rate_limited(
            app,
            limiter,
            "explain",
            app.config["EXPLAIN_RATE_LIMIT"],
        )
        if limited:
            return limited

        data = request.get_json(silent=True) or {}
        analysis = data.get("analysis")
        perspective = data.get("perspective", "both")

        if not isinstance(analysis, dict):
            return _error(
                "A completed analysis package is required.",
                400,
                "missing_analysis",
            )
        positions = analysis.get("positions")
        if (
            not isinstance(positions, list)
            or not positions
            or len(positions) > app.config["MAX_ANALYSIS_PLIES"]
        ):
            return _error(
                "The analysis package has an invalid position count.",
                400,
                "invalid_analysis",
            )
        if perspective not in {"white", "black", "both"}:
            return _error(
                "Perspective must be white, black, or both.",
                400,
                "invalid_perspective",
            )
        providers = analysis.get("providers") or {}
        missing_evidence = [
            name
            for name in ("stockfish", "lichess", "motifs")
            if not (providers.get(name) or {}).get("available")
        ]
        if missing_evidence:
            return _error(
                "AI coaching requires complete Stockfish, Lichess, and motif evidence.",
                409,
                "evidence_incomplete",
                retryable=True,
                missing_providers=missing_evidence,
            )

        cache_key = build_explanation_cache_key(analysis, perspective)
        cached = explanation_cache.get(cache_key)
        if cached is not None:
            return jsonify({**cached, "cached": True})

        try:
            result = generate_explanations(analysis, perspective)
        except AIConfigurationError as exc:
            return _error(
                str(exc),
                503,
                "ai_not_configured",
                retryable=False,
            )
        except AIResponseError as exc:
            return _error(
                str(exc),
                502,
                "ai_invalid_response",
                retryable=True,
            )
        except AIProviderError as exc:
            return _error(
                str(exc),
                502,
                "ai_provider_error",
                retryable=True,
            )
        except Exception:
            app.logger.exception("Unexpected AI coaching failure")
            return _error(
                "AI coaching could not be generated.",
                502,
                "ai_provider_error",
                retryable=True,
            )

        explanation_cache.set(cache_key, result)
        return jsonify({**result, "cached": False})

    @app.post("/api/motifs")
    def motifs():
        if not (
            app.testing
            or app.debug
            or app.config["ENABLE_DEV_ENDPOINTS"]
        ):
            return _error("Not found.", 404, "not_found")

        data = request.get_json(silent=True) or {}
        fen = data.get("fen")
        if not fen:
            return _error("Missing FEN.", 400, "missing_fen")

        try:
            board = chess.Board(fen)
            previous_fen = data.get("previous_fen") or data.get("prev_fen")
            previous_board = chess.Board(previous_fen) if previous_fen else None
            motifs_found = detect_motifs(
                board=board,
                prev_board=previous_board,
                move_number=data.get("ply") or data.get("move_number"),
                eval_cp=data.get("eval_cp", 0),
                prev_eval=data.get("previous_eval_cp"),
                sf_raw=data.get("stockfish") or data.get("sf_raw") or {},
                last_move_uci=data.get("played_move_uci")
                or data.get("last_move_uci"),
                prev_move_uci=data.get("previous_move_uci")
                or data.get("prev_move_uci"),
                include_experimental=bool(data.get("include_experimental")),
            )
            return jsonify({"motifs": motifs_found})
        except ValueError:
            return _error("Invalid FEN.", 400, "invalid_fen")
        except Exception:
            app.logger.exception("Motif endpoint failed")
            return _error("Motif detection failed.", 500, "motif_failed")

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path: str = ""):
        if path.startswith("api/"):
            return _error("Not found.", 404, "not_found")
        if BUILD_DIR.exists():
            requested = BUILD_DIR / path
            if path and requested.is_file():
                return send_from_directory(BUILD_DIR, path)
            return send_from_directory(BUILD_DIR, "index.html")
        return jsonify(
            {
                "name": "Virtual Chess Coach API",
                "message": "React build not found. Run `npm run build` for production.",
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = _env_int("PORT", 5050)
    debug = _env_bool("FLASK_DEBUG", False)
    app.run(host="0.0.0.0", port=port, debug=debug)
