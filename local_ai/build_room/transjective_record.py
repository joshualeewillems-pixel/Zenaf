"""Transjective record (accepted schema contract, 2026-10-30, Joshua).

Pure, deterministic implementation of the accepted transjective schema
contract for build-room meetings. Stdlib only; no imports from meeting.py,
so this module cannot accidentally mutate the record it reads. It never
imports claim_standing.py either: registry standing (active / superseded /
withdrawn, same-author moves) is a DIFFERENT system from contract standing,
and the two must never be confused. Contract standing lives under its own
key (``contract_standing``) and never overwrites ``claim_standing``.

Inputs are plain dicts. Claims are claim dicts as produced by
``Claim.to_dict()`` (id, participant, phase, text, relationship,
relates_to, supersedes, withdraws, relationship_target,
relationship_targets, disposition, disposition_by, ...). All other
records (declarations, proposals, events, disagreements, corrections,
target states, exposure) are plain dicts in the shapes documented on each
function. Outputs are plain dicts.

Contract summary (the contract document is the authority; this module is
its mechanical enforcement):

- RelationshipDeclarations are per (source, target) pairs with a kind
  from the vocabulary; layer is always ``declared`` at capture.
- Target-state is exactly one of populated / declared-none / unknown /
  missing. Missing is an integrity violation for response/revision
  claims, never an acceptable completed state.
- Standing is derived from ordered DispositionEvent history only:
  initial ``open``; ``maintained`` only via an accepted
  defense/reaffirmation event; ``contested-standing`` only via the
  §4.3 structural bar. A proposal, label, or declaration never changes
  standing.
- Authority (§4.2): the only authorizers are ``convener-close``
  (executing a linked target-author acceptance, a cited meeting rule +
  superseding claim, or a structurally valid unresolved challenge) and
  ``user`` (product meetings only). In build-council context ``user``
  is NOT a valid authorizer.
- Validation (§7) reports errors E1–E14 and warnings W1–W4 and NEVER
  silently repairs data. Conformance = zero errors (warnings allowed).
- Old captures are adapted read-only (see :func:`adapt_claims_to_contract_inputs`):
  the adapter preserves evidence (in-text references, legacy
  dispositions) without mutating the original capture. Old captures are
  EXPECTED to be non-conformant (missing target-states, dispositions
  without authorizers) — that is correct behavior, not a bug.
"""

from __future__ import annotations

import re

__all__ = [
    "KIND_VOCABULARY",
    "STANDING_VALUES",
    "TARGET_STATES",
    "adapt_claims_to_contract_inputs",
    "build_transjective_record",
    "compute_target_states",
    "derive_contract_standing",
    "derive_revision_links",
    "validate_contract_record",
]

KIND_VOCABULARY = (
    "extends",
    "corrects",
    "challenges",
    "integrates",
    "endorses",
    "repeats",
    "defends",
    "requests-evidence",
    "other",
)

STANDING_VALUES = (
    "open",
    "revised",
    "withdrawn",
    "superseded",
    "maintained",
    "contested-standing",
)

TARGET_STATES = ("populated", "declared-none", "unknown", "missing")

# Score-ish keys: scores live in judge files only (E14). Claim dicts
# from Claim.to_dict() never carry these; their presence means a
# scored sheet (or similar) was passed in as a capture.
_SCORE_KEYS = ("grounding", "actionability", "useful_unique", "score", "usefulness")

_CLAIM_REF_RE = re.compile(r"C(\d+)")

# Adapter kind mapping for legacy relationship labels. Labels already in
# the vocabulary pass through; 'defended' is the past-tense form of
# 'defends'. Everything else maps to 'other' WITH the source label
# preserved in the note — the adapter preserves evidence, it never
# invents a kind the source did not state.
_LABEL_TO_KIND = {"defended": "defends"}


def _claim_number(claim_id: str) -> int | None:
    m = re.fullmatch(r"C(\d+)", (claim_id or "").strip())
    return int(m.group(1)) if m else None


def _is_claim_id(value: object) -> bool:
    return isinstance(value, str) and _claim_number(value) is not None


# ---------------------------------------------------------------------------
# Adapter (read-only): old claim fields -> contract inputs
# ---------------------------------------------------------------------------


