"""Tests for app.services.cashfree — HMAC verification + client shape.

Run from the repo root:
    python3 -m unittest tests.test_cashfree

No DB or live HTTP — `httpx.Client` calls are patched.
"""
import hashlib
import hmac
import unittest
from unittest import mock

from fastapi import HTTPException

from app.services import cashfree


class EnvPatcher:
    """Context helper — temporarily set module-level env-backed constants.

    `app/services/cashfree.py` reads env vars at module-import time
    (module-level `os.getenv(...)`), so we patch the module globals
    directly rather than setting `os.environ`.
    """

    def __init__(self, **kwargs):
        self.kw = kwargs

    def __enter__(self):
        self._saved = {}
        for k, v in self.kw.items():
            self._saved[k] = getattr(cashfree, k, None)
            setattr(cashfree, k, v)
        cashfree.reset_client()
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            setattr(cashfree, k, v)
        cashfree.reset_client()


class WebhookSignatureTests(unittest.TestCase):
    def test_signature_accepts_valid_hmac(self):
        secret = "whsec_test_xyz"
        body = b'{"type":"PAYMENT_SUCCESS_WEBHOOK","data":{}}'
        ts = "1700000000"
        expected = hmac.new(secret.encode(),
                            (ts + body.decode()).encode(),
                            hashlib.sha256).hexdigest()
        with EnvPatcher(_WEBHOOK_SECRET=secret):
            ok = cashfree.verify_webhook_signature(body, expected, ts)
            self.assertTrue(ok)

    def test_signature_rejects_bad_hmac(self):
        with EnvPatcher(_WEBHOOK_SECRET="whsec_test_xyz"):
            self.assertFalse(cashfree.verify_webhook_signature(
                b'{"x":1}', "deadbeef" * 8, "1700000000"))

    def test_signature_rejects_empty_body(self):
        with EnvPatcher(_WEBHOOK_SECRET="whsec_test_xyz"):
            self.assertFalse(cashfree.verify_webhook_signature(
                b"", hmac.new(b"whsec_test_xyz", b"1700000000",
                              hashlib.sha256).hexdigest(), "1700000000"))

    def test_signature_rejects_missing_secret(self):
        # Without a secret we must reject everything.
        with EnvPatcher(_WEBHOOK_SECRET=""):
            self.assertFalse(cashfree.verify_webhook_signature(
                b'{"x":1}', "abcdef" * 8, "1700000000"))

    def test_signature_rejects_missing_timestamp(self):
        with EnvPatcher(_WEBHOOK_SECRET="whsec_test_xyz"):
            self.assertFalse(cashfree.verify_webhook_signature(
                b"{}", hmac.new(b"whsec_test_xyz", b"{}",
                                hashlib.sha256).hexdigest(), ""))

    def test_signature_case_insensitive_header(self):
        # Cashfree sends lower-hex signature; verify_webhook_signature
        # lowercases the header before compare.
        secret = "whsec_case"
        body = b'{"type":"PAYMENT_SUCCESS_WEBHOOK"}'
        ts = "1700000000"
        expected = hmac.new(secret.encode(),
                            (ts + body.decode()).encode(),
                            hashlib.sha256).hexdigest().upper()
        with EnvPatcher(_WEBHOOK_SECRET=secret):
            self.assertTrue(cashfree.verify_webhook_signature(body, expected, ts))


class IsConfiguredTests(unittest.TestCase):
    def test_unconfigured_when_app_id_missing(self):
        with EnvPatcher(
            _APP_ID="",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="p2",
        ):
            self.assertFalse(cashfree.is_configured())

    def test_unconfigured_when_secret_missing(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="p2",
        ):
            self.assertFalse(cashfree.is_configured())

    def test_unconfigured_when_webhook_secret_missing(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="p2",
        ):
            self.assertFalse(cashfree.is_configured())

    def test_unconfigured_when_year1_plan_id_missing(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="",
            _PLAN_YEAR2_ID="p2",
        ):
            self.assertFalse(cashfree.is_configured())

    def test_unconfigured_when_year2_plan_id_missing(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="",
        ):
            self.assertFalse(cashfree.is_configured())

    def test_configured_when_all_set(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="p2",
        ):
            self.assertTrue(cashfree.is_configured())


