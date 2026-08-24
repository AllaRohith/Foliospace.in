"""Comp grants service — pending invites + active grants reconciliation.

The comp-grants desk at /admin/users/grant grants Pro to existing users by
UUID. When the admin wants to grant to someone who isn't in `users` yet
(waitlist, cold lead, journalist, partner), we stash a `pending_comp_grants`
row keyed by email. When that person signs up and verifies their email, the
`create_user` / `create_user_from_oauth` hooks call `claim_pending_comp_grants`
IN-TRANSACTION on the signup's `cur`, which materializes a real
`subscription_grants` row + flips `users.plan='pro'`.

Pending invites have no expiry — admin manually revokes via the new
/pending-grants/{id}/revoke route.
"""
import logging
import os
import re
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row


logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=5000",
    )


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()[:254]


def _normalize_granted_by(granted_by_user_id) -> UUID | None:
    if not granted_by_user_id:
        return None
    try:
        return UUID(str(granted_by_user_id))
    except (ValueError, TypeError):
        return None


def create_pending_comp_grant(
    email: str,
    expires_at: datetime | None,
    reason: str | None,
    notes: str | None,
    granted_by_user_id,
) -> tuple[bool, str]:
    email_clean = _normalize_email(email)
    if not EMAIL_RE.match(email_clean):
        return False, "invalid-email"
    granted_by = _normalize_granted_by(granted_by_user_id)
    reason_clean = (reason or "").strip()[:500] or None
    notes_clean = (notes or "").strip()[:1000] or None
    if not DATABASE_URL:
        return False, "db-not-configured"
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pending_comp_grants
                        (email, expires_at, reason, notes, granted_by_user_id,
                         consumed_at, revoked_at)
                    VALUES (%s, %s, %s, %s, %s, NULL, NULL)
                    ON CONFLICT (email) DO UPDATE
                        SET expires_at         = EXCLUDED.expires_at,
                            reason             = EXCLUDED.reason,
                            notes              = EXCLUDED.notes,
                            granted_by_user_id = EXCLUDED.granted_by_user_id,
                            consumed_at        = NULL,
                            consumed_by_user_id = NULL,
                            revoked_at         = NULL,
                            created_at         = NOW()
                    """,
                    (email_clean, expires_at, reason_clean, notes_clean, granted_by),
                )
            conn.commit()
        return True, email_clean
    except psycopg.Error as e:
        logger.exception("create_pending_comp_grant failed for %s: %s", email_clean, e)
        return False, "db-error"


def claim_pending_comp_grants(cur, user_id, email: str) -> int:
    """Run IN-TRANSACTION on the signup's `cur`.

    SELECTs pending rows by email (excludes revoked + consumed), INSERTs into
    subscription_grants (UPSERT), UPDATEs users.plan='pro', marks consumed_at.

    Caller is responsible for wrapping in try/except — signup must not fail
    if comp logic errors. Returns count of grants claimed.
    """
    if cur is None:
        return 0
    email_clean = _normalize_email(email)
    if not email_clean:
        return 0
    try:
        uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    except (ValueError, TypeError):
        logger.warning("claim_pending_comp_grants: invalid user_id %r", user_id)
        return 0

    try:
        cur.execute(
            """
            SELECT id, expires_at, reason, notes, granted_by_user_id
              FROM pending_comp_grants
             WHERE lower(email) = lower(%s)
               AND consumed_at IS NULL
               AND revoked_at IS NULL
            """,
            (email_clean,),
        )
        rows = cur.fetchall() or []
    except psycopg.Error as e:
        logger.warning("claim_pending_comp_grants SELECT failed for %s: %s", email_clean, e)
        return 0

    claimed = 0
    for r in rows:
        try:
            cur.execute(
                """
                INSERT INTO subscription_grants
                    (user_id, granted_by_admin, expires_at, reason, notes, granted_by_user_id)
                VALUES (%s, TRUE, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                    SET expires_at         = EXCLUDED.expires_at,
                        reason             = EXCLUDED.reason,
                        notes              = EXCLUDED.notes,
                        granted_by_user_id = EXCLUDED.granted_by_user_id,
                        revoked_at         = NULL,
                        revoke_reason      = NULL,
                        revoked_by_user_id = NULL,
                        created_at         = NOW()
                """,
                (uid, r.get("expires_at"), r.get("reason"), r.get("notes"),
                 r.get("granted_by_user_id")),
            )
            cur.execute(
                """
                UPDATE users
                   SET plan = 'pro',
                       payment_failed_at = NULL,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (uid,),
            )
            cur.execute(
                """
                UPDATE pending_comp_grants
                   SET consumed_at = NOW(),
                       consumed_by_user_id = %s
                 WHERE id = %s
                """,
                (uid, r["id"]),
            )
            claimed += 1
        except psycopg.Error as e:
            logger.warning(
                "claim_pending_comp_grants row %s failed for user %s: %s",
                r.get("id"), uid, e,
            )
    return claimed


