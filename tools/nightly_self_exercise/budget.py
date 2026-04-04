"""
Heuristic external-call budget for nightly cloud sampling (no billing API).
Estimates only; hard-stops before calls that would exceed cap.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Conservative USD estimates per call type (cheap mini-tier; adjust via env multipliers).
_DEFAULT_UNIT_COSTS = {
    "council_stream_sanity": float(os.environ.get("ATRIA_NIGHTLY_EST_USD_COUNCIL", "0.012")),
    "adversarial_style_stream": float(os.environ.get("ATRIA_NIGHTLY_EST_USD_ADV", "0.018")),
    "long_context_council": float(os.environ.get("ATRIA_NIGHTLY_EST_USD_LONG", "0.035")),
}


@dataclass
class BudgetTracker:
    max_usd: float
    spent_usd: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def can_afford(self, kind: str) -> bool:
        est = _DEFAULT_UNIT_COSTS.get(kind, 0.02)
        return self.spent_usd + est <= self.max_usd + 1e-9

    def charge(self, kind: str, detail: str, *, est_tokens_in: int = 0, est_tokens_out: int = 0) -> bool:
        est_usd = _DEFAULT_UNIT_COSTS.get(kind, 0.02)
        if self.spent_usd + est_usd > self.max_usd:
            return False
        self.spent_usd += est_usd
        self.calls.append(
            {
                "kind": kind,
                "est_usd": round(est_usd, 6),
                "est_tokens_in": est_tokens_in,
                "est_tokens_out": est_tokens_out,
                "detail": detail[:500],
            }
        )
        return True

    def est_token_totals(self) -> tuple[int, int]:
        tin = sum(int(c.get("est_tokens_in") or 0) for c in self.calls)
        tout = sum(int(c.get("est_tokens_out") or 0) for c in self.calls)
        return tin, tout

    def write(self, path: Path) -> None:
        tin, tout = self.est_token_totals()
        path.write_text(
            json.dumps(
                {
                    "max_usd": self.max_usd,
                    "spent_usd_est": round(self.spent_usd, 6),
                    "external_call_count": len(self.calls),
                    "est_tokens_in": tin,
                    "est_tokens_out": tout,
                    "calls": self.calls,
                    "note": "Estimates only; reconcile with provider dashboard.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def parse_cloud_budget_usd() -> float:
    raw = (os.environ.get("ATRIA_NIGHTLY_CLOUD_BUDGET_USD") or "0").strip()
    try:
        v = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, v)
