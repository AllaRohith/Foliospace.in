ALTER TABLE users
  ADD COLUMN IF NOT EXISTS spotlight_kind   TEXT,
  ADD COLUMN IF NOT EXISTS spotlight_ref_id TEXT,
  ADD COLUMN IF NOT EXISTS spotlight_text   TEXT,
  ADD COLUMN IF NOT EXISTS spotlight_url    TEXT,
  ADD COLUMN IF NOT EXISTS spotlight_emoji  TEXT;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_spotlight_url_check;
ALTER TABLE users
  ADD CONSTRAINT users_spotlight_url_check
  CHECK (spotlight_url IS NULL OR spotlight_url ~* '^https?://');