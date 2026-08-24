"""Tests for the Edit Folio form section redesign + 4 new auto-fillable fields.

Covers:
* `app.services.user_auth.update_user_profile` accepts headline/locale/zoneinfo/profile_url
* Router-side validation regexes (locale, zoneinfo, profile_url, headline)
* LinkedIn `sync_basic_profile` writes the 4 new columns to users
* No-Neon fallback: validation rejects garbage BEFORE touching DB

Run from repo root:
    python3 -m unittest tests.test_manage_profile
"""
import re
import unittest
from unittest import mock


HEADLINE_OK = "Senior Product Designer · ex-Google"
HEADLINE_TOO_LONG = "x" * 201
LOCALE_OK = "en_IN"
LOCALE_BAD = "english"
LOCALE_EMPTY = ""
ZONEINFO_OK = "Asia/Kolkata"
ZONEINFO_BAD = "123 America!"
ZONEINFO_EMPTY = ""
PROFILE_URL_OK = "https://www.linkedin.com/in/your-handle"
PROFILE_URL_BAD = "notaurl"
PROFILE_URL_EMPTY = ""


class UpdateUserProfileValidationTests(unittest.TestCase):
    """No DB: validate the regex gating in update_user_profile returns None on bad input."""

    def _call(self, **kwargs):
        from app.services import user_auth as ua
        return ua.update_user_profile(
            "00000000-0000-0000-0000-000000000000",
            display_name="Test User",
            role="designer",
            bio="hi",
            phone="",
            is_public=False,
            **kwargs,
        )

    def test_returns_none_when_locale_invalid(self):
        with mock.patch("app.services.user_auth._connect") as conn:
            self.assertIsNone(self._call(locale=LOCALE_BAD))

    def test_returns_none_when_zoneinfo_invalid(self):
        with mock.patch("app.services.user_auth._connect") as conn:
            self.assertIsNone(self._call(zoneinfo=ZONEINFO_BAD))

    def test_returns_none_when_profile_url_invalid(self):
        with mock.patch("app.services.user_auth._connect") as conn:
            self.assertIsNone(self._call(profile_url=PROFILE_URL_BAD))

    def test_returns_none_when_headline_too_long(self):
        with mock.patch("app.services.user_auth._connect") as conn:
            self.assertIsNone(self._call(headline=HEADLINE_TOO_LONG))

    def test_empty_strings_are_accepted_as_none(self):
        fake_row = {
            "id": "00000000-0000-0000-0000-000000000000",
            "headline": "",
            "locale": "",
            "zoneinfo": "",
            "profile_url": "",
        }
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = fake_row
        fake_cur.execute.return_value = None
        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = mock.MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.cursor.return_value.__enter__ = mock.MagicMock(return_value=fake_cur)
        fake_conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch("app.services.user_auth._connect", return_value=fake_conn):
            res = self._call(
                headline=HEADLINE_OK,
                locale=LOCALE_EMPTY,
                zoneinfo=ZONEINFO_EMPTY,
                profile_url=PROFILE_URL_EMPTY,
            )
        self.assertIsNotNone(res)

    def test_known_good_values_pass_regex(self):
        self.assertTrue(re.fullmatch(r"[A-Za-z]{2,3}(_[A-Z]{2})?", LOCALE_OK))
        self.assertTrue(re.fullmatch(r"[A-Za-z]+(/[A-Za-z_]+)*", ZONEINFO_OK))
        self.assertTrue(re.fullmatch(r"https?://\S+", PROFILE_URL_OK))
        self.assertFalse(re.fullmatch(r"[A-Za-z]{2,3}(_[A-Z]{2})?", LOCALE_BAD))
        self.assertFalse(re.fullmatch(r"[A-Za-z]+(/[A-Za-z_]+)*", ZONEINFO_BAD))


