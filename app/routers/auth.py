import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.services import user_auth
from app.services import auth_tokens
from app.services import email_service
from app.services import oauth as oauth_svc
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
            "oauth_providers": oauth_svc.configured_providers(),
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
    user_auth.audit_user(request, str(user["id"]), "signup.created", target=ip)
    try:
        code, _expires_at = auth_tokens.issue_otp(email_clean)
        email_service.send_otp_email(email_clean, code)
        user_auth.audit_user(request, str(user["id"]), "signup.otp.issued", target=ip)
    except Exception as e:
        logger.exception("signup OTP send failed for %s: %s", email_clean, e)
        return RedirectResponse("/signup?err=otp-send", status_code=303)
    if user.get("prefilled_from_waitlist") and user.get("waitlist_created_at"):
        request.session["flash"] = {
            "kind": "waitlist",
            "first_seen_iso": user["waitlist_created_at"].isoformat(),
            "role": user.get("role") or "",
        }
    return RedirectResponse(f"/signup/verify?email={email_clean}", status_code=303)


@router.get("/signup/verify", response_class=HTMLResponse)
async def signup_verify_form(request: Request):
    if user_auth.require_user(request):
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    email = _sanitize(request.query_params.get("email", ""))[:254]
    err = _sanitize(request.query_params.get("err", ""))[:64]
    cooldown = auth_tokens.resend_cooldown_remaining(email)
    response = templates.TemplateResponse(
        request,
        "auth/signup_verify.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Verify your email — FolioSpace",
            "description": "Enter the 6-digit code we sent to your email to finish signing up.",
            "email": email,
            "err": err,
            "resend_cooldown": cooldown,
        },
    )
    return _no_cache(response)


@router.post("/signup/verify")
@limiter.limit("10/minute")
async def signup_verify_submit(request: Request, email: str = Form(""), code: str = Form("")):
    ip = user_auth._client_ip(request)
    email_clean = _sanitize(email).strip().lower()[:254]
    code_clean = _sanitize(code).strip()[:8]
    if not email_clean or not code_clean:
        return RedirectResponse(f"/signup/verify?err=missing&email={email_clean}", status_code=303)
    ok, reason = auth_tokens.verify_otp(email_clean, code_clean)
    if not ok:
        if email_clean:
            try:
                user = user_auth.find_user_by_email(email_clean)
                if user:
                    user_auth.audit_user(request, str(user["id"]), f"signup.otp.{reason}", target=ip)
            except Exception:
                pass
        else:
            user_auth.audit_user(request, None, f"signup.otp.{reason}", target=ip)
        return RedirectResponse(f"/signup/verify?err={reason}&email={email_clean}", status_code=303)
    user = user_auth.find_user_by_email(email_clean)
    if not user:
        return RedirectResponse(f"/signup?err=missing", status_code=303)
    try:
        user_auth.mark_email_verified(str(user["id"]))
    except Exception as e:
        logger.exception("mark_email_verified failed: %s", e)
        return RedirectResponse(f"/signup/verify?err=server&email={email_clean}", status_code=303)
    auth_tokens.consume_otp(email_clean)
    user_auth.audit_user(request, str(user["id"]), "signup.otp.verified", target=ip)
    try:
        user_auth.create_user_session(request, user["id"])
    except Exception as e:
        logger.exception("post-verify session failed: %s", e)
        return RedirectResponse("/login?err=session", status_code=303)
    return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)


@router.post("/signup/resend")
@limiter.limit("3/minute")
async def signup_resend(request: Request, email: str = Form("")):
    email_clean = _sanitize(email).strip().lower()[:254]
    if not email_clean:
        return RedirectResponse("/signup", status_code=303)
    cooldown = auth_tokens.resend_cooldown_remaining(email_clean)
    if cooldown > 0:
        return RedirectResponse(f"/signup/verify?err=cooldown&email={email_clean}", status_code=303)
    try:
        user = user_auth.find_user_by_email(email_clean)
        if user and not user.get("email_verified") and not user.get("deleted_at"):
            code, _expires_at = auth_tokens.issue_otp(email_clean)
            email_service.send_otp_email(email_clean, code)
            user_auth.audit_user(request, str(user["id"]), "signup.otp.resent")
    except Exception as e:
        logger.exception("resend OTP failed: %s", e)
    return RedirectResponse(f"/signup/verify?err=resent&email={email_clean}", status_code=303)


