"""Journal routes — RETIRED endpoint note.

POST /journal/story (render a journal entry as an archetype scene via the
Meta LLM) was retired in the overnight backend comb-over: it had zero
callers repo-wide (no frontend, test, doc, or backend caller), and its
job is covered by the minting pipeline's POST /pipeline/story
(``local_ai/pipeline/stories.py``: title + narrative + key line).

The router object stays mounted (empty) so ``api/main.py``'s import and
``include_router`` keep working with no load error. The underlying
module ``local_ai/journal/story.py`` MUST stay: ``pipeline/stories.py``,
``demo_routes.py``, ``agent_intake/project_miner.py``, and
``council/twigs.py`` all import its strand/casting machinery, and its
scene renderer (``render_archetype_story``) is now caller-less — see the
comb-over findings report before removing anything further from it.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/journal", tags=["journal"])
