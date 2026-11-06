"""
Authenticated user settings: LLM connections, notification prefs.
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, Depends, HTTPException

from api.routes.auth_routes import get_current_user
from local_ai import config as _config
from local_ai.llm.credentials import resolve_cloud_api_key
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.llm.provider_registry import (
    build_provider_status_rows,
    build_provider_status_rows_for_principal,
    normalize_provider_id,
)
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as St

router = APIRouter(tags=["settings"])

_PROVIDERS = frozenset({"ollama", "openai", "anthropic", "google", "xai", "meta", "openrouter"})
_KEY_PROVIDERS = frozenset({"openai", "anthropic", "google", "xai", "meta", "openrouter"})


def _ollama_tags_url(base_override: str | None) -> str:
    url = (base_override or "").strip() or _config.OLLAMA_URL
    if "/api/generate" in url:
        return url.replace("/api/generate", "/api/tags")
    u = url.rstrip("/")
    if u.endswith("/api"):
        return u + "/tags"
    return u + "/api/tags"


@router.get("/llm")
def get_llm_settings(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    profile = St.get_user_llm_profile(uid)
    creds = St.list_llm_credentials_mask(uid)
    enc = St.settings_encryption_available()
    active_model = profile["default_model"]
    if profile["default_provider"] == "ollama":
        active_model = profile["ollama_model"] or _config.OLLAMA_MODEL
    from local_ai.execution_policy.openai_credentials import (
        openai_env_key_present,
        openai_settings_key_present,
        resolve_openai_api_key_for_principal,
    )

    account_principal = authenticated_account_principal(uid)
    env_openai = openai_env_key_present()
    settings_openai_saved = openai_settings_key_present(uid)
    _key, effective_src = resolve_openai_api_key_for_principal(account_principal)
    if effective_src == "none":
        openai_status = "no_key_configured"
    elif effective_src == "env":
        openai_status = "env_override_active"
    elif effective_src == "undecryptable":
        openai_status = "saved_key_undecryptable"
    else:
        openai_status = "saved_key_available"
    providers = build_provider_status_rows_for_principal(account_principal, profile, creds)
    return {
        "default_provider": profile["default_provider"],
        "default_model": profile["default_model"],
        "ollama_base_url": profile["ollama_base_url"],
        "ollama_model": profile["ollama_model"],
        "credentials_present": creds,
        "encryption_configured": enc,
        "providers": providers,
        "active_summary": {
            "provider": profile["default_provider"],
            "model": active_model or "(default)",
        },
        "openai_execution": {
            "env_key_present": env_openai,
            "settings_key_saved": settings_openai_saved,
            "effective_source": effective_src,
            "status": openai_status,
            "note": (
                "Routed modes (e.g. Council with routing_context) resolve OpenAI as: OPENAI_API_KEY env first, "
                "then your saved Settings key when signed in. POST /run sends cookies to use the saved key."
            ),
        },
        "council_seat_providers": St.get_council_seat_providers(uid),
    }


@router.get("/llm/providers")
def get_llm_providers(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    profile = St.get_user_llm_profile(uid)
    creds = St.list_llm_credentials_mask(uid)
    return {"providers": build_provider_status_rows(uid, profile, creds)}


@router.put("/llm/providers/{provider}")
def put_llm_provider_enabled(
    provider: str,
    body: M.SettingsLLMProviderEnabledBody,
    current_user: dict = Depends(get_current_user),
):
    pv = normalize_provider_id(provider)
    try:
        St.set_llm_provider_enabled(current_user["id"], pv, body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    uid = current_user["id"]
    profile = St.get_user_llm_profile(uid)
    creds = St.list_llm_credentials_mask(uid)
    p = authenticated_account_principal(uid)
    return {"ok": True, "providers": build_provider_status_rows_for_principal(p, profile, creds)}


@router.put("/llm/council-seats/{seat_id}")
def put_council_seat_llm(
    seat_id: str,
    body: M.SettingsCouncilSeatLLMBody,
    current_user: dict = Depends(get_current_user),
):
    try:
        mapping = St.set_council_seat_llm_provider(current_user["id"], seat_id, body.llm_provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "council_seat_providers": mapping}


@router.put("/llm/profile")
def put_llm_profile(body: M.SettingsLLMProfileUpdate, current_user: dict = Depends(get_current_user)):
    try:
        return St.upsert_user_llm_profile(
            current_user["id"],
            default_provider=body.default_provider,
            default_model=body.default_model,
            ollama_base_url=body.ollama_base_url,
            ollama_model=body.ollama_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/llm/credentials/{provider}")
def put_llm_credential(
    provider: str,
    body: M.SettingsLLMCredentialBody,
    current_user: dict = Depends(get_current_user),
):
    pv = (provider or "").strip().lower()
    if pv not in _KEY_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid provider")
    if not St.settings_encryption_available():
        raise HTTPException(
            status_code=503,
            detail="Cannot encrypt API keys: install cryptography, or fix ZENAF_SETTINGS_ENCRYPTION_KEY / ~/.zenaf/settings_encryption.key.",
        )
    try:
        St.upsert_llm_provider_credential(current_user["id"], pv, body.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/llm/test")
def post_llm_test(body: M.SettingsLLMTestBody, current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    pv = (body.provider or "").strip().lower()
    if pv not in _PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid provider")

    model = (body.model or "").strip() or None
    ephemeral = (body.api_key or "").strip() or None
    key = ephemeral
    if key is None and pv in _KEY_PROVIDERS:
        p = authenticated_account_principal(uid)
        k, _src = resolve_cloud_api_key(p, pv)
        key = k

    result_ok = False
    result_err: str | None = None
    try:
        if pv == "ollama":
            try:
                prof = St.get_user_llm_profile(uid)
                tags_url = _ollama_tags_url(prof.get("ollama_base_url"))
                r = requests.get(tags_url, timeout=8)
                if r.status_code < 400:
                    result_ok = True
                    return {"ok": True}
                result_err = r.text[:300] or f"HTTP {r.status_code}"
                return {"ok": False, "error": result_err}
            except Exception as e:
                result_err = str(e)
                return {"ok": False, "error": result_err}

        if not key:
            result_err = "No API key (save credentials or pass api_key for a one-off test)."
            return {"ok": False, "error": result_err}

        if pv == "openai":
            from local_ai.providers import openai as po

            ok, err = po.test_connection(key, model)
        elif pv == "anthropic":
            from local_ai.providers import anthropic as pa

            ok, err = pa.test_connection(key, model)
        elif pv == "google":
            from local_ai.providers import google_genai as pg

            ok, err = pg.test_connection(key, model)
        elif pv == "meta":
            from local_ai.providers import meta as pm

            ok, err = pm.test_connection(key, model)
        elif pv == "openrouter":
            from local_ai.providers import openrouter as por

            ok, err = por.test_connection(key, model)
        else:
            from local_ai.providers import xai as px

            ok, err = px.test_connection(key, model)
        result_ok = bool(ok)
        result_err = (err or None) if not ok else None
        return {"ok": ok, "error": err or None} if ok else {"ok": False, "error": err or "failed"}
    except Exception as e:
        result_ok = False
        result_err = str(e)
        return {"ok": False, "error": result_err}
    finally:
        try:
            St.record_llm_provider_test_result(uid, pv, ok=result_ok, error=result_err)
        except Exception:
            pass


@router.get("/notifications")
def get_notifications(current_user: dict = Depends(get_current_user)):
    return St.get_user_notification_settings(current_user["id"])


@router.put("/notifications")
def put_notifications(body: M.SettingsNotificationUpdate, current_user: dict = Depends(get_current_user)):
    return St.upsert_user_notification_settings(current_user["id"], body.prefs or {})


@router.get("/permissions")
def get_permissions(current_user: dict = Depends(get_current_user)):
    return St.get_user_permissions_settings(current_user["id"])


@router.put("/permissions")
def put_permissions(body: M.SettingsPermissionsUpdate, current_user: dict = Depends(get_current_user)):
    try:
        return St.upsert_user_permissions_settings(
            current_user["id"],
            permissions=body.permissions or {},
            consent_acknowledged=bool(body.consent_acknowledged),
            consent_version=body.consent_version or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- Permission framework surface (Slice 2) --------------------------------
# The grouped stance surface (Rev2 §2.2–§2.3), the global pause control
# (C4.2–C4.3, clarification I.1), and the retained-information counts
# (Rev2 §4.2, R.1–R.4). Reads are lookups only; stance writes go
# through the Slice 1 stance store (never the boolean flags, never the
# scope ledger). No model calls on this path.


def _framework_state(user_id: str) -> dict:
    """Full framework state for the surface: pause + one entry per
    registered capability, each with its rows, current stance (user-set
    record, else the registry default), retained count, paused/quieted
    display flags, and exception membership (Rev2 §2.2).

    ``stance_source`` is "user" when a stance record exists and
    "default" when the row falls back to the registry default, so the
    surface never presents a default as if the user had set it.
    """
    from local_ai.permissions import registry as _registry
    from local_ai.permissions import retained as _retained
    from local_ai.permissions import store as _store

    pause = _store.get_pause(user_id)
    stances = _store.get_stances(user_id)
    counts = _retained.retained_counts(user_id)
    capabilities = []
    for capability_id, entry in _registry.CAPABILITIES.items():
        rows = []
        for row in entry.rows:
            record = (stances.get(capability_id) or {}).get(row.key)
            if isinstance(record, dict) and record.get("stance"):
                stance = record["stance"]
                source = "user"
                granted_at = record.get("granted_at")
                last_changed_at = record.get("last_changed_at")
                surface = record.get("surface")
            else:
                stance = entry.default_stance
                source = "default"
                granted_at = None
                last_changed_at = None
                surface = None
            rows.append(
                {
                    "key": row.key,
                    "label": row.label,
                    "kind": row.kind,
                    "stance": stance,
                    "stance_source": source,
                    "granted_at": granted_at,
                    "last_changed_at": last_changed_at,
                    "surface": surface,
                }
            )
        # Per-commitment capabilities (R6) list only rows with a
        # user-set stance record; commitments themselves are Slice 6
        # wiring, so no commitment picker is offered here.
        if entry.row_scheme == "per_commitment":
            rows = [
                {
                    "key": key,
                    "label": key,
                    "kind": "per_commitment",
                    "stance": record["stance"],
                    "stance_source": "user",
                    "granted_at": record.get("granted_at"),
                    "last_changed_at": record.get("last_changed_at"),
                    "surface": record.get("surface"),
                }
                for key, record in (stances.get(capability_id) or {}).items()
                if isinstance(record, dict) and record.get("stance")
            ]
        capabilities.append(
            {
                "id": capability_id,
                "covers": entry.covers,
                "does_not_allow": entry.does_not_allow,
                "default_stance": entry.default_stance,
                "supported_stances": list(entry.supported_stances),
                "exception_classes": list(entry.exception_classes),
                "retained_count": counts.get(capability_id, 0),
                # Quieting has no machinery until Slice 3 (no counters,
                # no quiet state): nothing is quieted in Slice 2.
                "quieted": False,
                "paused": bool(pause.get("paused", False)),
                "rows": rows,
            }
        )
    return {"paused": bool(pause.get("paused", False)), "pause": pause, "capabilities": capabilities}


@router.get("/permissions/framework")
def get_framework_permissions(current_user: dict = Depends(get_current_user)):
    return _framework_state(current_user["id"])


@router.put("/permissions/framework/stance")
def put_framework_stance(body: M.FrameworkStanceUpdate, current_user: dict = Depends(get_current_user)):
    """Write one stance record (surface: settings).

    Succeeds even while the global pause override is set (I.1 rule 2):
    the write is durable and visible, but takes no effect for new
    operations until un-pause — the pause record is independent and
    untouched. Invalid capability / stance / row → 400.
    """
    from local_ai.permissions import store as _store

    user_id = current_user["id"]
    try:
        record = _store.set_stance(
            user_id,
            body.capability,
            body.row_key,
            body.stance,
            surface=_store.SURFACE_SETTINGS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    from local_ai.permissions import retained as _retained

    retained_count = _retained.retained_counts(user_id).get(body.capability, 0)
    return {
        "record": record,
        "retained_count": retained_count,
        # The retained-information choice is offered (nonblocking,
        # R.1–R.4) when a revocation leaves retained items behind.
        "retained_choice_offered": (
            body.stance == "dont_do_it" and retained_count > 0
        ),
        "state": _framework_state(user_id),
    }


@router.put("/permissions/framework/pause")
def put_framework_pause(body: M.FrameworkPauseUpdate, current_user: dict = Depends(get_current_user)):
    """Set or clear the global pause override (surface: settings).

    Writes ONLY the pause record (C4.2(d), C4-T4): stances and stance
    history are untouched. ``canceled_operations`` lists the pending
    operations the pause canceled — empty in Slice 2, because no
    cancelable pending operation exists in the wired surface yet
    (queued reminders and unsent derivation proposals have no pending
    substrate; see C4-T2). Un-pausing restores stances, never
    restarts anything canceled (C4.2(e)).
    """
    from local_ai.permissions import store as _store

    user_id = current_user["id"]
    record = _store.set_pause(user_id, bool(body.paused), surface=_store.SURFACE_SETTINGS)
    return {
        "pause": record,
        "canceled_operations": [],
        "state": _framework_state(user_id),
    }
