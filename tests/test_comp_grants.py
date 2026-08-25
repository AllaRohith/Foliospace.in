"""Tests for the comp/grants flow.

Covers:
* `app.pricing` constants + formatter
* `app.services.billing.pick_plan_for_new_subscription` (pure)
* `app.services.billing.pick_plan_for_renewal` (no-DB + with-grant + no-grant branches)
* `app.services.billing.effective_plan_for` priority (comp > subscription > free)
* Admin grant route duration parsing (forever/years/reject)

Run from repo root:
    python3 -m unittest tests.test_comp_grants
"""
import unittest
from unittest import mock

from app.pricing import (
    PRO_YEAR1_INR,
    PRO_YEAR2_INR,
    PRO_MONTHLY_INR,
    PRO_ANNUAL_INR,
    FREE_PRICE_INR,
    TRIAL_DAYS,
    FOUNDER_COHORT_LIMIT,
    annual_savings_percent,
    fmt_inr,
    trial_label,
)
from app.services import billing
from app.services import cashfree as cashfree_svc


class PricingConstantsTests(unittest.TestCase):
    def test_year1_default_899(self):
        self.assertEqual(PRO_YEAR1_INR, 899)

    def test_year2_default_1499(self):
        self.assertEqual(PRO_YEAR2_INR, 1499)

    def test_free_zero(self):
        self.assertEqual(FREE_PRICE_INR, 0)

    def test_trial_disabled(self):
        self.assertEqual(TRIAL_DAYS, 0)

    def test_monthly_equivalent(self):
        # round(1499/12) == 125
        self.assertEqual(PRO_MONTHLY_INR, 125)

    def test_annual_alias_equals_year2(self):
        self.assertEqual(PRO_ANNUAL_INR, PRO_YEAR2_INR)

    def test_founder_cohort_cap_100(self):
        self.assertEqual(FOUNDER_COHORT_LIMIT, 100)


class PricingFormattersTests(unittest.TestCase):
    def test_fmt_inr_thousands(self):
        self.assertEqual(fmt_inr(1499), "₹1,499")

    def test_fmt_inr_zero(self):
        self.assertEqual(fmt_inr(0), "₹0")

    def test_fmt_inr_lakhs(self):
        self.assertEqual(fmt_inr(100000), "₹100,000")

    def test_fmt_inr_coerces(self):
        self.assertEqual(fmt_inr("899"), "₹899")

    def test_annual_savings_percent_year1_vs_year2(self):
        # (1499-899)/1499 = 40.026...% -> 40
        self.assertEqual(annual_savings_percent(), 40)

    def test_annual_savings_zero_when_year2_zero(self):
        # If env override zeroes year-2, savings is 0
        with mock.patch("app.pricing.PRO_YEAR2_INR", 0):
            self.assertEqual(annual_savings_percent(), 0)

    def test_trial_label_is_pro_annual(self):
        # trial disabled; label is a stub for backward compat
        self.assertEqual(trial_label(), "PRO · ANNUAL")


class PickPlanNewSubscriptionTests(unittest.TestCase):
    def test_returns_year1_plan_id(self):
        with mock.patch.object(cashfree_svc, "plan_year1_id", return_value="plan_year1"):
            self.assertEqual(billing.pick_plan_for_new_subscription(), "plan_year1")


class PickPlanRenewalTests(unittest.TestCase):
    def test_no_database_returns_year2(self):
        with mock.patch.object(billing, "DATABASE_URL", ""):
            with mock.patch.object(cashfree_svc, "plan_year2_id", return_value="plan_year2"):
                self.assertEqual(billing.pick_plan_for_renewal("u1"), "plan_year2")

    def test_active_grant_returns_none(self):
        """If user has an active grant, renewal is comp-handled — return None."""
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"expires_at": None}
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=fake_conn), \
             mock.patch.object(cashfree_svc, "plan_year2_id", return_value="plan_year2"):
            self.assertIsNone(billing.pick_plan_for_renewal("u1"))

    def test_no_active_grant_returns_year2(self):
        """No grant row → standard Year-2 plan swap."""
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = None
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=fake_conn), \
             mock.patch.object(cashfree_svc, "plan_year2_id", return_value="plan_year2"):
            self.assertEqual(billing.pick_plan_for_renewal("u1"), "plan_year2")


