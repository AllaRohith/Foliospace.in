ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS users_is_public_idx
    ON users (is_public, created_at DESC)
    WHERE deleted_at IS NULL;
