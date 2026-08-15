import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import psycopg
from psycopg.rows import dict_row

from app.rate_limit import limiter

router = APIRouter(prefix="/api", tags=["stats"])

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

logger = logging.getLogger(__name__)


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Waitlist database is not configured.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _anonymize_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if not local:
        return ""
    return f"{local[0]}***@{domain}"


@router.get("/stats")
@limiter.limit("30/minute")
async def stats(request: Request):
    if not DATABASE_URL:
        return {
            "total": 0,
            "last_7d": 0,
            "last_24h": 0,
            "latest_email_partial": "",
            "latest_ago_seconds": 0,
            "configured": False,
        }
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS n FROM waitlist")
                total = int((cur.fetchone() or {}).get("n", 0))

                cur.execute(
                    """
                    SELECT count(*) AS n FROM waitlist
                     WHERE created_at >= NOW() - INTERVAL '7 days'
                    """
                )
                last_7d = int((cur.fetchone() or {}).get("n", 0))

                cur.execute(
                    """
                    SELECT count(*) AS n FROM waitlist
                     WHERE created_at >= NOW() - INTERVAL '24 hours'
                    """
                )
                last_24h = int((cur.fetchone() or {}).get("n", 0))

                cur.execute(
                    """
                    SELECT email, created_at FROM waitlist
                     ORDER BY created_at DESC
                     LIMIT 1
                    """
                )
                latest = cur.fetchone()
            conn.commit()
    except psycopg.Error as e:
        logger.exception("database error during stats: %s", e)
        return JSONResponse(
            status_code=200,
            content={
                "total": 0,
                "last_7d": 0,
                "last_24h": 0,
                "latest_email_partial": "",
                "latest_ago_seconds": 0,
                "degraded": True,
            },
        )

    latest_email = ""
    latest_ago = 0
    if latest:
        latest_email = _anonymize_email(latest.get("email", ""))
        created = latest.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            latest_ago = max(0, int((datetime.now(timezone.utc) - created).total_seconds()))

    return {
        "total": total,
        "last_7d": last_7d,
        "last_24h": last_24h,
        "latest_email_partial": latest_email,
        "latest_ago_seconds": latest_ago,
        "configured": True,
    }
