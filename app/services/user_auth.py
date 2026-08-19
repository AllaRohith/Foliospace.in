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


def _slug_base_from_email(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    base = SLUG_RE.sub("-", local).strip("-")[:MAX_SLUG_LEN]
    if not base:
        base = "user"
    return base


def _slug_from_email(email: str, suffix: str) -> str:
    base = _slug_base_from_email(email)
    return f"{base}-{suffix[:6]}"


RESERVED_SLUGS = frozenset({
    "admin", "login", "signup", "logout", "logout", "me",
    "dashboard", "api", "static", "sitemap", "robots",
    "privacy", "terms", "features", "space-community",
    "about", "contact", "help", "claim", "forgot", "reset",
    "favicon", "u",
    "blog", "pricing", "teams", "changelog", "status", "app", "www",
    "staticfiles", "feed", "rss", "manifest", "service-worker",
    "robots.txt", "humans.txt", "security", "support",
})


def _slug_is_reserved(slug: str) -> bool:
    return (slug or "").lower() in RESERVED_SLUGS


def _reserve_slug(cur, email: str) -> str:
    base = _slug_base_from_email(email)
    if _slug_is_reserved(base):
        suffix = uuid4().hex
        return f"{base}-{suffix[:6]}"
    cur.execute("SELECT 1 FROM users WHERE slug = %s", (base,))
    if cur.fetchone() is None:
        return base
    suffix = uuid4().hex
    return f"{base}-{suffix[:6]}"


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
                        email_verified, created_at, updated_at,
                        plan, plan_expires_at, is_trial
                    )
                    VALUES (%s, %s, %s, %s, %s, FALSE, %s, %s,
                            'pro', %s + INTERVAL '15 days', TRUE)
                    RETURNING id, email, slug, display_name, role, email_verified,
                              created_at, updated_at, last_login_at, claimed_at,
                              claim_token, claim_expires_at, deleted_at,
                              plan, plan_expires_at, is_trial,
                              trial_reminder_7d_sent_at, trial_reminder_4d_sent_at, trial_reminder_2d_sent_at,
                              template_id
                    """,
                    (email_clean, pw_hash, slug, email_clean.split("@", 1)[0], role, now, now, now),
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
                           bio, phone, avatar_url, avatar_public_id, is_public,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at,
                           plan, plan_expires_at, payment_failed_at, razorpay_customer_id,
                           is_trial, trial_reminder_7d_sent_at, trial_reminder_4d_sent_at, trial_reminder_2d_sent_at,
                           is_internal,
                           template_id
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
                           bio, phone, avatar_url, avatar_public_id, is_public,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at,
                           plan, plan_expires_at, payment_failed_at, razorpay_customer_id,
                           is_trial, trial_reminder_7d_sent_at, trial_reminder_4d_sent_at, trial_reminder_2d_sent_at,
                           is_internal,
                           template_id
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
    from app.services.billing import enforce_plan_grace
    return enforce_plan_grace(str(user["id"]), user)


def current_user_id(request: Request) -> str | None:
    user = require_user(request)
    return str(user["id"]) if user else None


def mark_email_verified(user_id: str | UUID) -> bool:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET email_verified = TRUE,
                           updated_at      = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    """,
                    (uid,),
                )
                rowcount = cur.rowcount
            conn.commit()
        return rowcount > 0
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("mark_email_verified failed: %s", e)
        return False


def set_password(user_id: str | UUID, new_plain: str) -> bool:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    new_hash = hash_password(new_plain or "")
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET password_hash = %s,
                           updated_at    = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    """,
                    (new_hash, uid),
                )
                rowcount = cur.rowcount
            conn.commit()
        return rowcount > 0
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("set_password failed: %s", e)
        return False


def find_user_by_provider_uid(provider: str, provider_uid: str) -> dict | None:
    if not provider or not provider_uid:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.id, u.email, u.slug, u.display_name, u.role, u.bio,
                           u.phone, u.avatar_url, u.avatar_public_id, u.is_public,
                           u.plan, u.plan_expires_at, u.payment_failed_at,
                           u.is_trial, u.is_internal, u.template_id,
                           u.email_verified, u.created_at, u.deleted_at
                      FROM social_accounts sa
                      JOIN users u ON u.id = sa.user_id
                     WHERE sa.provider = %s AND sa.provider_uid = %s
                       AND u.deleted_at IS NULL
                     LIMIT 1
                    """,
                    (provider[:16], provider_uid[:255]),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except psycopg.Error as e:
        logger.exception("find_user_by_provider_uid failed: %s", e)
        return None


