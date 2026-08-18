import json
import logging
import os
import time
from datetime import datetime, timezone

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from app.services import razorpay as razorpay_svc
from app.services import user_auth

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

RECURRING_AMOUNT_PAISE = 14900
SUBSCRIPTION_TOTAL_COUNT = 120


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=5000",
    )


def _to_iso(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    return str(dt)[:10]


def _paise_to_rupees(paise) -> str:
    try:
        n = int(paise or 0)
    except (TypeError, ValueError):
        return "0.00"
    return f"{n / 100:.2f}"


def _get_or_create_customer_id(user: dict) -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    cust = (user.get("razorpay_customer_id") or "").strip()
    if cust:
        try:
            razorpay_svc.get_client().customer.fetch(cust)
            return cust
        except Exception as e:
            logger.warning("stale razorpay_customer_id=%s (%s), will recreate", cust, type(e).__name__)
            cust = ""
    name = (user.get("display_name") or user.get("slug") or "FolioSpace user")[:30]
    email = (user.get("email") or "")[:254]
    contact = (user.get("phone") or "")[:20]
    created = razorpay_svc.create_customer(name=name, email=email, contact=contact, notes={"user_id": str(user["id"])})
    cust_id = created.get("id") or ""
    if not cust_id:
        raise HTTPException(status_code=502, detail="Razorpay customer create failed.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET razorpay_customer_id = %s, updated_at = NOW() WHERE id = %s",
                (cust_id, str(user["id"])),
            )
        conn.commit()
    return cust_id


def _wait_for_customer(client, customer_id: str, max_wait_s: float = 8.0) -> bool:
    deadline = time.monotonic() + max_wait_s
    delay = 0.4
    while True:
        try:
            client.customer.fetch(customer_id)
            return True
        except Exception:
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(delay, deadline - time.monotonic()))
            delay = min(delay * 1.6, 1.5)


def create_subscription(user_id: str) -> str:
    if not razorpay_svc.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, slug, display_name, phone, razorpay_customer_id, created_at, deleted_at "
                "FROM users WHERE id = %s LIMIT 1",
                (user_id,),
            )
            user = cur.fetchone()
        conn.commit()
    if not user or user.get("deleted_at"):
        raise HTTPException(status_code=404, detail="User not found.")
    customer_id = _get_or_create_customer_id(user)
    plan_id = razorpay_svc.plan_id()
    logger.info("create_subscription: plan_id=%r customer_id=%r user_id=%s", plan_id, customer_id, user_id)
    client = razorpay_svc.get_client()
    if not _wait_for_customer(client, customer_id):
        raise HTTPException(status_code=503, detail="Razorpay customer propagation timeout, please retry.")
    sub = razorpay_svc.create_subscription(
        plan_id=plan_id,
        customer_id=customer_id,
        total_count=SUBSCRIPTION_TOTAL_COUNT,
        notes={
            "user_id": str(user["id"]),
            "kind": "recurring",
            "slug": (user.get("slug") or "")[:48],
        },
    )
    return sub.get("id") or ""


def cancel_subscription(user_id: str) -> bool:
    if not razorpay_svc.is_configured():
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, razorpay_subscription_id, cancel_at_period_end FROM user_subscriptions "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row or row.get("cancel_at_period_end"):
        return False
    sub_id = row["razorpay_subscription_id"]
    try:
        razorpay_svc.cancel_subscription_remote(sub_id, cancel_at_cycle_end=True)
    except Exception as e:
        logger.exception("razorpay cancel failed for sub=%s: %s", sub_id, e)
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_subscriptions SET cancel_at_period_end = TRUE, updated_at = NOW(), "
                "last_event_at = NOW() WHERE razorpay_subscription_id = %s",
                (sub_id,),
            )
        conn.commit()
    return True


def current_subscription(user_id: str) -> dict | None:
    if not DATABASE_URL:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM user_subscriptions WHERE user_id = %s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id,),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        row["current_period_end_iso"] = _to_iso(row.get("current_period_end"))
        row["current_period_start_iso"] = _to_iso(row.get("current_period_start"))
        return row
    except psycopg.errors.UndefinedTable:
        return None
    except psycopg.Error as e:
        logger.exception("current_subscription failed for user=%s: %s", user_id, e)
        return None


