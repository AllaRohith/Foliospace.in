ALTER TABLE social_accounts
    ADD COLUMN IF NOT EXISTS access_token   TEXT,
    ADD COLUMN IF NOT EXISTS refresh_token  TEXT,
    ADD COLUMN IF NOT EXISTS expires_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS scope          TEXT,
    ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS imported_repos (
    user_id          UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id          BIGINT      NOT NULL,
    name             TEXT        NOT NULL,
    full_name        TEXT        NOT NULL,
    html_url         TEXT        NOT NULL,
    description      TEXT,
    language         TEXT,
    stargazers_count INTEGER     NOT NULL DEFAULT 0,
    fork             BOOLEAN     NOT NULL DEFAULT FALSE,
    is_pinned        BOOLEAN     NOT NULL DEFAULT FALSE,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, repo_id)
);

CREATE INDEX IF NOT EXISTS imported_repos_user_idx
    ON imported_repos (user_id);

CREATE TABLE IF NOT EXISTS imported_contributions (
    user_id    UUID    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day        DATE    NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    level      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS imported_profile (
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider   TEXT        NOT NULL,
    payload    JSONB       NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, provider)
);
