import io
import logging
import os
from datetime import datetime, timezone

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

MIN_SLUG_LEN = 2
MAX_SLUG_LEN = 48


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=3000",
    )


def find_user_by_slug(slug: str, *, require_public: bool = True) -> dict | None:
    from app.utils.text import strip_control
    s = strip_control((slug or "").strip())[:MAX_SLUG_LEN]
    if not s or len(s) < MIN_SLUG_LEN:
        return None
    if not DATABASE_URL:
        return None
    full_sql = (
        """
        SELECT id, slug, display_name, role, bio, phone, avatar_url,
               is_public, created_at, updated_at, deleted_at
          FROM users
         WHERE slug = %s
            OR lower(slug) = lower(%s)
            OR lower(trim(slug)) = lower(trim(%s))
         LIMIT 1
        """
    )
    minimal_sql = (
        """
        SELECT id, slug, display_name, role, created_at, updated_at, deleted_at,
               NULL::text AS bio, NULL::text AS phone, NULL::text AS avatar_url,
               FALSE AS is_public
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


def render_og_image(user: dict) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed; OG image generation skipped")
        return None
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (250, 247, 242))
    draw = ImageDraw.Draw(img)
    accent = (255, 107, 53)
    ink = (15, 20, 25)
    muted = (92, 100, 112)
    hairline = (232, 227, 217)
    font_paths = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28, "name"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22, "role"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20, "bio"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24, "brand"),
    ]
    fonts = {}
    for path, size, key in font_paths:
        try:
            fonts[key] = ImageFont.truetype(path, size)
        except OSError:
            fonts[key] = ImageFont.load_default()
    PAD = 64
    draw.text((PAD, 64), "→ FOLIOSPACE.IN", fill=accent, font=fonts["brand"])
    draw.line([(PAD, 110), (PAD + 96, 110)], fill=accent, width=4)
    name = (user.get("display_name") or "Untitled folio").strip()[:48]
    draw.text((PAD, 168), name, fill=ink, font=fonts["name"])
    role = (user.get("role") or "").strip()[:60]
    if role:
        draw.text((PAD, 220), role.upper(), fill=muted, font=fonts["role"])
    bio = (user.get("bio") or "").strip()
    if bio:
        words = bio.split()
        line = ""
        lines: list[str] = []
        for word in words:
            test = (line + " " + word).strip()
            if draw.textlength(test, font=fonts["bio"]) > W - 2 * PAD:
                lines.append(line)
                line = word
            else:
                line = test
        if line:
            lines.append(line)
        lines = lines[:4]
        y = 290
        for ln in lines:
            draw.text((PAD, y), ln, fill=ink, font=fonts["bio"])
            y += 32
    draw.line([(PAD, H - 96), (W - PAD, H - 96)], fill=hairline, width=2)
    draw.text(
        (PAD, H - 72),
        f"foliospace.in/u/{user.get('slug', '')}",
        fill=accent,
        font=fonts["brand"],
    )
    avatar_url = (user.get("avatar_url") or "").strip()
    if avatar_url:
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
            avatar = Image.open(io.BytesIO(avatar_data)).convert("RGB")
            avatar = avatar.resize((200, 200))
            mask = Image.new("L", (200, 200), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 200, 200), fill=255)
            avatar.putalpha(mask)
            img.paste(avatar, (W - PAD - 200, 168), avatar)
        except (URLError, _socket_timeout, TimeoutError, OSError, ValueError) as e:
            logger.info("avatar fetch/skip: %s", e)
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
