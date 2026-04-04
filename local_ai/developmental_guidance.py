"""
Developmental guidance read model: JSON contract + non-diagnostic packet formatting.

Runtime-only interpretive layer: hypotheses and axes are not persisted, not a user profile,
and not trait labels. Server accepts a client-assembled payload under
council_preflight.developmental_guidance and appends a bounded block to enriched council
context (see council_preflight.build_enriched_council_context).

Interpretive axis *names* and *tilt* strings are canonical in
frontend/src/developmentalGuidance/interpretive_axis_copy.json; this module loads that file
from the repo (with an inline fallback). A future versioned judgment-profile artifact would
be a separate design — not raw persistence of this wording.

Hypotheses are advisory only; language avoids diagnosis.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEVELOPMENTAL_GUIDANCE_MARKER = "DEVELOPMENTAL GUIDANCE (hypotheses — uncertain, not diagnostic):"

_VALID_KINDS = frozenset({"strength", "friction", "edge", "challenge_style"})
_VALID_CONFIDENCE = frozenset({"low", "medium", "high"})
_VALID_STYLES = frozenset(
    {
        "more_structure",
        "more_ambiguity_tolerance",
        "more_accountability",
        "neutral",
    }
)

_PACKET_MAX_CHARS = 1200

# Inline fallback if JSON is missing (e.g. unusual deploy layout). Must match
# frontend/src/developmentalGuidance/interpretive_axis_copy.json for axisNames/tilts/labels —
# pytest enforces parity: tests/test_interpretive_axis_copy_parity.py
_INTERPRETIVE_AXIS_COPY_FALLBACK: dict[str, Any] = {
    "axisNames": {
        "clarityAmbiguity": "clarity ↔ ambiguity",
        "actionIdeation": "action ↔ ideation",
        "followThroughDropoff": "follow-through ↔ drop-off",
        "structureExploration": "structure ↔ exploration",
        "integrationFragmentation": "integration ↔ fragmentation",
    },
    "tilts": {
        "soilClarity": "tension leaning toward ambiguity in how this focus is bounded and named",
        "soilClarityMultiGapSuffix": (
            " (several map gaps at once — one possible read is that the picture is still "
            "open-ended; not a verdict about you)"
        ),
        "structureExplorationSoil": (
            "tilt toward exploratory framing until scope and acceptance criteria firm up"
        ),
        "waterFollowThrough": "tilt toward drop-off in visible ownership and follow-through cadence",
        "fruitActionIdeation": "tilt toward ideation relative to tangible output and proof so far",
        "structureFromStyle": "tentative read: a bit more structure might reduce thrash — advisory only",
        "ambiguityToleranceStyle": (
            "holding ambiguity a little longer may match how this focus is still forming — tentative"
        ),
        "traceDismissed": (
            "in this session only, answers and reactions may not be lining up — fragmentation "
            "as a hypothesis, not a judgment"
        ),
        "traceWeakIntegrity": (
            "synthesis grounding has looked uneven in recent runs — threads may feel pulled apart "
            "as one possible read, not as fact"
        ),
    },
    "labels": {
        "packetSectionTitle": (
            "Interpretive axes (ephemeral — language helpers for this packet only; not scores, "
            "traits, or stored profile):"
        ),
        "panelSectionTitle": "Interpretive axes — this moment only; not stored",
        "guideSentenceLeadIn": "Hypothesis-only phrasing (not a trait or score):",
        "panelCollapsibleTitle": "Tentative read (council context)",
        "panelIntro": (
            "Hypotheses for this moment only — nothing here is saved as your profile or traits."
        ),
    },
}


def _load_interpretive_axis_copy() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "developmentalGuidance"
        / "interpretive_axis_copy.json"
    )
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if (
            isinstance(data, dict)
            and isinstance(data.get("axisNames"), dict)
            and isinstance(data.get("tilts"), dict)
            and isinstance(data.get("labels"), dict)
        ):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return _INTERPRETIVE_AXIS_COPY_FALLBACK


_INTERPRETIVE_AXIS_COPY: dict[str, Any] = _load_interpretive_axis_copy()
_ALLOWED_AXIS_NAMES = frozenset(_INTERPRETIVE_AXIS_COPY["axisNames"].values())


def hypothesis_intro_phrase() -> str:
    return "One possible read (uncertain):"


def _cap_confidence(c: str | None) -> str:
    if not c:
        return "low"
    x = str(c).strip().lower()
    if x not in _VALID_CONFIDENCE:
        return "low"
    # Plan: cap to medium unless repeated evidence across sources — v1 client sends medium at most.
    if x == "high":
        return "medium"
    return x


def _clean_str(v: Any, max_len: int) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:max_len] if len(s) > max_len else s


def _normalize_axes_from_raw(ax_raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(ax_raw, list):
        return out
    seen: set[str] = set()
    for item in ax_raw[:8]:
        if not isinstance(item, dict):
            continue
        name = _clean_str(item.get("name"), 80)
        tilt = _clean_str(item.get("tilt"), 200)
        if not name or not tilt:
            continue
        if name not in _ALLOWED_AXIS_NAMES:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "tilt": tilt})
        if len(out) >= 6:
            break
    return out


def _bases_blob(hypotheses: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for h in hypotheses:
        b = h.get("basis")
        if isinstance(b, list):
            parts.extend(str(x) for x in b)
    return " ".join(parts).lower()


def _safe_council_runs(signals_summary: dict[str, Any]) -> int:
    """Bounded count from client signals_summary; avoids trace-derived axes on N=1."""
    v = signals_summary.get("council_runs_in_window")
    if v is None or isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return max(0, v)
    if isinstance(v, float):
        return max(0, int(v))
    try:
        return max(0, int(str(v).strip()))
    except ValueError:
        return 0


def _derive_interpretive_axes(
    hypotheses: list[dict[str, Any]],
    signals_summary: dict[str, Any],
    suggested_guidance_style: str,
) -> list[dict[str, str]]:
    """
    Ephemeral interpretive axes from normalized signals only (no DB, no numeric scores).
    Agency ↔ receptivity: only nudges multi-gap clarity wording — not a surfaced polarity line.
    Canonical strings: interpretive_axis_copy.json (mirrored by interpretiveAxes.ts).
    Trace-derived integration axes require council_runs_in_window >= 2.
    """
    copy = _INTERPRETIVE_AXIS_COPY
    nm: dict[str, Any] = copy["axisNames"]
    tilts: dict[str, Any] = copy["tilts"]
    axes: list[dict[str, str]] = []
    seen: set[str] = set()

    def push(name: str, tilt: str) -> None:
        t = (tilt or "").strip()
        if not t or name in seen or len(axes) >= 6:
            return
        seen.add(name)
        if len(t) > 200:
            t = t[:197].rstrip() + "…"
        axes.append({"name": name, "tilt": t})

    missing_s = str(signals_summary.get("map_missing_dimensions") or "").lower()
    has_soil = "soil" in missing_s
    has_water = "water" in missing_s
    has_fruit = "fruit" in missing_s
    multi_gap = sum(1 for x in (has_soil, has_water, has_fruit) if x) >= 2

    if has_soil:
        clarity = str(tilts.get("soilClarity") or "")
        if multi_gap:
            clarity += str(tilts.get("soilClarityMultiGapSuffix") or "")
        push(str(nm.get("clarityAmbiguity") or ""), clarity)
        push(str(nm.get("structureExploration") or ""), str(tilts.get("structureExplorationSoil") or ""))
    if has_water:
        push(str(nm.get("followThroughDropoff") or ""), str(tilts.get("waterFollowThrough") or ""))
    if has_fruit:
        push(str(nm.get("actionIdeation") or ""), str(tilts.get("fruitActionIdeation") or ""))

    if suggested_guidance_style == "more_structure" and not has_soil:
        push(str(nm.get("structureExploration") or ""), str(tilts.get("structureFromStyle") or ""))
    if suggested_guidance_style == "more_ambiguity_tolerance":
        push(str(nm.get("clarityAmbiguity") or ""), str(tilts.get("ambiguityToleranceStyle") or ""))

    council_runs = _safe_council_runs(signals_summary)
    bb = _bases_blob(hypotheses)
    if council_runs >= 2 and "user_outcome_dismissed" in bb:
        push(str(nm.get("integrationFragmentation") or ""), str(tilts.get("traceDismissed") or ""))
    if council_runs >= 2 and "weak_or_unreliable" in bb:
        push(str(nm.get("integrationFragmentation") or ""), str(tilts.get("traceWeakIntegrity") or ""))

    return axes[:6]


def normalize_developmental_guidance_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate and return a JSON-serializable dict safe to log and echo in prompts.
    Returns None if there is nothing meaningful to show.

    Runtime-only: nothing here is written to DB or treated as durable user state.
    Interpretive axes use strings from interpretive_axis_copy.json (see module docstring).
    """
    if not raw or not isinstance(raw, dict):
        return None

    as_of = _clean_str(raw.get("as_of"), 64)
    if not as_of:
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence_refs: list[dict[str, str]] = []
    er = raw.get("evidence_refs")
    if isinstance(er, list):
        for item in er[:24]:
            if not isinstance(item, dict):
                continue
            ref: dict[str, str] = {}
            for k in ("source_type", "source_id_or_key", "excerpt_or_hash"):
                v = _clean_str(item.get(k), 240)
                if v:
                    ref[k] = v
            if ref:
                evidence_refs.append(ref)

    signals_summary: dict[str, Any] = {}
    ss = raw.get("signals_summary")
    if isinstance(ss, dict) and ss:
        # Shallow copy allowed keys only (avoid huge blobs).
        for k, v in list(ss.items())[:32]:
            ks = _clean_str(k, 80)
            if not ks:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                signals_summary[ks] = v
            elif isinstance(v, list) and len(v) <= 24:
                signals_summary[ks] = v[:24]
            elif isinstance(v, dict) and len(v) <= 24:
                signals_summary[ks] = {str(a)[:80]: b for a, b in list(v.items())[:24]}

    hypotheses: list[dict[str, Any]] = []
    hy = raw.get("hypotheses")
    if isinstance(hy, list):
        for h in hy[:8]:
            if not isinstance(h, dict):
                continue
            kind = _clean_str(h.get("kind"), 32)
            if kind and kind not in _VALID_KINDS:
                kind = "friction"
            statement = _clean_str(h.get("statement"), 400)
            if not statement:
                continue
            basis_raw = h.get("basis")
            basis: list[str] = []
            if isinstance(basis_raw, list):
                for b in basis_raw[:8]:
                    bb = _clean_str(b, 160)
                    if bb:
                        basis.append(bb)
            hypotheses.append(
                {
                    "kind": kind or "friction",
                    "statement": statement,
                    "confidence": _cap_confidence(_clean_str(h.get("confidence"), 16)),
                    "basis": basis,
                }
            )

    wgf_norm: dict[str, Any] | None = None
    wgf_raw = raw.get("work_guidance_frame")
    if isinstance(wgf_raw, dict):
        stage = _clean_str(wgf_raw.get("stage"), 16)
        pq = _clean_str(wgf_raw.get("primary_question"), 500)
        if stage in ("seed", "tree", "branch") and pq:
            wgf_norm = {"stage": stage, "primary_question": pq}
            al = _clean_str(wgf_raw.get("assessment_line"), 400)
            if al:
                wgf_norm["assessment_line"] = al
            md = wgf_raw.get("missing_dimensions")
            if isinstance(md, list):
                dims: list[str] = []
                for x in md[:6]:
                    d = _clean_str(x, 16)
                    if d and d in ("water", "soil", "fruit"):
                        dims.append(d)
                if dims:
                    wgf_norm["missing_dimensions"] = dims

    style_raw = _clean_str(raw.get("suggested_guidance_style"), 48)
    suggested_guidance_style = (
        style_raw if style_raw and style_raw in _VALID_STYLES else "neutral"
    )

    esc_early = raw.get("escalation_signal")
    escalation_only_ok = (
        isinstance(esc_early, dict)
        and isinstance(esc_early.get("confidence"), (int, float))
        and float(esc_early["confidence"]) > 0.5
    )

    if not hypotheses and not signals_summary and not evidence_refs:
        if not escalation_only_ok and not wgf_norm:
            return None

    axes_out = _normalize_axes_from_raw(raw.get("axes"))
    if not axes_out:
        axes_out = _derive_interpretive_axes(hypotheses, signals_summary, suggested_guidance_style)

    out: dict[str, Any] = {
        "as_of": as_of,
        "evidence_refs": evidence_refs,
        "signals_summary": signals_summary,
        "hypotheses": hypotheses,
        "suggested_guidance_style": suggested_guidance_style,
    }
    if axes_out:
        out["axes"] = axes_out

    if wgf_norm:
        out["work_guidance_frame"] = wgf_norm

    esc_raw = raw.get("escalation_signal")
    if isinstance(esc_raw, dict):
        try:
            cl = int(esc_raw.get("current_level"))
            cf = float(esc_raw.get("confidence"))
            basis_esc = _clean_str(esc_raw.get("basis"), 400) or ""
            app = _clean_str(esc_raw.get("recommended_approach"), 32) or "exploration"
            if app in ("exploration", "recognition", "loop", "avoidance", "confrontation"):
                out["escalation_signal"] = {
                    "current_level": max(1, min(5, cl)),
                    "confidence": max(0.0, min(1.0, cf)),
                    "basis": basis_esc,
                    "recommended_approach": app,
                }
        except (TypeError, ValueError):
            pass

    return out


