import json
from atria_tools import (
    scan_folder,
    scan_file_steward_root,
    read_text_file,
    list_python_files,
    analyze_file_steward_folder,
    recommend_child_folders,
    assess_plan_strength,
    simulate_folder_plan,
    build_escalation_packet,
    run_council,
    web_research,
)


SYSTEM_PROMPT = """
You are Atria, a heart-centered visionary assistant.

You have tools. Use them to get data; then present and explain the results. Do NOT infer folder structure or plan strength yourself—call the File Steward tools so results come from the real engine.

When to CALL a tool:
- User asks to scan/list/read/analyze/recommend/assess/simulate something → call the matching tool with the path they mean (or from recent conversation).
- For folder-organization questions, call the SPECIFIC tool:
  - "What folders would you recommend?" / "Recommend child folders" → TOOL:recommend_child_folders:<folder_path>
  - "Which suggestions seem weak or uncertain?" / "Assess plan strength" → TOOL:assess_plan_strength:<folder_path>
  - "What would the simulated folder tree look like?" / "Simulate the plan" → TOOL:simulate_folder_plan:<folder_path>
- If no folder path was given recently, use the path from a previous "analyze" or "simulate" or "recommend" in the conversation.
- "Build escalation packet" / paste packet for Claude → TOOL:build_escalation_packet:<folder_path>
- Business decision / council → use "council <question>" (direct command) or TOOL:council:<question> for Strategist, Operator, Analyst, Governance, Brand + synthesis.
- Only use web search when the user explicitly asks for web research / lookup → TOOL:web_research:<query>. Do not call it for normal prompts.

When to answer NORMALLY (no tool):
- Follow-ups that only need you to explain or summarize what was already returned (e.g. "Explain that", "Summarize the file you just read").
- If the relevant tool result is already in the conversation, answer from it; do not call the tool again.

Your role for File Steward results: present the tool output clearly, explain what it means, and answer conversational questions. Do not invent structure or confidence—only report what the tools returned.

Tool response format (when calling a tool):
1. TOOL:scan_folder:<folder_path>
2. TOOL:scan_file_steward_root
3. TOOL:read_text_file:<file_path>
4. TOOL:list_python_files:<folder_path>
5. TOOL:analyze_file_steward_folder:<folder_path>
6. TOOL:recommend_child_folders:<folder_path>
7. TOOL:assess_plan_strength:<folder_path>
8. TOOL:simulate_folder_plan:<folder_path>
9. TOOL:build_escalation_packet:<folder_path>
10. TOOL:council:<question>
11. TOOL:web_research:<query> (only when user explicitly asks for web search or research)

Otherwise answer normally from the conversation.
"""

MAX_HISTORY_ENTRIES = 20
MAX_TOOL_RESULT_CHARS = 5000


def _truncate(s, max_chars=MAX_TOOL_RESULT_CHARS):
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n... (truncated in history)"


def _format_history_generic(tool_name: str, path_label: str, path: str | None, result) -> str:
    """Generic history formatter for dict or string results."""
    lines = [f"Tool used: {tool_name}"]
    if path is not None and path_label:
        lines.append(f"{path_label}: {path}")
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
    else:
        lines.append("Result:")
        if isinstance(result, dict):
            lines.append(_truncate(json.dumps(result, indent=2)))
        else:
            lines.append(_truncate(str(result)))
    return "\n".join(lines)


def _format_history_web_research(path: str | None, result) -> str:
    """Compact history for web_research so results do not overload the model."""
    _max_web_history = 1200
    lines = ["Tool used: web_research", "Query: " + (path or "")]
    if isinstance(result, dict) and result.get("error"):
        lines.append("Error: " + result["error"])
        return "\n".join(lines)
    if not isinstance(result, dict):
        lines.append(_truncate(str(result), _max_web_history))
        return "\n".join(lines)
    findings = result.get("findings", [])[:4]
    if findings:
        lines.append("Findings: " + " | ".join(f[:150] for f in findings))
    sources = result.get("sources", [])[:3]
    if sources:
        lines.append("Sources: " + "; ".join(s.get("title", "")[:80] for s in sources))
    notes = result.get("notes", "")
    if notes:
        lines.append("Notes: " + notes)
    out = "\n".join(lines)
    return _truncate(out, _max_web_history)


