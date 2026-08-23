-- Phase B: Razorpay -> Cashfree migration. Fresh cutover (no live Razorpay subs).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'cashfree_customer_id'
    ) THEN
        ALTER TABLE users RENAME COLUMN razorpay_customer_id TO cashfree_customer_id;
    END IF;
END $$;

ALTER TABLE users DROP COLUMN IF EXISTS setup_paid_at;

-- Clear trial/ reminder state ONLY if the columns exist. (Some Neon DBs
-- already migrated past trial — those tables don't have these columns
-- at all, and the unconditional UPDATE crashed with `column "is_trial"
-- does not exist`.)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'is_trial'
    ) THEN
        UPDATE users
           SET is_trial = FALSE, payment_failed_at = NULL,
               trial_reminder_7d_sent_at = NULL,
               trial_reminder_4d_sent_at = NULL,
               trial_reminder_2d_sent_at = NULL
         WHERE deleted_at IS NULL AND plan = 'free';
    END IF;
END $$;

ALTER TABLE users DROP COLUMN IF EXISTS is_trial;
ALTER TABLE users DROP COLUMN IF EXISTS trial_reminder_7d_sent_at;
ALTER TABLE users DROP COLUMN IF EXISTS trial_reminder_4d_sent_at;
ALTER TABLE users DROP COLUMN IF EXISTS trial_reminder_2d_sent_at;

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cashfree_subscription_id TEXT UNIQUE,
    cashfree_plan_id TEXT,
    original_plan_id TEXT,
    status TEXT,
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    short_url TEXT,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_event_at TIMESTAMPTZ,
    payment_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    discount_applied_until DATE
);
CREATE INDEX IF NOT EXISTS user_subscriptions_user_id_idx
    ON user_subscriptions(user_id, created_at DESC);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'user_subscriptions'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'user_subscriptions' AND column_name = 'razorpay_subscription_id'
    ) THEN
        ALTER TABLE user_subscriptions
            DROP COLUMN razorpay_subscription_id,
            DROP COLUMN razorpay_plan_id;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES user_subscriptions(id) ON DELETE SET NULL,
    cashfree_payment_id TEXT UNIQUE,
    cashfree_invoice_id TEXT,
    invoice_url         TEXT,
    amount_paise        INTEGER NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'INR',
    status              TEXT NOT NULL,
    method              TEXT,
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

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'payments' AND column_name = 'razorpay_payment_id'
    ) THEN
        ALTER TABLE payments DROP COLUMN razorpay_payment_id;
        ALTER TABLE payments DROP COLUMN razorpay_order_id;
        ALTER TABLE payments DROP COLUMN razorpay_invoice_id;
        ALTER TABLE payments DROP COLUMN vpa_suffix;
    END IF;
END $$;
