# Atria Adapters

Thin connectors to external systems. Adapters **only**:

- **Authenticate** — tokens, refresh, config
- **Fetch / send** — raw API calls to the external system
- **Normalize** — map external DTOs to internal objects (e.g. `IntakeItem`, `NormalizedTask`)

Adapters **never** contain:

- Routing or triage rules
- Council or reasoning logic
- Radar or decision memory
- Priority or lane assignment

Those live in **Atria Core** (e.g. `local_ai/intake/pipeline.py`, `local_ai/vision_execution/`, `local_ai/atria_tools.py`).

---

## Adapter kinds

| Kind | Key pattern | Returns / consumes |
|------|-------------|--------------------|
| **llm** | `llm.{name}` e.g. `llm.ollama` | `generate(prompt) -> str` |
| **mailbox** | `mailbox.{name}` e.g. `mailbox.gmail`, `mailbox.outlook` | `fetch_messages() -> list[NormalizedMessage]`; optional `send()` |
| **workflow_tracker** | `workflow.{name}` e.g. `workflow.linear` | `fetch_tasks()`, `fetch_projects()` -> normalized task/project; optional push |
| **content_distribution** | `content.{name}` e.g. `content.buffer` | fetch scheduled posts; publish; normalize |
| **fax_comms** | `fax.{name}` | receive/send; normalize to same intake input shape as mailbox |

---

## Registry usage

```python
from local_ai.adapters import get_adapter, register_adapter

# Resolve by key (core and API use this instead of importing concrete modules)
llm = get_adapter("llm", "ollama")
text = llm.generate("Hello")

# Register a new adapter (e.g. at app startup or in adapter module)
register_adapter("llm", "openai", MyOpenAIAdapter())
```

Default registrations are done in `__init__.py` (e.g. Ollama as `llm.ollama`). Mailbox and workflow adapters register when their modules are loaded or explicitly at startup.

---

## Internal types

- **Intake:** `IntakeItem` from `local_ai.intake.pipeline` — pipeline consumes normalized message content and produces `IntakeItem`; mailbox adapters produce the raw input to the pipeline (e.g. subject, body_plain, external_id, source_label).
- **Workflow (future):** `NormalizedTask`, `NormalizedProject` in this package or in `vision_execution` — adapter returns these; core maps to/from Vision Execution or radar as needed.

See `docs/ATRIA_ARCHITECTURE.md` for the full hub-and-spoke design.
