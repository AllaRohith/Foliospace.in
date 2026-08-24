import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

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
from app.routers import passkey
from app.routers import referral as _referral_router

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
from app.utils.template_globals import install_template_globals
install_template_globals(templates)


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


app.include_router(waitlist.router)
app.include_router(stats.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(passkey.router)


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
    from app.pricing import PRO_YEAR1_INR as _PRO_YEAR1_INR, FOUNDER_COHORT_LIMIT as _FOUNDER_COHORT_LIMIT
    import os as _os
    import psycopg as _psycopg
    from psycopg.rows import dict_row as _dict_row

    launch_iso = _LD.isoformat() if _LD else ""

    # Live waitlist count + public-folio slug list. Server-side so the
    # landing page is honest at first paint — no hardcoded 16 / 100.
    waitlist_count = 0
    founder_seats_left = None
    marquee_slugs: list[str] = []
    _db_url = _os.getenv("DATABASE_URL", "").strip()
    if _db_url:
        try:
            with _psycopg.connect(_db_url, row_factory=_dict_row) as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute("SELECT count(*) AS n FROM waitlist")
                    waitlist_count = int((_cur.fetchone() or {}).get("n", 0))
                    _cur.execute(
                        """
                        SELECT slug, display_name FROM users
                         WHERE is_public = TRUE
                           AND slug ~ '^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$'
                           AND slug NOT LIKE 'me-test-%%'
                           AND slug NOT LIKE 'avatar-test-%%'
                           AND slug NOT LIKE 'fm-test-%%'
                           AND slug NOT LIKE 'test-%%'
                         ORDER BY updated_at DESC NULLS LAST
                         LIMIT 7
                        """
                    )
                    rows = _cur.fetchall() or []
                    for r in rows:
                        slug = (r.get("slug") or "").strip()
                        if slug:
                            marquee_slugs.append(f"foliospace.in/{slug}")
                _conn.commit()
            founder_seats_left = max(0, _FOUNDER_COHORT_LIMIT - waitlist_count)
        except Exception:
            # Never break the landing page over a stats query — show 0.
            waitlist_count = 0
            founder_seats_left = _FOUNDER_COHORT_LIMIT

    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "site_name": "FolioSpace",
            "tagline": "Your story. One link. Done.",
            "page_title": "FolioSpace — One-page portfolio for Indian professionals (₹899/yr Pro)",
            "description": "FolioSpace is a one-page portfolio for Indian professionals — chefs, developers, students, consultants, shops, founders. Free forever; Pro is ₹899/yr in Year 1 (then ₹1,499/yr from Year 2), billed via UPI AutoPay.",
            "launch_iso": launch_iso,
            "waitlist_count": waitlist_count,
            "founder_seats_left": founder_seats_left,
            "marquee_slugs": marquee_slugs,
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


@app.get("/security")
async def security(request: Request):
    return templates.TemplateResponse(
        request,
        "security.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Security — FolioSpace",
            "description": "How FolioSpace is built and what we do — and don't do — to keep your data and your folios safe.",
        },
    )


@app.get("/pricing")
async def pricing(request: Request):
    from app.services import user_auth, billing as billing_svc
    from app.pricing import PRO_YEAR1_INR as _PRO_YEAR1_INR, PRO_YEAR2_INR as _PRO_YEAR2_INR
    try:
        viewer_redirect = user_auth.require_user(request)
        if viewer_redirect:
            return RedirectResponse("/dashboard/billing", status_code=303)
    except Exception:
        pass
    ctx = {
        "site_name": "FolioSpace",
        "page_title": "Pricing — FolioSpace",
        "description": f"Pro is ₹{_PRO_YEAR1_INR}/yr in Year 1, ₹{_PRO_YEAR2_INR}/yr from Year 2 — UPI AutoPay or Card AutoPay via Cashfree. Cancel any time.",
        "viewer": None,
        "grace_days_left": 0,
    }
    user = None
    try:
        user = user_auth.require_user(request)
    except Exception:
        user = None
    if user:
        ctx["viewer"] = {
            "id": str(user["id"]),
            "email": user.get("email") or "",
            "slug": user["slug"],
            "display_name": user.get("display_name") or "",
            "role": user.get("role") or "",
            "bio": user.get("bio") or "",
            "phone": user.get("phone") or "",
            "avatar_url": user.get("avatar_url") or "",
            "avatar_public_id": user.get("avatar_public_id") or "",
            "is_public": bool(user.get("is_public")),
            "is_internal": bool(user.get("is_internal")),
            "payment_failed_at": user.get("payment_failed_at"),
            "plan_expires_at": user.get("plan_expires_at"),
            "plan": user.get("plan") or "free",
            "template_id": (user.get("template_id") or "other-base").strip()[:32],
        }
        ctx["grace_days_left"] = billing_svc.grace_days_left(user)
    return templates.TemplateResponse(request, "pricing.html", ctx)


