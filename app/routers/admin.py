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

from app.services import admin_auth
from app.services import templates as templates_svc
from app.routers.waitlist import EMAIL_RE
from app.utils.text import strip_control, strip_control as _sanitize
from app.rate_limit import limiter

router = APIRouter(prefix="/admin", tags=["admin"])

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
from app.utils.template_globals import install_template_globals
install_template_globals(templates)


def _issue_label() -> str:
    d = datetime.now(timezone.utc)
    return f"№ {d.strftime('%y')}·{d.strftime('%m')}·{d.strftime('%d')}"


def _cold_open(last7: int, prev7: int, delta_pct: float, top_role: str, top_role_count: int, total: int) -> str:
    if last7 == 0:
        if total == 0:
            return "Desk is quiet. No signups yet — the waitlist is open."
        return f"{total} on the roster. None signed up this week."
    parts = []
    if prev7 == 0 and last7 > 0:
        parts.append(f"{last7} signups this week — an open door.")
    else:
        sign = "+" if delta_pct >= 0 else ""
        parts.append(f"{last7} signups this week, {sign}{delta_pct}% vs. last week.")
    if top_role and top_role != "—":
        parts.append(f"{top_role.capitalize()} leads at {top_role_count}.")
    return " ".join(parts)


templates.env.globals["issue"] = lambda: _issue_label()
templates.env.globals["now"] = lambda: datetime.now(timezone.utc)

ROLE_VALUES = [
    "student", "developer", "designer", "chef", "artist",
    "consultant", "writer", "researcher", "founder",
    "employee", "shop", "business", "other",
]
PAGE_SIZE = 50


def _connect():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options="-c statement_timeout=3000",
    )


def _sanitize(value: str) -> str:
    return strip_control(value) if value else ""


