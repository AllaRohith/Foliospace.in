import hashlib
import hmac
import logging
import os

import razorpay
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
_PLAN_ID = os.getenv("RAZORPAY_PLAN_ID_PRO", "").strip()

_client: razorpay.Client | None = None


def _get_client() -> razorpay.Client:
    global _client
    if _client is None:
        if not _KEY_ID or not _KEY_SECRET:
            raise HTTPException(status_code=503, detail="Razorpay not configured.")
        _client = razorpay.Client(auth=(_KEY_ID, _KEY_SECRET))
    return _client


def is_configured() -> bool:
    return bool(_KEY_ID and _KEY_SECRET and _WEBHOOK_SECRET and _PLAN_ID)


def public_key() -> str:
    return _KEY_ID


def plan_id() -> str:
    return _PLAN_ID


def webhook_secret() -> str:
    return _WEBHOOK_SECRET


def get_client() -> razorpay.Client:
    return _get_client()


def reset_client() -> None:
    global _client
    _client = None


def verify_signature(body: bytes, signature: str) -> bool:
    if not (body and signature and _WEBHOOK_SECRET):
        return False
    expected = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_one_time_order(amount_paise: int, notes: dict, currency: str = "INR") -> dict:
    client = _get_client()
    return client.order.create({
        "amount": int(amount_paise),
        "currency": currency,
        "payment_capture": 1,
        "notes": notes,
    })


def create_customer(name: str, email: str, contact: str = "", notes: dict | None = None) -> dict:
    client = _get_client()
    payload = {"name": name[:80], "email": email[:254]}
    if contact:
        payload["contact"] = contact[:20]
    if notes:
        payload["notes"] = notes
    return client.customer.create(payload)


def create_subscription(plan_id: str, customer_id: str, total_count: int, notes: dict) -> dict:
    client = _get_client()
    return client.subscription.create({
        "plan_id": plan_id,
        "customer_id": customer_id,
        "customer_notify": 1,
        "total_count": int(total_count),
        "notes": notes,
    })


def cancel_subscription_remote(subscription_id: str, cancel_at_cycle_end: bool = True) -> dict:
    client = _get_client()
    return client.subscription.cancel(subscription_id, {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0})


def fetch_payment(payment_id: str) -> dict:
    client = _get_client()
    return client.payment.fetch(payment_id)


def fetch_subscription(subscription_id: str) -> dict:
    client = _get_client()
    return client.subscription.fetch(subscription_id)