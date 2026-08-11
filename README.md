# FolioSpace — Product & Technical Spec (V1–V6 + Hardening)

**Target audience (V1+):** Everyone who needs a portfolio — students, chefs, employees, artists, consultants, developers, freelancers. Not niche-locked.

**V1 wedge:** Existing WhatsApp/LinkedIn network for first 50 users, then free-tier virality.

---

# FolioSpace — V1 Launch Scope

**Goal of V1:** Validate demand with a real, paid, usable product — not a full-feature platform. Ship in weeks, not months.

**Niche for V1 launch:** Existing network (WhatsApp groups, LinkedIn, Odoo community). Use this as the wedge — don't try to serve "everyone" yet, but build the product for everyone.

---

## 1. Core Feature Set (Build This, Nothing More)

### Auth & Account
- Signup/login (email + password, or Google OAuth to reduce friction)
- Username selection at signup → becomes foliospace.com/username
- Reserved-username blocklist (admin, api, login, test, help, pricing, etc.)
- **Email verification: hard-required OR skip entirely — pick one, no soft mode**
- **Reserved-username: simple server-side regex + reject admin/api/etc. No big blocklist needed**

### Portfolio Builder
- 3–5 templates only (not 20) — pick your best, niche-relevant designs
  - Templates must cover multiple professions: consultant, chef, artist, student, developer, employee
  - At least 1 template styled for "consultant/case-study" format (problem → solution → result) since that's the wedge audience
