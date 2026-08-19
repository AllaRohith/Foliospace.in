CREATE TABLE IF NOT EXISTS social_accounts (
    provider        TEXT        NOT NULL,
    provider_uid    TEXT        NOT NULL,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, provider_uid)
);

CREATE INDEX IF NOT EXISTS social_accounts_user_idx
    ON social_accounts (user_id);

CREATE INDEX IF NOT EXISTS social_accounts_email_idx
    ON social_accounts (email);