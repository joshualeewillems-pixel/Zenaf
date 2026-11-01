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
``council/twigs.py`` all import its strand/casting machinery. Phase 4
(tier enforcement) removed the scene renderer itself
(``render_archetype_story`` + ``_build_story_prompt``) after verifying
zero production callers and no unique behavior beyond what the
minting pipeline's story path covers; the ``scene_render`` ref kind
stays in the narrative vocabulary so old rows remain Tier D.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/journal", tags=["journal"])
