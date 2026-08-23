"""Referral program service. Phase C (Aug 2026).

Threshold: 10 successful referrals -> Year-1 plan stays locked at renewal.
A "successful" referral requires the referee to:
  1. have signed up via /ref/{code} (record_referral issued a 'pending' row)
  2. have verified their email   (verify_referrer flips to 'verified')
  3. have published their folio  (activate_referral_if_public flips to 'active')

Only status='active' rows count toward REFERRAL_THRESHOLD. The reward is
permanent — there is no downgrade path; once earned, always year-1.

Hot-path trigger: `activate_referral_if_public()` is called from
`user_auth.update_user_profile` the moment a referee's `is_public` transitions
FALSE -> TRUE. If the count crosses 10, it calls
`evaluate_user_referrals()` -> `billing._swap_to_plan()` -> Cashfree
`subscription.update`.

Backstop: a Render Cron Job (app/jobs/referral_evaluator.py) runs daily at
03:00 IST. It catches any race conditions or missed live hooks — the cron is
UPGRADE-ONLY (year-2 -> year-1), never year-1 -> year-2.
"""
import logging
import os
import secrets
from uuid import UUID

import psycopg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

REFERRAL_THRESHOLD = 10
MAX_CODE_GEN_ATTEMPTS = 3
CODE_LEN_BYTES = 7  # 14-char hex; ~62 bits entropy


def _connect():
    if not DATABASE_URL:
        return None
    return psycopg.connect(
        DATABASE_URL,
        row_factory=psycopg.rows.dict_row,
        options="-c statement_timeout=3000",
    )


def generate_referral_code() -> str:
    """14-char URL-safe hex. Caller loops on UNIQUE conflict."""
    return secrets.token_hex(CODE_LEN_BYTES)


def resolve_code_to_user_id(code: str) -> str | None:
    """Look up the referrer UUID for a referral code. None if unknown."""
    code = (code or "").strip()[:64]
    if not code or not DATABASE_URL:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users WHERE referral_code = %s AND deleted_at IS NULL",
                    (code,),
                )
                row = cur.fetchone()
        return str(row["id"]) if row else None
    except psycopg.Error as e:
        logger.exception("resolve_code_to_user_id failed: %s", e)
        return None


def record_referral(referrer_user_id: str, referee_user_id: str, referral_code: str) -> bool:
    """Insert a pending referrals row + UPDATE users.referred_by.

    Idempotent on duplicate referee_id (returns False). Returns True on insert.
    """
    if not (referrer_user_id and referee_user_id and referral_code):
        return False
    try:
        ref_uid = UUID(str(referrer_user_id))
        referee_uid = UUID(str(referee_user_id))
    except (ValueError, TypeError):
        return False
    if ref_uid == referee_uid:
        return False  # never self-refer
    if not DATABASE_URL:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO referrals (referrer_id, referee_id, referral_code, status)
                    VALUES (%s, %s, %s, 'pending')
                    ON CONFLICT (referee_id) DO NOTHING
                    """,
                    (ref_uid, referee_uid, referral_code[:64]),
                )
                inserted = cur.rowcount > 0
                if inserted:
                    cur.execute(
                        "UPDATE users SET referred_by = %s WHERE id = %s AND referred_by IS NULL",
                        (ref_uid, referee_uid),
                    )
            conn.commit()
        return inserted
    except psycopg.Error as e:
        logger.exception("record_referral failed: %s", e)
        return False


def verify_referrer(referee_user_id: str) -> int:
    """Flip this referee's pending row to 'verified'. Returns the new
    active_count for that referrer (0 if no row, or row not pending).

    NOTE: 'active_count' is what we care about for the threshold; flipping
    pending -> verified does NOT change active_count (it stays 0 until the
    referee publishes their folio).
    """
    if not DATABASE_URL:
        return 0
    try:
        referee_uid = UUID(str(referee_user_id))
    except (ValueError, TypeError):
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE referrals
                       SET status = 'verified', verified_at = NOW()
                     WHERE referee_id = %s AND status = 'pending'
                    RETURNING referrer_id
                    """,
                    (referee_uid,),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return 0
                referrer_id = row["referrer_id"]
                cur.execute(
                    "SELECT COUNT(*) AS n FROM referrals "
                    "WHERE referrer_id = %s AND status = 'active'",
                    (referrer_id,),
                )
                active_count = int((cur.fetchone() or {}).get("n", 0))
            conn.commit()
        return active_count
    except psycopg.Error as e:
        logger.exception("verify_referrer failed: %s", e)
        return 0


def activate_referral_if_public(referee_user_id: str, was_public: bool, now_public: bool) -> int:
    """Hook called from `user_auth.update_user_profile` on is_public save.

    Transitions verified -> active when the just-saved profile is public AND
    there is a verified row for this referee. Returns the new active_count
    for the referrer (0 if not eligible).

    Triggers `evaluate_user_referrals()` if the count just crossed the
    threshold (idempotent — safe to re-call).
    """
    if was_public or not now_public or not DATABASE_URL:
        return 0
    try:
        referee_uid = UUID(str(referee_user_id))
    except (ValueError, TypeError):
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE referrals
                       SET status = 'active', activated_at = NOW()
                     WHERE referee_id = %s AND status = 'verified'
                    RETURNING referrer_id
                    """,
                    (referee_uid,),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return 0
                referrer_id = row["referrer_id"]
                cur.execute(
                    "SELECT COUNT(*) AS n FROM referrals "
                    "WHERE referrer_id = %s AND status = 'active'",
                    (referrer_id,),
                )
                active_count = int((cur.fetchone() or {}).get("n", 0))
            conn.commit()
        if active_count >= REFERRAL_THRESHOLD:
            evaluate_user_referrals(str(referrer_id))
        return active_count
    except psycopg.Error as e:
        logger.exception("activate_referral_if_public failed: %s", e)
        return 0


def count_referrals(user_id: str) -> int:
    """Active (email-verified AND is_public=TRUE) referrals only."""
    if not DATABASE_URL:
        return 0
    try:
        uid = UUID(str(user_id))
    except (ValueError, TypeError):
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM referrals "
                    "WHERE referrer_id = %s AND status = 'active'",
                    (uid,),
                )
                row = cur.fetchone()
        return int((row or {}).get("n", 0))
    except psycopg.Error as e:
        logger.exception("count_referrals failed: %s", e)
        return 0


def evaluate_user_referrals(user_id: str) -> dict | None:
    """Re-evaluate one user. Idempotent. Called by:
      * activate_referral_if_public when active count crosses REFERRAL_THRESHOLD
      * the daily cron job (backstop)
      * future ad-hoc triggers
    """
    if not DATABASE_URL:
        return None
    if count_referrals(user_id) < REFERRAL_THRESHOLD:
        return {"swapped": False, "reason": "below_threshold"}
    # Lazy import to break circular dependency (billing imports referrals
    # service for the swap-back branch).
    try:
        from app.services import cashfree as cashfree_svc
        from app.services.billing import _swap_to_plan
        return _swap_to_plan(user_id, cashfree_svc.plan_year1_id(), reason="referral_unlock")
    except Exception as e:
        logger.exception("evaluate_user_referrals swap failed for user=%s: %s", user_id, e)
        return None


def progress_for_user(user_id: str) -> dict:
    """Dashboard-friendly progress dict."""
    count = count_referrals(user_id)
    return {
        "active_count": count,
        "threshold": REFERRAL_THRESHOLD,
        "remaining": max(0, REFERRAL_THRESHOLD - count),
        "unlocked": count >= REFERRAL_THRESHOLD,
    }
