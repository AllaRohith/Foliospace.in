"""Cashfree Payments Subscriptions API client.

Self-contained: no SDK dependency. Uses httpx (already in fastapi deps).

Two plans, one product:
  * pro_year1_discount   — ₹899/year   (assigned at signup)
  * pro_year2_full       — ₹1,499/year (swapped to on first renewal via webhook)

Webhook signature: HMAC-SHA256 over (timestamp + raw body) compared against
the `x-cashfree-signature` header (lower-hex). Per the Cashfree Subscriptions
docs, the timestamp header is `x-cashfree-timestamp` and the secret is the
Webhook Secret configured on the merchant dashboard.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_APP_ID = os.getenv("CASHFREE_APP_ID", "").strip()
_SECRET = os.getenv("CASHFREE_SECRET_KEY", "").strip()
_API_VERSION = (os.getenv("CASHFREE_API_VERSION", "2025-01-01") or "2025-01-01").strip()
_ENV = (os.getenv("CASHFREE_ENV") or os.getenv("APP_ENV") or "sandbox").strip().lower()
_WEBHOOK_SECRET = os.getenv("CASHFREE_WEBHOOK_SECRET", "").strip()
_PLAN_YEAR1_ID = os.getenv("CASHFREE_PLAN_ID_PRO_YEAR1_DISCOUNT", "").strip()
_PLAN_YEAR2_ID = os.getenv("CASHFREE_PLAN_ID_PRO_YEAR2_FULL", "").strip()

PRO_YEAR1_INR = 899
PRO_YEAR2_INR = 1499
PRO_YEAR1_PAISE = PRO_YEAR1_INR * 100
PRO_YEAR2_PAISE = PRO_YEAR2_INR * 100

_BASE_SANDBOX = "https://sandbox.cashfree.com/pg"
_BASE_PROD = "https://api.cashfree.com/pg"

_client: httpx.Client | None = None


def _base_url() -> str:
    return _BASE_SANDBOX if _ENV in ("sandbox", "dev", "development", "local", "staging") else _BASE_PROD


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        if not _APP_ID or not _SECRET:
            raise HTTPException(status_code=503, detail="Cashfree not configured.")
        _client = httpx.Client(
            base_url=_base_url(),
            timeout=15.0,
            headers={
                "x-client-id": _APP_ID,
                "x-client-secret": _SECRET,
                "x-api-version": _API_VERSION,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    return _client


def reset_client() -> None:
    """Reset cached httpx client (used when env vars change in tests / cold-start)."""
    global _client
    _client = None


def is_configured() -> bool:
    return bool(
        _APP_ID and _SECRET and _WEBHOOK_SECRET and _PLAN_YEAR1_ID and _PLAN_YEAR2_ID
    )


def app_id() -> str:
    return _APP_ID


def plan_year1_id() -> str:
    return _PLAN_YEAR1_ID


def plan_year2_id() -> str:
    return _PLAN_YEAR2_ID


def env_name() -> str:
    return _ENV


# ── Signature verification ─────────────────────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, signature: str, timestamp: str) -> bool:
    """HMAC-SHA256 over (timestamp + body). Compare against the header."""
    if not (raw_body and signature and timestamp and _WEBHOOK_SECRET):
        return False
    payload = (timestamp + raw_body.decode("utf-8", errors="replace")).encode("utf-8")
    expected = hmac.new(_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip().lower())


# ── Customer + Subscription ───────────────────────────────────────────────────

def create_customer(*, name: str, email: str, contact: str, user_id: str) -> dict[str, Any]:
    payload = {
        "customer_id": f"user_{user_id.replace('-', '')}"[:64],
        "customer_name": (name or "FolioSpace")[:80],
        "customer_email": (email or "")[:254] or f"user_{user_id[:8]}@foliospace.invalid",
        "customer_phone": (contact or "")[:20] or "9999999999",
        "customer_metadata": {"user_id": user_id},
    }
    r = _get_client().post("/customers", json=payload)
    if r.status_code >= 400:
        logger.error("cashfree customer create failed: %s %s", r.status_code, r.text[:500])
        raise HTTPException(status_code=502, detail="Cashfree customer create failed.")
    return r.json() or {}


def fetch_customer(cf_customer_id: str) -> dict[str, Any]:
    r = _get_client().get(f"/customers/{cf_customer_id}")
    r.raise_for_status()
    return r.json() or {}


def create_subscription(
    *,
    cf_customer_id: str,
    plan_id: str,
    user_id: str,
    slug: str,
) -> dict[str, Any]:
    """Create a Cashfree Subscription tied to a plan. Year-1 plan on first signup."""
    payload = {
        "subscription_id": f"sub_{int(time.time())}_{user_id[:8]}",
        "customer_details": {
            "customer_id": cf_customer_id,
            "customer_name": (slug or "FolioSpace user")[:80],
        },
        "plan_details": {"plan_id": plan_id},
        "subscription_meta": {
            "return_url": (
                f"{os.getenv('PUBLIC_BASE_URL', 'https://foliospace.in').rstrip('/')}"
                f"/dashboard/billing?cf_return=1"
            ),
            "notification_channel": ["EMAIL"],
        },
        "subscription_tags": {
            "user_id": user_id,
            "slug": (slug or "")[:48],
        },
    }
    r = _get_client().post("/subscriptions", json=payload)
    if r.status_code >= 400:
        logger.error(
            "cashfree subscription create failed: plan=%s status=%s body=%s",
            plan_id, r.status_code, r.text[:500],
        )
        raise HTTPException(status_code=502, detail="Cashfree subscription create failed.")
    return r.json() or {}


def fetch_subscription(cf_subscription_id: str) -> dict[str, Any]:
    r = _get_client().get(f"/subscriptions/{cf_subscription_id}")
    r.raise_for_status()
    return r.json() or {}


def update_subscription_plan(cf_subscription_id: str, new_plan_id: str) -> dict[str, Any]:
    """Plan swap: update_subscription.plan_details.plan_id on existing subscription."""
    payload = {"plan_details": {"plan_id": new_plan_id}}
    r = _get_client().post(f"/subscriptions/{cf_subscription_id}/update", json=payload)
    if r.status_code >= 400:
        logger.error(
            "cashfree subscription.update failed: sub=%s new_plan=%s status=%s body=%s",
            cf_subscription_id, new_plan_id, r.status_code, r.text[:500],
        )
        raise HTTPException(status_code=502, detail="Cashfree plan swap failed.")
    return r.json() or {}


def cancel_subscription(cf_subscription_id: str, *, cancel_at_cycle_end: bool = True) -> dict[str, Any]:
    payload = {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0}
    r = _get_client().post(
        f"/subscriptions/{cf_subscription_id}/cancel", json=payload
    )
    if r.status_code >= 400:
        # Cashfree returns 200 already-cancelled; treat as ok
        if r.status_code == 200:
            return r.json() or {}
        logger.error(
            "cashfree cancel failed: sub=%s status=%s body=%s",
            cf_subscription_id, r.status_code, r.text[:500],
        )
        raise HTTPException(status_code=502, detail="Cashfree cancel failed.")
    return r.json() or {}


def fetch_payment(cf_payment_id: str) -> dict[str, Any]:
    r = _get_client().get(f"/payments/{cf_payment_id}")
    r.raise_for_status()
    return r.json() or {}
