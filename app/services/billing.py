"""Cashfree-backed billing service.

State of play (post Phase B):
* No trial. New users see "Free". Pro activates on first payment.
* Two Cashfree plans: pro_year1_discount (₹899) + pro_year2_full (₹1,499).
* Plan swap to year-2 plan happens on first `subscription.charged` webhook after
  the year-1 cycle completes. Daily cron also re-evaluates for any user whose
  renewal is within the next 7 days, in case comp state changed in between.
* Admin comp/grants are looked up FIRST — they override subscription state.
"""
import json
import logging
import os
from datetime import datetime, timezone

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from app.services import cashfree as cashfree_svc
from app.services import user_auth
from app.services.referrals import REFERRAL_THRESHOLD
from app.pricing import (
    PRO_YEAR1_INR,
    PRO_YEAR2_INR,
    FREE_PRICE_INR,
    PRO_ANNUAL_INR,
)

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


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


# ── Plan helpers ────────────────────────────────────────────────────────────────────────────────────────────────────

def pick_plan_for_new_subscription() -> str:
    """First subscription on signup always uses the year-1 discount plan."""
    return cashfree_svc.plan_year1_id()


def pick_plan_for_renewal(user_id: str) -> str | None:
    """Called on subscription.charged webhook + daily cron for near-renewals.

    Returns:
        * pro_year1 plan id — keep discount for another year (referral reward OR
                               comp grant gap returning)
        * pro_year2 plan id — move to full price
        * None — comp/grants handle the renewal (do nothing)
    """
    if not DATABASE_URL:
        return cashfree_svc.plan_year2_id()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sg.expires_at
                      FROM subscription_grants sg
                     WHERE sg.user_id = %s
                       AND sg.revoked_at IS NULL
                       AND (sg.expires_at IS NULL OR sg.expires_at > NOW())
                     LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
            conn.commit()
        if row:
            return None
    except psycopg.Error as e:
        logger.exception("pick_plan_for_renewal grant check failed: %s", e)

    # Phase C: 10+ active referrals -> keep Year-1 plan at renewal (permanent reward).
    try:
        if _referral_count(user_id) >= REFERRAL_THRESHOLD:
            return cashfree_svc.plan_year1_id()
    except psycopg.Error as e:
        logger.exception("pick_plan_for_renewal referral check failed: %s", e)
    return cashfree_svc.plan_year2_id()


def _referral_count(user_id: str) -> int:
    """Active referrals count (status='active' only). Hot path; uses partial idx."""
    if not DATABASE_URL or not user_id:
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM referrals "
                    "WHERE referrer_id = %s AND status = 'active'",
                    (user_id,),
                )
                row = cur.fetchone()
        return int((row or {}).get("n", 0))
    except psycopg.Error as e:
        logger.exception("_referral_count failed for user=%s: %s", user_id, e)
        return 0


# ── Subscriptions ─────────────────────────────────────────────────────────────────────────────────────────────────

def _get_or_create_customer_id(user: dict) -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    cust = (user.get("cashfree_customer_id") or "").strip()
    if cust:
        try:
            cashfree_svc.fetch_customer(cust)
            return cust
        except Exception:
            cust = ""
    name = (user.get("display_name") or user.get("slug") or "FolioSpace user")[:30]
    email = (user.get("email") or "")[:254]
    created = cashfree_svc.create_customer(
        name=name,
        email=email,
        contact=(user.get("phone") or "")[:20],
        user_id=str(user["id"]),
    )
    cust_id = (created or {}).get("customer_id") or (created or {}).get("id") or ""
    if not cust_id:
        raise HTTPException(status_code=502, detail="Cashfree customer create failed.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET cashfree_customer_id = %s, updated_at = NOW() WHERE id = %s",
                (cust_id, str(user["id"])),
            )
        conn.commit()
    return cust_id


