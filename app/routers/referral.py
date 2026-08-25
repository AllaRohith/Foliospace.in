"""Phase C referral router — public `/ref/{code}` landing + dashboard page.

`GET /ref/{code}` is the entry point for someone clicking a referral link.
It validates the code, resolves the referrer's user UUID, stores it in a
30-day cookie (`fs_ref`), and redirects to /signup. If the code is unknown
or malformed, no cookie is set and we still redirect to /signup (no
enumeration leak).

`GET /dashboard/referrals` is the dashboard page — auth-required, shows
the user's own code, the count of active referrals, copy-to-clipboard,
and share buttons.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import referrals as referrals_svc
from app.services import user_auth

router = APIRouter(tags=["referral"])
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
from app.utils.template_globals import install_template_globals
install_template_globals(templates)


_REF_COOKIE = "fs_ref"
_REF_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def _no_cache(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _sanitize_code(code: str) -> str:
    """Trim + length-cap + lowercase. Keep only hex/word chars."""
    return "".join(ch for ch in (code or "").strip().lower()[:64] if ch.isalnum() or ch == "_-")


@router.get("/ref/{code}")
async def ref_landing(code: str):
    """Resolve a referral code, set fs_ref cookie, redirect to /signup.

    Anti-enumeration: always 303, even for unknown codes. Only sets the
    cookie when the code resolves to a real user. Never reveals whether
    a given code exists.
    """
    clean = _sanitize_code(code)
    response = RedirectResponse(url="/signup", status_code=303)
    if clean:
        referrer_id = referrals_svc.resolve_code_to_user_id(clean)
        if referrer_id:
            response.set_cookie(
                key=_REF_COOKIE,
                value=referrer_id,
                max_age=_REF_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=True,
                path="/",
            )
            logger.info("ref_attribution_set code=%s referrer=%s", clean[:8], referrer_id[:8])
    return response


@router.get("/dashboard/referrals", response_class=HTMLResponse)
async def dashboard_referrals(request: Request):
    """Auth-required page. Shows the user's referral code + count + share UI."""
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard/referrals", status_code=303)

    progress = referrals_svc.progress_for_user(str(user["id"]))
    code = (user.get("referral_code") or "").strip()
    if not code:
        code = user_auth.ensure_referral_code(str(user["id"]))
    # Referral URL uses PUBLIC_BASE_URL (or request.base_url as fallback).
    base_url = (
        request.headers.get("x-forwarded-proto", request.url.scheme)
        + "://"
        + request.headers.get("x-forwarded-host", request.url.netloc)
    )
    referral_url = f"{base_url.rstrip('/')}/ref/{code}"

    response = templates.TemplateResponse(
        request,
        "dashboard/referrals.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Referrals · FolioSpace",
            "description": "Refer friends to FolioSpace. Unlock the Year-1 price forever after 10 verified friends.",
            "user": user,
            "progress": progress,
            "ref_threshold": referrals_svc.REFERRAL_THRESHOLD,
            "referral_code": code,
            "referral_url": referral_url,
            "nav_active": "referrals",
        },
    )
    return _no_cache(response)
