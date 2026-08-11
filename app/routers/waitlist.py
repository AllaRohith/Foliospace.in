import json
import re
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services import email_service

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])

limiter = Limiter(key_func=get_remote_address)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
WAITLIST_FILE = DATA_DIR / "waitlist.json"

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

HONEYPOT_FIELD = "website"


def _read_waitlist() -> list:
    if not WAITLIST_FILE.exists():
        return []
    try:
        return json.loads(WAITLIST_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_waitlist(entries: list) -> None:
    WAITLIST_FILE.write_text(json.dumps(entries, indent=2))


@router.post("/join")
@limiter.limit("5/minute")
async def join_waitlist(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(...),
    role: str = Form(""),
    website: str = Form(""),
):
    if website:
        return JSONResponse(status_code=200, content={"ok": True, "message": "OK."})

    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email")

    entries = _read_waitlist()
    is_new = not any(e["email"] == email for e in entries)

    if is_new:
        entries.append(
            {
                "email": email,
                "role": role.strip() or None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ip": request.client.host if request.client else None,
            }
        )
        _write_waitlist(entries)
        background.add_task(email_service.send_welcome_email, email)
        background.add_task(email_service.send_internal_notification, email, role.strip() or None)

    return JSONResponse(
        status_code=201 if is_new else 200,
        content={
            "ok": True,
            "new": is_new,
            "count": len(entries),
            "message": "You're in. We'll email you when we launch." if is_new else "You're already on the list.",
        },
    )


@router.get("/count")
async def count():
    return {"count": len(_read_waitlist())}