def _format_history_read_text_file(path: str | None, result: dict) -> str:
    lines = ["Tool used: read_text_file", "Read file: " + (path or "")]
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
    else:
        content = result.get("content", "") if isinstance(result, dict) else ""
        lines.append("File content:")
        lines.append(_truncate(content))
    return "\n".join(lines)


# Compact history for analyze_file_steward_folder: do NOT store full dict; only summary so follow-ups don't overload the model.
_MAX_ANALYZE_HISTORY_TOKENS = 10
_MAX_ANALYZE_HISTORY_YEARS = 5
_MAX_ANALYZE_HISTORY_EXTENSIONS = 10
_MAX_ANALYZE_HISTORY_CHILD_FOLDERS = 10


def _format_history_analyze_file_steward_folder(path: str | None, result: dict) -> str:
    """Store only a compact summary in conversation history; terminal still shows full output."""
    lines = ["Tool used: analyze_file_steward_folder", "Folder: " + (path or "")]
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
        return "\n".join(lines)

    r = result
    lines.append("Inferred context/domain: " + str(r.get("inferred_context_domain", "")))
    lines.append("Item count: " + str(r.get("item_count", 0)) + " (files: " + str(r.get("file_count", 0)) + ", folders: " + str(r.get("folder_count", 0)) + ")")

    tokens = r.get("repeated_tokens", [])[:_MAX_ANALYZE_HISTORY_TOKENS]
    if tokens:
        lines.append("Top repeated tokens: " + ", ".join(tokens))
    years = r.get("repeated_years", [])[:_MAX_ANALYZE_HISTORY_YEARS]
    if years:
        lines.append("Top repeated years: " + ", ".join(years))

    ext_breakdown = r.get("extension_breakdown", {})
    if isinstance(ext_breakdown, dict):
        ext_items = list(ext_breakdown.items())[:_MAX_ANALYZE_HISTORY_EXTENSIONS]
        if ext_items:
            lines.append("Top extensions: " + ", ".join(f"{k}({v})" for k, v in ext_items))

    suggested = r.get("suggested_child_folders", [])[:_MAX_ANALYZE_HISTORY_CHILD_FOLDERS]
    if suggested:
        lines.append("Suggested child folders: " + ", ".join(suggested))

    if r.get("truncated"):
        lines.append("Note: Analysis was truncated (total_items_seen: " + str(r.get("total_items_seen", "")) + ", items_analyzed: " + str(r.get("items_analyzed", "")) + ").")

    return "\n".join(lines)


# Compact history for simulate_folder_plan: do NOT store full proposed_assignments; summary only.
_MAX_SIMULATE_HISTORY_CHILD_FOLDERS = 10
_MAX_SIMULATE_HISTORY_ASSIGNMENTS_SAMPLE = 15
_MAX_SIMULATE_HISTORY_BLOCKED = 5


def _format_history_simulate_folder_plan(path: str | None, result: dict) -> str:
    """Store only a compact summary in conversation history; terminal still shows full output."""
    lines = ["Tool used: simulate_folder_plan", "Folder: " + (path or "")]
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
        return "\n".join(lines)

    r = result
    lines.append("Inferred context/domain: " + str(r.get("inferred_context_domain", "")))
    suggested = r.get("suggested_child_folders", [])[:_MAX_SIMULATE_HISTORY_CHILD_FOLDERS]
    if suggested:
        lines.append("Suggested child folders: " + ", ".join(suggested))

    assignments = r.get("proposed_assignments", [])
    lines.append("Proposed assignments: " + str(len(assignments)) + " items")
    sample = assignments[:_MAX_SIMULATE_HISTORY_ASSIGNMENTS_SAMPLE]
    for a in sample:
        lines.append("  - " + a.get("item_name", "") + " → " + a.get("suggested_child", "") + " (" + str(a.get("confidence", "")) + ")")
    if len(assignments) > _MAX_SIMULATE_HISTORY_ASSIGNMENTS_SAMPLE:
        lines.append("  ... and " + str(len(assignments) - _MAX_SIMULATE_HISTORY_ASSIGNMENTS_SAMPLE) + " more")

    blocked = r.get("blocked_items", [])
    if blocked:
        lines.append("Blocked items: " + str(len(blocked)))
        for b in blocked[:_MAX_SIMULATE_HISTORY_BLOCKED]:
            lines.append("  - " + b.get("item_name", "") + ": " + b.get("reason", ""))
        if len(blocked) > _MAX_SIMULATE_HISTORY_BLOCKED:
            lines.append("  ... and " + str(len(blocked) - _MAX_SIMULATE_HISTORY_BLOCKED) + " more")

    notes = r.get("notes", [])
    if notes:
        lines.append("Notes: " + "; ".join(notes))

    return "\n".join(lines)


