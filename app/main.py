import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.rate_limit import limiter
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from starlette.middleware.sessions import SessionMiddleware

from app.middleware import install_security
from app.routers import admin
from app.routers import waitlist
from app.routers import stats

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

_session_secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
if not _session_secret:
    if ENV == "production":
        raise RuntimeError("ADMIN_SESSION_SECRET must be set in production.")
    _session_secret = "dev-only-not-secret-change-me"

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="fs_admin",
    max_age=24 * 3600,
    same_site="lax",
    https_only=ENV == "production",
    path="/",
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_proxy_trusted)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["asset_v"] = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "dev")[:8]

app.include_router(waitlist.router)
app.include_router(stats.router)
app.include_router(admin.router)


ERROR_COPY = {
    404: {
        "code": "404",
        "headline": 'This page hasn&rsquo;t been built <em>yet.</em>',
        "sub": "Maybe it never will be. Either way, the door is back that way.",
    },
    422: {
        "code": "422",
        "headline": 'That data didn&rsquo;t add up.',
        "sub": "Check the email and try once more. We're not picky, just specific.",
    },
    500: {
        "code": "500",
        "headline": 'Something <em>broke.</em>',
        "sub": "It happens. We're already looking at it — try again in a minute.",
    },
    503: {
        "code": "503",
        "headline": 'We&rsquo;re briefly <em>asleep.</em>',
        "sub": "Render's free tier wakes up when poked. Give it ~30 seconds and reload.",
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
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "site_name": "FolioSpace",
            "tagline": "Your story. One link. Done.",
            "page_title": "FolioSpace — Your portfolio. Your link. Done.",
            "description": "Stop sending CVs. Send a link. FolioSpace is one page for every Indian professional — chefs, developers, students, consultants, shop owners, agencies, founders. ₹150 setup, ₹99/month.",
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
            "description": "FolioSpace privacy policy. What we collect, how we use it, and how to ask us to delete it.",
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
            "description": "FolioSpace terms of service. The rules of the road for using the waitlist and the eventual product.",
        },
    )


@app.get("/robots.txt")
async def robots():
    from fastapi.responses import PlainTextResponse
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(content=content, media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap():
    from datetime import datetime, timezone
    from fastapi.responses import PlainTextResponse
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        '</urlset>\n'
    )
    return PlainTextResponse(content=body, media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=DEBUG)
