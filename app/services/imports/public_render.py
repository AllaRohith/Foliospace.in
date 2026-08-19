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


def get_public_sections(user_id: str) -> dict:
    out = {"repos": [], "contributions": [], "contributions_total": 0, "profile": None}
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT repo_id, name, full_name, html_url, description,
                       language, stargazers_count, fork, is_pinned
                FROM imported_repos
                WHERE user_id = %s
                ORDER BY is_pinned DESC, stargazers_count DESC, fetched_at DESC
                LIMIT 6
                """,
                (user_id,),
            )
            for r in cur.fetchall() or []:
                out["repos"].append({
                    "repo_id": r.get("repo_id"),
                    "name": (r.get("name") or "").strip(),
                    "full_name": (r.get("full_name") or "").strip(),
                    "html_url": (r.get("html_url") or "").strip(),
                    "description": (r.get("description") or "").strip() or None,
                    "language": (r.get("language") or "").strip() or None,
                    "stargazers_count": int(r.get("stargazers_count") or 0),
                    "fork": bool(r.get("fork")),
                    "is_pinned": bool(r.get("is_pinned")),
                })
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
    today = date.today()
    start_monday = _monday(today - timedelta(days=52 * 7))
    grid = []
    cursor = start_monday
    total_count = 0
    for _ in range(53):
        week = []
        for offset in range(7):
            d = cursor + timedelta(days=offset)
            if d > today:
                week.append({"date": d.isoformat(), "count": 0, "level": -1})
                continue
            data = days_map.get(d)
            if data:
                week.append({"date": d.isoformat(), "count": data["count"], "level": data["level"]})
                total_count += data["count"]
            else:
                week.append({"date": d.isoformat(), "count": 0, "level": 0})
        grid.append(week)
        cursor = cursor + timedelta(days=7)
    out["contributions"] = grid
    out["contributions_total"] = total_count
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
    return out


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