class LinkedInSyncWritesFourColumnsTests(unittest.TestCase):
    """LinkedIn sync must populate users.headline / locale / zoneinfo / profile_url."""

    def _build_fake_conn(self):
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {
            "avatar_provider": "",
            "avatar_public_id": "",
        }
        fake_conn = mock.MagicMock()
        fake_conn.__enter__ = mock.MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = mock.MagicMock(return_value=False)
        fake_conn.cursor.return_value.__enter__ = mock.MagicMock(return_value=fake_cur)
        fake_conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)
        return fake_conn, fake_cur

    def test_sync_writes_headline_locale_zoneinfo_profile_url(self):
        fake_conn, fake_cur = self._build_fake_conn()

        captured_sqls = []

        def _exec(sql, params=None):
            captured_sqls.append(str(sql).lower())

        fake_cur.execute.side_effect = _exec

        with mock.patch("app.services.user_auth._connect", return_value=fake_conn), \
             mock.patch("app.services.imports.linkedin._http_get_bearer") as http_mock, \
             mock.patch("app.services.imports.linkedin.get_token_for", return_value="fake-token"), \
             mock.patch("app.services.imports.linkedin._mirror_avatar", return_value=None):
            http_mock.side_effect = [
                {
                    "sub": "abc",
                    "name": "Test User",
                    "email": "t@example.com",
                    "email_verified": True,
                    "locale": "en_IN",
                    "zoneinfo": "Asia/Kolkata",
                    "picture": "",
                },
                {
                    "localizedHeadline": HEADLINE_OK,
                    "localizedFirstName": "Test",
                    "localizedLastName": "User",
                    "vanityName": "testuser",
                    "id": "abc",
                },
            ]
            from app.services.imports import linkedin as li
            li.sync_basic_profile("00000000-0000-0000-0000-000000000000")

        joined = "\n".join(captured_sqls)
        self.assertIn("headline", joined)
        self.assertIn("locale", joined)
        self.assertIn("zoneinfo", joined)
        self.assertIn("profile_url", joined)

    def test_sync_skips_overwriting_existing_user_values(self):
        """The SQL should only fire WHERE the column is NULL or empty."""
        fake_conn, fake_cur = self._build_fake_conn()
        captured_sqls = []

        def _exec(sql, params=None):
            captured_sqls.append(str(sql).lower())

        fake_cur.execute.side_effect = _exec

        with mock.patch("app.services.user_auth._connect", return_value=fake_conn), \
             mock.patch("app.services.imports.linkedin._http_get_bearer") as http_mock, \
             mock.patch("app.services.imports.linkedin.get_token_for", return_value="fake-token"), \
             mock.patch("app.services.imports.linkedin._mirror_avatar", return_value=None):
            http_mock.side_effect = [
                {"sub": "abc", "name": "", "email": "", "email_verified": False, "locale": "", "zoneinfo": "", "picture": ""},
                {"localizedHeadline": "x", "vanityName": "", "id": "abc"},
            ]
            from app.services.imports import linkedin as li
            li.sync_basic_profile("00000000-0000-0000-0000-000000000000")

        joined = "\n".join(captured_sqls)
        self.assertIn("is null or btrim", joined)


class ManageRouterValidationTests(unittest.TestCase):
    """Router: bad field → redirect with err code; good field → reach update_user_profile."""

    def _call_router(self, **overrides):
        import asyncio
        from app.routers.folio import owner_folio_manage_save
        fake_request = mock.MagicMock()
        user = {"id": "u", "slug": "s", "deleted_at": None, "is_listed": False}
        args = dict(
            display_name="Test User", role="", bio="", phone="", linkedin_url="",
            headline="", locale="", zoneinfo="", profile_url="",
            is_public="", is_listed="",
        )
        args.update(overrides)
        with mock.patch("app.services.folio.find_user_by_slug", return_value=user), \
             mock.patch("app.services.user_auth.require_user", return_value={"id": "u"}), \
             mock.patch("app.services.user_auth.update_user_profile", return_value={"ok": True}), \
             mock.patch("app.services.user_auth.audit_user"):
            coro = owner_folio_manage_save(
                request=fake_request, slug="s", **args,
            )
            return asyncio.get_event_loop().run_until_complete(coro)

    def test_locale_bad_redirects_with_err(self):
        res = self._call_router(locale=LOCALE_BAD)
        self.assertEqual(res.status_code, 303)
        self.assertIn("err=locale", res.headers["location"])

    def test_zoneinfo_bad_redirects_with_err(self):
        res = self._call_router(zoneinfo=ZONEINFO_BAD)
        self.assertEqual(res.status_code, 303)
        self.assertIn("err=zoneinfo", res.headers["location"])

    def test_profile_url_bad_redirects_with_err(self):
        res = self._call_router(profile_url=PROFILE_URL_BAD)
        self.assertEqual(res.status_code, 303)
        self.assertIn("err=profile_url", res.headers["location"])

    def test_headline_too_long_redirects_with_err(self):
        res = self._call_router(headline=HEADLINE_TOO_LONG)
        self.assertEqual(res.status_code, 303)
        self.assertIn("err=headline", res.headers["location"])

    def test_good_values_reach_update_user_profile(self):
        import asyncio
        from app.routers.folio import owner_folio_manage_save
        fake_request = mock.MagicMock()
        user = {"id": "u", "slug": "s", "deleted_at": None, "is_listed": False}
        with mock.patch("app.services.folio.find_user_by_slug", return_value=user), \
             mock.patch("app.services.user_auth.require_user", return_value={"id": "u"}), \
             mock.patch("app.services.user_auth.update_user_profile", return_value={"ok": True}) as ua_mock, \
             mock.patch("app.services.user_auth.audit_user"):
            coro = owner_folio_manage_save(
                request=fake_request,
                slug="s",
                display_name="Test User",
                role="designer",
                bio="hi",
                phone="",
                linkedin_url="",
                headline=HEADLINE_OK,
                locale=LOCALE_OK,
                zoneinfo=ZONEINFO_OK,
                profile_url=PROFILE_URL_OK,
                is_public="1",
                is_listed="",
            )
            res = asyncio.get_event_loop().run_until_complete(coro)
        self.assertEqual(res.status_code, 303)
        self.assertIn("saved=1", res.headers["location"])
        ua_mock.assert_called_once()
        kwargs = ua_mock.call_args.kwargs
        self.assertEqual(kwargs["headline"], HEADLINE_OK)
        self.assertEqual(kwargs["locale"], LOCALE_OK)
        self.assertEqual(kwargs["zoneinfo"], ZONEINFO_OK)
        self.assertEqual(kwargs["profile_url"], PROFILE_URL_OK)


if __name__ == "__main__":
    unittest.main()