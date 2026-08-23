CREATE TABLE IF NOT EXISTS subscription_grants (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_by_admin    BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at          TIMESTAMPTZ,
    reason              TEXT,
    notes               TEXT,
    granted_by_user_id  UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at          TIMESTAMPTZ,
    revoked_by_user_id  UUID,
    revoke_reason       TEXT,
    UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS subscription_grants_active_idx
    ON subscription_grants (user_id) WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS subscription_grants_expires_idx
    ON subscription_grants (expires_at) WHERE revoked_at IS NULL;