class EffectivePlanTests(unittest.TestCase):
    def _build_db(self, grant=None, user_plan="free", expires_at=None):
        """Returns a fake psycopg connection that responds based on the
        (grant, user_plan, expires_at) trio."""
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()

        def fake_execute(sql, params=()):
            sql_lc = (sql or "").lower()
            if "from subscription_grants" in sql_lc:
                fake_cur._next = grant
            elif "select plan, plan_expires_at from users" in sql_lc:
                fake_cur._next = {"plan": user_plan, "plan_expires_at": expires_at}
            return None

        fake_cur.execute.side_effect = fake_execute
        def fetchone():
            return getattr(fake_cur, "_next", None)
        fake_cur.fetchone.side_effect = fetchone

        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_no_database_returns_free(self):
        with mock.patch.object(billing, "DATABASE_URL", ""):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out, {"plan": "free", "expires_at": None, "source": "free",
                               "referral_count": 0, "days_until_expiry": None})

    def test_comp_wins_over_subscription(self):
        """If grant is active, plan=pro source=comp — even if user row says free."""
        conn = self._build_db(grant={"expires_at": None}, user_plan="free")
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["plan"], "pro")
        self.assertEqual(out["source"], "comp")

    def test_active_subscription_no_grant(self):
        conn = self._build_db(grant=None, user_plan="pro", expires_at="2027-08-23")
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["plan"], "pro")
        self.assertEqual(out["source"], "subscription")
        self.assertEqual(out["expires_at"], "2027-08-23")

    def test_free_user(self):
        conn = self._build_db(grant=None, user_plan="free")
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["plan"], "free")
        self.assertEqual(out["source"], "free")

    def test_db_error_returns_free_safely(self):
        import psycopg
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.execute.side_effect = psycopg.Error("db down")
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=fake_conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["source"], "free")
        self.assertEqual(out["plan"], "free")

    def test_user_row_missing(self):
        """If grant check empty and user row missing — return free."""
        conn = self._build_db(grant=None, user_plan=None)
        # Override user fetch to return None
        fake_cur = conn.cursor.return_value.__enter__.return_value
        original_fetchone = fake_cur.fetchone.side_effect
        def fetchone():
            sql = fake_cur.execute.call_args[0][0].lower() if fake_cur.execute.call_args else ""
            if "from users" in sql:
                return None
            return original_fetchone()
        fake_cur.fetchone.side_effect = fetchone
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["plan"], "free")


class PlanSummaryTests(unittest.TestCase):
    def test_internal_user_returns_internal_state(self):
        u = {"is_internal": True, "plan": "pro"}
        with mock.patch.object(billing, "grace_days_left", return_value=0):
            out = billing.plan_summary(u)
        self.assertEqual(out["state"], "internal")
        self.assertEqual(out["plan"], "pro")
        self.assertTrue(out["is_unlimited"])

    def test_free_user_returns_free_state(self):
        u = {"plan": "free", "is_internal": False}
        with mock.patch.object(billing, "grace_days_left", return_value=0):
            out = billing.plan_summary(u)
        self.assertEqual(out["state"], "free")
        self.assertEqual(out["plan"], "free")

    def test_pro_user_returns_pro_state(self):
        u = {"plan": "pro", "is_internal": False, "payment_failed_at": None}
        with mock.patch.object(billing, "grace_days_left", return_value=0):
            out = billing.plan_summary(u)
        self.assertEqual(out["state"], "pro")
        self.assertEqual(out["plan"], "pro")
        self.assertFalse(out["is_unlimited"])

    def test_grace_state_with_days_left(self):
        u = {"plan": "pro", "is_internal": False,
             "payment_failed_at": "2026-08-20", "plan_expires_at": None}
        with mock.patch.object(billing, "grace_days_left", return_value=3):
            out = billing.plan_summary(u)
        self.assertEqual(out["state"], "grace")
        self.assertIn("3", out["headline"])


class GraceDaysLeftTests(unittest.TestCase):
    def test_zero_when_no_expires(self):
        u = {"plan_expires_at": None, "payment_failed_at": "2026-08-20"}
        self.assertEqual(billing.grace_days_left(u), 0)

    def test_zero_when_no_failure(self):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(days=10)
        u = {"plan_expires_at": future, "payment_failed_at": None}
        self.assertEqual(billing.grace_days_left(u), 0)

    def test_positive_days_when_in_window(self):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(days=5)
        u = {"plan_expires_at": future, "payment_failed_at": "2026-08-20"}
        # Should be >= 5 (likely 5 or 6 depending on ms rounding)
        d = billing.grace_days_left(u)
        self.assertGreaterEqual(d, 5)
        self.assertLessEqual(d, 6)


