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

# Trial window — disabled Phase B (2026-08). Kept as an env-driven int for one
# backward-compat SELECT that may still reference it.
from app.pricing import TRIAL_DAYS as _TRIAL_DAYS
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


def _generate_unique_referral_code() -> str:
    """14-char hex (7 random bytes). Retries on UNIQUE conflict (max 3)."""
    if not DATABASE_URL:
        return secrets.token_hex(7)  # pre-DB fallback; backfilled by migration
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                for _ in range(3):
                    code = secrets.token_hex(7)
                    cur.execute("SELECT 1 FROM users WHERE referral_code = %s", (code,))
                    if cur.fetchone() is None:
                        return code
            conn.commit()
    except psycopg.Error:
        pass
    return secrets.token_hex(7)


RESERVED_SLUGS = frozenset({
    "admin", "login", "signup", "logout", "logout", "me",
    "dashboard", "api", "static", "sitemap", "robots",
    "privacy", "terms", "features", "space-community",
    "about", "contact", "help", "claim", "forgot", "reset",
    "favicon", "u",
    "blog", "pricing", "teams", "changelog", "status", "app", "www",
    "staticfiles", "feed", "rss", "manifest", "service-worker",
    "robots.txt", "humans.txt", "security", "support",
    # SEO landing pages (see app/routers/seo_pages.py)
    "portfolio-builder", "student-portfolio", "developer-portfolio",
    "designer-portfolio", "chef-portfolio", "consultant-portfolio",
    "freelancer-portfolio", "small-business-website",
    # Phase C: referral program catch-all
    "ref",
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


def create_user(
    email: str,
    password: str,
    role: str | None = None,
    referred_by: str | None = None,
) -> dict:
    """Create a new user with email + password.

    `referred_by` is the UUID of the referring user (resolved from the
    `fs_ref` cookie by the /signup router). The Phase C referrals row is
    inserted as status='pending' and flipped to 'verified'/'active' as the
    referee progresses through verification + publishing their folio.
    """
    email_clean = (email or "").strip().lower()[:MAX_EMAIL_LEN]
    if not EMAIL_RE.match(email_clean):
        raise HTTPException(status_code=400, detail="Invalid email.")
    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    pw_hash = hash_password(password)
    now = datetime.now(timezone.utc)
    referral_code = _generate_unique_referral_code()
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
                        plan, referral_code, referred_by
                    )
                    VALUES (%s, %s, %s, %s, %s, FALSE, %s, %s,
                            'free', %s, %s)
                    RETURNING id, email, slug, display_name, role, email_verified,
                              created_at, updated_at, last_login_at, claimed_at,
                              claim_token, claim_expires_at, deleted_at,
                              plan, plan_expires_at,
                              template_id, work_rail, referral_code
                    """,
                    (
                        email_clean, pw_hash, slug, email_clean.split("@", 1)[0],
                        role, now, now, referral_code, referred_by,
                    ),
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
                try:
                    from app.services.comp_grants import claim_pending_comp_grants
                    claim_pending_comp_grants(cur, row["id"], email_clean)
                except Exception as e:
                    logger.warning("claim_pending_comp_grants failed (non-fatal): %s", e)
            conn.commit()
    except psycopg.Error as e:
        logger.exception("create_user failed: %s", e)
        raise HTTPException(status_code=503, detail="Signup temporarily unavailable.")

    # Phase C: record the referral row (pending). Idempotent — self-refer is
    # rejected inside record_referral; same referee can't be attributed twice.
    if referred_by:
        try:
            from app.services.referrals import record_referral
            record_referral(referred_by, str(row["id"]), referral_code)
        except Exception as e:
            logger.warning("record_referral failed (non-fatal): %s", e)
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
                           bio, phone, avatar_url, avatar_public_id, avatar_video_url, avatar_video_public_id, avatar_video_kind, is_public,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at,
                           plan, plan_expires_at, payment_failed_at, cashfree_customer_id,
                           is_internal,
                           template_id, linkedin_url,
                           spotlight_kind, spotlight_ref_id, spotlight_text, spotlight_url, spotlight_emoji,
                           seo_title, seo_description, og_image_override_url,
                           work_rail
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
                           bio, phone, avatar_url, avatar_public_id, avatar_video_url, avatar_video_public_id, avatar_video_kind, is_public,
                           email_verified, created_at, updated_at, last_login_at,
                           claimed_at, claim_token, claim_expires_at, deleted_at,
                           plan, plan_expires_at, payment_failed_at, cashfree_customer_id,
                           is_internal,
                           template_id, linkedin_url,
                           spotlight_kind, spotlight_ref_id, spotlight_text, spotlight_url, spotlight_emoji,
                           seo_title, seo_description, og_image_override_url,
                           work_rail
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


def _enrich_audit(user_id: str, fields: list[str]) -> None:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                import json as _json
                cur.execute(
                    """
                    INSERT INTO user_audit_log (user_id, action, target, metadata, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, NOW())
                    """,
                    (user_id, "enrich.gravatar.applied", None, _json.dumps({"fields": fields})),
                )
            conn.commit()
    except Exception:
        pass


def enrich_from_gravatar(user_id, email: str) -> dict | None:
    try:
        from app.services.imports import gravatar
    except Exception as e:
        logger.info("gravatar import failed: %s", e)
        return None
    try:
        data = gravatar.lookup(email or "")
    except Exception as e:
        logger.info("gravatar lookup failed: %s", e)
        return None
    if not data:
        return None
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role, bio, linkedin_url FROM users WHERE id = %s AND deleted_at IS NULL",
                    (uid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                new_role = (row.get("role") or "").strip() or (data.get("job_title") or "").strip()[:60] or None
                new_bio = (row.get("bio") or "").strip() or (data.get("description") or "").strip()[:280] or None
                new_linkedin = (row.get("linkedin_url") or "").strip() or (data.get("linkedin_url") or "").strip()[:2048] or None
                cur.execute(
                    """
                    UPDATE users
                       SET role = COALESCE(%s, role),
                           bio = COALESCE(%s, bio),
                           linkedin_url = COALESCE(%s, linkedin_url),
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    """,
                    (new_role, new_bio, new_linkedin, uid),
                )
            conn.commit()
        _enrich_audit(str(uid), [k for k in ("job_title", "company", "location", "description", "linkedin_url", "github_url") if data.get(k)])
        return data
    except Exception as e:
        logger.info("gravatar enrich failed for %s: %s", user_id, e)
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
    if not user or user.get("deleted_at"):
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
        if rowcount > 0:
            # Phase C: flip this referee's pending row to 'verified'. active_count
            # stays at 0 until the referee publishes their folio (the
            # update_user_profile is_public hook handles that transition).
            try:
                from app.services.referrals import verify_referrer
                verify_referrer(str(uid))
            except Exception as e:
                logger.warning("verify_referrer failed (non-fatal): %s", e)
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
                           u.phone, u.avatar_url, u.avatar_public_id, u.avatar_video_url, u.avatar_video_public_id, u.avatar_video_kind, u.is_public,
                           u.plan, u.plan_expires_at, u.payment_failed_at,
                           u.is_internal, u.template_id,
                           u.email_verified, u.created_at, u.deleted_at,
                           u.spotlight_kind, u.spotlight_ref_id, u.spotlight_text, u.spotlight_url, u.spotlight_emoji,
                           u.seo_title, u.seo_description, u.og_image_override_url,
                           u.work_rail
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
    referred_by: str | None = None,
) -> dict | None:
    """Create a user from an OAuth callback. OAuth emails are pre-verified.

    `referred_by` is the UUID of the referrer resolved from the parallel
    `fs_oauth_ref` cookie. The Phase C referrals row is inserted as
    status='pending' then immediately flipped to 'verified' (since OAuth
    emails arrive pre-verified); flips to 'active' when the referee publishes
    their folio.
    """
    email_clean = (email or "").strip().lower()[:254]
    if not email_clean or not EMAIL_RE.match(email_clean):
        return None
    uid = uuid4()
    suffix = secrets.token_hex(4)
    slug = _slug_from_email(email_clean, suffix)
    name = (display_name or "").strip()[:80] or None
    referral_code = _generate_unique_referral_code()
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
                        email_verified, created_at, updated_at,
                        plan, referral_code, referred_by
                    )
                    VALUES (%s, %s, %s, NULL, %s, %s, TRUE, NOW(), NOW(),
                            'free', %s, %s)
                    RETURNING id, email, slug, display_name, role, bio,
                              phone, avatar_url, avatar_public_id, is_public,
                              plan, plan_expires_at, payment_failed_at,
                              is_internal, template_id,
                              email_verified, created_at, linkedin_url,
                              work_rail, referral_code
                    """,
                    (uid, email_clean, slug, name, (role or "")[:60] or None,
                     referral_code, referred_by),
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
                    try:
                        from app.services.comp_grants import claim_pending_comp_grants
                        claim_pending_comp_grants(cur, user["id"], email_clean)
                    except Exception as e:
                        logger.warning("claim_pending_comp_grants failed (non-fatal): %s", e)
            conn.commit()
    except psycopg.Error as e:
        logger.exception("create_user_from_oauth failed: %s", e)
        return None

    # Phase C: record the referral row + flip pending -> verified (OAuth emails
    # are pre-verified, so the email gate is already passed). Row will then
    # flip to 'active' the moment the referee publishes their folio.
    if referred_by and user:
        try:
            from app.services.referrals import record_referral, verify_referrer
            record_referral(referred_by, str(user["id"]), referral_code)
            verify_referrer(str(user["id"]))
        except Exception as e:
            logger.warning("referral record/verify failed (non-fatal): %s", e)
    return user


def list_social_accounts(user_id: str | UUID) -> list[dict]:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider, provider_uid, email, created_at
                      FROM social_accounts
                     WHERE user_id = %s
                     ORDER BY created_at ASC
                    """,
                    (uid,),
                )
                rows = cur.fetchall() or []
            conn.commit()
        return [
            {
                "provider": (r.get("provider") or "").strip()[:16],
                "provider_uid": (r.get("provider_uid") or "").strip()[:255],
                "email": (r.get("email") or "").strip()[:254],
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("list_social_accounts failed: %s", e)
        return []


def has_password(user_id: str | UUID) -> bool:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash IS NOT NULL AS has_pw FROM users WHERE id = %s",
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
        return bool(row and row.get("has_pw"))
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("has_password failed: %s", e)
        return False


def unlink_social_account(user_id: str | UUID, provider: str) -> bool:
    uid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    pid = (provider or "").strip().lower()[:16]
    if not pid:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash IS NOT NULL AS has_pw FROM users WHERE id = %s",
                    (uid,),
                )
                user_row = cur.fetchone()
                if not user_row:
                    conn.commit()
                    return False
                cur.execute(
                    "SELECT COUNT(*) AS n FROM social_accounts WHERE user_id = %s",
                    (uid,),
                )
                count_row = cur.fetchone() or {"n": 0}
                social_count = int(count_row.get("n") or 0)
                has_pw = bool(user_row.get("has_pw"))
                if not has_pw and social_count <= 1:
                    conn.commit()
                    return False
                cur.execute(
                    "DELETE FROM social_accounts WHERE user_id = %s AND provider = %s",
                    (uid, pid),
                )
                deleted = cur.rowcount
                avatar_public_id_to_destroy = None
                if pid == "linkedin":
                    cur.execute(
                        """
                        UPDATE users
                           SET avatar_url = NULL,
                               avatar_public_id = NULL,
                               avatar_provider = NULL,
                               updated_at = NOW()
                         WHERE id = %s
                           AND avatar_provider = 'linkedin'
                        RETURNING avatar_public_id
                        """,
                        (uid,),
                    )
                    row = cur.fetchone()
                    if row and row.get("avatar_public_id"):
                        avatar_public_id_to_destroy = row["avatar_public_id"]
            conn.commit()
        if avatar_public_id_to_destroy:
            try:
                from app.services import cloudinary_svc as _cs
                _cs.destroy_avatar(avatar_public_id_to_destroy)
            except Exception:
                logger.warning("cloudinary destroy failed on linkedin avatar unlink: %s", avatar_public_id_to_destroy)
        return deleted > 0
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("unlink_social_account failed: %s", e)
        return False


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
    from app.utils.url_safety import safe_public_url
    s = (value or "").strip()
    if not s:
        return None
    if not re.match(r"^https?://", s, re.IGNORECASE):
        raise ValueError("avatar_url must start with http:// or https://")
    ok, _reason = safe_public_url(s)
    if not ok:
        raise ValueError("avatar_url must be a public http(s) URL")
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
                           avatar_provider = NULL,
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


def set_avatar_video(user_id, url: str, public_id: str, kind: str = "mp4") -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET avatar_video_url = %s,
                           avatar_video_public_id = %s,
                           avatar_video_kind = %s,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug, avatar_video_url, avatar_video_public_id, avatar_video_kind
                    """,
                    (_clean_url(url), public_id[:512], (kind or "mp4")[:16], uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("set_avatar_video failed: %s", e)
        return None
    return row


def clear_avatar_video(user_id) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET avatar_video_url = NULL,
                           avatar_video_public_id = NULL,
                           avatar_video_kind = NULL,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug, avatar_video_public_id
                    """,
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg.Error as e:
        logger.exception("clear_avatar_video failed: %s", e)
        return None
    return row


def set_spotlight(
    user_id,
    kind: str | None = None,
    ref_id: str | None = None,
    text: str | None = None,
    url: str | None = None,
    emoji: str | None = None,
) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    allowed_kinds = {"", "repo", "url", "cta"}
    clean_kind = (kind or "").strip().lower()
    if clean_kind not in allowed_kinds:
        clean_kind = "url"
    clean_ref = (ref_id or "").strip()[:128] or None
    clean_text = (text or "").strip()[:120] or None
    clean_url = (url or "").strip()[:2048] or None
    clean_emoji = (emoji or "").strip()[:16] or None
    if clean_url and not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        clean_url = None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET spotlight_kind   = %s,
                           spotlight_ref_id = %s,
                           spotlight_text   = %s,
                           spotlight_url    = %s,
                           spotlight_emoji  = %s,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug, spotlight_kind, spotlight_ref_id, spotlight_text, spotlight_url, spotlight_emoji
                    """,
                    (clean_kind or None, clean_ref, clean_text, clean_url, clean_emoji, uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("set_spotlight failed: %s", e)
        return None
    return row


def clear_spotlight(user_id) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET spotlight_kind   = NULL,
                           spotlight_ref_id = NULL,
                           spotlight_text   = NULL,
                           spotlight_url    = NULL,
                           spotlight_emoji  = NULL,
                           updated_at = NOW()
                     WHERE id = %s AND deleted_at IS NULL
                    RETURNING id, slug
                    """,
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg.Error as e:
        logger.exception("clear_spotlight failed: %s", e)
        return None
    return row


def update_user_seo(user_id, seo_title: str | None = None, seo_description: str | None = None, og_image_override_url: str | None = None) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    sets = []
    params = []
    if seo_title is not None:
        sets.append("seo_title = %s")
        params.append((seo_title or "").strip()[:70] or None)
    if seo_description is not None:
        sets.append("seo_description = %s")
        params.append((seo_description or "").strip()[:160] or None)
    if og_image_override_url is not None:
        from app.utils.url_safety import safe_public_url
        url_clean = (og_image_override_url or "").strip()[:2048] or None
        if url_clean:
            ok_url, _reason = safe_public_url(url_clean)
            if not ok_url:
                url_clean = None
        sets.append("og_image_override_url = %s")
        params.append(url_clean)
    if not sets:
        return None
    sets.append("updated_at = NOW()")
    params.append(uid)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = %s AND deleted_at IS NULL "
                    "RETURNING id, slug, seo_title, seo_description, og_image_override_url",
                    tuple(params),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_user_seo failed: %s", e)
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
    linkedin_url=None,
    headline=None,
    locale=None,
    zoneinfo=None,
    profile_url=None,
) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    now = datetime.now(timezone.utc)
    avatar_present = avatar_url is not None and avatar_url != ""
    linkedin_present = linkedin_url is not None
    linkedin_value = _clean_text(linkedin_url, 2048) if linkedin_present else None
    if linkedin_present and linkedin_value and not re.fullmatch(
        r"https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_\-]+/?", linkedin_value
    ):
        return None
    headline_present = headline is not None
    locale_present = locale is not None
    zoneinfo_present = zoneinfo is not None
    profile_url_present = profile_url is not None
    headline_clean = _clean_text(headline, 200) if headline_present else None
    if headline_present and headline and (len(headline.strip()) > 200 or not headline_clean):
        return None
    locale_clean = _clean_text(locale, 16) if locale_present else None
    if locale_present and locale_clean and not re.fullmatch(
        r"[A-Za-z]{2,3}(_[A-Z]{2})?", locale_clean
    ):
        return None
    zoneinfo_clean = _clean_text(zoneinfo, 64) if zoneinfo_present else None
    if zoneinfo_present and zoneinfo_clean and not re.fullmatch(
        r"[A-Za-z]+(/[A-Za-z_]+)*", zoneinfo_clean
    ):
        return None
    if profile_url_present and profile_url:
        try:
            profile_url_clean = _clean_url(profile_url)
        except ValueError:
            return None
        if not profile_url_clean:
            return None
    else:
        profile_url_clean = None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Phase C: capture prior is_public BEFORE the UPDATE so we can
                # detect the FALSE -> TRUE transition (the live trigger for
                # flipping a referee from verified -> active).
                cur.execute(
                    "SELECT is_public FROM users WHERE id = %s AND deleted_at IS NULL",
                    (uid,),
                )
                prior = cur.fetchone()
                prior_is_public = bool(prior and prior.get("is_public"))

                set_clauses = [
                    "display_name = %s",
                    "role         = %s",
                    "bio          = %s",
                    "phone        = %s",
                    "is_public    = %s",
                    "updated_at   = %s",
                ]
                clean_phone = _clean_text(phone, MAX_PHONE_LEN)
                clean_phone = clean_phone if clean_phone else None
                params = [
                    _clean_text(display_name, MAX_DISPLAY_NAME_LEN) or None,
                    _clean_text(role, MAX_ROLE_LEN) or None,
                    _clean_text(bio, MAX_BIO_LEN) or None,
                    clean_phone,
                    bool(is_public),
                    now,
                ]
                if avatar_present:
                    set_clauses.append("avatar_url = %s")
                    params.append(_clean_url(avatar_url))
                if linkedin_present:
                    set_clauses.append("linkedin_url = %s")
                    params.append(linkedin_value or None)
                if headline_present:
                    set_clauses.append("headline = %s")
                    params.append(headline_clean or None)
                if locale_present:
                    set_clauses.append("locale = %s")
                    params.append(locale_clean or None)
                if zoneinfo_present:
                    set_clauses.append("zoneinfo = %s")
                    params.append(zoneinfo_clean or None)
                if profile_url_present:
                    set_clauses.append("profile_url = %s")
                    params.append(profile_url_clean or None)
                params.append(uid)
                sql = f"""
                    UPDATE users
                       SET {", ".join(set_clauses)}
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, email, slug, display_name, role, bio, phone, avatar_url,
                              is_public, email_verified, created_at, updated_at,
                              last_login_at, claimed_at, claim_token, claim_expires_at,
                              deleted_at, linkedin_url, headline, locale, zoneinfo, profile_url
                """
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_user_profile failed: %s", e)
        return None

    # Phase C hook: if is_public just transitioned FALSE -> TRUE, flip any
    # verified referral row for this referee to active. May trigger a plan
    # swap if the referrer's active_count crosses the threshold.
    if row and not prior_is_public and bool(is_public):
        try:
            from app.services.referrals import activate_referral_if_public
            activate_referral_if_public(str(uid), False, True)
        except Exception as e:
            logger.warning("activate_referral_if_public failed (non-fatal): %s", e)

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


def update_repo_sort(user_id, repo_sort: str) -> dict | None:
    sort = (repo_sort or "").strip().lower()[:16]
    if sort not in ("stars", "recent", "updated"):
        return None
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET repo_sort = %s,
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, repo_sort
                    """,
                    (sort, uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_repo_sort failed: %s", e)
        return None
    return row


def update_work_rail(user_id, rows) -> dict | None:
    if not isinstance(rows, list):
        return None
    cleaned = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        title = (str(r.get("title", ""))).strip()[:60]
        body = (str(r.get("body", ""))).strip()[:120]
        if not title and not body:
            continue
        cleaned.append({"title": title, "body": body})
        if len(cleaned) >= 30:
            break
    payload = json.dumps(cleaned)
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET work_rail = %s::jsonb,
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, work_rail
                    """,
                    (payload, uid),
                )
                row = cur.fetchone()
            conn.commit()
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_work_rail failed: %s", e)
        return None
    return row


VALID_CATEGORIES = {
    "student", "developer", "designer", "chef", "artist",
    "consultant", "writer", "researcher", "founder",
    "employee", "shop", "business", "other",
}
VALID_STEPS = {"category", "connect", "first", "manage", "done"}

_ROLE_BASE_FOR_CATEGORY = {
    "student":    "student-base",
    "developer":  "developer-base",
    "designer":   "designer-base",
    "chef":       "chef-base",
    "artist":     "artist-base",
    "consultant": "consultant-base",
    "writer":     "writer-base",
    "researcher": "researcher-base",
    "founder":    "founder-base",
    "employee":   "employee-base",
    "shop":       "shop-base",
    "business":   "business-base",
    "other":      "other-base",
}


def set_category(user_id, category: str) -> dict | None:
    cat = (category or "").strip().lower()[:32]
    if cat not in VALID_CATEGORIES:
        return None
    template_id = _ROLE_BASE_FOR_CATEGORY.get(cat, "other-base")
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET category = %s,
                           role = COALESCE(NULLIF(role, ''), %s),
                           template_id = %s,
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, category, role, template_id
                    """,
                    (cat, cat, template_id, uid),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("set_category failed: %s", e)
        return None


def update_onboarding_step(user_id, step: str) -> dict | None:
    s = (step or "").strip().lower()[:32]
    if s not in VALID_STEPS:
        return None
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET onboarding_step = %s,
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, onboarding_step
                    """,
                    (s, uid),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_onboarding_step failed: %s", e)
        return None


def update_listing(user_id, is_listed: bool) -> dict | None:
    try:
        uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                       SET is_listed = %s,
                           updated_at = NOW()
                     WHERE id = %s
                       AND deleted_at IS NULL
                    RETURNING id, is_listed
                    """,
                    (bool(is_listed), uid),
                )
                row = cur.fetchone()
            conn.commit()
        return row
    except (psycopg.Error, ValueError, TypeError) as e:
        logger.exception("update_listing failed: %s", e)
        return None


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