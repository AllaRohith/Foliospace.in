import csv
import io
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from psycopg.rows import dict_row
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services import admin_auth

router = APIRouter(prefix="/admin", tags=["admin"])

limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _issue_label() -> str:
    d = datetime.now(timezone.utc)
    return f"№ {d.strftime('%y')}·{d.strftime('%m')}·{d.strftime('%d')}"


templates.env.globals["issue"] = _issue_label()
templates.env.globals["now"] = lambda: datetime.now(timezone.utc)

ROLE_VALUES = ["student", "developer", "designer", "chef", "artist", "consultant", "writer", "researcher", "founder", "other"]
PAGE_SIZE = 50

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=3000",
    )


def _sanitize(value: str) -> str:
    if not value:
        return ""
    return CONTROL_RE.sub("", value)


def _no_cache(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _gate(request: Request) -> str | RedirectResponse:
    sid = admin_auth.require_admin(request)
    if not sid:
        return RedirectResponse("/admin/login", status_code=303)
    return sid


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    err = request.query_params.get("err", "")
    response = templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Admin · FolioSpace",
            "description": "FolioSpace admin login.",
            "error": err,
            "locked": request.query_params.get("locked") == "1",
        },
    )
    return _no_cache(response)


@router.post("/login")
@limiter.limit("5/minute")
async def login_submit(
    request: Request,
    password: str = Form(""),
):
    ip = request.client.host if request.client else "?"
    sanitized_pw = _sanitize(password)[:256]
    if admin_auth.is_locked_out(ip):
        admin_auth.audit(request, None, "login.locked", target=ip)
        return RedirectResponse("/admin/login?locked=1", status_code=303)
    ok = False
    try:
        ok = admin_auth.verify_password(sanitized_pw)
    finally:
        admin_auth.record_login_attempt(ip, ok)
    if not ok:
        admin_auth.audit(request, None, "login.fail", target=ip)
        return RedirectResponse("/admin/login?err=1", status_code=303)
    try:
        sid = admin_auth.create_session(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create_session failed: %s", e)
        raise HTTPException(status_code=503, detail="Login temporarily unavailable.")
    admin_auth.audit(request, sid, "login.ok", target=ip)
    return RedirectResponse("/admin/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    sid = admin_auth.get_session_id(request)
    if sid:
        admin_auth.audit(request, sid, "logout", target=sid)
    admin_auth.destroy_session(request)
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    total = 0
    last7 = 0
    per_day = []
    role_breakdown = []
    recent = []
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) AS n FROM waitlist")
                    total = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        """
                        SELECT count(*) AS n
                          FROM waitlist
                         WHERE created_at > NOW() - INTERVAL '7 days'
                        """
                    )
                    last7 = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        """
                        SELECT date_trunc('day', created_at) AS d, count(*) AS n
                          FROM waitlist
                         WHERE created_at > NOW() - INTERVAL '14 days'
                         GROUP BY 1
                         ORDER BY 1
                        """
                    )
                    per_day = [(row["d"], int(row["n"])) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT COALESCE(role, '(unspecified)') AS role, count(*) AS n
                          FROM waitlist
                         GROUP BY 1
                         ORDER BY 2 DESC
                        """
                    )
                    role_breakdown = [(row["role"], int(row["n"])) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT id, email, role, created_at
                          FROM waitlist
                         ORDER BY created_at DESC
                         LIMIT 8
                        """
                    )
                    recent = list(cur.fetchall())
                conn.commit()
        except psycopg.Error as e:
            logger.exception("dashboard query failed: %s", e)

    admin_auth.audit(request, sid, "dashboard.view")
    response = templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Dashboard · FolioSpace Admin",
            "description": "FolioSpace admin dashboard.",
            "total": total,
            "last7": last7,
            "per_day": per_day,
            "role_breakdown": role_breakdown,
            "recent": recent,
            "role_values": ROLE_VALUES,
        },
    )
    return _no_cache(response)


