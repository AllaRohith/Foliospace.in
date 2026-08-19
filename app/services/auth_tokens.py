import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_LENGTH = 6

RESET_TTL_MINUTES = 30


def _connect():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(dsn, row_factory=dict_row)


def _hash_otp(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _gen_otp_code() -> str:
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def _gen_reset_token() -> str:
    return secrets.token_urlsafe(32)


def issue_otp(email: str) -> tuple[str, datetime]:
    email_clean = (email or "").strip().lower()[:254]
    if not email_clean:
        raise ValueError("email required")
    code = _gen_otp_code()
    code_hash = _hash_otp(code)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_otps (email, code_hash, attempts, expires_at, created_at)
                    VALUES (%s, %s, 0, %s, NOW())
                    ON CONFLICT (email) DO UPDATE SET
                        code_hash   = EXCLUDED.code_hash,
                        attempts    = 0,
                        expires_at  = EXCLUDED.expires_at,
                        created_at  = EXCLUDED.created_at,
                        consumed_at = NULL
                    """,
                    (email_clean, code_hash, expires_at),
                )
            conn.commit()
    except Exception as e:
        logger.exception("issue_otp failed: %s", e)
        raise
    return code, expires_at


def resend_cooldown_remaining(email: str) -> int:
    email_clean = (email or "").strip().lower()[:254]
    if not email_clean:
        return 0
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT created_at FROM email_otps WHERE email = %s",
                    (email_clean,),
                )
                row = cur.fetchone()
        if not row:
            return 0
        created = row["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - created).total_seconds()
        return max(0, int(OTP_RESEND_COOLDOWN_SECONDS - elapsed))
    except Exception as e:
        logger.exception("resend_cooldown_remaining failed: %s", e)
        return 0


def verify_otp(email: str, code: str) -> tuple[bool, str]:
    email_clean = (email or "").strip().lower()[:254]
    code_clean = (code or "").strip()[:OTP_LENGTH]
    if not email_clean or not code_clean:
        return False, "missing"
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT code_hash, attempts, expires_at, consumed_at
                      FROM email_otps
                     WHERE email = %s
                    """,
                    (email_clean,),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return False, "no-code"
                if row["consumed_at"] is not None:
                    conn.commit()
                    return False, "consumed"
                expires_at = row["expires_at"]
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_at:
                    conn.commit()
                    return False, "expired"
                if row["attempts"] >= OTP_MAX_ATTEMPTS:
                    conn.commit()
                    return False, "locked"
                try:
                    ok = bcrypt.checkpw(
                        code_clean.encode("utf-8"),
                        (row["code_hash"] or "").encode("utf-8"),
                    )
                except Exception:
                    ok = False
                if ok:
                    cur.execute(
                        """
                        UPDATE email_otps
                           SET consumed_at = NOW()
                         WHERE email = %s
                        """,
                        (email_clean,),
                    )
                    conn.commit()
                    return True, "ok"
                cur.execute(
                    """
                    UPDATE email_otps
                       SET attempts = attempts + 1
                     WHERE email = %s
                    """,
                    (email_clean,),
                )
            conn.commit()
        return False, "bad-code"
    except Exception as e:
        logger.exception("verify_otp failed: %s", e)
        return False, "server"


def consume_otp(email: str) -> None:
    email_clean = (email or "").strip().lower()[:254]
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM email_otps WHERE email = %s", (email_clean,))
            conn.commit()
    except Exception as e:
        logger.exception("consume_otp failed: %s", e)


def issue_reset_token(user_id: str) -> str:
    if not user_id:
        raise ValueError("user_id required")
    token = _gen_reset_token()
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TTL_MINUTES)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
                    VALUES (%s, %s, %s)
                    """,
                    (token_hash, user_id, expires_at),
                )
            conn.commit()
    except Exception as e:
        logger.exception("issue_reset_token failed: %s", e)
        raise
    return token


def consume_reset_token(token: str, new_password_hash: str) -> tuple[bool, str]:
    if not token or not new_password_hash:
        return False, "missing"
    token_hash = _hash_token(token)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, expires_at, consumed_at
                      FROM password_reset_tokens
                     WHERE token_hash = %s
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return False, "not-found"
                if row["consumed_at"] is not None:
                    conn.commit()
                    return False, "consumed"
                expires_at = row["expires_at"]
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_at:
                    conn.commit()
                    return False, "expired"
                cur.execute(
                    """
                    UPDATE password_reset_tokens
                       SET consumed_at = NOW()
                     WHERE token_hash = %s
                    """,
                    (token_hash,),
                )
            conn.commit()
        return True, str(row["user_id"])
    except Exception as e:
        logger.exception("consume_reset_token failed: %s", e)
        return False, "server"


def hash_password(plain: str) -> str:
    pw = (plain or "").encode("utf-8")[: 200]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")