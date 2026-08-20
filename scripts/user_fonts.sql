CREATE TABLE IF NOT EXISTS user_fonts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    font_name      TEXT NOT NULL,
    file_url       TEXT NOT NULL,
    file_public_id TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, file_public_id)
);
CREATE INDEX IF NOT EXISTS user_fonts_user_id_idx ON user_fonts(user_id);
CREATE INDEX IF NOT EXISTS user_fonts_status_idx ON user_fonts(status);