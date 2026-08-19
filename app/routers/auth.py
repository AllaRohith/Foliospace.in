import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services import user_auth
from app.utils.text import strip_control
from app.rate_limit import limiter

router = APIRouter(tags=["auth"])

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
from app.utils.template_globals import install_template_globals
install_template_globals(templates)

MAX_PASSWORD_LEN = 256


def _sanitize(value: str) -> str:
    return strip_control(value) if value else ""


def _no_cache(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _next_url(request: Request, fallback: str) -> str:
    nxt = _sanitize(request.query_params.get("next", ""))[:512]
    if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
        return fallback
    return nxt


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    if user_auth.require_user(request):
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    response = templates.TemplateResponse(
        request,
        "auth/signup.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Sign up — FolioSpace",
            "description": "Create a FolioSpace account. One link for every Indian professional.",
            "err": _sanitize(request.query_params.get("err", ""))[:120],
            "email": _sanitize(request.query_params.get("email", ""))[:254],
            "next": _next_url(request, "/dashboard"),
        },
    )
    return _no_cache(response)


@router.post("/signup")
@limiter.limit("5/minute")
async def signup_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
):
    ip = user_auth._client_ip(request)
    email_clean = _sanitize(email).strip().lower()[:254]
    pw = _sanitize(password)[:MAX_PASSWORD_LEN]
    if not email_clean or not pw:
        user_auth.record_login_attempt(ip, email_clean, False)
        return RedirectResponse(
            f"/signup?err=missing&email={email_clean}", status_code=303
        )
    if len(pw) < 8:
        user_auth.record_login_attempt(ip, email_clean, False)
        return RedirectResponse(
            f"/signup?err=short&email={email_clean}", status_code=303
        )
    try:
        user = user_auth.create_user(email_clean, pw)
    except HTTPException as e:
        user_auth.record_login_attempt(ip, email_clean, False)
        if e.status_code == 409:
            return RedirectResponse("/login?err=exists", status_code=303)
        detail = str(e.detail).replace(" ", "+")[:64]
        return RedirectResponse(
            f"/signup?err={detail}&email={email_clean}", status_code=303
        )
    try:
        user_auth.create_user_session(request, user["id"])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("post-signup session failed: %s", e)
        return RedirectResponse("/login?err=session", status_code=303)
    user_auth.audit_user(request, str(user["id"]), "signup.ok", target=ip)
    if user.get("prefilled_from_waitlist") and user.get("waitlist_created_at"):
        request.session["flash"] = {
            "kind": "waitlist",
            "first_seen_iso": user["waitlist_created_at"].isoformat(),
            "role": user.get("role") or "",
        }
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if user_auth.require_user(request):
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    response = templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Log in — FolioSpace",
            "description": "Log in to your FolioSpace account.",
            "err": _sanitize(request.query_params.get("err", ""))[:120],
            "email": _sanitize(request.query_params.get("email", ""))[:254],
            "next": _next_url(request, "/dashboard"),
            "locked": request.query_params.get("locked") == "1",
        },
    )
    return _no_cache(response)


@router.post("/login")
@limiter.limit("5/minute")
async def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
):
    ip = user_auth._client_ip(request)
    email_clean = _sanitize(email).strip().lower()[:254]
    pw = _sanitize(password)[:MAX_PASSWORD_LEN]
    if user_auth.is_locked_out(ip):
        user_auth.audit_user(request, None, "login.locked", target=ip)
        return RedirectResponse("/login?locked=1", status_code=303)
    if not email_clean or not pw:
        user_auth.record_login_attempt(ip, email_clean, False)
        return RedirectResponse(
            f"/login?err=missing&email={email_clean}", status_code=303
        )
    user = user_auth.find_user_by_email(email_clean)
    ok = False
    if user and not user.get("deleted_at") and user.get("password_hash"):
        ok = user_auth.verify_password(pw, user.get("password_hash"))
    user_auth.record_login_attempt(ip, email_clean, ok)
    if not ok or not user:
        user_auth.audit_user(request, None, "login.fail", target=email_clean)
        return RedirectResponse(
            f"/login?err=invalid&email={email_clean}", status_code=303
        )
    try:
        user_auth.create_user_session(request, user["id"])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("login session failed: %s", e)
        return RedirectResponse("/login?err=session", status_code=303)
    user_auth.audit_user(request, str(user["id"]), "login.ok", target=ip)
    return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)


