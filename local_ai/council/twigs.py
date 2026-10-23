"""Specialization twigs — domain-clustered offshoots of council archetypes.

When a user's approved training signals cluster distinctly in a domain
(e.g. 20+ cooking decisions whose strand pattern diverges from every stock
archetype), a twig can sprout: "Guardian of Cooking". A twig inherits its
parent archetype's weight vector, tilted toward the cluster's strand
distribution.

Twigs are NEVER auto-activated. Detection creates *proposals* (status
"proposed"); the user approves them explicitly, and only approved twigs
participate in council weaving.

Design: ~/workspace/zenaf-council-archetype-plan.md §2 (approved 2026-10-16).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any

from .archetypes import (
    PLAIN_TO_KEY,
    CouncilArchetype,
    get_archetype,
    stock_archetype_ids,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "council"
DEFAULT_DB_PATH = DATA_DIR / "twigs.db"

#: Signals sharing a domain at/above this count can form a cluster.
CLUSTER_MIN_SIGNALS = 20
#: A cluster qualifies only if its cosine distance from EVERY stock archetype
#: exceeds this (i.e. max similarity < 1 - threshold).
DIVERGENCE_THRESHOLD = 0.25
#: Minimum scored signals needed to trust a cluster's strand distribution.
CLUSTER_MIN_SCORED = 10
#: Twig weight when nudging a parent seat at council time (parent 70 / twig 30).
TWIG_BLEND_WEIGHT = 0.30

_STRAND_ORDER: tuple[str, ...] = tuple(PLAIN_TO_KEY.keys())

_SCHEMA = """
CREATE TABLE IF NOT EXISTS twigs (
    twig_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    domain_label TEXT NOT NULL,
    display_name TEXT NOT NULL,
    strand_weights_json TEXT NOT NULL,
    prompt_frame TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    signal_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_twigs_user ON twigs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_twigs_user_parent ON twigs(user_id, parent_id);
"""


@dataclass
class TwigRecord:
    """One stored twig (proposal or approved)."""

    twig_id: str
    user_id: str
    parent_id: str
    domain: str            # slug, e.g. "cooking"
    domain_label: str      # e.g. "Cooking"
    display_name: str      # e.g. "Guardian of Cooking"
    strand_weights: dict[str, float]
    prompt_frame: str
    status: str = "proposed"  # "proposed" | "approved"
    signal_count: int = 0
    created_at: str = ""

    def to_archetype(self) -> CouncilArchetype:
        """View this twig as a CouncilArchetype (for prompt weaving)."""
        return CouncilArchetype(
            id=self.twig_id,
            display_name=self.display_name,
            strand_weights=dict(self.strand_weights),
            prompt_frame=self.prompt_frame,
            parent_id=self.parent_id,
            is_stock=False,
        )


class TwigStore:
    """SQLite store for per-user twigs. Additive; one table, user-scoped rows."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save(self, twig: TwigRecord) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO twigs
                   (twig_id, user_id, parent_id, domain, domain_label, display_name,
                    strand_weights_json, prompt_frame, status, signal_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    twig.twig_id,
                    twig.user_id,
                    twig.parent_id,
                    twig.domain,
                    twig.domain_label,
                    twig.display_name,
                    json.dumps(twig.strand_weights),
                    twig.prompt_frame,
                    twig.status,
                    twig.signal_count,
                    twig.created_at or _now_iso(),
                ),
            )
            self._conn.commit()

    def get(self, user_id: str, twig_id: str) -> TwigRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM twigs WHERE user_id = ? AND twig_id = ?",
                (user_id, twig_id),
            ).fetchone()
        return _row_to_twig(row) if row else None

    def list(
        self,
        user_id: str,
        status: str | None = None,
        parent_id: str | None = None,
    ) -> list[TwigRecord]:
        q = "SELECT * FROM twigs WHERE user_id = ?"
        params: list[Any] = [user_id]
        if status:
            q += " AND status = ?"
            params.append(status)
        if parent_id:
            q += " AND parent_id = ?"
            params.append(parent_id)
        q += " ORDER BY created_at ASC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [_row_to_twig(r) for r in rows]

    def set_status(self, user_id: str, twig_id: str, status: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE twigs SET status = ? WHERE user_id = ? AND twig_id = ?",
                (status, user_id, twig_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete(self, user_id: str, twig_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM twigs WHERE user_id = ? AND twig_id = ?",
                (user_id, twig_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def has_domain(self, user_id: str, domain: str) -> bool:
        """True if the user already has a twig (any status) for this domain."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM twigs WHERE user_id = ? AND domain = ? LIMIT 1",
                (user_id, domain),
            ).fetchone()
        return row is not None


def _row_to_twig(row: sqlite3.Row) -> TwigRecord:
    return TwigRecord(
        twig_id=row["twig_id"],
        user_id=row["user_id"],
        parent_id=row["parent_id"],
        domain=row["domain"],
        domain_label=row["domain_label"],
        display_name=row["display_name"],
        strand_weights=json.loads(row["strand_weights_json"]),
        prompt_frame=row["prompt_frame"],
        status=row["status"],
        signal_count=row["signal_count"],
        created_at=row["created_at"],
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pure helpers (testable without a DB)
# ---------------------------------------------------------------------------

def domain_slug(zone: str) -> str:
    """Normalize a free-form zone into a URL-safe domain slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", (zone or "").strip().lower()).strip("-")
    return slug or "general"


def domain_label_for(zone: str) -> str:
    """Human label for a zone: 'meal planning' -> 'Meal Planning'."""
    label = re.sub(r"\s+", " ", (zone or "").strip())
    return label.title() if label else "General"


def _to_vector(weights: dict[str, float]) -> tuple[float, ...]:
    return tuple(weights.get(name, 0.0) for name in _STRAND_ORDER)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        n = len(_STRAND_ORDER)
        return {name: 1.0 / n for name in _STRAND_ORDER}
    return {k: v / total for k, v in weights.items()}


def blend_weights(
    parent_weights: dict[str, float],
    cluster_weights: dict[str, float],
    cluster_share: float = 0.5,
) -> dict[str, float]:
    """Blend a parent archetype vector with a cluster distribution.

    cluster_share=0.5 -> the plan's "inherit, then tilt halfway" default.
    """
    blended = {
        name: (1.0 - cluster_share) * parent_weights.get(name, 0.0)
        + cluster_share * cluster_weights.get(name, 0.0)
        for name in _STRAND_ORDER
    }
    return _normalize(blended)


def closest_parent(
    cluster_weights: dict[str, float],
) -> tuple[str, float, float]:
    """Return (parent_id, similarity, max_stock_similarity) for a cluster.

    Only the fixed stock archetypes are compared (the Skeptic's vector is
    dynamic and excluded). max_stock_similarity is the highest similarity
    across all fixed stock archetypes — used for the divergence check.
    """
    cv = _to_vector(cluster_weights)
    best_id, best_sim, max_sim = "", 0.0, 0.0
    for aid in stock_archetype_ids():
        arch = get_archetype(aid)
        if arch is None or arch.strand_weights is None:
            continue  # Skeptic: dynamic, not a fixed comparison point
        sim = _cosine(cv, _to_vector(arch.strand_weights))
        max_sim = max(max_sim, sim)
        if sim > best_sim:
            best_id, best_sim = aid, sim
    return best_id, best_sim, max_sim


def _stem(word: str) -> str:
    """Crude stemmer: strip common English suffixes (cook-ing -> cook)."""
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def domain_matches_twig(domain: str, domain_label: str, text: str) -> bool:
    """Does a run's question/context mention the twig's domain? (v1: keyword).

    Matches the slug, the label words, and their stems, so "cook" matches a
    "cooking" twig. Minimum 4 characters to avoid noise.
    """
    hay = (text or "").lower()
    if not hay:
        return False
    words = set(re.findall(r"[a-z0-9]+", hay))
    candidates: set[str] = set()
    if domain:
        candidates.add(domain.lower())
    candidates.update((domain_label or "").lower().split())
    for cand in candidates:
        if len(cand) < 4:
            continue
        if cand in hay:
            return True
        stem = _stem(cand)
        if len(stem) >= 4:
            if stem in hay:
                return True
            for w in words:
                if len(w) >= 4 and (w.startswith(stem) or stem.startswith(w)):
                    return True
    return False


# ---------------------------------------------------------------------------
# Cluster detection
# ---------------------------------------------------------------------------

def _licensed_approved_signals(user_id: str | None) -> list:
    """Approved signals scoped to the user's active identity license.

    Same scoping pattern as compute_skeptic_weights: signals whose session
    provenance license_id matches the active license. Never raises — returns
    [] on any failure.
    """
    if not user_id:
        return []
    try:
        from local_ai.presence_ingest.store import PresenceStore
        from local_ai.identity.service import get_license

        lic = get_license()
        if lic is None or getattr(lic, "status", "") != "active":
            return []
        license_id = lic.license_id
        store = PresenceStore()
        try:
            sessions = {s.session_id: s for s in store.list_sessions()}
            out = []
            for sig in store.list_signals(status="approved"):
                sess = sessions.get(sig.session_id)
                prov = (sess.provenance if sess else {}) or {}
                if prov.get("license_id") == license_id:
                    out.append(sig)
            return out
        finally:
            store.close()
    except Exception:
        return []


def detect_domain_clusters(user_id: str | None) -> list[dict[str, Any]]:
    """Find domain clusters in the user's approved signals.

    Groups approved signals by zone. A zone qualifies when it has
    CLUSTER_MIN_SIGNALS+ signals AND its aggregate strand distribution is
    cosine-divergent (> DIVERGENCE_THRESHOLD) from every fixed stock
    archetype vector.

    Returns a list of cluster dicts: domain, domain_label, signal_count,
    cluster_weights (plain-spoken), parent_id, parent_similarity.
    Never raises.
    """
    try:
        from local_ai.journal.story import analyze_entry_strands
    except Exception:
        return []
    signals = _licensed_approved_signals(user_id)
    if not signals:
        return []

    by_zone: dict[str, list] = {}
    for sig in signals:
        zone = (sig.zone or "").strip()
        if not zone:
            continue
        by_zone.setdefault(zone.lower(), []).append(sig)

    clusters: list[dict[str, Any]] = []
    for zone_key, sigs in by_zone.items():
        if len(sigs) < CLUSTER_MIN_SIGNALS:
            continue
        # Aggregate strand distribution from per-signal rule-based scores.
        agg: dict[str, float] = {name: 0.0 for name in _STRAND_ORDER}
        scored = 0
        for sig in sigs:
            w = analyze_entry_strands(sig.summary or "")
            if not w:
                continue
            scored += 1
            for name, val in w.items():
                agg[name] = agg.get(name, 0.0) + val
        if scored < CLUSTER_MIN_SCORED:
            continue
        cluster_weights = _normalize(agg)
        parent_id, parent_sim, max_stock_sim = closest_parent(cluster_weights)
        if not parent_id:
            continue
        if (1.0 - max_stock_sim) <= DIVERGENCE_THRESHOLD:
            continue  # not distinct enough — the stock archetypes cover it
        clusters.append(
            {
                "domain": domain_slug(zone_key),
                "domain_label": domain_label_for(zone_key),
                "signal_count": len(sigs),
                "cluster_weights": cluster_weights,
                "parent_id": parent_id,
                "parent_similarity": round(parent_sim, 3),
            }
        )
    # Most signals first — the strongest clusters surface first.
    clusters.sort(key=lambda c: c["signal_count"], reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Sprouting (proposal-first — never silent)
# ---------------------------------------------------------------------------

def sprout_twig(
    user_id: str,
    parent_id: str,
    domain: str,
    cluster_weights: dict[str, float],
    signal_count: int = 0,
    store: TwigStore | None = None,
) -> TwigRecord:
    """Create a twig proposal off a parent archetype.

    Weights: parent vector blended 50/50 with the cluster distribution.
    Status is always "proposed" — the user approves via the API.
    """
    parent = get_archetype(parent_id)
    if parent is None or parent.strand_weights is None:
        raise ValueError(f"Cannot sprout twig: unknown parent archetype {parent_id!r}")
    slug = domain_slug(domain)
    label = domain_label_for(domain if domain != slug else domain)
    twig_id = f"{parent_id}-{slug}"
    weights = blend_weights(parent.strand_weights, cluster_weights, cluster_share=0.5)
    twig = TwigRecord(
        twig_id=twig_id,
        user_id=user_id,
        parent_id=parent_id,
        domain=slug,
        domain_label=label,
        display_name=f"{parent.display_name} of {label}",
        strand_weights=weights,
        prompt_frame=(
            f"{parent.prompt_frame} When the conversation turns to "
            f"{label.lower()}, you bring the specific texture of that world — "
            f"its stakes, its craft, its language."
        ),
        status="proposed",
        signal_count=signal_count,
        created_at=_now_iso(),
    )
    (store or TwigStore()).save(twig)
    return twig


def detect_and_propose(
    user_id: str,
    store: TwigStore | None = None,
) -> list[TwigRecord]:
    """Run cluster detection and create proposals for new qualifying domains.

    Skips domains the user already has a twig for (any status). Never raises.
    """
    twig_store = store or TwigStore()
    proposed: list[TwigRecord] = []
    try:
        clusters = detect_domain_clusters(user_id)
    except Exception:
        return []
    for cluster in clusters:
        try:
            if twig_store.has_domain(user_id, cluster["domain"]):
                continue
            twig = sprout_twig(
                user_id,
                cluster["parent_id"],
                cluster["domain"],
                cluster["cluster_weights"],
                signal_count=cluster["signal_count"],
                store=twig_store,
            )
            proposed.append(twig)
        except Exception:
            continue
    return proposed


# ---------------------------------------------------------------------------
# Council-time weaving
# ---------------------------------------------------------------------------

def apply_twig_overrides(
    perspective_definitions: list[dict] | None,
    user_id: str | None,
    question: str | None,
    context: str | None,
    store: TwigStore | None = None,
) -> list[dict] | None:
    """Nudge parent archetype seats with matching approved twigs.

    For each seat definition naming an archetype, if the user has an APPROVED
    twig under that parent whose domain matches the run's question/context,
    blend the parent weights 70/30 with the twig weights and set
    archetype_weights / archetype_name overrides (which
    _build_council_persona_block already honors).

    Returns a new list with copied dicts — the caller's definitions are not
    mutated. Returns the input unchanged when there is nothing to do.
    Never raises.
    """
    if not perspective_definitions or not user_id:
        return perspective_definitions
    try:
        twig_store = store or TwigStore()
        approved = twig_store.list(user_id, status="approved")
    except Exception:
        return perspective_definitions
    if not approved:
        return perspective_definitions

    haystack = f"{question or ''} {context or ''}"
    by_parent: dict[str, list[TwigRecord]] = {}
    for twig in approved:
        by_parent.setdefault(twig.parent_id, []).append(twig)

    out: list[dict] = []
    changed = False
    for defn in perspective_definitions:
        if not isinstance(defn, dict):
            out.append(defn)
            continue
        arch_id = (defn.get("archetype") or "").strip().lower()
        twigs = by_parent.get(arch_id, []) if arch_id else []
        match: TwigRecord | None = None
        for twig in sorted(twigs, key=lambda t: t.signal_count, reverse=True):
            if domain_matches_twig(twig.domain, twig.domain_label, haystack):
                match = twig
                break
        if match is None:
            out.append(defn)
            continue
        parent = get_archetype(arch_id)
        parent_weights = (
            parent.strand_weights
            if parent is not None and parent.strand_weights is not None
            else None
        )
        if parent_weights is None:
            out.append(defn)
            continue
        new_defn = dict(defn)
        new_defn["archetype_weights"] = blend_weights(
            parent_weights, match.strand_weights, cluster_share=TWIG_BLEND_WEIGHT
        )
        new_defn["archetype_name"] = match.display_name
        out.append(new_defn)
        changed = True
    return out if changed else perspective_definitions
