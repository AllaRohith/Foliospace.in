import os
import re
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.utils.text import strip_control as _strip_control, strip_control_strict as _strip_control_strict

ALLOWED_FORM_CONTENT_TYPES = {
    "application/x-www-form-urlencoded",
    "multipart/form-data",
}

MAX_FORM_BODY_BYTES = 8 * 1024


def _allowed_hosts() -> list[str]:
    raw = os.getenv("ALLOWED_HOSTS", "").strip()
    if raw:
        return [h.strip().lower() for h in raw.split(",") if h.strip()]
    base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if base:
        host = urlparse(base).hostname
        if host:
            return [host.lower(), f"www.{host.lower()}"]
    return ["foliospace.in", "www.foliospace.in", "localhost", "127.0.0.1", "testserver"]


def _allowed_origins() -> list[str]:
    hosts = _allowed_hosts()
    origins = set()
    for host in hosts:
        if host in ("localhost", "127.0.0.1"):
            origins.add(f"http://{host}")
            origins.add(f"https://{host}")
        else:
            origins.add(f"https://{host}")
            origins.add(f"http://{host}")
    return list(origins)


def _origin_key(origin: str) -> str:
    parsed = urlparse(origin.lower())
    if not parsed.scheme or not parsed.hostname:
        return ""
    return f"{parsed.scheme}://{parsed.hostname}"


def _csp() -> str:
    parts = [
        "default-src 'self'",
        "script-src 'self' https://checkout.razorpay.com https://cdn.razorpay.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob:",
        "connect-src 'self' https://lumberjack.razorpay.com",
        "frame-src 'self' https://api.razorpay.com https://checkout.razorpay.com",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "media-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self' blob:",
    ]
    if (os.getenv("ENV") or os.getenv("APP_ENV") or "production").lower() == "production":
        parts.append("upgrade-insecure-requests")
    return "; ".join(parts)


def _security_headers(request: Request, response: Response) -> None:
    if response.headers.get("Content-Security-Policy") is None:
        response.headers["Content-Security-Policy"] = _csp()
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("X-DNS-Prefetch-Control", "off")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    ctype = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype == "text/html":
        if request.url.path.startswith("/u/") or (response.headers.get("Cache-Control") or "").lower().startswith("public"):
            if response.headers.get("Cache-Control") is None:
                response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    elif request.url.path.startswith("/static/"):
        if response.headers.get("Cache-Control") is None:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        _security_headers(request, response)
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str] | None = None, trust_internal_token: str | None = None):
        super().__init__(app)
        self.allowed = {_origin_key(o) for o in (allowed_origins or _allowed_origins()) if o}
        self.allowed.discard("")
        self.safe_methods = {"GET", "HEAD", "OPTIONS"}
        self.webhook_paths = ("/webhooks/",)
        self.protected_paths = (
            "/api/waitlist/join",
            "/admin/login",
            "/admin/logout",
            "/signup",
            "/login",
            "/logout",
            "/dashboard/profile",
            "/dashboard/billing/subscribe",
            "/dashboard/billing/cancel",
        )
        self.protected_prefixes = (
            "/admin/signups/",
        )
        self.trust_internal_token = (trust_internal_token or os.getenv("INTERNAL_TRUST_TOKEN") or "").strip()

    def _is_protected(self, path: str) -> bool:
        if any(path.startswith(p) for p in self.webhook_paths):
            return False
        if any(path == p or path.startswith(p + "/") for p in self.protected_paths):
            return True
        if any(path.startswith(p) for p in self.protected_prefixes):
            return path.endswith("/delete")
        return False

    def _is_trusted_internal(self, request: Request) -> bool:
        if not self.trust_internal_token:
            return False
        provided = request.headers.get("x-internal-token", "").strip()
        return bool(provided) and provided == self.trust_internal_token

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method not in self.safe_methods and self._is_protected(path) and not self._is_trusted_internal(request):
            ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ctype not in ALLOWED_FORM_CONTENT_TYPES:
                return JSONResponse(
                    {"ok": False, "message": "Unsupported Content-Type."},
                    status_code=415,
                )
            cl = request.headers.get("content-length")
            if cl:
                try:
                    if int(cl) > MAX_FORM_BODY_BYTES:
                        return JSONResponse(
                            {"ok": False, "message": "Payload too large."},
                            status_code=413,
                        )
                except ValueError:
                    return JSONResponse(
                        {"ok": False, "message": "Invalid Content-Length."},
                        status_code=400,
                    )
            origin = _strip_control_strict(request.headers.get("origin", ""))
            referer = _strip_control(request.headers.get("referer", ""))
            if origin:
                if _origin_key(origin) not in self.allowed:
                    return JSONResponse(
                        {"ok": False, "message": "Origin not allowed."},
                        status_code=403,
                    )
            elif referer:
                parsed = urlparse(referer.lower())
                ref_key = f"{parsed.scheme}://{parsed.hostname}" if parsed.scheme and parsed.hostname else ""
                if not ref_key or ref_key not in self.allowed:
                    return JSONResponse(
                        {"ok": False, "message": "Referer not allowed."},
                        status_code=403,
                    )
            else:
                return JSONResponse(
                    {"ok": False, "message": "Origin required."},
                    status_code=403,
                )
        return await call_next(request)


def install_security(app) -> None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
    app.add_middleware(OriginCheckMiddleware, allowed_origins=_allowed_origins())
    app.add_middleware(SecurityHeadersMiddleware)
