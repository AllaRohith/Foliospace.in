CREATE TABLE IF NOT EXISTS pending_comp_grants (
    id                  BIGSERIAL PRIMARY KEY,
    email               TEXT NOT NULL,
    expires_at          TIMESTAMPTZ,
    reason              TEXT,
    notes               TEXT,
    granted_by_user_id  UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at         TIMESTAMPTZ,
    consumed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    revoked_at          TIMESTAMPTZ,
    UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS pending_comp_grants_open_idx
    ON pending_comp_grants (email) WHERE consumed_at IS NULL AND revoked_at IS NULL;