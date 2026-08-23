"""Tests for the Phase C referral program.

Covers:
* `app.services.referrals` pure helpers (generate, count, progress)
* `record_referral` idempotency + self-refer guard
* `verify_referrer` / `activate_referral_if_public` state transitions
* `evaluate_user_referrals` threshold gate + swap trigger
* billing integration: pick_plan_for_renewal referral branch
* Router /ref/{code}: cookie set/cleared/sanitized, anti-enumeration
* Cron preflight + scan query

Run from repo root:
    python3 -m unittest tests.test_referrals
"""
import unittest
from unittest import mock

from app.services import referrals as refs
from app.services import billing


def _run_async(coro):
    """Run a coroutine to completion in a sync test."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


class ReferralConstantsTests(unittest.TestCase):
    def test_threshold_is_10(self):
        self.assertEqual(refs.REFERRAL_THRESHOLD, 10)

    def test_code_len_bytes_is_7(self):
        # 7 bytes -> 14 hex chars (per secrets.token_hex)
        self.assertEqual(refs.CODE_LEN_BYTES, 7)

    def test_max_gen_attempts_is_3(self):
        self.assertEqual(refs.MAX_CODE_GEN_ATTEMPTS, 3)

    def test_generate_referral_code_is_14_hex(self):
        code = refs.generate_referral_code()
        self.assertEqual(len(code), 14)
        int(code, 16)  # parses as hex

    def test_generate_referral_code_unique_per_call(self):
        codes = {refs.generate_referral_code() for _ in range(50)}
        self.assertEqual(len(codes), 50)


class SanitizeCodeTests(unittest.TestCase):
    """Mirror of the sanitization in app.routers.referral._sanitize_code."""

    def _sanitize(self, code: str) -> str:
        return "".join(ch for ch in (code or "").strip().lower()[:64] if ch.isalnum() or ch == "_-")

    def test_strip_whitespace(self):
        self.assertEqual(self._sanitize("  abc123  "), "abc123")

    def test_lowercase(self):
        self.assertEqual(self._sanitize("ABC123"), "abc123")

    def test_truncate_long_input(self):
        self.assertEqual(len(self._sanitize("a" * 200)), 64)

    def test_strip_special_chars(self):
        # Path-slashes, query params, etc. should be dropped.
        self.assertEqual(self._sanitize("ab/../cd?x=1"), "abcdx1")

    def test_keeps_alnum_drops_special(self):
        # Sanitizer drops non-alnum (referral codes are pure hex, so this
        # also confirms that the function is safe against arbitrary input).
        self.assertEqual(self._sanitize("ab-cd_ef"), "abcdef")
        self.assertEqual(self._sanitize("ab.cd@ef"), "abcdef")

    def test_empty_input(self):
        self.assertEqual(self._sanitize(""), "")

    def test_only_special_chars(self):
        self.assertEqual(self._sanitize("!@#$%^&*()"), "")


class ResolveCodeTests(unittest.TestCase):
    def _build_conn(self, row):
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = row
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_returns_uuid_when_found(self):
        conn = self._build_conn({"id": "11111111-2222-3333-4444-555555555555"})
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            out = refs.resolve_code_to_user_id("abc123")
        self.assertEqual(out, "11111111-2222-3333-4444-555555555555")

    def test_returns_none_when_unknown(self):
        conn = self._build_conn(None)
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            self.assertIsNone(refs.resolve_code_to_user_id("zzz"))

    def test_returns_none_when_no_database(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertIsNone(refs.resolve_code_to_user_id("abc123"))

    def test_returns_none_on_db_error(self):
        import psycopg
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.execute.side_effect = psycopg.Error("db down")
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn if False else fake_conn):
            self.assertIsNone(refs.resolve_code_to_user_id("abc123"))

    def test_empty_code_returns_none(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"):
            self.assertIsNone(refs.resolve_code_to_user_id(""))


class RecordReferralTests(unittest.TestCase):
    def _build_conn(self, *, rowcount: int):
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.rowcount = rowcount
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_returns_false_when_args_missing(self):
        self.assertFalse(refs.record_referral("", "b", "code"))
        self.assertFalse(refs.record_referral("a", "", "code"))
        self.assertFalse(refs.record_referral("a", "b", ""))

    def test_returns_false_when_no_database(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertFalse(refs.record_referral(
                "11111111-2222-3333-4444-555555555555",
                "22222222-3333-4444-5555-666666666666",
                "abc123",
            ))

    def test_rejects_self_referral(self):
        uid = "11111111-2222-3333-4444-555555555555"
        self.assertFalse(refs.record_referral(uid, uid, "abc123"))

    def test_returns_false_on_invalid_uuid(self):
        self.assertFalse(refs.record_referral("not-a-uuid", "also-not-a-uuid", "code"))

    def test_returns_true_when_row_inserted(self):
        conn = self._build_conn(rowcount=1)
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            ok = refs.record_referral(
                "11111111-2222-3333-4444-555555555555",
                "22222222-3333-4444-5555-666666666666",
                "abc123",
            )
        self.assertTrue(ok)

    def test_returns_false_on_duplicate_referee(self):
        conn = self._build_conn(rowcount=0)
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            ok = refs.record_referral(
                "11111111-2222-3333-4444-555555555555",
                "22222222-3333-4444-5555-666666666666",
                "abc123",
            )
        self.assertFalse(ok)


class VerifyReferrerTests(unittest.TestCase):
    def _build_conn(self, update_row, count_value):
        """Build a conn where the UPDATE returns update_row and the COUNT(*) returns count_value."""
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        calls = {"i": 0}
        def fetchone():
            i = calls["i"]
            calls["i"] += 1
            if i == 0:
                return update_row
            return {"n": count_value}
        fake_cur.fetchone.side_effect = fetchone
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_returns_zero_when_no_pending_row(self):
        conn = self._build_conn(update_row=None, count_value=0)
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            self.assertEqual(refs.verify_referrer("22222222-3333-4444-5555-666666666666"), 0)

    def test_returns_active_count_when_row_updated(self):
        conn = self._build_conn(
            update_row={"referrer_id": "11111111-2222-3333-4444-555555555555"},
            count_value=3,
        )
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            self.assertEqual(refs.verify_referrer("22222222-3333-4444-5555-666666666666"), 3)

    def test_returns_zero_when_no_database(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertEqual(refs.verify_referrer("22222222-3333-4444-5555-666666666666"), 0)

    def test_invalid_uuid_returns_zero(self):
        self.assertEqual(refs.verify_referrer("not-a-uuid"), 0)


class ActivateReferralTests(unittest.TestCase):
    def _build_conn(self, update_row, count_value):
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        calls = {"i": 0}
        def fetchone():
            i = calls["i"]
            calls["i"] += 1
            if i == 0:
                return update_row
            return {"n": count_value}
        fake_cur.fetchone.side_effect = fetchone
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_short_circuits_when_was_public_true(self):
        # No DB call expected
        self.assertEqual(refs.activate_referral_if_public("u1", True, True), 0)

    def test_short_circuits_when_now_public_false(self):
        self.assertEqual(refs.activate_referral_if_public("u1", False, False), 0)

    def test_short_circuits_when_no_database(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertEqual(refs.activate_referral_if_public(
                "22222222-3333-4444-5555-666666666666", False, True,
            ), 0)

    def test_returns_zero_when_no_verified_row(self):
        conn = self._build_conn(update_row=None, count_value=0)
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            self.assertEqual(refs.activate_referral_if_public(
                "22222222-3333-4444-5555-666666666666", False, True,
            ), 0)

    def test_returns_active_count_below_threshold(self):
        conn = self._build_conn(
            update_row={"referrer_id": "11111111-2222-3333-4444-555555555555"},
            count_value=5,
        )
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            # Below threshold — does NOT trigger evaluate
            with mock.patch.object(refs, "evaluate_user_referrals") as ev:
                out = refs.activate_referral_if_public(
                    "22222222-3333-4444-5555-666666666666", False, True,
                )
        self.assertEqual(out, 5)
        ev.assert_not_called()

    def test_triggers_evaluate_at_threshold(self):
        conn = self._build_conn(
            update_row={"referrer_id": "11111111-2222-3333-4444-555555555555"},
            count_value=10,
        )
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=conn):
            with mock.patch.object(refs, "evaluate_user_referrals") as ev:
                out = refs.activate_referral_if_public(
                    "22222222-3333-4444-5555-666666666666", False, True,
                )
        self.assertEqual(out, 10)
        ev.assert_called_once_with("11111111-2222-3333-4444-555555555555")


class CountReferralsTests(unittest.TestCase):
    def _build_conn(self, n):
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"n": n}
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_returns_count(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "_connect", return_value=self._build_conn(7)):
            self.assertEqual(refs.count_referrals("22222222-3333-4444-5555-666666666666"), 7)

    def test_zero_when_no_database(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertEqual(refs.count_referrals("22222222-3333-4444-5555-666666666666"), 0)

    def test_zero_on_invalid_uuid(self):
        self.assertEqual(refs.count_referrals("not-a-uuid"), 0)


class EvaluateUserReferralsTests(unittest.TestCase):
    def test_no_database_returns_none(self):
        with mock.patch.object(refs, "DATABASE_URL", ""):
            self.assertIsNone(refs.evaluate_user_referrals("u1"))

    def test_below_threshold_does_not_swap(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "count_referrals", return_value=3):
            with mock.patch("app.services.billing._swap_to_plan") as sw:
                out = refs.evaluate_user_referrals("u1")
        self.assertEqual(out, {"swapped": False, "reason": "below_threshold"})
        sw.assert_not_called()

    def test_at_threshold_triggers_swap(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "count_referrals", return_value=10):
            with mock.patch("app.services.cashfree.plan_year1_id", return_value="plan_y1"), \
                 mock.patch("app.services.billing._swap_to_plan", return_value={"swapped": True, "new_plan": "plan_y1"}) as sw:
                out = refs.evaluate_user_referrals("u1")
        self.assertEqual(out, {"swapped": True, "new_plan": "plan_y1"})
        sw.assert_called_once_with("u1", "plan_y1", reason="referral_unlock")

    def test_above_threshold_triggers_swap(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "count_referrals", return_value=42):
            with mock.patch("app.services.cashfree.plan_year1_id", return_value="plan_y1"), \
                 mock.patch("app.services.billing._swap_to_plan", return_value={"swapped": True}) as sw:
                refs.evaluate_user_referrals("u1")
        sw.assert_called_once()

    def test_swap_failure_returns_none(self):
        with mock.patch.object(refs, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(refs, "count_referrals", return_value=10):
            with mock.patch("app.services.cashfree.plan_year1_id", return_value="plan_y1"), \
                 mock.patch("app.services.billing._swap_to_plan", side_effect=RuntimeError("boom")):
                out = refs.evaluate_user_referrals("u1")
        self.assertIsNone(out)


class ProgressForUserTests(unittest.TestCase):
    def test_below_threshold(self):
        with mock.patch.object(refs, "count_referrals", return_value=3):
            p = refs.progress_for_user("u1")
        self.assertEqual(p["active_count"], 3)
        self.assertEqual(p["threshold"], 10)
        self.assertEqual(p["remaining"], 7)
        self.assertFalse(p["unlocked"])

    def test_at_threshold(self):
        with mock.patch.object(refs, "count_referrals", return_value=10):
            p = refs.progress_for_user("u1")
        self.assertEqual(p["remaining"], 0)
        self.assertTrue(p["unlocked"])

    def test_above_threshold_clamps_remaining(self):
        with mock.patch.object(refs, "count_referrals", return_value=42):
            p = refs.progress_for_user("u1")
        self.assertEqual(p["active_count"], 42)
        self.assertEqual(p["remaining"], 0)
        self.assertTrue(p["unlocked"])

    def test_threshold_matches_constant(self):
        with mock.patch.object(refs, "count_referrals", return_value=0):
            p = refs.progress_for_user("u1")
        self.assertEqual(p["threshold"], refs.REFERRAL_THRESHOLD)


class PickPlanRenewalReferralTests(unittest.TestCase):
    """Referral branch in pick_plan_for_renewal: 10+ active -> year-1."""

    def _build_conn(self, grant_row, referral_count):
        """Returns a conn that dispatches based on which query is run.

        pick_plan_for_renewal runs two queries:
          1. subscription_grants check -> returns grant_row
          2. referrals count check    -> returns referral_count
        """
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        state = {"sql": ""}
        def fake_execute(sql, params=()):
            state["sql"] = (sql or "").lower()
        def fake_fetchone():
            if "from subscription_grants" in state["sql"]:
                return grant_row
            if "from referrals" in state["sql"]:
                return {"n": referral_count}
            return None
        fake_cur.execute.side_effect = fake_execute
        fake_cur.fetchone.side_effect = fake_fetchone
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False
        return fake_conn

    def test_below_threshold_returns_year2(self):
        conn = self._build_conn(grant_row=None, referral_count=3)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn), \
             mock.patch.object(billing, "cashfree_svc") as cf:
            cf.plan_year2_id.return_value = "plan_y2"
            out = billing.pick_plan_for_renewal("u1")
        self.assertEqual(out, "plan_y2")

    def test_at_threshold_returns_year1(self):
        conn = self._build_conn(grant_row=None, referral_count=10)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn), \
             mock.patch.object(billing, "cashfree_svc") as cf:
            cf.plan_year1_id.return_value = "plan_y1"
            out = billing.pick_plan_for_renewal("u1")
        self.assertEqual(out, "plan_y1")

    def test_above_threshold_returns_year1(self):
        conn = self._build_conn(grant_row=None, referral_count=42)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn), \
             mock.patch.object(billing, "cashfree_svc") as cf:
            cf.plan_year1_id.return_value = "plan_y1"
            out = billing.pick_plan_for_renewal("u1")
        self.assertEqual(out, "plan_y1")

    def test_active_grant_takes_priority_over_referral(self):
        """Comp grant returns None even when referral count >= 10."""
        conn = self._build_conn(grant_row={"expires_at": None}, referral_count=42)
        with mock.patch.object(billing, "DATABASE_URL", "postgres://x"), \
             mock.patch.object(billing, "_connect", return_value=conn):
            out = billing.pick_plan_for_renewal("u1")
        self.assertIsNone(out)


class ReferralRouterTests(unittest.TestCase):
    """Lightweight tests on app.routers.referral._sanitize_code + cookie semantics."""

    def test_ref_landing_sets_cookie_for_known_code(self):
        from app.routers.referral import ref_landing, _REF_COOKIE
        with mock.patch("app.routers.referral.referrals_svc.resolve_code_to_user_id",
                        return_value="11111111-2222-3333-4444-555555555555"):
            resp = _run_async(ref_landing(code="abc123"))
        # Endpoint must always be a 303 redirect — never 200 (anti-enumeration).
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers.get("location"), "/signup")
        cookie_header = resp.headers.get("set-cookie", "")
        self.assertIn(_REF_COOKIE, cookie_header)
        self.assertIn("11111111-2222-3333-4444-555555555555", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=lax", cookie_header)

    def test_ref_landing_unknown_code_does_not_set_cookie(self):
        from app.routers.referral import ref_landing
        with mock.patch("app.routers.referral.referrals_svc.resolve_code_to_user_id",
                        return_value=None):
            resp = _run_async(ref_landing(code="notreal"))
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("fs_ref", resp.headers.get("set-cookie", ""))

    def test_ref_landing_junk_sanitized_to_empty(self):
        from app.routers.referral import ref_landing
        # All special chars -> sanitized to empty -> no cookie set, no resolution attempted
        with mock.patch("app.routers.referral.referrals_svc.resolve_code_to_user_id") as rslv:
            resp = _run_async(ref_landing(code="!@#$%^"))
        self.assertEqual(resp.status_code, 303)
        rslv.assert_not_called()


class CronPreflightTests(unittest.TestCase):
    """Tests for app.jobs/referral_evaluator._preflight."""

    def _reload_module(self):
        import importlib
        from app.jobs import referral_evaluator
        importlib.reload(referral_evaluator)
        return referral_evaluator

    def test_missing_token_returns_2(self):
        re_mod = self._reload_module()
        with mock.patch.object(re_mod, "TRUST_TOKEN", ""), \
             mock.patch.object(re_mod, "DATABASE_URL", "postgres://x"):
            self.assertEqual(re_mod._preflight(), 2)

    def test_missing_database_returns_2(self):
        re_mod = self._reload_module()
        with mock.patch.object(re_mod, "TRUST_TOKEN", "x"), \
             mock.patch.object(re_mod, "DATABASE_URL", ""):
            self.assertEqual(re_mod._preflight(), 2)

    def test_both_present_returns_none(self):
        re_mod = self._reload_module()
        with mock.patch.object(re_mod, "TRUST_TOKEN", "x"), \
             mock.patch.object(re_mod, "DATABASE_URL", "postgres://x"):
            self.assertIsNone(re_mod._preflight())


class CronFindSwapTargetsTests(unittest.TestCase):
    """Validates the JOIN shape that the cron uses — it must filter out
    users already on year-1 and only consider active/authenticated subs."""

    def test_query_filters_existing_year1(self):
        """The query must include 'cashfree_plan_id <> %s' so we don't re-swap."""
        from app.jobs import referral_evaluator as re_mod
        captured = {}
        fake_conn = mock.MagicMock()
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = []
        def capture(sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
        fake_cur.execute.side_effect = capture
        fake_conn.__enter__.return_value = fake_conn
        fake_conn.__exit__.return_value = False
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        fake_conn.cursor.return_value.__exit__.return_value = False

        with mock.patch.object(re_mod, "_cashfree_svc") as cf, \
             mock.patch.object(re_mod, "_connect", return_value=fake_conn):
            cf.plan_year1_id.return_value = "plan_y1"
            targets = re_mod._find_swap_targets(fake_conn)
        self.assertEqual(targets, [])
        self.assertIn("cashfree_plan_id <> %s", captured["sql"])
        self.assertIn("v_referral_counts", captured["sql"])
        self.assertEqual(captured["params"][0], 10)
        self.assertEqual(captured["params"][1], "plan_y1")


if __name__ == "__main__":
    unittest.main()