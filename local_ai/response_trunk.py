"""
Central Response Trunk: turn-specific contract for Zenaf / System Interface.

Aspiration, mediation, grounding, and syntax are assembled into one Technical Header
prepended to the system prompt for that turn only (see ``build_response_control_block``).
"""
from __future__ import annotations

from typing import Sequence, TypedDict

from local_ai.conversation_trunk import MediationProfile, OutputContract, QuestionKind


class ResponseContract(TypedDict):
    """
    Turn-specific contract (Python backend is source of truth).
    Rendered into the Technical Header for a single LLM call.
    """

    syntax_rules: str
    grounding_fences: str
    mode_directives: str


def _mode_directives_block(
    *,
    scoped_digression: bool,
    question_kind: QuestionKind,
    output_contract: OutputContract,
    mediation_profile: MediationProfile,
    aspiration_context_available: bool,
    required_fields: Sequence[str],
) -> str:
    """Mediation profile + turn-level field checklist routing."""
    mode = f"question_kind={question_kind!r}, output_contract={output_contract!r}"
    mediation_line = (
        f"mediation_move={mediation_profile['mediation_move']!r}, "
        f"resolution_mode={mediation_profile['resolution_mode']!r}, "
        f"ambiguity_type={mediation_profile['ambiguity_type']!r}"
    )
    strict = ""
    if scoped_digression or question_kind == "priority_resolution":
        strict = "**STRICT FIELD MODE — ON:** Fill required fields exactly; malformed tags are parser failures.\n"
    priority_note = ""
    if question_kind == "priority_resolution":
        priority_note = (
            "**PRIORITY AMNESIA:** Recent conversation is omitted from Context this turn; "
            "answer from this contract + trunk only.\n"
        )
    field_rows = [f"- {str(f).strip()}" for f in required_fields if str(f).strip()]
    field_checklist = (
        "**FIELD CHECKLIST (backend required):**\n"
        + ("\n".join(field_rows) if field_rows else "- FIELD_1: [ID] when entity referenced")
        + "\n- If a field is missing/malformed, backend may auto-fill from Context or re-query as FIELD MISSING."
    )
    if aspiration_context_available:
        asp = (
            "**ASPIRATION:** If Context includes ASPIRATION ORIENTATION with an explicit directive, "
            "execute it while obeying this contract.\n"
        )
    else:
        asp = "**ASPIRATION:** None in Context; do not invent aspiration lines.\n"

    parts = [
        priority_note,
        strict,
        f"**mode:** {mode}\n",
        f"**mediation_profile:** {mediation_line}\n",
        field_checklist,
        asp,
    ]
    return "".join(p for p in parts if p)


def _syntax_rules_block() -> str:
    """Hostile schema — stylistic drift = integration failure."""
    return (
        "**ID MANDATE:** Every Vision & Execution entity you mention that has an id in Context MUST appear as "
        "`Name [ID: uuid]` (space after colon). Use exactly one pair of brackets around the tag — "
        "do not nest brackets around the uuid (e.g. never `[ID: [uuid]]`). No ID = system crash for linking.\n"
        "**BACKTICK BAN:** Triple backticks for proposed field text are a FATAL ERROR. "
        "Use ONLY `[DRAFT_VALUE: …]` for proposals — no code fences.\n"
        "**PARSER:** Reply is consumed by a technical parser; malformed field tokens are rejected."
    )


def _grounding_fences_block(*, scoped_digression: bool) -> str:
    """Lane control — different rooms / silos."""
    base = (
        "**LANE CONTROL (different rooms):** Never blend a Mailing List (idea lane) into a Website task lane "
        "unless PRIMARY notes or the user question explicitly ties them together.\n"
        "**PRIMARY AUTHORITY:** PRIMARY text is the only authority for focused entity contents."
    )
    if scoped_digression:
        return base + " **Scoped thread:** PRIMARY + BACKGROUND only for in-band edits.\n"
    return base


def build_response_contract(
    *,
    scoped_digression: bool,
    question_kind: QuestionKind,
    output_contract: OutputContract,
    mediation_profile: MediationProfile,
    aspiration_context_available: bool,
    required_fields: Sequence[str] | None = None,
) -> ResponseContract:
    """Assemble the three-part contract for this turn (dispatcher output)."""
    req = list(required_fields) if required_fields is not None else (
        ["FIELD_1: [DRAFT_VALUE]", "FIELD_2: [ID]"]
        if question_kind == "priority_resolution"
        else ["FIELD_1: [ID] when entity referenced"]
    )
    return ResponseContract(
        syntax_rules=_syntax_rules_block(),
        grounding_fences=_grounding_fences_block(scoped_digression=scoped_digression),
        mode_directives=_mode_directives_block(
            scoped_digression=scoped_digression,
            question_kind=question_kind,
            output_contract=output_contract,
            mediation_profile=mediation_profile,
            aspiration_context_available=aspiration_context_available,
            required_fields=req,
        ),
    )


def build_response_control_block(
    *,
    scoped_digression: bool,
    question_kind: QuestionKind,
    output_contract: OutputContract,
    mediation_profile: MediationProfile,
    aspiration_context_available: bool,
    required_fields: Sequence[str] | None = None,
) -> str:
    """Technical Header: prepended to Zenaf system instructions for this turn only."""
    c = build_response_contract(
        scoped_digression=scoped_digression,
        question_kind=question_kind,
        output_contract=output_contract,
        mediation_profile=mediation_profile,
        aspiration_context_available=aspiration_context_available,
        required_fields=required_fields,
    )
    return (
        "\n**RESPONSE CONTRACT — TECHNICAL HEADER (this turn only; backend-mandated):**\n"
        f"- **mode_directives:** {c['mode_directives']}\n"
        f"- **syntax_rules:** {c['syntax_rules']}\n"
        f"- **grounding_fences:** {c['grounding_fences']}\n"
    )
