ALTER TABLE users
    ADD COLUMN IF NOT EXISTS headline    TEXT,
    ADD COLUMN IF NOT EXISTS locale      TEXT,
    ADD COLUMN IF NOT EXISTS zoneinfo    TEXT,
    ADD COLUMN IF NOT EXISTS profile_url TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_locale_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_locale_chk
            CHECK (locale IS NULL OR locale ~ '^[A-Za-z]{2,3}(_[A-Z]{2})?$');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_zoneinfo_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_zoneinfo_chk
            CHECK (zoneinfo IS NULL OR zoneinfo ~ '^[A-Za-z]+(/[A-Za-z_]+)*$');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_profile_url_scheme_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_profile_url_scheme_chk
            CHECK (profile_url IS NULL OR profile_url ~* '^https?://');
    END IF;
END $$;