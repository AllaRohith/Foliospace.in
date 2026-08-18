import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

MAX_SLUG_LEN = 48
MAX_UA_LEN = 256
DAILY_SALT_ENV = "FOLIO_VIEWS_SALT"

_BOT_RE = re.compile(
    r"(bot|crawler|spider|slurp|bingpreview|facebookexternalhit|"
    r"whatsapp|telegrambot|embedly|preview|monitor|headless|"
    r"phantom|wget|curl|python-requests|scrapy|archiver)",
    re.IGNORECASE,
)


def _daily_salt() -> str:
    base = os.getenv(DAILY_SALT_ENV, "").strip()
    if base:
        return base
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"foliospace-{today}"


def hash_ip(ip: str) -> str:
    salt = _daily_salt()
    return hashlib.sha256(f"{salt}|{ip}".encode("utf-8")).hexdigest()[:32]


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").strip()
    if not ua:
        return True
    return bool(_BOT_RE.search(ua))


def _connect():
    if not DATABASE_URL:
        return None
    return psycopg.connect(
        DATABASE_URL,
        options="-c statement_timeout=2000",
    )


def record_view(
    slug: str,
    ip: str,
    user_agent: str,
    *,
    owner_user_id: str | None = None,
) -> bool:
    s = (slug or "").strip()[:MAX_SLUG_LEN]
    if not s:
        return False
    if not ip:
        return False
    if is_bot(user_agent):
        return False
    ip_h = hash_ip(ip)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO folio_views (slug, ip_hash, user_agent)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (slug, ip_hash, view_date) DO NOTHING
                    RETURNING id
                    """,
                    (s, ip_h, (user_agent or "")[:MAX_UA_LEN]),
                )
                row = cur.fetchone()
            conn.commit()
        return row is not None
    except psycopg.errors.UndefinedTable:
        logger.warning("folio_views table missing; run scripts/folio_views.sql")
        return False
    except psycopg.Error as e:
        logger.exception("record_view failed for slug=%s: %s", s, e)
        return False


def get_view_stats(slug: str, days: int = 30) -> dict:
    s = (slug or "").strip()[:MAX_SLUG_LEN]
    empty = {
        "total_views": 0,
        "unique_visitors": 0,
        "daily": [],
        "days": days,
    }
    if not s:
        return empty
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n, COUNT(DISTINCT ip_hash) AS u "
                    "FROM folio_views WHERE slug = %s",
                    (s,),
                )
                row = cur.fetchone()
                if row is None:
                    return empty
                total = int(row.get("n") or 0)
                unique = int(row.get("u") or 0)
                today = datetime.now(timezone.utc).date()
                start = today - timedelta(days=days - 1)
                cur.execute(
                    """
                    SELECT view_date,
                           COUNT(*)        AS views,
                           COUNT(DISTINCT ip_hash) AS uniques
                      FROM folio_views
                     WHERE slug = %s
                       AND view_date >= %s
                     GROUP BY view_date
                     ORDER BY view_date ASC
                    """,
                    (s, start),
                )
                rows = cur.fetchall() or []
            conn.commit()
        by_date = {r["view_date"]: r for r in rows}
        daily = []
        for i in range(days):
            d = start + timedelta(days=i)
            r = by_date.get(d)
            daily.append({
                "date": d.isoformat(),
                "views": int(r["views"]) if r else 0,
                "uniques": int(r["uniques"]) if r else 0,
            })
        return {
            "total_views": total,
            "unique_visitors": unique,
            "daily": daily,
            "days": days,
        }
    except psycopg.errors.UndefinedTable:
        return empty
    except psycopg.Error as e:
        logger.exception("get_view_stats failed for slug=%s: %s", s, e)
        return empty