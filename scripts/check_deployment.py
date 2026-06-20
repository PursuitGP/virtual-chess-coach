#!/usr/bin/env python3
"""Verify a deployed service and optionally run one complete review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="For example: https://example.up.railway.app")
    parser.add_argument(
        "--pgn",
        type=Path,
        help="Optional PGN used for an analysis plus Gemini coaching smoke test.",
    )
    parser.add_argument(
        "--perspective",
        choices=("white", "black", "both"),
        default="both",
    )
    return parser.parse_args()


def response_json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"{response.request.method} {response.url} returned non-JSON "
            f"HTTP {response.status_code}."
        ) from exc
    if not response.ok:
        raise RuntimeError(
            f"{response.request.method} {response.url} returned "
            f"HTTP {response.status_code}: {payload}"
        )
    return payload


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    try:
        health = response_json(requests.get(f"{base_url}/api/health", timeout=20))
        ready = response_json(requests.get(f"{base_url}/api/ready", timeout=20))
        output = {
            "base_url": base_url,
            "health": {
                "status": health.get("status"),
                "ready": health.get("ready"),
                "environment": health.get("environment"),
            },
            "readiness": ready,
        }

        if args.pgn:
            with args.pgn.open("rb") as handle:
                analysis = response_json(
                    requests.post(
                        f"{base_url}/api/analyze",
                        files={"file": (args.pgn.name, handle, "application/x-chess-pgn")},
                        timeout=180,
                    )
                )
            coaching = response_json(
                requests.post(
                    f"{base_url}/api/explain",
                    json={
                        "analysis": analysis,
                        "perspective": args.perspective,
                    },
                    timeout=180,
                )
            )
            output["review"] = {
                "analysis_id": analysis.get("analysis_id"),
                "analyzed_plies": analysis.get("analyzed_plies"),
                "warnings": analysis.get("warnings"),
                "critical_multipv": (
                    analysis.get("providers", {})
                    .get("stockfish", {})
                    .get("critical_multipv")
                ),
                "coaching_explanations": len(
                    coaching.get("explanations") or []
                ),
                "model": coaching.get("model"),
            }

        print(json.dumps(output, indent=2))
        return 0
    except (OSError, requests.RequestException, RuntimeError) as exc:
        print(f"Deployment check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
