import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import folio as folio_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["folio"])

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
import os as _os
templates.env.globals["asset_v"] = (_os.getenv("RENDER_GIT_COMMIT") or _os.getenv("GIT_COMMIT") or "dev")[:8]


def _public_cache(response: Response) -> Response:
    if response.headers.get("Cache-Control") is None:
        response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
    return response


def _no_cache_html(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/u/{slug}", response_class=HTMLResponse)
async def public_folio(request: Request, slug: str):
    from app.utils.text import strip_control
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug)
    if not user:
        response = templates.TemplateResponse(
            request,
            "folio_404.html",
            {
                "site_name": "FolioSpace",
                "page_title": "Folio not found — FolioSpace",
                "description": "This folio isn't claimed yet on FolioSpace.",
                "slug": safe_slug,
            },
            status_code=404,
        )
        return _no_cache_html(response)
    if user.get("deleted_at"):
        response = templates.TemplateResponse(
            request,
            "folio_gone.html",
            {
                "site_name": "FolioSpace",
                "page_title": "Folio unavailable — FolioSpace",
                "description": "This folio is no longer available on FolioSpace.",
            },
            status_code=410,
        )
        return _no_cache_html(response)
    display_name = (user.get("display_name") or user.get("slug") or "Folio").strip()
    role = (user.get("role") or "").strip()
    bio = (user.get("bio") or "").strip()
    description = bio if bio else f"{display_name} on FolioSpace."
    page_title = f"{display_name} — FolioSpace"
    response = templates.TemplateResponse(
        request,
        "folio.html",
        {
            "site_name": "FolioSpace",
            "page_title": page_title,
            "description": description[:200],
            "user": user,
            "og_image": f"/u/{user['slug']}/og.png",
            "og_image_alt": f"{display_name} — {role or 'Folio'} on FolioSpace",
            "og_title": f"{display_name} — {role}" if role else page_title,
        },
    )
    return _public_cache(response)


@router.get("/u/{slug}/og.png")
async def public_folio_og(request: Request, slug: str):
    from app.utils.text import strip_control
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/static/img/og.png", status_code=302)
    png = folio_svc.render_og_image(user)
    if png is None:
        return RedirectResponse("/static/img/og.png", status_code=302)
    response = Response(content=png, media_type="image/png")
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/u/{slug}/qr.png")
async def public_folio_qr(request: Request, slug: str):
    from app.utils.text import strip_control
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/static/img/og.png", status_code=302)
    share_url = str(request.url_for("public_folio", slug=user["slug"]))
    png = folio_svc.render_qr_png(share_url)
    if png is None:
        return RedirectResponse("/static/img/og.png", status_code=302)
    response = Response(content=png, media_type="image/png")
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
