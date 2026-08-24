"""WebAuthn / Passkey HTTP routes.

Mirrors `app/routers/auth.py` conventions:
- Jinja2Templates from local templates dir (per the asset_v memory note).
- slowapi rate limits.
- Returns JSON for ceremony endpoints, HTML for the manage page.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services import passkey as passkey_svc
from app.services import user_auth
from app.utils.template_globals import install_template_globals
from app.utils.text import strip_control
from app.rate_limit import limiter

router = APIRouter(tags=["passkey"])
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
install_template_globals(templates)


def _next_url(request: Request, fallback: str) -> str:
    nxt = strip_control(request.query_params.get("next", ""))[:512]
    if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
        return fallback
    return nxt


def _client_ip(request: Request) -> str:
    return user_auth._client_ip(request)


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:512]


# ── Login ─────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/passkey/login/begin")
@limiter.limit("20/minute")
async def passkey_login_begin_get(request: Request):
    """Discoverable credential login (no email). Same JSON shape as the POST variant
    (allowCredentials is empty here since we don't yet know the user).
    """
    try:
        payload = passkey_svc.start_login(
            email_or_none=None,
            ip=_client_ip(request),
            ua=_ua(request),
        )
    except passkey_svc.PasskeyError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "options": payload})


@router.post("/passkey/login/begin")
@limiter.limit("20/minute")
async def passkey_login_begin_post(request: Request):
    """Email-scoped login begin. Body: `{"email": "..."}` (optional).

    If the email matches a user with an enrolled passkey, allowCredentials will
    contain their credential descriptors. Anti-enumeration: unknown emails get
    an empty allowCredentials with the same shape.
    """
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    email = strip_control(str(raw.get("email", "")))[:254].strip().lower() or None
    try:
        payload = passkey_svc.start_login(
            email_or_none=email,
            ip=_client_ip(request),
            ua=_ua(request),
        )
    except passkey_svc.PasskeyError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "options": payload})


@router.post("/passkey/login/complete")
@limiter.limit("10/minute")
async def passkey_login_complete(request: Request):
    """Verify the assertion, then create the session."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "code": "bad_request", "message": "Invalid JSON."}, status_code=400)
    assertion = body.get("assertion") if isinstance(body, dict) else None
    next_url = _next_url(request, "/dashboard")
    if not isinstance(assertion, dict):
        return JSONResponse({"ok": False, "code": "bad_request", "message": "Missing assertion."}, status_code=400)
    try:
        user_id = passkey_svc.complete_login(assertion, request)
    except passkey_svc.PasskeyCounterRegression:
        # Don't tell the attacker that cloning was detected.
        return JSONResponse({"ok": False, "code": "sign_in_failed", "message": "Sign-in failed."}, status_code=401)
    except passkey_svc.PasskeyError as e:
        logger.info("passkey login fail code=%s msg=%s", e.code, e)
        return JSONResponse({"ok": False, "code": "sign_in_failed", "message": "Sign-in failed."}, status_code=401)
    except Exception as e:  # noqa: BLE001
        logger.exception("passkey login unexpected: %s", e)
        return JSONResponse({"ok": False, "code": "sign_in_failed", "message": "Sign-in failed."}, status_code=401)
    try:
        user_auth.create_user_session(request, user_id)
    except Exception as e:
        logger.exception("passkey session create failed: %s", e)
        return JSONResponse({"ok": False, "code": "session", "message": "Could not start session."}, status_code=500)
    user_auth.audit_user(request, user_id, "passkey.login.complete", target=_client_ip(request))
    return JSONResponse({"ok": True, "redirect": next_url})


# ── Registration ─────────────────────────────────────────────────────────────────────────────────────────

@router.post("/passkey/register/begin")
@limiter.limit("10/minute")
async def passkey_register_begin(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return JSONResponse({"ok": False, "code": "auth", "message": "Sign in first."}, status_code=401)
    try:
        options = passkey_svc.start_registration(
            str(user["id"]),
            ip=_client_ip(request),
            ua=_ua(request),
        )
    except passkey_svc.PasskeyUnverifiedEmail:
        return JSONResponse(
            {"ok": False, "code": "unverified_email", "message": "Verify your email first."},
            status_code=400,
        )
    except passkey_svc.PasskeyAlreadyEnrolled:
        return JSONResponse(
            {"ok": False, "code": "already_enrolled", "message": "You already have a passkey. Remove it first."},
            status_code=409,
        )
    except passkey_svc.PasskeyError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "options": options})


@router.post("/passkey/register/complete")
@limiter.limit("10/minute")
async def passkey_register_complete(request: Request, body: dict = Body(...)):
    user = user_auth.require_user(request)
    if not user:
        return JSONResponse({"ok": False, "code": "auth", "message": "Sign in first."}, status_code=401)
    attestation = body.get("attestation") if isinstance(body, dict) else None
    friendly_name = (body.get("friendly_name") if isinstance(body, dict) else None) or ""
    friendly_name = strip_control(str(friendly_name))[:80].strip() or None
    if not isinstance(attestation, dict):
        return JSONResponse({"ok": False, "code": "bad_request", "message": "Missing attestation."}, status_code=400)
    try:
        passkey_svc.complete_registration(str(user["id"]), attestation, friendly_name, request)
    except passkey_svc.PasskeyUnverifiedEmail:
        return JSONResponse(
            {"ok": False, "code": "unverified_email", "message": "Verify your email first."},
            status_code=400,
        )
    except passkey_svc.PasskeyAlreadyEnrolled:
        return JSONResponse(
            {"ok": False, "code": "already_enrolled", "message": "You already have a passkey. Remove it first."},
            status_code=409,
        )
    except passkey_svc.PasskeyAttestationFailed as e:
        logger.info("passkey register fail code=%s msg=%s", e.code, e)
        return JSONResponse({"ok": False, "code": "attestation_failed", "message": "Could not register passkey."}, status_code=400)
    except passkey_svc.PasskeyError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "redirect": "/dashboard/passkeys?saved=passkey"})


# ── Manage page ──────────────────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard/passkeys", response_class=HTMLResponse)
async def passkeys_page(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard/passkeys", status_code=303)
    items = passkey_svc.list_user_passkeys(str(user["id"]))
    response = templates.TemplateResponse(
        request,
        "dashboard/passkeys.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Passkeys — FolioSpace",
            "description": "Manage your sign-in passkey.",
            "nav_active": "passkeys",
            "user": user,
            "u": {
                "id": str(user["id"]),
                "email": user["email"],
                "slug": user["slug"],
                "display_name": user.get("display_name") or "",
                "is_pro": user.get("plan") == "pro",
                "email_verified": bool(user.get("email_verified")),
            },
            "passkeys": items,
            "saved": strip_control(request.query_params.get("saved", ""))[:32],
            "err": strip_control(request.query_params.get("err", ""))[:64],
        },
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.delete("/dashboard/passkey/{credential_id}")
@limiter.limit("10/minute")
async def passkey_revoke(request: Request, credential_id: str):
    user = user_auth.require_user(request)
    if not user:
        return JSONResponse({"ok": False, "code": "auth"}, status_code=401)
    # credential_id arrives URL-encoded base64url; strip_control for safety.
    cred_b64u = strip_control(credential_id)[:512]
    ok = passkey_svc.revoke_passkey(str(user["id"]), cred_b64u, request)
    if not ok:
        return JSONResponse({"ok": False, "code": "not_found"}, status_code=404)
    return JSONResponse({"ok": True})
