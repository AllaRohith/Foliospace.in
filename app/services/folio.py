import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

MIN_SLUG_LEN = 2
MAX_SLUG_LEN = 48

_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"

W, H = 1200, 630
INK = (15, 20, 25)
CREAM = (250, 247, 242)
CREAM_2 = (242, 237, 227)
ACCENT = (255, 107, 53)
ACCENT_SOFT = (255, 107, 53, 30)
MUTED = (92, 100, 112)
HAIRLINE = (232, 227, 217)

BRAND_MARK_PATH = [
    (8, 8), (8, 48), (16, 48), (16, 33), (30, 33),
    (30, 26), (16, 26), (16, 15), (38, 15), (38, 8),
]
BRAND_MARK_ACC_X, BRAND_MARK_ACC_Y, BRAND_MARK_ACC_S = 32, 40, 10


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=3000",
    )


def _try_font(filename: str, size: int):
    from PIL import ImageFont
    path = _FONT_DIR / filename
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fonts():
    return {
        "stalinist": _try_font("stalinist-one.ttf", 64),
        "stalinist_avatar": _try_font("stalinist-one.ttf", 140),
        "saira_400": _try_font("saira-400.ttf", 28),
        "saira_500": _try_font("saira-500.ttf", 50),
        "saira_600": _try_font("saira-600.ttf", 78),
        "saira_700_15": _try_font("saira-700.ttf", 15),
        "saira_700_18": _try_font("saira-700.ttf", 18),
        "saira_700_22": _try_font("saira-700.ttf", 22),
        "saira_500_25": _try_font("saira-500.ttf", 25),
        "saira_italic": _try_font("saira-italic.ttf", 28),
    }


def _draw_background(draw):
    for y in range(0, H, 4):
        draw.line([(0, y), (W, y)], fill=HAIRLINE)
    draw.rectangle([0, 0, W, 96], fill=CREAM_2)
    draw.rectangle([0, H - 96, W, H], fill=CREAM_2)
    draw.line([(0, 96), (W, 96)], fill=HAIRLINE, width=1)
    draw.line([(0, H - 96), (W, H - 96)], fill=HAIRLINE, width=1)


def _draw_brand(draw, x, y, size=56):
    scale = size / 56
    poly = [(x + int(px * scale), y + int(py * scale)) for px, py in BRAND_MARK_PATH]
    draw.polygon(poly, fill=INK)
    ax = x + int(BRAND_MARK_ACC_X * scale)
    ay = y + int(BRAND_MARK_ACC_Y * scale)
    aw = max(1, int(BRAND_MARK_ACC_S * scale))
    draw.rectangle([ax, ay, ax + aw, ay + aw], fill=ACCENT)


def _measure(draw, text, fnt):
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox


def _wrap_text(draw, text, fnt, max_width, max_lines=3):
    words = text.split()
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        w, _, _ = _measure(draw, candidate, fnt)
        if w <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines:
        last = lines[-1]
        while last and _measure(draw, last + "…", fnt)[0] > max_width:
            last = last[:-1]
        if last:
            lines[-1] = last.rstrip(",.;:") + "…"
    return lines


def _strip_role(role: str) -> str:
    if not role:
        return ""
    parts = [p.strip() for p in role.replace("·", "·").split("·") if p.strip()]
    cleaned = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p = p[0].upper() + p[1:] if len(p) > 1 else p.upper()
        cleaned.append(p)
    return " · ".join(cleaned)[:80]


def _initial_letter(user: dict) -> str:
    name = (user.get("display_name") or "").strip()
    if name:
        for ch in name:
            if ch.isalpha():
                return ch.upper()
    slug = (user.get("slug") or "").strip()
    if slug:
        return slug[0].upper()
    return "·"


def _draw_avatar_circle(draw, fonts, user, cx, cy, diameter=240):
    radius = diameter // 2
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=CREAM,
        outline=ACCENT,
        width=4,
    )
    initial = _initial_letter(user)
    bbox = draw.textbbox((0, 0), initial, font=fonts["stalinist_avatar"])
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw / 2 - bbox[0]
    ty = cy - th / 2 - bbox[1]
    draw.text((tx, ty), initial, fill=INK, font=fonts["stalinist_avatar"])


