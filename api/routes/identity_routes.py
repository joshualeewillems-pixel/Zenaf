"""Identity license + consent scopes + takeout API.

The ownership layer: issue the signed license, manage the granular consent
ledger, export everything (takeout), or delete everything (signed receipt).
Default-deny: every use of identity-derived data requires an explicit grant.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from local_ai.identity import LicenseRequired, ScopeDenied
from local_ai.identity import service as identity_service
from local_ai.identity.models import DeletionReceipt, IdentityLicense
from local_ai.identity.scopes import KNOWN_SCOPES, check_scope

router = APIRouter(prefix="/identity", tags=["identity"])


class IssueBody(BaseModel):
    owner_id: str = "local-owner"


class ScopeBody(BaseModel):
    scope: str
    action: str  # grant | revoke
    note: str = ""


class DeleteBody(BaseModel):
    confirmation: str = ""


@router.post("/license/issue", response_model=IdentityLicense)
def issue_license(body: IssueBody):
    """Issue the identity license (idempotent — returns the existing one)."""
    return identity_service.issue_license(owner_id=body.owner_id)


@router.get("/license")
def get_license():
    """The license plus whether its signature currently verifies."""
    lic = identity_service.get_license()
    if lic is None:
        raise HTTPException(status_code=404, detail="No identity license issued.")
    return {
        "license": lic,
        "signature_valid": identity_service.verify_license(),
    }


@router.get("/scopes")
def list_scopes():
    """Active scopes, the full ledger, and the known-scope catalog."""
    from local_ai.identity.store import IdentityStore

    store = IdentityStore()
    try:
        return {
            "active": sorted(store.active_scopes()),
            "ledger": [e.model_dump(mode="json") for e in store.list_scope_events()],
            "known_scopes": KNOWN_SCOPES,
        }
    finally:
        store.close()


@router.post("/scopes")
def change_scope(body: ScopeBody):
    """Grant or revoke a consent scope. Unknown scopes are rejected."""
    action = (body.action or "").strip().lower()
    if action not in ("grant", "revoke"):
        raise HTTPException(
            status_code=422, detail="action must be 'grant' or 'revoke'."
        )
    try:
        if action == "grant":
            active = identity_service.grant_scope(body.scope, note=body.note)
        else:
            active = identity_service.revoke_scope(body.scope, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"active": active}


@router.get("/scopes/check")
def check_one_scope(scope: str):
    """Check whether a single scope is currently granted (default-deny)."""
    return {"scope": scope, "granted": check_scope(scope)}


@router.post("/takeout")
def takeout():
    """Export everything Zenaf holds about the owner as one JSON bundle.

    Takeout is a right, not a privilege: no scope required, license required.
    """
    try:
        bundle = identity_service.build_takeout()
    except LicenseRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return JSONResponse(
        content=bundle,
        headers={
            "Content-Disposition": f"attachment; filename=zenaf-takeout-{stamp}.json"
        },
    )


@router.post("/delete", response_model=DeletionReceipt)
def delete_everything(body: DeleteBody):
    """Delete everything derived from the owner. Returns a signed receipt.

    Requires confirmation == "DELETE" (exactly) and the delete:execute scope.
    """
    try:
        receipt = identity_service.delete_all(body.confirmation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ScopeDenied as exc:
        raise HTTPException(
            status_code=403,
            detail=f"{exc} Grant it via POST /identity/scopes.",
        )
    return receipt
