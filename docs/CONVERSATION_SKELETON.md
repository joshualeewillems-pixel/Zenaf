# Conversation Skeleton — backend contract

One persistent conversation per user (`data/conversations/conversations.db`),
branching into personas via seat chips and into site activities via live
context. History carries across seats; per-seat `thread_state` keeps each
persona's quiet background continuity.

## Endpoints (auth required)

### POST /conversation/turn
One turn of the persistent conversation.

Request:
```json
{
  "conversation_id": "skeleton",
  "archetype_id": "mentor",
  "message": "Help me plan my week",
  "mode": "trained",
  "question": false,
  "context": {
    "sheet_type": "today",
    "sheet_id": null,
    "entity_type": "task",
    "entity_id": "t_abc123"
  }
}
```
- `conversation_id` defaults to `"skeleton"`. `archetype_id` is required and
  must be a stock seat id. `question: true` mirrors the chat "Question me"
  toggle (message may be empty). `context` is optional and entirely
  factual — which sheet is open, which entity is in focus.
- Seat switches are just a new `archetype_id` on the next turn.

Response:
```json
{
  "reply": "...",
  "conversation_id": "skeleton",
  "message_id": "9f2c…",
  "archetype_id": "mentor",
  "display_name": "The Gardener",
  "voice_color": "#c9a86a",
  "mode_used": "trained",
  "has_training": true
}
```

### GET /conversation?conversation_id=skeleton&limit=50
Hydrate the ongoing conversation, oldest first. **This replaces the
client-sent `history` array.** Each message:
```json
{
  "id": "…", "archetype_id": "mentor", "role": "user",
  "body": "…", "mode": "trained",
  "context": {"sheet_type": "today"}, "created_at": "…"
}
```
Frontend migration: on Talk open, `GET /conversation` once (seed
`initialMessages`), then `POST /conversation/turn` per send. The
`conversationId` / `initialMessages` props from chat consolidation plug
straight in.

### GET /conversation/suggestions?conversation_id=skeleton
The suggestion engine's three kinds — **all drafts, never filed**:
```json
{
  "conversation_id": "skeleton",
  "cached": false,
  "trainable_moments": [
    {"id": "skeleton:insight:0", "claim_type": "value_inference",
     "title": "…", "evidence": "verbatim user quote", "inference": "…",
     "question": "…", "scope": "moment", "status": "draft",
     "draft": true, "source": "conversation-skeleton"}
  ],
  "project_proposals": [
    {"id": "skeleton:proposal:0", "kind": "task", "title": "…",
     "source_quote": "…", "detail": "…",
     "draft": true, "status": "draft", "source": "conversation-skeleton"}
  ],
  "mint_suggestions": [
    {"id": "skeleton:mint:0", "title": "…", "moment": "…",
     "source_quote": "…", "why": "…",
     "suggested_action": "mint-standalone",
     "anchor_question": "How does this piece express this moment to you?",
     "draft": true, "source": "conversation-skeleton"}
  ]
}
```
- `trainable_moments` are shaped like `ReviewClaim` dicts — feed them to the
  existing amber confirmation flow to file; never auto-file.
- `project_proposals` are shaped like the project miner's proposals — feed
  them to the mining confirmation flow.
- `mint_suggestions` point at `POST /pipeline/mint-standalone`.
- The response is cached per message watermark (`cached: true` on repeat
  GETs with no new messages) so the UI can poll cheaply; the engine never
  pushes. Review gating holds everywhere: nothing trains without his verdict.

### POST /voice/chat (extended)
Now accepts optional `conversation_id`. When present, the server loads the
last 10 turns from the skeleton (the client `history` array is ignored) and
persists both turns of the exchange. Without it, behavior is byte-identical
to before.

## Frontend follow-up (out of scope for this PR)
- CouncilChat: seed from `GET /conversation`, send via `POST /conversation/turn`
  with `context` from the open sheet / focused entity.
- A suggestions affordance (open thread, never a push) consuming
  `GET /conversation/suggestions`.
- Unlock-ceremony visuals for seat reveals (the faces are already behind the
  training-depth gate).

## Notes for maintainers
- The reply builder lives in `local_ai/conversation/reply.py` and is shared
  by `/voice/chat` and `/conversation/turn` — never fork it.
- Thread summaries refresh every 20 turns per seat via the existing LLM path;
  on failure the old summary stands (raw history is the source of truth).
- Fixed here: `PersonalityStore` was being constructed with `user_id`
  positionally (its first param is `db_path`), which created a throwaway DB
  named after the user id and silently disabled trained voices. Same latent
  bug exists at `local_ai/council/archetypes.py:453` (Skeptic weights) —
  intentionally left for separate review.
