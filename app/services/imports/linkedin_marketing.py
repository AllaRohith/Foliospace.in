import logging
import os

logger = logging.getLogger(__name__)

MARKETING_NEEDED = ["r_liteprofile", "r_emailaddress"]


def _configured() -> bool:
    cid = os.getenv("LINKEDIN_MARKETING_CLIENT_ID", "").strip()
    csec = os.getenv("LINKEDIN_MARKETING_CLIENT_SECRET", "").strip()
    return bool(cid and csec)


def sync_marketing(user_id: str) -> dict:
    if not _configured():
        return {"ok": False, "reason": "not-configured"}
    token = _get_user_marketing_token(user_id)
    if not token:
        return {"ok": False, "reason": "no-token"}
    from app.services.imports import tokens as _tokens
    from app.services.user_auth import _connect
    decrypted = _tokens.decrypt(token)
    if not decrypted:
        return {"ok": False, "reason": "decrypt-failed"}
    return {"ok": False, "reason": "scaffold"}


def _get_user_marketing_token(user_id: str) -> str | None:
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access_token FROM social_accounts
                WHERE user_id = %s AND provider = 'linkedin'
                  AND access_token IS NOT NULL
                """,
                (user_id,),
            )
            row = cur.fetchone()
    return row.get("access_token") if row else None


def get_status() -> dict:
    return {
        "configured": _configured(),
        "needed_scopes": MARKETING_NEEDED,
        "env_vars_present": {
            "LINKEDIN_MARKETING_CLIENT_ID": bool(os.getenv("LINKEDIN_MARKETING_CLIENT_ID", "").strip()),
            "LINKEDIN_MARKETING_CLIENT_SECRET": bool(os.getenv("LINKEDIN_MARKETING_CLIENT_SECRET", "").strip()),
        },
    }
