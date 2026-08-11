import os
import logging
from pathlib import Path

import resend

logger = logging.getLogger(__name__)

API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "FolioSpace <hello@foliospace.in>")
REPLY_TO = os.getenv("RESEND_REPLY_TO", "rohit@foliospace.in")
PUBLIC_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"


def _load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def send_welcome_email(to_email: str) -> tuple[bool, str]:
    if not API_KEY:
        logger.info("RESEND_API_KEY not set, skipping email to %s", to_email)
        return False, "no_api_key"

    try:
        resend.api_key = API_KEY
        html = _load_template("welcome.html")
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


def send_internal_notification(email: str, role: str | None) -> tuple[bool, str]:
    if not API_KEY:
        return False, "no_api_key"
    try:
        resend.api_key = API_KEY
        body = (
            f"New waitlist signup\n\n"
            f"Email: {email}\n"
            f"Role:  {role or '(unspecified)'}\n"
        )
        params = {
            "from": FROM_EMAIL,
            "to": [REPLY_TO],
            "subject": f"New waitlist signup: {email}",
            "text": body,
        }
        resend.Emails.send(params)
        return True, "ok"
    except Exception as e:
        logger.exception("internal notification failed: %s", e)
        return False, str(e)
