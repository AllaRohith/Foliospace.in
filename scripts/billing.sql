ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan                 TEXT NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS plan_expires_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS setup_paid_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS razorpay_customer_id TEXT,
    ADD COLUMN IF NOT EXISTS payment_failed_at    TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_plan_chk'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_plan_chk
            CHECK (plan IN ('free', 'pro'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    razorpay_subscription_id TEXT NOT NULL UNIQUE,
    razorpay_plan_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    short_url TEXT,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_event_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS user_subscriptions_user_id_idx
    ON user_subscriptions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES user_subscriptions(id) ON DELETE SET NULL,
    razorpay_payment_id TEXT NOT NULL UNIQUE,
    razorpay_order_id   TEXT,
    razorpay_invoice_id TEXT,
    invoice_url         TEXT,
    amount_paise        INTEGER NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'INR',
    status              TEXT NOT NULL,
    method              TEXT,
    vpa_suffix          TEXT,
    description         TEXT,
    kind                TEXT NOT NULL,
    billing_period_start TIMESTAMPTZ,
    billing_period_end   TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_event JSONB
);
CREATE INDEX IF NOT EXISTS payments_user_id_paid_at_idx
    ON payments(user_id, paid_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    error TEXT
);