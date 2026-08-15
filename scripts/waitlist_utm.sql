ALTER TABLE waitlist
    ADD COLUMN IF NOT EXISTS utm_source   TEXT,
    ADD COLUMN IF NOT EXISTS utm_medium   TEXT,
    ADD COLUMN IF NOT EXISTS utm_campaign TEXT,
    ADD COLUMN IF NOT EXISTS referer      TEXT;

CREATE INDEX IF NOT EXISTS waitlist_utm_source_idx
    ON waitlist (utm_source)
 WHERE utm_source IS NOT NULL;
