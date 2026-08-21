-- users_work_rail.sql
-- Adds an editable JSONB list of {title, body} rows for the public
-- "What I do" section on /<slug>. Order is insertion order.
-- Default is an empty array. Cap payload to ~64 KB so a giant form
-- post can't bloat a user row.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS work_rail JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_work_rail_size_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_work_rail_size_chk
            CHECK (octet_length(work_rail::text) <= 65536);
    END IF;
END $$;