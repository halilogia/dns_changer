"""Update-check version parsing and the never-raises GitHub contract."""

from __future__ import annotations

import json
import unittest
import urllib.error

from core import updater
from core.updater import UpdateInfo
from tests import ROOT  # noqa: F401


class StubFetch:
    """Injectable ``fetch(url, timeout) -> bytes`` double.

    Records every call so the tests can assert on the URL and the timeout that
    ``check_for_update`` actually used, and replays either a canned body or a
    canned failure.  No test in this file touches the network.
    """

    def __init__(self, body=b"", error=None):
        self.body = body
        self.error = error
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.body

    @property
    def urls(self):
        return [url for url, _ in self.calls]


def release_bytes(
    tag="v2.1.0",
    url="https://github.com/halilogia/dns_changer/releases/tag/v2.1.0",
    body="Bug fixes.",
    prerelease=False,
):
    return json.dumps({"tag_name": tag, "html_url": url, "body": body, "prerelease": prerelease}).encode("utf-8")


class TestParseVersion(unittest.TestCase):
    def test_well_formed(self):
        self.assertEqual(updater.parse_version("2.1.0"), (2, 1, 0))

    def test_single_component(self):
        self.assertEqual(updater.parse_version("3"), (3, 0, 0))

    def test_v_prefix_is_tolerated(self):
        self.assertEqual(updater.parse_version("v2.1.0"), (2, 1, 0))

    def test_short_version_is_padded(self):
        self.assertEqual(updater.parse_version("2.1"), (2, 1, 0))

    def test_extra_components_are_kept(self):
        self.assertEqual(updater.parse_version("2.1.0.4"), (2, 1, 0, 4))

    def test_surrounding_whitespace_and_prerelease_suffix(self):
        self.assertEqual(updater.parse_version("  v2.1.0-beta.2  "), (2, 1, 0))

    def test_empty_input(self):
        self.assertEqual(updater.parse_version(""), (0, 0, 0))
        self.assertEqual(updater.parse_version("   "), (0, 0, 0))

    def test_junk_input(self):
        for junk in ("latest", "unknown", "vNext", "..."):
            self.assertEqual(updater.parse_version(junk), (0, 0, 0), junk)

    def test_junk_result_sorts_below_real_versions(self):
        self.assertLess(updater.parse_version("nope"), updater.parse_version("0.0.1"))

    def test_numeric_segments_compare_as_integers(self):
        self.assertGreater(updater.parse_version("2.10.0"), updater.parse_version("2.9.0"))

    def test_never_raises(self):
        for value in ("", "v", "1.2.3.4.5.6", "-1", "1..2"):
            self.assertIsInstance(updater.parse_version(value), tuple, value)


class TestIsNewer(unittest.TestCase):
    def test_remote_is_newer(self):
        self.assertTrue(updater.is_newer("2.1.0", "2.0.0"))

    def test_equal_is_not_newer(self):
        self.assertFalse(updater.is_newer("2.0.0", "2.0.0"))

    def test_remote_is_older(self):
        self.assertFalse(updater.is_newer("1.9.0", "2.0.0"))

    def test_numeric_not_lexicographic(self):
        self.assertTrue(updater.is_newer("2.10.0", "2.9.0"))

    def test_v_prefix_on_either_side(self):
        self.assertTrue(updater.is_newer("v2.1.0", "v2.0.0"))
        self.assertFalse(updater.is_newer("v2.0.0", "2.0.0"))

    def test_missing_components_are_equivalent_to_zeros(self):
        self.assertFalse(updater.is_newer("2.1", "2.1.0"))
        self.assertTrue(updater.is_newer("2.1.1", "2.1"))

    def test_unparseable_remote_is_never_newer(self):
        for junk in ("", "latest", "unknown"):
            self.assertFalse(updater.is_newer(junk, "2.0.0"), junk)

    def test_unparseable_local_is_never_newer(self):
        for junk in ("", "dev", "unknown"):
            self.assertFalse(updater.is_newer("2.0.0", junk), junk)

    def test_prerelease_suffix_does_not_beat_the_final(self):
        self.assertFalse(updater.is_newer("2.1.0-beta.1", "2.1.0"))


