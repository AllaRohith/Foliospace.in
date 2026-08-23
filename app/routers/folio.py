import logging
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Form, Request
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
from app.utils.template_globals import install_template_globals
install_template_globals(templates)


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
    public_base_url = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    view_stats = views_svc.get_view_stats(safe_slug, days=30)
    from app.services.imports import public_render as imports_svc
    integrations = imports_svc.get_public_sections(str(user["id"]))
    from app.services import user_fonts as user_fonts_svc
    approved_fonts = user_fonts_svc.list_approved_for_user(str(user["id"]))
    from app.services import user_links as user_links_svc
    public_links = user_links_svc.list_links(str(user["id"]))
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
            "view_stats": view_stats,
            "integrations": integrations,
            "approved_fonts": approved_fonts,
            "public_links": public_links,
            "now": datetime.utcnow(),
            # Test/dev folios (timestamp-suffix or "test-" prefix) must not
            # be indexed. Detection is slug-pattern based; production slugs
            # do not match these patterns.
            "is_test_slug": bool(
                re.match(r"^(me|avatar|fm)-test-[0-9]+$|^test-", safe_slug)
            ),
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
    from app.services import templates as templates_svc
    public_base_url = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
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
    visible_templates = templates_svc.catalog_for_role(user.get("category") or "other")
    current_tid = (user.get("template_id") or "other-base").strip()
    user_plan = (viewer.get("plan") or "free").lower()
    is_internal = bool(viewer.get("is_internal"))
    from app.services import oauth as oauth_svc
    linked_accounts = user_auth_svc.list_social_accounts(str(viewer["id"]))
    user_has_password = user_auth_svc.has_password(str(viewer["id"]))
    oauth_providers = oauth_svc.configured_providers()
    saved_kind = strip_control(request.query_params.get("saved", ""))[:24]
    provider_q = strip_control(request.query_params.get("provider", ""))[:16]
    from app.services.imports import public_render as imports_svc
    imports_state = imports_svc.get_manage_state(str(viewer["id"]))
    imports_configured = imports_svc.server_configured()
    manage_repos = imports_svc.get_manage_repos(str(viewer["id"]))
    from app.services.imports import linkedin_marketing as li_marketing
    marketing_status = li_marketing.get_status()
    repo_sort = (user.get("repo_sort") or "stars").lower() if isinstance(user.get("repo_sort"), str) else "stars"
    if repo_sort not in ("stars", "recent", "updated"):
        repo_sort = "stars"
    is_pro = (user_plan == "pro") or is_internal
    from app.services import user_fonts as user_fonts_svc
    user_fonts = user_fonts_svc.list_fonts(str(viewer["id"]))
    from app.services import user_links as user_links_svc
    user_links = user_links_svc.list_links(str(viewer["id"]))
    raw_work_rail = user.get("work_rail") if isinstance(user.get("work_rail"), list) else []
    work_rail_rows = [
        {
            "title": (str(r.get("title", "")) if isinstance(r, dict) else "").strip()[:60],
            "body": (str(r.get("body", "")) if isinstance(r, dict) else "").strip()[:120],
        }
        for r in raw_work_rail
        if isinstance(r, dict) and ((str(r.get("title", ""))).strip() or (str(r.get("body", ""))).strip())
    ]
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
            "saved_kind": saved_kind,
            "provider_q": provider_q,
            "grace_days_left": ctx["grace_days_left"],
            "trial_days_left": ctx["trial_days_left"],
            "subscription": ctx["subscription"],
            "nav_active": "manage",
            "canonical": f"/{safe_slug}/manage",
            "templates_catalog": visible_templates,
            "current_template_id": current_tid,
            "user_plan": user_plan,
            "is_internal": is_internal,
            "linked_accounts": linked_accounts,
            "user_has_password": user_has_password,
            "oauth_providers": oauth_providers,
            "imports_state": imports_state,
            "imports_configured": imports_configured,
            "repo_sort": repo_sort,
            "manage_repos": manage_repos,
            "marketing_status": marketing_status,
            "completion": user_auth_svc.compute_completion(user),
            "is_pro": is_pro,
            "user_fonts": user_fonts,
            "user_links": user_links,
            "work_rail_rows": work_rail_rows,
            "flash": request.session.pop("flash", None),
            "now": datetime.utcnow(),
        },
    )
    return _no_cache_html(response)


