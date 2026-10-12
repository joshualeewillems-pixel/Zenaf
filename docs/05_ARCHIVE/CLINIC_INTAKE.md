# Clinic Intake — Direction and Priorities

## Current state

- **Pipeline:** Email/fax → internal classification → PHI detection → optional redaction → structured output. Raw content stays internal; only sanitized text may go to external AI.
- **Test harness:** The current "paste raw email / paste fax" UI in the Workspace Organizer is **temporary scaffolding** for testing the intake pipeline. It is not the target product UX.
- **Queue:** In-memory list of intake items (category, priority, summary, suggested_action, source). No status or workflow yet.

## Target direction

1. **Queue first:** Make the queue operationally useful (status, triage, optional notes/assignment). The future **Clinic Intake Dashboard** will be driven by this live queue.
2. **Real ingestion:** Replace paste-based ingestion with real integrations — **email connection first**, then fax ingestion.
3. **Reframe frontend:** Current manual textareas = test harness. Future UI = Clinic Intake Dashboard driven by live queue items (list/detail, filters, status actions, later assignments).

## Implementation priority

| Priority | Step | Scope |
|----------|------|--------|
| **A** | Make the queue operationally useful | Add queue item status (new / reviewed / done). Keep category, priority, source, summary, suggested_action. Add optional notes and assigned_to (fields + API; UI can follow). |
| **B** | Design email ingestion integration | Design how real email (IMAP/OAuth or similar) feeds the same pipeline; no paste. Document approach; implement in a follow-up. |
| **C** | Fax integration | After email is in place; same pipeline, different ingestion source. |

Do not overbuild; do not treat the current paste UI as the real product.

---

## Email ingestion (first integration)

### Proposal

**A. Safest first email integration**
- **IMAP with app password** (no OAuth in v1): connect to one mailbox, list recent messages, fetch body, normalize to plain text, run the existing pipeline, add to queue. Trigger via **on-demand poll** (e.g. POST /intake/email/poll or cron). No daemon; paste UI and poll coexist. Config via env: `INTAKE_IMAP_HOST`, `INTAKE_IMAP_USER`, `INTAKE_IMAP_PASSWORD`, optional `INTAKE_IMAP_MAILBOX` (default INBOX).

**B. Duplicate prevention**
- Each queue item can store an optional **external_id** (stable per email: Message-ID header if present, else hash of UID+date). Before adding, check **get_by_external_id(external_id)**; if an item already exists with that id, skip. No separate “seen” store in the minimal version—duplicates are avoided as long as the item remains in the queue.

**C. Email metadata in queue item**
- Add optional **external_id** (for dedup) and **subject** (email subject line; useful for staff). Do not store From/To or raw body in the queue. **created_at** can be set from the email Date header when available.
- **Subject caution:** Subject lines may contain sensitive information. Stored as-is for now; keep room for later optional subject redaction or suppression.
- **Sender:** Do not add full sender info unless clearly justified. If needed later, prefer a minimal safe form (e.g. sender display name or domain only), not full raw headers.

**D. Fit without overbuilding**
- Email ingestion is a **source adapter**: fetch → normalize body → run_pipeline (unchanged) → set external_id/subject on item → add_item. Classifier, redaction, and queue model stay as-is. Paste UI and POST /email unchanged. New endpoint POST /intake/email/poll returns added, skipped_duplicates, errors (or 503 if not configured).

### Mirror-only (read-only) — no mailbox changes

The current email integration is **mirror-only**. It must not change the original mailbox or confuse users.

- **Do not:** move emails, archive, apply labels/folders, mark as read, reply, or draft. Only ingest/copy enough content to classify and create queue items.
- **Unread stays unread:** Anything that is unread when we touch it stays unread. We use `FETCH` with **BODY.PEEK[]** so the server does not set the \Seen flag (unlike RFC822/BODY[], which can mark messages read).
- **How we keep it read-only:** (1) `SELECT` mailbox with **readonly=True**. (2) `FETCH` with **BODY.PEEK[]** only. (3) No STORE, COPY, MOVE, or other write operations.
- This design mirrors inbox activity into the clinic intake queue without altering mailbox state.

### Implementation (minimal)

- **Config:** Env vars `INTAKE_IMAP_HOST`, `INTAKE_IMAP_USER`, `INTAKE_IMAP_PASSWORD`; optional `INTAKE_IMAP_MAILBOX` (default INBOX). If unset, poll returns 503 with a clear message.
- **Polling scope:** Prefer **UNSEEN** messages so we don't repeatedly scan the same broad window; deduplication via `external_id` remains the final safeguard.
- **Module:** `local_ai/intake/email_ingestion.py` — IMAP connect (SSL), fetch unread messages, normalize body (text/plain preferred; HTML only when necessary with conservative tag stripping), dedupe by `external_id`, run pipeline, set `external_id` + `subject` on item, add to queue.
- **Queue:** Optional `external_id`, `subject`, and `source_label` on items; `get_by_external_id()` for duplicate check.
- **API:** POST `/intake/email/poll` → `{ "added": N, "skipped_duplicates": N, "errors": [...] }` or 503 `{ "detail": "...", "added": 0, "skipped_duplicates": 0, "errors": [] }`.
- **UI:** “Poll email” button in Clinic Intake; queue list shows subject when present.

### Multiple inbox sources (future)

