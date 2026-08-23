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


def is_launched(now: datetime | None = None) -> bool:
    if not LAUNCH_DATE:
        return False
    current = now or datetime.now(timezone.utc)
    if LAUNCH_DATE.tzinfo is None:
        launch_aware = LAUNCH_DATE.replace(tzinfo=timezone.utc)
    else:
        launch_aware = LAUNCH_DATE
    return current >= launch_aware

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

# Single-source-of-truth pricing/trial globals for every email template.
from app.pricing import (
    PRO_MONTHLY_INR as _PRO_MONTHLY_INR,
    PRO_ANNUAL_INR as _PRO_ANNUAL_INR,
    FREE_PRICE_INR as _FREE_PRICE_INR,
    TRIAL_DAYS as _TRIAL_DAYS,
    annual_savings_percent as _annual_savings_percent,
)
_jinja_env.globals["PRO_MONTHLY_INR"] = _PRO_MONTHLY_INR
_jinja_env.globals["PRO_ANNUAL_INR"] = _PRO_ANNUAL_INR
_jinja_env.globals["FREE_PRICE_INR"] = _FREE_PRICE_INR
_jinja_env.globals["TRIAL_DAYS"] = _TRIAL_DAYS
_jinja_env.globals["annual_savings_percent"] = _annual_savings_percent


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


def send_payment_failed_email(to_email: str, days_left: int, slug: str = "") -> tuple[bool, str]:
    """Day-1 email on Cashfree SUBCRIPTION_CHARGED failure.

    Replaces the old trial-ending template (trial was retired Phase B).
    Same brand; day-7 follow-up is intentionally not implemented yet — we
    keep this single reminder so the user gets one clear nudge to fix
    the UPI mandate.
    """
    if not API_KEY:
        logger.info("RESEND_API_KEY not set, skipping payment-failed email to %s", to_email)
        return False, "no_api_key"
    try:
        resend.api_key = API_KEY
        days_int = max(0, int(days_left))
        context = {
            "public_url": PUBLIC_URL,
            "first_name": _first_name_from_email(to_email),
            "days_left": days_int,
            "slug": (slug or "")[:64],
            "billing_url": f"{PUBLIC_URL}/dashboard/billing",
        }
        html = _render_template("payment_failed.html", **context)
        subject = f"Your FolioSpace Pro payment didn't go through"
        params = {
            "from": FROM_EMAIL,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "html": html,
        }
        result = resend.Emails.send(params)
        msg_id = result.get("id", "unknown") if isinstance(result, dict) else str(result)
        logger.info("sent payment-failed email to %s (days_left=%s, id=%s)",
                    to_email, days_int, msg_id)
        return True, msg_id
    except Exception as e:
        logger.exception("send_payment_failed_email failed for %s: %s", to_email, e)
        return False, "send_error"


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


def send_otp_email(to_email: str, code: str, ttl_minutes: int = 10) -> tuple[bool, str]:
    if not API_KEY:
        logger.info("RESEND_API_KEY not set, skipping OTP email to %s", to_email)
        return False, "no_api_key"
    try:
        resend.api_key = API_KEY
        context = {
            "public_url": PUBLIC_URL,
            "first_name": _first_name_from_email(to_email),
            "code": code,
            "ttl_minutes": ttl_minutes,
        }
        html = _render_template("otp.html", **context)
        subject = f"Your FolioSpace code: {code}"
        params = {
            "from": FROM_EMAIL,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "html": html,
        }
        result = resend.Emails.send(params)
        msg_id = result.get("id", "unknown") if isinstance(result, dict) else str(result)
        logger.info("sent OTP email to %s (id=%s)", to_email, msg_id)
        return True, msg_id
    except Exception as e:
        logger.exception("failed to send OTP email to %s: %s", to_email, e)
        return False, str(e)


def send_password_reset_email(to_email: str, reset_link: str, ttl_minutes: int = 30) -> tuple[bool, str]:
    if not API_KEY:
        logger.info("RESEND_API_KEY not set, skipping reset email to %s", to_email)
        return False, "no_api_key"
    try:
        resend.api_key = API_KEY
        context = {
            "public_url": PUBLIC_URL,
            "first_name": _first_name_from_email(to_email),
            "reset_link": reset_link,
            "ttl_minutes": ttl_minutes,
        }
        html = _render_template("password_reset.html", **context)
        subject = "Reset your FolioSpace password"
        params = {
            "from": FROM_EMAIL,
            "to": [to_email],
            "reply_to": REPLY_TO,
            "subject": subject,
            "html": html,
        }
        result = resend.Emails.send(params)
        msg_id = result.get("id", "unknown") if isinstance(result, dict) else str(result)
        logger.info("sent password reset email to %s (id=%s)", to_email, msg_id)
        return True, msg_id
    except Exception as e:
        logger.exception("failed to send reset email to %s: %s", to_email, e)
        return False, str(e)