def _anonymize_ip(ip: str | None) -> str:
    if not ip:
        return ""
    if ":" in ip:
        parts = ip.split(":")
        if len(parts) >= 3:
            return ":".join(parts[:2]) + ":…"
        return "::…"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0"
    return ip[: ip.rfind(".") + 1] + "0" if "." in ip else "0.0.0.0"


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
    prev7 = 0
    per_day = []
    per_day_30 = []
    role_breakdown = []
    top_sources = []
    recent = []
    top_role_7d = []
    recent_audit = []
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
                        SELECT count(*) AS n
                          FROM waitlist
                         WHERE created_at > NOW() - INTERVAL '14 days'
                           AND created_at <= NOW() - INTERVAL '7 days'
                        """
                    )
                    prev7 = int((cur.fetchone() or {}).get("n") or 0)
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
                        SELECT date_trunc('day', created_at) AS d, count(*) AS n
                          FROM waitlist
                         WHERE created_at > NOW() - INTERVAL '30 days'
                         GROUP BY 1
                         ORDER BY 1
                        """
                    )
                    per_day_30 = [(row["d"], int(row["n"])) for row in cur.fetchall()]
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
                        SELECT COALESCE(NULLIF(utm_source, ''), '(direct)') AS src,
                               count(*) AS n
                          FROM waitlist
                         GROUP BY 1
                         ORDER BY 2 DESC
                         LIMIT 5
                        """
                    )
                    top_sources = [(row["src"], int(row["n"])) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT id, email, role, created_at,
                               utm_source, utm_medium, utm_campaign
                          FROM waitlist
                         ORDER BY created_at DESC
                         LIMIT 8
                        """
                    )
                    recent = list(cur.fetchall())
                    if role_breakdown:
                        cur.execute(
                            """
                            SELECT date_trunc('day', created_at) AS d, count(*) AS n
                              FROM waitlist
                             WHERE COALESCE(role, '(unspecified)') = %s
                               AND created_at > NOW() - INTERVAL '7 days'
                             GROUP BY 1
                             ORDER BY 1
                            """,
                            (role_breakdown[0][0],),
                        )
                        top_role_7d = [(row["d"], int(row["n"])) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT id, action, ip, target, created_at, metadata
                          FROM admin_audit_log
                         ORDER BY created_at DESC
                         LIMIT 6
                        """
                    )
                    recent_audit = list(cur.fetchall())
                conn.commit()
        except psycopg.Error as e:
            logger.exception("dashboard query failed: %s", e)

    if prev7 > 0:
        delta_pct = round(((last7 - prev7) / prev7) * 100, 1)
    elif last7 > 0:
        delta_pct = 100.0
    else:
        delta_pct = 0.0

    if role_breakdown:
        top_role_name = role_breakdown[0][0]
        top_role_count = role_breakdown[0][1]
    else:
        top_role_name = "—"
        top_role_count = 0

    cold_open = _cold_open(last7, prev7, delta_pct, top_role_name, top_role_count, total)

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
            "prev7": prev7,
            "delta_pct": delta_pct,
            "per_day": per_day,
            "per_day_30": per_day_30,
            "role_breakdown": role_breakdown,
            "top_sources": top_sources,
            "recent": recent,
            "top_role": top_role_name,
            "top_role_count": top_role_count,
            "top_role_7d": top_role_7d,
            "recent_audit": recent_audit,
            "cold_open": cold_open,
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
                        SELECT id, email, role, created_at,
                               utm_source, utm_medium, utm_campaign, referer
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
                        f"SELECT id, email, role, created_at, ip, utm_source, utm_medium, utm_campaign, referer FROM waitlist{where_sql} ORDER BY created_at DESC",
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
        writer.writerow([
            "id", "email", "role", "created_at",
            "ip_subnet", "utm_source", "utm_medium", "utm_campaign", "referer",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for row in rows:
            writer.writerow([
                row["id"],
                row["email"],
                row["role"] or "",
                row["created_at"].isoformat() if row.get("created_at") else "",
                _anonymize_ip(row.get("ip")),
                row.get("utm_source") or "",
                row.get("utm_medium") or "",
                row.get("utm_campaign") or "",
                row.get("referer") or "",
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
    audit_rows = []
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, email, role, created_at, ip, utm_source, utm_medium, utm_campaign, referer FROM waitlist WHERE id = %s",
                        (signup_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        cur.execute(
                            """
                            SELECT id, session_id, ip, action, target, metadata, created_at
                              FROM admin_audit_log
                             WHERE target = %s
                             ORDER BY created_at DESC
                             LIMIT 10
                            """,
                            (str(signup_id),),
                        )
                        audit_rows = cur.fetchall()
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
            "audit_rows": audit_rows,
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


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard

    action = _sanitize(request.query_params.get("action", ""))[:64]
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
    if action:
        where.append("action = %s")
        params.append(action)
    if date_from:
        where.append("created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("created_at < (%s)::date + INTERVAL '1 day'")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    rows = []
    total = 0
    distinct_actions = []
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT count(*) AS n FROM admin_audit_log{where_sql}", params)
                    total = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        f"""
                        SELECT id, session_id, ip, action, target, metadata, created_at
                          FROM admin_audit_log{where_sql}
                         ORDER BY created_at DESC
                         LIMIT %s OFFSET %s
                        """,
                        [*params, PAGE_SIZE, offset],
                    )
                    rows = list(cur.fetchall())
                    cur.execute(
                        "SELECT DISTINCT action FROM admin_audit_log ORDER BY action"
                    )
                    distinct_actions = [r["action"] for r in cur.fetchall()]
                conn.commit()
        except psycopg.Error as e:
            logger.exception("audit query failed: %s", e)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    admin_auth.audit(
        request,
        sid,
        "audit.view",
        metadata={"action": action, "from": date_from, "to": date_to, "page": page, "total": total},
    )
    response = templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Audit · FolioSpace Admin",
            "description": "FolioSpace admin audit log.",
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "page_size": PAGE_SIZE,
            "action": action,
            "actions": distinct_actions,
            "date_from": date_from,
            "date_to": date_to,
        },
    )
    return _no_cache(response)

@router.get("/templates", response_class=HTMLResponse)
async def templates_list(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard
    items = templates_svc.list_catalog()
    flash = _sanitize(request.query_params.get("msg", ""))[:80]
    err = _sanitize(request.query_params.get("err", ""))[:80]
    visible_count = sum(1 for t in items if t["is_visible"])
    return templates.TemplateResponse(
        request,
        "admin/templates.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Templates · FolioSpace Admin",
            "description": "Manage the public folio template catalog. Toggle visibility per template.",
            "nav_active": "templates",
            "items": items,
            "visible_count": visible_count,
            "flash": flash,
            "err": err,
        },
    )


@router.post("/templates/{template_id}/toggle")
async def templates_toggle(template_id: str, request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard
    tid = _sanitize(template_id)[:32]
    if not tid:
        return RedirectResponse("/admin/templates?err=missing-id", status_code=303)
    current = templates_svc.get(tid)
    if not current:
        return RedirectResponse("/admin/templates?err=not-found", status_code=303)
    new_state = not current["is_visible"]
    if tid == "t1" and not new_state:
        return RedirectResponse("/admin/templates?err=default-locked", status_code=303)
    ok = templates_svc.set_visibility(tid, new_state, updated_by=sid or "")
    if not ok:
        return RedirectResponse("/admin/templates?err=save-failed", status_code=303)
    admin_auth.audit(
        request,
        sid,
        "admin.template.toggle",
        target=tid,
        metadata={"is_visible": new_state, "name": current["name"]},
    )
    return RedirectResponse(f"/admin/templates?msg={tid}", status_code=303)


@router.get("/fonts", response_class=HTMLResponse)
async def fonts_list(request: Request):
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard
    items: list[dict] = []
    user_lookup: dict[str, dict] = {}
    if DATABASE_URL:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, user_id, font_name, file_url, file_public_id, status, created_at
                          FROM user_fonts
                         ORDER BY created_at DESC
                        """
                    )
                    items = list(cur.fetchall())
                    if items:
                        user_ids = list({str(r["user_id"]) for r in items})
                        cur.execute(
                            "SELECT id, display_name, slug FROM users WHERE id = ANY(%s::uuid[])",
                            (user_ids,),
                        )
                        for u in cur.fetchall() or []:
                            user_lookup[str(u["id"])] = u
                conn.commit()
        except psycopg.Error as e:
            logger.exception("fonts_list query failed: %s", e)
            items = []
    for it in items:
        u = user_lookup.get(str(it["user_id"]), {})
        it["display_name"] = u.get("display_name") or "(no name)"
        it["slug"] = u.get("slug") or ""
    pending = [f for f in items if f["status"] == "pending"]
    decided = [f for f in items if f["status"] != "pending"]
    admin_auth.audit(request, sid, "fonts.list", metadata={"pending": len(pending)})
    response = templates.TemplateResponse(
        request,
        "admin/fonts.html",
        {
            "site_name": "FolioSpace",
            "page_title": "Fonts · FolioSpace Admin",
            "description": "Approve or reject custom font uploads from Pro users.",
            "nav_active": "fonts",
            "pending": pending,
            "decided": decided,
            "msg": request.query_params.get("msg", ""),
            "err": request.query_params.get("err", ""),
        },
    )
    return _no_cache(response)