def _draw_avatar_image(draw, img, user, cx, cy, diameter=240):
    radius = diameter // 2
    avatar_url = (user.get("avatar_url") or "").strip()
    if not avatar_url:
        return False
    try:
        import urllib.request
        from urllib.error import URLError
        from socket import timeout as _socket_timeout
        req = urllib.request.Request(
            avatar_url,
            headers={"User-Agent": "FolioSpace/1.0 OG-Generator"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            avatar_data = resp.read()
        from PIL import Image
        avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
        avatar = avatar.resize((diameter, diameter))
        mask = Image.new("L", (diameter, diameter), 0)
        from PIL import ImageDraw as _ID
        _ID.Draw(mask).ellipse([0, 0, diameter, diameter], fill=255)
        avatar.putalpha(mask)
        box = (cx - radius, cy - radius)
        img_rgba = img.convert("RGBA")
        img_rgba.paste(avatar, box, avatar)
        img.paste(img_rgba.convert("RGB"))
        return True
    except (URLError, _socket_timeout, TimeoutError, OSError, ValueError) as e:
        logger.info("avatar fetch/skip: %s", e)
        return False


def find_user_by_slug(slug: str, *, require_public: bool = True) -> dict | None:
    from app.utils.text import strip_control
    s = strip_control((slug or "").strip())[:MAX_SLUG_LEN]
    if not s or len(s) < MIN_SLUG_LEN:
        return None
    if not DATABASE_URL:
        return None
    full_sql = (
        """
        SELECT id, slug, display_name, role, category, bio, phone, avatar_url,
               avatar_public_id, avatar_video_url, avatar_video_public_id, avatar_video_kind,
               is_public,
               plan, is_internal, is_trial, payment_failed_at,
               setup_paid_at, plan_expires_at,
               template_id,
               created_at, updated_at, deleted_at, linkedin_url,
               spotlight_kind, spotlight_ref_id, spotlight_text, spotlight_url, spotlight_emoji,
               seo_title, seo_description, og_image_override_url,
               work_rail
          FROM users
         WHERE slug = %s
            OR lower(slug) = lower(%s)
            OR lower(trim(slug)) = lower(trim(%s))
         LIMIT 1
        """
    )
    minimal_sql = (
        """
        SELECT id, slug, display_name, role, category, created_at, updated_at, deleted_at,
               NULL::text AS bio, NULL::text AS phone, NULL::text AS avatar_url,
               NULL::text AS avatar_public_id, NULL::text AS avatar_video_url,
               NULL::text AS avatar_video_public_id, NULL::text AS avatar_video_kind,
               FALSE AS is_public,
               'free'::text AS plan, FALSE AS is_internal, FALSE AS is_trial,
               NULL::timestamp AS payment_failed_at,
               NULL::timestamp AS setup_paid_at,
               NULL::timestamp AS plan_expires_at,
               'other-base'::text AS template_id,
               NULL::text AS linkedin_url,
               NULL::text AS spotlight_kind, NULL::text AS spotlight_ref_id,
               NULL::text AS spotlight_text, NULL::text AS spotlight_url,
               NULL::text AS spotlight_emoji,
               NULL::text AS seo_title, NULL::text AS seo_description,
               NULL::text AS og_image_override_url,
               '[]'::jsonb AS work_rail
          FROM users
         WHERE slug = %s
            OR lower(slug) = lower(%s)
            OR lower(trim(slug)) = lower(trim(%s))
         LIMIT 1
        """
    )
    params = (s, s, s)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(full_sql, params)
                row = cur.fetchone()
            conn.commit()
        if require_public and row is not None and not row.get("is_public"):
            return None
        return row
    except psycopg.errors.UndefinedColumn as e:
        logger.warning("find_user_by_slug: optional columns missing, falling back: %s", e)
    except psycopg.Error as e:
        logger.exception("find_user_by_slug failed (full query): %s", e)
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(minimal_sql, params)
                row = cur.fetchone()
            conn.commit()
        if require_public and row is not None and not row.get("is_public"):
            return None
        return row
    except psycopg.Error as e:
        logger.exception("find_user_by_slug failed (minimal fallback): %s", e)
        return None


def list_public_slugs() -> list[tuple[str, str]]:
    if not DATABASE_URL:
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT slug, updated_at
                      FROM users
                     WHERE deleted_at IS NULL
                       AND is_public = TRUE
                       AND display_name IS NOT NULL
                       AND length(trim(display_name)) > 0
                       AND slug IS NOT NULL
                       AND length(trim(slug)) >= %s
                     ORDER BY created_at DESC
                     LIMIT 5000
                    """,
                    (MIN_SLUG_LEN,),
                )
                rows = cur.fetchall()
            conn.commit()
        return [
            (r["slug"], r["updated_at"].date().isoformat() if r.get("updated_at") else "")
            for r in rows
        ]
    except psycopg.errors.UndefinedColumn:
        logger.warning(
            "list_public_slugs: is_public column missing; returning empty "
            "(privacy-first until migration users_private.sql is applied)"
        )
        return []
    except psycopg.Error as e:
        logger.exception("list_public_slugs failed: %s", e)
        return []


def _fit_text_to_width(draw, text, font, max_width):
    if _measure(draw, text, font)[0] <= max_width:
        return text
    ell = "…"
    while text and _measure(draw, text + ell, font)[0] > max_width:
        text = text[:-1].rstrip()
    return (text + ell) if text else ell


def _shrink_name_to_width(draw, text, fonts, max_width):
    for key in ("saira_600", "saira_500"):
        if _measure(draw, text, fonts[key])[0] <= max_width:
            return text, fonts[key]
    return _fit_text_to_width(draw, text, fonts["saira_500"], max_width), fonts["saira_500"]


def render_og_image(user: dict) -> bytes | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed; OG image generation skipped")
        return None

    fonts = _fonts()
    img = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(img)
    _draw_background(draw)

    _draw_brand(draw, 80, 20, size=56)
    word_x = 80 + 56 + 18
    word_y = 28
    draw.text((word_x, word_y), "FolioSpace", fill=INK, font=fonts["stalinist"])
    brand_bbox = draw.textbbox((0, 0), "FolioSpace", font=fonts["stalinist"])
    brand_w = brand_bbox[2] - brand_bbox[0]
    brand_h = brand_bbox[3] - brand_bbox[1]
    acc_size = 12
    acc_x = word_x + brand_w + 4
    acc_y = word_y + brand_h - acc_size - 2
    draw.rectangle([acc_x, acc_y, acc_x + acc_size, acc_y + acc_size], fill=ACCENT)

    name = (user.get("display_name") or "").strip()[:120].rstrip()
    if not name:
        name = "Untitled folio"

    role = _strip_role(user.get("role") or "")
    bio = (user.get("bio") or "").strip()

    right_center_x = W - 80 - 120
    right_center_y = 230

    left_x = 80
    right_edge_for_text = right_center_x - 180
    max_text_width = right_edge_for_text - left_x

    if role:
        eyebrow = f"→ {role.upper()}"
        eyebrow = _fit_text_to_width(draw, eyebrow, fonts["saira_700_15"], max_text_width)
        draw.text((left_x, 158), eyebrow, fill=ACCENT, font=fonts["saira_700_15"])

    name, name_font = _shrink_name_to_width(draw, name, fonts, max_text_width)
    draw.text((left_x, 200), name, fill=INK, font=name_font)

    if bio:
        bio_lines = _wrap_text(draw, bio, fonts["saira_400"], max_text_width, max_lines=3)
        y = 290
        for line in bio_lines:
            draw.text((left_x, y), line, fill=INK, font=fonts["saira_400"])
            y += 36

    used_image = _draw_avatar_image(draw, img, user, right_center_x, right_center_y, diameter=240)
    if not used_image:
        _draw_avatar_circle(draw, fonts, user, right_center_x, right_center_y, diameter=240)

    draw.line([(80, H - 96), (W - 80, H - 96)], fill=HAIRLINE, width=1)
    footer_url = f"foliospace.in/{user.get('slug', '')}"
    draw.text((80, H - 60), "→ ", fill=ACCENT, font=fonts["saira_700_22"])
    arrow_w, _, _ = _measure(draw, "→ ", fonts["saira_700_22"])
    draw.text((80 + arrow_w, H - 60), footer_url, fill=INK, font=fonts["saira_700_22"])

    note = "FolioSpace · a portfolio for every Indian professional"
    draw.text((W - 80 - _measure(draw, note, fonts["saira_700_15"])[0], H - 56), note, fill=MUTED, font=fonts["saira_700_15"])

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_qr_png(url: str) -> bytes | None:
    try:
        import qrcode
        from qrcode.image.pil import PilImage
    except ImportError:
        logger.warning("qrcode[pil] not installed; QR PNG skipped")
        return None
    if not url:
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(
            fill_color=(15, 20, 25),
            back_color=(250, 247, 242),
            image_factory=PilImage,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.exception("render_qr_png failed: %s", e)
        return None
