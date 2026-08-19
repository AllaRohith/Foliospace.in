ALTER TABLE users
    ADD COLUMN IF NOT EXISTS avatar_public_id TEXT;