@app.get("/community")
async def community_legacy(request: Request):
    return RedirectResponse(
        url=f"/space-community{('?' + request.url.query) if request.url.query else ''}",
        status_code=308,
    )


@app.get("/space-community")
async def space_community(request: Request):
    from app.services import directory as directory_svc
    q = request.query_params.get("q", "")
    category = request.query_params.get("category", "")
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    data = directory_svc.list_directory(q=q, category=category, page=page)
    return templates.TemplateResponse(
        request,
        "community.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Space Community — FolioSpace",
            "description": "The FolioSpace marketplace. Find a chef, developer, consultant, or shop — by name, company, category, profession, or place.",
            "rows": data["rows"],
            "total": data["total"],
            "page": data["page"],
            "total_pages": data["total_pages"],
            "per_page": data["per_page"],
            "q": data["q"],
            "category": data["category"] or "all",
            "categories": directory_svc.category_options(),
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


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    from fastapi.responses import FileResponse
    fp = BASE_DIR / "static" / "llms.txt"
    if not fp.is_file():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("# FolioSpace llms.txt missing", status_code=404)
    return FileResponse(fp, media_type="text/plain; charset=utf-8")


@app.get("/llms-full.txt", include_in_schema=False)
async def llms_full_txt():
    from fastapi.responses import FileResponse
    fp = BASE_DIR / "static" / "llms-full.txt"
    if not fp.is_file():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("# FolioSpace llms-full.txt missing", status_code=404)
    return FileResponse(fp, media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml")
async def sitemap():
    from datetime import datetime, timezone
    from fastapi.responses import PlainTextResponse
    from app.services import folio as folio_svc
    from app.routers.seo_pages import list_seo_paths
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    legal_lastmod = "2026-08-15"
    public_users = folio_svc.list_public_slugs()
    urls = [
        f'  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>',
        f'  <url><loc>{base}/privacy</loc><lastmod>{legal_lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        f'  <url><loc>{base}/terms</loc><lastmod>{legal_lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        f'  <url><loc>{base}/security</loc><lastmod>{legal_lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>',
        f'  <url><loc>{base}/features</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>',
        f'  <url><loc>{base}/pricing</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority></url>',
        f'  <url><loc>{base}/space-community</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>',
    ]
    for path, _lastmod in list_seo_paths():
        urls.append(
            f'  <url><loc>{base}{path}</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>'
        )
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


_GSC_VERIFY_FILE = os.getenv("GOOGLE_SITE_VERIFICATION_FILE", "").strip()
_GSC_VERIFY_CONTENT = os.getenv("GOOGLE_SITE_VERIFICATION_CONTENT", "").strip()
if _GSC_VERIFY_FILE and _GSC_VERIFY_CONTENT:
    @app.get(f"/{_GSC_VERIFY_FILE}", include_in_schema=False)
    async def google_site_verification():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(_GSC_VERIFY_CONTENT, media_type="text/html")


from app.routers import folio as _folio_router
from app.routers import seo_pages as _seo_pages_router

# Mount SEO landing pages BEFORE the folio catch-all router so /<role-slug>
# paths resolve to the SEO page rather than a 404-folio.
app.include_router(_seo_pages_router.router)
# Phase C: referral router MUST mount BEFORE the folio catch-all so /ref/{code}
# resolves to the referral landing (303 to /signup) instead of trying to render
# 'ref' as a folio slug. RESERVED_SLUGS also blocks 'ref' as a defense-in-depth.
app.include_router(_referral_router.router)
app.include_router(_folio_router.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=DEBUG)
