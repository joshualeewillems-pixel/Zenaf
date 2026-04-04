"""
Gmail mailbox access via Google OAuth2 (no app password).
Identity vs mailbox: this is for mailbox access only; tokens are used to read Gmail via IMAP XOAUTH2.
"""
from __future__ import annotations

import base64
import json
import os

# Optional: only needed for OAuth flow and token refresh
def _ensure_google_libs():
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow
        from google.auth.transport.requests import Request
        return True, (Credentials, Flow, Request)
    except ImportError:
        return False, None


# Scopes: Gmail IMAP (read mail); openid + userinfo.email so we get email in id_token.
# Use canonical URLs to avoid Google "scope has changed" errors (short "email" vs userinfo.email).
GMAIL_SCOPE = [
    "https://mail.google.com/",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

def _gmail_oauth_path() -> str:
    if os.environ.get("INTAKE_GMAIL_OAUTH_FILE", "").strip():
        return os.environ.get("INTAKE_GMAIL_OAUTH_FILE", "").strip()
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(root, "intake_gmail_oauth.json")
    except Exception:
        return os.path.join(os.getcwd(), "intake_gmail_oauth.json")


def _google_oauth_config_path() -> str:
    """Path to saved Google OAuth client credentials. Prefer env; else repo root (so path is stable regardless of cwd)."""
    if os.environ.get("INTAKE_GOOGLE_OAUTH_CONFIG_FILE", "").strip():
        return os.environ.get("INTAKE_GOOGLE_OAUTH_CONFIG_FILE", "").strip()
    # Put next to intake_imap_config.json in repo root (parent of local_ai)
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(root, "intake_google_oauth_config.json")
    except Exception:
        return os.path.join(os.getcwd(), "intake_google_oauth_config.json")


def _read_oauth_config_from_file(path: str) -> tuple[str, str]:
    """Read client_id and client_secret from a JSON file. Returns ('', '') on any failure."""
    if not path or not os.path.isfile(path):
        return ("", "")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            (data.get("client_id") or "").strip(),
            (data.get("client_secret") or "").strip(),
        )
    except (OSError, json.JSONDecodeError):
        return ("", "")


def _find_oauth_config_file() -> str | None:
    """
    Locate intake_google_oauth_config.json when __file__-based path fails
    (e.g. API started from api/, or multiple copies of local_ai).
    """
    name = "intake_google_oauth_config.json"
    env_path = os.environ.get("INTAKE_GOOGLE_OAUTH_CONFIG_FILE", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    p1 = _google_oauth_config_path()
    if os.path.isfile(p1):
        return p1
    cwd = os.getcwd()
    path2 = os.path.join(cwd, name)
    if os.path.isfile(path2):
        return path2
    # Walk upward from cwd (e.g. cwd is api/ or frontend/)
    cur = os.path.abspath(cwd)
    for _ in range(8):
        candidate = os.path.join(cur, name)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def get_gmail_oauth_config() -> dict | None:
    """Return client_id, client_secret, redirect_uri from env, then from saved file(s), or None."""
    client_id = os.environ.get("INTAKE_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("INTAKE_GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("INTAKE_GOOGLE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret:
        # Env first; then repo-root from __file__; then cwd; then walk up from cwd
        found = _find_oauth_config_file()
        if found:
            client_id, client_secret = _read_oauth_config_from_file(found)
        if not client_id or not client_secret:
            path2 = os.path.join(os.getcwd(), "intake_google_oauth_config.json")
            client_id, client_secret = _read_oauth_config_from_file(path2)
    if not redirect_uri:
        redirect_uri = "http://127.0.0.1:8010/intake/oauth/google/callback"
    if not client_id or not client_secret:
        return None
    return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}


def save_gmail_oauth_config(client_id: str, client_secret: str) -> None:
    """Save Google OAuth client credentials to file (for UI). Keep file out of version control. Writes to repo root and cwd so Connect Gmail finds it either way."""
    payload = {"client_id": (client_id or "").strip(), "client_secret": (client_secret or "").strip()}
    path1 = _google_oauth_config_path()
    paths = {path1, os.path.join(os.getcwd(), "intake_google_oauth_config.json")}
    # Also write next to first existing intake_imap_config.json upward from cwd so Poll/config find it
    cur = os.path.abspath(os.getcwd())
    for _ in range(8):
        for sibling in ("intake_imap_config.json", "intake_google_oauth_config.json"):
            p = os.path.join(cur, sibling)
            if os.path.isfile(p):
                paths.add(os.path.join(cur, "intake_google_oauth_config.json"))
                break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for path in paths:
        if not path:
            continue
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass


def get_gmail_oauth_config_path_for_diagnostic() -> str:
    """Return the path we read/write for OAuth config (so user can verify file location)."""
    return _google_oauth_config_path()


def get_gmail_oauth_auth_url(redirect_uri: str | None = None) -> tuple[str, str] | None:
    """
    Return (auth_url, state) for redirecting the user to Google consent.
    state can be used to redirect back to frontend after callback.
    """
    ok, libs = _ensure_google_libs()
    if not ok:
        return None
    cfg = get_gmail_oauth_config()
    if not cfg:
        return None
    Credentials, Flow, Request = libs
    redirect = redirect_uri or cfg["redirect_uri"]
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect],
            }
        },
        scopes=GMAIL_SCOPE,
        redirect_uri=redirect,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # PKCE: google_auth_oauthlib Flow stores code_verifier on flow.code_verifier (and uses
    # it in fetch_token). Callback creates a new Flow—persist verifier by state.
    verifier = getattr(flow, "code_verifier", None)
    if verifier and state:
        _save_pkce_state(state, verifier)
    return (auth_url, state)


