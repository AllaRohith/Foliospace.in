CREATE TABLE IF NOT EXISTS waitlist (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    role TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip TEXT
);

CREATE INDEX IF NOT EXISTS waitlist_email_lower_idx ON waitlist (lower(email));