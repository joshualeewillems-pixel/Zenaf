from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as S

SESSION_COOKIE_NAME = "atria_session"

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_cookie_settings() -> dict:
    # Local-first dev default. Not production-safe without secure deployment settings.
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": False,
        "path": "/",
    }


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = S.get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    return user


def get_current_admin_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.post("/login")
def login(body: M.LoginRequest, response: Response):
    user = S.authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    session_token = S.create_session(user["id"])
    response.set_cookie(SESSION_COOKIE_NAME, session_token, **_session_cookie_settings())
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "is_admin": bool(user.get("is_admin")),
            "avatar_data_url": user.get("avatar_data_url"),
        },
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        S.revoke_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "display_name": current_user["display_name"],
        "is_admin": bool(current_user.get("is_admin")),
        "avatar_data_url": current_user.get("avatar_data_url"),
    }


@router.patch("/me")
def patch_me(body: M.UserSelfUpdate, current_user: dict = Depends(get_current_user)):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        row = S.patch_user_profile(current_user["id"], data)
    except ValueError as e:
        code = str(e)
        if code == "invalid_avatar":
            raise HTTPException(
                status_code=400,
                detail="Avatar must be a data URL for a small jpeg, png, webp, or gif image.",
            ) from e
        if code == "avatar_too_large":
            raise HTTPException(status_code=400, detail="Avatar image is too large.") from e
        if code == "display_name_invalid":
            raise HTTPException(status_code=400, detail="Display name cannot be empty.") from e
        raise HTTPException(status_code=400, detail="Invalid update.") from e
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": bool(row.get("is_admin")),
        "avatar_data_url": row.get("avatar_data_url"),
    }


@router.post("/admin/users")
def admin_create_user(body: M.AdminUserCreate, _admin: dict = Depends(get_current_admin_user)):
    try:
        user = S.create_user_account(
            body.email,
            body.password,
            body.display_name,
            is_admin=body.is_admin,
        )
    except ValueError as e:
        code = str(e)
        if code == "user_exists":
            raise HTTPException(status_code=409, detail="User with this email already exists") from e
        if code == "invalid_email":
            raise HTTPException(status_code=400, detail="Invalid email") from e
        raise HTTPException(status_code=400, detail=code) from e
    return {"ok": True, "user": user}