def adapt_claims_to_contract_inputs(claims: list[dict]) -> dict:
    """Build contract inputs from existing claim fields, without mutation.

    Sources, in priority order per (source, target) pair (first wins):
    relationship_targets, relationship_target, relates_to,
    supersedes/withdraws fields, in-text C-id references. Structured
    targets use the source relationship label mapped through
    ``_LABEL_TO_KIND`` (unknown labels -> ``other`` with the label in
    the note); in-text references are always ``other`` with note
    "in-text reference". Dispositions on original claims are NOT
    events: they are preserved as ``legacy_dispositions`` observations
    for validation (E7, and E13 unless the shape matches an
    unauthorized revised/withdrawn event — see :func:`validate_contract_record`).

    Target-states: response/revision claims with declarations ->
    populated; without -> missing (the honest adapter output for old
    captures, which never recorded target-states); openings with
    declarations -> populated, without -> unknown with reason. The
    adapter never produces declared-none: it cannot attest author
    intent. Exposure: claims carrying a native ``exposure_ref``
    (Increment B) use it — ref from payload_ref/payload_hash,
    evidence passed through (unknown evidence values are normalized
    to ``absent``, fail-closed, so a malformed native record errors
    E12 rather than passing silently); claims without one get
    evidence ``absent`` (E12). Input claim dicts are never mutated
    (copies are not even needed: nothing here writes to them).
    """
    declarations: list[dict] = []
    legacy_dispositions: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_declaration(source: str, target: str, kind: str, note: str) -> None:
        if (source, target) in seen_pairs or source == target:
            return
        seen_pairs.add((source, target))
        declarations.append(
            {
                "source_claim": source,
                "target_claim": target,
                "kind": kind,
                "layer": "declared",
                "note": note,
            }
        )

    for claim in claims:
        cid = claim.get("id", "")
        if not cid:
            continue
        label = claim.get("relationship")
        kind = _LABEL_TO_KIND.get(label, label if label in KIND_VOCABULARY else "other")
        note = f"source relationship: {label}" if label else "relationship unstated in source"
        targets: list[str] = []
        for field in ("relationship_targets",):
            targets.extend(claim.get(field) or [])
        if not targets and claim.get("relationship_target"):
            targets.append(claim["relationship_target"])
        if not targets:
            targets.extend(claim.get("relates_to") or [])
        for target in targets:
            if _is_claim_id(target):
                add_declaration(cid, target, kind, note)
        for field in ("supersedes", "withdraws"):
            target = claim.get(field)
            if _is_claim_id(target):
                add_declaration(cid, target, "other", f"source field: {field}")
        text = claim.get("text", "") or ""
        for num in _CLAIM_REF_RE.findall(text):
            target = f"C{num}"
            if target != cid:
                add_declaration(cid, target, "other", "in-text reference")
        if claim.get("disposition") is not None:
            legacy_dispositions.append(
                {
                    "claim_id": cid,
                    "disposition": claim.get("disposition"),
                    "disposition_by": claim.get("disposition_by"),
                }
            )

    target_states = compute_target_states(claims, declarations)
    exposure: dict[str, dict] = {}
    for claim in claims:
        cid = claim.get("id", "")
        if not cid:
            continue
        ref = claim.get("exposure_ref")
        if isinstance(ref, dict):
            evidence = ref.get("evidence")
            if evidence not in ("available", "temporarily_unavailable",
                                "absent", "present"):
                evidence = "absent"
            exposure[cid] = {
                "ref": ref.get("payload_ref") or ref.get("payload_hash"),
                "evidence": evidence,
                "visible_ids": ref.get("visible_ids"),
            }
        else:
            exposure[cid] = {"ref": None, "evidence": "absent",
                             "visible_ids": None}
    return {
        "claims": claims,
        "declarations": declarations,
        "target_states": target_states,
        "legacy_dispositions": legacy_dispositions,
        "exposure": exposure,
    }


# ---------------------------------------------------------------------------
# Target-state computation
# ---------------------------------------------------------------------------


