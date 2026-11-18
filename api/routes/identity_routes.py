"""Identity license + consent scopes + takeout API.

The ownership layer: issue the signed license, manage the granular consent
ledger, export everything (takeout), or delete the owner's deletable
footprint (signed receipt). Default-deny: every use of identity-derived
data requires an explicit grant.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.routes.auth_routes import get_current_user
from local_ai.identity import LicenseRequired, ScopeDenied
from local_ai.identity import service as identity_service
from local_ai.identity.erasure import COVERAGE_STATEMENTS, ErasureRefused
from local_ai.identity.models import DeletionReceipt, IdentityLicense
from local_ai.identity.scopes import KNOWN_SCOPES, check_scope

router = APIRouter(prefix="/identity", tags=["identity"])


def _resolve_owner_id() -> str | None:
    """The bootstrapped installation owner's user id (§9.1 source).

    Called through this module attribute so tests monkeypatch it
    exactly as the erasure flow's resolver is patched.
    """
    from local_ai.identity.erasure import _default_owner_resolver

    return _default_owner_resolver()


def require_installation_owner(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Session + installation-owner boundary (security correction).

    The identity stores are singletons — one license, one consent
    ledger — so a login gate alone is not a boundary: the session
    user must resolve to the bootstrapped installation owner, the
    same §9.1 resolution POST /identity/delete already enforces.
    Unauthenticated callers get 401 from get_current_user;
    authenticated non-owners get 403 here, before any store access.
    """
    owner_id = _resolve_owner_id()
    if not owner_id or current_user.get("id") != owner_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "This operation is restricted to the installation "
                "owner: the authenticated session does not resolve "
                "to this installation's owner record."
            ),
        )
    return current_user


class IssueBody(BaseModel):
    owner_id: str = "local-owner"


class ScopeBody(BaseModel):
    scope: str
    action: str  # grant | revoke
    note: str = ""


class DeleteBody(BaseModel):
    confirmation: str = ""


@router.post("/license/issue", response_model=IdentityLicense)
def issue_license(
    body: IssueBody,
    current_user: dict = Depends(require_installation_owner),
):
    """Issue the identity license (idempotent — returns the existing one).

    Installation-owner only: the trusted bootstrap path is the
    bootstrapped owner account's session (that account is created
    by the vision-execution storage bootstrap, independently of
    this license, so gating issuance creates no provisioning
    deadlock and leaves no unauthenticated alternative).
    """
    return identity_service.issue_license(owner_id=body.owner_id)


@router.get("/license")
def get_license(
    current_user: dict = Depends(require_installation_owner),
):
    """The license plus whether its signature currently verifies."""
    lic = identity_service.get_license()
    if lic is None:
        raise HTTPException(status_code=404, detail="No identity license issued.")
    return {
        "license": lic,
        "signature_valid": identity_service.verify_license(),
    }


@router.get("/scopes")
def list_scopes(
    current_user: dict = Depends(require_installation_owner),
):
    """Active scopes, the full ledger, and the known-scope catalog.

    Owner-only. ``active`` is the owner's fold. Scopes effective
    only via the legacy global (user_id="") tier — written before
    this route required the owner, provenance unattributable — are
    reported distinctly under ``legacy_global`` rather than
    silently presented as verified owner consent.
    """
    from local_ai.identity.store import IdentityStore

    owner_id = current_user["id"]
    store = IdentityStore()
    try:
        return {
            "active": sorted(store.active_scopes(user_id=owner_id)),
            "ledger": [e.model_dump(mode="json") for e in store.list_scope_events()],
            "known_scopes": KNOWN_SCOPES,
            "legacy_global": {
                "scopes": sorted(store.legacy_global_scopes(owner_id)),
                "note": (
                    "Effective for the installation owner via "
                    "historical global ledger events whose provenance "
                    "cannot be attributed; preserved, not verified "
                    "as owner consent."
                ),
            },
        }
    finally:
        store.close()


@router.post("/scopes")
def change_scope(
    body: ScopeBody,
    current_user: dict = Depends(require_installation_owner),
):
    """Grant or revoke a consent scope. Unknown scopes are rejected.

    Owner-only; the event is written under the resolved owner's
    user_id — never the global empty-user identity.
    """
    action = (body.action or "").strip().lower()
    if action not in ("grant", "revoke"):
        raise HTTPException(
            status_code=422, detail="action must be 'grant' or 'revoke'."
        )
    try:
        if action == "grant":
            active = identity_service.grant_scope(
                body.scope, note=body.note, user_id=current_user["id"]
            )
        else:
            active = identity_service.revoke_scope(
                body.scope, note=body.note, user_id=current_user["id"]
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"active": active}


@router.get("/scopes/check")
def check_one_scope(
    scope: str,
    current_user: dict = Depends(require_installation_owner),
):
    """Check whether a single scope is currently granted (default-deny)."""
    return {
        "scope": scope,
        "granted": check_scope(scope, user_id=current_user["id"]),
    }


@router.post("/takeout")
def takeout(
    current_user: dict = Depends(require_installation_owner),
):
    """Export everything Zenaf holds about the owner as one JSON bundle.

    Takeout is a right, not a privilege: no scope required, license
    required — but the right is the owner's, so the session must
    resolve to the installation owner (§9.1). Bundle contents are
    unchanged.
    """
    try:
        bundle = identity_service.build_takeout(
            requesting_user_id=current_user["id"]
        )
    except ErasureRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LicenseRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return JSONResponse(
        content=bundle,
        headers={
            "Content-Disposition": f"attachment; filename=zenaf-takeout-{stamp}.json"
        },
    )


@router.post(
    "/delete",
    response_model=DeletionReceipt,
    summary=(
        "Delete presence data, your narrative steward record, and "
        "fellowship observations (signed receipt)"
    ),
    # The coverage statement renders BY ID from the registry
    # (amendment §4; Gate B Increment 1 §3.3): the binding is
    # mechanical, not editorial — these are the same words the
    # receipt carries, drawn from the single registered text.
    description=COVERAGE_STATEMENTS["coverage/1"],
)
def delete_everything(
    body: DeleteBody,
    current_user: dict = Depends(get_current_user),
):
    """Run the Scope S erasure for the authenticated owner.

    Requires confirmation == "DELETE" (exactly) and the
    delete:execute scope. The session user must resolve to the
    installation's owner (§9.1); anything else is refused before
    anything is deleted. Returns the signed receipt — complete,
    incomplete, or the standing-completion report on a repeat
    invocation.
    """
    try:
        receipt = identity_service.delete_all(
            body.confirmation,
            requesting_user_id=current_user.get("id"),
        )
    except ErasureRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ScopeDenied as exc:
        raise HTTPException(
            status_code=403,
            detail=f"{exc} Grant it via POST /identity/scopes.",
        )
    return receipt