def _format_history_recommend_child_folders(path: str | None, result: dict) -> str:
    """Compact history for recommend_child_folders."""
    lines = ["Tool used: recommend_child_folders", "Folder: " + (path or "")]
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
        return "\n".join(lines)
    r = result
    lines.append("Inferred context/domain: " + str(r.get("inferred_context_domain", "")))
    suggested = r.get("suggested_child_folders", [])[:10]
    if suggested:
        lines.append("Suggested child folders: " + ", ".join(suggested))
    plan = r.get("folder_plan", [])[:15]
    for p in plan:
        lines.append("  - " + p.get("suggested_child", "") + " (source: " + str(p.get("source", "")) + ", confidence: " + str(p.get("confidence", "")) + ")")
    if r.get("notes"):
        lines.append("Notes: " + "; ".join(r["notes"]))
    return "\n".join(lines)


def _format_history_assess_plan_strength(path: str | None, result: dict) -> str:
    """Compact history for assess_plan_strength."""
    lines = ["Tool used: assess_plan_strength", "Folder: " + (path or "")]
    if isinstance(result, dict) and "error" in result:
        lines.append("Error: " + result["error"])
        return "\n".join(lines)
    r = result
    lines.append("Inferred context/domain: " + str(r.get("inferred_context_domain", "")))
    summary = r.get("strength_summary", {})
    lines.append("Strength: total=" + str(summary.get("total_assignments", 0)) + " high=" + str(summary.get("high_confidence_count", 0)) + " medium=" + str(summary.get("medium_confidence_count", 0)) + " low=" + str(summary.get("low_confidence_count", 0)))
    low = r.get("low_confidence_assignments", [])[:10]
    if low:
        lines.append("Low-confidence: " + ", ".join(a.get("item_name", "") + "(" + str(a.get("confidence", "")) + ")" for a in low))
    weak = r.get("weak_suggestions", [])[:10]
    if weak:
        lines.append("Weak suggestions: " + ", ".join(w.get("suggested_child", "") + "(n=" + str(w.get("item_count", 0)) + ", avg=" + str(w.get("avg_confidence", "")) + ")" for w in weak))
    if r.get("notes"):
        lines.append("Notes: " + "; ".join(r["notes"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registry: name -> { func, direct_exact, direct_prefix, tool_prefix, takes_path, print_style, format_history }
# - direct_exact: user input equals this (case-insensitive) → run tool with path=None
# - direct_prefix: user input startswith this → path = rest of line
# - tool_prefix: model reply equals this or startswith this + path
# - takes_path: tool expects a path argument
# - print_style: "str" = print result as-is; "dict" = print result["error"] or json.dumps(result)
# - format_history: (path, result) -> str for conversation history
# ---------------------------------------------------------------------------
TOOLS = {
    "scan_file_steward_root": {
        "func": scan_file_steward_root,
        "direct_exact": "scan the file steward folder",
        "direct_prefix": None,
        "tool_prefix": "TOOL:scan_file_steward_root",
        "takes_path": False,
        "print_style": "str",
        "format_history": lambda path, result: "Tool used: scan_file_steward_root\nResult:\n" + _truncate(result),
    },
    "read_text_file": {
        "func": read_text_file,
        "direct_exact": None,
        "direct_prefix": "read ",
        "tool_prefix": "TOOL:read_text_file:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_read_text_file,
    },
    "scan_folder": {
        "func": scan_folder,
        "direct_exact": None,
        "direct_prefix": "scan ",
        "tool_prefix": "TOOL:scan_folder:",
        "takes_path": True,
        "print_style": "str",
        "format_history": lambda path, result: "Tool used: scan_folder\nScanned folder: " + (path or "") + "\nResult:\n" + _truncate(result),
    },
    "analyze_file_steward_folder": {
        "func": analyze_file_steward_folder,
        "direct_exact": None,
        "direct_prefix": "analyze ",
        "tool_prefix": "TOOL:analyze_file_steward_folder:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_analyze_file_steward_folder,
    },
    "recommend_child_folders": {
        "func": recommend_child_folders,
        "direct_exact": None,
        "direct_prefix": "recommend ",
        "tool_prefix": "TOOL:recommend_child_folders:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_recommend_child_folders,
    },
    "assess_plan_strength": {
        "func": assess_plan_strength,
        "direct_exact": None,
        "direct_prefix": "assess ",
        "tool_prefix": "TOOL:assess_plan_strength:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_assess_plan_strength,
    },
    "simulate_folder_plan": {
        "func": simulate_folder_plan,
        "direct_exact": None,
        "direct_prefix": "simulate ",
        "tool_prefix": "TOOL:simulate_folder_plan:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_simulate_folder_plan,
    },
    "list_python_files": {
        "func": list_python_files,
        "direct_exact": None,
        "direct_prefix": None,
        "tool_prefix": "TOOL:list_python_files:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": lambda path, result: _format_history_generic("list_python_files", "Folder", path, result),
    },
    "build_escalation_packet": {
        "func": build_escalation_packet,
        "direct_exact": None,
        "direct_prefix": "build escalation packet ",
        "tool_prefix": "TOOL:build_escalation_packet:",
        "takes_path": True,
        "print_style": "str",
        "format_history": lambda path, result: "Tool used: build_escalation_packet\nFolder: " + (path or "") + "\nResult:\n" + _truncate(str(result)),
    },
    "council": {
        "func": run_council,
        "direct_exact": None,
        "direct_prefix": "council ",
        "tool_prefix": "TOOL:council:",
        "takes_path": True,
        "print_style": "str",
        "format_history": lambda path, result: "Tool used: council\nQuestion: " + (path or "") + "\nResult:\n" + _truncate(str(result)),
    },
    "web_research": {
        "func": web_research,
        "direct_exact": None,
        "direct_prefix": "web ",
        "tool_prefix": "TOOL:web_research:",
        "takes_path": True,
        "print_style": "dict",
        "format_history": _format_history_web_research,
    },
}


def run_tool(tool_name: str, path: str | None = None) -> str:
    """
    Run a registered tool, print its result to the user, and return the
    model-friendly history string to append to conversation.
    """
    t = TOOLS[tool_name]
    func = t["func"]
    result = func(path) if t["takes_path"] else func()

    print("Atria tool result:")
    if t["print_style"] == "str":
        print(result)
    else:
        if isinstance(result, dict) and "error" in result:
            print(result["error"])
        else:
            print(json.dumps(result, indent=2))

    return t["format_history"](path, result)


# Exact phrases that mean "use recent analyzed folder" (no path in input); checked before prefix so "recommend child folders" is not parsed as path "child folders".
CONTEXT_ONLY_EXACT = {
    "recommend child folders": "recommend_child_folders",
    "assess uncertainty": "assess_plan_strength",
}


def match_direct_command(user: str) -> tuple[str | None, str | None]:
    """
    If user input matches a direct command, return (tool_name, path).
    path is None for no-arg tools, or the trimmed path for prefix commands.
    Context-only commands ("recommend child folders", "assess uncertainty") return (tool_name, None); caller uses recent_analyzed_folder.
    """
    user_stripped = user.strip()
    user_lower = user_stripped.lower()
    # Normalize whitespace so "recommend  child  folders" still matches
    user_normalized = " ".join(user_lower.split())

    # Context-only: use recent analyzed folder; do not interpret as path
    for phrase, tool_name in CONTEXT_ONLY_EXACT.items():
        if user_normalized == phrase:
            return tool_name, None

    # Exact phrase from registry (e.g. "scan the file steward folder")
    for name, t in TOOLS.items():
        exact = t.get("direct_exact")
        if exact and user_lower == exact.lower():
            return name, None

    # Prefix-based commands (require non-empty path for path-taking tools)
    for name, t in TOOLS.items():
        prefix = t.get("direct_prefix")
        if not prefix or not user.startswith(prefix):
            continue
        path = user[len(prefix):].strip()
        if t["takes_path"] and not path:
            continue
        return name, path if t["takes_path"] else None

    return None, None


def match_model_tool_reply(reply: str) -> tuple[str | None, str | None]:
    """
    If reply is a TOOL:... invocation, return (tool_name, path).
    path is None for no-arg tools or if not present. Otherwise return (None, None).
    """
    for name, t in TOOLS.items():
        prefix = t["tool_prefix"]
        if t["takes_path"]:
            if reply.startswith(prefix):
                path = reply[len(prefix):].strip()
                return name, path
        else:
            if reply.strip() == prefix:
                return name, None
    return None, None


def ask_model(full_prompt: str) -> str:
    """Send the full prompt (system + history + 'Atria:') via principal-based resolver."""
    from local_ai.llm.adapter import LLMRequest
    from local_ai.llm.execution_principal import anonymous_account_principal
    from local_ai.llm.resolver import get_llm_adapter_for_principal

    adapter = get_llm_adapter_for_principal(anonymous_account_principal())
    return adapter.generate_text(LLMRequest(task="atria_cli", prompt=full_prompt, timeout=None))


# Tools that update "recent analyzed folder" when run with a path (so "recommend child folders" / "assess uncertainty" can use it next).
FOLDER_CONTEXT_TOOLS = ("analyze_file_steward_folder", "simulate_folder_plan", "recommend_child_folders", "assess_plan_strength")


def main():
    print("\nAtria is ready.\n")
    conversation_history = []
    recent_analyzed_folder = None

    while True:
        user = input("You: ")

        if user.lower() in ["exit", "quit"]:
            break

        conversation_history.append("User: " + user)

        # Direct command handling (no model call)
        tool_name, path = match_direct_command(user)
        if tool_name is not None:
            # Context-only commands: use recent analyzed folder
            if path is None and tool_name in ("recommend_child_folders", "assess_plan_strength"):
                path = recent_analyzed_folder
                if not path:
                    msg = "No recent analysis available. First run: analyze <folder_path>"
                    print("Atria:", msg)
                    conversation_history.append("Atria: " + msg)
                    conversation_history = conversation_history[-MAX_HISTORY_ENTRIES:]
                    continue
            # "simulate " with no path: use recent if available
            if tool_name == "simulate_folder_plan" and not path and recent_analyzed_folder:
                path = recent_analyzed_folder
            if tool_name == "simulate_folder_plan" and not path:
                msg = "No folder path. Use: simulate <folder_path>"
                print("Atria:", msg)
                conversation_history.append("Atria: " + msg)
                conversation_history = conversation_history[-MAX_HISTORY_ENTRIES:]
                continue

            history_entry = run_tool(tool_name, path)
            conversation_history.append(history_entry)
            if tool_name in FOLDER_CONTEXT_TOOLS and path:
                recent_analyzed_folder = path
            conversation_history = conversation_history[-MAX_HISTORY_ENTRIES:]
            continue

        # Model turn
        full_prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(conversation_history[-MAX_HISTORY_ENTRIES:]) + "\nAtria:"
        reply = ask_model(full_prompt).strip()

        tool_name, path = match_model_tool_reply(reply)
        if tool_name is not None:
            history_entry = run_tool(tool_name, path)
            conversation_history.append(history_entry)
            if tool_name in FOLDER_CONTEXT_TOOLS and path:
                recent_analyzed_folder = path
        else:
            print("Atria:", reply)
            conversation_history.append("Atria: " + reply)

        conversation_history = conversation_history[-MAX_HISTORY_ENTRIES:]


if __name__ == "__main__":
    main()
