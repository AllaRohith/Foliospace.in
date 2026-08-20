ALTER TABLE users ADD COLUMN IF NOT EXISTS is_listed BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS users_is_listed_idx ON users (is_listed, category)
    WHERE deleted_at IS NULL AND is_listed = TRUE;