class EnvNameTests(unittest.TestCase):
    def test_default_is_sandbox(self):
        # The module-level `_ENV` falls back to "sandbox" at import time.
        # EnvPatcher restores the import-time default when no override
        # is set in this test, so we just check the current value.
        with EnvPatcher():
            self.assertEqual(cashfree.env_name(), "sandbox")

    def test_production(self):
        with EnvPatcher(_ENV="production"):
            self.assertEqual(cashfree.env_name(), "production")

    def test_development_alias(self):
        with EnvPatcher(_ENV="dev"):
            self.assertEqual(cashfree.env_name(), "dev")


class BaseUrlTests(unittest.TestCase):
    def test_sandbox_url(self):
        with EnvPatcher(_ENV="sandbox"):
            self.assertEqual(cashfree._base_url(), "https://sandbox.cashfree.com/pg")

    def test_production_url(self):
        with EnvPatcher(_ENV="production"):
            self.assertEqual(cashfree._base_url(), "https://api.cashfree.com/pg")


class PlanIdTests(unittest.TestCase):
    def test_plan_year1_id(self):
        with EnvPatcher(_PLAN_YEAR1_ID="plan_y1_id"):
            self.assertEqual(cashfree.plan_year1_id(), "plan_y1_id")

    def test_plan_year2_id(self):
        with EnvPatcher(_PLAN_YEAR2_ID="plan_y2_id"):
            self.assertEqual(cashfree.plan_year2_id(), "plan_y2_id")


class CreateCustomerTests(unittest.TestCase):
    def _full_config(self):
        return EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="p1",
            _PLAN_YEAR2_ID="p2",
        )

    def test_create_customer_returns_dict_on_2xx(self):
        with self._full_config():
            fake_resp = mock.Mock(status_code=200)
            fake_resp.json.return_value = {
                "customer_id": "user_abc",
                "customer_name": "Rohith",
                "customer_email": "r@example.com",
            }
            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.return_value = fake_resp
                out = cashfree.create_customer(
                    name="Rohith", email="r@example.com",
                    contact="9999999999", user_id="8b3a8b3a-8b3a-8b3a-8b3a-8b3a8b3a8b3a",
                )
            self.assertEqual(out["customer_id"], "user_abc")

    def test_create_customer_raises_502_on_4xx(self):
        with self._full_config():
            fake_resp = mock.Mock(status_code=400)
            fake_resp.text = "bad request"
            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.return_value = fake_resp
                with self.assertRaises(HTTPException) as cm:
                    cashfree.create_customer(
                        name="R", email="r@x.in", contact="9",
                        user_id="8b3a8b3a-8b3a-8b3a-8b3a-8b3a8b3a8b3a",
                    )
            self.assertEqual(cm.exception.status_code, 502)


class CreateSubscriptionTests(unittest.TestCase):
    def _full_config(self):
        return EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="plan_year1",
            _PLAN_YEAR2_ID="plan_year2",
        )

    def test_create_subscription_payload_shape(self):
        with self._full_config(), EnvPatcher(PUBLIC_BASE_URL="https://foliospace.in") if False else mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            captured = {}

            def fake_post(path, json=None):
                captured["path"] = path
                captured["json"] = json
                r = mock.Mock(status_code=200)
                r.json.return_value = {
                    "cf_subscription_id": "sub_xyz",
                    "subscription_session_id": "session_xyz",
                    "subscription_status": "created",
                }
                return r

            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.side_effect = fake_post
                out = cashfree.create_subscription(
                    cf_customer_id="user_abc",
                    plan_id="plan_year1",
                    user_id="8b3a8b3a-8b3a-8b3a-8b3a-8b3a8b3a8b3a",
                    slug="allarohithnaidu",
                )

            self.assertEqual(captured["path"], "/subscriptions")
            payload = captured["json"]
            self.assertEqual(payload["plan_details"]["plan_id"], "plan_year1")
            self.assertEqual(payload["customer_details"]["customer_id"], "user_abc")
            self.assertEqual(payload["subscription_tags"]["slug"], "allarohithnaidu")
            self.assertIn("return_url", payload["subscription_meta"])
            self.assertTrue(payload["subscription_meta"]["return_url"].endswith(
                "/dashboard/billing?cf_return=1"
            ))
            self.assertEqual(out["cf_subscription_id"], "sub_xyz")
            self.assertEqual(out["subscription_session_id"], "session_xyz")

    def test_create_subscription_raises_502_on_error(self):
        with self._full_config():
            fake_resp = mock.Mock(status_code=500)
            fake_resp.text = "boom"
            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.return_value = fake_resp
                with self.assertRaises(HTTPException) as cm:
                    cashfree.create_subscription(
                        cf_customer_id="user_x",
                        plan_id="plan_year1",
                        user_id="8b3a8b3a-8b3a-8b3a-8b3a-8b3a8b3a8b3a",
                        slug="x",
                    )
            self.assertEqual(cm.exception.status_code, 502)


