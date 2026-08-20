import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

PROVIDERS = ("google", "github", "linkedin")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_PROFILE_URL = "https://openidconnect.googleapis.com/v1/userinfo"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_PROFILE_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_PROFILE_URL = "https://api.linkedin.com/v2/userinfo"


def _redirect_base() -> str:
    return (os.getenv("OAUTH_REDIRECT_BASE") or os.getenv("PUBLIC_URL") or "https://foliospace.in").strip().rstrip("/")


def callback_uri(provider: str, kind: str = "callback") -> str:
    pid = provider.lower().strip()
    return f"{_redirect_base()}/auth/oauth/{pid}/{kind}"


def _provider_config(provider: str) -> dict | None:
    pid = provider.lower().strip()
    client_id = os.getenv(f"OAUTH_{pid.upper()}_CLIENT_ID", "").strip()
    client_secret = os.getenv(f"OAUTH_{pid.upper()}_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {
        "provider": pid,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": callback_uri(pid, "callback"),
    }


def is_configured(provider: str) -> bool:
    return _provider_config(provider) is not None


def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if is_configured(p)]


def _scope_for(provider: str) -> str:
    if provider == "google":
        return "openid email profile"
    if provider == "github":
        return "read:user user:email repo"
    if provider == "linkedin":
        return "openid profile email"
    return ""


def build_authorize_url(provider: str, state: str, redirect_uri: str | None = None) -> str | None:
    cfg = _provider_config(provider)
    if not cfg:
        return None
    pid = cfg["provider"]
    target = (redirect_uri or cfg["redirect_uri"]).strip()
    scope = _scope_for(pid)
    if pid == "google":
        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": target,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
            "include_granted_scopes": "true",
        }
    elif pid == "github":
        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": target,
            "scope": scope,
            "state": state,
            "allow_signup": "true",
        }
    elif pid == "linkedin":
        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": target,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
    else:
        return None
    base = {
        "google": GOOGLE_AUTH_URL,
        "github": GITHUB_AUTH_URL,
        "linkedin": LINKEDIN_AUTH_URL,
    }[pid]
    return f"{base}?{urllib.parse.urlencode(params)}"


def _http_post_form(url: str, data: dict, headers: dict | None = None) -> dict | None:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("oauth POST %s failed: %s", url, e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _http_get(url: str, headers: dict | None = None) -> dict | None:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "FolioSpace/1.0 (+https://foliospace.in)",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning("oauth GET %s failed: %s", url, e)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _exchange_code(provider: str, code: str, redirect_uri: str | None = None) -> dict | None:
    cfg = _provider_config(provider)
    if not cfg:
        return None
    pid = cfg["provider"]
    target = (redirect_uri or cfg["redirect_uri"]).strip()
    data = {
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": target,
        "grant_type": "authorization_code",
    }
    headers = None
    if pid == "github":
        headers = {"Accept": "application/json"}
    return _http_post_form(
        {
            "google": GOOGLE_TOKEN_URL,
            "github": GITHUB_TOKEN_URL,
            "linkedin": LINKEDIN_TOKEN_URL,
        }[pid],
        data,
        headers=headers,
    )


def _fetch_profile(provider: str, access_token: str) -> dict | None:
    pid = provider.lower().strip()
    bearer = {"Authorization": f"Bearer {access_token}"}
    if pid == "google":
        return _http_get(GOOGLE_PROFILE_URL, headers=bearer)
    if pid == "github":
        user = _http_get(GITHUB_PROFILE_URL, headers=bearer)
        if not user:
            return None
        email = (user.get("email") or "").strip().lower()
        if not email:
            emails = _http_get(GITHUB_EMAILS_URL, headers=bearer) or []
            for entry in emails:
                if entry.get("primary") and entry.get("verified") and entry.get("email"):
                    email = entry["email"].strip().lower()
                    break
            if not email:
                for entry in emails:
                    if entry.get("email"):
                        email = entry["email"].strip().lower()
                        break
        user["email"] = email
        return user
    if pid == "linkedin":
        return _http_get(LINKEDIN_PROFILE_URL, headers=bearer)
    return None


def normalize_profile(provider: str, raw: dict) -> dict | None:
    pid = provider.lower().strip()
    if not raw:
        return None
    if pid == "google":
        uid = (raw.get("sub") or "").strip()
        email = (raw.get("email") or "").strip().lower()
        name = (raw.get("name") or raw.get("given_name") or "").strip()
    elif pid == "github":
        uid = str(raw.get("id") or "").strip()
        email = (raw.get("email") or "").strip().lower()
        name = (raw.get("name") or raw.get("login") or "").strip()
    elif pid == "linkedin":
        uid = (raw.get("sub") or "").strip()
        email = (raw.get("email") or "").strip().lower()
        name = (raw.get("name") or raw.get("given_name") or "").strip()
    else:
        return None
    if not uid or not email:
        return None
    return {
        "provider": pid,
        "uid": uid[:255],
        "email": email[:254],
        "name": name[:80],
    }


def complete(provider: str, code: str, redirect_uri: str | None = None) -> tuple[dict | None, dict | None]:
    pid = provider.lower().strip()
    if pid not in PROVIDERS:
        return None, None
    token_data = _exchange_code(pid, code, redirect_uri=redirect_uri)
    if not token_data:
        return None, None
    access_token = (token_data.get("access_token") or "").strip()
    if not access_token:
        return None, token_data
    raw_profile = _fetch_profile(pid, access_token)
    if not raw_profile:
        return None, token_data
    return normalize_profile(pid, raw_profile), token_data


def generate_state() -> str:
    return secrets.token_urlsafe(24)