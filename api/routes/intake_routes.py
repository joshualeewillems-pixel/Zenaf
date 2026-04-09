"""
Intake API: email and fax ingestion → pipeline → queue. Raw content not returned.

Operator actions (mirror-only; no mailbox mutation):
- Open/read item: detail view and judgment chain ("Why?").
- Change lane: manual lane override + correction note (creates correction judgment).
- Add correction note: with lane change (required) or when clearing override.
- Update queue status: new / reviewed / done.
- Archive (internal hide): item hidden from default queue list in Zenaf only; no mailbox delete, no external folder/label moves.

Not supported: mailbox delete, external folder/label moves, or any mutation of the source mailbox.
"""
import os
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter(prefix="/intake", tags=["intake"])

# Where to send user after successful Gmail OAuth (frontend)
FRONTEND_URL = os.environ.get("INTAKE_OAUTH_FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")


class EmailIntakeBody(BaseModel):
    raw_body: str = ""


class FaxIntakeBody(BaseModel):
    raw_content: str = ""


class EmailConfigBody(BaseModel):
    host: str = ""
    user: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    label: str = ""


@router.get("/config/email")
def get_intake_email_config():
    """Return saved IMAP config for display (no password). Empty if not configured."""
    from local_ai.intake import get_imap_config_from_file
    configs = get_imap_config_from_file()
    if not configs:
        return {"host": "", "user": "", "mailbox": "INBOX", "label": ""}
    c = configs[0]
    return {"host": c.host, "user": c.user, "mailbox": c.mailbox, "label": c.label}


@router.put("/config/email")
def put_intake_email_config(body: EmailConfigBody):
    """Save IMAP config (host, user, password, optional mailbox/label). Used by UI to connect."""
    from local_ai.intake import save_imap_config
    if not (body.host or "").strip() or not (body.user or "").strip() or not (body.password or "").strip():
        raise HTTPException(status_code=400, detail="host, user, and password are required")
    save_imap_config(
        host=body.host.strip(),
        user=body.user.strip(),
        password=body.password.strip(),
        mailbox=(body.mailbox or "INBOX").strip() or "INBOX",
        label=(body.label or "").strip(),
    )
    return {"ok": True}


class GoogleOAuthConfigBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""


@router.get("/oauth/google/config")
def get_gmail_oauth_config_status():
    """Return whether Google OAuth credentials are configured; if not, return config_path for troubleshooting."""
    from local_ai.intake import gmail_oauth
    configured = gmail_oauth.get_gmail_oauth_config() is not None
    out = {"configured": configured}
    if not configured:
        out["config_path"] = getattr(gmail_oauth, "get_gmail_oauth_config_path_for_diagnostic", lambda: "")()
    return out


@router.put("/oauth/google/config")
def put_gmail_oauth_config(body: GoogleOAuthConfigBody):
    """Save Google OAuth client ID and secret (from Google Cloud Console). Enables Connect Gmail."""
    from local_ai.intake import gmail_oauth
    if not (body.client_id or "").strip() or not (body.client_secret or "").strip():
        raise HTTPException(status_code=400, detail="client_id and client_secret are required")
    gmail_oauth.save_gmail_oauth_config(body.client_id.strip(), body.client_secret.strip())
    return {"ok": True}


@router.get("/oauth/google/status")
def get_gmail_oauth_status():
    """Return whether Gmail is connected via OAuth and the email if so."""
    from local_ai.intake import gmail_oauth
    if not gmail_oauth.has_gmail_oauth():
        return {"connected": False, "email": None}
    tok = gmail_oauth.get_gmail_oauth_access_token()
    if not tok:
        return {"connected": False, "email": None}
    return {"connected": True, "email": tok[0]}


@router.get("/oauth/google/start")
def get_gmail_oauth_start():
    """Redirect user to Google consent screen for Gmail mailbox access (OAuth)."""
    from local_ai.intake import gmail_oauth
    cfg = gmail_oauth.get_gmail_oauth_config()
    if not cfg:
        config_path = getattr(gmail_oauth, "get_gmail_oauth_config_path_for_diagnostic", lambda: "")()
        found = getattr(gmail_oauth, "_find_oauth_config_file", lambda: None)()
        extra = f" Searched path: {config_path}" + (f"; file found at {found} but unreadable." if found else "")
        detail = (
            "Gmail OAuth not configured. Save Client ID and Client secret in the app (Email connection section), "
            "or set INTAKE_GOOGLE_CLIENT_ID and INTAKE_GOOGLE_CLIENT_SECRET."
            + extra
        )
        raise HTTPException(status_code=503, detail=detail)
    ok, _ = gmail_oauth._ensure_google_libs()
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth libraries not installed. From repo root run: pip install -r api/requirements.txt",
        )
    result = gmail_oauth.get_gmail_oauth_auth_url()
    if not result:
        raise HTTPException(status_code=503, detail="Could not build Gmail OAuth URL (check client credentials).")
    auth_url, _state = result
    return RedirectResponse(url=auth_url)


