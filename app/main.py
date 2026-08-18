import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.rate_limit import limiter
from starlette.middleware.gzip import GZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from starlette.middleware.sessions import SessionMiddleware

from app.middleware import install_security
from app.routers import admin
from app.routers import auth
from app.routers import waitlist
from app.routers import stats
from app.routers import folio
from app.routers import billing

BASE_DIR = Path(__file__).resolve().parent

_RAW_ENV = os.getenv("ENV") or os.getenv("APP_ENV") or "production"
ENV = _RAW_ENV.lower()
DEBUG = ENV in ("dev", "development", "local") and os.getenv("DEBUG", "0") == "1"

_proxy_trusted = (
    {"*.render.com", "render.com", "127.0.0.1", "localhost"}
    if ENV == "production"
    else "*"
)

app = FastAPI(
    title="FolioSpace",
    description="A portfolio for everyone. Built for WhatsApp, LinkedIn, and the Indian web.",
    version="0.1.0",
    docs_url=None if not DEBUG else "/docs",
    redoc_url=None if not DEBUG else "/redoc",
    openapi_url=None if not DEBUG else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

install_security(app)

app.add_middleware(GZipMiddleware, minimum_size=512)

_session_secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
if not _session_secret:
    if ENV == "production":
        raise RuntimeError("ADMIN_SESSION_SECRET must be set in production.")
    _session_secret = "dev-only-not-secret-change-me"

_user_session_secret = os.getenv("USER_SESSION_SECRET", "").strip()
if not _user_session_secret:
    if ENV == "production":
        raise RuntimeError("USER_SESSION_SECRET must be set in production.")
    _user_session_secret = "dev-only-user-not-secret-change-me"

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="fs_admin",
    max_age=24 * 3600,
    same_site="lax",
    https_only=ENV == "production",
    path="/",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=_user_session_secret,
    session_cookie="fs_usr",
    max_age=30 * 24 * 3600,
    same_site="lax",
    https_only=ENV == "production",
    path="/",
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_proxy_trusted)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["asset_v"] = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "dev")[:8]


def _is_launched_now() -> bool:
    from app.services.email_service import is_launched
    try:
        return bool(is_launched())
    except Exception:
        return False


_orig_template_response = templates.TemplateResponse


def _patched_template_response(*args, **kwargs):
    if "context" in kwargs and isinstance(kwargs["context"], dict):
        kwargs["context"].setdefault("launched", _is_launched_now())
    elif len(args) >= 3 and isinstance(args[2], dict):
        ctx = dict(args[2])
        ctx.setdefault("launched", _is_launched_now())
        args = (args[0], args[1], ctx) + args[3:]
    return _orig_template_response(*args, **kwargs)


templates.TemplateResponse = _patched_template_response


def _nav_user(request: Request):
    from app.services import user_auth
    try:
        user = user_auth.require_user(request)
    except Exception:
        return None
    if not user:
        return None
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "slug": user["slug"],
        "display_name": user.get("display_name") or "",
        "role": user.get("role") or "",
    }


templates.env.globals["nav_user"] = _nav_user

app.include_router(waitlist.router)
app.include_router(stats.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(billing.router)


ERROR_COPY = {
    404: {
        "code": "404",
        "headline": 'This page hasn&rsquo;t been built <em>yet.</em>',
        "sub": "Maybe it never will be. Either way, the door is back that way.",
        "description": "That page doesn't exist (yet) on FolioSpace — your portfolio link for every Indian professional.",
    },
    422: {
        "code": "422",
        "headline": 'That data didn&rsquo;t add up.',
        "sub": "Check the email and try once more. We're not picky, just specific.",
        "description": "The form data didn't validate. FolioSpace needs a real email and a real role before adding you to the waitlist.",
    },
    500: {
        "code": "500",
        "headline": 'Something <em>broke.</em>',
        "sub": "It happens. We're already looking at it — try again in a minute.",
        "description": "FolioSpace hit an unexpected error. The team has been notified — try again in a minute.",
    },
    503: {
        "code": "503",
        "headline": 'We&rsquo;re briefly <em>asleep.</em>',
        "sub": "Render's free tier wakes up when poked. Give it ~30 seconds and reload.",
        "description": "FolioSpace is briefly unavailable — the free Render tier spins down after inactivity. Give it ~30 seconds and reload.",
    },
}


def _render_error(request: Request, status_code: int):
    copy = ERROR_COPY.get(status_code, ERROR_COPY[500])
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "site_name": "FolioSpace",
            "page_title": f"{copy['code']} — FolioSpace",
            "description": "FolioSpace error page.",
            **copy,
        },
        status_code=status_code,
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return _render_error(request, 404)