def create_subscription(user_id: str) -> str:
    """Create a new Cashfree Subscription on the year-1 discount plan.

    Returns the Cashfree `subscription_session_id` (or full subscription id) — used
    by the router to redirect the user to the Cashfree checkout page.
    """
    if not cashfree_svc.is_configured():
        raise HTTPException(status_code=503, detail="Cashfree not configured.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, slug, display_name, phone, cashfree_customer_id, deleted_at "
                "FROM users WHERE id = %s LIMIT 1",
                (user_id,),
            )
            user = cur.fetchone()
        conn.commit()
    if not user or user.get("deleted_at"):
        raise HTTPException(status_code=404, detail="User not found.")
    customer_id = _get_or_create_customer_id(user)
    plan_id = pick_plan_for_new_subscription()
    sub = cashfree_svc.create_subscription(
        cf_customer_id=customer_id,
        plan_id=plan_id,
        user_id=str(user["id"]),
        slug=(user.get("slug") or ""),
    )
    cf_sub_id = sub.get("cf_subscription_id") or sub.get("subscription_id") or ""
    session_id = sub.get("subscription_session_id") or ""
    if cf_sub_id:
        _upsert_subscription_row(
            user_id=str(user["id"]),
            cf_subscription_id=cf_sub_id,
            plan_id=plan_id,
            status=(sub.get("subscription_status") or "created"),
            raw=sub,
        )
    return {"subscription_id": cf_sub_id, "session_id": session_id, "plan_id": plan_id}


