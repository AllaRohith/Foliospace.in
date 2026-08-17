import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

import bcrypt
import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SESSION_TTL_HOURS = int(os.getenv("USER_SESSION_TTL_HOURS", "720"))
IDLE_TTL_MINUTES = int(os.getenv("USER_SESSION_IDLE_MINUTES", "1440"))
FAIL_WINDOW_MINUTES = int(os.getenv("USER_LOGIN_FAIL_WINDOW_MINUTES", "15"))
LOCKOUT_TRIGGER_FAILS = int(os.getenv("USER_LOGIN_FAILS_TRIGGER", "10"))
BCRYPT_ROUNDS = int(os.getenv("USER_BCRYPT_ROUNDS", "12"))

SESSION_COOKIE = "fs_usr"
SESSION_KEY = "user_session_id"
LOGIN_INVALID_MESSAGE = "Invalid email or password."

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_EMAIL_LEN = 254
MAX_PASSWORD_LEN = 256
MAX_SLUG_LEN = 48

if not DATABASE_URL:
    logger.warning("DATABASE_URL not set; user auth endpoints will return 503.")


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


def hash_password(plain: str) -> str:
    pw = (plain or "").encode("utf-8")[:MAX_PASSWORD_LEN]
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(pw, salt).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed or not plain:
        return False
    try:
        pw = plain.encode("utf-8")[:MAX_PASSWORD_LEN]
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _slug_from_email(email: str, suffix: str) -> str:
    local = email.split("@", 1)[0].lower()
    base = SLUG_RE.sub("-", local).strip("-")[:MAX_SLUG_LEN]
    if not base:
        base = "user"
    return f"{base}-{suffix[:6]}"


def _reserve_slug(cur, email: str) -> str:
    suffix = uuid4().hex
    candidate = _slug_from_email(email, suffix)
    cur.execute("SELECT 1 FROM users WHERE slug = %s", (candidate,))
    if cur.fetchone() is None:
        return candidate
    suffix2 = uuid4().hex
    return _slug_from_email(email, suffix2)


def create_user(email: str, password: str, role: str | None = None) -> dict:
    email_clean = (email or "").strip().lower()[:MAX_EMAIL_LEN]
    if not EMAIL_RE.match(email_clean):
        raise HTTPException(status_code=400, detail="Invalid email.")
    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    pw_hash = hash_password(password)
    now = datetime.now(timezone.utc)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (email_clean,))
                if cur.fetchone() is not None:
                    raise HTTPException(status_code=409, detail="Account already exists. Try logging in.")
                slug = _reserve_slug(cur, email_clean)
                cur.execute(
                    """
                    INSERT INTO users (
                        email, password_hash, slug, display_name, role,
                        email_verified, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, FALSE, %s, %s)
                    RETURNING id, email, slug, display_name, role, email_verified,
                              created_at, updated_at, last_login_at, claimed_at,
                              claim_token, claim_expires_at, deleted_at
                    """,
                    (email_clean, pw_hash, slug, email_clean.split("@", 1)[0], role, now, now),
                )
                row = cur.fetchone()
                prefill = _apply_waitlist_to_user(cur, row["id"], email_clean)
                if prefill:
                    row["role"] = prefill["role"] or row["role"]
                    row["created_at"] = prefill["created_at"] or row["created_at"]
                    row["prefilled_from_waitlist"] = True
                    row["waitlist_created_at"] = prefill["created_at"]
                else:
                    row["prefilled_from_waitlist"] = False
                    row["waitlist_created_at"] = None
            conn.commit()
    except psycopg.Error as e:
        logger.exception("create_user failed: %s", e)
        raise HTTPException(status_code=503, detail="Signup temporarily unavailable.")
    return row


def find_user_by_email(email: str) -> dict | None:
    email_clean = (email or "").strip().lower()[:MAX_EMAIL_LEN]
    if not DATABASE_URL or not email_clean:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, password_hash, slug, display_name, role,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at
                      FROM users
                     WHERE email = %s
                    """,
                    (email_clean,),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except psycopg.Error as e:
        logger.exception("find_user_by_email failed: %s", e)
        return None


def find_user_by_id(user_id: str | UUID) -> dict | None:
    if not DATABASE_URL or not user_id:
        return None
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, password_hash, slug, display_name, role,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at
                      FROM users
                     WHERE id = %s
                    """,
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("find_user_by_id failed: %s", e)
        return None


def find_waitlist_row(email: str) -> dict | None:
    email_clean = (email or "").strip().lower()[:MAX_EMAIL_LEN]
    if not DATABASE_URL or not email_clean:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role, created_at, utm_source FROM waitlist WHERE email = %s",
                    (email_clean,),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except psycopg.Error as e:
        logger.exception("find_waitlist_row failed: %s", e)
        return None