@router.post("/fonts/{font_id}/approve")
async def fonts_approve(font_id: str, request: Request):
    from app.services import user_fonts as user_fonts_svc
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard
    fid = _sanitize(font_id)[:48]
    if not fid:
        return RedirectResponse("/admin/fonts?err=missing-id", status_code=303)
    updated = user_fonts_svc.set_font_status(fid, "approved")
    if not updated:
        return RedirectResponse("/admin/fonts?err=not-found", status_code=303)
    admin_auth.audit(
        request,
        sid,
        "fonts.approve",
        target=fid,
        metadata={"user_id": updated.get("user_id"), "font_name": updated.get("font_name")},
    )
    return RedirectResponse("/admin/fonts?msg=approved", status_code=303)


@router.post("/fonts/{font_id}/reject")
async def fonts_reject(font_id: str, request: Request):
    from app.services import user_fonts as user_fonts_svc
    guard = _gate(request)
    if isinstance(guard, RedirectResponse):
        return guard
    sid = guard
    fid = _sanitize(font_id)[:48]
    if not fid:
        return RedirectResponse("/admin/fonts?err=missing-id", status_code=303)
    updated = user_fonts_svc.set_font_status(fid, "rejected")
    if not updated:
        return RedirectResponse("/admin/fonts?err=not-found", status_code=303)
    admin_auth.audit(
        request,
        sid,
        "fonts.reject",
        target=fid,
        metadata={"user_id": updated.get("user_id"), "font_name": updated.get("font_name")},
    )
    return RedirectResponse("/admin/fonts?msg=rejected", status_code=303)
