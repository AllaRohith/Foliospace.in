"""Tests for `app.services.billing` additions (comp_status + comp-revoke
on subscription activation) and the days_until_expiry computation
in `effective_plan_for`.

Run from repo root:
    python3 -m unittest tests.test_billing
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.services import billing


def _future(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class _FakeCursor:
    def __init__(self, fetchone_rows=None, rowcounts=None):
        self._fetchone_rows = list(fetchone_rows or [])
        self._rowcounts = list(rowcounts or [])
        self.executed = []
        self.rowcount = 0

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)
        else:
            self.rowcount = 1

    def fetchone(self):
        if self._fetchone_rows:
            return self._fetchone_rows.pop(0)
        return None

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, cur):
        self.cur = cur
        self.committed = False
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self):
        return self.cur
    def commit(self): self.committed = True


class DaysUntilExpiryTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(billing._days_until(None))

    def test_future_returns_positive_days(self):
        out = billing._days_until(_future(7))
        self.assertGreaterEqual(out, 6)
        self.assertLessEqual(out, 7)

    def test_past_returns_zero(self):
        self.assertEqual(billing._days_until(_past(3)), 0)

    def test_naive_datetime_treated_as_utc(self):
        naive = (datetime.now(timezone.utc) + timedelta(days=5)).replace(tzinfo=None)
        self.assertGreaterEqual(billing._days_until(naive), 4)


class CompStatusTests(unittest.TestCase):
    def test_no_db_returns_none(self):
        with mock.patch.object(billing, "DATABASE_URL", ""):
            self.assertIsNone(billing.comp_status("u1"))

    def test_no_grant_returns_none(self):
        cur = _FakeCursor(fetchone_rows=[None])
        conn = _FakeConn(cur)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            self.assertIsNone(billing.comp_status("u1"))

    def test_forever_grant_returns_none(self):
        cur = _FakeCursor(fetchone_rows=[{"grant_id": 1, "expires_at": None}])
        conn = _FakeConn(cur)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            self.assertIsNone(billing.comp_status("u1"))

    def test_active_grant_returns_dict_with_days(self):
        cur = _FakeCursor(fetchone_rows=[{
            "grant_id": 7, "expires_at": _future(12),
        }])
        conn = _FakeConn(cur)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.comp_status("u1")
        self.assertIsNotNone(out)
        self.assertEqual(out["grant_id"], 7)
        self.assertGreaterEqual(out["days_until_expiry"], 11)
        self.assertLessEqual(out["days_until_expiry"], 12)


class EffectivePlanDaysUntilTests(unittest.TestCase):
    def _build_db(self, grant=None, user_plan="free", expires_at=None):
        cur = mock.MagicMock()

        def fake_execute(sql, params=()):
            sql_lc = (sql or "").lower()
            if "from subscription_grants" in sql_lc:
                cur._next = grant
            elif "select plan, plan_expires_at from users" in sql_lc:
                cur._next = {"plan": user_plan, "plan_expires_at": expires_at}
            return None

        cur.execute.side_effect = fake_execute
        def fetchone():
            return getattr(cur, "_next", None)
        cur.fetchone.side_effect = fetchone
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        conn.cursor.return_value.__enter__.return_value = cur
        conn.cursor.return_value.__exit__.return_value = False
        return conn

    def test_comp_grant_returns_days_until_expiry(self):
        conn = self._build_db(grant={"expires_at": _future(7)})
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["source"], "comp")
        self.assertGreaterEqual(out["days_until_expiry"], 6)
        self.assertLessEqual(out["days_until_expiry"], 7)

    def test_paid_subscription_returns_days_until_expiry(self):
        conn = self._build_db(grant=None, user_plan="pro", expires_at=_future(30))
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["source"], "subscription")
        self.assertGreaterEqual(out["days_until_expiry"], 29)

    def test_forever_comp_returns_none_for_days(self):
        conn = self._build_db(grant={"expires_at": None})
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["source"], "comp")
        self.assertIsNone(out["days_until_expiry"])

    def test_free_user_returns_none_for_days(self):
        conn = self._build_db(grant=None, user_plan="free")
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.effective_plan_for("u1")
        self.assertEqual(out["source"], "free")
        self.assertIsNone(out["days_until_expiry"])


class SubscriptionActivatedRevokesCompTests(unittest.TestCase):
    def test_comp_revoke_sql_issued_with_correct_reason(self):
        cur = _FakeCursor()
        with mock.patch.object(billing, "_connect", return_value=_FakeConn(cur)):
            payload = {
                "data": {"object": {
                    "cf_subscription_id": "cf_sub_1",
                    "plan_id": "plan_year1",
                    "subscription_status": "active",
                    "subscription_tags": {"user_id": "u-1"},
                }}
            }
            billing._on_subscription_activated(cur, payload)
        sqls = [s for s, _ in cur.executed]
        revoke_sqls = [s for s in sqls if "UPDATE subscription_grants" in s]
        self.assertEqual(len(revoke_sqls), 1)
        revoke_sql = revoke_sqls[0]
        self.assertIn("revoked_at = NOW()", revoke_sql)
        self.assertIn("revoke_reason = 'user_activated_subscription'", revoke_sql)
        self.assertIn("revoked_at IS NULL", revoke_sql)
        revoke_params = [p for s, p in cur.executed if s == revoke_sql][0]
        self.assertEqual(revoke_params, ("u-1",))


if __name__ == "__main__":
    unittest.main()