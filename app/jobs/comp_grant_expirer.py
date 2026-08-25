"""Render Cron Job — comp-grant expiry warnings + stale-state cleanup.

Runs daily at 02:00 IST (cron schedule `30 20 * * *` UTC), 30 minutes before
the referral-evaluator cron at 21:30 UTC. Two passes:

1. **Warning sweeps (14d, 7d, 1d).** Find comp grants with `expires_at` inside
   the target window that haven't been warned at that stage yet. Send a
   single Resend email per (grant, stage) and stamp the matching
   `warn_Nd_sent_at` column. Three partial indexes keep the SELECT cheap.

2. **Flip-expired sweep.** Find comp grants with `expires_at < NOW()` and
   `revoked_at IS NULL`, where the user has no other active grant AND no
   active paid subscription (`user_subscriptions.status IN ('active',
   'authenticated')` with a future `current_period_end`). For each match,
   set `users.plan='free'` and `users.plan_expires_at=NULL`. Defends
   against the stale-state bug where users kept silent Pro access after a
   comp expired. Also a backstop for comp-vs-paid users whose comp was
   created before `_on_subscription_activated` learned to revoke it.

Stale-state bug fix + three-stage email cadence. Always-shown banner on
every dashboard page is wired separately in the templates.

Standalone Python — no FastAPI app, no request context. Uses
INTERNAL_TRUST_TOKEN env var as a startup guard (matches the pattern
Render Cron expects).

Start command (see render.yaml):
    python -m app.jobs.comp_grant_expirer

Exit codes:
    0  — run completed (whether warnings went out or not)
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
logger = logging.getLogger("comp_grant_expirer")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TRUST_TOKEN = os.getenv("INTERNAL_TRUST_TOKEN", "").strip()

WARN_STAGES = (14, 7, 1)


def _connect():
    if not DATABASE_URL:
        return None
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=10000",
    )


def _preflight() -> int | None:
    if not TRUST_TOKEN:
        print("INTERNAL_TRUST_TOKEN missing", file=sys.stderr)
        return 2
    if not DATABASE_URL:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    return None


def _warn_column(days: int) -> str:
    return {14: "warn_14d_sent_at", 7: "warn_7d_sent_at", 1: "warn_1d_sent_at"}[days]


def _find_warning_targets(conn, days: int) -> list[dict]:
    col = _warn_column(days)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT sg.id    AS grant_id,
                   sg.user_id,
                   sg.expires_at,
                   u.email,
                   u.slug
              FROM subscription_grants sg
              JOIN users u ON u.id = sg.user_id
             WHERE sg.revoked_at IS NULL
               AND sg.expires_at IS NOT NULL
               AND sg.expires_at >= (NOW() + INTERVAL '%d days')
               AND sg.expires_at <  (NOW() + INTERVAL '%d days')
               AND sg.{col} IS NULL
             ORDER BY sg.expires_at ASC
            """ % (days, days + 1),
        )
        return list(cur.fetchall() or [])


def _send_warning(grant: dict, days: int) -> bool:
    from app.services.email_service import PUBLIC_URL, send_comp_expiry_warning_email
    expires_at = grant.get("expires_at")
    expires_date = ""
    if expires_at:
        try:
            expires_date = expires_at.strftime("%-d %B %Y")
        except ValueError:
            expires_date = expires_at.strftime("%d %B %Y")
    cta_url = f"{PUBLIC_URL}/dashboard/billing"
    ok, _msg_id = send_comp_expiry_warning_email(
        to_email=grant.get("email") or "",
        days_left=days,
        expires_date=expires_date,
        cta_url=cta_url,
    )
    return ok


def _mark_warning_sent(conn, grant_id: int, days: int) -> None:
    col = _warn_column(days)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE subscription_grants SET {col} = NOW() WHERE id = %s",
            (grant_id,),
        )


