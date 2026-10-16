"""Council archetype status — the Living Tree's archetype branches.

GET /council/archetypes/status: the 7 stock archetypes with live per-archetype
depth (derived from strand training depths), the Skeptic's dynamically computed
weights, and the user's sub-personality twigs grouped under their parents.

Read-only: computes from live stores and mutates nothing. Session auth only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import (
    PLAIN_TO_KEY,
    STOCK_ARCHETYPES,
    compute_skeptic_weights,
)
from local_ai.personality.depth import band_for_score

router = APIRouter(prefix="/council", tags=["council"])


class TwigStatus(BaseModel):
    """A sub-personality twig sprouted off a stock archetype."""

    twig_id: str
    display_name: str
    domain: str
    domain_label: str
    status: str
    signal_count: int


class ArchetypeStatus(BaseModel):
    """One archetype branch of the Living Tree."""

    id: str
    display_name: str
    # Lowercase strand keys -> weight (sums to ~1.0). Frontend maps these to
    # strand colors; plain-spoken names are derivable via KEY_TO_PLAIN.
    strand_weights: dict[str, float]
    # 0..100 training depth: the archetype's weight vector applied to the
    # user's per-strand depth scores. Honest zeros when nothing is trained.
    depth: int = Field(ge=0, le=100)
    band: str
    prompt_frame: str
    twigs: list[TwigStatus] = Field(default_factory=list)
    is_skeptic: bool = False
    # Seat avatar: the user's custom avatar URL, or None for the ???
    # placeholder silhouette. Unlocks at 10 depth points (naming at 25).
    # The comic-strip renderer uses this same field: avatar_url present ->
    # draw the character with it; None -> amorphous cloud placeholder.
    # (The ??? silhouette in the UI and the cloud in comics are the same
    # concept at different fidelities: an undiscovered face.)
    avatar_url: str | None = None
    avatar_unlocked: bool = False
    avatar_signals_to_unlock: int = 0


class ArchetypeStatusResponse(BaseModel):
    archetypes: list[ArchetypeStatus]
    computed_at: str


def _user_id(current_user: dict) -> str:
    uid = (current_user or {}).get("id") or (current_user or {}).get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(uid)


def _strand_depth_scores(user_id: str) -> dict[str, int]:
    """Per-strand 0..100 depth scores keyed by lowercase strand key."""
    # Lazy imports: mirrors personality_routes and avoids import cycles.
    from api.routes.personality_routes import _store, _user_approved_signals
    from local_ai.personality.depth import compute_training_depth

    store = _store(user_id)
    try:
        profile = store.get_current()
        versions: list = []
        for meta in store.list_versions():
            v = store.get_version(meta["version"])
            if v is not None:
                versions.append((meta["version"], v))
        depths = compute_training_depth(
            signals=_user_approved_signals(),
            profile=profile,
            versions=versions,
        )
        return {k: d.score for k, d in depths.items()}
    finally:
        store.close()


def _twigs_by_parent(user_id: str) -> dict[str, list[TwigStatus]]:
    """Approved + proposed twigs grouped by parent archetype id."""
    from local_ai.council.twigs import TwigStore

    store = TwigStore()
    try:
        twigs = store.list(user_id)
    finally:
        store.close()
    out: dict[str, list[TwigStatus]] = {}
    for t in twigs:
        # Only surfaced twigs: approved ones live on the tree; proposed ones
        # show as buds awaiting review. Rejected/deleted never appear.
        if t.status not in ("approved", "proposed"):
            continue
        out.setdefault(t.parent_id, []).append(
            TwigStatus(
                twig_id=t.twig_id,
                display_name=t.display_name,
                domain=t.domain,
                domain_label=t.domain_label,
                status=t.status,
                signal_count=t.signal_count,
            )
        )
    return out


@router.get("/archetypes/status", response_model=ArchetypeStatusResponse)
def get_archetype_status(current_user: dict = Depends(get_current_user)):
    """Live archetype status for the Living Tree branches.

    Each archetype's depth is its strand-weight vector applied to the user's
    per-strand training depths — the archetype deepens as its constituent
    strands are trained. The Skeptic's weights are computed dynamically as
    the inverse of the user's dominant strands.
    """
    user_id = _user_id(current_user)
    strand_scores = _strand_depth_scores(user_id)
    skeptic_weights = compute_skeptic_weights(user_id)
    twigs_by_parent = _twigs_by_parent(user_id)

    # Avatar unlock state comes from the naming-milestone depth model
    # (avatar at 10 depth points, naming at 25). Computed once here so the
    # tree panel and the naming status endpoint agree.
    from local_ai.council.naming import rename_status as _naming_status

    naming = _naming_status(user_id)
    naming_by_id = {a["id"]: a for a in naming.get("archetypes", [])}

    out: list[ArchetypeStatus] = []
    for arch in STOCK_ARCHETYPES:
        is_skeptic = arch.id == "skeptic"
        weights_plain = skeptic_weights if is_skeptic else (arch.strand_weights or {})
        depth = round(
            sum(
                weights_plain.get(plain, 0.0) * strand_scores.get(PLAIN_TO_KEY[plain], 0)
                for plain in PLAIN_TO_KEY
            )
        )
        depth = max(0, min(100, depth))
        weights_keyed = {
            PLAIN_TO_KEY[plain]: w
            for plain, w in weights_plain.items()
            if plain in PLAIN_TO_KEY
        }
        out.append(
            ArchetypeStatus(
                id=arch.id,
                display_name=arch.display_name,
                strand_weights=weights_keyed,
                depth=depth,
                band=band_for_score(depth),
                prompt_frame=arch.prompt_frame,
                twigs=twigs_by_parent.get(arch.id, []),
                is_skeptic=is_skeptic,
                avatar_url=(naming_by_id.get(arch.id) or {}).get("avatar_url"),
                avatar_unlocked=bool(
                    (naming_by_id.get(arch.id) or {}).get("avatar_unlocked", False)
                ),
                avatar_signals_to_unlock=int(
                    (naming_by_id.get(arch.id) or {}).get("avatar_signals_to_unlock", 0)
                ),
            )
        )
    return ArchetypeStatusResponse(
        archetypes=out,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