@router.get("/oauth/google/callback")
def get_gmail_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Exchange code for tokens, save, redirect to frontend. On failure, redirect with error message."""
    from local_ai.intake import gmail_oauth
    if error:
        return RedirectResponse(url=f"{FRONTEND_URL}?gmail_oauth=error&message={urlencode({'e': error})}")
    if not code:
        return RedirectResponse(url=f"{FRONTEND_URL}?gmail_oauth=error&message={urlencode({'e': 'missing_code'})}")
    try:
        email = gmail_oauth.exchange_gmail_oauth_code(code, state=state or None)
        return RedirectResponse(url=f"{FRONTEND_URL}?gmail_oauth=success&{urlencode({'email': email or ''})}")
    except Exception as e:
        return RedirectResponse(url=f"{FRONTEND_URL}?gmail_oauth=error&message={urlencode({'e': str(e)[:200]})}")


@router.post("/email")
def post_email_intake(body: EmailIntakeBody):
    """Ingest raw email body; run classification and PHI redaction; add to queue. Returns structured item only."""
    from local_ai.intake import process_email, add_item
    item = process_email(body.raw_body or "")
    add_item(item)
    return item.to_dict()


@router.post("/email/poll")
def post_email_poll():
    """Poll configured IMAP mailbox (unread), run pipeline, add to queue (skip duplicates). Returns added, skipped_duplicates, errors."""
    from fastapi.responses import JSONResponse
    from local_ai.intake import poll_ingest_emails
    stats, err = poll_ingest_emails()
    if err is not None:
        return JSONResponse(
            status_code=503,
            content={"detail": err, "added": 0, "skipped_duplicates": 0, "errors": []},
        )
    return {
        "added": stats["added"],
        "skipped_duplicates": stats["skipped_duplicates"],
        "errors": stats["errors"],
    }


@router.post("/fax")
def post_fax_intake(body: FaxIntakeBody):
    """Ingest raw fax/OCR content; run pipeline; add to queue. Returns structured item only."""
    from local_ai.intake import process_fax, add_item
    item = process_fax(body.raw_content or "")
    add_item(item)
    return item.to_dict()


@router.get("/queue")
def get_intake_queue(
    limit: int = 100,
    lane: str | None = None,
    status: str | None = None,
    search: str | None = None,
    sort: str = "created_desc",
    include_archived: bool = False,
):
    """List queue items with optional filters. lane/status: filter; search: subject+summary; sort: created_desc|created_asc. include_archived: show archived (internal hide) items."""
    from local_ai.intake import get_queue
    allowed_sort = ("created_desc", "created_asc")
    sort_val = sort if sort in allowed_sort else "created_desc"
    return get_queue(
        limit=max(1, min(500, limit)),
        lane=lane,
        status=status,
        search=search or None,
        sort=sort_val,
        include_archived=include_archived,
    )


class QueueItemUpdateBody(BaseModel):
    status: str | None = None
    notes: str | None = None
    assigned_to: str | None = None
    lane_override: str | None = None  # staff override; requires correction_note for logging
    correction_note: str | None = None  # reason for override (logged in judgment layer)
    archived: bool | None = None  # internal hide in Zenaf queue only; no mailbox change


class CreateTaskFromIntakeBody(BaseModel):
    """Body for graduating an intake item into a Vision Execution task."""
    project_id: str
    title: str = ""
    summary: str | None = None
    notes: str | None = None
    source_judgment_id: str | None = None


@router.post("/queue/{item_id}/create-task", status_code=201)
def post_intake_create_task(item_id: str, body: CreateTaskFromIntakeBody):
    """Create a Vision Execution task from this intake item. Records minimal lifecycle linkage (intake_item_id, judgment_id, task_id) in a Decision and in task notes. Human confirmation should be done in the UI before calling."""
    from local_ai.intake.bridge import create_task_from_intake_item
    if not (body.project_id or "").strip():
        raise HTTPException(status_code=400, detail="project_id is required")
    try:
        result = create_task_from_intake_item(
            intake_item_id=item_id,
            project_id=body.project_id.strip(),
            title=body.title or "",
            summary=body.summary,
            notes=body.notes,
            source_judgment_id=body.source_judgment_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.patch("/queue/{item_id}")
def patch_intake_queue_item(item_id: str, body: QueueItemUpdateBody):
    """Update status, notes, assigned_to. Optionally lane_override + correction_note to record a correction (judgment layer)."""
    from local_ai.intake import update_item
    allowed = ("new", "reviewed", "done")
    if body.status is not None and body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of: {allowed}")
    if body.lane_override is not None and (body.correction_note or "").strip() == "":
        raise HTTPException(status_code=400, detail="correction_note is required when setting lane_override")
    updated = update_item(
        item_id,
        status=body.status,
        notes=body.notes,
        assigned_to=body.assigned_to,
        lane_override=body.lane_override,
        correction_note=body.correction_note,
        archived=body.archived,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return updated


@router.get("/queue/{item_id}/judgment")
def get_intake_item_judgment(item_id: str):
    """Return judgment record(s) for this queue item: supersession chain (original first, then corrections) for explainability."""
    from local_ai.intake import get_item
    from local_ai.judgment import get_supersession_chain
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    judgment_id = (item.get("judgment_id") or "").strip()
    if not judgment_id:
        return {"chain": [], "item_id": item_id}
    chain = get_supersession_chain(judgment_id)
    return {"chain": [r.to_dict() for r in chain], "item_id": item_id}
