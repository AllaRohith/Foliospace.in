ALTER TABLE users
    ADD COLUMN IF NOT EXISTS bio        TEXT,
    ADD COLUMN IF NOT EXISTS phone      TEXT,
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_phone_format_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_phone_format_chk
            CHECK (phone IS NULL OR phone ~ '^[+0-9 ()\-]{6,20}$');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_avatar_url_scheme_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_avatar_url_scheme_chk
            CHECK (avatar_url IS NULL OR avatar_url ~* '^https?://');
    END IF;
END $$;