@router.post("/{slug}/manage/template")
async def owner_folio_template_switch(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import templates as templates_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    body = {}
    try:
        body_bytes = await request.body()
        if body_bytes:
            from urllib.parse import parse_qs
            parsed = parse_qs(body_bytes.decode("utf-8"))
            for k, v in parsed.items():
                body[k] = v[0] if v else ""
    except Exception:
        body = {}
    target = strip_control(str(body.get("template_id", "")))[:32] or "other-base"
    if not templates_svc.can_user_pick(viewer, target):
        if (viewer.get("plan") or "free").lower() != "pro" and not viewer.get("is_internal"):
            return RedirectResponse(f"/{safe_slug}/manage/templates?err=template-pro", status_code=303)
        return RedirectResponse(f"/{safe_slug}/manage/templates?err=template-not-found", status_code=303)
    updated = user_auth_svc.update_template(str(user["id"]), target)
    if not updated:
        return RedirectResponse(f"/{safe_slug}/manage/templates?err=server", status_code=303)
    user_auth_svc.audit_user(
        request, str(user["id"]), "folio.template.switch", target=target,
    )
    return RedirectResponse(f"/{safe_slug}/manage/templates?saved=template", status_code=303)


@router.get("/{slug}/manage/templates", response_class=HTMLResponse)
async def owner_folio_templates(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services.user_auth import _slug_is_reserved
    from app.services import user_auth as user_auth_svc
    from app.services import templates as templates_svc

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
        return RedirectResponse(f"/login?next=/{safe_slug}/manage/templates", status_code=303)

    err = strip_control(request.query_params.get("err", ""))[:24]
    saved = request.query_params.get("saved") == "1"
    saved_kind = strip_control(request.query_params.get("saved", ""))[:24]
    user_plan = (viewer.get("plan") or "free").lower()
    is_internal = bool(viewer.get("is_internal"))
    is_pro = (user_plan == "pro") or is_internal
    current_tid = (user.get("template_id") or "other-base").strip()
    visible_templates = templates_svc.catalog_for_role(user.get("category") or "other")

    response = templates.TemplateResponse(
        request,
        "folio_manage_templates.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Templates — FolioSpace",
            "description": "Pick the template for your folio.",
            "user": user,
            "templates_catalog": visible_templates,
            "current_template_id": current_tid,
            "user_plan": user_plan,
            "is_internal": is_internal,
            "is_pro": is_pro,
            "err": err,
            "saved": saved,
            "saved_kind": saved_kind,
            "nav_active": "templates",
            "canonical": f"/{safe_slug}/manage/templates",
            "now": datetime.utcnow(),
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
    linkedin_url: str = _Form_folio(""),
    is_public: str = _Form_folio(""),
    is_listed: str = _Form_folio(""),
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
    linkedin_clean = (linkedin_url or "").strip()
    if linkedin_clean and not _re_folio.fullmatch(
        r"https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_\-]+/?", linkedin_clean
    ):
        return RedirectResponse(f"/{safe_slug}/manage?err=linkedin_url", status_code=303)
    public_flag = (is_public or "").strip().lower() in ("1", "true", "on", "yes")
    listed_flag = (is_listed or "").strip().lower() in ("1", "true", "on", "yes")
    if listed_flag and not public_flag:
        listed_flag = False
    updated = user_auth_svc.update_user_profile(
        str(user["id"]),
        display_name=dname,
        role=role_clean,
        bio=bio_clean,
        phone=phone_clean,
        is_public=public_flag,
        linkedin_url=linkedin_clean,
    )
    if not updated:
        import logging
        logging.getLogger("app.routers.folio").exception(
            "owner_folio_manage_save: update_user_profile returned None for user=%s",
            user["id"],
        )
        return RedirectResponse(f"/{safe_slug}/manage?err=server", status_code=303)
    if listed_flag != bool(user.get("is_listed")):
        user_auth_svc.update_listing(str(user["id"]), listed_flag)
    from app.services.user_auth import audit_user as _audit
    _audit(
        request,
        str(user["id"]),
        "folio.update",
        metadata={"is_public": public_flag, "is_listed": listed_flag},
    )
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


@router.get("/{slug}/manage/avatar-video/sign")
@limiter.limit("20/minute")
async def owner_avatar_video_sign(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    params = cloudinary_svc.sign_upload_params(str(user["id"]), kind="video")
    if not params:
        return JSONResponse({"ok": False, "message": "uploads-disabled"}, status_code=503)
    return JSONResponse({"ok": True, **params})


@router.post("/{slug}/manage/avatar-video")
async def owner_avatar_video_save(
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
    kind = strip_control(str(payload.get("kind", "mp4")))[:16]
    if not url or not url.startswith("https://res.cloudinary.com/"):
        return JSONResponse({"ok": False, "message": "bad-url"}, status_code=400)
    if not public_id:
        return JSONResponse({"ok": False, "message": "missing-public-id"}, status_code=400)
    old_public_id = (user.get("avatar_video_public_id") or "").strip()
    updated = user_auth_svc.set_avatar_video(str(user["id"]), url, public_id, kind)
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    if old_public_id and old_public_id != public_id:
        background.add_task(cloudinary_svc.destroy_avatar, old_public_id, "video")
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.avatar_video.uploaded" if not old_public_id or old_public_id == public_id else "folio.avatar_video.replaced",
        target=public_id,
    )
    return JSONResponse({"ok": True, "url": url, "public_id": public_id, "kind": kind})


@router.delete("/{slug}/manage/avatar-video")
async def owner_avatar_video_delete(request: Request, slug: str, background: BackgroundTasks):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    old_public_id = (user.get("avatar_video_public_id") or "").strip()
    cleared = user_auth_svc.clear_avatar_video(str(user["id"]))
    if not cleared:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    if old_public_id:
        background.add_task(cloudinary_svc.destroy_avatar, old_public_id, "video")
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.avatar_video.removed",
        target=old_public_id or "-",
    )
    return JSONResponse({"ok": True})


@router.post("/{slug}/manage/spotlight")
async def owner_spotlight_save(
    request: Request,
    slug: str,
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
    if not (viewer.get("plan") == "pro" or viewer.get("is_internal")):
        return JSONResponse({"ok": False, "message": "pro-only"}, status_code=402)
    kind = strip_control(str(payload.get("kind", "url")))[:16]
    ref_id = strip_control(str(payload.get("ref_id", "")))[:128]
    text = strip_control(str(payload.get("text", "")))[:120]
    url = strip_control(str(payload.get("url", "")))[:2048]
    emoji = strip_control(str(payload.get("emoji", "")))[:16]
    updated = user_auth_svc.set_spotlight(
        str(user["id"]),
        kind=kind,
        ref_id=ref_id,
        text=text,
        url=url,
        emoji=emoji,
    )
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.spotlight.saved",
        target=kind or "url",
    )
    return JSONResponse({"ok": True})


@router.delete("/{slug}/manage/spotlight")
async def owner_spotlight_delete(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    cleared = user_auth_svc.clear_spotlight(str(user["id"]))
    if not cleared:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.spotlight.removed",
    )
    return JSONResponse({"ok": True})


@router.post("/{slug}/manage/seo")
async def owner_seo_save(
    request: Request,
    slug: str,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.utils.url_safety import safe_public_url
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    seo_title = strip_control(str(payload.get("seo_title", "")))[:70]
    seo_description = strip_control(str(payload.get("seo_description", "")))[:160]
    og_image_override_url_raw = strip_control(str(payload.get("og_image_override_url", "")))[:2048]
    ok, reason = safe_public_url(og_image_override_url_raw)
    if not ok:
        return JSONResponse(
            {"ok": False, "field": "og_image_override_url", "reason": reason},
            status_code=400,
        )
    og_image_override_url = og_image_override_url_raw
    updated = user_auth_svc.update_user_seo(
        str(user["id"]),
        seo_title=seo_title,
        seo_description=seo_description,
        og_image_override_url=og_image_override_url,
    )
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.seo.saved",
    )
    return JSONResponse({"ok": True})


@router.post("/{slug}/manage/work-rail")
async def owner_work_rail_save(
    request: Request,
    slug: str,
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
    raw_rows = payload.get("rows") or []
    if not isinstance(raw_rows, list):
        return JSONResponse({"ok": False, "message": "bad-input"}, status_code=400)
    updated = user_auth_svc.update_work_rail(str(user["id"]), raw_rows)
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.work_rail.saved",
        metadata={"count": len(updated.get("work_rail") or [])},
    )
    return JSONResponse({"ok": True, "rows": updated.get("work_rail") or []})


@router.get("/{slug}/manage/fonts/sign")
@limiter.limit("20/minute")
async def owner_fonts_sign(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    if not (viewer.get("plan") == "pro" or viewer.get("is_internal")):
        return JSONResponse({"ok": False, "message": "pro-only"}, status_code=402)
    params = cloudinary_svc.sign_font_upload(str(user["id"]))
    if not params:
        return JSONResponse({"ok": False, "message": "uploads-disabled"}, status_code=503)
    return JSONResponse({"ok": True, **params})


@router.post("/{slug}/manage/fonts")
async def owner_fonts_save(
    request: Request,
    slug: str,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_fonts as user_fonts_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    if not (viewer.get("plan") == "pro" or viewer.get("is_internal")):
        return JSONResponse({"ok": False, "message": "pro-only"}, status_code=402)
    if user_fonts_svc.count_fonts(str(user["id"])) >= user_fonts_svc.MAX_FONTS_PER_USER:
        return JSONResponse({"ok": False, "message": "limit-reached"}, status_code=403)
    font_name = strip_control(str(payload.get("font_name", "")))[:60]
    url = strip_control(str(payload.get("url", "")))[:2048]
    public_id = strip_control(str(payload.get("public_id", "")))[:512]
    if not url or not url.startswith("https://res.cloudinary.com/"):
        return JSONResponse({"ok": False, "message": "bad-url"}, status_code=400)
    created = user_fonts_svc.create_font(str(user["id"]), font_name, url, public_id)
    if not created:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.font.uploaded",
        target=created.get("id"),
    )
    return JSONResponse({"ok": True, "font": created})


@router.delete("/{slug}/manage/fonts/{font_id}")
async def owner_fonts_delete(request: Request, slug: str, font_id: str, background: BackgroundTasks):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_fonts as user_fonts_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    deleted = user_fonts_svc.delete_font(str(user["id"]), font_id)
    if not deleted:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.font.removed",
        target=font_id,
    )
    return JSONResponse({"ok": True})


@router.get("/{slug}/manage/links")
async def owner_links_list(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_links as user_links_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    items = user_links_svc.list_links(str(user["id"]))
    return JSONResponse({"ok": True, "links": items})


@router.post("/{slug}/manage/links")
async def owner_links_create(
    request: Request,
    slug: str,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_links as user_links_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    is_pro = (viewer.get("plan") == "pro") or bool(viewer.get("is_internal"))
    label = strip_control(str(payload.get("label", "")))[:80]
    url = strip_control(str(payload.get("url", "")))[:2048]
    layout = strip_control(str(payload.get("layout", "stack")))[:16]
    created = user_links_svc.create_link(
        str(user["id"]),
        label=label,
        url=url,
        layout=layout,
        is_pro=is_pro,
    )
    if not created:
        if not is_pro and user_links_svc.count_links(str(user["id"])) >= user_links_svc.FREE_TIER_MAX:
            return JSONResponse({"ok": False, "message": "limit-reached"}, status_code=403)
        return JSONResponse({"ok": False, "message": "bad-input"}, status_code=400)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.link.created",
        target=created.get("id"),
    )
    return JSONResponse({"ok": True, "link": created})


@router.put("/{slug}/manage/links/{link_id}")
async def owner_links_update(
    request: Request,
    slug: str,
    link_id: str,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_links as user_links_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    label = strip_control(str(payload.get("label", "")))[:80] if "label" in payload else None
    url = strip_control(str(payload.get("url", "")))[:2048] if "url" in payload else None
    layout = strip_control(str(payload.get("layout", "")))[:16] if "layout" in payload else None
    updated = user_links_svc.update_link(
        str(user["id"]),
        link_id,
        label=label,
        url=url,
        layout=layout,
    )
    if not updated:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.link.updated",
        target=link_id,
    )
    return JSONResponse({"ok": True, "link": updated})


@router.delete("/{slug}/manage/links/{link_id}")
async def owner_links_delete(request: Request, slug: str, link_id: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_links as user_links_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    deleted = user_links_svc.delete_link(str(user["id"]), link_id)
    if not deleted:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.link.removed",
        target=link_id,
    )
    return JSONResponse({"ok": True})


@router.put("/{slug}/manage/links/reorder")
async def owner_links_reorder(
    request: Request,
    slug: str,
    payload: dict = Body(...),
):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import user_links as user_links_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return JSONResponse({"ok": False}, status_code=404)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return JSONResponse({"ok": False}, status_code=403)
    ordered = payload.get("ordered_ids") or []
    if not isinstance(ordered, list) or not all(isinstance(x, str) for x in ordered):
        return JSONResponse({"ok": False, "message": "bad-input"}, status_code=400)
    ok = user_links_svc.reorder_links(str(user["id"]), ordered)
    if not ok:
        return JSONResponse({"ok": False, "message": "save-failed"}, status_code=500)
    user_auth_svc.audit_user(
        request,
        str(user["id"]),
        "folio.link.reordered",
        metadata={"count": len(ordered)},
    )
    return JSONResponse({"ok": True})


@router.post("/{slug}/manage/connections/unlink")
async def owner_connections_unlink(request: Request, slug: str, provider: str = Form("")):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services import oauth as oauth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    pid = strip_control((provider or "").strip().lower())[:16]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/login", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/{safe_slug}/manage?err=oauth-not-owner", status_code=303)
    if pid not in oauth_svc.PROVIDERS:
        return RedirectResponse(f"/{safe_slug}/manage?err=oauth-provider", status_code=303)
    ok = user_auth_svc.unlink_social_account(str(viewer["id"]), pid)
    if not ok:
        user_auth_svc.audit_user(request, str(viewer["id"]), f"oauth.{pid}.unlink-blocked")
        return RedirectResponse(f"/{safe_slug}/manage?err=oauth-last-login", status_code=303)
    user_auth_svc.audit_user(request, str(viewer["id"]), f"oauth.{pid}.unlinked")
    return RedirectResponse(f"/{safe_slug}/manage?saved=connections", status_code=303)


@router.post("/{slug}/manage/imports/{provider}/refresh")
@limiter.limit("5/minute")
async def owner_imports_refresh(request: Request, slug: str, provider: str, background: BackgroundTasks):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services.imports import public_render as imports_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    pid = strip_control((provider or "").strip().lower())[:16]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    if pid not in ("github", "linkedin"):
        return RedirectResponse(f"/{safe_slug}/manage?err=import-provider", status_code=303)
    if not imports_svc.server_configured():
        user_auth_svc.audit_user(request, str(viewer["id"]), f"import.{pid}.sync.no-config")
        return RedirectResponse(f"/{safe_slug}/manage?err=import-server-config", status_code=303)
    if not imports_svc.has_token(str(viewer["id"]), pid):
        return RedirectResponse(f"/{safe_slug}/manage?err=import-not-linked&provider={pid}", status_code=303)
    user_auth_svc.audit_user(request, str(viewer["id"]), f"import.{pid}.sync.start")
    background.add_task(imports_svc.sync_for_user, str(viewer["id"]), pid)
    return RedirectResponse(f"/{safe_slug}/manage?saved=imports-queued&provider={pid}", status_code=303)


@router.post("/{slug}/manage/imports/{provider}/disconnect")
async def owner_imports_disconnect(request: Request, slug: str, provider: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services.imports import public_render as imports_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    pid = strip_control((provider or "").strip().lower())[:16]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    if pid not in ("github", "linkedin"):
        return RedirectResponse(f"/{safe_slug}/manage?err=import-provider", status_code=303)
    imports_svc.clear_imports(str(viewer["id"]), pid)
    user_auth_svc.audit_user(request, str(viewer["id"]), f"import.{pid}.disconnect")
    return RedirectResponse(f"/{safe_slug}/manage?saved=imports-cleared&provider={pid}", status_code=303)


@router.post("/{slug}/manage/repo-sort")
@limiter.limit("30/minute")
async def owner_repo_sort(request: Request, slug: str, repo_sort: str = Form("")):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    updated = user_auth_svc.update_repo_sort(str(viewer["id"]), repo_sort)
    if not updated:
        return RedirectResponse(f"/{safe_slug}/manage?err=repo-sort", status_code=303)
    user_auth_svc.audit_user(request, str(viewer["id"]), "import.repo_sort.update", target=(repo_sort or "").strip().lower()[:16])
    return RedirectResponse(f"/{safe_slug}/manage?saved=repo-sort", status_code=303)


@router.post("/{slug}/manage/imports/repos/feature")
@limiter.limit("30/minute")
async def owner_repos_feature(request: Request, slug: str):
    from app.utils.text import strip_control
    from app.services import user_auth as user_auth_svc
    from app.services.imports import public_render as imports_svc
    safe_slug = strip_control((slug or "").strip())[:48]
    user = folio_svc.find_user_by_slug(safe_slug, require_public=False)
    if not user or user.get("deleted_at"):
        return RedirectResponse("/", status_code=303)
    viewer = user_auth_svc.require_user(request)
    if not viewer or str(viewer["id"]) != str(user["id"]):
        return RedirectResponse(f"/login?next=/{safe_slug}/manage", status_code=303)
    raw_values: list[str] = []
    try:
        raw = await request.body()
        if raw:
            from urllib.parse import parse_qs
            parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
            raw_values = parsed.get("repo_ids", []) or []
    except Exception:
        raw_values = []
    featured_ids = set()
    for val in raw_values:
        for chunk in val.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                featured_ids.add(int(chunk))
    result = imports_svc.set_featured_repos(str(viewer["id"]), featured_ids)
    if not result.get("ok"):
        return RedirectResponse(f"/{safe_slug}/manage?err=feature", status_code=303)
    user_auth_svc.audit_user(
        request,
        str(viewer["id"]),
        "import.repos.feature.update",
        metadata={"count": len(featured_ids)},
    )
    return RedirectResponse(f"/{safe_slug}/manage?saved=featured&count={len(featured_ids)}", status_code=303)


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


@router.get("/api/debug/connections")
async def debug_connections(request: Request):
    from app.services import user_auth as user_auth_svc
    from app.services import oauth as oauth_svc
    viewer = user_auth_svc.require_user(request)
    if not viewer:
        return JSONResponse({"error": "not_logged_in"}, status_code=401)
    raw_accounts = user_auth_svc.list_social_accounts(str(viewer["id"]))
    accounts_iso = [
        {
            "provider": a.get("provider"),
            "provider_uid": a.get("provider_uid"),
            "email": a.get("email"),
            "created_at": a["created_at"].isoformat() if a.get("created_at") else None,
        }
        for a in raw_accounts
    ]
    return JSONResponse({
        "viewer_id": str(viewer["id"]),
        "viewer_slug": viewer.get("slug"),
        "viewer_email": viewer.get("email"),
        "viewer_has_password_hash": bool(viewer.get("password_hash")),
        "linked_accounts": accounts_iso,
        "linked_count": len(accounts_iso),
        "oauth_providers": oauth_svc.configured_providers(),
    })
