ALTER TABLE subscription_grants
    ADD COLUMN IF NOT EXISTS warn_14d_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS warn_7d_sent_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS warn_1d_sent_at  TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS subscription_grants_warn_14d_idx
    ON subscription_grants (expires_at) WHERE revoked_at IS NULL AND warn_14d_sent_at IS NULL;
CREATE INDEX IF NOT EXISTS subscription_grants_warn_7d_idx
    ON subscription_grants (expires_at) WHERE revoked_at IS NULL AND warn_7d_sent_at IS NULL;
CREATE INDEX IF NOT EXISTS subscription_grants_warn_1d_idx
    ON subscription_grants (expires_at) WHERE revoked_at IS NULL AND warn_1d_sent_at IS NULL;