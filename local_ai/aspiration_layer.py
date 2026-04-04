"""
Aspiration layer: bounded aspiration_signal derivation, signal intake (phased),
deterministic invocation policy, and compact prompt blocks for council / core profile.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from local_ai.council_preflight import CouncilPreflight

_ASPIRATION_MARKER = "ASPIRATION ORIENTATION (user-stated; bounded):"
_SHADOW_INSTRUCTION_PREFIX = (
    "Integrate the following adaptation naturally into the flow of conversation "
    "without referencing these instructions explicitly."
)
_MAX_ORIENTATION_CHARS = 500
_MAX_CALIBRATION_CHARS = 380
_MAX_TOTAL_CHARS = 780
_PROPOSAL_MIN_CONFIDENCE = 0.75
_TIME_DECAY_LAMBDA_PER_DAY = 0.1


def aspiration_profile_enabled() -> bool:
    return os.getenv("ATRIA_ASPIRATION_PROFILE_ENABLED", "1").strip().lower() not in ("0", "false", "off")


def aspiration_inference_enabled() -> bool:
    return os.getenv("ATRIA_ASPIRATION_INFERENCE_ENABLED", "1").strip().lower() not in ("0", "false", "off")


def aspiration_guidance_injection_enabled() -> bool:
    return os.getenv("ATRIA_ASPIRATION_GUIDANCE_INJECTION_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _clip(s: str, n: int) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_dt(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _days_since(ts: datetime | None) -> float:
    if ts is None:
        return 0.0
    d = (_now_utc() - ts).total_seconds() / 86400.0
    return max(0.0, d)


def _smart_truncate_block(text: str, max_chars: int) -> str:
    """Hard cap with compact summarization (not raw cut)."""
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return _clip(t, max_chars)
    head = lines[0]
    bullets = [ln for ln in lines[1:] if ln.startswith("-")]
    if bullets:
        compact = [head]
        for b in bullets[:3]:
            compact.append(_clip(b, 120))
        compact.append("- (summarized for token hygiene)")
        candidate = "\n".join(compact).strip()
        if len(candidate) <= max_chars:
            return candidate
    return _clip(t, max_chars)


def _confidence_weighted_intake(
    *,
    profile_readiness: float,
    resonance_average: float | None,
    resonance_friction: bool,
    explicit_guidance_request: bool,
) -> tuple[float, list[str]]:
    """Phase-A intake weighting with human-readable basis lines."""
    basis: list[str] = []
    score = max(0.0, min(1.0, profile_readiness)) * 0.62
    basis.append(f"Profile completeness weight contributes {score:.2f} (Phase A).")
    if resonance_average is not None:
        ra = max(0.0, min(1.0, resonance_average))
        w = ra * 0.23
        score += w
        basis.append(f"Resonance average contributes {w:.2f} from score={ra:.2f}.")
    if resonance_friction:
        score += 0.07
        basis.append("Friction marker contributes +0.07 (resonance escalation/low ratings).")
    if explicit_guidance_request:
        score += 0.08
        basis.append("Explicit guidance request contributes +0.08.")
    return min(0.95, score), basis


def _detect_aspiration_conflicts(
    *,
    core_aim: str,
    near_term: str,
    anti_goals: str,
    resonance_pattern: dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    markers: list[str] = []
    basis: list[str] = []
    if anti_goals and near_term:
        aw = set(re.findall(r"[A-Za-z]{4,}", anti_goals.lower()))
        nw = set(re.findall(r"[A-Za-z]{4,}", near_term.lower()))
        overlap = aw & nw
        if overlap:
            markers.append("near_term_vs_anti_goals_term_overlap")
            basis.append(
                f"Conflict marker from overlap between near-term aspirations and anti-goals ({len(overlap)} shared terms)."
            )
    pat = resonance_pattern or {}
    low = int(pat.get("low_resonance_count") or 0) if isinstance(pat, dict) else 0
    high = int(pat.get("high_resonance_count") or 0) if isinstance(pat, dict) else 0
    esc = pat.get("escalation_signal") if isinstance(pat, dict) else None
    if low >= 3 and high <= low:
        markers.append("resonance_friction_against_stated_trajectory")
        basis.append(
            f"Derived from {low} low-resonance responses outweighing high-resonance responses ({high})."
        )
    if isinstance(esc, dict):
        try:
            cf = float(esc.get("confidence") or 0)
            lvl = int(esc.get("current_level") or 1)
            if cf >= 0.65 and lvl >= 3:
                markers.append("sustained_interaction_friction")
                basis.append(
                    f"Derived from escalation level {lvl} with {cf:.0%} confidence; potential tension with stated direction."
                )
        except (TypeError, ValueError):
            pass
    if core_aim and low >= 3:
        basis.append("Core aim is present while response friction persists; flag for guided clarification.")
    core_l = core_aim.lower()
    if ("decis" in core_l or "decision" in core_l) and low >= 3:
        markers.append("resonance_friction_against_decisiveness")
        basis.append("Stated decisiveness aim conflicts with repeated low-resonance interaction pattern.")
    return markers[:8], basis[:8]


def _directive_soft_exit_requested(preflight: CouncilPreflight | None) -> bool:
    if preflight is None:
        return False
    q = _s(preflight.user_question).lower()
    if not q:
        return False
    return any(
        x in q
        for x in (
            "stop forcing me",
            "don't force me",
            "i need to brainstorm",
            "just brainstorming",
            "not ready to decide",
            "don't make me choose",
        )
    )


def _action_directive_for_signal(
    *,
    conflict_markers: list[str],
    style_key: str,
    soft_exit: bool,
) -> str | None:
    if soft_exit:
        return "User requested brainstorming latitude. Suspend forced-choice directives temporarily; keep guidance exploratory."
    rules: dict[tuple[str, str], str] = {
        (
            "resonance_friction_against_decisiveness",
            "challenge",
        ): "Limit to 2 options and require a selection before proceeding.",
        (
            "resonance_friction_against_decisiveness",
            "direct",
        ): "Ask for a single final call now; defer additional options until after execution begins.",
        (
            "sustained_interaction_friction",
            "structured",
        ): "Use one commitment checkpoint with explicit done criteria before new ideation.",
    }
    for marker in conflict_markers:
        for (m, sk), directive in rules.items():
            if marker == m and style_key == sk:
                return directive
    if "resonance_friction_against_stated_trajectory" in conflict_markers and style_key == "challenge":
        return "Shift to challenge-forward mode: ask for a concrete commitment and hold option-sprawl."
    return None


def derive_aspiration_signal(user_id: str) -> dict[str, Any]:
    """
    Operational aspiration_signal from explicit profile + bounded Phase-A signals (resonance summary).
    """
    from local_ai.vision_execution.storage import get_aspiration_profile, get_resonance_pattern

    uid = (user_id or "").strip()
    prof = get_aspiration_profile(uid) if uid else None
    basis: list[str] = []
    conflict_markers: list[str] = []

    core = _s(prof.get("core_aim")) if prof else ""
    edge = _s(prof.get("current_edge")) if prof else ""
    near = _s(prof.get("near_term_aspirations")) if prof else ""
    anti = _s(prof.get("anti_goals")) if prof else ""
    gd: list[str] = []
    if prof and isinstance(prof.get("growth_domains"), list):
        gd = [str(x).strip() for x in prof["growth_domains"][:12] if str(x).strip()]

    if core:
        basis.append("Explicit core aim from aspiration profile.")
    elif near:
        basis.append("Near-term aspirations used as primary vector (core aim empty).")
    elif gd:
        basis.append("Growth domains used as orientation (other fields sparse).")
    else:
        basis.append("Aspiration profile sparse; confidence capped low.")

    dominant = core or _clip(near, 200) or (gd[0] if gd else "")
    if not dominant:
        dominant = "(not specified)"

    active_edge = edge or (gd[0] if gd else "") or _clip(near, 120)

    filled = 0
    total = 6
    for bit in (core, edge, near, anti, prof.get("current_obstacles") if prof else "", " ".join(gd)):
        if _s(bit):
            filled += 1
    readiness = min(1.0, 0.25 + (filled / total) * 0.75)

    pat = get_resonance_pattern(uid, limit=120) if uid else {}
    esc = pat.get("escalation_signal") if isinstance(pat, dict) else None
    low_res_friction = False
    if isinstance(esc, dict):
        try:
            cf = float(esc.get("confidence") or 0)
            lvl = int(esc.get("current_level") or 1)
            if cf > 0.45 and lvl >= 3:
                low_res_friction = True
                basis.append("Resonance escalation suggests interaction friction (bounded read).")
        except (TypeError, ValueError):
            pass
    if isinstance(pat, dict) and int(pat.get("low_resonance_count") or 0) >= 3:
        low_res_friction = True
        basis.append("Several low resonance ratings observed (bounded read).")

    avg_f: float | None = None
    try:
        avg = pat.get("average_score") if isinstance(pat, dict) else None
        avg_f = float(avg) if avg is not None else None
    except (TypeError, ValueError):
        avg_f = None

    derived_confidence, weighted_basis = _confidence_weighted_intake(
        profile_readiness=readiness,
        resonance_average=avg_f,
        resonance_friction=low_res_friction,
        explicit_guidance_request=False,
    )
    basis.extend(weighted_basis)
    updated_at = _parse_iso_dt(prof.get("updated_at")) if isinstance(prof, dict) else None
    age_days = _days_since(updated_at)
    decay = math.exp(-_TIME_DECAY_LAMBDA_PER_DAY * age_days)
    derived_confidence *= decay
    if age_days > 0.5:
        basis.append(
            f"Time decay applied: exp(-{_TIME_DECAY_LAMBDA_PER_DAY:.2f} * {age_days:.1f}d) = {decay:.2f}."
        )
    conflict_markers, conflict_basis = _detect_aspiration_conflicts(
        core_aim=core,
        near_term=near,
        anti_goals=anti,
        resonance_pattern=pat if isinstance(pat, dict) else None,
    )
    basis.extend(conflict_basis)

    confidence = derived_confidence
    if conflict_markers:
        confidence *= 0.85
    if not core and not gd:
        confidence = min(confidence, 0.42)
    if low_res_friction:
        confidence = min(confidence, 0.88)

    return {
        "dominant_aspiration_vector": dominant,
        "active_growth_edge": active_edge or "(not specified)",
        "guidance_readiness": round(min(1.0, readiness), 3),
        "aspiration_conflict_markers": conflict_markers[:8],
        "confidence": round(max(0.05, min(0.95, confidence)), 3),
        "basis": basis[:12],
        "phase": "A",
        "resonance_friction_hint": bool(low_res_friction),
        "time_decay_factor": round(decay, 4),
        "signal_age_days": round(age_days, 3),
    }


def _surface_relevant_for_aspiration(preflight: CouncilPreflight | None) -> bool:
    if preflight is None:
        return False
    surf = (_s(preflight.active_surface) or "").lower()
    if surf in ("core_profile", "vision_execution", "perspectives", "workspace", "home"):
        return True
    wml = (_s(preflight.workspace_mode_label) or "").lower()
    if "council" in wml or "reflect" in wml or "zenaf" in wml:
        return True
    br = (_s(preflight.breadcrumb) or "").lower()
    if "foundation" in br:
        return True
    return False


def should_invoke_aspirational_guidance(
    *,
    user_id: str,
    preflight: CouncilPreflight | None,
    explicit_guidance_request: bool = False,
) -> tuple[bool, list[str], float]:
    """
    Deterministic invocation: permissions + profile toggles + surface + confidence floor.
    Returns (invoke, reason_codes, confidence).
    """
    from local_ai.vision_execution.storage import get_aspiration_profile, user_permission_enabled

    uid = (user_id or "").strip()
    reasons: list[str] = []
    if not uid:
        return False, ["no_user"], 0.0
    if not aspiration_guidance_injection_enabled():
        return False, ["aspiration_guidance_feature_off"], 0.0
    if not user_permission_enabled(uid, "aspiration_use_in_guidance"):
        return False, ["permission_aspiration_use_denied"], 0.0

    prof = get_aspiration_profile(uid)
    sig = derive_aspiration_signal(uid)
    conf = float(sig.get("confidence") or 0)

    eg = explicit_guidance_request
    if preflight and getattr(preflight, "explicit_guidance_request", False):
        eg = True
    if eg:
        reasons.append("explicit_guidance_request")

    has_aspiration_content = bool(
        prof
        and (
            _s(prof.get("core_aim"))
            or _s(prof.get("near_term_aspirations"))
            or (isinstance(prof.get("growth_domains"), list) and len(prof.get("growth_domains") or []) > 0)
        )
    )
    if has_aspiration_content:
        reasons.append("aspiration_present")
    elif eg:
        reasons.append("infer_on_explicit_request_only")
    else:
        return False, ["no_aspiration_content"], conf

    use_flag = bool(prof and prof.get("use_in_guidance"))
    if use_flag:
        reasons.append("use_in_guidance_enabled")
    elif eg:
        reasons.append("explicit_request_overrides_toggle")
    else:
        return False, ["use_in_guidance_off"], conf

    if conf < 0.22 and not eg:
        return False, ["low_confidence_omit", *reasons], conf

    surface_ok = _surface_relevant_for_aspiration(preflight) or eg
    if surface_ok:
        reasons.append("relevant_surface_or_mode")
    else:
        return False, ["surface_not_relevant", *reasons], conf

    # Resonance / developmental utility: optional boost — require some client developmental payload or friction hint
    dg = preflight.developmental_guidance if preflight else None
    has_dev = isinstance(dg, dict) and bool(dg)
    surf = (_s(preflight.active_surface) or "").lower() if preflight else ""
    if has_dev:
        reasons.append("developmental_guidance_present")
    elif sig.get("resonance_friction_hint"):
        reasons.append("resonance_friction")
    elif surf in ("core_profile", "vision_execution", "perspectives", "workspace", "home"):
        reasons.append("surface_utility")
    elif eg:
        reasons.append("explicit_request")
    else:
        return False, ["utility_gate_not_met", *reasons], conf

    return True, reasons, conf


def format_aspiration_augmentation_block(
    user_id: str,
    *,
    preflight: CouncilPreflight | None = None,
    explicit_guidance_request: bool = False,
) -> tuple[str | None, dict[str, Any]]:
    """
    Compact bounded blocks for council context. Returns (text_or_none, explainability_dict).
    """
    from local_ai.vision_execution.storage import get_aspiration_profile

    uid = (user_id or "").strip()
    explain: dict[str, Any] = {"reason_codes": [], "confidence": 0.0, "blocks_included": []}
    if not uid:
        return None, explain

    invoke, reasons, conf = should_invoke_aspirational_guidance(
        user_id=uid,
        preflight=preflight,
        explicit_guidance_request=explicit_guidance_request,
    )
    explain["reason_codes"] = reasons
    explain["confidence"] = conf
    if not invoke:
        return None, explain

    prof = get_aspiration_profile(uid) or {}
    sig = derive_aspiration_signal(uid)
    gp = prof.get("guidance_preferences") if isinstance(prof.get("guidance_preferences"), dict) else {}
    style = _s(gp.get("style") or gp.get("guidance_style") or "")
    style_key = style.lower().replace("-", "_").replace(" ", "_")
    style_map = {
        "socratic": "Socratic questioning over directive advice",
        "socratic_questioning": "Socratic questioning over directive advice",
        "direct": "Direct advice and clear next moves",
        "structured": "Structured prompts with concrete checkpoints",
        "gentle": "Gentle reflection before challenge",
        "challenge": "Challenge-forward prompts when confidence is high",
    }
    style_line = style_map.get(style_key, style or "Adaptive style (default)")

    orient_lines = [
        f"- Core aim: {_clip(_s(prof.get('core_aim')), 200) or '(not specified)'}",
        f"- Active edge: {_clip(_s(prof.get('current_edge')), 160) or '(not specified)'}",
    ]
    if style_line:
        orient_lines.append(f"- Preferred guidance style: {_clip(style_line, 120)}")
    orient_lines.append(f"- Obstacle now: {_clip(_s(prof.get('current_obstacles')), 160) or '(not specified)'}")

    oblock = _ASPIRATION_MARKER + "\n" + "\n".join(orient_lines)
    oblock = _smart_truncate_block(oblock, _MAX_ORIENTATION_CHARS)
    explain["blocks_included"].append("aspirational_orientation")

    esc = None
    if isinstance(sig, dict) and sig.get("resonance_friction_hint"):
        esc = "Challenge level: friction signals suggest leaning slightly gentler unless user asks otherwise."
    cal_lines = [
        f"- Dominant vector (summary): {_clip(str(sig.get('dominant_aspiration_vector')), 200)}",
    ]
    directive = _action_directive_for_signal(
        conflict_markers=list(sig.get("aspiration_conflict_markers") or []),
        style_key=style_key if style_key in ("socratic", "direct", "structured", "gentle", "challenge") else "direct",
        soft_exit=_directive_soft_exit_requested(preflight),
    )
    if directive:
        cal_lines.append(f"- [STRATEGIC ADAPTATION: {directive}]")
        explain["directive"] = directive
    cal_lines.append(f"- Guidance style calibration: {style_line}")
    if esc:
        cal_lines.append(_clip(esc, 200))
    cblock = (
        "INTERACTION CALIBRATION (aspiration + signals; bounded):\n"
        + _SHADOW_INSTRUCTION_PREFIX
        + "\n"
        + "\n".join(cal_lines)
    )
    cblock = _smart_truncate_block(cblock, _MAX_CALIBRATION_CHARS)
    explain["blocks_included"].append("interaction_calibration")

    merged = oblock + "\n\n" + cblock
    if len(merged) > _MAX_TOTAL_CHARS:
        merged = _smart_truncate_block(merged, _MAX_TOTAL_CHARS)
    explain["augmentation_chars"] = len(merged)
    return merged, explain


def maybe_core_profile_aspiration_block(user_id: str) -> str:
    """Single bounded block for core profile Zenaf conversation (no CouncilPreflight)."""
    from local_ai.council_preflight import CouncilPreflight

    uid = (user_id or "").strip()
    if not uid:
        return ""
    pf = CouncilPreflight(active_surface="core_profile")
    text, _exp = format_aspiration_augmentation_block(uid, preflight=pf, explicit_guidance_request=False)
    if not text:
        return ""
    return text.strip() + "\n\n"


def get_aspiration_inference_proposals(user_id: str) -> list[dict[str, Any]]:
    """
    Bounded suggestive proposals (not canonical). Phase A+B heuristics; persisted as pending rows optionally.
    """
    from local_ai.vision_execution import storage as St

    uid = (user_id or "").strip()
    if not uid or not aspiration_inference_enabled():
        return []
    if not St.user_permission_enabled(uid, "aspiration_infer_suggestions"):
        return []
    prof = St.get_aspiration_profile(uid)
    if prof and not prof.get("allow_inference"):
        return []

    proposals: list[dict[str, Any]] = []
    pat = St.get_resonance_pattern(uid, limit=200)
    esc = pat.get("escalation_signal") if isinstance(pat, dict) else {}
    approach = str(esc.get("recommended_approach") or "") if isinstance(esc, dict) else ""

    total = int(pat.get("total_ratings") or 0) if isinstance(pat, dict) else 0
    high = int(pat.get("high_resonance_count") or 0) if isinstance(pat, dict) else 0
    avg = pat.get("average_score") if isinstance(pat, dict) else None
    try:
        avg_f = float(avg) if avg is not None else None
    except (TypeError, ValueError):
        avg_f = None
    # Significant interaction gate: core profile-like depth approximated by enough rated turns.
    significant_interaction = (total >= 10 and (high >= 6 or (avg_f is not None and avg_f >= 0.65))) or (
        isinstance(esc, dict)
        and float(esc.get("confidence") or 0) >= 0.75
        and int(esc.get("current_level") or 0) >= 3
        and total >= 6
    )
    if not significant_interaction:
        St.append_aspiration_inference_log(
            uid,
            {
                "event": "proposal_scan_skipped",
                "reason": "insufficient_significant_interaction",
                "total_ratings": total,
                "high_resonance_count": high,
                "average_score": avg_f,
            },
        )
        return []

    core_empty = not _s(prof.get("core_aim")) if prof else True
    if core_empty:
        proposals.append(
            {
                "theme": "Name a single core aim",
                "detail": "One sentence that states what 'winning' looks like for you in the next chapter.",
                "basis": ["Profile core aim is empty (Phase A heuristic)."],
                "phase": "A",
                "confidence": 0.86,
            }
        )

    if isinstance(esc, dict) and approach and approach != "exploration":
        proposals.append(
            {
                "theme": "Interaction calibration",
                "detail": f"Observed pattern suggests '{approach}' may fit; confirm or correct.",
                "basis": ["Resonance escalation summary (bounded, not diagnostic)."],
                "phase": "A",
                "confidence": min(0.92, max(0.0, float(esc.get("confidence") or 0.0))),
            }
        )

    # Phase B (controlled): council outcome patterns — placeholder hook; keep empty unless extended later.
    proposals.append(
        {
            "theme": "Tighten growth domains",
            "detail": "Pick 2–3 growth domains you want the system to weigh more heavily.",
            "basis": ["Controlled Phase B suggestion slot (no extra telemetry in v1)."],
            "phase": "B",
            "confidence": 0.72,
        }
    )

    # De-dupe against dismissed themes
    dismissed = {
        _s(r.get("theme"))
        for r in St.list_aspiration_proposals(uid, status="dismissed")
        if isinstance(r, dict)
    }
    out: list[dict[str, Any]] = []
    for p in proposals[:5]:
        th = _s(p.get("theme"))
        if th and th in dismissed:
            continue
        c = float(p.get("confidence") or 0.0)
        if c < _PROPOSAL_MIN_CONFIDENCE:
            St.append_aspiration_inference_log(
                uid,
                {
                    "event": "proposal_filtered_low_confidence",
                    "theme": th,
                    "confidence": c,
                    "basis": p.get("basis"),
                },
            )
            continue
        out.append(p)
    return out[:3]


def sync_aspiration_proposals_to_storage(user_id: str) -> list[dict[str, Any]]:
    """Insert pending proposals that are not already pending (by theme)."""
    from local_ai.vision_execution import storage as St

    uid = (user_id or "").strip()
    if not uid:
        return []
    pending = St.list_aspiration_proposals(uid, status="pending")
    pending_themes = {_s(p.get("theme")) for p in pending}
    fresh = get_aspiration_inference_proposals(uid)
    for p in fresh:
        th = _s(p.get("theme"))
        if not th or th in pending_themes:
            continue
        St.create_aspiration_proposal(
            uid,
            theme=th,
            detail=_s(p.get("detail")),
            basis=list(p.get("basis") or []) if isinstance(p.get("basis"), list) else [],
        )
        pending_themes.add(th)
    St.append_aspiration_inference_log(uid, {"proposals": fresh, "source": "sync"})
    return St.list_aspiration_proposals(uid, status="pending")


def accept_aspiration_proposal(user_id: str, proposal_id: str) -> dict[str, Any] | None:
    """Mark accepted and return proposal; UI performs explicit PATCH profile integration."""
    from local_ai.vision_execution import storage as St

    uid = (user_id or "").strip()
    pid = (proposal_id or "").strip()
    if not uid or not pid:
        return None
    conn = St.get_connection()
    row = conn.execute(
        "SELECT * FROM aspiration_proposals WHERE user_id = ? AND id = ? AND status = 'pending'",
        (uid, pid),
    ).fetchone()
    if not row:
        return None
    St.set_aspiration_proposal_status(uid, pid, "accepted")
    return {
        "id": row["id"],
        "theme": _s(row["theme"]),
        "detail": _s(row["detail"]),
        "status": "accepted",
    }