@router.get("/forgot", response_class=HTMLResponse)
async def forgot_form(request: Request):
    if user_auth.require_user(request):
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    response = templates.TemplateResponse(
        request,
        "auth/forgot.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Forgot password — FolioSpace",
            "description": "Get a reset link sent to your email.",
            "err": _sanitize(request.query_params.get("err", ""))[:64],
            "email": _sanitize(request.query_params.get("email", ""))[:254],
            "sent": request.query_params.get("sent") == "1",
        },
    )
    return _no_cache(response)


@router.post("/forgot")
@limiter.limit("5/minute")
async def forgot_submit(request: Request, email: str = Form("")):
    ip = user_auth._client_ip(request)
    email_clean = _sanitize(email).strip().lower()[:254]
    if not email_clean or "@" not in email_clean or len(email_clean) > 254:
        return RedirectResponse("/forgot?err=missing", status_code=303)
    try:
        user = user_auth.find_user_by_email(email_clean)
        if user and not user.get("deleted_at") and user.get("password_hash"):
            token = auth_tokens.issue_reset_token(str(user["id"]))
            public_base = os.getenv("PUBLIC_URL", "https://foliospace.in").strip().rstrip("/")
            reset_link = f"{public_base}/reset?token={token}"
            try:
                email_service.send_password_reset_email(
                    email_clean, reset_link, auth_tokens.RESET_TTL_MINUTES
                )
                user_auth.audit_user(request, str(user["id"]), "password.reset.sent", target=ip)
            except Exception as e:
                logger.exception("reset email send failed for %s: %s", email_clean, e)
        else:
            try:
                user_auth.hash_password("timing-safe-noop")
            except Exception:
                pass
    except Exception as e:
        logger.exception("forgot submit failed: %s", e)
    return RedirectResponse("/forgot?sent=1", status_code=303)


@router.get("/reset", response_class=HTMLResponse)
async def reset_form(request: Request, token: str = ""):
    if user_auth.require_user(request):
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    err = _sanitize(request.query_params.get("err", ""))[:64]
    token_clean = _sanitize(token)[:256]
    response = templates.TemplateResponse(
        request,
        "auth/reset.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Reset password — FolioSpace",
            "description": "Set a new password for your FolioSpace account.",
            "token": token_clean,
            "err": err,
        },
    )
    return _no_cache(response)


@router.post("/reset")
@limiter.limit("5/minute")
async def reset_submit(
    request: Request,
    token: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
):
    ip = user_auth._client_ip(request)
    token_clean = _sanitize(token).strip()[:256]
    pw = _sanitize(password)[:MAX_PASSWORD_LEN]
    cf = _sanitize(confirm)[:MAX_PASSWORD_LEN]
    if not token_clean:
        return RedirectResponse("/forgot?err=missing", status_code=303)
    if not pw or len(pw) < 8:
        return RedirectResponse(f"/reset?err=short&token={token_clean}", status_code=303)
    if pw != cf:
        return RedirectResponse(f"/reset?err=match&token={token_clean}", status_code=303)
    ok, payload = auth_tokens.consume_reset_token(token_clean, user_auth.hash_password(pw))
    if not ok:
        user_auth.audit_user(request, None, f"password.reset.{payload}", target=ip)
        return RedirectResponse(f"/reset?err={payload}&token={token_clean}", status_code=303)
    user_id = payload
    if not user_auth.set_password(user_id, pw):
        return RedirectResponse(f"/reset?err=server&token={token_clean}", status_code=303)
    user_auth.audit_user(request, user_id, "password.reset.done", target=ip)
    try:
        user = user_auth.find_user_by_id(user_id)
        if user and not user.get("deleted_at"):
            user_auth.create_user_session(request, user_id)
    except Exception as e:
        logger.exception("post-reset session failed: %s", e)
    return RedirectResponse("/login?ok=reset", status_code=303)


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
            "ok": _sanitize(request.query_params.get("ok", ""))[:64],
            "oauth_providers": oauth_svc.configured_providers(),
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
        if not user.get("email_verified") and not user.get("is_internal"):
            try:
                code, _expires_at = auth_tokens.issue_otp(email_clean)
                email_service.send_otp_email(email_clean, code)
                user_auth.audit_user(request, str(user["id"]), "login.otp.resent", target=ip)
            except Exception as e:
                logger.exception("login OTP resend failed for %s: %s", email_clean, e)
            return RedirectResponse(f"/signup/verify?email={email_clean}&err=verify", status_code=303)
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
        "template_id": (user.get("template_id") or "t1").strip()[:32],
    }


