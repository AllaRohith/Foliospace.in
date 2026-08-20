import logging
from uuid import UUID

from app.services.user_auth import _connect

logger = logging.getLogger(__name__)

ALLOWED_LAYOUTS = {"stack", "grid", "carousel"}
FREE_TIER_MAX = 10
ICON_ALIASES = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "spotify.com": "spotify",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "github.com": "github",
}


def detect_icon(url: str) -> str:
    if not url:
        return "link"
    lowered = url.lower()
    for needle, icon in ICON_ALIASES.items():
        if needle in lowered:
            return icon
    return "link"


def _row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "label": (row["label"] or "").strip(),
        "url": (row["url"] or "").strip(),
        "icon": (row["icon"] or "link").strip(),
        "layout": (row["layout"] or "stack").strip(),
        "position": int(row.get("position") or 0),
        "created_at": row.get("created_at"),
    }


def list_links(user_id) -> list[dict]:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, label, url, icon, layout, position, created_at
                      FROM user_links
                     WHERE user_id = %s
                     ORDER BY position ASC, created_at ASC
                    """,
                    (uid,),
                )
                rows = cur.fetchall() or []
            conn.commit()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.exception("list_links failed: %s", e)
        return []


def count_links(user_id) -> int:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM user_links WHERE user_id = %s",
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
        return int((row or {}).get("n") or 0) if row else 0
    except Exception as e:
        logger.exception("count_links failed: %s", e)
        return 0


def create_link(user_id, label: str, url: str, layout: str = "stack", is_pro: bool = False) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    if layout not in ALLOWED_LAYOUTS:
        layout = "stack"
    clean_label = (label or "").strip()[:80] or "Untitled"
    clean_url = (url or "").strip()[:2048]
    if not clean_url.startswith(("http://", "https://")):
        return None
    if not is_pro and count_links(uid) >= FREE_TIER_MAX:
        return None
    icon = detect_icon(clean_url)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(position), -1) AS m FROM user_links WHERE user_id = %s",
                    (uid,),
                )
                max_pos = int((cur.fetchone() or {}).get("m") or -1)
                cur.execute(
                    """
                    INSERT INTO user_links (user_id, label, url, icon, layout, position)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, label, url, icon, layout, position, created_at
                    """,
                    (uid, clean_label, clean_url, icon, layout, max_pos + 1),
                )
                row = cur.fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.exception("create_link failed: %s", e)
        return None


def update_link(user_id, link_id, label: str | None = None, url: str | None = None, layout: str | None = None) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    fid = UUID(link_id) if not isinstance(link_id, UUID) else link_id
    sets: list[str] = []
    params: list = []
    if label is not None:
        clean_label = (label or "").strip()[:80] or "Untitled"
        sets.append("label = %s")
        params.append(clean_label)
    if url is not None:
        clean_url = (url or "").strip()[:2048]
        if not clean_url.startswith(("http://", "https://")):
            return None
        sets.append("url = %s")
        params.append(clean_url)
        sets.append("icon = %s")
        params.append(detect_icon(clean_url))
    if layout is not None:
        if layout not in ALLOWED_LAYOUTS:
            layout = "stack"
        sets.append("layout = %s")
        params.append(layout)
    if not sets:
        return None
    params.extend([fid, uid])
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE user_links SET {', '.join(sets)}
                     WHERE id = %s AND user_id = %s
                    RETURNING id, user_id, label, url, icon, layout, position, created_at
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.exception("update_link failed: %s", e)
        return None


def delete_link(user_id, link_id) -> bool:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    fid = UUID(link_id) if not isinstance(link_id, UUID) else link_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_links WHERE id = %s AND user_id = %s RETURNING id",
                    (fid, uid),
                )
                row = cur.fetchone()
            conn.commit()
        return bool(row)
    except Exception as e:
        logger.exception("delete_link failed: %s", e)
        return False


def reorder_links(user_id, ordered_ids: list[str]) -> bool:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    parsed: list = []
    for lid in ordered_ids:
        try:
            parsed.append(UUID(lid))
        except Exception:
            return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                for idx, fid in enumerate(parsed):
                    cur.execute(
                        "UPDATE user_links SET position = %s WHERE id = %s AND user_id = %s",
                        (idx, fid, uid),
                    )
            conn.commit()
        return True
    except Exception as e:
        logger.exception("reorder_links failed: %s", e)
        return False
