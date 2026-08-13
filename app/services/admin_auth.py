import json
import logging
import os
import secrets
from datetime import datetime, timezone

import bcrypt
import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
SESSION_TTL_HOURS = int(os.getenv("ADMIN_SESSION_TTL_HOURS", "24"))
IDLE_TTL_MINUTES = int(os.getenv("ADMIN_SESSION_IDLE_MINUTES", "30"))
FAIL_WINDOW_MINUTES = int(os.getenv("ADMIN_LOGIN_FAIL_WINDOW_MINUTES", "15"))
LOCKOUT_TRIGGER_FAILS = int(os.getenv("ADMIN_LOGIN_FAILS_TRIGGER", "10"))

SESSION_COOKIE = "fs_admin"
SESSION_KEY = "admin_id"

LOGIN_INVALID_MESSAGE = "Invalid credentials."

if not DATABASE_URL:
    logger.warning("DATABASE_URL not set; admin endpoints will return 503.")
if not ADMIN_PASSWORD_HASH:
    logger.warning("ADMIN_PASSWORD_HASH not set; admin login disabled.")


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=3000",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _user_agent(request: Request) -> str:
    return (request.headers.get("user-agent", "") or "")[:512]


def verify_password(plain: str) -> bool:
    if not ADMIN_PASSWORD_HASH or not plain:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), ADMIN_PASSWORD_HASH.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def is_locked_out(ip: str) -> bool:
    if not DATABASE_URL:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) AS n
                      FROM admin_login_attempts
                     WHERE ip = %s
                       AND success = false
                       AND created_at > NOW() - make_interval(mins => %s)
                    """,
                    (ip, FAIL_WINDOW_MINUTES),
                )
                row = cur.fetchone()
                return int(row["n"] or 0) >= LOCKOUT_TRIGGER_FAILS
    except psycopg.Error as e:
        logger.exception("lockout check failed: %s", e)
        return False


def record_login_attempt(ip: str, success: bool) -> None:
    if not DATABASE_URL:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO admin_login_attempts (ip, success) VALUES (%s, %s)",
                    (ip, success),
                )
            conn.commit()
    except psycopg.Error as e:
        logger.exception("record_login_attempt failed: %s", e)


def create_session(request: Request) -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    sid = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now.timestamp() + SESSION_TTL_HOURS * 3600
    expires_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
    ip = _client_ip(request)
    ua = _user_agent(request)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_sessions
                    (id, ip, user_agent, created_at, last_used_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (sid, ip, ua, now, now, expires_dt),
            )
            _purge_old_sessions(conn)
        conn.commit()
    request.session.clear()
    request.session[SESSION_KEY] = sid
    return sid


def _purge_old_sessions(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM admin_sessions WHERE expires_at < NOW()")
        return cur.rowcount


def _slide_session(sid: str) -> bool:
    if not DATABASE_URL:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE admin_sessions
                       SET last_used_at = NOW(),
                           expires_at = NOW() + make_interval(hours => %s)
                     WHERE id = %s
                       AND expires_at > NOW()
                    RETURNING id
                    """,
                    (SESSION_TTL_HOURS, sid),
                )
                row = cur.fetchone()
                if not row:
                    return False
                _purge_old_sessions(conn)
            conn.commit()
        return True
    except psycopg.Error as e:
        logger.exception("_slide_session failed: %s", e)
        return False


def get_session_id(request: Request) -> str | None:
    return request.session.get(SESSION_KEY)


def require_admin(request: Request) -> str | None:
    sid = get_session_id(request)
    if not sid:
        return None
    if not _slide_session(sid):
        request.session.clear()
        return None
    return sid


def destroy_session(request: Request) -> None:
    sid = get_session_id(request)
    if sid and DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM admin_sessions WHERE id = %s", (sid,))
                conn.commit()
        except psycopg.Error as e:
            logger.exception("destroy_session failed: %s", e)
    request.session.clear()


def audit(
    request: Request,
    sid: str | None,
    action: str,
    target: str | None = None,
    metadata: dict | None = None,
) -> None:
    ip = _client_ip(request)
    logger.info("admin.audit action=%s ip=%s target=%s sid=%s", action, ip, target, sid or "-")
    if not DATABASE_URL:
        return
    try:
        meta_json = json.dumps(metadata, default=str) if metadata else None
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_audit_log
                        (session_id, ip, action, target, metadata)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (sid, ip, action, target, meta_json),
                )
            conn.commit()
    except psycopg.Error as e:
        logger.exception("audit insert failed: %s", e)