@router.get("/auth/oauth/{provider}")
async def oauth_start(request: Request, provider: str, intent: str = "login"):
    pid = _sanitize(provider).strip().lower()[:16]
    if pid not in oauth_svc.PROVIDERS:
        return RedirectResponse("/login?err=oauth-provider", status_code=303)
    if not oauth_svc.is_configured(pid):
        return RedirectResponse("/login?err=oauth-not-configured", status_code=303)
    link_mode = (intent or "").strip().lower() == "link"
    if link_mode:
        viewer = user_auth.require_user(request)
        if not viewer:
            return RedirectResponse("/login?err=oauth-link-needs-auth", status_code=303)
    state = oauth_svc.generate_state()
    if link_mode and viewer:
        attach_uri = f"{os.getenv('OAUTH_REDIRECT_BASE') or os.getenv('PUBLIC_URL') or 'https://foliospace.in'}/auth/oauth/{pid}/attach"
        authorize_url = oauth_svc.build_authorize_url(pid, state, redirect_uri=attach_uri)
    else:
        authorize_url = oauth_svc.build_authorize_url(pid, state)
    if not authorize_url:
        if link_mode:
            return RedirectResponse(f"/{viewer['slug']}/manage?err=oauth-start", status_code=303)
        return RedirectResponse("/login?err=oauth-start", status_code=303)
    response = RedirectResponse(authorize_url, status_code=303)
    response.set_cookie(
        "fs_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/auth/oauth",
    )
    response.set_cookie(
        "fs_oauth_provider",
        pid,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/auth/oauth",
    )
    if link_mode:
        response.set_cookie(
            "fs_oauth_intent",
            "link",
            max_age=600,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/auth/oauth",
        )
        user_auth.audit_user(request, str(viewer["id"]), f"oauth.{pid}.link.start")
    else:
        user_auth.audit_user(request, None, f"oauth.{pid}.start")
    return response


@router.get("/auth/oauth/{provider}/callback")
async def oauth_callback(request: Request, provider: str):
    ip = user_auth._client_ip(request)
    pid = _sanitize(provider).strip().lower()[:16]
    if pid not in oauth_svc.PROVIDERS:
        return RedirectResponse("/login?err=oauth-provider", status_code=303)
    if not oauth_svc.is_configured(pid):
        return RedirectResponse("/login?err=oauth-not-configured", status_code=303)
    code = _sanitize(request.query_params.get("code", ""))[:512]
    state_in = _sanitize(request.query_params.get("state", ""))[:128]
    state_cookie = request.cookies.get("fs_oauth_state", "")
    pid_cookie = request.cookies.get("fs_oauth_provider", "")
    response = RedirectResponse("/login?err=oauth", status_code=303)
    response.delete_cookie("fs_oauth_state", path="/auth/oauth")
    response.delete_cookie("fs_oauth_provider", path="/auth/oauth")
    if not code:
        return response
    if not state_in or not state_cookie or state_in != state_cookie:
        user_auth.audit_user(request, None, f"oauth.{pid}.state-mismatch", target=ip)
        return response
    if pid_cookie and pid_cookie != pid:
        return response
    profile = oauth_svc.complete(pid, code)
    if not profile or not profile.get("uid") or not profile.get("email"):
        user_auth.audit_user(request, None, f"oauth.{pid}.profile-failed", target=ip)
        return response
    try:
        user = user_auth.find_user_by_provider_uid(pid, profile["uid"])
        if not user:
            existing = user_auth.find_user_by_email(profile["email"])
            if existing and not existing.get("deleted_at"):
                response = RedirectResponse(
                    f"/login?err=oauth-link-needed&email={profile['email']}", status_code=303
                )
                return response
            user = user_auth.create_user_from_oauth(
                email=profile["email"],
                provider=pid,
                provider_uid=profile["uid"],
                display_name=profile.get("name") or "",
            )
            if not user:
                user_auth.audit_user(request, None, f"oauth.{pid}.create-failed", target=ip)
                return response
            user_auth.audit_user(request, str(user["id"]), f"oauth.{pid}.signup", target=ip)
        else:
            user_auth.link_social_account(str(user["id"]), pid, profile["uid"], profile["email"])
            user_auth.audit_user(request, str(user["id"]), f"oauth.{pid}.login", target=ip)
        try:
            user_auth.create_user_session(request, user["id"])
        except Exception as e:
            logger.exception("oauth session create failed: %s", e)
            return RedirectResponse("/login?err=session", status_code=303)
        return RedirectResponse(_next_url(request, "/dashboard"), status_code=303)
    except Exception as e:
        logger.exception("oauth callback failed: %s", e)
        return RedirectResponse("/login?err=oauth", status_code=303)


