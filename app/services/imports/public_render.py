import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _human_when(dt) -> str:
    if not dt:
        return "never"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return "recently"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    if delta.total_seconds() < 60:
        return "just now"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)} hr ago"
    days = int(delta.days)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7} wk ago"
    if days < 365:
        return f"{days // 30} mo ago"
    return f"{days // 365} yr ago"


def get_manage_state(user_id: str) -> dict:
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sa.provider,
                       sa.last_synced_at,
                       (SELECT COUNT(*) FROM imported_repos r WHERE r.user_id = sa.user_id) AS repo_count,
                       (SELECT 1 FROM imported_profile p WHERE p.user_id = sa.user_id AND p.provider = sa.provider LIMIT 1) AS has_profile
                FROM social_accounts sa
                WHERE sa.user_id = %s
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
    out = {
        "github": {"linked": False, "last_synced_human": "never", "repo_count": 0, "has_data": False, "last_synced_at": None},
        "linkedin": {"linked": False, "last_synced_human": "never", "has_basic_profile": False, "has_data": False, "last_synced_at": None},
    }
    for row in rows:
        pid = (row.get("provider") or "").strip().lower()
        if pid not in out:
            continue
        out[pid]["linked"] = True
        last = row.get("last_synced_at")
        out[pid]["last_synced_at"] = last.isoformat() if last else None
        out[pid]["last_synced_human"] = _human_when(last)
        if pid == "github":
            out[pid]["repo_count"] = int(row.get("repo_count") or 0)
            out[pid]["has_data"] = out[pid]["repo_count"] > 0
        else:
            out[pid]["has_basic_profile"] = bool(row.get("has_profile"))
            out[pid]["has_data"] = out[pid]["has_basic_profile"]
    return out


_REPO_SORTS = {
    "stars": "is_pinned DESC, stargazers_count DESC, fetched_at DESC",
    "recent": "is_pinned DESC, fetched_at DESC, stargazers_count DESC",
    "updated": "is_pinned DESC, COALESCE(pushed_at, fetched_at) DESC, stargazers_count DESC",
}


def _repo_dict(r: dict) -> dict:
    return {
        "repo_id": r.get("repo_id"),
        "name": (r.get("name") or "").strip(),
        "full_name": (r.get("full_name") or "").strip(),
        "html_url": (r.get("html_url") or "").strip(),
        "description": (r.get("description") or "").strip() or None,
        "language": (r.get("language") or "").strip() or None,
        "stargazers_count": int(r.get("stargazers_count") or 0),
        "fork": bool(r.get("fork")),
        "is_pinned": bool(r.get("is_pinned")),
        "private": bool(r.get("private")),
        "featured": bool(r.get("featured")),
        "pushed_at": r.get("pushed_at").isoformat() if r.get("pushed_at") else None,
    }


