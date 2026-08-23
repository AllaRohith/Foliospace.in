"""Render Cron Job — referral-program backstop. Phase C (Aug 2026).

Runs daily at 03:00 IST (cron schedule `30 21 * * *` UTC). Iterates
`v_referral_counts` and swaps any user whose active_count has crossed
REFERRAL_THRESHOLD (10) but whose subscription is still on year-2.

NO-DOWNGRADE GUARANTEE: this script ONLY swaps year-2 -> year-1. It never
swaps year-1 -> year-2. The hot-path trigger (activate_referral_if_public
in app/services/referrals.py) handles the year-1 -> year-2 path on renewal.

Standalone Python — no FastAPI app, no request context. Uses INTERNAL_TRUST_TOKEN
env var as a startup guard (matches the pattern expected by Render Cron).

Start command (see render.yaml):
    python -m app.jobs.referral_evaluator

Exit codes:
    0  — run completed (whether swaps happened or not)
    2  — preflight failure (missing env vars, etc.)
"""
import logging
import os
import sys

import psycopg
from psycopg.rows import dict_row

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("referral_evaluator")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TRUST_TOKEN = os.getenv("INTERNAL_TRUST_TOKEN", "").strip()
THRESHOLD = 10

# Lazy-imported inside main() so a missing DATABASE_URL fails fast first.
_cashfree_svc = None
_swap_to_plan = None


def _connect():
    if not DATABASE_URL:
        return None
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=10000",
    )


def _preflight() -> int | None:
    """Returns exit code if a preflight failure occurred; None if OK."""
    if not TRUST_TOKEN:
        print("INTERNAL_TRUST_TOKEN missing", file=sys.stderr)
        return 2
    if not DATABASE_URL:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    return None


def _load_dependencies() -> bool:
    """Lazy import billing/cashfree so unit tests can monkey-patch."""
    global _cashfree_svc, _swap_to_plan
    try:
        from app.services import cashfree as cashfree_svc
        from app.services.billing import _swap_to_plan
        _cashfree_svc = cashfree_svc
        _swap_to_plan = _swap_to_plan
        return True
    except Exception as e:
        logger.exception("dependency import failed: %s", e)
        return False


def _find_swap_targets(conn) -> list[dict]:
    """Users with active_count >= 10 AND a year-2 active subscription.

    Joins v_referral_counts to user_subscriptions. We only consider the
    latest subscription row per user. Free-tier users have no
    user_subscriptions row, so they are skipped — but Free has no
    year-2/y-1 distinction anyway, so this is correct.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id AS user_id,
                   s.cashfree_subscription_id AS cf_sub_id,
                   s.cashfree_plan_id       AS current_plan,
                   v.active_count
              FROM users u
              JOIN v_referral_counts v ON v.referrer_id = u.id
              JOIN user_subscriptions s ON s.user_id = u.id
             WHERE u.deleted_at IS NULL
               AND v.active_count >= %s
               AND s.cashfree_plan_id <> %s
               AND s.status IN ('active', 'authenticated')
             ORDER BY v.active_count DESC, u.created_at ASC
            """,
            (THRESHOLD, _cashfree_svc.plan_year1_id()),
        )
        rows = cur.fetchall() or []
    return rows


def main() -> int:
    rc = _preflight()
    if rc is not None:
        return rc
    if not _load_dependencies():
        return 2
    target_plan = _cashfree_svc.plan_year1_id()
    logger.info("referral_evaluator start: threshold=%s target_plan=%s", THRESHOLD, target_plan)
    try:
        with _connect() as conn:
            targets = _find_swap_targets(conn)
    except psycopg.Error as e:
        logger.exception("DB scan failed: %s", e)
        return 2
    logger.info("referral_evaluator: candidates=%d", len(targets))
    swapped = 0
    failed = 0
    for row in targets:
        uid = str(row["user_id"])
        try:
            result = _swap_to_plan(uid, target_plan, reason="referral_unlock")
            if result and result.get("swapped"):
                swapped += 1
                logger.info(
                    "swapped user=%s active_count=%d -> %s",
                    uid, row.get("active_count"), target_plan,
                )
            else:
                logger.info(
                    "skipped user=%s reason=%s",
                    uid, (result or {}).get("reason") or (result or {}).get("error"),
                )
        except Exception as e:
            failed += 1
            logger.exception("swap exception for user=%s: %s", uid, e)
    print(
        f"referral_evaluator done: candidates={len(targets)} "
        f"swapped={swapped} failed={failed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())