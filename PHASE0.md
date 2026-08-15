# FolioSpace — Project Notes

## Stack

- FastAPI + Jinja2 server-rendered HTML
- raw `psycopg` against Postgres (Neon free tier)
- vanilla CSS + JS, no build step
- Resend for transactional email
- Render free tier for hosting

## Layout

```
app/
├── main.py               FastAPI app, mounts static + routers
├── middleware.py         CSP / HSTS / TrustedHost / OriginCheck / SecurityHeaders
├── routers/
│   ├── waitlist.py       POST /api/waitlist/join, GET /api/waitlist/count
│   ├── stats.py          GET /api/stats
│   └── admin.py          /admin/* console
├── services/
│   ├── email_service.py  Resend welcome + internal notifications
│   └── admin_auth.py     bcrypt + cookie sessions + audit log
├── templates/
│   ├── base.html         Layout, OG/Twitter meta, fonts
│   ├── landing.html      One-page site
│   ├── privacy.html
│   ├── terms.html
│   ├── error.html
│   ├── emails/welcome.html
│   └── admin/            Dashboard, signups, audit, login
└── static/
    ├── css/style.css     Design system
    ├── css/admin.css
    ├── js/main.js        Front-end
    ├── js/admin.js       Admin console
    ├── js/utm.js         UTM capture (localStorage)
    ├── js/curtain.js     Pre-paint class for the cover reveal
    ├── img/{og.png, logo.svg, logo-mark.svg, favicon.svg}
    └── fonts/{Saira-Variable.ttf, Saira-Italic-Variable.ttf, StalinistOne-Regular.ttf}

scripts/
├── init_db.sql           waitlist table — run first
├── admin_init_db.sql     admin_sessions, admin_audit_log, admin_login_attempts — run second
├── waitlist_utm.sql      UTM columns + index — run third (idempotent, safe on fresh DBs)
└── generate_og.py        Regenerate app/static/img/og.png after copy changes
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill DATABASE_URL + ADMIN_* vars
python scripts/init_db.sql # via psql or Neon SQL editor
uvicorn app.main:app --reload --port 8780
```

## Deploy

See [DEPLOY.md](DEPLOY.md). Free tier only — Render web + Neon DB + GoDaddy DNS, no card.

## Current state

- Phase 0 — waitlist landing page live at https://foliospace.in
- Phase 1 — admin console at `/admin` for tracking signups
- Phase 2 — product not yet built; landing page + admin is the waitlist instrument

## Where data lives

- Waitlist rows: Postgres `waitlist` table (schema in [scripts/init_db.sql](scripts/init_db.sql))
- Admin sessions: Postgres `admin_sessions` (24h absolute, 30m idle)
- Admin audit: Postgres `admin_audit_log`
- Old `data/waitlist.json` is gitignored legacy — no Python code reads it.