def get_public_sections(user_id: str) -> dict:
    out = {"repos": [], "contributions": [], "contributions_total": 0, "active_days": 0, "profile": None, "marketing": None, "month_labels": [], "day_labels": ["Mon", "Wed", "Fri"]}
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT repo_sort FROM users WHERE id = %s", (user_id,))
            sort_row = cur.fetchone()
            sort_key = (sort_row.get("repo_sort") if sort_row else None) or "stars"
            order_clause = _REPO_SORTS.get(sort_key, _REPO_SORTS["stars"])
            cur.execute(
                f"""
                SELECT repo_id, name, full_name, html_url, description,
                       language, stargazers_count, fork, is_pinned, private, featured,
                       COALESCE(pushed_at, fetched_at) AS pushed_at
                FROM imported_repos
                WHERE user_id = %s AND private = FALSE
                ORDER BY featured DESC, {order_clause}
                LIMIT 6
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
            for r in rows:
                out["repos"].append(_repo_dict(r))
            cur.execute(
                """
                SELECT day, count, level FROM imported_contributions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            days_map = {}
            for row in cur.fetchall() or []:
                d = row.get("day")
                if isinstance(d, str):
                    try:
                        d = datetime.strptime(d, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                if not d:
                    continue
                days_map[d] = {
                    "count": int(row.get("count") or 0),
                    "level": max(0, min(4, int(row.get("level") or 0))),
                }
            cur.execute(
                "SELECT provider, payload, fetched_at FROM imported_profile WHERE user_id = %s",
                (user_id,),
            )
            profile_rows = cur.fetchall() or []
            cur.execute(
                """
                SELECT provider, payload, fetched_at FROM imported_marketing
                WHERE user_id = %s
                """,
                (user_id,),
            )
            marketing_rows = cur.fetchall() or []
    today = date.today()
    start_monday = _monday(today - timedelta(days=52 * 7))
    grid = []
    month_labels = []
    cursor = start_monday
    total_count = 0
    active_days = 0
    last_month = None
    for week_idx in range(53):
        week = []
        any_active = False
        for offset in range(7):
            d = cursor + timedelta(days=offset)
            entry = {"date": d.isoformat(), "count": 0, "level": 0, "is_today": d == today}
            if d > today:
                entry["level"] = -1
            else:
                data = days_map.get(d)
                if data:
                    entry["count"] = data["count"]
                    entry["level"] = data["level"]
                    any_active = True
                    total_count += data["count"]
                    active_days += 1
                if d == today:
                    entry["is_today"] = True
            week.append(entry)
        if any_active or week_idx == 0:
            month_num = cursor.month
            if month_num != last_month:
                month_labels.append((week_idx, cursor.strftime("%b")))
                last_month = month_num
        else:
            month_labels.append((week_idx, ""))
        grid.append(week)
        cursor = cursor + timedelta(days=7)
    out["contributions"] = grid
    out["month_labels"] = month_labels
    out["contributions_total"] = total_count
    out["active_days"] = active_days

    weekly = []
    week_cursor = start_monday
    for week_idx in range(53):
        week_total = 0
        for offset in range(7):
            d = week_cursor + timedelta(days=offset)
            if d > today:
                continue
            data = days_map.get(d)
            if data:
                week_total += data["count"]
        weekly.append({
            "week_start": week_cursor.isoformat(),
            "total": week_total,
            "active": week_total > 0,
            "is_current": today >= week_cursor and today < week_cursor + timedelta(days=7),
        })
        week_cursor = week_cursor + timedelta(days=7)
    max_week = max((w["total"] for w in weekly), default=0)
    for w in weekly:
        w["pct"] = int((w["total"] / max_week) * 100) if max_week > 0 else 0
    out["weekly"] = weekly
    out["weekly_max"] = max_week
    for prow in profile_rows:
        pid = (prow.get("provider") or "").strip().lower()
        payload = prow.get("payload") or {}
        if isinstance(payload, str):
            try:
                import json as _json
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        out["profile"] = {
            "provider": pid,
            "payload": payload,
            "fetched_at": prow.get("fetched_at").isoformat() if prow.get("fetched_at") else None,
        }
        break
    for mrow in marketing_rows:
        pid = (mrow.get("provider") or "").strip().lower()
        payload = mrow.get("payload") or {}
        if isinstance(payload, str):
            try:
                import json as _json
                payload = _json.loads(payload)
            except Exception:
                payload = {}
        out["marketing"] = {
            "provider": pid,
            "payload": payload,
            "fetched_at": mrow.get("fetched_at").isoformat() if mrow.get("fetched_at") else None,
        }
        break
    return out


def get_manage_repos(user_id: str) -> list[dict]:
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT repo_sort FROM users WHERE id = %s", (user_id,))
            sort_row = cur.fetchone()
            sort_key = (sort_row.get("repo_sort") if sort_row else None) or "stars"
            order_clause = _REPO_SORTS.get(sort_key, _REPO_SORTS["stars"])
            cur.execute(
                f"""
                SELECT repo_id, name, full_name, html_url, description,
                       language, stargazers_count, fork, is_pinned, private, featured,
                       COALESCE(pushed_at, fetched_at) AS pushed_at
                FROM imported_repos
                WHERE user_id = %s
                ORDER BY featured DESC, {order_clause}
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
    return [_repo_dict(r) for r in rows]


def set_featured_repos(user_id: str, featured_ids: set[int]) -> dict:
    from app.services.user_auth import _connect
    featured_ids = {int(x) for x in featured_ids if x is not None}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE imported_repos SET featured = FALSE WHERE user_id = %s", (user_id,))
            if featured_ids:
                cur.execute(
                    "UPDATE imported_repos SET featured = TRUE WHERE user_id = %s AND repo_id = ANY(%s)",
                    (user_id, list(featured_ids)),
                )
        conn.commit()
    return {"ok": True, "count": len(featured_ids)}


def has_token(user_id: str, provider: str) -> bool:
    from app.services.user_auth import _connect
    pid = (provider or "").strip().lower()[:16]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM social_accounts WHERE user_id = %s AND provider = %s AND access_token IS NOT NULL",
                (user_id, pid),
            )
            return cur.fetchone() is not None


def is_linked(user_id: str, provider: str) -> bool:
    from app.services.user_auth import _connect
    pid = (provider or "").strip().lower()[:16]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM social_accounts WHERE user_id = %s AND provider = %s",
                (user_id, pid),
            )
            return cur.fetchone() is not None


def save_token(user_id: str, provider: str, token_dict: dict) -> bool:
    from app.services.imports import tokens as _tokens
    from app.services.user_auth import _connect
    pid = (provider or "").strip().lower()[:16]
    raw_access = (token_dict.get("access_token") or "").strip()
    if not raw_access:
        return False
    encrypted = _tokens.encrypt(raw_access)
    if not encrypted:
        return False
    refresh = (token_dict.get("refresh_token") or "").strip() or None
    scope = (token_dict.get("scope") or "").strip() or None
    expires_in = token_dict.get("expires_in")
    from datetime import datetime, timedelta, timezone
    expires_at = None
    try:
        if expires_in is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        expires_at = None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE social_accounts
                SET access_token = %s,
                    refresh_token = COALESCE(%s, refresh_token),
                    scope = COALESCE(%s, scope),
                    expires_at = COALESCE(%s, expires_at)
                WHERE user_id = %s AND provider = %s
                """,
                (encrypted, refresh, scope, expires_at, user_id, pid),
            )
        conn.commit()
    return True


def clear_imports(user_id: str, provider: str) -> None:
    pid = (provider or "").strip().lower()[:16]
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE social_accounts
                SET access_token = NULL,
                    refresh_token = NULL,
                    expires_at = NULL,
                    last_synced_at = NULL
                WHERE user_id = %s AND provider = %s
                """,
                (user_id, pid),
            )
            if pid == "github":
                cur.execute("DELETE FROM imported_repos WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM imported_contributions WHERE user_id = %s", (user_id,))
            elif pid == "linkedin":
                cur.execute("DELETE FROM imported_profile WHERE user_id = %s AND provider = 'linkedin'", (user_id,))
        conn.commit()


def sync_for_user(user_id: str, provider: str) -> dict:
    pid = (provider or "").strip().lower()[:16]
    if pid == "github":
        from app.services.imports import github
        return github.sync_all(user_id)
    if pid == "linkedin":
        from app.services.imports import linkedin
        return linkedin.sync_basic_profile(user_id)
    return {"ok": False, "reason": "unknown-provider"}


def server_configured() -> bool:
    from app.services.imports import tokens
    return tokens._configured()
