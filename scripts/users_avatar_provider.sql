ALTER TABLE users
    ADD COLUMN IF NOT EXISTS avatar_provider TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_avatar_provider_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_avatar_provider_chk
            CHECK (avatar_provider IS NULL OR avatar_provider IN
                ('cloudinary', 'linkedin', 'gravatar', 'manual'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS users_avatar_provider_idx
    ON users (avatar_provider) WHERE avatar_provider IS NOT NULL;