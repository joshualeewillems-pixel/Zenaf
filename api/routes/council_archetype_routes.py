"""Council archetype naming unlocks + seat avatars.

GET /council/archetypes/status — per-archetype training depth, rename
unlock state, avatar unlock state, and custom-archetype milestone progress.
PUT /council/archetypes/{id}/name — rename a seat. 404 for unknown ids,
403 when the rename milestone is not yet unlocked (with signals_to_unlock),
422 for invalid names.
PUT /council/archetypes/{id}/avatar — set a seat's avatar. Accepts
{"avatar_url": "..."} for uploads, or {"generate": true} to request
AI generation (501 — not yet available). 403 when the avatar milestone
is not yet unlocked (with avatar_signals_to_unlock).

Renaming and avatars are display preferences, not training: session auth
is enough (no train:self scope), same as the council-mode setting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import get_archetype
from local_ai.council.naming import rename_status

router = APIRouter(prefix="/council/archetypes", tags=["council-archetypes"])


class RenameBody(BaseModel):
    """New display name for a council archetype seat."""

    display_name: str = Field(min_length=1, max_length=60)


class AvatarBody(BaseModel):
    """Set a council archetype seat's avatar.

    Either avatar_url (user-uploaded image) or generate=True (AI-generated
    from the archetype's prompt frame + strand weights). Not both.
    """

    avatar_url: str | None = Field(default=None, max_length=2048)
    generate: bool = False


def _avatar_generation_prompt(archetype_id: str) -> str:
    """Build an image-generation prompt from the archetype's character.

    Draws on the prompt frame and dominant strands so the generated face
    reflects the seat's personality, not a generic avatar.
    """
    from local_ai.council.archetypes import KEY_TO_PLAIN

    arch = get_archetype(archetype_id)
    if arch is None or not arch.strand_weights:
        return "A wise, warm portrait avatar, painterly style, soft light"
    # Dominant strands shape the visual: e.g. Compass/Logic -> sage-like,
    # Heart/Hands -> warm guardian, Eye/Voice -> vivid and expressive.
    top = sorted(arch.strand_weights.items(), key=lambda kv: kv[1], reverse=True)[:3]
    strand_words = ", ".join(k.lower() for k, _ in top)
    return (
        f"Portrait avatar for '{arch.display_name}': {arch.prompt_frame} "
        f"Emphasize {strand_words}. Painterly, warm, distinctive face — "
        "not photorealistic, not generic. Square composition."
    )


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


@router.get("/status")
def get_archetype_status(current_user: dict = Depends(get_current_user)):
    """Naming unlock status for every council archetype.

    For each archetype: id, display_name (custom if renamed), depth
    (depth points from approved signals), rename_unlocked, and
    signals_to_unlock (depth points still needed, 0 when unlocked).
    Also reports the all-rename and custom-archetype milestones.
    """
    return rename_status(_uid(current_user))


@router.put("/{archetype_id}/name")
def rename_archetype(
    archetype_id: str,
    body: RenameBody,
    current_user: dict = Depends(get_current_user),
):
    """Rename a council archetype seat (after its unlock milestone).

    Joshua's principle: naming is intimate — the seat's training depth
    must reach 25 depth points before it can be renamed. Returns 403 with
    signals_to_unlock when the milestone is not yet met.
    """
    arch = get_archetype(archetype_id)
    if arch is None:
        raise HTTPException(
            status_code=404, detail=f"unknown archetype {archetype_id!r}"
        )
    uid = _uid(current_user)
    status = rename_status(uid)
    entry = next((a for a in status["archetypes"] if a["id"] == arch.id), None)
    if entry is None or not entry["rename_unlocked"]:
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    f"{arch.display_name} cannot be renamed yet — "
                    "naming unlocks after 25 depth points of training shape it."
                ),
                "signals_to_unlock": (entry or {}).get("signals_to_unlock", 25),
            },
        )
    from local_ai.personality.store import PersonalityStore

    store = PersonalityStore(user_id=uid)
    try:
        try:
            name = store.set_archetype_name(arch.id, body.display_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        store.close()
    return {"id": arch.id, "display_name": name}


@router.put("/{archetype_id}/avatar")
def set_archetype_avatar(
    archetype_id: str,
    body: AvatarBody,
    current_user: dict = Depends(get_current_user),
):
    """Set a council archetype seat's avatar (after its unlock milestone).

    Joshua's principle: the face comes before the name — visual
    individuation unlocks at 10 depth points, naming at 25. A seat with
    no avatar shows the ??? placeholder silhouette.

    Accepts {"avatar_url": "..."} for a user-uploaded image, or
    {"generate": true} to request AI generation from the archetype's
    prompt frame + strand weights (501 — image generation is not yet
    available through the Meta provider).

    Returns 403 with avatar_signals_to_unlock when the milestone is not
    yet met, 404 for unknown ids, 422 for invalid URLs.
    """
    from local_ai.council.naming import AVATAR_DEPTH_THRESHOLD, rename_status

    arch = get_archetype(archetype_id)
    if arch is None:
        raise HTTPException(
            status_code=404, detail=f"unknown archetype {archetype_id!r}"
        )
    uid = _uid(current_user)
    status = rename_status(uid)
    entry = next((a for a in status["archetypes"] if a["id"] == arch.id), None)
    if entry is None or not entry["avatar_unlocked"]:
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    f"{arch.display_name}'s face is still ??? — "
                    f"avatar unlocks after {AVATAR_DEPTH_THRESHOLD:g} depth points "
                    "of training shape it."
                ),
                "avatar_signals_to_unlock": (entry or {}).get(
                    "avatar_signals_to_unlock", AVATAR_DEPTH_THRESHOLD
                ),
            },
        )
    if body.generate and not body.avatar_url:
        # AI avatar generation is not yet wired: the Meta provider only
        # supports text generation. The prompt builder above
        # (_avatar_generation_prompt) is ready for when image generation
        # lands — the comic-strip renderer will need the same per-seat
        # visual identity contract (see local_ai/journal/story.py).
        raise HTTPException(
            status_code=501,
            detail=(
                "AI avatar generation is not yet available. Upload an image "
                "URL instead, or wait for the comic-strip renderer — it will "
                "share this seat's visual identity."
            ),
        )
    if not body.avatar_url:
        raise HTTPException(
            status_code=422, detail="Provide avatar_url or generate=true."
        )
    from local_ai.personality.store import PersonalityStore

    store = PersonalityStore(user_id=uid)
    try:
        try:
            url = store.set_archetype_avatar(arch.id, body.avatar_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        store.close()
    return {"id": arch.id, "avatar_url": url}


@router.delete("/{archetype_id}/avatar")
def clear_archetype_avatar(
    archetype_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a seat's custom avatar, restoring the ??? placeholder."""
    arch = get_archetype(archetype_id)
    if arch is None:
        raise HTTPException(
            status_code=404, detail=f"unknown archetype {archetype_id!r}"
        )
    uid = _uid(current_user)
    from local_ai.personality.store import PersonalityStore

    store = PersonalityStore(user_id=uid)
    try:
        store.clear_archetype_avatar(arch.id)
    finally:
        store.close()
    return {"id": arch.id, "avatar_url": None}
