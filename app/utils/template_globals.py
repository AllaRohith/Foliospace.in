import os
from pathlib import Path


def install_template_globals(templates) -> None:
    """Register the same Jinja globals on every Jinja2Templates instance.

    Routers each construct their own Jinja2Templates (because Starlette
    keeps per-config env isolation). This helper makes sure every router
    gets the same globals so any template anywhere can call them.

    SSOT invariants this preserves:
      - `asset_v`         → CSS/JS cache-bust (env + content mtime)
      - `plan_summary(u)` → plan-state to template (single source of truth)
      - `compute_completion(u)` → profile-completion numbers (single source)
      - `nav_user(request)` → top-nav user object (single source)
    """
    sha = (
        os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "dev"
    )[:8]

    css_mtime = "0"
    css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "main.css"
    if css_path.exists():
        try:
            css_mtime = str(int(css_path.stat().st_mtime))
        except OSError:
            css_mtime = "0"

    templates.env.globals["asset_v"] = f"{sha}-{css_mtime}"

    templates.env.globals["APP_ENV"] = (os.getenv("ENV") or os.getenv("APP_ENV") or "production").lower()

    from app.services.billing import plan_summary as _plan_summary
    from app.services.user_auth import compute_completion as _compute_completion

    def plan_summary(user):
        try:
            return _plan_summary(user or {})
        except Exception:
            return _plan_summary({})

    def compute_completion(user):
        try:
            return _compute_completion(user or {})
        except Exception:
            return {"filled": 0, "total": 6, "fields": []}

    templates.env.globals["plan_summary"] = plan_summary
    templates.env.globals["compute_completion"] = compute_completion

    # Pricing / trial / founder-cohort SSOT — every template reads from here.
    from app.pricing import (
        FREE_PRICE_INR as _FREE_PRICE_INR,
        PRO_MONTHLY_INR as _PRO_MONTHLY_INR,
        PRO_ANNUAL_INR as _PRO_ANNUAL_INR,
        PRO_YEAR1_INR as _PRO_YEAR1_INR,
        PRO_YEAR2_INR as _PRO_YEAR2_INR,
        TRIAL_DAYS as _TRIAL_DAYS,
        PAYMENT_GRACE_DAYS as _PAYMENT_GRACE_DAYS,
        FOUNDER_COHORT_LIMIT as _FOUNDER_COHORT_LIMIT,
        annual_savings_percent as _annual_savings_percent,
        fmt_inr as _fmt_inr,
        trial_label as _trial_label,
    )
    templates.env.globals["FREE_PRICE_INR"] = _FREE_PRICE_INR
    templates.env.globals["PRO_MONTHLY_INR"] = _PRO_MONTHLY_INR
    templates.env.globals["PRO_ANNUAL_INR"] = _PRO_ANNUAL_INR
    templates.env.globals["PRO_YEAR1_INR"] = _PRO_YEAR1_INR
    templates.env.globals["PRO_YEAR2_INR"] = _PRO_YEAR2_INR
    templates.env.globals["TRIAL_DAYS"] = _TRIAL_DAYS
    templates.env.globals["PAYMENT_GRACE_DAYS"] = _PAYMENT_GRACE_DAYS
    templates.env.globals["FOUNDER_COHORT_LIMIT"] = _FOUNDER_COHORT_LIMIT
    templates.env.globals["annual_savings_percent"] = _annual_savings_percent
    templates.env.globals["fmt_inr"] = _fmt_inr
    templates.env.globals["trial_label"] = _trial_label

    try:
        from app.services.email_service import LAUNCH_DATE as _LD, is_launched as _is_launched
        from datetime import timezone as _tz

        def launch_iso() -> str:
            if not _LD:
                return ""
            if _LD.tzinfo is None:
                return _LD.replace(tzinfo=_tz.utc).isoformat()
            return _LD.isoformat()

        def launch_date_label() -> str:
            if not _LD:
                return ""
            try:
                from app.services.email_service import _format_day, _format_time
                return f"{_format_day(_LD)} · {_format_time(_LD)}"
            except Exception:
                try:
                    return _LD.strftime("%B %-d, %Y · %-I:%M %p IST")
                except ValueError:
                    return _LD.strftime("%B %d, %Y · %I:%M %p IST").replace(" 0", " ")

        def launched() -> bool:
            try:
                return bool(_is_launched())
            except Exception:
                return False

        templates.env.globals["launch_iso"] = launch_iso
        templates.env.globals["launch_date_label"] = launch_date_label
        templates.env.globals["launched"] = launched
    except Exception:
        pass

    try:
        from app.services import user_auth as _user_auth

        def nav_user(request):
            try:
                user = _user_auth.require_user(request)
            except Exception:
                return None
            if not user:
                return None
            return {
                "id": str(user["id"]),
                "email": user["email"],
                "slug": user["slug"],
                "display_name": user.get("display_name") or "",
                "role": user.get("role") or "",
            }

        templates.env.globals["nav_user"] = nav_user
    except Exception:
        pass
