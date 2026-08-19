import os


def install_template_globals(templates) -> None:
    """Register the same Jinja globals on every Jinja2Templates instance.

    Routers each construct their own Jinja2Templates (because Starlette
    keeps per-config env isolation). This helper makes sure every router
    gets the same globals so any template anywhere can call them.

    SSOT invariants this preserves:
      - `asset_v`         → CSS/JS cache-bust (env-driven)
      - `plan_summary(u)` → plan-state to template (single source of truth)
      - `compute_completion(u)` → profile-completion numbers (single source)
      - `nav_user(request)` → top-nav user object (single source)
    """
    templates.env.globals["asset_v"] = (
        os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "dev"
    )[:8]

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
