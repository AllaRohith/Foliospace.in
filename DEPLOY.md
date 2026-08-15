# Deploy FolioSpace to foliospace.in

Free-tier deploy path: Render (web) + Neon (Postgres) + GoDaddy DNS. No credit card required per Render's April 2026 policy and Neon's free tier terms.

## What is already done

- Code committed and pushed to `main` on `github.com/AllaRohith/Foliospace.in`
- `render.yaml` references all env vars (DATABASE_URL, PUBLIC_BASE_URL, RESEND_*) as `sync: false` so Render surfaces them for you to fill in
- `app/routers/waitlist.py` uses Postgres via psycopg (idempotent insert, parameterized queries)
- `app/main.py` has `ProxyHeadersMiddleware` so the app sees the real visitor IP + `https` scheme behind Render's load balancer
- `scripts/init_db.sql` has the waitlist schema ready to run

## Steps for you

### 1. Create a Neon account + project (free, no card)

1. Go to <https://neon.tech> and sign up with GitHub OAuth.
2. Create a new project. Name it `foliospace`. Region: pick the closest to your users (Mumbai `aws-ap-south-1` if available, else Singapore or Frankfurt).
3. From the project dashboard, copy the **connection string**. It looks like:
   ```
   postgresql://neondb_owner:xxxxxxxx@ep-xxx-xxx.region.aws.neon.tech/neondb?sslmode=require
   ```
   Save this — you'll paste it into Render.

### 2. Run the schema against Neon

Run all three migrations in order. Each is idempotent.

**Option A — Neon's web SQL editor:**
- Neon dashboard → your project → SQL Editor
- Paste and run `scripts/init_db.sql`
- Paste and run `scripts/admin_init_db.sql` (admin tables — sessions, audit log)
- Paste and run `scripts/waitlist_utm.sql` (UTM columns + index on `waitlist`)

**Option B — psql from your terminal:**
```bash
psql "<paste-the-neon-connection-string-here>" -f scripts/init_db.sql
psql "<paste-the-neon-connection-string-here>" -f scripts/admin_init_db.sql
psql "<paste-the-neon-connection-string-here>" -f scripts/waitlist_utm.sql
```

Verify with:
```bash
psql "<connection-string>" -c "\dt"
```
You should see `waitlist`, `admin_sessions`, and `admin_audit_log` (plus their indexes).

### 3. Create a Render account (verify no card asked)

1. Go to <https://render.com/register> and sign up with GitHub OAuth.
2. **At the signup screen, confirm no credit card is requested.** Render's April 2026 article says no card is needed, but policies change. If they ask for one, abort and we'll pivot.

### 4. Connect Render to your GitHub repo

1. Render dashboard → **New** → **Blueprint**.
2. Connect the `AllaRohith/Foliospace.in` repo (you may need to authorize Render to see your GitHub repos).
3. Render reads `render.yaml` and proposes a web service named `foliospace` on the free plan. Confirm.

### 5. Fill in the env vars

In the Render dashboard for the `foliospace` service → **Environment**:

| Key                          | Value / how to set                                                       |
|------------------------------|--------------------------------------------------------------------------|
| `DATABASE_URL`               | The Neon connection string from step 1                                   |
| `PUBLIC_BASE_URL`            | `https://foliospace.in`                                                  |
| `APP_ENV`                    | `production` (already set in `render.yaml` — leave it)                   |
| `ENV`                        | `production` (already set in `render.yaml` — leave it)                   |
| `RESEND_FROM_EMAIL`          | `FolioSpace <hello@foliospace.in>` (already set in `render.yaml`)         |
| `RESEND_REPLY_TO`            | `rohit@foliospace.in`                                                    |
| `RESEND_API_KEY`             | *(leave empty for now — emails skip gracefully)*                         |
| `ADMIN_SESSION_SECRET`       | Run `python -c "import secrets; print(secrets.token_urlsafe(64))"` locally and paste the output. **Required.** App hard-crashes without it. |
| `ADMIN_PASSWORD_HASH`        | Run `python -c "from app.services.admin_auth import hash_password; print(hash_password('YOUR_PASSWORD'))"` locally with your chosen admin password and paste the output. **Required** to log into `/admin`. |
| `LAUNCH_DATE`                | ISO-8601 date like `2026-09-02T00:00:00+05:30`. **Required** to render the countdown in the welcome email. |
| `INTERNAL_TRUST_TOKEN`       | Optional. Run `python -c "import secrets; print(secrets.token_urlsafe(32))"` locally. Lets trusted internal callers send POSTs to `/api/waitlist/join` or `/admin/login` without an Origin/Referer by passing the same value in `X-Internal-Token`. Leave empty in production to keep CSRF protection strict. |