- Editable sections: name, tagline, about, skills, projects/case studies (title, description, image, link), contact info, social links
- Image upload (compressed automatically on upload — don't skip this, it affects PDF export and load speed)
- **Bulk image upload (drag-drop multiple) — editor UX win**

### Public Portfolio Page
- Live at foliospace.com/username
- Mobile-responsive (most views will come from WhatsApp/LinkedIn shares on phone)
- OG meta tags + preview image so links look good when shared on WhatsApp/LinkedIn
- **OG image: static fallback for V1, per-user generated image in V1.5**
- Contact form on the page — **deliver via WhatsApp Business API (vs email) for faster lead delivery, premium feel**
- "Share to WhatsApp" button — opens WhatsApp with a pre-filled message using wa.me link format
- **"Duplicate this portfolio to mine" button on sample/demo portfolios — instant onboarding**

### PDF Export
- One-click "Download as PDF" using Playwright rendering of the live page
- **Generate PDF in background only on `portfolio.update` — NOT on click**
- **Serve pre-generated PDF from R2 with 1-week TTL**
- **One Playwright render per edit, not per download — cuts cost ~95%**
- Available on paid tier only (this is a paid-tier hook)

### Payments & Subscription
- Razorpay Subscriptions API (not Payment Links) — handles ₹150 setup + ₹50/month UPI Autopay with native retry
- **Pricing: ₹150 first payment (setup + month 1), ₹99/month after via autopay (revised from ₹50 — 2x margin headroom)**
- Subscription states: active → grace (3 days) → suspended → archived (60 days) → expired (180 days unpaid → data deleted, username released)
- Daily cron job to check and transition states, send email reminders

### Free Tier (for growth/virality)
- 1 basic template, "Made with FolioSpace" badge, no PDF export, no custom domain
- This is your funnel — free users are marketing surface area

### Analytics (Minimal V1 — was V2, promoted)
- Track: page view (counter), referrer (utm_source), unique visitor hash
- Show owner: "12 views this week, 4 from WhatsApp"
- Cheap to build, huge retention driver, justifies renewal

### Public Leaderboard (Free virality)
- "Top viewed this week" leaderboard on landing page
- Free users opt-in by default, paid users always included
- Zero-cost growth mechanic

---

## 2. Explicitly OUT of Scope for V1 (Build Later, After Validation)

- Custom domain mapping (rohith.dev → portfolio) — V2 upsell tier
- Per-user generated OG image — V1.5 polish
- QR code generator — cheap to add later, not urgent
- Multi-language (Telugu/Hindi) support — nice differentiator, but not needed to validate demand
- Referral program — add once you have paying users to refer from
- Content moderation tooling beyond a basic "report" button — build if/when it's actually needed
- Admin dashboard/analytics for you (beyond basic DB queries) — do this manually at V1 scale

---

## 3. Tech Stack (Fits Your Background)

- **Backend:** FastAPI (Python)
- **DB:** PostgreSQL
- **Frontend:** Server-rendered templates (Jinja2) for V1
- **PDF export:** Playwright (Python) — headless Chromium only
- **Payments:** Razorpay Subscriptions API (primary) + Stripe as backup (for international/failed-UPI users)
- **Hosting:** Railway or Render (V1), DigitalOcean/Hetzner VPS (cost optimization at scale)
- **Image handling:** Pillow for compression on upload
- **Cron/scheduling:** APScheduler
- **Storage:** Cloudflare R2 (S3-compatible, no egress fees) — uploaded images + pre-generated PDFs
- **Email:** Resend or SendGrid (transactional)
- **CDN:** Cloudflare in front of Railway/Render — free, hides origin, faster for India
- **Monitoring:** Sentry free tier (day 1), UptimeRobot free (webhook endpoint + public pages)
- **Rate limiting:** slowapi on signup + username-check endpoints

---

## 3a. Payment & Trust Details

**Payment handling**
- Failed autopay → Razorpay handles native retry (1-2x over a few days) BEFORE starting grace-period countdown
- No refunds for partial/mid-cycle cancellations — state clearly on pricing/ToS page
- Manual admin override — DB flag toggle for personal reactivation if Razorpay/webhook issues

**Trust signals**
- Simple "About" section — your name + background, builds credibility
- 2-3 demo/sample portfolios visible pre-signup, so visitors see real output quality
- **"Duplicate this portfolio to mine" on demos — instant onboarding for visitors**

**Support**
- One visible contact channel (WhatsApp Business number or support email)

**Username rules**
- Lowercase-only, alphanumeric + hyphens, no spaces
- **Username: 1 free change allowed in first 30 days post-payment. After that, ₹50 per change.** Removes support pain, still protects shared links.

**Small polish**
- Favicon + basic branding
- Branded 404 page for nonexistent usernames
- **Branded "archived" page (not just "unavailable") — shows "this portfolio is archived" with reactivation CTA + owner contact for 60 days before deletion**

---

## 3b. Signup & Editing Experience

- **Template preview before payment** — user picks/previews template BEFORE paying
- **Pre-filled onboarding** — new users land on sample-filled portfolio (dummy text/images) they edit
- **Mobile-friendly editor** — given WhatsApp/LinkedIn-driven distribution, many users edit from phone first
- **Email verification: hard-required OR skip — pick one** (no soft mode)

---

## 3c. Integrations — Docs & URLs (Reference for Build)

**Payments — Razorpay**
- Docs home: https://razorpay.com/docs/
- Subscriptions/autopay: https://razorpay.com/docs/payments/subscriptions/
- Webhooks: https://razorpay.com/docs/webhooks/

**PDF Export — Playwright (Python)**
- Docs home: https://playwright.dev/python/docs/intro
- PDF generation: https://playwright.dev/python/docs/api/class-page#page-pdf

**Backend — FastAPI**
- https://fastapi.tiangolo.com/
- Background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/

**Scheduling — APScheduler**
- https://apscheduler.readthedocs.io/

**Image handling — Pillow**
- https://pillow.readthedocs.io/

**Database — PostgreSQL + SQLAlchemy + Alembic**
- https://docs.sqlalchemy.org/
- https://alembic.sqlalchemy.org/

**Auth — Google OAuth**
- https://developers.google.com/identity/protocols/oauth2

**Email — Resend or SendGrid**
- https://resend.com/docs
- https://docs.sendgrid.com/

**Sentry**
- https://docs.sentry.io/

**Cloudflare R2**
- https://developers.cloudflare.com/r2/

---

## 3d. Core Flows

**Flow 1 — New user signup → live portfolio**
1. User visits landing page → clicks "Create your portfolio"
2. Signs up (email+password or Google OAuth) → email verification
3. Picks a template (preview shown, no payment yet)
4. Lands in editor pre-filled with sample content → edits sections
5. Clicks "Publish" → redirected to Razorpay checkout for ₹150
6. Razorpay webhook confirms payment → backend sets `subscription_status = active`, `next_due_date = +30 days`, reserves username
7. Portfolio goes live at foliospace.com/username

**Flow 2 — Recurring monthly payment**
1. Razorpay UPI Autopay auto-charges ₹99 on `next_due_date`
2. Webhook success: extend `next_due_date` +30 days
3. Webhook failure: Razorpay retries natively → if still failing, move to `grace` (3 days) → then `suspended`

**Flow 3 — Suspension → archived → expired**
1. Daily cron: check all users past `grace_ends_at`
2. Set `subscription_status = suspended` → public route shows "archived" page (not portfolio)
3. Owner can still log in, sees "pay to reactivate" banner
4. After 60 days suspended → `archived` state (page shows reactivation CTA + owner contact)
5. After 180 days total unpaid → send final warning email → delete content, release username, set `expired`

**Flow 4 — PDF export (paid tier only)**
1. User edits portfolio → save triggers background Playwright render → PDF stored in R2
2. User clicks "Download as PDF" → served from R2 (pre-generated, 1-week TTL, regenerated on next edit)

**Flow 5 — Payment webhook handling (critical reliability path)**
1. Razorpay sends webhook to `/webhook/razorpay`
2. Backend verifies webhook signature (security)
3. Updates subscription_status/next_due_date accordingly
4. Sentry logs all signature mismatches
5. UptimeRobot monitors webhook endpoint uptime
6. Manual admin override as backup

---

## 3e. Hosting, Storage & Infra

**Backend stack**
- FastAPI ↔ PostgreSQL via SQLAlchemy
- FastAPI ↔ Razorpay (REST + webhooks)
- FastAPI ↔ Playwright (background PDF generation)
- FastAPI ↔ Resend/SendGrid
- FastAPI ↔ Google OAuth
- FastAPI ↔ Cloudflare R2 (images + pre-generated PDFs)
- Cloudflare CDN in front of Railway/Render

**Frontend hosting**
- Jinja2 server-rendered templates from FastAPI
- Railway or Render for V1
- DigitalOcean/Hetzner VPS later (cost optimization)

**File storage**
- Cloudflare R2 (no egress fees, good for India traffic)

**Payment**
- Razorpay Subscriptions API (primary)
- Stripe as backup for international/failed-UPI

**Domain + DNS**
- Registrar → Cloudflare DNS → Railway/Render CNAME
- SSL: automatic on Railway/Render

---

## 3f. Dev Practices

**Testing (V1 minimum)**
- Subscription state machine tests (active→grace→suspended→archived→expired)
- Razorpay webhook handler tests
- GitHub Actions CI on every push to main

**Secrets management**
- `.env` locally via `.env.example`
- Railway/Render env vars in production
- Never commit secrets

**Local dev setup**
- Docker Compose for local Postgres
- README with one-pass setup steps

**Error handling & logging**
- Sentry for exception tracking (day 1)
- Console/file logging for non-critical
- UptimeRobot on webhook endpoint + public pages

**Rate limiting**
- slowapi on signup + username-check endpoints (prevent bot squatting)

**Staging environment**
- Second cheap Railway/Render deploy for testing
- Required once real subscribers exist

---

## 4. Legal/Compliance Before Taking Payment

- Terms of Service + Privacy Policy page
- Refund/cancellation policy page
- Basic data handling disclosure

---

## 5. Pre-Launch Validation

1. Build one-page waitlist/landing site
2. Share in: Odoo groups, freelance WhatsApp groups, LinkedIn, Algora/dev communities
3. Target: 50+ signups in 1-2 weeks
4. If signal weak, revisit niche/hook

---

## 6. Suggested Build Order

1. Landing page + waitlist (validate demand)
2. Auth + username reservation + basic portfolio CRUD
3. **Commission 2-3 freelance designers for templates (₹3-5k each, ₹10-15k total) — OR ship 2 strong templates and iterate**
4. Razorpay payment + subscription state machine + cron
5. PDF export (Playwright, background-only)
6. Free tier + badge + minimal analytics + leaderboard
7. Soft launch to network (first 50 users)

---

## 7. Definition of "V1 Done"

A user can: sign up → pick a template → fill in their work → pay ₹150 → get a live foliospace.com/theirname page → share on WhatsApp with good preview → download as PDF → auto-renew at ₹99/month via UPI autopay → see view counts and referrer source.

Everything else is V2.

---

## 7a. V1 Hardening — 7.5 → 9 Path (Changes from Original Spec)

**Margin (₹50 → ₹99/mo)**
- Doubles margin headroom, still cheap for India
- Justifies Playwright + R2 + Razorpay + Sentry costs

**Username lock → flexible**
- 1 free change in first 30 days post-payment
- ₹50 per change after that
- Removes support pain, keeps shared-link protection

**PDF load — kill it**
- Background generation on edit only
- R2 storage with 1-week TTL
- 1 Playwright render per edit (not per download)

**Analytics promoted to V1**
- Page view counter + referrer (utm_source) + unique visitor hash
- Owner dashboard: "12 views this week, 4 from WhatsApp"
- Retention driver, justifies ₹99/mo renewal

**Razorpay diversification**
- Stripe as backup for international / failed-UPI users

**Template bottleneck — solve upfront**
- Commission 2-3 designers (₹10-15k) OR ship 2 strong templates
- Don't wait for designs to block you

**Subscription lifecycle extended**
- active → grace (3d) → suspended → archived (60d) → expired (180d)
- 180-day total before data delete (was 90)
- Archived state shows reactivation CTA + owner contact

**Cheap V1 wins added**
- "Duplicate this portfolio to mine" on demos → onboarding
- Public leaderboard ("top viewed this week") → free virality
- WhatsApp Business API for contact form → premium lead delivery
- Bulk image upload (drag-drop) → editor UX

**Dropped from V1 (over-engineering)**
- Reserved-username blocklist → simple server-side regex
- Soft email verification → hard-required OR skip
- Per-user OG image generator → static fallback V1, per-user V1.5

**Infra additions**
- Sentry free tier (day 1) — catches webhook failures
- UptimeRobot free — monitors webhook + public pages
- Cloudflare CDN in front of origin — free, faster for India

---

# FolioSpace — V2 Roadmap (Post-Validation)

Start only after V1 has paying users, low churn, organic word-of-mouth.

## 1. Upsell / Higher-Tier Features
- **Custom domain mapping** — user points their own domain (e.g., rohith.dev) to portfolio. Justifies higher tier (₹199-299/month)
- **Deeper analytics** — viewed-this-week trends, time-on-page, device breakdown
- **QR code generator** — auto-generated, linked to live portfolio

## 2. Growth Mechanics
- **Referral program** — "refer a friend, get 1 month free"
- **Multi-language support** (Telugu/Hindi/English)
- **Public template marketplace** — designers submit/sell templates (rev share)

## 3. Product Depth
- **GitHub integration** — auto-pull latest repos/commits
- **Case-study-specific blocks** — deeper problem→solution→result formatting
- **Multiple portfolios per account**

## 4. Trust & Scale Infrastructure
- **Formal admin dashboard** — subscription overview, manual overrides, revenue tracking
- **Content moderation tooling** — flag/report review queue
- **Backup/disaster recovery policy**
- **GST registration** — once revenue crosses ₹20L/year

## 5. Retention/Expansion
- **Email/WhatsApp nudges** — "Portfolio not updated in 60 days", "3 people viewed this week"
- **Seasonal/job-search mode** — template variant tuned for active job searching

**Sequencing note:** Prioritize based on what V1 users ask for, not this list alone.

---

# FolioSpace — V3 Roadmap (Scale Stage)

Start only after V2 is live, retention/churn healthy, consistent MRR.

## 1. Market Expansion
- **Multi-currency / international pricing** — region-based, not 1:1 INR→USD
- **New niche verticals** — designers, photographers, writers (own templates + hooks)
- **Agency/team accounts** — multiple portfolios under one paying account

## 2. Platform & Marketplace
- **Template marketplace maturity** — open to third-party designers, proper rev-share
- **API access** — power users (agencies, devs) programmatic updates
- **Integrations** — LinkedIn auto-import, Behance/Dribbble sync, WATI/WhatsApp Business API

## 3. Retention & Intelligence
- **AI-assisted content writing** — "about" or case-study from prompts
- **A/B testing for users** — test 2 portfolio versions
- **Smart renewal prediction** — flag likely-to-churn users

## 4. Infrastructure & Ops Maturity
- **Dedicated support team/ticketing**
- **SLA-backed uptime**
- **DPDP Act (India) compliance audit**
- **Team hiring** — support, design, second dev

**Sequencing note:** V3 = real scale pressure. Don't build speculatively.

---

# FolioSpace — V4 Roadmap (Platform/Ecosystem Stage)

Start only when V3 infra is solid, real team, stable profitable business. Far-future, speculative.

## 1. Ecosystem & Developer Platform
- **Public API + developer docs portal**
- **Zapier/Make integration**
- **White-label offering** — agencies/platforms license FolioSpace engine

## 2. Advanced AI Features
- **AI portfolio generation from resume/LinkedIn upload** — auto-build draft portfolio
- **AI-driven template recommendation** — based on role/field

## 3. Marketplace Maturity
- **Full creator economy for templates** — rev share, leaderboards, versioning
- **Portfolio-to-job matching** — recruiters discover portfolios (opt-in, strong privacy)

## 4. Enterprise/B2B
- **Enterprise accounts** — agencies/universities managing 100s of portfolios
- **SSO (SAML) support**
- **Custom SLAs and dedicated infra**

## 5. Global Scale Infra
- **Multi-region hosting**
- **SOC 2 / ISO certification**

**Sequencing note:** V4 = directional thinking, not commitment. Revisit only when V3 fully realized and genuine business reason exists.

---

# FolioSpace — V5: Technical Implementation Spec

Technical detail layer underneath V1, needed for a coding agent to build without guessing.

## 1. Database Schema

**users**
- id (PK), email (unique), password_hash, google_id (nullable), email_verified (bool), created_at

**portfolios**
- id (PK), user_id (FK), username (unique, lowercase, alphanumeric+hyphen), template_id (FK), title, tagline, about_text, skills (JSON), contact_email, social_links (JSON), created_at, updated_at

**portfolio_sections** (projects/case studies)
- id (PK), portfolio_id (FK), title, description, image_url, project_link, sort_order

**templates**
- id (PK), name, preview_image_url, is_free_tier (bool), html_template_path

**subscriptions**
- id (PK), user_id (FK), status (enum: active/grace/suspended/archived/expired), razorpay_subscription_id, last_paid_date, next_due_date, grace_ends_at, archived_at, created_at

**payments**
- id (PK), user_id (FK), razorpay_payment_id, amount, status, created_at

**portfolio_views** (analytics — promoted to V1)
- id (PK), portfolio_id (FK), viewed_at, referrer_source, visitor_hash

## 2. API Route Structure

**Auth**
- POST /auth/signup
- POST /auth/login
- GET /auth/google/callback
- POST /auth/verify-email

**Portfolio (editor)**
- POST /portfolio (create)
- GET /portfolio/me
- PUT /portfolio/me
- POST /portfolio/me/upload-image
- POST /portfolio/me/publish (triggers payment flow)
- POST /portfolio/me/change-username (1 free in 30d, ₹50 after)

**Public**
- GET /{username} (renders portfolio or archived/unavailable page)
- GET /{username}/pdf (paid tier, served from R2)
- POST /{username}/contact (delivers via WhatsApp Business API)

**Payments**
- POST /payment/create-order (₹150 setup)
- POST /webhook/razorpay (signature-verified)

**Admin (internal)**
- GET /admin/users
- POST /admin/subscription/override (manual reactivation)

**Analytics**
- POST /track/view (called from public page)
- GET /portfolio/me/analytics (owner view)

## 3. Folder Structure

```
portfoliopop/
├── app/
│   ├── main.py
│   ├── models/          (SQLAlchemy models)
│   ├── routers/          (auth.py, portfolio.py, public.py, payment.py, admin.py, analytics.py)
│   ├── schemas/          (Pydantic request/response)
│   ├── services/          (razorpay_service.py, pdf_service.py, email_service.py, storage_service.py)
│   ├── templates/          (Jinja2 HTML — includes /templates/portfolio_designs/ for 3-5 portfolio templates)
│   ├── static/          (CSS/JS/images for app itself)
│   └── cron/          (subscription_check.py — daily state transition)
├── alembic/          (DB migrations)
├── tests/
├── .env.example
└── requirements.txt
```

## 4. Cron Job Logic (Daily, APScheduler)

```
For each subscription where status == 'active' and next_due_date < today:
    move to 'grace', set grace_ends_at = today + 3 days

For each subscription where status == 'grace' and grace_ends_at < today:
    move to 'suspended', send reactivation email

For each subscription where status == 'suspended' for 60+ days:
    move to 'archived', archived_at = today
    (public page now shows "archived" with reactivation CTA)

For each subscription where status == 'archived' for 120+ more days (180 total unpaid):
    send final warning email
    after 7 more days: delete portfolio content, release username, set status = 'expired'
```

## 5. What to Hand a Coding Agent

Give both V5 spec AND V1 feature/flow sections together. Expect to review DB migrations and webhook signature verification manually — payment security never fully trusted to an agent.

---

# FolioSpace — V6: Testing, QA & DevOps Maturity

Practices layer that starts light in V1 and matures as product grows.

## 1. Testing Maturity
- **V1 minimum:** subscription state machine + webhook handler tests
- **V2:** analytics data accuracy, custom domain DNS verification
- **Real revenue at stake:** end-to-end signup→payment→live-portfolio tests (Playwright E2E)
- **CI:** GitHub Actions on every push before merge to main

## 2. Observability
- **V1:** Sentry free tier + UptimeRobot free (day 1)
- **Real users:** structured JSON logs
- **Meaningful scale:** Sentry paid tier, full observability stack

## 3. Deployment Maturity
- **V1:** manual Railway/Render git-push deploy
- **Staging exists:** simple CI/CD — push to staging branch auto-deploys
- **Scale:** blue-green or rolling deploys

## 4. Security Practices
- Webhook signature verification (day 1, non-negotiable)
- `pip-audit` or Dependabot for dependency updates
- Free OWASP ZAP scan before real scale

## 5. When to Invest
Don't front-load V6 maturity before V1 has paying users. Trigger testing growth when bug costs money; observability growth when finding out from users; deployment maturity when bad deploy = real downtime.
