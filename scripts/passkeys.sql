-- WebAuthn / Passkey support.
-- Additive only. Does not modify any existing table.
-- Safe to re-run: every statement uses IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS passkey_credentials (
    id                BIGSERIAL PRIMARY KEY,
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id     BYTEA NOT NULL UNIQUE,
    public_key        BYTEA NOT NULL,
    sign_count        INTEGER NOT NULL DEFAULT 0,
    transports        TEXT[],
    aaguid            UUID,
    user_verified     BOOLEAN NOT NULL DEFAULT FALSE,
    backup_eligible   BOOLEAN NOT NULL DEFAULT FALSE,
    backup_state      BOOLEAN NOT NULL DEFAULT FALSE,
    friendly_name     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at      TIMESTAMPTZ,
    revoked_at        TIMESTAMPTZ,
    CONSTRAINT passkey_credentials_user_unique UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS passkey_credentials_active_idx
    ON passkey_credentials (user_id) WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS passkey_credentials_credential_id_idx
    ON passkey_credentials (credential_id);

CREATE TABLE IF NOT EXISTS webauthn_challenges (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('register', 'login')),
    challenge     BYTEA NOT NULL,
    user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
    email_hint    TEXT,
    expires_at    TIMESTAMPTZ NOT NULL,
    consumed_at   TIMESTAMPTZ,
    attempts      INTEGER NOT NULL DEFAULT 0,
    ip            INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS webauthn_challenges_expires_idx
    ON webauthn_challenges (expires_at) WHERE consumed_at IS NULL;

CREATE INDEX IF NOT EXISTS webauthn_challenges_user_idx
    ON webauthn_challenges (user_id, kind) WHERE consumed_at IS NULL;