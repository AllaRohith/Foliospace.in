import os
import re
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse
import psycopg
from psycopg.rows import dict_row
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services import email_service

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

limiter = Limiter(key_func=get_remote_address)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

HONEYPOT_FIELD = "website"

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


@router.post("/join")
@limiter.limit("5/minute")
async def join_waitlist(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    role: str = Form(""),
    website: str = Form(""),
):
    if website:
        return JSONResponse(status_code=200, content={"ok": True, "message": "OK."})

    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email")

    role_clean = role.strip() or None
    ip = request.client.host if request.client else None

    is_new = False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO waitlist (email, role, created_at, ip)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
                """,
                (email, role_clean, datetime.now(timezone.utc), ip),
            )
            row = cur.fetchone()
            is_new = row is not None
        total = _count(conn)
        conn.commit()

    if is_new:
        background.add_task(email_service.send_welcome_email, email)
        background.add_task(email_service.send_internal_notification, email, role_clean)

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
async def count():
    if not DATABASE_URL:
        return {"count": 0, "configured": False}
    with _connect() as conn:
        total = _count(conn)
    return {"count": total, "configured": True}