class TestCheckForUpdateHappyPath(unittest.TestCase):
    def test_newer_release_is_available(self):
        fetch = StubFetch(release_bytes(tag="v2.1.0"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertTrue(info.available)
        self.assertEqual(info.current, "2.0.0")
        self.assertEqual(info.latest, "2.1.0")
        self.assertEqual(info.url, "https://github.com/halilogia/dns_changer/releases/tag/v2.1.0")
        self.assertEqual(info.notes, "Bug fixes.")
        self.assertFalse(info.prerelease)
        self.assertEqual(info.error, "")

    def test_older_remote_is_not_available(self):
        fetch = StubFetch(release_bytes(tag="v1.9.0"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertEqual(info.latest, "1.9.0")
        self.assertEqual(info.error, "")

    def test_equal_versions_are_not_available(self):
        fetch = StubFetch(release_bytes(tag="v2.0.0"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertEqual(info.latest, "2.0.0")

    def test_prerelease_is_reported(self):
        fetch = StubFetch(release_bytes(tag="v3.0.0-rc1", prerelease=True))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertTrue(info.prerelease)
        self.assertTrue(info.available)
        self.assertEqual(info.latest, "3.0.0-rc1")

    def test_tag_without_v_prefix_is_kept_verbatim(self):
        fetch = StubFetch(release_bytes(tag="2.5.0"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertEqual(info.latest, "2.5.0")
        self.assertTrue(info.available)

    def test_body_is_stripped_and_null_body_is_empty(self):
        fetch = StubFetch(release_bytes(body="  spaced notes  \n"))
        self.assertEqual(updater.check_for_update("2.0.0", fetch=fetch).notes, "spaced notes")

        fetch = StubFetch(json.dumps({"tag_name": "v2.1.0", "body": None}).encode("utf-8"))
        info = updater.check_for_update("2.0.0", fetch=fetch)
        self.assertEqual(info.notes, "")
        self.assertTrue(info.available)

    def test_very_long_notes_are_truncated(self):
        fetch = StubFetch(release_bytes(body="x" * 50_000))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertLessEqual(len(info.notes), updater.NOTES_LIMIT)
        self.assertTrue(info.notes.endswith("..."))

    def test_notes_just_under_the_limit_are_untouched(self):
        body = "y" * updater.NOTES_LIMIT
        fetch = StubFetch(release_bytes(body=body))
        self.assertEqual(updater.check_for_update("2.0.0", fetch=fetch).notes, body)


class TestCheckForUpdateRequestShape(unittest.TestCase):
    def test_default_repo_url(self):
        fetch = StubFetch(release_bytes())
        updater.check_for_update("2.0.0", fetch=fetch)

        self.assertEqual(fetch.urls, ["https://api.github.com/repos/halilogia/dns_changer/releases/latest"])
        self.assertEqual(updater.RELEASES_URL.format(repo=updater.DEFAULT_REPO), fetch.urls[0])

    def test_custom_repo_url(self):
        fetch = StubFetch(release_bytes())
        updater.check_for_update("2.0.0", repo="someone/other_repo", fetch=fetch)

        self.assertEqual(fetch.urls, ["https://api.github.com/repos/someone/other_repo/releases/latest"])

    def test_timeout_is_forwarded(self):
        fetch = StubFetch(release_bytes())
        updater.check_for_update("2.0.0", timeout=1.25, fetch=fetch)

        self.assertEqual(fetch.calls[0][1], 1.25)

    def test_empty_repo_falls_back_to_the_default(self):
        fetch = StubFetch(release_bytes())
        updater.check_for_update("2.0.0", repo="", fetch=fetch)

        self.assertIn(updater.DEFAULT_REPO, fetch.urls[0])


class TestCheckForUpdateFailures(unittest.TestCase):
    def test_network_error_is_reported_not_raised(self):
        fetch = StubFetch(error=OSError("timed out"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertTrue(info.error)
        self.assertIn("timed out", info.error)
        self.assertEqual(info.current, "2.0.0")
        self.assertEqual(info.latest, "")

    def test_url_error_is_reported_not_raised(self):
        fetch = StubFetch(error=urllib.error.URLError("name resolution failed"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertIn("name resolution failed", info.error)

    def test_http_404_mentions_the_status(self):
        error = urllib.error.HTTPError(updater.RELEASES_URL, 404, "Not Found", {}, None)
        info = updater.check_for_update("2.0.0", fetch=StubFetch(error=error))

        self.assertFalse(info.available)
        self.assertIn("404", info.error)
        self.assertNotIn("Not Found", info.error)

    def test_malformed_json_is_reported_not_raised(self):
        fetch = StubFetch(b"<html>rate limited</html>")
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertTrue(info.error)
        self.assertEqual(info.latest, "")

    def test_truncated_json_is_reported_not_raised(self):
        info = updater.check_for_update("2.0.0", fetch=StubFetch(b'{"tag_name": "v2.1'))

        self.assertFalse(info.available)
        self.assertTrue(info.error)

    def test_undecodable_body_is_reported_not_raised(self):
        info = updater.check_for_update("2.0.0", fetch=StubFetch(b"\xff\xfe\x00\x01"))

        self.assertFalse(info.available)
        self.assertTrue(info.error)

    def test_json_that_is_not_an_object_is_reported(self):
        info = updater.check_for_update("2.0.0", fetch=StubFetch(b"[1, 2, 3]"))

        self.assertFalse(info.available)
        self.assertTrue(info.error)

    def test_missing_tag_name_is_reported_not_raised(self):
        fetch = StubFetch(json.dumps({"html_url": "https://example.com", "body": "hi"}).encode("utf-8"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertTrue(info.error)
        self.assertEqual(info.latest, "")

    def test_blank_tag_name_is_reported(self):
        fetch = StubFetch(json.dumps({"tag_name": "   "}).encode("utf-8"))
        info = updater.check_for_update("2.0.0", fetch=fetch)

        self.assertFalse(info.available)
        self.assertTrue(info.error)

    def test_fetch_returning_none_is_reported(self):
        info = updater.check_for_update("2.0.0", fetch=StubFetch(None))

        self.assertFalse(info.available)
        self.assertTrue(info.error)

    def test_broken_fetch_callable_is_reported(self):
        def broken(url, timeout):
            raise RuntimeError("boom")

        info = updater.check_for_update("2.0.0", fetch=broken)

        self.assertFalse(info.available)
        self.assertIn("boom", info.error)

    def test_error_message_is_bounded(self):
        info = updater.check_for_update("2.0.0", fetch=StubFetch(error=OSError("e" * 5_000)))

        self.assertLessEqual(len(info.error), 200)


class TestUpdateInfo(unittest.TestCase):
    def test_defaults_after_current(self):
        info = UpdateInfo(available=False, current="2.0.0")

        self.assertEqual(info.latest, "")
        self.assertEqual(info.url, "")
        self.assertEqual(info.notes, "")
        self.assertEqual(info.error, "")
        self.assertFalse(info.prerelease)

    def test_is_frozen(self):
        info = UpdateInfo(available=True, current="2.0.0")
        with self.assertRaises(AttributeError):
            info.available = False

    def test_field_order(self):
        self.assertEqual(
            list(UpdateInfo.__dataclass_fields__),
            ["available", "current", "latest", "url", "notes", "error", "prerelease"],
        )

    def test_is_hashable_and_comparable_by_value(self):
        self.assertEqual(UpdateInfo(available=True, current="2.0.0"), UpdateInfo(available=True, current="2.0.0"))


if __name__ == "__main__":
    unittest.main()
