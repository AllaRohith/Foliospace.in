CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT,
    slug            TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    role            TEXT,
    email_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    claimed_at      TIMESTAMPTZ,
    claim_token     TEXT UNIQUE,
    claim_expires_at TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS users_slug_lower_idx ON users (lower(slug));
CREATE INDEX IF NOT EXISTS users_claim_token_idx ON users (claim_token) WHERE claim_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS users_last_login_idx ON users (last_login_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS user_sessions (
    id           TEXT PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip           TEXT,
    user_agent   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS user_sessions_user_id_idx ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS user_sessions_expires_at_idx ON user_sessions (expires_at);

CREATE TABLE IF NOT EXISTS user_login_attempts (
    id           SERIAL PRIMARY KEY,
    ip           TEXT NOT NULL,
    email        TEXT,
    success      BOOLEAN NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_login_attempts_ip_time_idx ON user_login_attempts (ip, created_at DESC);

CREATE TABLE IF NOT EXISTS user_audit_log (
    id           SERIAL PRIMARY KEY,
    session_id   TEXT REFERENCES user_sessions(id) ON DELETE SET NULL,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    ip           TEXT,
    action       TEXT NOT NULL,
    target       TEXT,
    metadata     JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_audit_log_created_at_idx ON user_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS user_audit_log_user_id_idx ON user_audit_log (user_id, created_at DESC);