def _apply_waitlist_to_user(cur, user_id: UUID, email: str) -> dict | None:
    email_clean = (email or "").strip().lower()[:MAX_EMAIL_LEN]
    if not email_clean:
        return None
    cur.execute(
        "SELECT role, created_at FROM waitlist WHERE email = %s",
        (email_clean,),
    )
    row = cur.fetchone()
    if not row:
        return None
    role = row["role"]
    created_at = row["created_at"]
    cur.execute(
        """
        UPDATE users
           SET role = COALESCE(%s, role),
               created_at = COALESCE(%s, created_at)
         WHERE id = %s
        """,
        (role, created_at, user_id),
    )
    return {"role": role, "created_at": created_at}


def is_locked_out(ip: str) -> bool:
    if not DATABASE_URL:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) AS n
                      FROM user_login_attempts
                     WHERE ip = %s
                       AND success = false
                       AND created_at > NOW() - make_interval(mins => %s)
                    """,
                    (ip, FAIL_WINDOW_MINUTES),
                )
                row = cur.fetchone()
                return int(row["n"] or 0) >= LOCKOUT_TRIGGER_FAILS
    except psycopg.Error as e:
        logger.exception("user lockout check failed: %s", e)
        return False


def record_login_attempt(ip: str, email: str | None, success: bool) -> None:
    if not DATABASE_URL:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_login_attempts (ip, email, success) VALUES (%s, %s, %s)",
                    (ip, (email or "")[:MAX_EMAIL_LEN], success),
                )
            conn.commit()
    except psycopg.Error as e:
        logger.exception("record_login_attempt failed: %s", e)


def create_user_session(request: Request, user_id: str | UUID) -> str:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    sid = secrets.token_urlsafe(32)
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    now = datetime.now(timezone.utc)
    expires = now.timestamp() + SESSION_TTL_HOURS * 3600
    expires_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
    ip = _client_ip(request)
    ua = _user_agent(request)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_sessions
                        (id, user_id, ip, user_agent, created_at, last_used_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (sid, uid, ip, ua, now, now, expires_dt),
                )
                cur.execute(
                    "UPDATE users SET last_login_at = %s WHERE id = %s",
                    (now, uid),
                )
                cur.execute("DELETE FROM user_sessions WHERE expires_at < NOW()")
            conn.commit()
    except psycopg.Error as e:
        logger.exception("create_user_session failed: %s", e)
        raise HTTPException(status_code=503, detail="Login temporarily unavailable.")
    request.session.clear()
    request.session[SESSION_KEY] = sid
    return sid


def _slide_user_session(sid: str) -> tuple[str | None, str | None]:
    if not DATABASE_URL:
        return None, None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_sessions
                       SET last_used_at = NOW(),
                           expires_at = NOW() + make_interval(hours => %s)
                     WHERE id = %s
                       AND expires_at > NOW()
                       AND last_used_at > NOW() - make_interval(mins => %s)
                    RETURNING user_id
                    """,
                    (SESSION_TTL_HOURS, sid, IDLE_TTL_MINUTES),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute("DELETE FROM user_sessions WHERE id = %s", (sid,))
                    conn.commit()
                    return None, None
                cur.execute("DELETE FROM user_sessions WHERE expires_at < NOW()")
            conn.commit()
        return sid, str(row["user_id"]) if row else None
    except psycopg.Error as e:
        logger.exception("_slide_user_session failed: %s", e)
        return None, None


def require_user(request: Request) -> dict | None:
    sid = request.session.get(SESSION_KEY)
    if not sid:
        return None
    _new_sid, user_id = _slide_user_session(sid)
    if not user_id:
        request.session.clear()
        return None
    user = find_user_by_id(user_id)
    if not user or user.get("deleted_at") or not user.get("password_hash"):
        request.session.clear()
        return None
    return user


def current_user_id(request: Request) -> str | None:
    user = require_user(request)
    return str(user["id"]) if user else None


def destroy_user_session(request: Request) -> None:
    sid = request.session.get(SESSION_KEY)
    if sid and DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_sessions WHERE id = %s", (sid,))
                conn.commit()
        except psycopg.Error as e:
            logger.exception("destroy_user_session failed: %s", e)
    request.session.clear()


def audit_user(
    request: Request,
    user_id: str | None,
    action: str,
    target: str | None = None,
    metadata: dict | None = None,
) -> None:
    ip = _client_ip(request)
    sid = request.session.get(SESSION_KEY)
    if not DATABASE_URL:
        logger.info("user.audit (no-db) action=%s ip=%s target=%s user=%s", action, ip, target, user_id or "-")
        return
    try:
        meta_json = json.dumps(metadata, default=str) if metadata else None
        uid = UUID(user_id) if user_id else None
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_audit_log
                        (session_id, user_id, ip, action, target, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (sid, uid, ip, action, target, meta_json),
                )
            conn.commit()
        logger.info("user.audit action=%s ip=%s target=%s user=%s", action, ip, target, user_id or "-")
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("user audit insert failed: %s", e)