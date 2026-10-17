"""Pipeline orchestration — the seam the API routes call.

Journal entries are registered as `journal_entry` artifacts in the
provenance registry (private by default — personal writing), so the
story → entry link is walkable in the lineage view. Stories, packs, and
quote cards follow the registry's standard visibility default (unlisted).

Text artifacts carry SHA-256 of normalized text; there is no perceptual
hash for text in the MVP (simhash is phase 2).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from local_ai.provenance import service as prov
from local_ai.provenance.fingerprints import fingerprint_image
from local_ai.provenance.store import ProvenanceStore

from . import markers, packs, quote_cards, stories, taste
from .store import PipelineStore

ANCHORING_QUESTION = "How does this piece express this moment to you?"


def _text_sha256(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_owner(entry_or_artifact: dict[str, Any], user_id: str, what: str) -> None:
    owner = entry_or_artifact.get("user_id", entry_or_artifact.get("creator_user_id"))
    custodian = entry_or_artifact.get("custodian_user_id")
    if user_id not in (owner, custodian):
        raise PermissionError(f"not your {what}")


def _story_content(artifact: dict[str, Any]) -> dict[str, Any]:
    """Story artifacts carry their content as JSON in `description`."""
    try:
        data = json.loads(artifact.get("description") or "{}")
    except (json.JSONDecodeError, TypeError):
        data = {}
    return {
        "title": artifact.get("title") or "",
        "narrative": data.get("narrative") or "",
        "key_line": data.get("key_line") or "",
        "archetype_cast": artifact.get("archetype_cast") or [],
    }


# -- journal entries ----------------------------------------------------------


def create_journal_entry(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    text: str,
) -> dict[str, Any]:
    """Save a journal entry, register it as a (private) artifact, and run
    the marker detector. Returns {entry, suggestion | None}."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Entry text is empty.")
    if len(text) > 20000:
        raise ValueError("Entry is too long (max 20,000 characters).")

    source_hash = _text_sha256(text)
    artifact = prov_store.create_artifact(
        creator_user_id=user_id,
        custodian_user_id=user_id,
        title=text[:60] + ("…" if len(text) > 60 else ""),
        description="",
        modality="text",
        sha256=source_hash,
        visibility="private",  # personal writing: default-deny
        remix_policy="open",
        imported=False,
        creator_declared=True,
    )
    prov_store.log_event(artifact["artifact_id"], "minted", actor_user_id=user_id)

    entry = pstore.create_entry(
        user_id, text, source_hash, artifact_id=artifact["artifact_id"]
    )

    suggestion = markers.pick_suggestion(
        text, precision_of=pstore.marker_precision
    )
    if suggestion:
        pstore.update_entry(
            entry["entry_id"],
            suggested_at=entry["created_at"],
            suggested_marker=suggestion["marker"],
            suggested_modality=suggestion["modality"],
            suggestion_copy=suggestion["copy"],
        )
        entry = pstore.get_entry(entry["entry_id"])
    return {"entry": entry, "suggestion": suggestion}


