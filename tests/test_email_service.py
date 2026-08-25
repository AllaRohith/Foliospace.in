"""Tests for `app.services.email_service` — focused on the comp expiry warning
function. Mirrors the patterns in `tests/test_pending_comp_grants.py`:
mock `RESEND_API_KEY` to control the API path, assert (ok, msg_id) shape.

Run from repo root:
    python3 -m unittest tests.test_email_service
"""
import unittest
from unittest import mock

from app.services import email_service


class CompExpiryWarningEmailTests(unittest.TestCase):
    def test_no_api_key_returns_no_api_key(self):
        with mock.patch.object(email_service, "API_KEY", None):
            ok, msg = email_service.send_comp_expiry_warning_email(
                to_email="x@example.com",
                days_left=7,
                expires_date="1 September 2026",
                cta_url="https://foliospace.in/dashboard/billing",
            )
        self.assertFalse(ok)
        self.assertEqual(msg, "no_api_key")

    def test_happy_path_returns_true_and_msg_id(self):
        fake_resend = mock.MagicMock()
        fake_resend.Emails.send.return_value = {"id": "msg_abc123"}
        with mock.patch.object(email_service, "API_KEY", "test-key"), \
             mock.patch.object(email_service, "resend", fake_resend):
            ok, msg = email_service.send_comp_expiry_warning_email(
                to_email="x@example.com",
                days_left=7,
                expires_date="1 September 2026",
                cta_url="https://foliospace.in/dashboard/billing",
            )
        self.assertTrue(ok)
        self.assertEqual(msg, "msg_abc123")
        fake_resend.Emails.send.assert_called_once()
        params = fake_resend.Emails.send.call_args.args[0]
        self.assertEqual(params["to"], ["x@example.com"])
        self.assertIn("ends in 7 days", params["subject"])
        self.assertIn("Hi,", params["html"])

    def test_days_one_singular_subject(self):
        fake_resend = mock.MagicMock()
        fake_resend.Emails.send.return_value = {"id": "msg_x"}
        with mock.patch.object(email_service, "API_KEY", "test-key"), \
             mock.patch.object(email_service, "resend", fake_resend):
            ok, _ = email_service.send_comp_expiry_warning_email(
                to_email="x@example.com",
                days_left=1,
                expires_date="1 September 2026",
                cta_url="https://foliospace.in/dashboard/billing",
            )
        self.assertTrue(ok)
        params = fake_resend.Emails.send.call_args.args[0]
        self.assertIn("ends in 1 day", params["subject"])
        self.assertNotIn("1 days", params["subject"])

    def test_send_exception_returns_send_error(self):
        fake_resend = mock.MagicMock()
        fake_resend.Emails.send.side_effect = RuntimeError("resend 500")
        with mock.patch.object(email_service, "API_KEY", "test-key"), \
             mock.patch.object(email_service, "resend", fake_resend):
            ok, msg = email_service.send_comp_expiry_warning_email(
                to_email="x@example.com",
                days_left=7,
                expires_date="1 September 2026",
                cta_url="https://foliospace.in/dashboard/billing",
            )
        self.assertFalse(ok)
        self.assertEqual(msg, "send_error")

    def test_negative_days_left_clamped_to_zero(self):
        fake_resend = mock.MagicMock()
        fake_resend.Emails.send.return_value = {"id": "msg_y"}
        with mock.patch.object(email_service, "API_KEY", "test-key"), \
             mock.patch.object(email_service, "resend", fake_resend):
            ok, _ = email_service.send_comp_expiry_warning_email(
                to_email="x@example.com",
                days_left=-5,
                expires_date="1 September 2026",
                cta_url="https://foliospace.in/dashboard/billing",
            )
        self.assertTrue(ok)
        params = fake_resend.Emails.send.call_args.args[0]
        self.assertIn("ends in 0 days", params["subject"])


if __name__ == "__main__":
    unittest.main()