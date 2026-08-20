ALTER TABLE users
    ADD COLUMN IF NOT EXISTS linkedin_url TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_linkedin_url_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_linkedin_url_chk
            CHECK (linkedin_url IS NULL
                   OR linkedin_url ~* '^https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_\-]+/?$');
    END IF;
END $$;