- The ingestion layer is **not** hardcoded for a single mailbox. It uses a **list of mailbox configs**; MVP builds one config from env via `get_imap_config_from_env()`.
- **MailboxConfig** (host, user, password, mailbox, label, use_ssl) is the unit; `poll_ingest_emails(configs=...)` iterates over configs. To support multiple accounts/streams later: extend `get_imap_config_from_env()` (e.g. INTAKE_IMAP_2_*, ...) or load from a config file and pass the list.
- Each queue item can carry a **source_label** (e.g. inbox name or account label) so staff can see which stream an item came from. Optional env `INTAKE_IMAP_LABEL` sets the label for the single mailbox; default is the mailbox name (e.g. "INBOX").

### Identity login vs mailbox access

We **separate two concerns**:

- **Identity login** — Who is using the app (e.g. “Sign in to Zenaf”). Used for access control, preferences, audit. If we add **Sign in with Apple**, it is **identity/authentication only**. It does **not** grant read access to the user’s Apple Mail or iCloud Mail. Do not assume “Sign in with Apple” solves mailbox-reading for Apple Mail/iCloud Mail; a separate iCloud Mail integration would be needed for that.
- **Mailbox access** — Permission to read a specific mailbox for intake (Gmail, Outlook, etc.). This is **provider-specific OAuth** (or IMAP + app password as fallback). The real user-friendly path is OAuth per provider; IMAP + app password stays as a fallback/dev path.

**Preferred paths for mailbox access (email ingestion)**

| Provider | Preferred path | Fallback |
|----------|----------------|----------|
| **Gmail** | **Google OAuth** for mailbox access (user consents to “read your email”; we use tokens with IMAP XOAUTH2). | IMAP + app password |
| **Outlook / Microsoft 365** | **Microsoft OAuth** for mailbox access (user consents to mail read scope; we use tokens). | IMAP + app password |
| **Apple Mail / iCloud Mail** | Not solved by Sign in with Apple. Would require a separate **iCloud Mail integration** if we add it later. | — |

**Summary**

- **Google OAuth** = preferred future path for **Gmail** mailbox connection.
- **Microsoft OAuth** = preferred future path for **Outlook** mailbox connection.
- **Sign in with Apple** = identity only; it is **not** the same as Apple Mail access. Do not use it for mailbox-reading unless we build a dedicated iCloud Mail integration.
- **IMAP + app password** = fallback and dev path; keep it for providers without OAuth or for power users.

**Google’s official stance (Gmail)**

Google no longer supports third-party apps that require sharing your Google username and password; they recommend **“Sign in with Google”** (OAuth) for syncing mail to other apps. IMAP access for personal Gmail remains always on (as of 2025 the user-facing IMAP toggle is removed; existing IMAP connections are unaffected). Our design matches this: **Google OAuth for Gmail** as the user-facing path, with IMAP + app password as a fallback/dev option where still applicable.

### Gmail OAuth setup (Connect Gmail without app password)

To use **Connect Gmail** in the app you must create OAuth credentials and set env vars:

1. **Google Cloud Console:** Create a project (or use existing) → APIs & Services → Credentials → Create Credentials → OAuth client ID. Application type: **Web application**. Authorized redirect URI: `http://127.0.0.1:8010/intake/oauth/google/callback` (or your API base + `/intake/oauth/google/callback`). Copy Client ID and Client secret.
2. **OAuth consent screen:** Configure if prompted (e.g. User type: External, add your email as test user until the app is verified).
3. **Env vars** (where you run the API):
   - `INTAKE_GOOGLE_CLIENT_ID` = your Client ID
   - `INTAKE_GOOGLE_CLIENT_SECRET` = your Client secret
   - Optional: `INTAKE_GOOGLE_REDIRECT_URI` (default `http://127.0.0.1:8010/intake/oauth/google/callback`)
   - Optional: `INTAKE_OAUTH_FRONTEND_URL` (where to send user after success; default `http://127.0.0.1:5173`)

Then in the app click **Connect Gmail (no app password)** → sign in with Google → grant mail access → you are redirected back and Poll email will use OAuth. Tokens are stored in `intake_gmail_oauth.json` (add to .gitignore; already listed).

### OAuth mailbox connection (future implementation)

The **user-friendly** path for email intake is **provider-specific OAuth for mailbox access**, not a generic “Sign in with Google/Microsoft” for app identity. In the Email connection UI we’d have:

- **Connect Gmail** → Google OAuth (mail scopes) → store tokens → poll via XOAUTH2.
- **Connect Outlook** (later) → Microsoft OAuth (mail scopes) → store tokens → poll.
- **Manual / other** → existing IMAP host + user + app password (fallback).

**What we’d build**

- **Backend:** OAuth callback per provider (e.g. `/intake/oauth/google/callback`, `/intake/oauth/microsoft/callback`), exchange code for tokens, store refresh_token + access_token per connected mailbox. When polling, use stored tokens and refresh if expired; connect to IMAP (or Graph) with OAuth tokens.
- **Config:** Google Cloud project (Gmail); Azure app registration (Microsoft). Client ID/secret, redirect URIs. Tokens stored server-side only.
- **Frontend:** “Connect Gmail” and “Connect Outlook” (when implemented) as primary actions; “Use IMAP (advanced)” or similar for the current form. No conflation with app-level “Sign in with Apple” if that is added later for identity.

### Trial / rollout (safest path)

1. **Sandbox/test mailbox first:** Use a dedicated test or sandbox mailbox (e.g. a separate account or folder used only for intake trials). Confirm polling works, queue items appear, and the mailbox state is unchanged (nothing marked read, moved, or labeled).
2. **Then one real mailbox in read-only mirror mode:** Point at one real clinic mailbox. Keep mirror-only behavior; do not enable any mailbox automation (no auto-archive, no labels, no mark-read).
3. **No mailbox automation yet:** Do not add features that modify the mailbox (move, archive, label, mark read, reply, or draft) until explicitly required and agreed.
