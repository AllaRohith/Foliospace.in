import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _http_get_bearer(url: str, token: str, accept: str = "application/vnd.github+json") -> dict | list | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("github GET %s failed: %s", url, e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _http_post_graphql(token: str, query: str, variables: dict) -> dict | None:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("github POST graphql failed: %s", e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _http_get_json(url: str) -> dict | list | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("contrib GET %s failed: %s", url, e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_token_for(user_id: str) -> str | None:
    from app.services.imports import tokens as _tokens
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM social_accounts WHERE user_id = %s AND provider = 'github'",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _tokens.decrypt(row.get("access_token"))


def get_username(user_id: str) -> str | None:
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider_uid, email FROM social_accounts WHERE user_id = %s AND provider = 'github'",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return (row.get("provider_uid") or "").strip() or None


def sync_repos(user_id: str) -> dict:
    token = get_token_for(user_id)
    if not token:
        return {"ok": False, "reason": "no-token", "count": 0}
    pages = 0
    seen = []
    page = 1
    while pages < 3:
        url = f"{GITHUB_API}/user/repos?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator,organization_member"
        data = _http_get_bearer(url, token)
        if not isinstance(data, list):
            logger.warning("github sync: page %d non-list response", page)
            break
        logger.warning("github sync: page %d returned %d repos", page, len(data))
        seen.extend(data)
        if len(data) < 100:
            break
        page += 1
        pages += 1
    logger.warning("github sync: total %d repos fetched across %d pages", len(seen), pages)
    rows = []
    seen_ids = set()
    from datetime import datetime
    for r in seen:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not rid:
            continue
        seen_ids.add(int(rid))
        pushed_at_val = None
        pushed_at_raw = r.get("pushed_at")
        if pushed_at_raw:
            try:
                pushed_at_val = datetime.fromisoformat(str(pushed_at_raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pushed_at_val = None
        rows.append((
            int(rid),
            (r.get("name") or "").strip()[:200] or "repo",
            (r.get("full_name") or "").strip()[:200] or "user/repo",
            (r.get("html_url") or "").strip()[:2048],
            (r.get("description") or "").strip()[:1000] or None,
            (r.get("language") or "").strip()[:80] or None,
            int(r.get("stargazers_count") or 0),
            bool(r.get("fork")),
            bool(r.get("pinned")),
            bool(r.get("private")),
            pushed_at_val,
        ))
    if not rows and not seen:
        from app.services.user_auth import _connect
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM imported_repos WHERE user_id = %s", (user_id,))
            conn.commit()
        return {"ok": True, "count": 0}
    logger.warning("github sync: parsed %d rows from %d raw", len(rows), len(seen))
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            from psycopg.types.json import Json
            cur.executemany(
                """
                INSERT INTO imported_repos
                    (user_id, repo_id, name, full_name, html_url, description,
                     language, stargazers_count, fork, is_pinned, private, pushed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, repo_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    full_name = EXCLUDED.full_name,
                    html_url = EXCLUDED.html_url,
                    description = EXCLUDED.description,
                    language = EXCLUDED.language,
                    stargazers_count = EXCLUDED.stargazers_count,
                    fork = EXCLUDED.fork,
                    is_pinned = EXCLUDED.is_pinned,
                    private = EXCLUDED.private,
                    pushed_at = EXCLUDED.pushed_at,
                    fetched_at = NOW()
                """,
                [(user_id, *row) for row in rows],
            )
            if seen_ids:
                cur.execute(
                    "DELETE FROM imported_repos WHERE user_id = %s AND NOT (repo_id = ANY(%s))",
                    (user_id, list(seen_ids)),
                )
            else:
                cur.execute(
                    "DELETE FROM imported_repos WHERE user_id = %s AND featured = FALSE",
                    (user_id,),
                )
            cur.execute(
                "UPDATE social_accounts SET last_synced_at = NOW() WHERE user_id = %s AND provider = 'github'",
                (user_id,),
            )
        conn.commit()
    return {"ok": True, "count": len(rows)}


def sync_contributions(user_id: str) -> dict:
    token = get_token_for(user_id)
    if not token:
        return {"ok": False, "reason": "no-token", "count": 0}
    query = """
    {
      viewer {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
              }
            }
          }
        }
      }
    }
    """
    payload = _http_post_graphql(token, query, {})
    if not isinstance(payload, dict):
        logger.warning("github graphql: no payload")
        return {"ok": False, "reason": "graphql-failed", "count": 0}
    if payload.get("errors"):
        logger.warning("github graphql errors: %s", payload.get("errors"))
    data = payload.get("data") or {}
    viewer = data.get("viewer") or {}
    if not viewer:
        logger.warning("github graphql: viewer is null — token probably lacks read:user")
        return {"ok": False, "reason": "no-viewer", "count": 0}
    collection = viewer.get("contributionsCollection") or {}
    calendar = collection.get("contributionCalendar") or {}
    weeks = calendar.get("weeks") or []
    rows = []
    total = int(calendar.get("totalContributions") or 0)
    for week in weeks:
        days = week.get("contributionDays") or []
        for day in days:
            dstr = (day.get("date") or "").strip()
            if not dstr:
                continue
            try:
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
            except ValueError:
                continue
            try:
                count = int(day.get("contributionCount") or 0)
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                level = 0
            elif count < 4:
                level = 1
            elif count < 7:
                level = 2
            elif count < 10:
                level = 3
            else:
                level = 4
            if count > 0:
                rows.append((user_id, d, count, level))
    logger.warning("github contrib: total %d, %d active days", total, len(rows))
    if not rows:
        return {"ok": True, "count": 0, "total": total}
    from app.services.user_auth import _connect
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM imported_contributions WHERE user_id = %s", (user_id,))
            cur.executemany(
                """
                INSERT INTO imported_contributions (user_id, day, count, level)
                VALUES (%s, %s, %s, %s)
                """,
                rows,
            )
        conn.commit()
    return {"ok": True, "count": len(rows), "total": total}


def sync_all(user_id: str) -> dict:
    repos = sync_repos(user_id)
    contribs = sync_contributions(user_id)
    return {"repos": repos, "contributions": contribs}
