import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

VALID_ROLES = {
    "student", "developer", "designer", "chef", "artist", "consultant",
    "writer", "researcher", "founder", "employee", "shop", "business", "other",
}

ROLE_DEFAULT_TEMPLATE = {
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

DEFAULT_TEMPLATE_ID = "other-base"

DEFAULT_CATALOG = [
    {"id": "chef-base",       "name": "Chef Base",       "role": "chef",       "description": "Showcase dishes, experience, and a direct message CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "chef.svg",       "sort": 1},
    {"id": "developer-base",  "name": "Developer Base",  "role": "developer",  "description": "Repos, contribution graph, tech stack, project history.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "developer.svg",  "sort": 2},
    {"id": "designer-base",   "name": "Designer Base",   "role": "designer",   "description": "Cover-led case studies, process, tools, experience.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "designer.svg",   "sort": 3},
    {"id": "consultant-base", "name": "Consultant Base", "role": "consultant", "description": "Engagements with outcomes, niche, industries.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "consultant.svg", "sort": 4},
    {"id": "founder-base",    "name": "Founder Base",    "role": "founder",    "description": "Companies, traction, team, vision, hiring CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "founder.svg",    "sort": 5},
    {"id": "student-base",    "name": "Student Base",    "role": "student",    "description": "Education, internships, side projects, first-role CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "student.svg",    "sort": 6},
    {"id": "shop-base",       "name": "Shop Base",       "role": "shop",       "description": "Made-to-order gallery, walk-in hours, location.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "shop.svg",       "sort": 7},
    {"id": "artist-base",     "name": "Artist Base",     "role": "artist",     "description": "Curated work, exhibitions, galleries, commission CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "artist.svg",     "sort": 8},
    {"id": "writer-base",     "name": "Writer Base",     "role": "writer",     "description": "Best clips with publication logos, topics covered.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "writer.svg",     "sort": 9},
    {"id": "researcher-base", "name": "Researcher Base", "role": "researcher", "description": "Publications, affiliations, current focus, collab CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "researcher.svg", "sort": 10},
    {"id": "employee-base",   "name": "Employee Base",   "role": "employee",   "description": "Internal mobility, side projects, skills matrix.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "employee.svg",   "sort": 11},
    {"id": "business-base",   "name": "Business Base",   "role": "business",   "description": "Company tagline, services, team, metrics, quote CTA.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "business.svg",   "sort": 12},
    {"id": "other-base",      "name": "Other Base",      "role": "other",      "description": "Generic-but-distinctive storytelling folio.", "is_visible": True, "is_default": False, "is_pro_only": False, "is_selectable": True, "thumb": "other.svg",      "sort": 13},
]


def _conn():
    import psycopg
    from psycopg.rows import dict_row
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg.connect(dsn, row_factory=dict_row)
    return conn


def _normalize(t: dict) -> dict:
    return {
        "id": str(t.get("id") or ""),
        "name": str(t.get("name") or t.get("id") or ""),
        "role": str(t.get("role") or ""),
        "description": str(t.get("description") or ""),
        "is_visible": bool(t.get("is_visible", False)),
        "is_default": bool(t.get("is_default", False)),
        "is_pro_only": bool(t.get("is_pro_only", False)),
        "is_selectable": bool(t.get("is_selectable", False)),
        "thumb": str(t.get("thumb") or ""),
        "sort": int(t.get("sort") or 0),
    }


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
            out.append(_normalize(t))
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
        payload.append(_normalize(t))
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


def catalog_for_role(role: str) -> list[dict]:
    r = (role or "other").strip().lower()
    if r not in VALID_ROLES:
        r = "other"
    return [t for t in visible_catalog() if t.get("role") == r]


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
    if not t.get("is_selectable", False):
        return False
    user_role = (user.get("category") or "other").strip().lower()
    if user_role not in VALID_ROLES:
        user_role = "other"
    return t.get("role") == user_role


def safe_default(user: dict) -> str:
    role = (user.get("category") or "other").strip().lower()
    if role not in VALID_ROLES:
        role = "other"
    return ROLE_DEFAULT_TEMPLATE[role]