# FolioSpace

One-page portfolio SaaS for Indian professionals — chefs, developers, students, consultants, shop owners, agencies, founders. Live at [foliospace.in](https://foliospace.in).

This repository is the production site: landing page, waitlist signup, and an `/admin` console for tracking signups. The actual portfolio product is not yet built.

## Stack

- **Web:** FastAPI + Jinja2 (server-rendered HTML), vanilla CSS + JS, no build step
- **DB:** Postgres on Neon free tier, raw `psycopg` (no ORM)
- **Hosting:** Render free tier ([render.yaml](render.yaml))
- **Email:** Resend for transactional mail
- **DNS:** GoDaddy

## Layout

```
app/
├── main.py               FastAPI app, route registration, sitemap, error pages
├── middleware.py         CSP / HSTS / TrustedHost / OriginCheck / SecurityHeaders
├── routers/
│   ├── waitlist.py       POST /api/waitlist/join, GET /api/waitlist/count
│   ├── stats.py          GET /api/stats (cover-counter + microcopy polling)
│   └── admin.py          /admin/* console (login, dashboard, signups, audit, export)
├── services/
│   ├── email_service.py  Resend welcome + internal notifications
│   └── admin_auth.py     bcrypt + cookie sessions + audit log + rate-limit
├── templates/
│   ├── base.html         Layout, OG/Twitter meta, fonts
│   ├── landing.html      One-page site
│   ├── features.html     Integration roadmap page (GitHub + LinkedIn, no auth)
│   ├── privacy.html
│   ├── terms.html
│   ├── error.html
│   ├── emails/welcome.html
│   ├── partials/         Shared nav (_nav.html) and footer (_footer.html)
│   └── admin/            dashboard, signups, signup_detail, audit, login, base
└── static/
    ├── css/style.css     Design system
    ├── css/admin.css
    ├── js/main.js        Front-end (form submit, curtain reveal, marquee)
    ├── js/admin.js       Admin console
    ├── js/utm.js         UTM capture (localStorage)
    ├── js/curtain.js     Pre-paint class for the cover reveal
    ├── img/{og.png, logo.svg, logo-mark.svg, favicon.svg}
    └── fonts/{Saira-Variable.ttf, Saira-Italic-Variable.ttf, StalinistOne-Regular.ttf}

scripts/
├── init_db.sql           waitlist table
├── admin_init_db.sql     admin_sessions, admin_audit_log, admin_login_attempts
├── waitlist_utm.sql      UTM columns + index (idempotent)
└── generate_og.py        Regenerate app/static/img/og.png after copy changes

.env.example              Local dev template
render.yaml               Render blueprint (free plan)
DEPLOY.md                 Operator runbook for fresh deploys
PHASE0.md                 Project notes & file map
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill DATABASE_URL + ADMIN_* + RESEND_* vars
psql "$DATABASE_URL" -f scripts/init_db.sql
psql "$DATABASE_URL" -f scripts/admin_init_db.sql
psql "$DATABASE_URL" -f scripts/waitlist_utm.sql
uvicorn app.main:app --reload --port 8780
```

Set `ADMIN_PASSWORD_HASH` to a bcrypt-hashed password:

```bash
python -c "from app.services.admin_auth import hash_password; print(hash_password('your-pass'))"
```

## Deploy

See [DEPLOY.md](DEPLOY.md). Free tier only — Render + Neon + GoDaddy, no card.

## Environment

| Var                          | Required | Default                  |
|------------------------------|----------|--------------------------|
| `APP_ENV` / `ENV`            | no       | `production`             |
| `DATABASE_URL`               | yes      | —                        |
| `PUBLIC_BASE_URL`            | yes      | `http://localhost:8000`  |
| `RESEND_API_KEY`             | no       | empty (emails skip)      |
| `RESEND_FROM_EMAIL`          | no       | `FolioSpace <hello@foliospace.in>` |
| `RESEND_REPLY_TO`            | no       | `rohit@foliospace.in`    |
| `LAUNCH_DATE`                | no       | empty (no countdown)     |
| `ADMIN_SESSION_SECRET`       | yes (prod) | dev fallback            |
| `ADMIN_PASSWORD_HASH`        | yes      | empty (login disabled)   |
| `ADMIN_SESSION_TTL_HOURS`   | no       | `24`                     |
| `ADMIN_SESSION_IDLE_MINUTES` | no       | `30`                     |
| `ADMIN_LOGIN_FAIL_WINDOW_MINUTES` | no | `15`                      |
| `ADMIN_LOGIN_FAILS_TRIGGER`  | no       | `10`                     |
| `ALLOWED_HOSTS`              | no       | derived from `PUBLIC_BASE_URL` |
| `RENDER_GIT_COMMIT`          | no       | used as asset cache-bust |

## Security posture

- CSP `default-src 'self'; script-src 'self'; …` — no `'unsafe-inline'`. The cover-curtain pre-paint class is set via an external `static/js/curtain.js` (CSP-compliant).
- HSTS (`max-age=31536000; includeSubDomains`), `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, Permissions-Policy lockdown.
- TrustedHostMiddleware — host allowlist.
- OriginCheckMiddleware — POSTs to `/api/waitlist/join`, `/admin/login`, `/admin/logout`, `/admin/signups/*/delete` require an `Origin` or `Referer` matching the allowed host set.
- Cookie `fs_admin` is `SameSite=Lax`, `https_only=True` in prod.
- Rate limits (slowapi): `/api/waitlist/join` 5/min, `/api/waitlist/count` 60/min, admin login 10/15min.
- Body cap 8 KB on POSTs.
- Honeypot field `website` on the waitlist form.

## Hard constraints

- No comments in CSS / JS / templates.
- No GSAP / ScrollTrigger / build tooling.
- No SQLAlchemy, no Alembic — raw `psycopg` only.
- No fabricated locations, team-size claims, or author names in brand copy / OG / meta / footer.
- The form contract (`#join`, honeypot `website`, `email`, `role`, `form-msg`) must stay intact.

## Generating the OG image

After changing the OG copy in [scripts/generate_og.py](scripts/generate_og.py):

```bash
python3 scripts/generate_og.py
```

Output: `app/static/img/og.png` (1200×630).

## License

Proprietary. © 2026 FolioSpace.