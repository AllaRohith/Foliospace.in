import json
import logging
import os
from datetime import timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.services import billing as billing_svc
from app.services import razorpay as razorpay_svc
from app.services import user_auth
from app.rate_limit import limiter

router = APIRouter(tags=["billing"])
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
_asset_v = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "dev")[:8]
templates.env.globals["asset_v"] = _asset_v


def _no_cache(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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
        "is_public": bool(user.get("is_public")),
        "plan": user.get("plan") or "free",
        "plan_expires_at": user.get("plan_expires_at"),
        "payment_failed_at": user.get("payment_failed_at"),
        "setup_paid_at": user.get("setup_paid_at"),
        "is_trial": bool(user.get("is_trial")),
        "is_internal": bool(user.get("is_internal")),
    }


@router.get("/dashboard/billing", response_class=HTMLResponse)
async def dashboard_billing(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard/billing", status_code=303)
    sub = billing_svc.current_subscription(str(user["id"]))
    invoices = billing_svc.list_invoices(str(user["id"]))
    configured = razorpay_svc.is_configured()
    trial_days_left = billing_svc.trial_days_left(user)
    trial_expires_at_iso = ""
    if user.get("is_trial") and user.get("plan_expires_at"):
        ist = timezone(timedelta(hours=5, minutes=30))
        trial_expires_at_iso = user["plan_expires_at"].astimezone(ist).strftime("%Y-%m-%d %H:%M IST")
    return _no_cache(templates.TemplateResponse(
        request,
        "dashboard/billing.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Billing — FolioSpace",
            "description": "Manage your FolioSpace subscription and invoices.",
            "user": _user_to_context(user),
            "subscription": sub,
            "invoices": invoices,
            "razorpay_configured": configured,
            "razorpay_key_id": razorpay_svc.public_key() if configured else "",
            "setup_paid": bool(user.get("setup_paid_at")),
            "grace_days_left": billing_svc.grace_days_left(user),
            "trial_days_left": trial_days_left,
            "trial_expires_at_iso": trial_expires_at_iso,
            "err": (request.query_params.get("err") or "")[:24],
            "cancelled": request.query_params.get("cancel") == "1",
            "nav_active": "billing",
        },
    ))


@router.post("/dashboard/billing/subscribe")
@limiter.limit("30/minute")
async def billing_subscribe(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not razorpay_svc.is_configured():
        return RedirectResponse("/dashboard/billing?err=config", status_code=303)
    try:
        sub_id = await run_in_threadpool(billing_svc.create_subscription, str(user["id"]))
    except HTTPException as e:
        return RedirectResponse(f"/dashboard/billing?err={'config' if e.status_code == 503 else 'server'}", status_code=303)
    except Exception as e:
        logger.exception("subscribe failed: %s", e)
        return RedirectResponse("/dashboard/billing?err=server", status_code=303)
    user_auth.audit_user(
        request,
        str(user["id"]),
        "billing.checkout.created",
        metadata={"kind": "recurring"},
    )
    return JSONResponse({"kind": "recurring", "subscription_id": sub_id, "key": razorpay_svc.public_key()})


@router.post("/dashboard/billing/cancel")
@limiter.limit("10/minute")
async def billing_cancel(request: Request):
    user = user_auth.require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ok = False
    try:
        ok = await run_in_threadpool(billing_svc.cancel_subscription, str(user["id"]))
    except Exception as e:
        logger.exception("cancel failed: %s", e)
    user_auth.audit_user(
        request,
        str(user["id"]),
        "billing.cancel" if ok else "billing.cancel.fail",
    )
    if ok:
        return RedirectResponse("/dashboard/billing?cancel=1", status_code=303)
    return RedirectResponse("/dashboard/billing?err=cancel", status_code=303)


@router.post("/webhooks/razorpay")
@limiter.limit("120/minute")
async def razorpay_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    if not razorpay_svc.verify_signature(body, sig):
        return JSONResponse({"ok": False}, status_code=400)
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)
    event_id = payload.get("id", "") if isinstance(payload, dict) else ""
    event = payload.get("event", "") if isinstance(payload, dict) else ""
    if not event_id or not event:
        return JSONResponse({"ok": False}, status_code=400)
    try:
        await run_in_threadpool(billing_svc.handle_webhook, event, payload)
    except Exception as e:
        logger.exception("webhook dispatch failed: %s", e)
    return JSONResponse({"ok": True}, status_code=200)