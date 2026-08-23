"""Tests for app.utils.url_safety — OG image override SSRF guard.

Run from the repo root:
    python3 -m unittest tests.test_url_safety

No DB or network required — getaddrinfo is monkey-patched where DNS lookup
would otherwise hit the network.
"""
import socket
from unittest import mock

from app.utils.url_safety import safe_public_url


def _fake_getaddrinfo(host, port, *args, **kwargs):
    if host == "good.example.com":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    if host == "private.example.com":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    if host == "metadata.example.com":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]
    raise socket.gaierror(-2, "Name does not resolve")


import unittest


class SafePublicUrlTests(unittest.TestCase):
    def setUp(self):
        self._patcher = mock.patch("socket.getaddrinfo", side_effect=_fake_getaddrinfo)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_empty_url_ok(self):
        ok, reason = safe_public_url("")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_valid_https_ok(self):
        ok, reason = safe_public_url("https://good.example.com/image.png")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_valid_http_ok(self):
        ok, reason = safe_public_url("http://good.example.com/image.png")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_javascript_scheme_rejected(self):
        ok, reason = safe_public_url("javascript:alert(1)")
        self.assertFalse(ok)
        self.assertEqual(reason, "bad-scheme")

    def test_data_scheme_rejected(self):
        ok, reason = safe_public_url("data:image/png;base64,iVBORw0KGgo=")
        self.assertFalse(ok)
        self.assertEqual(reason, "bad-scheme")

    def test_file_scheme_rejected(self):
        ok, reason = safe_public_url("file:///etc/passwd")
        self.assertFalse(ok)
        self.assertEqual(reason, "bad-scheme")

    def test_credentials_rejected(self):
        ok, reason = safe_public_url("https://user:pass@good.example.com/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "credentials-not-allowed")

    def test_loopback_literal_rejected(self):
        ok, reason = safe_public_url("http://127.0.0.1/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_metadata_ip_rejected(self):
        ok, reason = safe_public_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_rfc1918_10x_rejected(self):
        ok, reason = safe_public_url("http://10.0.0.5/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_rfc1918_192_rejected(self):
        ok, reason = safe_public_url("http://192.168.1.1/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_rfc1918_172_rejected(self):
        ok, reason = safe_public_url("http://172.16.5.5/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_dns_to_private_ip_rejected(self):
        ok, reason = safe_public_url("http://private.example.com/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_dns_to_metadata_rejected(self):
        ok, reason = safe_public_url("http://metadata.example.com/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")

    def test_localhost_internal_tld_rejected(self):
        ok, reason = safe_public_url("http://foo.localhost/x")
        self.assertFalse(ok)
        # Either DNS lookup fails (unresolvable) or the .localhost TLD is
        # rejected directly — both are safe outcomes.
        self.assertIn(reason, ("internal-host", "private-host", "unresolvable-host"))

    def test_internal_tld_rejected(self):
        ok, reason = safe_public_url("http://host.internal/x")
        self.assertFalse(ok)
        self.assertIn(reason, ("internal-host", "unresolvable-host"))

    def test_unresolvable_rejected(self):
        ok, reason = safe_public_url("http://does-not-exist-9f3k2j4.invalid/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "unresolvable-host")

    def test_too_long_rejected(self):
        long_url = "https://good.example.com/" + ("a" * 3000)
        ok, reason = safe_public_url(long_url)
        self.assertFalse(ok)
        self.assertEqual(reason, "too-long")

    def test_no_host_rejected(self):
        ok, reason = safe_public_url("https:///path")
        self.assertFalse(ok)
        self.assertIn(reason, ("no-host", "bad-scheme"))

    def test_ipv6_loopback_rejected(self):
        ok, reason = safe_public_url("http://[::1]/x")
        self.assertFalse(ok)
        self.assertEqual(reason, "private-host")