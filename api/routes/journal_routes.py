"""Journal as archetype story — render a journal entry as a scene with council archetypes as characters.

POST /journal/story: analyze the entry's strands, detect active archetypes,
render a short metaphorical story via the Meta LLM.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.journal.story import (
    analyze_entry_strands,
    build_cast,
    detect_active_archetypes,
    render_archetype_story,
    select_cast,
)

router = APIRouter(prefix="/journal", tags=["journal"])


class StoryBody(BaseModel):
    """A journal entry to render as an archetype story."""

    text: str = Field(min_length=1, max_length=20000)


class CastMember(BaseModel):
    id: str
    name: str
    similarity: float
    # Seat avatar URL, or None for the ??? placeholder. The comic-strip
    # renderer uses this: avatar when present, amorphous cloud when None.
    avatar_url: str | None = None


class StoryResponse(BaseModel):
    story: str
    cast: list[CastMember]
    strand_weights: dict[str, float]


@router.post("/story", response_model=StoryResponse)
def post_journal_story(
    body: StoryBody,
    current_user: dict = Depends(get_current_user),
):
    """Render a journal entry as an archetype story.

    1. Score the entry against the 7 strands (rule-based, no LLM).
    2. Match strand weights against archetype vectors (cosine similarity).
    3. Render a short scene with the top archetypes as characters (Meta LLM).
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Entry text is empty.")

    strand_weights = analyze_entry_strands(text)
    if not strand_weights:
        raise HTTPException(
            status_code=422,
            detail="Could not detect strand activity in this entry. Try a longer entry.",
        )

    user_id = (current_user or {}).get("id") or (current_user or {}).get("user_id")
    ranked = detect_active_archetypes(strand_weights, user_id=user_id)
    cast = select_cast(ranked)
    if not cast:
        raise HTTPException(status_code=422, detail="No archetypes activated.")

    try:
        story = render_archetype_story(text, cast, user_id=user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return StoryResponse(
        story=story,
        cast=[
            CastMember(
                id=m["id"],
                name=m["name"],
                similarity=m["similarity"],
                avatar_url=m["avatar_url"],
            )
            for m in build_cast(cast, user_id=user_id)
        ],
        strand_weights={k: round(v, 3) for k, v in strand_weights.items()},
    )