def attach_resonance_escalation_to_developmental_guidance(
    dg: dict[str, Any] | None,
    user_id: str | None,
) -> dict[str, Any] | None:
    """
    Merge ``escalation_signal`` from ``get_resonance_pattern`` into council preflight guidance.
    When guidance is absent, creates a minimal payload only if resonance confidence > 0.5.
    """
    uid = (user_id or "").strip()
    if not uid:
        return dg
    from local_ai.vision_execution.storage import get_resonance_pattern

    pat = get_resonance_pattern(uid, limit=200)
    esc = pat.get("escalation_signal")
    if not isinstance(esc, dict):
        return dg
    if dg is None:
        try:
            conf = float(esc.get("confidence") or 0)
        except (TypeError, ValueError):
            return dg
        if conf <= 0.5:
            return None
        return {
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evidence_refs": [],
            "signals_summary": {},
            "hypotheses": [],
            "suggested_guidance_style": "neutral",
            "escalation_signal": esc,
        }
    merged = dict(dg)
    merged["escalation_signal"] = esc
    return merged


_WS_RE = re.compile(r"\s+")


def format_developmental_guidance_packet_block(raw: dict[str, Any] | None) -> str | None:
    """Plain-text block for council Context packet; bounded length."""
    if not raw or not isinstance(raw, dict):
        return None
    norm = normalize_developmental_guidance_payload(raw)
    if not norm:
        return None

    lines: list[str] = [DEVELOPMENTAL_GUIDANCE_MARKER, ""]
    lines.append(
        "The following is assembled from recent app signals. Treat every line as a tentative "
        "hypothesis — not a fact, not a stored profile, and not an enduring label about the user."
    )
    lines.append(f"As of: {norm['as_of']}")

    style = norm.get("suggested_guidance_style")
    if style and style != "neutral":
        lines.append(f"Suggested tone (advisory): {style.replace('_', ' ')}")

    wgf = norm.get("work_guidance_frame")
    if isinstance(wgf, dict):
        pq = _clean_str(wgf.get("primary_question"), 500)
        if pq:
            lines.append("")
            lines.append(
                "WORK GUIDANCE LENS (Vision map / Vision & Execution scaffolding for the focused entity):"
            )
            lines.append(
                "When the question is about what remains to do, what is incomplete, weak dimensions, or the "
                "next shippable slice for this work, ground your opening inventory in the lines below **before** "
                "switching to a generic next-step menu."
            )
            stg = _clean_str(wgf.get("stage"), 16) or "?"
            lines.append(
                f"• Stage metaphor: {stg} (seed=idea, tree=initiative, branch=project; water=ownership/cadence, "
                "soil=scope/clarity, fruit=tangible output)."
            )
            lines.append(f"• Primary stage question (product guidance script): {pq}")
            al = _clean_str(wgf.get("assessment_line"), 400)
            if al:
                lines.append(f"• Stage assessment: {al}")
            md = wgf.get("missing_dimensions")
            if isinstance(md, list) and md:
                lines.append(
                    "• Heuristic weak dimensions (low scores in this packet's triad): "
                    + ", ".join(str(x) for x in md[:6])
                )

    ax_list = norm.get("axes") or []
    if ax_list:
        lines.append("")
        labels = _INTERPRETIVE_AXIS_COPY.get("labels") if isinstance(_INTERPRETIVE_AXIS_COPY.get("labels"), dict) else {}
        packet_axes_title = str(labels.get("packetSectionTitle") or "").strip() or (
            "Interpretive axes (ephemeral — language only; not scores, traits, or stored profile):"
        )
        lines.append(packet_axes_title)
        for ax in ax_list[:6]:
            nm = ax.get("name", "?")
            tl = ax.get("tilt", "")
            lines.append(f"• {nm} — {tl}")

    hy_list = norm.get("hypotheses") or []
    if hy_list:
        lines.append("")
        lines.append("Hypotheses:")
        for h in hy_list[:6]:
            st = h.get("statement", "")
            kind = h.get("kind", "")
            conf = h.get("confidence", "low")
            intro = hypothesis_intro_phrase()
            line = f"• ({kind}, confidence {conf}) {intro} {st}"
            lines.append(_WS_RE.sub(" ", line).strip())

    ev = norm.get("evidence_refs") or []
    if ev:
        lines.append("")
        lines.append("Evidence pointers (no raw prompts):")
        for e in ev[:8]:
            st = e.get("source_type", "?")
            sk = e.get("source_id_or_key", "")
            ex = e.get("excerpt_or_hash", "")
            bit = f"• {st}"
            if sk:
                bit += f" — {sk}"
            if ex:
                bit += f" — {ex[:120]}"
            lines.append(bit)

    sig = norm.get("signals_summary") or {}
    if sig:
        lines.append("")
        lines.append("Derived signal summary:")
        for k, v in list(sig.items())[:12]:
            lines.append(f"• {k}: {v}")

    esc = norm.get("escalation_signal")
    if isinstance(esc, dict):
        try:
            conf_esc = float(esc.get("confidence") or 0)
        except (TypeError, ValueError):
            conf_esc = 0.0
        if conf_esc > 0.5:
            app = str(esc.get("recommended_approach") or "exploration").strip()
            lines.append("")
            lines.append(
                f"Interaction calibration: {app} (based on observed response patterns, {conf_esc:.0%} confidence)"
            )

    text = "\n".join(lines).strip()
    if len(text) > _PACKET_MAX_CHARS:
        text = text[: _PACKET_MAX_CHARS - 1].rstrip() + "…"
    return text
