CREATE TABLE IF NOT EXISTS waitlist (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    role TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip TEXT,
    utm_source   TEXT,
    utm_medium   TEXT,
    utm_campaign TEXT,
    referer      TEXT
);

CREATE INDEX IF NOT EXISTS waitlist_email_lower_idx ON waitlist (lower(email));
CREATE INDEX IF NOT EXISTS waitlist_utm_source_idx ON waitlist (utm_source) WHERE utm_source IS NOT NULL;