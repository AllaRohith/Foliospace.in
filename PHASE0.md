# Phase 0 — Waitlist Landing Page

## Run locally

```bash
cd /Users/rohithnaidualla/Desktop/FolioSpace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

## What it does

- One-page landing site
- Email + role signup → stored in `data/waitlist.json`
- Mobile-first, OG-tagged, WhatsApp-share-ready
- Rate-limited to 5 submits/min/IP

## Files

```
app/
├── main.py               FastAPI app, mounts static + routers
├── routers/waitlist.py   POST /api/waitlist/join, GET /api/waitlist/count
├── templates/
│   ├── base.html         Layout, OG/Twitter meta, fonts
│   └── landing.html      Hero + showcase + features + pricing + signup
└── static/
    ├── css/style.css     Design system
    ├── js/main.js        Form submit + status
    └── img/favicon.svg
data/waitlist.json        Storage (auto-created)
```

## What's next (Phase 1)

- Auth (email/password + Google OAuth)
- Username reservation
- Portfolio CRUD
- Replace `data/waitlist.json` with Postgres
