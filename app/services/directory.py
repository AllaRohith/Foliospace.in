import logging
import os

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PAGE_SIZE = 24


def _conn():
    if not DATABASE_URL:
        return None
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, options="-c statement_timeout=3000")


def list_directory(q: str = "", category: str = "", page: int = 1, per_page: int = PAGE_SIZE) -> dict:
    safe_q = (q or "").strip()[:64].lower()
    safe_cat = (category or "").strip().lower()[:32]
    page = max(1, int(page or 1))
    per_page = max(1, min(48, int(per_page or PAGE_SIZE)))
    offset = (page - 1) * per_page
    where = ["is_listed = TRUE", "is_public = TRUE", "deleted_at IS NULL", "slug IS NOT NULL"]
    params: list = []
    if safe_q:
        where.append("(lower(display_name) LIKE %s OR lower(slug) LIKE %s)")
        params.extend([f"%{safe_q}%", f"%{safe_q}%"])
    if safe_cat and safe_cat != "all":
        where.append("lower(category) = %s")
        params.append(safe_cat)
    where_sql = " AND ".join(where)
    rows: list[dict] = []
    total = 0
    conn = _conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) AS n FROM users WHERE {where_sql}", tuple(params))
                    total = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        f"""
                        SELECT id, slug, display_name, role, category, avatar_url
                          FROM users
                         WHERE {where_sql}
                         ORDER BY lower(display_name) ASC, slug ASC
                         LIMIT %s OFFSET %s
                        """,
                        [*params, per_page, offset],
                    )
                    rows = list(cur.fetchall())
        except Exception as e:
            logger.exception("list_directory failed: %s", e)
            rows = []
            total = 0
        finally:
            conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "q": safe_q,
        "category": safe_cat,
    }


def category_options() -> list[str]:
    return [
        "all", "student", "developer", "designer", "chef", "artist",
        "consultant", "writer", "researcher", "founder",
        "employee", "shop", "business", "other",
    ]