@router.post("/logout")
async def logout(request: Request):
    uid = user_auth.current_user_id(request)
    if uid:
        user_auth.audit_user(request, uid, "logout")
    user_auth.destroy_user_session(request)
    return RedirectResponse("/", status_code=303)


@router.get("/me")
async def me(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return JSONResponse({"logged_in": False}, status_code=200)
    return JSONResponse(
        {
            "logged_in": True,
            "id": str(user["id"]),
            "email": user["email"],
            "slug": user["slug"],
            "display_name": user.get("display_name") or "",
            "role": user.get("role") or "",
            "bio": user.get("bio") or "",
            "phone": user.get("phone") or "",
            "avatar_url": user.get("avatar_url") or "",
            "is_public": bool(user.get("is_public")),
            "plan": user.get("plan") or "free",
            "is_internal": bool(user.get("is_internal")),
            "is_trial": bool(user.get("is_trial")),
            "payment_failed_at": user.get("payment_failed_at").isoformat() if user.get("payment_failed_at") else None,
            "plan_expires_at": user.get("plan_expires_at").isoformat() if user.get("plan_expires_at") else None,
        }
    )


def _user_to_context(user) -> dict:
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "slug": user["slug"],
        "display_name": user.get("display_name") or "",
        "role": user.get("role") or "",
        "bio": user.get("bio") or "",
        "phone": user.get("phone") or "",
        "avatar_url": user.get("avatar_url") or "",
        "avatar_public_id": user.get("avatar_public_id") or "",
        "is_public": bool(user.get("is_public")),
        "plan": user.get("plan") or "free",
        "plan_expires_at": user.get("plan_expires_at"),
        "payment_failed_at": user.get("payment_failed_at"),
        "is_trial": bool(user.get("is_trial")),
        "is_internal": bool(user.get("is_internal")),
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard", status_code=303)
    return RedirectResponse(f"/{user['slug']}/manage", status_code=303)


@router.get("/dashboard/profile", response_class=HTMLResponse)
async def profile_form(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard/profile", status_code=303)
    return RedirectResponse(f"/{user['slug']}/manage", status_code=303)


@router.post("/dashboard/profile")
@limiter.limit("30/minute")
async def profile_submit(
    request: Request,
    display_name: str = Form(""),
    role: str = Form(""),
    bio: str = Form(""),
    phone: str = Form(""),
    avatar_url: str = Form(""),
    is_public: str = Form(""),
):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    target = f"/{user['slug']}/manage"
    dname = (display_name or "").strip()
    if not (2 <= len(dname) <= 80):
        return RedirectResponse(f"{target}?err=display_name", status_code=303)
    bio_clean = (bio or "").strip()
    if len(bio_clean) > 280:
        return RedirectResponse(f"{target}?err=bio", status_code=303)
    phone_clean = (phone or "").strip()
    if phone_clean and not re.fullmatch(r"[+0-9 ()\-]{6,20}", phone_clean):
        return RedirectResponse(f"{target}?err=phone", status_code=303)
    avatar_clean = (avatar_url or "").strip()
    if avatar_clean and not re.fullmatch(r"https?://[^\s]+", avatar_clean):
        return RedirectResponse(f"{target}?err=avatar_url", status_code=303)
    role_clean = (role or "").strip()
    if len(role_clean) > 60:
        return RedirectResponse(f"{target}?err=role", status_code=303)
    public_flag = (is_public or "").strip().lower() in ("1", "true", "on", "yes")
    updated = user_auth.update_user_profile(
        str(user["id"]),
        display_name=dname,
        role=role_clean,
        bio=bio_clean,
        phone=phone_clean,
        avatar_url=avatar_clean,
        is_public=public_flag,
    )
    if not updated:
        return RedirectResponse(f"{target}?err=server", status_code=303)
    user_auth.audit_user(
        request,
        str(user["id"]),
        "profile.update",
        metadata={"is_public": public_flag},
    )
    return RedirectResponse(f"{target}?saved=1", status_code=303)