def link_social_account(user_id: str | UUID, provider: str, provider_uid: str, email: str | None = None) -> bool:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    clean_email = (email or "").strip().lower()[:254] or None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO social_accounts (provider, provider_uid, user_id, email)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (provider, provider_uid) DO UPDATE
                        SET email = EXCLUDED.email
                    """,
                    (provider[:16], provider_uid[:255], uid, clean_email),
                )
            conn.commit()
        return True
    except psycopg.Error as e:
        logger.exception("link_social_account failed: %s", e)
        return False


def create_user_from_oauth(
    email: str,
    provider: str,
    provider_uid: str,
    display_name: str | None = None,
    role: str | None = None,
) -> dict | None:
    email_clean = (email or "").strip().lower()[:254]
    if not email_clean or not EMAIL_RE.match(email_clean):
        return None
    uid = uuid4()
    suffix = secrets.token_hex(4)
    slug = _slug_from_email(email_clean, suffix)
    name = (display_name or "").strip()[:80] or None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users WHERE email = %s AND deleted_at IS NULL",
                    (email_clean,),
                )
                existing = cur.fetchone()
                if existing:
                    return None
                cur.execute(
                    """
                    INSERT INTO users (
                        id, email, slug, password_hash, display_name, role,
                        email_verified, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, NULL, %s, %s, TRUE, NOW(), NOW())
                    RETURNING id, email, slug, display_name, role, bio,
                              phone, avatar_url, avatar_public_id, is_public,
                              plan, plan_expires_at, payment_failed_at,
                              is_trial, is_internal, template_id,
                              email_verified, created_at
                    """,
                    (uid, email_clean, slug, name, (role or "")[:60] or None),
                )
                user = cur.fetchone()
                if user:
                    cur.execute(
                        """
                        INSERT INTO social_accounts (provider, provider_uid, user_id, email)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (provider[:16], provider_uid[:255], user["id"], email_clean),
                    )
            conn.commit()
        return user
    except psycopg.Error as e:
        logger.exception("create_user_from_oauth failed: %s", e)
        return None


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


PROFILE_FIELDS = ("display_name", "role", "bio", "phone", "avatar_url")

MAX_DISPLAY_NAME_LEN = 80
MAX_ROLE_LEN = 60
MAX_BIO_LEN = 280
MAX_PHONE_LEN = 20
MAX_AVATAR_URL_LEN = 2048
BIO_COMPLETE_MIN = 40


def _clean_text(value, max_len):
    from app.utils.text import strip_control
    return strip_control((value or "").strip())[:max_len]


def _clean_url(value):
    s = (value or "").strip()
    if not s:
        return None
    if not re.match(r"^https?://", s, re.IGNORECASE):
        raise ValueError("avatar_url must start with http:// or https://")
    return s[:MAX_AVATAR_URL_LEN]


def set_avatar(user_id, url: str, public_id: str) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET avatar_url = %s,
                           avatar_public_id = %s,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug, avatar_url, avatar_public_id
                    """,
                    (_clean_url(url), public_id[:512], uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("set_avatar failed: %s", e)
        return None
    return row


def clear_avatar(user_id) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET avatar_url = NULL,
                           avatar_public_id = NULL,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug, avatar_public_id
                    """,
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg.Error as e:
        logger.exception("clear_avatar failed: %s", e)
        return None
    return row


def update_user_profile(
    user_id,
    *,
    display_name,
    role,
    bio,
    phone,
    avatar_url=None,
    is_public,
) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    now = datetime.now(timezone.utc)
    avatar_present = avatar_url is not None and avatar_url != ""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                if avatar_present:
                    cur.execute(
                        """
                        UPDATE users
                           SET display_name = %s,
                               role         = %s,
                               bio          = %s,
                               phone        = %s,
                               avatar_url   = %s,
                               is_public    = %s,
                               updated_at   = %s
                         WHERE id = %s
                           AND deleted_at IS NULL
                        RETURNING id, email, slug, display_name, role, bio, phone, avatar_url,
                                  is_public, email_verified, created_at, updated_at,
                                  last_login_at, claimed_at, claim_token, claim_expires_at,
                                  deleted_at
                        """,
                        (
                            _clean_text(display_name, MAX_DISPLAY_NAME_LEN),
                            _clean_text(role, MAX_ROLE_LEN),
                            _clean_text(bio, MAX_BIO_LEN),
                            _clean_text(phone, MAX_PHONE_LEN),
                            _clean_url(avatar_url),
                            bool(is_public),
                            now, uid,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE users
                           SET display_name = %s,
                               role         = %s,
                               bio          = %s,
                               phone        = %s,
                               is_public    = %s,
                               updated_at   = %s
                         WHERE id = %s
                           AND deleted_at IS NULL
                        RETURNING id, email, slug, display_name, role, bio, phone, avatar_url,
                                  is_public, email_verified, created_at, updated_at,
                                  last_login_at, claimed_at, claim_token, claim_expires_at,
                                  deleted_at
                        """,
                        (
                            _clean_text(display_name, MAX_DISPLAY_NAME_LEN),
                            _clean_text(role, MAX_ROLE_LEN),
                            _clean_text(bio, MAX_BIO_LEN),
                            _clean_text(phone, MAX_PHONE_LEN),
                            bool(is_public),
                            now, uid,
                        ),
                    )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_user_profile failed: %s", e)
        return None
    return row


def update_template(user_id, template_id: str) -> dict | None:
    tid = (template_id or "").strip()[:32]
    if not tid:
        return None
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET template_id = %s,
                           updated_at  = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, template_id
                    """,
                    (tid, uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_template failed: %s", e)
        return None
    return row


def compute_completion(user) -> dict:
    dname = (user.get("display_name") or "").strip()
    role = (user.get("role") or "").strip()
    bio = (user.get("bio") or "").strip()
    phone = (user.get("phone") or "").strip()
    avatar = (user.get("avatar_url") or "").strip()
    public = bool(user.get("is_public"))
    fields = [
        ("display_name", "Display name", bool(dname)),
        ("role",         "Role",         bool(role)),
        ("bio",          "Bio (40+ chars)", bool(bio) and len(bio) >= BIO_COMPLETE_MIN),
        ("phone",        "WhatsApp number", bool(phone)),
        ("avatar_url",   "Avatar URL",   bool(avatar)),
        ("is_public",    "Public folio", public),
    ]
    filled = sum(1 for _, _, done in fields if done)
    return {
        "filled": filled,
        "total": 6,
        "fields": [{"key": k, "label": l, "done": d} for k, l, d in fields],
    }


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