> **Generate the secret and password hash on the same machine you'll commit from**, not in the Render dashboard. They never need to be re-typed anywhere else.

Save. Render will redeploy automatically.

### 6. Verify the deploy works on the default Render URL

1. Open the URL Render gave you — looks like `https://foliospace.onrender.com`.
2. The landing page should render identically to local.
3. Submit the waitlist form with any email.
4. Check in Neon (SQL Editor) that the row landed: `SELECT email, created_at FROM waitlist;`

> **Note about the 15-min sleep:** Render's free tier spins down the web service after 15 min of no traffic. First hit after sleep takes ~1 min (Render shows its loading page). This is acceptable for V0 sharing in small groups.

### 7. Add the custom domain

In Render dashboard → `foliospace` service → **Settings** → **Custom Domains** → **Add Custom Domain**:

- Add `foliospace.in` — Render tells you an **A record** target (an IP address)
- Add `www.foliospace.in` — Render tells you a **CNAME** target (looks like `foliospace.onrender.com` or a proxy host Render generates)

Leave both Render tabs open — you'll need the targets for the next step.

### 8. Update GoDaddy DNS

1. Log into GoDaddy → **My Products** → **Domains** → `foliospace.in` → **DNS** (or **Manage DNS**).
2. **Remove** the default parking A record for `@` if it exists.
3. **Add** these records:

| Type  | Name | Value                          | TTL  |
|-------|------|--------------------------------|------|
| A     | `@`  | (the Render IP from step 7)    | 600  |
| CNAME | `www`| (the Render CNAME from step 7) | 600  |

4. Save. DNS propagation takes 5–60 minutes.

> **If Render also shows a `_dnslink` or verification TXT**, add that too.

### 9. Wait for SSL

1. Back in Render → Custom Domains. The status for both `foliospace.in` and `www.foliospace.in` should turn green (✓) once DNS resolves and Let's Encrypt issues the cert. Can take up to 30 min after DNS propagates.
2. Once green, open `https://foliospace.in` in a browser — should show the page with a valid SSL padlock.

### 10. (Optional, recommended) Keep the service warm

Render free sleeps after 15 min idle. To prevent this:

1. Sign up at <https://uptimerobot.com> (free, no card, 50 monitors).
2. Add a new monitor: type **HTTP(s)**, URL `https://foliospace.in`, interval **5 minutes**.
3. Save. UptimeRobot will ping every 5 min, keeping Render awake.

## Verification checklist

- [ ] `curl -sI https://foliospace.in | head -1` → `HTTP/2 200`
- [ ] `curl -s https://foliospace.in/robots.txt` shows `Sitemap: https://foliospace.in/sitemap.xml`
- [ ] Browser shows valid SSL padlock on `https://foliospace.in`
- [ ] Form submission lands in Neon (`SELECT count(*) FROM waitlist;`)
- [ ] `https://foliospace.in/api/waitlist/count` returns the right number
- [ ] Dark mode toggle works (cmd-K palette)
- [ ] Mobile (375px) renders without horizontal scroll

## Troubleshooting

**Render asks for a card at signup.** Stop. The April 2026 policy said no card, but they may have changed it back. Don't add a card. Ping me and we'll pivot to Hugging Face Spaces (no card, but only `foliospace.hf.space` URL, no custom domain).

**DNS won't resolve.** Check `dig foliospace.in` in your terminal. The A record should point to the Render IP. If it's still pointing to GoDaddy's parking IPs, your change hasn't propagated — wait longer or check you removed the parking record.

**SSL doesn't provision.** In Render → Custom Domains, look at the error message. Most common: DNS doesn't point to Render yet (wait longer), or the apex A record isn't using the exact IP Render gave you (no aliases, no CNAME at apex).

**Form submits but row doesn't land in Neon.** Check Render logs for the error. Most likely: `DATABASE_URL` has the wrong password, or Neon is paused (free tier pauses after extended inactivity — go to Neon dashboard and resume).

**Render service is sleeping when you visit.** First hit takes ~1 min. Sign up for UptimeRobot as described in step 10.

## Adding Resend later (when you have an API key)

1. Sign up at <https://resend.com>, verify `foliospace.in` (Resend gives you SPF + DKIM records — add those to GoDaddy DNS).
2. Set `RESEND_API_KEY` in Render env vars.
3. Redeploy.

Welcome emails will start sending automatically — no code changes needed.