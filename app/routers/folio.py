import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.rate_limit import limiter
from app.services import cloudinary_svc
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
async def public_folio_legacy_redirect(request: Request, slug: str):
    from app.services.user_auth import _slug_is_reserved
    from app.utils.text import strip_control
    safe_slug = strip_control((slug or "").strip())[:48]
    if not safe_slug or _slug_is_reserved(safe_slug):
        return _no_cache_html(templates.TemplateResponse(
            request,
            "folio_404.html",
            {
                "site_name": "FolioSpace",
                "page_title": "Folio not found — FolioSpace",
                "description": "This folio isn't claimed yet on FolioSpace.",
                "slug": safe_slug,
            },
            status_code=404,
        ))
    return RedirectResponse(f"/{safe_slug}", status_code=301)


@router.get("/{slug}", response_class=HTMLResponse)
async def public_folio(request: Request, slug: str):
    from app.services.user_auth import _slug_is_reserved
    from app.utils.text import strip_control
    from app.services import folio_views as views_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    if not safe_slug or _slug_is_reserved(safe_slug):
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
    from app.services import user_auth as user_auth_svc
    viewer = user_auth_svc.require_user(request)
    viewer_id = str(viewer["id"]) if viewer else None
    user = folio_svc.find_user_by_slug(
        safe_slug, require_public=(viewer_id is None)
    )
    if not user:
        from app.services import user_auth as _uauth
        viewer2 = _uauth.require_user(request)
        viewer_id2 = str(viewer2["id"]) if viewer2 else None
        if viewer_id2 is not None:
            user_try = folio_svc.find_user_by_slug(safe_slug, require_public=False)
            if user_try and str(user_try.get("id")) == viewer_id2:
                user = user_try
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
    from app.services import user_auth as user_auth_svc
    viewer = user_auth_svc.require_user(request)
    viewer_id = str(viewer["id"]) if viewer else None
    owner_id = str(user.get("id") or "")
    if viewer_id != owner_id:
        views_svc.record_view(
            safe_slug,
            request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
        )
    display_name = (user.get("display_name") or user.get("slug") or "Folio").strip()
    role = (user.get("role") or "").strip()
    bio = (user.get("bio") or "").strip()
    description = bio if bio else f"{display_name} on FolioSpace."
    page_title = f"{display_name} — FolioSpace"
    public_base_url = _os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
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
            "canonical": f"/{user['slug']}",
            "public_base_url": public_base_url,
        },
    )
    return _public_cache(response)


@router.get("/{slug}/manage", response_class=HTMLResponse)
async def owner_folio_manage(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services.user_auth import _slug_is_reserved
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at") or _slug_is_reserved(safe_slug):
        return _no_cache_html(templates.TemplateResponse(
            request,
            "folio_404.html",
            {
                "site_name": "FolioSpace",
                "page_title": "Folio not found — FolioSpace",
                "description": "This folio isn't claimed yet on FolioSpace.",
                "slug": safe_slug,
            },
            status_code=404,
        ))
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        if viewer:
            return RedirectResponse(f"/{safe_slug}", status_code=303)
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    from app.services import billing as billing_svc
    public_base_url = _os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    share_url = f"{public_base_url}/{safe_slug}"
    qr_url = f"{public_base_url}/u/{safe_slug}/qr.png"
    og_image_url = f"{public_base_url}/u/{safe_slug}/og.png"
    display_name = (user.get("display_name") or user.get("slug") or "Folio").strip()
    role = (user.get("role") or "").strip()
    bio = (user.get("bio") or "").strip()
    wa_text = f"Hey — my folio is on FolioSpace: {share_url}"
    mail_subject = f"My folio: {display_name}"
    og_title = f"{display_name} — FolioSpace" if not role else f"{display_name} — {role}"
    og_desc = (bio[:140] if bio else f"{display_name} on FolioSpace.")
    og_alt = f"{display_name} — {role or 'Folio'} on FolioSpace"
    ctx = {
        "trial_days_left": billing_svc.trial_days_left(viewer),
        "grace_days_left": billing_svc.grace_days_left(viewer),
        "subscription": billing_svc.current_subscription(str(viewer["id"])),
    }
    from app.services import folio_views as views_svc
    view_stats = views_svc.get_view_stats(safe_slug, days=30)
    err = strip_control(request.query_params.get("err", ""))[:24]
    saved = request.query_params.get("saved") == "1"
    response = templates.TemplateResponse(
        request,
        "folio_manage.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Manage folio — FolioSpace",
            "description": "Edit and share your FolioSpace folio.",
            "user": user,
            "share_url": share_url,
            "qr_url": qr_url,
            "og_image_url": og_image_url,
            "wa_text": wa_text,
            "mail_subject": mail_subject,
            "og_title": og_title,
            "og_desc": og_desc,
            "og_alt": og_alt,
            "og_preview_meta_url": public_base_url.replace("https://", ""),
            "is_live": bool(user.get("is_public")),
            "view_stats": view_stats,
            "err": err,
            "saved": saved,
            "grace_days_left": ctx["grace_days_left"],
            "trial_days_left": ctx["trial_days_left"],
            "subscription": ctx["subscription"],
            "canonical": f"/{safe_slug}/manage",
        },
    )
    return _no_cache_html(response)