@router.get("/signups", response_class=HTMLResponse)
async def signups_list(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    role = _sanitize(request.query_params.get("role", ""))[:32]
    q = _sanitize(request.query_params.get("q", ""))[:128]
    date_from = _sanitize(request.query_params.get("from", ""))[:10]
    date_to = _sanitize(request.query_params.get("to", ""))[:10]
    page_raw = _sanitize(request.query_params.get("page", "1"))[:6]
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1
    offset = (page - 1) * PAGE_SIZE

    where = []
    params = []
    if role and role in ROLE_VALUES:
        where.append("role = %s")
        params.append(role)
    if q:
        where.append("lower(email) LIKE %s")
        params.append(f"%{q.lower()}%")
    if date_from:
        where.append("created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("created_at < (%s)::date + INTERVAL '1 day'")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    rows = []
    total = 0
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT count(*) AS n FROM waitlist{where_sql}",
                        params,
                    )
                    total = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        f"""
                        SELECT id, email, role, created_at
                          FROM waitlist{where_sql}
                         ORDER BY created_at DESC
                         LIMIT %s OFFSET %s
                        """,
                        [*params, PAGE_SIZE, offset],
                    )
                    rows = list(cur.fetchall())
                conn.commit()
        except psycopg.Error as e:
            logger.exception("signups query failed: %s", e)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    admin_auth.audit(
        request,
        sid,
        "signups.list",
        metadata={"role": role, "q": q, "page": page, "total": total},
    )
    response = templates.TemplateResponse(
        request,
        "admin/signups.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Signups · FolioSpace Admin",
            "description": "FolioSpace admin signups list.",
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "page_size": PAGE_SIZE,
            "role_values": ROLE_VALUES,
            "role": role,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "msg": request.query_params.get("msg", ""),
        },
    )
    return _no_cache(response)


@router.get("/signups/export.csv")
@limiter.limit("10/minute")
async def signup_export(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    role = _sanitize(request.query_params.get("role", ""))[:32]
    q = _sanitize(request.query_params.get("q", ""))[:128]
    date_from = _sanitize(request.query_params.get("from", ""))[:10]
    date_to = _sanitize(request.query_params.get("to", ""))[:10]

    where = []
    params = []
    if role and role in ROLE_VALUES:
        where.append("role = %s")
        params.append(role)
    if q:
        where.append("lower(email) LIKE %s")
        params.append(f"%{q.lower()}%")
    if date_from:
        where.append("created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("created_at < (%s)::date + INTERVAL '1 day'")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    rows = []
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT id, email, role, created_at, ip FROM waitlist{where_sql} ORDER BY created_at DESC",
                        params,
                    )
                    rows = list(cur.fetchall())
                conn.commit()
        except psycopg.Error as e:
            logger.exception("export query failed: %s", e)
            rows = []

    admin_auth.audit(
        request,
        sid,
        "signups.export",
        metadata={"role": role, "q": q, "count": len(rows)},
    )

    def stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "email", "role", "created_at", "ip"])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for row in rows:
            writer.writerow([
                row["id"],
                row["email"],
                row["role"] or "",
                row["created_at"].isoformat() if row.get("created_at") else "",
                row["ip"] or "",
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    headers = {
        "Content-Disposition": f'attachment; filename="foliospace-waitlist-{stamp}.csv"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(stream(), media_type="text/csv", headers=headers)


@router.get("/signups/{signup_id}", response_class=HTMLResponse)
async def signup_detail(signup_id: int, request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    row = None
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, email, role, created_at, ip FROM waitlist WHERE id = %s",
                        (signup_id,),
                    )
                    row = cur.fetchone()
                conn.commit()
        except psycopg.Error as e:
            logger.exception("signup_detail query failed: %s", e)

    if not row:
        raise HTTPException(status_code=404, detail="Not found.")

    admin_auth.audit(request, sid, "signups.detail", target=str(signup_id))
    response = templates.TemplateResponse(
        request,
        "admin/signup_detail.html",
        {
            "site_name": "FolioSpace",
            "page_title": f"Signup #{signup_id} · FolioSpace Admin",
            "description": "FolioSpace signup detail.",
            "row": row,
            "signup_id": signup_id,
        },
    )
    return _no_cache(response)


@router.post("/signups/{signup_id}/delete")
async def signup_delete(signup_id: int, request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    deleted = False
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM waitlist WHERE id = %s RETURNING email",
                        (signup_id,),
                    )
                    row = cur.fetchone()
                    deleted = row is not None
                conn.commit()
        except psycopg.Error as e:
            logger.exception("signup_delete failed: %s", e)

    admin_auth.audit(
        request,
        sid,
        "signups.delete",
        target=str(signup_id),
        metadata={"deleted": deleted},
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found.")
    return RedirectResponse("/admin/signups?msg=deleted", status_code=303)