import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

UNAVAILABLE_FIELDS = ["profession", "experiences", "education", "location"]


def _http_get_bearer(url: str, token: str) -> dict | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("linkedin GET %s failed: %s", url, e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_token_for(user_id: str) -> str | None:
    from app.services.imports import tokens as _tokens
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM social_accounts WHERE user_id = %s AND provider = 'linkedin'",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _tokens.decrypt(row.get("access_token"))


def sync_basic_profile(user_id: str) -> dict:
    token = get_token_for(user_id)
    if not token:
        return {"ok": False, "reason": "no-token"}
    raw = _http_get_bearer(LINKEDIN_USERINFO_URL, token)
    if not raw or not isinstance(raw, dict):
        return {"ok": False, "reason": "fetch-failed"}
    payload = {
        "sub": (raw.get("sub") or "").strip()[:255],
        "name": (raw.get("name") or "").strip()[:160],
        "given_name": (raw.get("given_name") or "").strip()[:80],
        "family_name": (raw.get("family_name") or "").strip()[:80],
        "email": (raw.get("email") or "").strip().lower()[:254],
        "email_verified": bool(raw.get("email_verified")),
        "locale": (raw.get("locale") or "").strip()[:32],
        "zoneinfo": (raw.get("zoneinfo") or "").strip()[:64],
        "picture": (raw.get("picture") or "").strip()[:2048],
        "unavailable_fields": UNAVAILABLE_FIELDS,
    }
    if not payload["name"] and payload["given_name"]:
        payload["name"] = f"{payload['given_name']} {payload['family_name']}".strip()
    if not payload["sub"]:
        return {"ok": False, "reason": "no-sub"}
    from psycopg.types.json import Json
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO imported_profile (user_id, provider, payload, fetched_at)
                VALUES (%s, 'linkedin', %s, NOW())
                ON CONFLICT (user_id, provider) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    fetched_at = NOW()
                """,
                (user_id, Json(payload)),
            )
            cur.execute(
                "UPDATE social_accounts SET last_synced_at = NOW() WHERE user_id = %s AND provider = 'linkedin'",
                (user_id,),
            )
        conn.commit()
    return {"ok": True, "payload": payload}