def list_journal_entries(
    pstore: PipelineStore, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    return pstore.list_entries(user_id, limit=limit)


def dismiss_suggestion(
    pstore: PipelineStore, user_id: str, entry_id: str
) -> dict[str, Any]:
    """'Not a story moment' — records the verdict and tunes the detector."""
    entry = pstore.get_entry(entry_id)
    if entry is None:
        raise KeyError(f"unknown journal entry: {entry_id}")
    if entry["user_id"] != user_id:
        raise PermissionError("not your journal entry")
    if entry.get("suggested_marker") and not entry.get("dismissed"):
        pstore.record_suggestion(entry["suggested_marker"], accepted=False)
    return pstore.update_entry(entry_id, dismissed=True)


# -- stories --------------------------------------------------------------------


def make_story(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    entry_id: str,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Extract a story from a journal entry and register it as a `story`
    artifact parented to the entry's artifact."""
    entry = pstore.get_entry(entry_id)
    if entry is None:
        raise KeyError(f"unknown journal entry: {entry_id}")
    if entry["user_id"] != user_id:
        raise PermissionError("not your journal entry")
    if entry.get("storified"):
        raise ValueError("this entry already has a story")
    if not entry.get("artifact_id"):
        raise ValueError("journal entry has no registry artifact")

    content = stories.extract_story(entry["text"], user_id=user_id, api_key=api_key)

    artifact = prov_store.create_artifact(
        creator_user_id=user_id,
        custodian_user_id=user_id,
        title=content["title"],
        description=json.dumps({
            "narrative": content["narrative"],
            "key_line": content["key_line"],
        }),
        archetype_cast=content["archetype_cast"],
        source_hash=entry["source_hash"],
        modality="text",
        sha256=_text_sha256(
            content["title"] + "\n" + content["narrative"] + "\n" + content["key_line"]
        ),
        visibility="unlisted",
        remix_policy="open",
        imported=False,
        creator_declared=True,
    )
    prov_store.log_event(artifact["artifact_id"], "minted", actor_user_id=user_id)
    prov_store.add_link(artifact["artifact_id"], entry["artifact_id"], "linked")

    # A suggestion shown and acted on is an accept for the detector.
    if entry.get("suggested_marker") and not entry.get("dismissed"):
        pstore.record_suggestion(entry["suggested_marker"], accepted=True)
    pstore.update_entry(entry_id, storified=True)

    return {"artifact": artifact, "content": content}


# -- prompt packs ---------------------------------------------------------------


def plan_packs(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    story_id: str,
) -> dict[str, Any]:
    """Graduated taste flow: ask | suggest | propose (spec §3)."""
    story = prov_store.get_artifact(story_id)
    if story is None:
        raise KeyError(f"unknown story: {story_id}")
    _require_owner(story, user_id, "story")

    stage = taste.get_stage(pstore, user_id)
    result: dict[str, Any] = {"stage": stage, "story_id": story_id}
    if stage == "ask":
        result["questions"] = [
            {**q, "suggestions": q["generic_suggestions"]}
            for q in taste.QUESTIONS
        ]
    elif stage == "suggest":
        personalized = taste.personalized_suggestions(pstore, user_id)
        result["questions"] = [
            {**q, "suggestions": personalized[q["id"]]}
            for q in taste.QUESTIONS
        ]
    else:
        content = _story_content(story)
        story_markers = markers.detect_markers(content["narrative"])
        result["proposal"] = taste.build_proposal(pstore, user_id, story_markers)
    return result


def generate_packs(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    story_id: str,
    modalities: list[str],
    *,
    answers: dict[str, str] | None = None,
    confirmed: bool = False,
    tweak: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate prompt packs for a story; register each as a `prompt_pack`
    artifact parented to the story."""
    story = prov_store.get_artifact(story_id)
    if story is None:
        raise KeyError(f"unknown story: {story_id}")
    _require_owner(story, user_id, "story")

    modalities = [m for m in (modalities or []) if m in packs.MODALITIES]
    if not modalities:
        raise ValueError(f"choose at least one of: {', '.join(packs.MODALITIES)}")

    # Graduated taste flow: the plan must be honored.
    stage = taste.get_stage(pstore, user_id)
    if stage in ("ask", "suggest"):
        if not answers:
            raise ValueError("taste answers are required before generating packs")
        taste.record_answers(pstore, user_id, answers)
    else:
        if not confirmed and not (tweak or "").strip():
            raise ValueError("confirm the proposal or send a tweak")
        taste.record_confirmation(pstore, user_id, tweak)

    style_anchors = taste.style_anchors_for_prompt(pstore, user_id)
    content = _story_content(story)

    results = []
    for modality in modalities:
        pack = packs.generate_pack(
            content, modality, style_anchors=style_anchors, api_key=api_key
        )
        pack_json = json.dumps(pack, sort_keys=True)
        artifact = prov_store.create_artifact(
            creator_user_id=user_id,
            custodian_user_id=user_id,
            title=pack["pack_title"],
            description=json.dumps({
                "modality": modality,
                "style_line": pack["style_line"],
                "preview": pack["prompts"][0][:200] if pack["prompts"] else "",
            }),
            source_hash=story.get("sha256"),
            modality="text",
            sha256=_text_sha256(pack_json),
            visibility="unlisted",
            remix_policy="open",
            imported=False,
            creator_declared=True,
            styled_by=None,  # style rental is later work (spec §9 step 10)
            variation_of=None,
        )
        prov_store.log_event(artifact["artifact_id"], "minted", actor_user_id=user_id)
        prov_store.add_link(artifact["artifact_id"], story_id, "linked")
        results.append({"artifact": artifact, "pack": pack})
    return {"packs": results}


def regen_pack(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    pack_id: str,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """'Give me another take' — a new pack artifact, same story parent,
    `variation_of` the previous pack."""
    pack_artifact = prov_store.get_artifact(pack_id)
    if pack_artifact is None:
        raise KeyError(f"unknown pack: {pack_id}")
    _require_owner(pack_artifact, user_id, "pack")
    parents = prov_store.parents_of(pack_id)
    if not parents:
        raise ValueError("pack has no parent story")
    story_id = parents[0]["parent_id"]
    story = prov_store.get_artifact(story_id)
    if story is None:
        raise KeyError("pack's parent story is gone")

    try:
        modality = json.loads(pack_artifact.get("description") or "{}").get("modality")
    except (json.JSONDecodeError, TypeError):
        modality = None
    if modality not in packs.MODALITIES:
        raise ValueError("pack artifact is not a prompt pack")

    style_anchors = taste.style_anchors_for_prompt(pstore, user_id)
    content = _story_content(story)
    pack = packs.generate_pack(
        content, modality, style_anchors=style_anchors,
        variation_of=pack_id, api_key=api_key,
    )
    pack_json = json.dumps(pack, sort_keys=True)
    artifact = prov_store.create_artifact(
        creator_user_id=user_id,
        custodian_user_id=user_id,
        title=pack["pack_title"],
        description=json.dumps({
            "modality": modality,
            "style_line": pack["style_line"],
            "preview": pack["prompts"][0][:200] if pack["prompts"] else "",
        }),
        source_hash=story.get("sha256"),
        modality="text",
        sha256=_text_sha256(pack_json),
        visibility="unlisted",
        remix_policy="open",
        imported=False,
        creator_declared=True,
        styled_by=None,
        variation_of=pack_id,
    )
    prov_store.log_event(artifact["artifact_id"], "minted", actor_user_id=user_id)
    prov_store.add_link(artifact["artifact_id"], story_id, "linked")
    return {"artifact": artifact, "pack": pack}


# -- quote cards ------------------------------------------------------------------


def make_quote_card(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    story_id: str,
    *,
    badge: bool = True,
) -> dict[str, Any]:
    """Render a quote card in-house and auto-mint it as a `quote_card`
    artifact parented to the story (no import step)."""
    story = prov_store.get_artifact(story_id)
    if story is None:
        raise KeyError(f"unknown story: {story_id}")
    _require_owner(story, user_id, "story")
    content = _story_content(story)
    if not content["key_line"]:
        raise ValueError("story has no key line to render")

    style_anchors = taste.style_anchors_for_prompt(pstore, user_id)

    # Two-pass when the badge is on: register first (fingerprint of the
    # unbadged card), then re-render with the badge encoding the real
    # artifact id and re-fingerprint. Both passes are PIL milliseconds.
    plain_png = quote_cards.render_quote_card(
        content["key_line"], title=content["title"],
        style_anchors=style_anchors, badge_url=None,
    )
    artifact = prov.register_artifact(
        prov_store,
        image_base64=base64.b64encode(plain_png).decode(),
        creator_user_id=user_id,
        title=f"Quote card — {content['title']}",
        description=json.dumps({"key_line": content["key_line"]}),
        archetype_cast=content["archetype_cast"],
        source_hash=story.get("sha256"),
        remix_policy="open",
    )
    image_b64 = base64.b64encode(plain_png).decode()
    if badge:
        badge_url = quote_cards.SHARE_URL_TEMPLATE.format(
            artifact_id=artifact["artifact_id"]
        )
        badged_png = quote_cards.render_quote_card(
            content["key_line"], title=content["title"],
            style_anchors=style_anchors, badge_url=badge_url,
        )
        fp = fingerprint_image(badged_png)
        artifact = prov_store.update_artifact(
            artifact["artifact_id"], phash=fp.phash, sha256=fp.sha256
        )
        image_b64 = base64.b64encode(badged_png).decode()

    prov_store.add_link(artifact["artifact_id"], story_id, "linked")
    return {
        "artifact": artifact,
        "image_base64": image_b64,
        "badge": badge,
    }


# -- standalone mint --------------------------------------------------------------


def standalone_mint(
    prov_store: ProvenanceStore,
    user_id: str,
    image_base64: str,
    title: str = "",
) -> dict[str, Any]:
    """Mint something with no journal parent. Returns the artifact plus the
    one anchoring question (asked once, skippable)."""
    result = prov.identify_upload(
        prov_store,
        image_base64=image_base64,
        user_id=user_id,
        title=title,
        claim_creator=True,
    )
    result["anchoring_question"] = ANCHORING_QUESTION
    return result


def anchor_standalone(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    user_id: str,
    artifact_id: str,
    *,
    journal_entry_id: str | None = None,
    micro_reflection: str | None = None,
) -> dict[str, Any]:
    """Answer the anchoring question: graft the artifact onto a journal
    entry, or turn a micro-reflection into one. No answer = skipped."""
    artifact = prov_store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    _require_owner(artifact, user_id, "artifact")

    if journal_entry_id:
        entry = pstore.get_entry(journal_entry_id)
        if entry is None:
            raise KeyError(f"unknown journal entry: {journal_entry_id}")
        if entry["user_id"] != user_id:
            raise PermissionError("not your journal entry")
        if not entry.get("artifact_id"):
            raise ValueError("journal entry has no registry artifact")
        link = prov_store.add_link(artifact_id, entry["artifact_id"], "linked")
        return {"anchored": True, "entry_id": journal_entry_id, "link": link}

    if (micro_reflection or "").strip():
        created = create_journal_entry(
            pstore, prov_store, user_id, micro_reflection.strip()
        )
        entry = created["entry"]
        link = prov_store.add_link(artifact_id, entry["artifact_id"], "linked")
        return {
            "anchored": True,
            "entry_id": entry["entry_id"],
            "entry": entry,
            "link": link,
            "suggestion": created["suggestion"],
        }

    return {"anchored": False}