class UpdateSubscriptionPlanTests(unittest.TestCase):
    def test_update_subscription_payload(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="plan_year1",
            _PLAN_YEAR2_ID="plan_year2",
        ):
            captured = {}

            def fake_post(path, json=None):
                captured["path"] = path
                captured["json"] = json
                r = mock.Mock(status_code=200)
                r.json.return_value = {"subscription_id": "sub_xyz", "plan_id": "plan_year2"}
                return r

            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.side_effect = fake_post
                out = cashfree.update_subscription_plan("sub_xyz", "plan_year2")
            self.assertEqual(captured["path"], "/subscriptions/sub_xyz/update")
            self.assertEqual(captured["json"]["plan_details"]["plan_id"], "plan_year2")
            self.assertEqual(out["plan_id"], "plan_year2")

    def test_update_subscription_raises_502_on_error(self):
        with EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="plan_year1",
            _PLAN_YEAR2_ID="plan_year2",
        ):
            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.return_value = mock.Mock(status_code=400, text="err")
                with self.assertRaises(HTTPException):
                    cashfree.update_subscription_plan("sub_xyz", "plan_year2")


class CancelSubscriptionTests(unittest.TestCase):
    def _full_config(self):
        return EnvPatcher(
            _APP_ID="app",
            _SECRET="sec",
            _WEBHOOK_SECRET="wh",
            _PLAN_YEAR1_ID="plan_year1",
            _PLAN_YEAR2_ID="plan_year2",
        )

    def test_cancel_subscription_sends_cycle_end(self):
        with self._full_config():
            captured = {}

            def fake_post(path, json=None):
                captured["path"] = path
                captured["json"] = json
                r = mock.Mock(status_code=200)
                r.json.return_value = {"status": "cancelled"}
                return r

            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.side_effect = fake_post
                cashfree.cancel_subscription("sub_xyz", cancel_at_cycle_end=True)
            self.assertEqual(captured["path"], "/subscriptions/sub_xyz/cancel")
            self.assertEqual(captured["json"]["cancel_at_cycle_end"], 1)

    def test_cancel_subscription_immediate(self):
        with self._full_config():
            captured = {}

            def fake_post(path, json=None):
                captured["json"] = json
                r = mock.Mock(status_code=200)
                r.json.return_value = {"status": "cancelled"}
                return r

            with mock.patch.object(cashfree, "_get_client") as gc:
                gc.return_value.post.side_effect = fake_post
                cashfree.cancel_subscription("sub_xyz", cancel_at_cycle_end=False)
            self.assertEqual(captured["json"]["cancel_at_cycle_end"], 0)


class ConstantsTests(unittest.TestCase):
    def test_year1_inr_is_899(self):
        self.assertEqual(cashfree.PRO_YEAR1_INR, 899)

    def test_year2_inr_is_1499(self):
        self.assertEqual(cashfree.PRO_YEAR2_INR, 1499)

    def test_year1_paise(self):
        self.assertEqual(cashfree.PRO_YEAR1_PAISE, 89900)

    def test_year2_paise(self):
        self.assertEqual(cashfree.PRO_YEAR2_PAISE, 149900)


if __name__ == "__main__":
    unittest.main()