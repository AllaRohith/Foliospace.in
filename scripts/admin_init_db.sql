CREATE TABLE IF NOT EXISTS admin_sessions (
    id           TEXT PRIMARY KEY,
    ip           TEXT,
    user_agent   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS admin_sessions_expires_at_idx
    ON admin_sessions (expires_at);

CREATE TABLE IF NOT EXISTS admin_login_attempts (
    id           SERIAL PRIMARY KEY,
    ip           TEXT NOT NULL,
    success      BOOLEAN NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS admin_login_attempts_ip_time_idx
    ON admin_login_attempts (ip, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id           SERIAL PRIMARY KEY,
    session_id   TEXT REFERENCES admin_sessions(id) ON DELETE SET NULL,
    ip           TEXT,
    action       TEXT NOT NULL,
    target       TEXT,
    metadata     JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS admin_audit_log_created_at_idx
    ON admin_audit_log (created_at DESC);