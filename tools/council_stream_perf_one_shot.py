"""
One-shot POST /run/stream (council) with perf logging to a file.

Usage (repo root):
  python tools/council_stream_perf_one_shot.py
  python tools/council_stream_perf_one_shot.py --no-mock-ollama   # real Ollama (may be slow)

Then grep the printed perf run id in the log file:
  rg <uuid> zenaf-perf-council-last.log
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_NAME = "zenaf-perf-council-last.log"


def _council_body(question: str) -> dict:
    """Mirrors a single-seat Zenaf + Thinking partner + per-seat Ollama (App.tsx shape)."""
    return {
        "mode": "council",
        "params": {
            "question": question,
            # Request override: skip native+teacher path (studio may enable shadow/warn/…).
            "teacher_mode": "off",
            "included_agents": ["cs-0"],
            "perspective_definitions": [
                {
                    "id": "cs-0",
                    "perspective_agent_id": "zenaf",
                    "name": "Zenaf",
                    "role": "Thinking partner",
                    "llm_provider": "ollama",
                    "mandate": {
                        "id": "thinking_partner",
                        "name": "Thinking partner",
                        "coreQuestion": "",
                        "optimizeFor": "",
                        "watchFor": "",
                        "failureMode": "",
                        "outputStyle": "",
                    },
                }
            ],
        },
        "routing_context": {
            "surface": "workspace_organizer",
            "action_kind": "structured_evaluation",
            "action_intent": "workspace_council",
            "streaming": True,
            "privacy_mode": "local",
            "allows_externalization": False,
        },
        "context": {"council_preflight": {}},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--no-mock-ollama",
        action="store_true",
        help="Call real Ollama (conversational path uses generate timeout 40s per call).",
    )
    p.add_argument(
        "--question",
        default="what should i do with my day",
        help='Exact council question (default matches UI repro).',
    )
    args = p.parse_args()

    log_path = ROOT / LOG_NAME
    perf_logger = logging.getLogger("zenaf.perf")
    perf_logger.setLevel(logging.INFO)
    perf_logger.handlers.clear()
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))
    perf_logger.addHandler(fh)
    perf_logger.propagate = True

    if not args.no_mock_ollama:
        from unittest.mock import patch

        from local_ai.providers.ollama import OllamaProvider

        def _fast_generate(self, prompt: str, *, timeout: int | None = None) -> str:
            return "[mock ollama] short reply for perf trace"

        patcher = patch.object(OllamaProvider, "generate", _fast_generate)
        patcher.start()

    from fastapi.testclient import TestClient

    from api.main import app

    body = _council_body(args.question.strip())
    client = TestClient(app)

    print("[Zenaf perf one-shot] POST /run/stream (question=%r)" % (body["params"]["question"],))
    if not args.no_mock_ollama:
        print("[Zenaf perf one-shot] OllamaProvider.generate is MOCKED for a fast finish.")

    with client.stream("POST", "/run/stream", json=body) as res:
        perf_id = (res.headers.get("X-Zenaf-Perf-Run-Id") or "").strip()
        print("[Zenaf perf] fetch_resolved perfRunId=%s" % perf_id)
        print(
            "[Zenaf perf] headers: X-Zenaf-Provider-Used=%r X-Zenaf-Model-Used=%r status=%s"
            % (
                res.headers.get("X-Zenaf-Provider-Used"),
                res.headers.get("X-Zenaf-Model-Used"),
                res.status_code,
            )
        )
        chunks = 0
        for line in res.iter_lines():
            if not line:
                continue
            chunks += 1
            if chunks <= 5:
                print("[Zenaf perf] sse line:", line[:200] + ("..." if len(line) > 200 else ""))
        print("[Zenaf perf] sse_lines_read=%s" % chunks)

    if not args.no_mock_ollama:
        patcher.stop()

    print("[Zenaf perf one-shot] Log file: %s" % log_path)
    print("[Zenaf perf one-shot] Grep: rg %s %s" % (perf_id or "<no-id>", LOG_NAME))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