def _pkce_store_path() -> str:
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(root, "intake_gmail_oauth_pkce.json")
    except Exception:
        return os.path.join(os.getcwd(), "intake_gmail_oauth_pkce.json")


def _save_pkce_state(state: str, code_verifier: str) -> None:
    """Persist PKCE code_verifier keyed by OAuth state for callback exchange."""
    path = _pkce_store_path()
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
    # Keep last 10 entries to avoid unbounded growth
    data[state] = code_verifier
    if len(data) > 10:
        for k in list(data.keys())[:-10]:
            del data[k]
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_pkce_verifier(state: str) -> str | None:
    if not state:
        return None
    path = _pkce_store_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get(state) or "").strip() or None
    except (OSError, json.JSONDecodeError):
        return None


def _clear_pkce_state(state: str) -> None:
    path = _pkce_store_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if state in data:
            del data[state]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
    except (OSError, json.JSONDecodeError):
        pass


def exchange_gmail_oauth_code(
    code: str, redirect_uri: str | None = None, state: str | None = None
) -> str | None:
    """
    Exchange authorization code for tokens; save to intake_gmail_oauth.json.
    Returns the user's email (from token info) or None on failure.
    """
    ok, libs = _ensure_google_libs()
    if not ok:
        return None
    cfg = get_gmail_oauth_config()
    if not cfg:
        return None
    Credentials, Flow, Request = libs
    redirect = redirect_uri or cfg["redirect_uri"]
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect],
            }
        },
        scopes=GMAIL_SCOPE,
        redirect_uri=redirect,
    )
    verifier = _load_pkce_verifier(state or "")
    if verifier:
        flow.code_verifier = verifier
    try:
        flow.fetch_token(code=code)
    finally:
        if state:
            _clear_pkce_state(state)
    credentials = flow.credentials
    email = ""
    if getattr(credentials, "id_token", None):
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            info = id_token.verify_oauth2_token(
                credentials.id_token, google_requests.Request(), None
            )
            email = (info.get("email") or "").strip()
        except Exception:
            pass
    # Store for IMAP
    path = _gmail_oauth_path()
    data = {
        "refresh_token": credentials.refresh_token,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "email": email,
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return email or ""


def get_gmail_oauth_access_token() -> tuple[str, str] | None:
    """
    Load saved Gmail OAuth credentials; refresh if needed. Return (email, access_token) or None.
    """
    ok, libs = _ensure_google_libs()
    if not ok:
        return None
    path = _gmail_oauth_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    refresh_token = (data.get("refresh_token") or "").strip()
    client_id = (data.get("client_id") or "").strip()
    client_secret = (data.get("client_secret") or "").strip()
    email = (data.get("email") or "").strip()
    if not refresh_token or not client_id or not client_secret:
        return None
    Credentials, Flow, Request = libs
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPE,
    )
    creds.refresh(Request())
    return (email or "gmail@oauth", creds.token)


def build_xoauth2_string(email: str, access_token: str, *, already_base64: bool = False) -> str:
    """
    Build SASL XOAUTH2 initial client response per RFC (user=...\\x01auth=Bearer ...\\x01\\x01).
    When used with imaplib.authenticate('XOAUTH2', ...), pass already_base64=False (default):
    imaplib will base64-encode the return value before sending. If you need the pre-encoded
    form for another client, pass already_base64=True.
    """
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    if already_base64:
        return base64.b64encode(raw.encode()).decode()
    return raw


def has_gmail_oauth() -> bool:
    """True if we have saved Gmail OAuth credentials (and optional client config)."""
    path = _gmail_oauth_path()
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool((data.get("refresh_token") or "").strip())
    except (OSError, json.JSONDecodeError):
        return False