def list_pending_comp_grants(
    q: str = "",
    show_only_open: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if not DATABASE_URL:
        return [], 0
    q_clean = (q or "").strip().lower()[:128]
    where: list[str] = []
    params: list = []
    if show_only_open:
        where.append("consumed_at IS NULL AND revoked_at IS NULL")
    if q_clean:
        where.append("lower(email) LIKE %s")
        params.append(f"%{q_clean}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    rows: list[dict] = []
    total = 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) AS n FROM pending_comp_grants{where_sql}", params)
                total = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(
                    f"""
                    SELECT id, email, expires_at, reason, notes,
                           granted_by_user_id, created_at, consumed_at, revoked_at
                      FROM pending_comp_grants
                      {where_sql}
                     ORDER BY created_at DESC
                     LIMIT %s OFFSET %s
                    """,
                    [*params, limit, offset],
                )
                rows = list(cur.fetchall())
            conn.commit()
    except psycopg.Error as e:
        logger.exception("list_pending_comp_grants failed: %s", e)
    return rows, total


def get_pending_comp_grant(grant_id: int) -> dict | None:
    if not DATABASE_URL or not grant_id:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, expires_at, reason, notes,
                           granted_by_user_id, created_at, consumed_at, revoked_at
                      FROM pending_comp_grants
                     WHERE id = %s
                    """,
                    (int(grant_id),),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except psycopg.Error as e:
        logger.exception("get_pending_comp_grant failed for id=%s: %s", grant_id, e)
        return None


def revoke_pending_comp_grant(grant_id: int) -> tuple[bool, str]:
    if not DATABASE_URL or not grant_id:
        return False, "missing"
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pending_comp_grants
                       SET revoked_at = NOW()
                     WHERE id = %s AND consumed_at IS NULL AND revoked_at IS NULL
                    """,
                    (int(grant_id),),
                )
                rowcount = cur.rowcount
            conn.commit()
        if rowcount == 0:
            return False, "not-found-or-already-closed"
        return True, "ok"
    except psycopg.Error as e:
        logger.exception("revoke_pending_comp_grant failed for id=%s: %s", grant_id, e)
        return False, "db-error"


def resend_comp_invite(grant_id: int) -> tuple[bool, str]:
    """Returns (ok, msg_id_or_error). Caller wraps in BackgroundTasks."""
    from app.services import email_service

    row = get_pending_comp_grant(grant_id)
    if not row:
        return False, "not-found"
    if row.get("consumed_at"):
        return False, "already-consumed"
    if row.get("revoked_at"):
        return False, "revoked"
    email = row.get("email") or ""
    if not email:
        return False, "missing-email"
    duration_label = _duration_label(row.get("expires_at"))
    return email_service.send_comp_invite_email(
        to_email=email,
        recipient_kind="pending",
        duration_label=duration_label,
        cta_url=f"{email_service.PUBLIC_URL}/signup",
    )


def _duration_label(expires_at) -> str:
    if not expires_at:
        return "forever"
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        delta_days = (expires_at - datetime.now(timezone.utc)).days
        if delta_days >= 360:
            years = max(1, round(delta_days / 365))
            return f"{years} year" + ("s" if years != 1 else "")
        return f"{delta_days} days"
    return "forever"