def list_invoices(user_id: str, limit: int = 50) -> list[dict]:
    if not DATABASE_URL:
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM payments WHERE user_id = %s ORDER BY paid_at DESC NULLS LAST, created_at DESC LIMIT %s",
                    (user_id, int(limit)),
                )
                rows = cur.fetchall() or []
            conn.commit()
        out = []
        for r in rows:
            out.append({
                "razorpay_payment_id": r.get("razorpay_payment_id") or "",
                "description": r.get("description") or "",
                "amount_paise": r.get("amount_paise") or 0,
                "amount_rupees": _paise_to_rupees(r.get("amount_paise")),
                "currency": r.get("currency") or "INR",
                "status": r.get("status") or "",
                "method": r.get("method") or "",
                "invoice_url": r.get("invoice_url") or "",
                "paid_at_iso": _to_iso(r.get("paid_at")) or _to_iso(r.get("created_at")),
            })
        return out
    except psycopg.errors.UndefinedTable:
        return []
    except psycopg.Error as e:
        logger.exception("list_invoices failed for user=%s: %s", user_id, e)
        return []


def handle_webhook(event: str, payload: dict) -> str:
    event_id = payload.get("id") or ""
    if not event_id or not event:
        return "invalid"
    handler = _DISPATCH.get(event)
    if handler is None:
        return "ignored"
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO webhook_events (event_id, event_type) VALUES (%s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                    (event_id, event),
                )
                if cur.fetchone() is None:
                    conn.commit()
                    return "duplicate"
                handler(cur, payload)
                cur.execute(
                    "UPDATE webhook_events SET processed_at = NOW(), error = NULL WHERE event_id = %s",
                    (event_id,),
                )
            conn.commit()
        return "ok"
    except psycopg.errors.UndefinedTable:
        logger.warning("billing tables missing; run scripts/billing.sql")
        return "schema-missing"
    except Exception as e:
        logger.exception("webhook %s failed: %s", event_id, e)
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE webhook_events SET error = %s WHERE event_id = %s",
                        (str(e)[:500], event_id),
                    )
                conn.commit()
        except Exception:
            pass
        return "error"


def _notes_kind(payload: dict) -> str:
    entity = payload.get("payload") or {}
    inner = entity.get("payment") or entity.get("subscription") or {}
    notes = inner.get("notes") or {}
    return (notes.get("kind") or "").strip()


def _notes_user_id(payload: dict) -> str:
    entity = payload.get("payload") or {}
    inner = entity.get("payment") or entity.get("subscription") or {}
    notes = inner.get("notes") or {}
    uid = notes.get("user_id")
    return str(uid) if uid else ""


def _vpa_suffix(vpa: str | None) -> str:
    if not vpa:
        return ""
    s = str(vpa).strip()
    return s[-4:] if len(s) > 4 else s


def _on_payment_captured(cur, payload: dict):
    entity = (payload.get("payload") or {}).get("payment") or {}
    payment_entity = entity.get("entity") or {}
    payment_id = payment_entity.get("id") or ""
    if not payment_id:
        return
    user_id = _notes_user_id(payload)
    if not user_id:
        return
    kind = _notes_kind(payload)
    amount = int(payment_entity.get("amount") or 0)
    currency = (payment_entity.get("currency") or "INR").upper()
    status = (payment_entity.get("status") or "captured").lower()
    method = (payment_entity.get("method") or "").lower() or None
    vpa_suffix = _vpa_suffix(payment_entity.get("vpa"))
    description = "Pro subscription"
    invoice_id = payment_entity.get("invoice_id") or None
    invoice_url = None
    if invoice_id:
        invoice_url = f"https://rzp.io/invoice/{invoice_id}"
    paid_at_iso = payment_entity.get("captured_at") or payment_entity.get("created_at")
    paid_at = None
    if paid_at_iso:
        try:
            paid_at = datetime.fromtimestamp(int(paid_at_iso), tz=timezone.utc)
        except (TypeError, ValueError):
            paid_at = None
    order_id = (payment_entity.get("order_id") or "") or None
    cur.execute(
        """
        INSERT INTO payments (
            user_id, razorpay_payment_id, razorpay_order_id, razorpay_invoice_id, invoice_url,
            amount_paise, currency, status, method, vpa_suffix, description, kind, paid_at, raw_event
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (razorpay_payment_id) DO NOTHING
        """,
        (
            user_id, payment_id, order_id, invoice_id, invoice_url,
            amount, currency, status, method, vpa_suffix, description, kind, paid_at,
            json.dumps(payload, default=str)[:64000],
        ),
    )
    if kind == "recurring":
        period_end_iso = (payment_entity.get("notes") or {}).get("current_period_end")
        period_end = None
        if period_end_iso:
            try:
                period_end = datetime.fromtimestamp(int(period_end_iso), tz=timezone.utc)
            except (TypeError, ValueError):
                period_end = None
        if period_end is None:
            period_end = datetime.now(timezone.utc)
        cur.execute(
            "UPDATE users SET plan = 'pro', plan_expires_at = %s, "
            "is_trial = FALSE, "
            "trial_reminder_7d_sent_at = NULL, "
            "trial_reminder_4d_sent_at = NULL, "
            "trial_reminder_2d_sent_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (period_end, user_id),
        )