def compute_target_states(
    claims: list[dict],
    declarations: list[dict],
    explicit: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Compute one target-state per claim.

    ``explicit`` (claim id -> {"state", "set_by", "uncertainty_reason"})
    overrides the computed default when present — that is how a new
    capture records an author-set declared-none or a reasoned unknown.
    Defaults: response/revision claims with declarations -> populated,
    without -> missing; openings with declarations -> populated,
    without -> unknown ("opening claim; no targets declared").
    ``set_by`` defaults to "system" for computed states.
    """
    declared_targets: dict[str, int] = {}
    for decl in declarations:
        src = decl.get("source_claim", "")
        if src:
            declared_targets[src] = declared_targets.get(src, 0) + 1
    explicit = explicit or {}
    states: dict[str, dict] = {}
    for claim in claims:
        cid = claim.get("id", "")
        if not cid:
            continue
        if cid in explicit:
            entry = explicit[cid]
            states[cid] = {
                "state": entry.get("state"),
                "set_by": entry.get("set_by", "system"),
                "uncertainty_reason": entry.get("uncertainty_reason"),
            }
            continue
        has_targets = declared_targets.get(cid, 0) > 0
        phase = claim.get("phase", "")
        if has_targets:
            states[cid] = {"state": "populated", "set_by": "system",
                           "uncertainty_reason": None}
        elif phase in ("response", "revision"):
            states[cid] = {"state": "missing", "set_by": "system",
                           "uncertainty_reason": None}
        else:
            states[cid] = {"state": "unknown", "set_by": "system",
                           "uncertainty_reason": "opening claim; no targets declared"}
    return states


# ---------------------------------------------------------------------------
# Standing derivation + revision links (mechanical, from event history)
# ---------------------------------------------------------------------------


def derive_contract_standing(
    events: list[dict], claim_ids: list[str] | None = None
) -> dict[str, str]:
    """Derive current contract standing per claim from event history.

    Events are ordered by ``sequence`` (stable sort); the last event
    for a target wins. Claims with no events are ``open``. This
    function does NOT validate: invalid events still move the
    derivation, and validation (E7/E9) flags them separately. Standing
    is never read from anywhere else — in particular, never from
    registry ``claim_standing`` output or any stored standing field.
    """
    standing: dict[str, str] = {}
    if claim_ids:
        standing = {cid: "open" for cid in claim_ids}
    ordered = sorted(events, key=lambda e: e.get("sequence") if isinstance(e.get("sequence"), int) else 0)
    for event in ordered:
        target = event.get("target_claim", "")
        new = event.get("new_standing", "")
        if target and new in STANDING_VALUES:
            standing[target] = new
    return standing


def derive_revision_links(events: list[dict]) -> dict:
    """Derive revision_of / revised_by from revised events (latest wins).

    ``revision_of`` maps revision claim -> original claim;
    ``revised_by`` maps original claim -> revision claim. Both come
    from the single canonical revision event per pair; later revised
    events for the same target replace earlier ones in the derivation.
    ``conflicts`` lists revision claims cited for more than one target
    (informational: the contract assigns no error code to this alone).
    """
    ordered = sorted(events, key=lambda e: e.get("sequence") if isinstance(e.get("sequence"), int) else 0)
    revision_of: dict[str, str] = {}
    revised_by: dict[str, str] = {}
    seen_targets: dict[str, list[str]] = {}
    for event in ordered:
        if event.get("new_standing") != "revised":
            continue
        rev = event.get("revision_claim", "")
        target = event.get("target_claim", "")
        if not rev or not target:
            continue
        revision_of[rev] = target
        revised_by[target] = rev
        seen_targets.setdefault(rev, [])
        if target not in seen_targets[rev]:
            seen_targets[rev].append(target)
    conflicts = [rev for rev, tgts in seen_targets.items() if len(tgts) > 1]
    return {"revision_of": revision_of, "revised_by": revised_by,
            "conflicts": conflicts}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _err(errors: list[dict], code: str, message: str, **context: object) -> None:
    entry: dict[str, object] = {"code": code, "message": message}
    entry.update(context)
    errors.append(entry)


def _warn(warnings: list[dict], code: str, message: str, **context: object) -> None:
    entry: dict[str, object] = {"code": code, "message": message}
    entry.update(context)
    warnings.append(entry)


def _check_contested_bar(
    basis: dict,
    event_target: str,
    declarations: list[dict],
    events: list[dict],
) -> str | None:
    """Structural bar (§4.3). Returns an error detail string, else None.

    Checks, in order: challenge cited and existing is the caller's job
    (E1 covers dangling ids); here: the challenge claim targets the
    event target (via a declaration, or an explicit challenge target),
    and the challenge has no withdrawn/superseded event on it. The
    convener never judges whether the challenge is CORRECT — only
    whether the structure above holds.
    """
    challenge = basis.get("challenge") or {}
    challenge_claim = challenge.get("challenge_claim", "")
    if not challenge_claim:
        return "contested-standing event without a cited challenge claim"
    explicit_target = challenge.get("target")
    if explicit_target is not None:
        if explicit_target != event_target:
            return ("contested-standing challenge does not address the event "
                    "target")
        targets_event_target = True
    else:
        targets_event_target = any(
            decl.get("source_claim") == challenge_claim
            and decl.get("target_claim") == event_target
            for decl in declarations
        )
    if not targets_event_target:
        return ("contested-standing challenge does not address the event "
                "target")
    for event in events:
        if (event.get("target_claim") == challenge_claim
                and event.get("new_standing") in ("withdrawn", "superseded")):
            return "contested-standing challenge has been withdrawn or superseded"
    return None


def validate_contract_record(
    record: dict,
    *,
    validation_phase: str = "interim",
    meeting_kind: str = "build_council",
    meeting_rules: list[str] | None = None,
) -> dict:
    """Validate one contract record; never repairs data.

    ``record`` shape (all keys optional except ``claims``):
    claims, declarations, proposals, events, disagreements,
    corrections, target_states (explicit overrides; merged over
    computed defaults), exposure ({claim_id: {ref, evidence,
    visible_ids}}), stored_contract_standing ({claim_id: standing}),
    legacy_dispositions ([{claim_id, disposition, disposition_by}]),
    explicit_revision_links ({revision_of, revised_by} checked against
    derived links -> E8), score_fields_present (bool).

    ``validation_phase`` is "interim" or "final": temporarily
    unavailable evidence warns interim (W2) and errors at final (E12).
    ``meeting_kind`` is "build_council" (default: ``user`` is NOT a
    valid authorizer) or "product" (``user`` valid with a cited
    decision). Returns the validation report: phase, kind,
    conformant (zero errors), errors, warnings, counts, and the
    derived contract standing + revision links.
    """
    meeting_rules = list(meeting_rules or [])
    claims: list[dict] = record.get("claims") or []
    declarations: list[dict] = record.get("declarations") or []
    proposals: list[dict] = record.get("proposals") or []
    events: list[dict] = record.get("events") or []
    disagreements: list[dict] = record.get("disagreements") or []
    corrections: list[dict] = record.get("corrections") or []
    explicit_states: dict[str, dict] = record.get("target_states") or {}
    exposure: dict[str, dict] = record.get("exposure") or {}
    stored_standing: dict[str, str] = record.get("stored_contract_standing") or {}
    legacy: list[dict] = record.get("legacy_dispositions") or []
    explicit_links: dict | None = record.get("explicit_revision_links")

    errors: list[dict] = []
    warnings: list[dict] = []

    # --- claim index + positions (list order = sequence) ---
    by_id: dict[str, dict] = {}
    position: dict[str, int] = {}
    for i, claim in enumerate(claims):
        cid = claim.get("id", "")
        if not cid:
            continue
        if cid in by_id:
            _err(errors, "E1", f"duplicate claim id: {cid}", claim_id=cid)
        else:
            by_id[cid] = claim
        position[cid] = i
    claim_ids = list(by_id)

    # --- global id uniqueness across record namespaces ---
    seen_ids: dict[str, str] = {}
    for namespace, items, key in (
        ("proposal", proposals, "id"),
        ("event", events, "event_id"),
        ("disagreement", disagreements, "id"),
    ):
        for item in items:
            rid = item.get(key, "")
            if not rid:
                continue
            if rid in seen_ids or rid in by_id:
                _err(errors, "E1", f"duplicate id across records: {rid}",
                     record_id=rid)
            else:
                seen_ids[rid] = namespace

    # --- E14: score fields in the payload ---
    if record.get("score_fields_present"):
        _err(errors, "E14", "score fields present in capture payload")
    else:
        for claim in claims:
            for key in _SCORE_KEYS:
                if key in claim:
                    _err(errors, "E14",
                         f"score field {key!r} present on claim "
                         f"{claim.get('id', '?')}",
                         claim_id=claim.get("id", ""))
                    break

    # --- declarations: E1/E2/E3/E4 ---
    valid_declaration_sources: dict[str, int] = {}
    for decl in declarations:
        src = decl.get("source_claim", "")
        tgt = decl.get("target_claim", "")
        kind = decl.get("kind", "")
        layer = decl.get("layer", "declared")
        valid = True
        if not src or src not in by_id:
            _err(errors, "E1", f"declaration with unknown source: {src!r}",
                 claim_id=src)
            valid = False
        if not tgt or tgt not in by_id:
            _err(errors, "E1", f"declaration with unknown target: {tgt!r}",
                 claim_id=src)
            valid = False
        if valid and position[tgt] >= position[src]:
            _err(errors, "E2",
                 f"forward reference: {src} targets later claim {tgt}",
                 claim_id=src)
            valid = False
        if kind not in KIND_VOCABULARY or layer != "declared":
            _err(errors, "E4",
                 f"declaration kind/layer outside contract: kind={kind!r} "
                 f"layer={layer!r}",
                 claim_id=src)
            valid = False
        if valid:
            valid_declaration_sources[src] = valid_declaration_sources.get(src, 0) + 1
            exp = exposure.get(src) or {}
            if exp.get("evidence") == "present":
                visible = exp.get("visible_ids")
                if isinstance(visible, list) and tgt not in visible:
                    _err(errors, "E3",
                         f"declared target {tgt} not in visible set of {src}",
                         claim_id=src)

    # --- target-states: E5/E6/W1 (explicit merged over computed) ---
    computed = compute_target_states(claims, declarations)
    effective: dict[str, dict] = dict(computed)
    for cid, entry in explicit_states.items():
        effective[cid] = {
            "state": entry.get("state"),
            "set_by": entry.get("set_by", "system"),
            "uncertainty_reason": entry.get("uncertainty_reason"),
        }
    for claim in claims:
        cid = claim.get("id", "")
        if not cid:
            continue
        state_entry = effective.get(cid)
        if state_entry is None:
            continue
        state = state_entry.get("state")
        phase = claim.get("phase", "")
        if phase in ("response", "revision") and state == "missing":
            _err(errors, "E5", f"target-state missing for {phase} claim {cid}",
                 claim_id=cid)
        if state not in TARGET_STATES:
            _err(errors, "E6", f"target-state outside four states: {state!r}",
                 claim_id=cid)
            continue
        if state == "populated" and valid_declaration_sources.get(cid, 0) == 0:
            _err(errors, "E6",
                 f"populated target-state with zero valid declarations: {cid}",
                 claim_id=cid)
        if state == "declared-none":
            has_decls = any(d.get("source_claim") == cid for d in declarations)
            if has_decls or state_entry.get("set_by") != "author":
                _err(errors, "E6",
                     f"declared-none requires author-set state and zero "
                     f"target records: {cid}",
                     claim_id=cid)
        if state == "unknown":
            if state_entry.get("uncertainty_reason"):
                _warn(warnings, "W1",
                      f"target-state unknown: {cid}",
                      claim_id=cid)
            else:
                _err(errors, "E6",
                     f"unknown target-state without uncertainty_reason: {cid}",
                     claim_id=cid)

    # --- proposals: E1/E7/W4 ---
    for prop in proposals:
        pid = prop.get("id", "")
        tgt = prop.get("target_claim", "")
        if tgt and tgt not in by_id:
            _err(errors, "E1", f"proposal {pid!r} targets unknown claim {tgt!r}",
                 record_id=pid)
        if prop.get("proposed_standing") not in STANDING_VALUES:
            _err(errors, "E7",
                 f"proposal {pid!r} with standing outside vocabulary: "
                 f"{prop.get('proposed_standing')!r}",
                 record_id=pid)
        if not prop.get("proposer"):
            _err(errors, "E7", f"proposal {pid!r} without proposer",
                 record_id=pid)
        if not prop.get("evidence"):
            _warn(warnings, "W4", f"proposal {pid!r} without cited evidence",
                  record_id=pid)

    # --- basis id existence (E1) ---
    def _basis_ids(basis: dict) -> list[str]:
        ids: list[str] = []
        _pids = basis.get("proposal_ids") or []
        ids.extend([_pids] if isinstance(_pids, str) else _pids)
        acceptance = basis.get("acceptance") or {}
        if acceptance.get("claim_id"):
            ids.append(acceptance["claim_id"])
        if basis.get("superseding_claim"):
            ids.append(basis["superseding_claim"])
        challenge = basis.get("challenge") or {}
        if challenge.get("challenge_claim"):
            ids.append(challenge["challenge_claim"])
        _rcs = challenge.get("response_claims") or []
        ids.extend([_rcs] if isinstance(_rcs, str) else _rcs)
        return ids

    proposals_by_id = {p.get("id", ""): p for p in proposals}

    # --- events: E1/E7/E8/E9 ---
    ordered_events = sorted(events, key=lambda e: e.get("sequence") if isinstance(e.get("sequence"), int) else 0)
    sequences = [e.get("sequence") for e in events]
    if len(sequences) != len(set(sequences)) and sequences:
        _err(errors, "E9", "disposition event sequences are not unique")
    per_target: dict[str, list[dict]] = {}
    for event in ordered_events:
        eid = event.get("event_id", "")
        tgt = event.get("target_claim", "")
        new = event.get("new_standing", "")
        prior = event.get("prior_standing", "")
        authorizer = event.get("authorizer", "")
        basis = event.get("authorizing_basis") or {}
        if not eid or not tgt or new not in STANDING_VALUES or not isinstance(
            event.get("sequence"), int
        ):
            _err(errors, "E7", f"disposition event malformed: {eid!r}",
                 record_id=eid)
            continue
        if tgt not in by_id:
            _err(errors, "E1", f"event {eid!r} targets unknown claim {tgt!r}",
                 record_id=eid)
            continue
        for ref in _basis_ids(basis):
            if ref not in by_id and ref not in proposals_by_id:
                _err(errors, "E1",
                     f"event {eid!r} basis cites unknown id: {ref!r}",
                     record_id=eid)
        if not authorizer or not basis:
            _err(errors, "E7",
                 f"event {eid!r} without authorizer or authorizing_basis",
                 record_id=eid)
        elif authorizer == "user":
            if meeting_kind != "product":
                _err(errors, "E7",
                     f"user authorizer in build-council meeting: {eid!r}",
                     record_id=eid)
            elif not basis.get("user_decision"):
                _err(errors, "E7",
                     f"user-authorized event without cited decision: {eid!r}",
                     record_id=eid)
        elif authorizer == "convener-close":
            if new in ("revised", "withdrawn", "maintained"):
                acceptance = basis.get("acceptance") or {}
                target_author = (by_id[tgt].get("participant", "")
                                 or by_id[tgt].get("author", ""))
                if (acceptance.get("author") != target_author
                        or not acceptance.get("author")):
                    _err(errors, "E7",
                         f"convener-close {new} event without linked "
                         f"target-author acceptance: {eid!r}",
                         record_id=eid)
            elif new == "superseded":
                if (basis.get("meeting_rule") not in meeting_rules
                        or not basis.get("superseding_claim")
                        or basis.get("superseding_claim") not in by_id):
                    _err(errors, "E7",
                         f"convener-close supersession without cited rule + "
                         f"superseding claim: {eid!r}",
                         record_id=eid)
            elif new == "contested-standing":
                detail = _check_contested_bar(basis, tgt, declarations, events)
                if detail:
                    _err(errors, "E7",
                         f"contested-standing event fails structural bar: "
                         f"{detail}",
                         record_id=eid)
            elif new == "open":
                _err(errors, "E7",
                     f"event {eid!r} cannot set standing back to open",
                     record_id=eid)
        else:
            _err(errors, "E7",
                 f"event {eid!r} authorizer outside authorized set: "
                 f"{authorizer!r}",
                 record_id=eid)
        if new == "revised" and not event.get("revision_claim"):
            _err(errors, "E8",
                 f"revised event without revision_claim: {eid!r}",
                 record_id=eid)
        per_target.setdefault(tgt, []).append(event)
    for tgt, chain in per_target.items():
        if chain[0].get("prior_standing") != "open":
            _err(errors, "E9",
                 f"first event for {tgt} does not carry prior_standing open",
                 claim_id=tgt)
        for prev, cur in zip(chain, chain[1:]):
            if cur.get("prior_standing") != prev.get("new_standing"):
                _err(errors, "E9",
                     f"event chain break for {tgt}: prior_standing does not "
                     f"match previous new_standing",
                     claim_id=tgt)
    derived = derive_contract_standing(events, claim_ids)
    for cid, stored in stored_standing.items():
        if cid in derived and stored != derived[cid]:
            _err(errors, "E9",
                 f"stored contract standing for {cid} does not match "
                 f"derived standing",
                 claim_id=cid)

    # --- revision links: derived vs explicit (E8) ---
    derived_links = derive_revision_links(events)
    if explicit_links is not None:
        for key in ("revision_of", "revised_by"):
            if explicit_links.get(key) != derived_links.get(key):
                _err(errors, "E8",
                     f"explicit {key} disagrees with event-derived links")

    # --- disagreements: E1/E10/W3 ---
    for dis in disagreements:
        did = dis.get("id", "")
        claims_list = dis.get("claims") or []
        for cid in claims_list:
            if cid not in by_id:
                _err(errors, "E1",
                     f"disagreement {did!r} cites unknown claim {cid!r}",
                     record_id=did)
        if len(claims_list) < 2:
            _err(errors, "E10",
                 f"disagreement {did!r} names fewer than two claims",
                 record_id=did)
        if not dis.get("incompatibility"):
            _err(errors, "E10",
                 f"disagreement {did!r} without incompatibility statement",
                 record_id=did)
        if not dis.get("proposer"):
            _err(errors, "E10",
                 f"disagreement {did!r} without proposer",
                 record_id=did)
        if dis.get("stage") not in ("identified", "articulated"):
            _err(errors, "E10",
                 f"disagreement {did!r} with invalid stage: "
                 f"{dis.get('stage')!r}",
                 record_id=did)
        if not dis.get("cited_evidence"):
            _warn(warnings, "W3",
                  f"disagreement {did!r} with thin cited evidence",
                  record_id=did)

    # --- corrections: E11 (single-successor chains) ---
    correction_ids: set[str] = set()
    chain_of: dict[str, str] = {}
    head_of: dict[str, str] = {}
    for i, corr in enumerate(corrections):
        corr_id = corr.get("id") or f"correction:{i}"
        missing = [f for f in ("original_value", "corrected_value",
                               "author_or_process", "reason",
                               "superseded_record")
                   if corr.get(f) is None]
        if missing:
            _err(errors, "E11",
                 f"correction {corr_id!r} missing fields: {missing}",
                 record_id=corr_id)
            continue
        sup = corr.get("superseded_record", "")
        if sup in correction_ids:
            chain = chain_of[sup]
            if head_of.get(chain) != sup:
                reconciles = corr.get("reconciles") or {}
                heads = (reconciles.get("heads")
                         if isinstance(reconciles, dict) else None)
                if (not heads
                        or head_of.get(chain) not in (heads or [])
                        or not reconciles.get("resolver")
                        or not reconciles.get("reason")):
                    _err(errors, "E11",
                         f"correction {corr_id!r} cites non-head {sup!r} "
                         f"without valid reconciliation",
                         record_id=corr_id)
                    continue
                head_of[chain] = corr_id
            else:
                head_of[chain] = corr_id
            chain_of[corr_id] = chain
        elif sup in by_id or sup in seen_ids or sup in proposals_by_id:
            if sup in head_of:
                # Chain already exists for this origin: citing the
                # origin (not the head) is a conflict, not a new chain.
                reconciles = corr.get("reconciles") or {}
                heads = (reconciles.get("heads")
                         if isinstance(reconciles, dict) else None)
                if (not heads or head_of.get(sup) not in (heads or [])
                        or not reconciles.get("resolver")
                        or not reconciles.get("reason")):
                    _err(errors, "E11",
                         f"correction {corr_id!r} cites origin {sup!r} "
                         f"while head {head_of.get(sup)!r} exists, without "
                         f"valid reconciliation",
                         record_id=corr_id)
                    continue
                head_of[sup] = corr_id
            else:
                chain_of[corr_id] = sup
                head_of[sup] = corr_id
        else:
            _err(errors, "E11",
                 f"correction {corr_id!r} supersedes nonexistent record "
                 f"{sup!r}",
                 record_id=corr_id)
            continue
        correction_ids.add(corr_id)

    # --- exposure: E12/W2 (E3 handled in the declaration pass) ---
    for claim in claims:
        cid = claim.get("id", "")
        if not cid:
            continue
        exp = exposure.get(cid) or {}
        ref = exp.get("ref")
        evidence = exp.get("evidence")
        if ref is None and evidence in (None, "absent"):
            _err(errors, "E12", f"no exposure_ref recorded for {cid}",
                 claim_id=cid)
        elif not isinstance(ref, str) or not ref.strip():
            _err(errors, "E12", f"malformed exposure_ref for {cid}",
                 claim_id=cid)
        elif evidence == "absent":
            _err(errors, "E12",
                 f"exposure_ref points to nonexistent evidence for {cid}",
                 claim_id=cid)
        elif evidence == "temporarily_unavailable":
            if validation_phase == "final":
                _err(errors, "E12",
                     f"evidence still unavailable at final validation: {cid}",
                     claim_id=cid)
            else:
                _warn(warnings, "W2",
                      f"evidence temporarily unavailable (interim): {cid}",
                      claim_id=cid)

    # --- legacy dispositions: E7 (+E13 unless event-shaped) ---
    decl_pairs = {(d.get("source_claim"), d.get("target_claim"))
                  for d in declarations}
    claim_phase = {c.get("id", ""): c.get("phase", "") for c in claims}
    for leg in legacy:
        cid = leg.get("claim_id", "")
        disp = leg.get("disposition", "")
        by = leg.get("disposition_by", "")
        _err(errors, "E7",
             f"legacy disposition without authorizer: {cid} "
             f"{disp!r} by {by!r}",
             claim_id=cid)
        event_shaped = (
            disp in ("revised", "withdrawn")
            and by in by_id
            and claim_phase.get(by) == "revision"
            and (by, cid) in decl_pairs
        )
        if not event_shaped:
            _err(errors, "E13",
                 f"standing implied by non-event (legacy disposition): "
                 f"{cid} {disp!r}",
                 claim_id=cid)

    error_counts: dict[str, int] = {}
    for e in errors:
        error_counts[e["code"]] = error_counts.get(e["code"], 0) + 1
    warning_counts: dict[str, int] = {}
    for w in warnings:
        warning_counts[w["code"]] = warning_counts.get(w["code"], 0) + 1
    return {
        "version": 1,
        "validation_phase": validation_phase,
        "meeting_kind": meeting_kind,
        "conformant": not errors,
        "errors": errors,
        "warnings": warnings,
        "error_counts": error_counts,
        "warning_counts": warning_counts,
        "derived_contract_standing": derived,
        "revision_links": derived_links,
    }


# ---------------------------------------------------------------------------
# Convenience: full transjective_record section for one meeting's claims
# ---------------------------------------------------------------------------


def build_transjective_record(
    claims: list[dict],
    *,
    validation_phase: str = "final",
    meeting_kind: str = "build_council",
    meeting_rules: list[str] | None = None,
    payload_evidence: dict[str, str] | None = None,
) -> dict:
    """Build the ``transjective_record`` section from claim dicts.

    Adapter-derived and read-only: declarations, target-states, legacy
    dispositions, and exposure are computed from the existing claim
    fields (see :func:`adapt_claims_to_contract_inputs`); the input
    claims are never mutated and no stored capture is rewritten.
    Claims carrying a native ``exposure_ref`` (Increment B) feed
    validation through the adapter instead of defaulting to absent
    evidence. Contract standing is derived from the (empty, for old
    captures) event history — old captures carry no DispositionEvents,
    so every claim derives ``open``; proposals, labels, and legacy
    dispositions never move it. Old captures are expected to be
    non-conformant (E5 missing target-states, E7 dispositions without
    authorizers, E12 missing exposure_refs) — that is correct
    behavior, not a bug. ``payload_evidence`` (hash -> exact payload
    text, Increment B) is included in the section only when provided
    and non-empty, so old callers see no new key.
    """
    adapted = adapt_claims_to_contract_inputs(claims)
    record = {
        "claims": claims,
        "declarations": adapted["declarations"],
        "proposals": [],
        "events": [],
        "disagreements": [],
        "corrections": [],
        "target_states": adapted["target_states"],
        "exposure": adapted["exposure"],
        "legacy_dispositions": adapted["legacy_dispositions"],
    }
    report = validate_contract_record(
        record,
        validation_phase=validation_phase,
        meeting_kind=meeting_kind,
        meeting_rules=meeting_rules,
    )
    section = {
        "version": 1,
        "source": "adapter",
        "meeting_kind": meeting_kind,
        "validation_phase": validation_phase,
        "conformant": report["conformant"],
        "validation": {
            "errors": report["errors"],
            "warnings": report["warnings"],
            "error_counts": report["error_counts"],
            "warning_counts": report["warning_counts"],
        },
        "contract_standing": report["derived_contract_standing"],
        "revision_links": report["revision_links"],
        "declarations": adapted["declarations"],
        "target_states": adapted["target_states"],
        "legacy_dispositions": adapted["legacy_dispositions"],
        "exposure": adapted["exposure"],
        "notes": [
            "Adapter-derived from existing claim fields; original capture "
            "untouched.",
            "Old captures are expected to be non-conformant (missing "
            "target-states, dispositions without authorizers, missing "
            "exposure_refs); that is correct behavior, not a bug.",
            "Contract standing is derived from DispositionEvent history "
            "only and never overwrites registry claim_standing.",
        ],
    }
    if payload_evidence:
        # Increment B: exact payload texts keyed by hash, so payload
        # references stay retrievable and the presented-vs-mentioned
        # distinction stays auditable. Omitted when empty so old
        # callers see no new key.
        section["payload_evidence"] = dict(payload_evidence)
    return section
