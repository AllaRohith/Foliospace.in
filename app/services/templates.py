import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_ID = "t1"

DEFAULT_CATALOG = [
    {
        "id": "t1",
        "name": "Editorial",
        "description": "Cream editorial spread with proof rail, what-I-do grid, and WhatsApp CTA.",
        "is_visible": True,
        "is_default": True,
        "is_pro_only": False,
        "thumb": "t1.svg",
        "sort": 1,
    },
    {
        "id": "t2",
        "name": "Developer",
        "description": "Mono accents, repo-first, contribution graph hero.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": False,
        "thumb": "t2.svg",
        "sort": 2,
    },
    {
        "id": "t3",
        "name": "Designer",
        "description": "Photo-led portfolio, large type, generous whitespace.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": False,
        "thumb": "t3.svg",
        "sort": 3,
    },
    {
        "id": "t4",
        "name": "Chef",
        "description": "Photo gallery, tasting menu rail, hours card.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": True,
        "thumb": "t4.svg",
        "sort": 4,
    },
    {
        "id": "t5",
        "name": "Consultant",
        "description": "Strategy rail, advisory pricing, calendar CTA.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": True,
        "thumb": "t5.svg",
        "sort": 5,
    },
    {
        "id": "t6",
        "name": "Shop",
        "description": "Product grid, hours, walk-in CTA.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": True,
        "thumb": "t6.svg",
        "sort": 6,
    },
    {
        "id": "t7",
        "name": "Founder",
        "description": "Thesis-led, advisory rails, angel CTA.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": True,
        "thumb": "t7.svg",
        "sort": 7,
    },
    {
        "id": "t8",
        "name": "Student",
        "description": "Coursework, internships, open-source PR list.",
        "is_visible": True,
        "is_default": False,
        "is_pro_only": False,
        "thumb": "t8.svg",
        "sort": 8,
    },
]


def _conn():
    import psycopg
    from psycopg.rows import dict_row
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg.connect(dsn, row_factory=dict_row)
    return conn


def list_catalog() -> list[dict]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM admin_settings WHERE key = 'templates'")
                row = cur.fetchone()
        if not row:
            return list(DEFAULT_CATALOG)
        data = row["value"]
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            return list(DEFAULT_CATALOG)
        out = []
        for t in data:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            out.append(
                {
                    "id": str(t["id"]),
                    "name": str(t.get("name") or t["id"]),
                    "description": str(t.get("description") or ""),
                    "is_visible": bool(t.get("is_visible", False)),
                    "is_default": bool(t.get("is_default", False)),
                    "is_pro_only": bool(t.get("is_pro_only", False)),
                    "thumb": str(t.get("thumb") or ""),
                    "sort": int(t.get("sort") or 0),
                }
            )
        out.sort(key=lambda x: (x["sort"], x["id"]))
        return out
    except Exception as e:
        logger.exception("list_catalog failed: %s", e)
        return list(DEFAULT_CATALOG)


def save_catalog(items: list[dict], updated_by: str = "") -> bool:
    payload = []
    for t in items:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        payload.append(
            {
                "id": str(t["id"]),
                "name": str(t.get("name") or t["id"]),
                "description": str(t.get("description") or ""),
                "is_visible": bool(t.get("is_visible", False)),
                "is_default": bool(t.get("is_default", False)),
                "is_pro_only": bool(t.get("is_pro_only", False)),
                "thumb": str(t.get("thumb") or ""),
                "sort": int(t.get("sort") or 0),
            }
        )
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_settings (key, value, updated_at, updated_by)
                    VALUES ('templates', %s::jsonb, now(), %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                    """,
                    (json.dumps(payload), (updated_by or "")[:128]),
                )
            conn.commit()
        return True
    except Exception as e:
        logger.exception("save_catalog failed: %s", e)
        return False


def set_visibility(template_id: str, is_visible: bool, updated_by: str = "") -> bool:
    items = list_catalog()
    found = False
    for t in items:
        if t["id"] == template_id:
            t["is_visible"] = bool(is_visible)
            found = True
            break
    if not found:
        return False
    return save_catalog(items, updated_by=updated_by)


def visible_catalog() -> list[dict]:
    return [t for t in list_catalog() if t["is_visible"]]


def get(template_id: Optional[str]) -> Optional[dict]:
    if not template_id:
        return None
    for t in list_catalog():
        if t["id"] == template_id:
            return t
    return None


def can_user_pick(user: dict, template_id: str) -> bool:
    t = get(template_id)
    if not t or not t["is_visible"]:
        return False
    if not t["is_pro_only"]:
        return True
    plan = (user.get("plan") or "").lower()
    return plan == "pro" or bool(user.get("is_internal"))


def safe_default(user: dict) -> str:
    current = (user.get("template_id") or "").strip()
    if current and get(current) and get(current)["is_visible"] and can_user_pick(user, current):
        return current
    return DEFAULT_TEMPLATE_ID