def _on_payment_failed(cur, payload: dict):
    entity = (payload.get("payload") or {}).get("payment") or {}
    payment_entity = entity.get("entity") or {}
    payment_id = payment_entity.get("id") or ""
    if not payment_id:
        return
    user_id = _notes_user_id(payload)
    if not user_id:
        return
    kind = _notes_kind(payload)
    amount = int(payment_entity.get("amount") or 0)
    currency = (payment_entity.get("currency") or "INR").upper()
    method = (payment_entity.get("method") or "").lower() or None
    vpa_suffix = _vpa_suffix(payment_entity.get("vpa"))
    description = "Pro subscription"
    order_id = (payment_entity.get("order_id") or "") or None
    cur.execute(
        """
        INSERT INTO payments (
            user_id, razorpay_payment_id, razorpay_order_id,
            amount_paise, currency, status, method, vpa_suffix, description, kind, raw_event
        )
        VALUES (%s, %s, %s, %s, %s, 'failed', %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (razorpay_payment_id) DO NOTHING
        """,
        (
            user_id, payment_id, order_id,
            amount, currency, method, vpa_suffix, description, kind,
            json.dumps(payload, default=str)[:64000],
        ),
    )


def _on_subscription_activated(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    if not user_id:
        return
    plan_id = (sub.get("plan_id") or "").strip()
    status = (sub.get("status") or "active").lower()
    short_url = sub.get("short_url") or None
    cur.execute(
        """
        INSERT INTO user_subscriptions (
            user_id, razorpay_subscription_id, razorpay_plan_id, status, short_url, last_event_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (razorpay_subscription_id) DO UPDATE
            SET status = EXCLUDED.status,
                short_url = COALESCE(EXCLUDED.short_url, user_subscriptions.short_url),
                last_event_at = NOW(),
                updated_at = NOW()
        """,
        (user_id, sub_id, plan_id, status, short_url),
    )
    if status in ("active", "authenticated", "created"):
        cur.execute(
            "UPDATE users SET plan = 'pro', payment_failed_at = NULL, "
            "is_trial = FALSE, "
            "trial_reminder_7d_sent_at = NULL, "
            "trial_reminder_4d_sent_at = NULL, "
            "trial_reminder_2d_sent_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


def _on_subscription_charged(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    if not user_id:
        return
    plan_id = (sub.get("plan_id") or "").strip()
    status = (sub.get("status") or "active").lower()
    cps = sub.get("current_period_start")
    cpe = sub.get("current_period_end")
    period_start = None
    period_end = None
    if cps:
        try:
            period_start = datetime.fromtimestamp(int(cps), tz=timezone.utc)
        except (TypeError, ValueError):
            period_start = None
    if cpe:
        try:
            period_end = datetime.fromtimestamp(int(cpe), tz=timezone.utc)
        except (TypeError, ValueError):
            period_end = None
    cur.execute(
        """
        INSERT INTO user_subscriptions (
            user_id, razorpay_subscription_id, razorpay_plan_id, status,
            current_period_start, current_period_end, last_event_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (razorpay_subscription_id) DO UPDATE
            SET status = EXCLUDED.status,
                current_period_start = COALESCE(EXCLUDED.current_period_start, user_subscriptions.current_period_start),
                current_period_end   = COALESCE(EXCLUDED.current_period_end,   user_subscriptions.current_period_end),
                last_event_at = NOW(),
                updated_at = NOW()
        """,
        (user_id, sub_id, plan_id, status, period_start, period_end),
    )
    payment_entity = (sub.get("payment") or {}).get("entity") if isinstance(sub.get("payment"), dict) else None
    if payment_entity and payment_entity.get("id"):
        _upsert_payment_from_charge(cur, user_id, sub_id, payment_entity)
    if period_end is not None:
        cur.execute(
            "UPDATE users SET plan = 'pro', plan_expires_at = %s, payment_failed_at = NULL, "
            "is_trial = FALSE, "
            "trial_reminder_7d_sent_at = NULL, "
            "trial_reminder_4d_sent_at = NULL, "
            "trial_reminder_2d_sent_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (period_end, user_id),
        )


def _upsert_payment_from_charge(cur, user_id: str, sub_razorpay_id: str, payment_entity: dict):
    payment_id = payment_entity.get("id") or ""
    if not payment_id:
        return
    amount = int(payment_entity.get("amount") or 0)
    currency = (payment_entity.get("currency") or "INR").upper()
    status = (payment_entity.get("status") or "captured").lower()
    method = (payment_entity.get("method") or "").lower() or None
    vpa_suffix = _vpa_suffix(payment_entity.get("vpa"))
    description = "Pro subscription"
    invoice_id = payment_entity.get("invoice_id") or None
    invoice_url = f"https://rzp.io/invoice/{invoice_id}" if invoice_id else None
    paid_at_iso = payment_entity.get("captured_at") or payment_entity.get("created_at")
    paid_at = None
    if paid_at_iso:
        try:
            paid_at = datetime.fromtimestamp(int(paid_at_iso), tz=timezone.utc)
        except (TypeError, ValueError):
            paid_at = None
    cur.execute(
        "SELECT id FROM user_subscriptions WHERE razorpay_subscription_id = %s LIMIT 1",
        (sub_razorpay_id,),
    )
    row = cur.fetchone()
    sub_uuid = row["id"] if row else None
    cur.execute(
        """
        INSERT INTO payments (
            user_id, subscription_id, razorpay_payment_id, razorpay_invoice_id, invoice_url,
            amount_paise, currency, status, method, vpa_suffix, description, kind,
            billing_period_start, billing_period_end, paid_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'recurring', %s, %s, %s)
        ON CONFLICT (razorpay_payment_id) DO NOTHING
        """,
        (
            user_id, sub_uuid, payment_id, invoice_id, invoice_url,
            amount, currency, status, method, vpa_suffix, description,
            paid_at, paid_at, paid_at,
        ),
    )


def _on_subscription_halted(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    cur.execute(
        "UPDATE user_subscriptions SET status = 'halted', last_event_at = NOW(), updated_at = NOW() "
        "WHERE razorpay_subscription_id = %s",
        (sub_id,),
    )
    if user_id:
        cur.execute(
            "UPDATE users SET plan_expires_at = NOW() + INTERVAL '7 days', "
            "payment_failed_at = NOW(), updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


def _on_subscription_cancelled(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    cpe = sub.get("current_period_end")
    period_end = None
    if cpe:
        try:
            period_end = datetime.fromtimestamp(int(cpe), tz=timezone.utc)
        except (TypeError, ValueError):
            period_end = None
    cur.execute(
        "UPDATE user_subscriptions SET status = 'cancelled', cancelled_at = NOW(), "
        "current_period_end = COALESCE(%s, current_period_end), last_event_at = NOW(), updated_at = NOW() "
        "WHERE razorpay_subscription_id = %s",
        (period_end, sub_id),
    )
    if user_id:
        if period_end and period_end > datetime.now(timezone.utc):
            cur.execute(
                "UPDATE users SET plan = 'pro', plan_expires_at = %s, "
                "is_trial = FALSE, "
                "trial_reminder_7d_sent_at = NULL, "
                "trial_reminder_4d_sent_at = NULL, "
                "trial_reminder_2d_sent_at = NULL, "
                "updated_at = NOW() WHERE id = %s",
                (period_end, user_id),
            )
        else:
            cur.execute(
                "UPDATE users SET plan = 'free', plan_expires_at = NULL, "
                "is_trial = FALSE, "
                "trial_reminder_7d_sent_at = NULL, "
                "trial_reminder_4d_sent_at = NULL, "
                "trial_reminder_2d_sent_at = NULL, "
                "updated_at = NOW() WHERE id = %s",
                (user_id,),
            )


def _on_subscription_completed(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    cur.execute(
        "UPDATE user_subscriptions SET status = 'completed', cancelled_at = NOW(), "
        "last_event_at = NOW(), updated_at = NOW() WHERE razorpay_subscription_id = %s",
        (sub_id,),
    )
    if user_id:
        cur.execute(
            "UPDATE users SET plan = 'free', plan_expires_at = NULL, "
            "is_trial = FALSE, "
            "trial_reminder_7d_sent_at = NULL, "
            "trial_reminder_4d_sent_at = NULL, "
            "trial_reminder_2d_sent_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


def _on_subscription_paused(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    cur.execute(
        "UPDATE user_subscriptions SET status = 'paused', last_event_at = NOW(), updated_at = NOW() "
        "WHERE razorpay_subscription_id = %s",
        (sub_id,),
    )


def _on_subscription_resumed(cur, payload: dict):
    sub = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    sub_id = sub.get("id") or ""
    if not sub_id:
        return
    user_id = _notes_user_id(payload)
    cur.execute(
        "UPDATE user_subscriptions SET status = 'active', last_event_at = NOW(), updated_at = NOW() "
        "WHERE razorpay_subscription_id = %s",
        (sub_id,),
    )
    if user_id:
        cur.execute(
            "UPDATE users SET plan = 'pro', updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


_DISPATCH = {
    "payment.captured": _on_payment_captured,
    "payment.failed": _on_payment_failed,
    "subscription.activated": _on_subscription_activated,
    "subscription.charged": _on_subscription_charged,
    "subscription.halted": _on_subscription_halted,
    "subscription.cancelled": _on_subscription_cancelled,
    "subscription.completed": _on_subscription_completed,
    "subscription.paused": _on_subscription_paused,
    "subscription.resumed": _on_subscription_resumed,
}


def grace_days_left(user: dict) -> int:
    expires_at = user.get("plan_expires_at")
    failed_at = user.get("payment_failed_at")
    if not expires_at or not failed_at:
        return 0
    delta = expires_at - datetime.now(timezone.utc)
    if delta.total_seconds() <= 0:
        return 0
    return int((delta.total_seconds() + 86399) // 86400)


def trial_days_left(user: dict) -> int:
    if not user.get("is_trial"):
        return 0
    expires_at = user.get("plan_expires_at")
    if not expires_at:
        return 0
    delta = expires_at - datetime.now(timezone.utc)
    if delta.total_seconds() <= 0:
        return 0
    return int((delta.total_seconds() + 86399) // 86400)


def enforce_plan_grace(user_id: str, user: dict) -> dict:
    if user.get("is_internal"):
        return user
    if user.get("plan") != "pro":
        return user
    expires_at = user.get("plan_expires_at")
    if not expires_at:
        return user
    if expires_at > datetime.now(timezone.utc):
        return user
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET plan = 'free', plan_expires_at = NULL, "
                    "payment_failed_at = NULL, is_trial = FALSE, "
                    "trial_reminder_7d_sent_at = NULL, "
                    "trial_reminder_4d_sent_at = NULL, "
                    "trial_reminder_2d_sent_at = NULL, "
                    "updated_at = NOW() "
                    "WHERE id = %s AND plan = 'pro'",
                    (user_id,),
                )
            conn.commit()
    except psycopg.Error as e:
        logger.exception("enforce_plan_grace failed for user=%s: %s", user_id, e)
        return user
    user["plan"] = "free"
    user["plan_expires_at"] = None
    user["payment_failed_at"] = None
    user["is_trial"] = False
    user["trial_reminder_7d_sent_at"] = None
    user["trial_reminder_4d_sent_at"] = None
    user["trial_reminder_2d_sent_at"] = None
    return user


def maybe_send_trial_reminders(user_id: str, user: dict) -> bool:
    if not user.get("is_trial"):
        return False
    days_left = trial_days_left(user)
    if not (0 < days_left <= 7):
        return False
    sent = False
    thresholds = [
        (7, "trial_reminder_7d_sent_at"),
        (4, "trial_reminder_4d_sent_at"),
        (2, "trial_reminder_2d_sent_at"),
    ]
    for threshold, sent_col in thresholds:
        if days_left > threshold:
            continue
        if user.get(sent_col) is not None:
            continue
        if _fire_trial_reminder(user_id, sent_col, days_left):
            sent = True
    return sent


def _fire_trial_reminder(user_id: str, sent_col: str, days_left: int) -> bool:
    from app.services import email_service
    fresh = user_auth.find_user_by_id(user_id) or {}
    if not fresh.get("email"):
        return False
    ok, _msg_id = email_service.send_trial_ending_email(
        fresh["email"], days_left
    )
    if not ok:
        logger.warning("trial reminder send failed for user=%s days_left=%s", user_id, days_left)
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {sent_col} = NOW(), updated_at = NOW() "
                    f"WHERE id = %s AND {sent_col} IS NULL",
                    (user_id,),
                )
                updated = cur.rowcount
            conn.commit()
    except psycopg.Error as e:
        logger.exception("trial reminder mark-sent failed for user=%s: %s", user_id, e)
        return False
    if updated == 0:
        logger.info("trial reminder race: another worker already sent %s for user=%s",
                    sent_col, user_id)
    return True