def _run_warning_sweep(conn, days: int) -> tuple[int, int, int]:
    """Returns (sent, dedup_skipped, failed)."""
    targets = _find_warning_targets(conn, days)
    if not targets:
        return (0, 0, 0)
    sent = 0
    failed = 0
    for grant in targets:
        try:
            if _send_warning(grant, days):
                _mark_warning_sent(conn, grant["grant_id"], days)
                conn.commit()
                sent += 1
            else:
                failed += 1
                logger.warning(
                    "warning email not sent user=%s days=%d",
                    str(grant.get("user_id"))[:8], days,
                )
        except Exception as e:
            failed += 1
            logger.exception(
                "warning sweep exception grant_id=%s days=%d: %s",
                grant.get("grant_id"), days, e,
            )
    return (sent, 0, failed)


def _find_expired_targets(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sg.user_id, sg.id AS grant_id
              FROM subscription_grants sg
             WHERE sg.revoked_at IS NULL
               AND sg.expires_at IS NOT NULL
               AND sg.expires_at < NOW()
               AND NOT EXISTS (
                   SELECT 1 FROM subscription_grants sg2
                    WHERE sg2.user_id = sg.user_id
                      AND sg2.revoked_at IS NULL
                      AND (sg2.expires_at IS NULL OR sg2.expires_at > NOW())
               )
               AND NOT EXISTS (
                   SELECT 1 FROM user_subscriptions s
                    WHERE s.user_id = sg.user_id
                      AND s.status IN ('active', 'authenticated')
                      AND (s.current_period_end IS NULL OR s.current_period_end > NOW())
               )
            """,
        )
        return list(cur.fetchall() or [])


def _flip_to_free(conn, user_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
               SET plan = 'free',
                   plan_expires_at = NULL,
                   payment_failed_at = NULL,
                   updated_at = NOW()
             WHERE id = %s AND plan = 'pro'
            """,
            (user_id,),
        )
        flipped = cur.rowcount > 0
        if flipped:
            try:
                cur.execute(
                    """
                    INSERT INTO user_audit_log
                        (session_id, user_id, ip, action, target, metadata)
                    VALUES (NULL, %s, 'cron', 'billing.comp_expired_flip',
                            'cron:comp_grant_expirer',
                            '{"reason":"cron:comp_grant_expirer"}'::jsonb)
                    """,
                    (user_id,),
                )
            except psycopg.Error as e:
                logger.exception(
                    "audit insert failed during flip user=%s: %s",
                    str(user_id)[:8], e,
                )
    return flipped


def _run_flip_sweep(conn) -> tuple[int, int]:
    """Returns (flipped, guarded_by_sub_or_other_grant)."""
    targets = _find_expired_targets(conn)
    if not targets:
        return (0, 0)
    flipped = 0
    guarded = 0
    for row in targets:
        try:
            if _flip_to_free(conn, row["user_id"]):
                conn.commit()
                flipped += 1
                logger.info(
                    "flipped user=%s from comp expiry (grant_id=%s)",
                    str(row["user_id"])[:8], row["grant_id"],
                )
            else:
                guarded += 1
        except Exception as e:
            logger.exception(
                "flip exception user=%s: %s",
                str(row.get("user_id"))[:8], e,
            )
    return (flipped, guarded)


def main() -> int:
    rc = _preflight()
    if rc is not None:
        return rc
    logger.info("comp_grant_expirer start: stages=%s", WARN_STAGES)
    totals = {d: {"sent": 0, "failed": 0} for d in WARN_STAGES}
    flipped = 0
    guarded = 0
    try:
        with _connect() as conn:
            for days in WARN_STAGES:
                try:
                    sent, _dedup, failed = _run_warning_sweep(conn, days)
                    totals[days]["sent"] = sent
                    totals[days]["failed"] = failed
                except psycopg.Error as e:
                    logger.exception("warning sweep %dd failed: %s", days, e)
                except Exception as e:
                    logger.exception("warning sweep %dd unexpected: %s", days, e)
            try:
                flipped, guarded = _run_flip_sweep(conn)
            except psycopg.Error as e:
                logger.exception("flip sweep failed: %s", e)
            except Exception as e:
                logger.exception("flip sweep unexpected: %s", e)
    except psycopg.Error as e:
        logger.exception("DB connect failed: %s", e)
        return 2
    summary = " ".join(
        f"{d}d:sent={totals[d]['sent']},failed={totals[d]['failed']}" for d in WARN_STAGES
    )
    print(
        f"comp_grant_expirer done: {summary} "
        f"flipped={flipped} guarded={guarded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())