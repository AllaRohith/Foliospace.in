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
