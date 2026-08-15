import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.utils.text import strip_control as _strip_control


def _strip_control(value: str) -> str:
    return strip_control(value) if value else ""

logger = logging.getLogger(__name__)

API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "FolioSpace <hello@foliospace.in>")
REPLY_TO = os.getenv("RESEND_REPLY_TO", "rohit@foliospace.in")
PUBLIC_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

_DEFAULT_LAUNCH_DATE_STR = "2026-09-02T00:00:00+05:30"
_LAUNCH_DATE_STR = os.getenv("LAUNCH_DATE", "").strip() or _DEFAULT_LAUNCH_DATE_STR
LAUNCH_DATE: datetime | None = None
try:
    LAUNCH_DATE = datetime.fromisoformat(_LAUNCH_DATE_STR)
except ValueError:
    logger.warning("LAUNCH_DATE env var is set but invalid: %s", _LAUNCH_DATE_STR)
    try:
        LAUNCH_DATE = datetime.fromisoformat(_DEFAULT_LAUNCH_DATE_STR)
    except ValueError:
        logger.warning("default LAUNCH_DATE is unparseable: %s", _DEFAULT_LAUNCH_DATE_STR)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _render_template(name: str, **context) -> str:
    template = _jinja_env.get_template(name)
    return template.render(**context)


def _first_name_from_email(email: str) -> str:
    if not email:
        return "there"
    local = email.split("@", 1)[0].strip()
    if not local:
        return "there"
    for sep in (".", "_", "-", "+", "·", "•", "、", "．"):
        if sep in local:
            local = local.split(sep, 1)[0]
            break
    local = "".join(ch for ch in local if ch.isalpha() or ch == " ")
    if not local:
        return "there"
    return local[:1].upper() + local[1:].lower()


def _launch_context() -> dict:
    if not LAUNCH_DATE:
        return {"show_launch": False}
    now = datetime.now(timezone.utc)
    delta = LAUNCH_DATE - now
    days = max(0, delta.days)
    return {
        "show_launch": True,
        "days_until_launch": days,
        "launch_date_formatted": _format_day(LAUNCH_DATE),
        "launch_time_formatted": _format_time(LAUNCH_DATE),
    }


def _format_day(dt: datetime) -> str:
    return f"{dt.day} {_month_name(dt.month)} {dt.year}"


def _format_time(dt: datetime) -> str:
    hour12 = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour12}:{minute} {suffix} IST"


def _month_name(m: int) -> str:
    return ["", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"][m]


def send_welcome_email(to_email: str) -> tuple[bool, str]:
    if not API_KEY:
        logger.info("RESEND_API_KEY not set, skipping email to %s", to_email)
        return False, "no_api_key"

    try:
        resend.api_key = API_KEY
        context = {
            "public_url": PUBLIC_URL,
            "first_name": _first_name_from_email(to_email),
            **_launch_context(),
        }
        html = _render_template("welcome.html", **context)
        subject = "You're on the FolioSpace waitlist"
        params = {
            "from": FROM_EMAIL,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "html": html,
        }
        result = resend.Emails.send(params)
        msg_id = result.get("id", "unknown") if isinstance(result, dict) else str(result)
        logger.info("sent welcome email to %s (id=%s)", to_email, msg_id)
        return True, msg_id
    except Exception as e:
        logger.exception("failed to send welcome email to %s: %s", to_email, e)
        return False, str(e)


def send_internal_notification(
    email: str,
    role: str | None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    referer: str | None = None,
) -> tuple[bool, str]:
    if not API_KEY:
        return False, "no_api_key"
    try:
        resend.api_key = API_KEY
        safe_email = _strip_control(email)[:254]
        safe_role = _strip_control(role) if role else None
        safe_src = _strip_control(utm_source)[:64] if utm_source else None
        safe_med = _strip_control(utm_medium)[:64] if utm_medium else None
        safe_camp = _strip_control(utm_campaign)[:64] if utm_campaign else None
        safe_ref = _strip_control(referer)[:256] if referer else None
        body = (
            f"New waitlist signup\n\n"
            f"Email: {safe_email}\n"
            f"Role:  {safe_role or '(unspecified)'}\n"
        )
        if safe_src or safe_med or safe_camp:
            body += "\nAttribution:\n"
            if safe_src:
                body += f"  source:   {safe_src}\n"
            if safe_med:
                body += f"  medium:   {safe_med}\n"
            if safe_camp:
                body += f"  campaign: {safe_camp}\n"
        if safe_ref:
            body += f"\nReferer: {safe_ref}\n"
        params = {
            "from": FROM_EMAIL,
            "to": [REPLY_TO],
            "reply_to": REPLY_TO,
            "subject": f"New waitlist signup: {safe_email}"[:200],
            "text": body,
        }
        resend.Emails.send(params)
        return True, "ok"
    except Exception as e:
        logger.exception("internal notification failed: %s", e)
        return False, str(e)
