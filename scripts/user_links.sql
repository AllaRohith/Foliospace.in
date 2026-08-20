CREATE TABLE IF NOT EXISTS user_links (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    url         TEXT NOT NULL,
    icon        TEXT NOT NULL DEFAULT 'link',
    layout      TEXT NOT NULL DEFAULT 'stack'
                CHECK (layout IN ('stack','grid','carousel')),
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_links_user_id_pos_idx ON user_links(user_id, position);