def _upsert_subscription_row(
    *,
    user_id: str,
    cf_subscription_id: str,
    plan_id: str,
    status: str,
    short_url: str | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    raw: dict | None = None,
) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_subscriptions (
                    user_id, cashfree_subscription_id, cashfree_plan_id,
                    original_plan_id, status, short_url,
                    current_period_start, current_period_end, last_event_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (cashfree_subscription_id) DO UPDATE
                    SET cashfree_plan_id = EXCLUDED.cashfree_plan_id,
                        status = EXCLUDED.status,
                        short_url = COALESCE(EXCLUDED.short_url, user_subscriptions.short_url),
                        current_period_start = COALESCE(EXCLUDED.current_period_start, user_subscriptions.current_period_start),
                        current_period_end   = COALESCE(EXCLUDED.current_period_end,   user_subscriptions.current_period_end),
                        last_event_at = NOW(),
                        updated_at = NOW()
                """,
                (
                    user_id, cf_subscription_id, plan_id, plan_id, status,
                    short_url, current_period_start, current_period_end,
                ),
            )
        conn.commit()


def cancel_subscription(user_id: str) -> bool:
    if not cashfree_svc.is_configured():
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, cashfree_subscription_id, cancel_at_period_end FROM user_subscriptions "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row or row.get("cancel_at_period_end"):
        return False
    sub_id = row["cashfree_subscription_id"]
    try:
        cashfree_svc.cancel_subscription(sub_id, cancel_at_cycle_end=True)
    except Exception as e:
        logger.exception("cashfree cancel failed for sub=%s: %s", sub_id, e)
        return False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_subscriptions SET cancel_at_period_end = TRUE, updated_at = NOW(), "
                "last_event_at = NOW() WHERE cashfree_subscription_id = %s",
                (sub_id,),
            )
        conn.commit()
    return True


# ── Reads ─────────────────────────────────────────────────────────────────────────────────────────────────────────

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
                    "SELECT * FROM payments WHERE user_id = %s "
                    "ORDER BY paid_at DESC NULLS LAST, created_at DESC LIMIT %s",
                    (user_id, int(limit)),
                )
                rows = cur.fetchall() or []
            conn.commit()
        out = []
        for r in rows:
            amount_paise = int(r.get("amount_paise") or 0)
            out.append({
                "cashfree_payment_id": r.get("cashfree_payment_id") or "",
                "description": r.get("description") or "",
                "amount_paise": amount_paise,
                "amount_rupees": f"{amount_paise / 100:.2f}",
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


# ── Webhook dispatch ─────────────────────────────────────────────────────────────────────────────────────────

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
        logger.warning("billing tables missing; run scripts/cashfree_billing.sql")
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


# ── Webhook helpers ────────────────────────────────────────────────────────────────────────────────────────────

def _tags(payload: dict) -> dict:
    entity = payload.get("data") or {}
    inner = entity.get("object") or {}
    return (
        (inner.get("customer_details") or {}).get("customer_details", {})
        if isinstance(inner.get("customer_details"), dict)
        else inner.get("subscription_tags") or {}
    ) if False else (inner.get("subscription_tags") or {})


def _tags_payload(payload: dict) -> tuple[str, str]:
    """Return (user_id, slug) from Cashfree subscription_tags we set."""
    inner = (payload.get("data") or {}).get("object") or {}
    inner = inner if isinstance(inner, dict) else {}
    tags = inner.get("subscription_tags") or {}
    if not isinstance(tags, dict):
        tags = {}
    # Cashfree sometimes nests tags under "subscription_tags" inside "object"
    user_id = str(tags.get("user_id") or "").strip()
    slug = str(tags.get("slug") or "").strip()
    return user_id, slug


def _inner(payload: dict) -> dict:
    """Drill down to the inner 'object' dict in Cashfree webhook payloads."""
    inner = (payload.get("data") or {}).get("object") or {}
    return inner if isinstance(inner, dict) else {}


def _on_payment_succeeded(cur, payload: dict):
    inner = _inner(payload)
    cf_payment_id = str(inner.get("cf_payment_id") or "").strip()
    if not cf_payment_id:
        return
    user_id, _slug = _tags_payload(payload)
    if not user_id:
        return
    amount = int(inner.get("payment_amount") or 0)
    currency = (inner.get("payment_currency") or "INR").upper()
    status = (inner.get("payment_status") or "SUCCESS").lower()
    method = (inner.get("payment_method") or {}).get("payment_method") or inner.get("payment_method") or None
    description = "Pro subscription"
    paid_at_iso = inner.get("payment_completion_time") or inner.get("payment_created_at")
    paid_at = None
    if paid_at_iso:
        try:
            paid_at = datetime.fromtimestamp(int(paid_at_iso), tz=timezone.utc)
        except (TypeError, ValueError):
            paid_at = None
    invoice_id = inner.get("cf_invoice_id") or None
    invoice_url = None  # Cashfree doesn't expose a stable invoice URL pattern from webhooks yet

    cf_sub_id = str(inner.get("subscription_id") or "").strip() or None

    cur.execute(
        """
        INSERT INTO payments (
            user_id, cashfree_payment_id, cashfree_invoice_id, invoice_url,
            amount_paise, currency, status, method, description, paid_at, raw_event
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (cashfree_payment_id) DO NOTHING
        """,
        (
            user_id, cf_payment_id, invoice_id, invoice_url,
            amount, currency, status, method, description,
            paid_at, json.dumps(payload, default=str)[:64000],
        ),
    )

    # Promote user to Pro on first successful payment
    sub_uuid = None
    if cf_sub_id:
        cur.execute("SELECT id FROM user_subscriptions WHERE cashfree_subscription_id = %s LIMIT 1",
                    (cf_sub_id,))
        srow = cur.fetchone()
        sub_uuid = srow["id"] if srow else None

    if status == "success":
        cur.execute(
            "UPDATE users SET plan = 'pro', payment_failed_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


def _on_payment_failed(cur, payload: dict):
    inner = _inner(payload)
    cf_payment_id = str(inner.get("cf_payment_id") or "").strip()
    if not cf_payment_id:
        return
    user_id, _slug = _tags_payload(payload)
    if not user_id:
        return
    amount = int(inner.get("payment_amount") or 0)
    currency = (inner.get("payment_currency") or "INR").upper()
    method = (inner.get("payment_method") or {}).get("payment_method") or inner.get("payment_method") or None
    description = "Pro subscription"
    cur.execute(
        """
        INSERT INTO payments (
            user_id, cashfree_payment_id, amount_paise, currency, status,
            method, description, raw_event
        )
        VALUES (%s, %s, %s, %s, 'failed', %s, %s, %s::jsonb)
        ON CONFLICT (cashfree_payment_id) DO NOTHING
        """,
        (
            user_id, cf_payment_id, amount, currency, method, description,
            json.dumps(payload, default=str)[:64000],
        ),
    )


def _on_subscription_activated(cur, payload: dict):
    inner = _inner(payload)
    cf_sub_id = str(inner.get("cf_subscription_id") or "").strip()
    if not cf_sub_id:
        return
    user_id, _ = _tags_payload(payload)
    if not user_id:
        return
    plan_id = str(inner.get("plan_id") or "").strip()
    status = (inner.get("subscription_status") or "active").lower()
    cur.execute(
        """
        INSERT INTO user_subscriptions (
            user_id, cashfree_subscription_id, cashfree_plan_id,
            original_plan_id, status, last_event_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (cashfree_subscription_id) DO UPDATE
            SET cashfree_plan_id = EXCLUDED.cashfree_plan_id,
                status = EXCLUDED.status,
                last_event_at = NOW(),
                updated_at = NOW()
        """,
        (user_id, cf_sub_id, plan_id, plan_id, status),
    )
    cur.execute(
        "UPDATE users SET plan = 'pro', payment_failed_at = NULL, "
        "updated_at = NOW() WHERE id = %s",
        (user_id,),
    )


def _on_subscription_charged(cur, payload: dict):
    """Year-2 plan-swap trigger + period refresh."""
    inner = _inner(payload)
    cf_sub_id = str(inner.get("cf_subscription_id") or "").strip()
    if not cf_sub_id:
        return
    user_id, _ = _tags_payload(payload)
    if not user_id:
        return
    plan_id = str(inner.get("plan_id") or "").strip()
    status = (inner.get("subscription_status") or "active").lower()
    next_pay_iso = inner.get("next_charge_at") or inner.get("scheduled_charge_at")
    period_end = None
    if next_pay_iso:
        try:
            period_end = datetime.fromtimestamp(int(next_pay_iso), tz=timezone.utc)
        except (TypeError, ValueError):
            period_end = None

    cur.execute(
        """
        UPDATE user_subscriptions
           SET cashfree_plan_id = COALESCE(NULLIF(%s, ''), cashfree_plan_id),
               status = %s,
               current_period_end = COALESCE(%s, current_period_end),
               last_event_at = NOW(),
               updated_at = NOW()
         WHERE cashfree_subscription_id = %s
        """,
        (plan_id, status, period_end, cf_sub_id),
    )

    if period_end is not None:
        cur.execute(
            "UPDATE users SET plan = 'pro', plan_expires_at = %s, payment_failed_at = NULL, "
            "updated_at = NOW() WHERE id = %s",
            (period_end, user_id),
        )

    # Plan-swap decision: keep discount plan only if comp grants still active.
    # Cashfree Subscriptions doesn't include a clean "subscription.tags" roundtrip
    # in this payload, so re-fetch tags from our DB row.
    cur.execute(
        "SELECT original_plan_id FROM user_subscriptions WHERE cashfree_subscription_id = %s",
        (cf_sub_id,),
    )
    orig = cur.fetchone()
    original_plan_id = (orig or {}).get("original_plan_id") if orig else None

    target_plan = pick_plan_for_renewal(user_id)
    if target_plan and target_plan != plan_id and original_plan_id == cashfree_svc.plan_year1_id():
        # Comp gap expired mid-cycle (or never existed) and on year-1 plan — swap up.
        _swap_to_plan_in_conn(
            cur,
            user_id=user_id,
            cf_subscription_id=cf_sub_id,
            target_plan_id=target_plan,
            reason="comp_gap_expired",
        )


def _swap_to_plan_in_conn(
    cur,
    *,
    user_id: str,
    cf_subscription_id: str,
    target_plan_id: str,
    reason: str,
) -> dict:
    """Plan-swap helper that reuses an open psycopg cursor (webhook path).

    Calls Cashfree's update_subscription_plan, mirrors the new plan_id into
    user_subscriptions, and writes a user_audit_log row. Returns {"swapped": bool}.
    `reason` is one of: "comp_gap_expired", "referral_unlock", "cron_backstop".
    """
    try:
        cashfree_svc.update_subscription_plan(cf_subscription_id, target_plan_id)
    except HTTPException:
        logger.exception(
            "plan swap failed: sub=%s target=%s reason=%s",
            cf_subscription_id, target_plan_id, reason,
        )
        return {"swapped": False, "error": "cashfree_failed"}
    cur.execute(
        "UPDATE user_subscriptions SET cashfree_plan_id = %s, updated_at = NOW() "
        "WHERE cashfree_subscription_id = %s",
        (target_plan_id, cf_subscription_id),
    )
    direction = (
        "year2_to_year1" if target_plan_id == cashfree_svc.plan_year1_id()
        else "year1_to_year2"
    )
    user_auth.audit_user(
        None,
        user_id,
        f"billing.plan_swap.{direction}.{reason}",
        metadata={
            "cf_subscription_id": cf_subscription_id,
            "new_plan": target_plan_id,
            "reason": reason,
        },
    )
    return {"swapped": True, "new_plan": target_plan_id}


def _swap_to_plan(user_id: str, target_plan_id: str, *, reason: str) -> dict | None:
    """Plan-swap helper that opens its own psycopg connection.

    Used by `app/services/referrals.evaluate_user_referrals()` and by the
    daily cron (`app/jobs/referral_evaluator.py`). Both call sites do not
    have an open cursor to share.

    Idempotent — if the user's subscription is already on the target plan,
    returns {"swapped": False} without calling Cashfree.
    """
    if not DATABASE_URL:
        return None
    if not user_id or not target_plan_id:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cashfree_subscription_id, cashfree_plan_id, status
                      FROM user_subscriptions
                     WHERE user_id = %s
                     ORDER BY updated_at DESC NULLS LAST
                     LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return {"swapped": False, "reason": "no_subscription"}
        cf_sub_id = (row.get("cashfree_subscription_id") or "").strip()
        current_plan = (row.get("cashfree_plan_id") or "").strip()
        status = (row.get("status") or "").lower()
        if not cf_sub_id or current_plan == target_plan_id:
            return {"swapped": False, "reason": "already_on_target"}
        if status not in ("active", "authenticated"):
            return {"swapped": False, "reason": "sub_not_active"}
        # Open a fresh connection for the cashfree call + DB writes (Cashfree
        # call can take a few seconds; we don't want to hold a DB connection
        # open unnecessarily). Mirrors the helper above but no shared cursor.
        try:
            cashfree_svc.update_subscription_plan(cf_sub_id, target_plan_id)
        except HTTPException:
            logger.exception(
                "plan swap failed (own-conn): sub=%s target=%s reason=%s",
                cf_sub_id, target_plan_id, reason,
            )
            return {"swapped": False, "error": "cashfree_failed"}
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_subscriptions SET cashfree_plan_id = %s, updated_at = NOW() "
                    "WHERE cashfree_subscription_id = %s",
                    (target_plan_id, cf_sub_id),
                )
            conn.commit()
        direction = (
            "year2_to_year1" if target_plan_id == cashfree_svc.plan_year1_id()
            else "year1_to_year2"
        )
        user_auth.audit_user(
            None,
            user_id,
            f"billing.plan_swap.{direction}.{reason}",
            metadata={
                "cf_subscription_id": cf_sub_id,
                "new_plan": target_plan_id,
                "reason": reason,
            },
        )
        return {"swapped": True, "new_plan": target_plan_id}
    except psycopg.Error as e:
        logger.exception("_swap_to_plan DB failed: user=%s reason=%s err=%s", user_id, reason, e)
        return {"swapped": False, "error": "db_error"}


def _on_subscription_cancelled(cur, payload: dict):
    inner = _inner(payload)
    cf_sub_id = str(inner.get("cf_subscription_id") or "").strip()
    if not cf_sub_id:
        return
    user_id, _ = _tags_payload(payload)
    next_pay_iso = inner.get("next_charge_at")
    period_end = None
    if next_pay_iso:
        try:
            period_end = datetime.fromtimestamp(int(next_pay_iso), tz=timezone.utc)
        except (TypeError, ValueError):
            period_end = None
    cur.execute(
        "UPDATE user_subscriptions SET status = 'cancelled', cancelled_at = NOW(), "
        "current_period_end = COALESCE(%s, current_period_end), "
        "last_event_at = NOW(), updated_at = NOW() WHERE cashfree_subscription_id = %s",
        (period_end, cf_sub_id),
    )
    if user_id:
        if period_end and period_end > datetime.now(timezone.utc):
            cur.execute(
                "UPDATE users SET plan = 'pro', plan_expires_at = %s, updated_at = NOW() "
                "WHERE id = %s",
                (period_end, user_id),
            )
        else:
            cur.execute(
                "UPDATE users SET plan = 'free', plan_expires_at = NULL, "
                "updated_at = NOW() WHERE id = %s",
                (user_id,),
            )


def _on_subscription_completed(cur, payload: dict):
    inner = _inner(payload)
    cf_sub_id = str(inner.get("cf_subscription_id") or "").strip()
    if not cf_sub_id:
        return
    user_id, _ = _tags_payload(payload)
    cur.execute(
        "UPDATE user_subscriptions SET status = 'completed', cancelled_at = NOW(), "
        "last_event_at = NOW(), updated_at = NOW() WHERE cashfree_subscription_id = %s",
        (cf_sub_id,),
    )
    if user_id:
        cur.execute(
            "UPDATE users SET plan = 'free', plan_expires_at = NULL, updated_at = NOW() "
            "WHERE id = %s",
            (user_id,),
        )


def _on_subscription_halted(cur, payload: dict):
    inner = _inner(payload)
    cf_sub_id = str(inner.get("cf_subscription_id") or "").strip()
    if not cf_sub_id:
        return
    user_id, _ = _tags_payload(payload)
    cur.execute(
        "UPDATE user_subscriptions SET status = 'halted', last_event_at = NOW(), "
        "updated_at = NOW() WHERE cashfree_subscription_id = %s",
        (cf_sub_id,),
    )
    if user_id:
        cur.execute(
            "UPDATE users SET plan_expires_at = NOW() + INTERVAL '7 days', "
            "payment_failed_at = NOW(), updated_at = NOW() WHERE id = %s",
            (user_id,),
        )


# Cashfree event names we listen to (mapped via _DISPATCH below).
_DISPATCH = {
    "PAYMENT_SUCCESS_WEBHOOK":       _on_payment_succeeded,
    "PAYMENT_FAILED_WEBHOOK":        _on_payment_failed,
    "SUBSCRIPTION_ACTIVATED":        _on_subscription_activated,
    "SUBSCRIPTION_CHARGED":          _on_subscription_charged,
    "SUBSCRIPTION_CANCELLED":        _on_subscription_cancelled,
    "SUBSCRIPTION_COMPLETED":        _on_subscription_completed,
    "SUBSCRIPTION_HALTED":           _on_subscription_halted,
}


# ── Effective-plan decision ──────────────────────────────────────────────────────────────────────────────────

def effective_plan_for(user_id: str) -> dict:
    """Returns {plan, expires_at, source} where source ∈ {comp, subscription, free}.

    Comp grants always win. Then Cashfree subscription. Else free.
    Also returns `referral_count` (status='active' rows in referrals) so
    templates can render the "X / 10 friends" badge without a second query.
    """
    if not DATABASE_URL:
        return {"plan": "free", "expires_at": None, "source": "free", "referral_count": 0}
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sg.expires_at
                      FROM subscription_grants sg
                     WHERE sg.user_id = %s
                       AND sg.revoked_at IS NULL
                       AND (sg.expires_at IS NULL OR sg.expires_at > NOW())
                     ORDER BY sg.created_at DESC LIMIT 1
                    """,
                    (user_id,),
                )
                grant = cur.fetchone()
                if grant:
                    return {
                        "plan": "pro",
                        "expires_at": grant["expires_at"],
                        "source": "comp",
                        "referral_count": _referral_count(user_id),
                    }
                cur.execute(
                    "SELECT plan, plan_expires_at FROM users WHERE id = %s LIMIT 1",
                    (user_id,),
                )
                u = cur.fetchone()
            conn.commit()
        if not u:
            return {"plan": "free", "expires_at": None, "source": "free", "referral_count": 0}
        plan = u.get("plan") or "free"
        expires_at = u.get("plan_expires_at")
        return {
            "plan": plan,
            "expires_at": expires_at,
            "source": "subscription" if plan == "pro" else "free",
            "referral_count": _referral_count(user_id),
        }
    except psycopg.Error as e:
        logger.exception("effective_plan_for failed for user=%s: %s", user_id, e)
        return {"plan": "free", "expires_at": None, "source": "free", "referral_count": 0}


# ── Plan summary for templates ─────────────────────────────────────────────────────────────────────────────

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
    return 0  # trial disabled Phase B


def plan_summary(user: dict) -> dict:
    """Backward-compat surface for templates.

    Same shape the old Razorpay-era `plan_summary` returned. Trial state is removed.
    Grace state preserved for failed-payment scenarios.
    """
    user = user or {}
    is_internal = bool(user.get("is_internal"))
    is_pro = (user.get("plan") or "free") == "pro"
    has_grace = bool(user.get("payment_failed_at")) and bool(grace_days_left(user))
    grace_left = grace_days_left(user)

    if is_internal:
        return {
            "state": "internal",
            "plan": "pro",
            "is_unlimited": True,
            "eyebrow": "→ Founder access",
            "headline": "Unlimited access",
            "headline_html": "Unlimited <em>access.</em>",
            "sub": "Active — no expiry",
            "value_key": "Status",
            "value_val": "Active — no expiry",
            "billing_key": "Billing",
            "billing_val": "Not required",
            "pill_class": "internal",
            "pill_label": "✓ Unlimited",
            "pill_title": "Founder account — unlimited access",
            "pill_short": "✓ Unlimited",
            "cta_kind": "none",
            "cta_label": "",
            "trial_days_left": 0,
            "grace_days_left": 0,
        }
    if has_grace:
        d = f"{grace_left} day{'s' if grace_left != 1 else ''}"
        return {
            "state": "grace",
            "plan": "pro",
            "is_unlimited": False,
            "eyebrow": "→ Payment failed",
            "headline": f"Pro ends in {d}",
            "headline_html": f"Pro ends in <em>{grace_left}</em> day{'s' if grace_left != 1 else ''}",
            "sub": "Cashfree couldn't charge your last payment. Update payment to keep Pro.",
            "value_key": "Status",
            "value_val": f"⚠ Failed · {d} left",
            "billing_key": "Mandate",
            "billing_val": "UPI AutoPay — re-approve",
            "pill_class": "grace",
            "pill_label": f"⚠ Pro · {grace_left}d →",
            "pill_title": f"Payment failed — {d} grace left",
            "pill_short": f"⚠ Pro · {grace_left}d",
            "cta_kind": "update-payment",
            "cta_label": "Update payment →",
            "trial_days_left": 0,
            "grace_days_left": grace_left,
        }
    if is_pro:
        return {
            "state": "pro",
            "plan": "pro",
            "is_unlimited": False,
            "eyebrow": "→ Pro · Active",
            "headline": f"Pro · ₹{PRO_YEAR2_INR:,}/yr",
            "headline_html": f"Pro <em>₹{PRO_YEAR2_INR:,}/yr.</em>",
            "sub": "Active subscription",
            "value_key": "Status",
            "value_val": "Active",
            "billing_key": "Renewal",
            "billing_val": f"₹{PRO_YEAR2_INR:,}/yr · UPI AutoPay",
            "pill_class": "pro",
            "pill_label": "Pro · Active",
            "pill_title": "Pro subscription — manage",
            "pill_short": "Pro · Active",
            "cta_kind": "manage",
            "cta_label": "Manage →",
            "trial_days_left": 0,
            "grace_days_left": 0,
        }
    return {
        "state": "free",
        "plan": "free",
        "is_unlimited": False,
        "eyebrow": "→ Your plan",
        "headline": f"Pro features from ₹{PRO_YEAR1_INR:,}/yr",
        "headline_html": f"Pro features<br>from <strong>₹{PRO_YEAR1_INR:,}</strong>/yr",
        "sub": "UPI AutoPay or Card · annual billing · cancel any time",
        "value_key": "Status",
        "value_val": "Free",
        "billing_key": "Billing",
        "billing_val": f"₹{PRO_YEAR1_INR:,}/yr via UPI AutoPay",
        "pill_class": "free",
        "pill_label": "Free · Upgrade →",
        "pill_title": "Free tier — upgrade to Pro",
        "pill_short": "Free · Upgrade →",
        "cta_kind": "activate",
        "cta_label": f"Activate ₹{PRO_YEAR1_INR:,}/yr →",
        "trial_days_left": 0,
        "grace_days_left": 0,
    }


def enforce_plan_grace(user_id: str, user: dict) -> dict:
    """Downgrade users whose plan_expires_at has passed."""
    if user.get("is_internal"):
        return user
    if user.get("plan") != "pro":
        return user
    expires_at = user.get("plan_expires_at")
    if not expires_at or expires_at > datetime.now(timezone.utc):
        return user
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET plan = 'free', plan_expires_at = NULL, "
                    "payment_failed_at = NULL, updated_at = NOW() "
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
    return user