@router.get("/auth/oauth/{provider}/attach")
async def oauth_attach(request: Request, provider: str):
    ip = user_auth._client_ip(request)
    viewer = user_auth.require_user(request)
    pid = _sanitize(provider).strip().lower()[:16]
    fallback_target = f"/{viewer['slug']}/manage" if viewer else "/login"
    if not viewer:
        response = RedirectResponse("/login?err=oauth-link-needs-auth", status_code=303)
        response.delete_cookie("fs_oauth_state", path="/auth/oauth")
        response.delete_cookie("fs_oauth_provider", path="/auth/oauth")
        response.delete_cookie("fs_oauth_intent", path="/auth/oauth")
        return response
    if pid not in oauth_svc.PROVIDERS:
        response = RedirectResponse(f"{fallback_target}?err=oauth-provider", status_code=303)
        response.delete_cookie("fs_oauth_state", path="/auth/oauth")
        response.delete_cookie("fs_oauth_provider", path="/auth/oauth")
        response.delete_cookie("fs_oauth_intent", path="/auth/oauth")
        return response
    if not oauth_svc.is_configured(pid):
        response = RedirectResponse(f"{fallback_target}?err=oauth-not-configured", status_code=303)
        response.delete_cookie("fs_oauth_state", path="/auth/oauth")
        response.delete_cookie("fs_oauth_provider", path="/auth/oauth")
        response.delete_cookie("fs_oauth_intent", path="/auth/oauth")
        return response
    code = _sanitize(request.query_params.get("code", ""))[:512]
    state_in = _sanitize(request.query_params.get("state", ""))[:128]
    state_cookie = request.cookies.get("fs_oauth_state", "")
    intent_cookie = request.cookies.get("fs_oauth_intent", "")
    pid_cookie = request.cookies.get("fs_oauth_provider", "")
    if pid_cookie and pid_cookie != pid:
        user_auth.audit_user(request, str(viewer["id"]), f"oauth.{pid}.attach.provider-mismatch", target=ip)
    response = RedirectResponse(f"{fallback_target}?err=oauth-attach", status_code=303)
    response.delete_cookie("fs_oauth_state", path="/auth/oauth")
    response.delete_cookie("fs_oauth_provider", path="/auth/oauth")
    response.delete_cookie("fs_oauth_intent", path="/auth/oauth")
    if not code or not state_in or state_in != state_cookie or intent_cookie != "link":
        user_auth.audit_user(request, str(viewer["id"]), f"oauth.{pid}.attach.state-mismatch", target=ip)
        return response
    profile = oauth_svc.complete(pid, code)
    if not profile or not profile.get("uid") or not profile.get("email"):
        user_auth.audit_user(request, str(viewer["id"]), f"oauth.{pid}.attach.profile-failed", target=ip)
        return response
    existing = user_auth.find_user_by_provider_uid(pid, profile["uid"])
    if existing and str(existing.get("id") or "") != str(viewer["id"]):
        user_auth.audit_user(
            request,
            str(viewer["id"]),
            f"oauth.{pid}.attach.already-linked",
            target=str(existing.get("id")),
        )
        return RedirectResponse(f"{fallback_target}?err=oauth-already-linked", status_code=303)
    try:
        ok = user_auth.link_social_account(str(viewer["id"]), pid, profile["uid"], profile["email"])
    except Exception as e:
        logger.exception("attach link_social_account failed: %s", e)
        ok = False
    if not ok:
        return response
    user_auth.audit_user(
        request,
        str(viewer["id"]),
        f"oauth.{pid}.linked",
        target=profile["uid"][:255],
    )
    return RedirectResponse(f"{fallback_target}?saved=oauth", status_code=303)


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