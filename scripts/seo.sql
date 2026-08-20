ALTER TABLE users
  ADD COLUMN IF NOT EXISTS seo_title             TEXT,
  ADD COLUMN IF NOT EXISTS seo_description       TEXT,
  ADD COLUMN IF NOT EXISTS og_image_override_url TEXT;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_og_image_override_url_check;
ALTER TABLE users
  ADD CONSTRAINT users_og_image_override_url_check
  CHECK (og_image_override_url IS NULL OR og_image_override_url ~* '^https://res\.cloudinary\.com/');