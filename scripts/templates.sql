ALTER TABLE users
    ADD COLUMN IF NOT EXISTS template_id TEXT NOT NULL DEFAULT 't1';

CREATE TABLE IF NOT EXISTS admin_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT
);

INSERT INTO admin_settings (key, value, updated_at)
VALUES (
    'templates',
    jsonb_build_array(
        jsonb_build_object(
            'id', 't1',
            'name', 'Editorial',
            'description', 'Cream editorial spread with proof rail, what-I-do grid, and WhatsApp CTA.',
            'is_visible', true,
            'is_default', true,
            'is_pro_only', false,
            'thumb', 't1.svg',
            'sort', 1
        )
    )::jsonb,
    now()
)
ON CONFLICT (key) DO NOTHING;