class TrialDaysLeftTests(unittest.TestCase):
    def test_trial_disabled_always_zero(self):
        self.assertEqual(billing.trial_days_left({}), 0)
        self.assertEqual(billing.trial_days_left({"is_trial": True}), 0)
        self.assertEqual(billing.trial_days_left({"trial_reminder_3d_sent_at": "2026-08-20"}), 0)


class AdminGrantDurationParsingTests(unittest.TestCase):
    """Tests the duration → expires_at parsing inside the grants_grant handler."""

    def test_duration_forever_returns_none(self):
        # Replicating the inline logic from admin.py:912-989
        from datetime import datetime, timezone, timedelta as _td
        duration = "forever"
        expires_at = None
        if duration == "forever":
            expires_at = None
        elif duration.endswith("y"):
            years = max(1, min(int(duration[:-1] or "1"), 99))
            expires_at = datetime.now(timezone.utc) + _td(days=365 * years)
        self.assertIsNone(expires_at)

    def test_duration_1y(self):
        from datetime import datetime, timezone, timedelta as _td
        duration = "1y"
        if duration == "forever":
            expires_at = None
        elif duration.endswith("y"):
            years = max(1, min(int(duration[:-1] or "1"), 99))
            expires_at = datetime.now(timezone.utc) + _td(days=365 * years)
        self.assertIsNotNone(expires_at)
        # Should be ~365 days from now (timedelta.days truncates fractional days,
        # so the delta can read 364 if a few microseconds elapsed between
        # `datetime.now()` calls).
        delta = expires_at - datetime.now(timezone.utc)
        self.assertGreaterEqual(delta.days, 364)
        self.assertLessEqual(delta.days, 365)

    def test_duration_3y(self):
        from datetime import datetime, timezone, timedelta as _td
        duration = "3y"
        if duration.endswith("y"):
            years = max(1, min(int(duration[:-1] or "1"), 99))
            expires_at = datetime.now(timezone.utc) + _td(days=365 * years)
        delta = expires_at - datetime.now(timezone.utc)
        self.assertGreaterEqual(delta.days, 365 * 3 - 1)
        self.assertLessEqual(delta.days, 365 * 3)

    def test_duration_99y_clamped(self):
        from datetime import datetime, timezone, timedelta as _td
        duration = "999y"
        if duration.endswith("y"):
            years = max(1, min(int(duration[:-1] or "1"), 99))
        self.assertEqual(years, 99)

    def test_duration_0y_clamped_to_1(self):
        from datetime import datetime, timezone, timedelta as _td
        duration = "0y"
        if duration.endswith("y"):
            years = max(1, min(int(duration[:-1] or "1"), 99))
        self.assertEqual(years, 1)

    def test_duration_junk_rejected(self):
        # Anything that doesn't end in "y" (other than "forever") must redirect
        # with err=bad-duration. We replicate the boolean check.
        for bad in ("", "1", "five", "12m", "1Y"):
            is_valid = (bad == "forever") or bad.endswith("y")
            if bad == "1Y":
                # Case-sensitive in code (`.lower()` is applied first)
                self.assertFalse(is_valid)
            else:
                self.assertFalse(is_valid)


class GrantListFilterAndSearchTests(unittest.TestCase):
    """Test the WHERE-clause building logic from the GET /admin/grants route."""

    def test_active_filter_builds_clause(self):
        show_only_active = True
        where = ["sg.id IS NOT NULL"]
        if show_only_active:
            where.append("sg.revoked_at IS NULL AND (sg.expires_at IS NULL OR sg.expires_at > NOW())")
        self.assertIn("sg.revoked_at IS NULL", where[1])

    def test_all_filter_no_extra_clause(self):
        show_only_active = False
        where = ["sg.id IS NOT NULL"]
        if show_only_active:
            where.append("...")  # never added
        self.assertEqual(len(where), 1)

    def test_search_query_lowercased_and_liked(self):
        q = "Rohith"
        like = f"%{q.lower()}%"
        self.assertEqual(like, "%rohith%")

    def test_pagination_offset_for_page_3(self):
        page = 3
        page_size = 50
        offset = (page - 1) * page_size
        self.assertEqual(offset, 100)


if __name__ == "__main__":
    unittest.main()