-- Per-folio visit tracking. DPDP-safe: stores hashed IP, never raw IP.
-- Dedup is enforced at the DB level (one row per slug + ip_hash + view_date).
CREATE TABLE IF NOT EXISTS folio_views (
    id          BIGSERIAL PRIMARY KEY,
    slug        TEXT        NOT NULL,
    ip_hash     TEXT        NOT NULL,
    user_agent  TEXT,
    viewed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    view_date   DATE        NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')::date
);

CREATE INDEX IF NOT EXISTS folio_views_slug_viewed_at_idx
    ON folio_views (slug, viewed_at DESC);

CREATE INDEX IF NOT EXISTS folio_views_slug_date_idx
    ON folio_views (slug, view_date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS folio_views_dedup_idx
    ON folio_views (slug, ip_hash, view_date);