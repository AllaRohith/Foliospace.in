import logging
from uuid import UUID

from app.services.user_auth import _connect

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {"pending", "approved", "rejected"}
ALLOWED_EXTENSIONS = (".ttf", ".otf", ".woff", ".woff2")
MAX_FONTS_PER_USER = 2
MAX_BYTES = 1 * 1024 * 1024


def _row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "font_name": (row["font_name"] or "").strip(),
        "file_url": row["file_url"],
        "file_public_id": row["file_public_id"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def list_fonts(user_id, status: str | None = None) -> list[dict]:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    where = "WHERE user_id = %s"
    params: list = [uid]
    if status:
        where += " AND status = %s"
        params.append(status)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, user_id, font_name, file_url, file_public_id, status, created_at
                      FROM user_fonts
                      {where}
                     ORDER BY created_at DESC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall() or []
            conn.commit()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.exception("list_fonts failed: %s", e)
        return []


def count_fonts(user_id) -> int:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM user_fonts WHERE user_id = %s",
                    (uid,),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row.get("n") or 0) if row else 0
    except Exception as e:
        logger.exception("count_fonts failed: %s", e)
        return 0


def create_font(user_id, font_name: str, file_url: str, file_public_id: str) -> dict | None:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    clean_name = (font_name or "").strip()[:60] or "Untitled"
    if not file_url.startswith("https://res.cloudinary.com/"):
        return None
    if not any(file_url.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return None
    clean_public_id = (file_public_id or "").strip()[:512]
    if not clean_public_id:
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_fonts (user_id, font_name, file_url, file_public_id, status)
                    VALUES (%s, %s, %s, %s, 'pending')
                    RETURNING id, user_id, font_name, file_url, file_public_id, status, created_at
                    """,
                    (uid, clean_name, file_url[:2048], clean_public_id),
                )
                row = cur.fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.exception("create_font failed: %s", e)
        return None


def delete_font(user_id, font_id) -> bool:
    uid = UUID(user_id) if not isinstance(user_id, UUID) else user_id
    fid = UUID(font_id) if not isinstance(font_id, UUID) else font_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM user_fonts WHERE id = %s AND user_id = %s RETURNING file_public_id",
                    (fid, uid),
                )
                row = cur.fetchone()
            conn.commit()
        return bool(row)
    except Exception as e:
        logger.exception("delete_font failed: %s", e)
        return False


def list_approved_for_user(user_id) -> list[dict]:
    return list_fonts(user_id, status="approved")


def set_font_status(font_id, status: str) -> dict | None:
    if status not in ALLOWED_STATUSES:
        return None
    fid = UUID(font_id) if not isinstance(font_id, UUID) else font_id
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_fonts
                       SET status = %s
                     WHERE id = %s
                    RETURNING id, user_id, font_name, file_url, file_public_id, status, created_at
                    """,
                    (status, fid),
                )
                row = cur.fetchone()
            conn.commit()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.exception("set_font_status failed: %s", e)
        return None