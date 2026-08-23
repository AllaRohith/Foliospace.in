-- Phase C: Referral program.
--
-- Threshold: 10 successful referrals -> Year-1 plan stays locked at renewal.
-- "Successful" = referee has signed up via /ref/{code}, verified email,
-- AND published their folio (is_public=TRUE). Tier does not matter.
-- Reward is permanent — no downgrade path.
--
-- Run on Neon BEFORE the Phase C deploy hits prod.

-- 1. Add referral columns to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS referral_code TEXT,
    ADD COLUMN IF NOT EXISTS referred_by  UUID REFERENCES users(id) ON DELETE SET NULL;

-- 2. Backfill existing users with random codes (14-char hex from 7 bytes).
-- gen_random_bytes needs pgcrypto — already enabled in users_init_db.sql.
UPDATE users
   SET referral_code = encode(gen_random_bytes(7), 'hex')
 WHERE referral_code IS NULL;

-- 3. Enforce NOT NULL + UNIQUE.
-- The constraint is created via a DO block so re-running this script is safe.
ALTER TABLE users ALTER COLUMN referral_code SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'users_referral_code_uniq'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_referral_code_uniq UNIQUE (referral_code);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS users_referred_by_idx ON users (referred_by);

-- 4. Referrals table. UNIQUE(referee_id) so each user can be referred once.
--    ON CONFLICT in app/services/referrals.py handles the race.
CREATE TABLE IF NOT EXISTS referrals (
    id              BIGSERIAL PRIMARY KEY,
    referrer_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referee_id      UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    referral_code   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'verified', 'active', 'revoked')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at     TIMESTAMPTZ,        -- set on email_verified → verified
    activated_at    TIMESTAMPTZ          -- set on is_public=TRUE → active
);

-- 5. Hot-path partial index: cron + dashboard count only care about 'active'.
CREATE INDEX IF NOT EXISTS referrals_active_count_idx
    ON referrals (referrer_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS referrals_referrer_idx ON referrals (referrer_id);

-- 6. View for the cron evaluator — one row per referrer with their count.
CREATE OR REPLACE VIEW v_referral_counts AS
SELECT referrer_id, COUNT(*) FILTER (WHERE status = 'active') AS active_count
  FROM referrals
 GROUP BY referrer_id;
