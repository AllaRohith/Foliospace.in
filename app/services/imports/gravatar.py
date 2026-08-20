import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

GRAVATAR_API = "https://api.gravatar.com/v3/profiles/"

API_KEY = (os.getenv("GRAVATAR_API_KEY") or "").strip()

TIMEOUT = 6


def _hash_email(email: str) -> str:
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def _http_get_json(url: str) -> dict | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
            **({"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.info("gravatar GET %s failed: %s", url, e)
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _find_verified(data: dict, service_type: str) -> str:
    for entry in (data.get("verified_accounts") or []):
        if not isinstance(entry, dict):
            continue
        if (entry.get("service_type") or "").strip().lower() == service_type:
            url = (entry.get("url") or "").strip()
            if url:
                return url[:2048]
    return ""


def lookup(email: str) -> dict | None:
    if not email or "@" not in email:
        return None
    digest = _hash_email(email)
    qs = f"?interim=true"
    if API_KEY:
        qs += f"&api_key={urllib.parse.quote(API_KEY)}"
    data = _http_get_json(f"{GRAVATAR_API}{digest}{qs}")
    if not data:
        return None
    job_title = (data.get("job_title") or "").strip()[:80]
    company = (data.get("company") or "").strip()[:120]
    location = (data.get("location") or "").strip()[:120]
    description = (data.get("description") or "").strip()[:280]
    pronouns = (data.get("pronouns") or "").strip()[:40]
    linkedin_url = _find_verified(data, "linkedin")
    github_url = _find_verified(data, "github")
    if not any([job_title, company, location, description, linkedin_url, github_url, pronouns]):
        return None
    return {
        "job_title": job_title,
        "company": company,
        "location": location,
        "description": description,
        "pronouns": pronouns,
        "linkedin_url": linkedin_url,
        "github_url": github_url,
        "source": "gravatar",
    }
