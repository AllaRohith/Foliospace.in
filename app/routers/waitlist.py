import os
import re
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse
import psycopg
from psycopg.rows import dict_row
from app.services import email_service
from app.utils.text import strip_control, strip_control as _sanitize
from app.rate_limit import limiter

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

MAX_EMAIL_LEN = 254
MAX_ROLE_LEN = 32
MAX_WEBSITE_LEN = 256
MAX_UTM_LEN = 64
MAX_REFERER_LEN = 256
MAX_BODY_BYTES = 8 * 1024

UTM_RE = re.compile(r"[^a-z0-9_./\-+]")

ROLE_VALUES = {
    "",
    "student",
    "developer",
    "designer",
    "chef",
    "artist",
    "consultant",
    "writer",
    "researcher",
    "founder",
    "employee",
    "shop",
    "business",
    "other",
}

ALLOWED_CONTENT_TYPES = {
    "application/x-www-form-urlencoded",
    "multipart/form-data",
}

if not DATABASE_URL:
    logger.warning(
        "DATABASE_URL is not set. The waitlist endpoints will return 503 until it is configured. "
        "Set DATABASE_URL to your Postgres connection string (e.g. Neon)."
    )


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Waitlist database is not configured.")
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn


def _count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM waitlist")
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def _purge_old_ips(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waitlist
               SET ip = NULL
             WHERE ip IS NOT NULL
               AND created_at < NOW() - INTERVAL '30 days'
            """
        )
        return cur.rowcount


_PURGE_LAST_RUN: dict[str, float] = {}
_PURGE_INTERVAL_SECONDS = 24 * 60 * 60


def _maybe_purge_old_ips(conn) -> None:
    now = datetime.now(timezone.utc).timestamp()
    last = _PURGE_LAST_RUN.get("ip")
    if last is not None and (now - last) < _PURGE_INTERVAL_SECONDS:
        return
    try:
        _purge_old_ips(conn)
        _PURGE_LAST_RUN["ip"] = now
    except psycopg.Error as e:
        logger.warning("deferred _purge_old_ips skipped: %s", e)


def _sanitize(value: str) -> str:
    return strip_control(value)


def _clean_utm(value: str) -> str:
    cleaned = _sanitize(value).strip().lower()
    if not cleaned:
        return ""
    cleaned = UTM_RE.sub("", cleaned)
    return cleaned[:MAX_UTM_LEN]


def _clean_referer(value: str) -> str:
    cleaned = _sanitize(value).strip()
    return cleaned[:MAX_REFERER_LEN]


def _check_content_type(request: Request) -> None:
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported Content-Type.")


def _check_body_size(request: Request) -> None:
    cl = request.headers.get("content-length")
    if cl is None:
        return
    try:
        if int(cl) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length.")


@router.post("/join")
@limiter.limit("5/minute")
async def join_waitlist(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    role: str = Form(""),
    website: str = Form(""),
    utm_source: str = Form(""),
    utm_medium: str = Form(""),
    utm_campaign: str = Form(""),
):
    _check_content_type(request)
    _check_body_size(request)

    email = _sanitize(email).strip().lower()
    role_clean_raw = _sanitize(role).strip().lower()
    website = _sanitize(website).strip()
    utm_source = _clean_utm(utm_source)
    utm_medium = _clean_utm(utm_medium)
    utm_campaign = _clean_utm(utm_campaign)
    referer = _clean_referer(request.headers.get("referer", ""))

    if website:
        logger.info("honeypot triggered from %s", request.client.host if request.client else "?")
        return JSONResponse(status_code=200, content={"ok": True, "message": "OK."})

    if (
        len(email) > MAX_EMAIL_LEN
        or len(role_clean_raw) > MAX_ROLE_LEN
        or len(website) > MAX_WEBSITE_LEN
        or len(utm_source) > MAX_UTM_LEN
        or len(utm_medium) > MAX_UTM_LEN
        or len(utm_campaign) > MAX_UTM_LEN
        or len(referer) > MAX_REFERER_LEN
    ):
        raise HTTPException(status_code=400, detail="Invalid input length.")

    if role_clean_raw not in ROLE_VALUES:
        raise HTTPException(status_code=400, detail="Invalid role.")

    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email.")

    role_clean = role_clean_raw or None
    ip = request.client.host if request.client else None

    is_new = False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO waitlist (
                        email, role, created_at, ip,
                        utm_source, utm_medium, utm_campaign, referer
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                    """,
                    (
                        email,
                        role_clean,
                        datetime.now(timezone.utc),
                        ip,
                        utm_source or None,
                        utm_medium or None,
                        utm_campaign or None,
                        referer or None,
                    ),
                )
                row = cur.fetchone()
                is_new = row is not None
            total = _count(conn)
            _maybe_purge_old_ips(conn)
            conn.commit()
    except psycopg.Error as e:
        logger.exception("database error during waitlist insert: %s", e)
        raise HTTPException(status_code=503, detail="Waitlist temporarily unavailable.")

    if is_new:
        def _log_welcome(email: str) -> None:
            ok, info = email_service.send_welcome_email(email)
            if not ok:
                logger.warning("welcome email failed for %s: %s", email, info)

        def _log_internal(
            email: str,
            role_clean: str | None,
            utm_source: str | None,
            utm_medium: str | None,
            utm_campaign: str | None,
            referer: str | None,
        ) -> None:
            ok, info = email_service.send_internal_notification(
                email, role_clean, utm_source, utm_medium, utm_campaign, referer,
            )
            if not ok:
                logger.warning("internal notification failed for %s: %s", email, info)

        background.add_task(_log_welcome, email)
        background.add_task(
            _log_internal,
            email,
            role_clean,
            utm_source or None,
            utm_medium or None,
            utm_campaign or None,
            referer or None,
        )

    return JSONResponse(
        status_code=201 if is_new else 200,
        content={
            "ok": True,
            "new": is_new,
            "count": total,
            "message": "You're in. We'll email you when we launch." if is_new else "You're already on the list.",
        },
    )


@router.get("/count")
@limiter.limit("60/minute")
async def count(request: Request):
    if not DATABASE_URL:
        return {"count": 0, "configured": False}
    try:
        with _connect() as conn:
            total = _count(conn)
            _maybe_purge_old_ips(conn)
            conn.commit()
    except psycopg.Error as e:
        logger.exception("database error during count: %s", e)
        return {"count": 0, "configured": True, "degraded": True}
    return {"count": total, "configured": True}