@app.exception_handler(422)
async def unprocessable(request: Request, exc):
    return _render_error(request, 422)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return _render_error(request, 500)


@app.exception_handler(503)
async def unavailable(request: Request, exc):
    return _render_error(request, 503)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def landing(request: Request):
    from app.services.email_service import LAUNCH_DATE as _LD
    launch_iso = _LD.isoformat() if _LD else ""
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "site_name": "FolioSpace",
            "tagline": "Your story. One link. Done.",
            "page_title": "FolioSpace — Your portfolio. Your link. Done.",
            "description": "One link for every Indian pro — chefs, devs, students, consultants, shops, founders. ₹150 setup, ₹99/mo.",
            "launch_iso": launch_iso,
        },
    )


@app.get("/privacy")
async def privacy(request: Request):
    return templates.TemplateResponse(
        request,
        "privacy.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Privacy — FolioSpace",
            "description": "FolioSpace privacy policy. What we collect when you join the waitlist, how we use it, retention, and how to ask us to delete it.",
        },
    )


@app.get("/terms")
async def terms(request: Request):
    return templates.TemplateResponse(
        request,
        "terms.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Terms — FolioSpace",
            "description": "FolioSpace terms of service. Rules for the waitlist, conduct, refunds, liability, and what to expect when the product launches.",
        },
    )


@app.get("/features")
async def features(request: Request):
    return templates.TemplateResponse(
        request,
        "features.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Features — FolioSpace",
            "description": "GitHub + LinkedIn import are next on the FolioSpace roadmap. See exactly what each integration pulls, the honest limits, and when to expect them.",
        },
    )


@app.get("/community")
async def community_legacy(request: Request):
    return RedirectResponse(
        url=f"/space-community{('?' + request.url.query) if request.url.query else ''}",
        status_code=308,
    )


@app.get("/space-community")
async def space_community(request: Request):
    return templates.TemplateResponse(
        request,
        "community.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Space Community — FolioSpace",
            "description": "The FolioSpace marketplace. Find a chef, developer, consultant, or shop — by name, company, category, profession, or place.",
        },
    )


@app.get("/robots.txt")
async def robots():
    from fastapi.responses import PlainTextResponse
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /dashboard/\n"
        "Disallow: /api/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    response = PlainTextResponse(content=content, media_type="text/plain")
    response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
    return response


@app.get("/sitemap.xml")
async def sitemap():
    from datetime import datetime, timezone
    from fastapi.responses import PlainTextResponse
    from app.services import folio as folio_svc
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    legal_lastmod = "2026-08-15"
    public_users = folio_svc.list_public_slugs()
    urls = [
        f'  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'  <url><loc>{base}/privacy</loc><lastmod>{legal_lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        f'  <url><loc>{base}/terms</loc><lastmod>{legal_lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        f'  <url><loc>{base}/features</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>',
        f'  <url><loc>{base}/space-community</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>',
    ]
    for slug, lastmod in public_users:
        lm = lastmod or today
        urls.append(
            f'  <url><loc>{base}/{slug}</loc><lastmod>{lm}</lastmod><changefreq>weekly</changefreq><priority>0.5</priority></url>'
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n"
        '</urlset>\n'
    )
    response = PlainTextResponse(content=body, media_type="application/xml")
    response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
    return response


from app.routers import folio as _folio_router
app.include_router(_folio_router.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=DEBUG)
