"""Tests for `app.jobs.comp_grant_expirer`.

Covers:
* Preflight failure (missing TRUST_TOKEN / DATABASE_URL) → exit 2
* Three-stage warning sweep (14d / 7d / 1d): finds row, sends email, marks sent_at
* Already-sent dedupe: row skipped when warn_Nd_sent_at IS NOT NULL
* Flip-expired sweep: flips users.plan='free' when no other active grant
* Flip guard: NOT EXISTS against active subscription keeps user on Pro
* Email service exceptions are caught, don't crash the cron

Run from repo root:
    python3 -m unittest tests.test_comp_grant_expirer
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.jobs import comp_grant_expirer


class _FakeCursor:
    def __init__(self, rows=None, rowcounts=None, fetchone_rows=None):
        self._fetchall_rows = list(rows or [])
        self._rowcounts = list(rowcounts or [])
        self._fetchone_rows = list(fetchone_rows or [])
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
        if self._fetchall_rows:
            return self._fetchall_rows.pop(0)
        return []


class _FakeConn:
    def __init__(self, cursors=None):
        self._cursors = list(cursors or [_FakeCursor()])
        self.committed = False
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self):
        if len(self._cursors) == 1:
            return self._cursors[0]
        return self._cursors.pop(0)
    def commit(self): self.committed = True


def _make_conn(cursors=None):
    return _FakeConn(cursors or [_FakeCursor()])


def _future(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class PreflightTests(unittest.TestCase):
    def test_missing_token_returns_2(self):
        with mock.patch.object(comp_grant_expirer, "TRUST_TOKEN", ""), \
             mock.patch.object(comp_grant_expirer, "DATABASE_URL", "postgres://x"):
            self.assertEqual(comp_grant_expirer.main(), 2)

    def test_missing_db_returns_2(self):
        with mock.patch.object(comp_grant_expirer, "TRUST_TOKEN", "tok"), \
             mock.patch.object(comp_grant_expirer, "DATABASE_URL", ""):
            self.assertEqual(comp_grant_expirer.main(), 2)


class WarningSweepTests(unittest.TestCase):
    def _patch_env(self):
        return (
            mock.patch.object(comp_grant_expirer, "TRUST_TOKEN", "tok"),
            mock.patch.object(comp_grant_expirer, "DATABASE_URL", "postgres://x"),
        )

    def test_14d_sweep_sends_email_and_marks_sent(self):
        grant_id = 99
        cur_select = _FakeCursor(rows=[[{
            "grant_id": grant_id,
            "user_id": "u-1",
            "expires_at": _future(14),
            "email": "x@example.com",
            "slug": "x",
        }]])
        cur_update = _FakeCursor()
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn), \
             mock.patch(
                 "app.services.email_service.send_comp_expiry_warning_email",
                 return_value=(True, "msg-1"),
             ) as send:
            sent, _dedup, failed = comp_grant_expirer._run_warning_sweep(conn, 14)
        self.assertEqual(sent, 1)
        self.assertEqual(failed, 0)
        send.assert_called_once()
        called = send.call_args.kwargs
        self.assertEqual(called["days_left"], 14)
        self.assertEqual(called["to_email"], "x@example.com")
        # The second cursor handled the UPDATE that marks warn_14d_sent_at
        self.assertTrue(any(
            "warn_14d_sent_at = NOW()" in sql for sql, _ in cur_update.executed
        ))

    def test_7d_sweep_marks_correct_column(self):
        cur_select = _FakeCursor(rows=[[{
            "grant_id": 7, "user_id": "u", "expires_at": _future(7),
            "email": "a@b.com", "slug": "a",
        }]])
        cur_update = _FakeCursor()
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn), \
             mock.patch(
                 "app.services.email_service.send_comp_expiry_warning_email",
                 return_value=(True, "ok"),
             ):
            comp_grant_expirer._run_warning_sweep(conn, 7)
        self.assertTrue(any(
            "warn_7d_sent_at = NOW()" in sql for sql, _ in cur_update.executed
        ))

    def test_1d_sweep_marks_correct_column(self):
        cur_select = _FakeCursor(rows=[[{
            "grant_id": 1, "user_id": "u", "expires_at": _future(1),
            "email": "a@b.com", "slug": "a",
        }]])
        cur_update = _FakeCursor()
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn), \
             mock.patch(
                 "app.services.email_service.send_comp_expiry_warning_email",
                 return_value=(True, "ok"),
             ):
            comp_grant_expirer._run_warning_sweep(conn, 1)
        self.assertTrue(any(
            "warn_1d_sent_at = NOW()" in sql for sql, _ in cur_update.executed
        ))

    def test_no_targets_returns_zero(self):
        cur = _FakeCursor(rows=[[]])
        conn = _make_conn([cur])
        with mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            sent, dedup, failed = comp_grant_expirer._run_warning_sweep(conn, 14)
        self.assertEqual((sent, dedup, failed), (0, 0, 0))

    def test_send_failure_counted(self):
        cur_select = _FakeCursor(rows=[[{
            "grant_id": 1, "user_id": "u", "expires_at": _future(14),
            "email": "x@y.com", "slug": "x",
        }]])
        cur_update = _FakeCursor()
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn), \
             mock.patch(
                 "app.services.email_service.send_comp_expiry_warning_email",
                 return_value=(False, "no_api_key"),
             ):
            sent, dedup, failed = comp_grant_expirer._run_warning_sweep(conn, 14)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 1)
        self.assertFalse(any("warn_14d_sent_at" in sql for sql, _ in cur_update.executed))


class FlipSweepTests(unittest.TestCase):
    def _patch_env(self):
        return (
            mock.patch.object(comp_grant_expirer, "TRUST_TOKEN", "tok"),
            mock.patch.object(comp_grant_expirer, "DATABASE_URL", "postgres://x"),
        )

    def test_flip_expired_user_to_free(self):
        cur_select = _FakeCursor(rows=[[{"user_id": "u-1", "grant_id": 99}]])
        cur_update = _FakeCursor(rowcounts=[1])
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            flipped, guarded = comp_grant_expirer._run_flip_sweep(conn)
        self.assertEqual(flipped, 1)
        self.assertEqual(guarded, 0)
        update_sql, update_params = cur_update.executed[0]
        self.assertIn("UPDATE users", update_sql)
        self.assertIn("plan = 'free'", update_sql)
        self.assertEqual(update_params, ("u-1",))

    def test_no_targets_returns_zero(self):
        cur = _FakeCursor(rows=[[]])
        conn = _make_conn([cur])
        with mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            flipped, guarded = comp_grant_expirer._run_flip_sweep(conn)
        self.assertEqual((flipped, guarded), (0, 0))

    def test_flip_query_excludes_other_active_grant(self):
        """Defensive check — the SQL must NOT EXISTS against subscription_grants."""
        cur_select = _FakeCursor(rows=[[]])
        conn = _make_conn([cur_select])
        with mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            comp_grant_expirer._find_expired_targets(conn)
        sql, _ = cur_select.executed[0]
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("subscription_grants sg2", sql)
        self.assertIn("user_subscriptions s", sql)
        self.assertIn("status IN ('active', 'authenticated')", sql)
        self.assertIn("current_period_end > NOW()", sql)

    def test_rowcount_zero_is_guarded_not_flipped(self):
        """User rowcount=0 (already free) — counted as guarded, not flipped."""
        cur_select = _FakeCursor(rows=[[{"user_id": "u-1", "grant_id": 99}]])
        cur_update = _FakeCursor(rowcounts=[0])
        conn = _make_conn([cur_select, cur_update])
        with self._patch_env()[0], self._patch_env()[1], \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            flipped, guarded = comp_grant_expirer._run_flip_sweep(conn)
        self.assertEqual(flipped, 0)
        self.assertEqual(guarded, 1)


class MainHappyPathTests(unittest.TestCase):
    def test_main_returns_0_with_no_targets(self):
        cur = _FakeCursor(rows=[[]])
        conn = _make_conn([cur])
        with mock.patch.object(comp_grant_expirer, "TRUST_TOKEN", "tok"), \
             mock.patch.object(comp_grant_expirer, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(comp_grant_expirer, "_connect", return_value=conn):
            rc = comp_grant_expirer.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()