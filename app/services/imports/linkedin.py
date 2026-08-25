import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_ME_URL = "https://api.linkedin.com/v2/me?projection=(id,localizedFirstName,localizedLastName,localizedHeadline,vanityName,profilePicture(displayImage~:playableStreams))"

UNAVAILABLE_FIELDS = ["experiences", "education"]


def _str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        country = value.get("country") or value.get("countryCode") or ""
        language = value.get("language") or value.get("languageCode") or ""
        if country and language:
            return f"{language}_{country}"
        for k in ("locale", "name", "value", "id"):
            v = value.get(k)
            if isinstance(v, str) and v:
                return v
    return ""


def _http_get_bearer(url: str, token: str) -> dict | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("linkedin GET %s failed: %s", url, e)
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _extract_picture_url(me_data: dict) -> str:
    pp = me_data.get("profilePicture") or {}
    display = pp.get("displayImage~") or {}
    elements = display.get("elements") or []
    candidates = []
    for el in elements:
        for ident in el.get("identifiers") or []:
            url = (ident.get("identifier") or "").strip()
            if not url:
                continue
            try:
                w = int(ident.get("width") or 0)
            except (TypeError, ValueError):
                w = 0
            candidates.append((w, url))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


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
    if not raw:
        return {"ok": False, "reason": "fetch-failed"}
    me_raw: dict = {}
    me_err: str | None = None
    try:
        me_resp = _http_get_bearer(LINKEDIN_ME_URL, token)
        if isinstance(me_resp, dict):
            me_raw = me_resp
        else:
            me_err = "non-dict"
    except Exception as e:
        me_err = str(e)
    if me_err:
        logger.info(
            "linkedin /v2/me unavailable; headline/vanity_name skipped: %s",
            me_err,
        )
    payload = {
        "sub": _str(raw.get("sub")).strip()[:255],
        "name": _str(raw.get("name")).strip()[:160],
        "given_name": _str(raw.get("given_name")).strip()[:80],
        "family_name": _str(raw.get("family_name")).strip()[:80],
        "email": _str(raw.get("email")).strip().lower()[:254],
        "email_verified": bool(raw.get("email_verified")),
        "locale": _str(raw.get("locale")).strip()[:32],
        "zoneinfo": _str(raw.get("zoneinfo")).strip()[:64],
        "picture": _str(raw.get("picture")).strip()[:2048],
        "headline": _str(me_raw.get("localizedHeadline")).strip()[:200],
        "first_name": _str(me_raw.get("localizedFirstName")).strip()[:80],
        "last_name": _str(me_raw.get("localizedLastName")).strip()[:80],
        "vanity_name": _str(me_raw.get("vanityName")).strip().lower()[:80],
        "profile_url": "",
        "unavailable_fields": UNAVAILABLE_FIELDS,
    }
    me_picture = _extract_picture_url(me_raw)
    if me_picture:
        payload["picture"] = me_picture[:2048]
    if payload["vanity_name"]:
        payload["profile_url"] = f"https://www.linkedin.com/in/{payload['vanity_name']}"[:2048]
    if not payload["name"] and (payload["first_name"] or payload["given_name"]):
        first = payload["first_name"] or payload["given_name"]
        last = payload["last_name"] or payload["family_name"]
        payload["name"] = f"{first} {last}".strip()[:160]
    if not payload["sub"]:
        return {"ok": False, "reason": "no-sub"}
    from psycopg.types.json import Json
    from app.services.user_auth import _connect
    fields_written: list[str] = []
    try:
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
                if payload.get("headline"):
                    cur.execute(
                        """
                        UPDATE users
                           SET headline = %s,
                               role = %s,
                               updated_at = NOW()
                         WHERE id = %s
                           AND (role IS NULL OR BTRIM(role) = '')
                        """,
                        (payload["headline"][:200], payload["headline"][:60], user_id),
                    )
                    cur.execute(
                        """
                        UPDATE users
                           SET headline = %s,
                               updated_at = NOW()
                         WHERE id = %s
                           AND (headline IS NULL OR BTRIM(headline) = '')
                        """,
                        (payload["headline"][:200], user_id),
                    )
                    fields_written.append("headline")
                if payload.get("locale"):
                    cur.execute(
                        """
                        UPDATE users
                           SET locale = %s,
                               updated_at = NOW()
                         WHERE id = %s
                           AND (locale IS NULL OR BTRIM(locale) = '')
                        """,
                        (payload["locale"][:16], user_id),
                    )
                    if cur.rowcount > 0:
                        fields_written.append("locale")
                if payload.get("zoneinfo"):
                    cur.execute(
                        """
                        UPDATE users
                           SET zoneinfo = %s,
                               updated_at = NOW()
                         WHERE id = %s
                           AND (zoneinfo IS NULL OR BTRIM(zoneinfo) = '')
                        """,
                        (payload["zoneinfo"][:64], user_id),
                    )
                    if cur.rowcount > 0:
                        fields_written.append("zoneinfo")
                if payload.get("profile_url"):
                    cur.execute(
                        """
                        UPDATE users
                           SET profile_url = %s,
                               updated_at = NOW()
                         WHERE id = %s
                           AND (profile_url IS NULL OR BTRIM(profile_url) = '')
                        """,
                        (payload["profile_url"][:2048], user_id),
                    )
                    if cur.rowcount > 0:
                        fields_written.append("profile_url")
            conn.commit()
    except Exception as e:
        logger.exception("linkedin sync_basic_profile users-write failed: %s", e)
        return {"ok": False, "reason": "db-write-failed", "fields_attempted": fields_written}
    if fields_written:
        logger.info(
            "linkedin sync_basic_profile wrote fields=%s user_id=%s",
            ",".join(fields_written), user_id,
        )
    avatar_mirror = _mirror_avatar(user_id, payload.get("picture", ""))
    result = {"ok": True, "payload": payload, "fields_written": fields_written}
    if avatar_mirror is not None:
        result["avatar_mirror"] = avatar_mirror
    return result


def _mirror_avatar(user_id: str, picture_url: str) -> dict | None:
    if not picture_url or not picture_url.lower().startswith(("http://", "https://")):
        return None
    from app.services.user_auth import _connect as _uac
    with _uac() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT avatar_provider, avatar_public_id FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            current_provider = (row["avatar_provider"] or "").strip().lower()
            current_public_id = (row["avatar_public_id"] or "").strip()
            if current_provider not in ("", "linkedin"):
                return {"skipped": True, "reason": f"provider={current_provider or 'none'}"}
    from app.services import cloudinary_svc
    upload_res = cloudinary_svc.upload_remote(picture_url, user_id, kind="image")
    if not upload_res or not upload_res.get("url"):
        return {"skipped": True, "reason": "upload-failed"}
    new_url = upload_res["url"]
    new_public_id = upload_res["public_id"]
    with _uac() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                   SET avatar_url = %s,
                       avatar_public_id = %s,
                       avatar_provider = 'linkedin',
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (new_url, new_public_id, user_id),
            )
        conn.commit()
    if current_public_id and current_public_id != new_public_id:
        try:
            from app.services import cloudinary_svc as _cs
            _cs.destroy_avatar(current_public_id)
        except Exception:
            pass
    return {"ok": True, "url": new_url, "public_id": new_public_id}