import re as _re_folio
from fastapi import Form as _Form_folio


@router.post("/{slug}/manage")
async def owner_folio_manage_save(
    request: Request,
    slug: str,
    display_name: str = _Form_folio(""),
    role: str = _Form_folio(""),
    bio: str = _Form_folio(""),
    phone: str = _Form_folio(""),
    is_public: str = _Form_folio(""),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    dname = (display_name or "").strip()
    if not (2 <= len(dname) <= 80):
        return RedirectResponse(f"/{safe_slug}/manage?err=display_name", status_code=303)
    bio_clean = (bio or "").strip()
    if len(bio_clean) > 280:
        return RedirectResponse(f"/{safe_slug}/manage?err=bio", status_code=303)
    phone_clean = (phone or "").strip()
    if phone_clean and not _re_folio.fullmatch(r"[+0-9 ()\-]{6,20}", phone_clean):
        return RedirectResponse(f"/{safe_slug}/manage?err=phone", status_code=303)
    role_clean = (role or "").strip()
    if len(role_clean) > 60:
        return RedirectResponse(f"/{safe_slug}/manage?err=role", status_code=303)
    public_flag = (is_public or "").strip().lower() in ("1", "true", "on", "yes")
    updated = user_auth_svc.update_user_profile(
        str(user["id"]),
        display_name=dname,
        role=role_clean,
        bio=bio_clean,
        phone=phone_clean,
        is_public=public_flag,
    )
    if not updated:
        return RedirectResponse(f"/{safe_slug}/manage?err=server", status_code=303)
    from app.services.user_auth import audit_user as _audit
    _audit(request, str(user["id"]), "folio.update", metadata={"is_public": public_flag})
    return RedirectResponse(f"/{safe_slug}/manage?saved=1", status_code=303)


@router.get("/{slug}/manage/avatar/sign")
@limiter.limit("20/minute")
async def owner_avatar_sign(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    params = cloudinary_svc.sign_upload_params(str(user["id"]))
    if not params:
        return JSONResponse({"ok": False, "message": "uploads-disabled"}, status_code=503)
    return JSONResponse({"ok": True, **params})


@router.post("/{slug}/manage/avatar")
async def owner_avatar_save(
    request: Request,
    slug: str,
    background: BackgroundTasks,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    url = strip_control(str(payload.get("url", "")))[:2048]
    public_id = strip_control(str(payload.get("public_id", "")))[:512]
    if not url or not url.startswith("https://res.cloudinary.com/"):
        return JSONResponse({"ok": False, "message": "bad-url"}, status_code=400)
    if not public_id:
        return JSONResponse({"ok": False, "message": "missing-public-id"}, status_code=400)
    old_public_id = (user.get("avatar_public_id") or "").strip()
    updated = user_auth_svc.set_avatar(str(user["id"]), url, public_id)
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    if old_public_id and old_public_id != public_id:
        background.add_task(cloudinary_svc.destroy_avatar, old_public_id)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.avatar.uploaded" if not old_public_id or old_public_id == public_id else "folio.avatar.replaced",
        target=public_id,
    )
    return JSONResponse({"ok": True, "url": url, "public_id": public_id})


@router.delete("/{slug}/manage/avatar")
async def owner_avatar_delete(request: Request, slug: str, background: BackgroundTasks):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    old_public_id = (user.get("avatar_public_id") or "").strip()
    cleared = user_auth_svc.clear_avatar(str(user["id"]))
    if not cleared:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    if old_public_id:
        background.add_task(cloudinary_svc.destroy_avatar, old_public_id)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.avatar.removed",
        target=old_public_id or "-",
    )
    return JSONResponse({"ok": True})


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
