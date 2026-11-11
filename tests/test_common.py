# Tool by @adi.codz (Discord)
"""Unit tests for luarmor_crack.common (response classification, Lua escape
decoding, sandbox discovery error path)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luarmor_crack import common as C  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(C.classify_response(
            "This loader code is outdated. You must use the loadstring ..."), "stale-loader")
        self.assertEqual(C.classify_response(
            "-- your executor is not supported by Luarmor."), "executor-trap")
        self.assertEqual(C.classify_response(
            '["d8e55380558032852ae6fc64f70e3fe2"]'), "session-response")
        self.assertEqual(C.classify_response('{"status":"ok"}'), "json")
        self.assertEqual(C.classify_response("hello"), "text")


class EscapeTest(unittest.TestCase):
    def test_decimal(self):
        self.assertEqual(C.decode_lua_escapes("\\164\\109\\57"), bytes([164, 109, 57]))

    def test_hex(self):
        self.assertEqual(C.decode_lua_escapes("\\x41\\x42"), b"AB")

    def test_named_and_literal(self):
        self.assertEqual(C.decode_lua_escapes("a\\nb\\tc"), b"a\nb\tc")
        self.assertEqual(C.decode_lua_escapes("72b8"), b"72b8")

    def test_mixed(self):
        self.assertEqual(C.decode_lua_escapes("\\218\\157\\138"), bytes([218, 157, 138]))

    def test_non_ascii_digit_is_not_a_decimal_escape(self):
        """str.isdigit() also accepts e.g. the superscript two, which int()
        then refuses to parse -- that used to crash the parser. The blob is
        read byte-per-char (latin-1), so the char stays one byte."""
        out = C.decode_lua_escapes("\\²")
        self.assertIsInstance(out, bytes)
        self.assertEqual(out, bytes([ord("²")]))

    def test_invalid_hex_escape_stays_literal(self):
        self.assertEqual(C.decode_lua_escapes("\\xZZ"), b"xZZ")

    def test_z_escape_skips_whitespace(self):
        self.assertEqual(C.decode_lua_escapes("a\\z   \n  b"), b"ab")

    def test_unicode_escape(self):
        self.assertEqual(C.decode_lua_escapes("\\u{48}\\u{49}"), b"HI")


class HttpErrorTest(unittest.TestCase):
    def test_http_error_becomes_runtime_error(self):
        """A 4xx/5xx must surface as a clean CLI error, not a traceback."""
        import urllib.error
        from unittest import mock
        err = urllib.error.HTTPError("http://host/x", 404, "Not Found", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                C.http_get("http://host/x")
        self.assertIn("404", str(ctx.exception))

    def test_url_error_becomes_runtime_error(self):
        import urllib.error
        from unittest import mock
        err = urllib.error.URLError("name resolution failed")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                C.http_get("http://host/x")
        self.assertIn("failed", str(ctx.exception))


class DiscoveryTest(unittest.TestCase):
    def test_looks_like_repo_rejects_bogus(self):
        self.assertFalse(C._looks_like_repo("/nonexistent/path/does/not/exist"))
        self.assertFalse(C._looks_like_repo(None))

    def test_discovery_outcome(self):
        # In an environment with the sandbox repo as a sibling, discovery must
        # return a path carrying the markers; otherwise it must raise a clear
        # error naming what was tried. Either outcome proves the contract.
        try:
            repo = C.find_sandbox_repo()
        except C.SandboxNotFound as e:
            self.assertIn("Tried", str(e))
            self.assertIn("harness.py", str(e))
        else:
            self.assertTrue(C._looks_like_repo(repo))


if __name__ == "__main__":
    unittest.main()
