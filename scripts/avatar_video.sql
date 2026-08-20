ALTER TABLE users
  ADD COLUMN IF NOT EXISTS avatar_video_url       TEXT,
  ADD COLUMN IF NOT EXISTS avatar_video_public_id TEXT,
  ADD COLUMN IF NOT EXISTS avatar_video_kind      TEXT;

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_avatar_video_url_check;
ALTER TABLE users
  ADD CONSTRAINT users_avatar_video_url_check
  CHECK (avatar_video_url IS NULL OR avatar_video_url ~* '^https?://');