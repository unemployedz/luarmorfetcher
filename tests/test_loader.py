# Tool by @adi.codz (Discord)
"""Unit tests for luarmor_crack.loader (pure parsing/building) and the
handshake/time-pin helpers. Adapted from the parent repo's luarmor_fetch_test."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luarmor_crack import loader as L  # noqa: E402

STUB = """-- Do not save this file
-- Always use the loadstring
  _bsdata0={339253403,"\\164\\109\\57",2167875005,92540919,"783e9b5f",1128507,"72b8b951637a",1790615855,33828300,"\\218\\157\\138",4314001,71740338};
local f,b,a="static_content_170926","f07dbcbe19a-sephal";pcall(function()a=readfile(f.."/init-"..b..".lua")end) if a and #a>2000 then a=loadstring(a) else a=nil; end;
if a then return a() else pcall(makefolder,f) a=game:HttpGet("https://cdn.luarmor.net/v4_init_sephal.lua"..(_ca920af6193 or "")) writefile(f.."/init-"..b..".lua", a); ldrupd8m=a; return loadstring(a)(b) end
   """

INIT = (
    "--[[\n        Luarmor V4 bootstrapper for scripts.\n]]--"
    + 'superflow_bytecode={"\\136\\221\\229\\183"}'
    + "x=1;"
    + "return setmetatable({[80]=unpack,[31]=bit32.bxor},{}):TK()(...);"
)
INIT_NOARG = INIT.replace(":TK()(...);", ":TK();")


class StubTest(unittest.TestCase):
    def test_parse_stub(self):
        s = L.parse_stub(STUB)
        self.assertEqual(s["module_id"], "f07dbcbe19a-sephal")
        self.assertEqual(s["init_url"], "https://cdn.luarmor.net/v4_init_sephal.lua")
        self.assertIn("_bsdata0={339253403", s["bsdata0_line"])

    def test_parse_bsdata0(self):
        bs = L.parse_bsdata0(L.parse_stub(STUB)["bsdata0_line"])
        self.assertEqual(len(bs), 12)
        self.assertEqual(bs[1], 339253403)
        self.assertEqual(bs[2], bytes([164, 109, 57]))
        self.assertEqual(bs[7], b"72b8b951637a")
        self.assertEqual(bs[10], bytes([218, 157, 138]))
        self.assertEqual(bs[12], 71740338)

    def test_parse_stub_rejects_non_luarmor(self):
        with self.assertRaises(ValueError):
            L.parse_stub("print('hello world')")


class InitTest(unittest.TestCase):
    def test_parse_init_shapes(self):
        for text in (INIT, INIT_NOARG):
            ini = L.parse_init(text)
            self.assertEqual(ini["blob"], 'superflow_bytecode={"\\136\\221\\229\\183"}')
            self.assertIn('return setmetatable({[80]=unpack,[31]=bit32.bxor},{})', ini["chunk"])
            self.assertIn(':TK()(__MODULE_ID__);', ini["chunk"])

    def test_build_input(self):
        s = L.parse_stub(STUB)
        ini = L.parse_init(INIT)
        text = L.build_input(s, ini, "f07dbcbe19a-sephal", "KEY123", "INITTEXT")
        lines = text.split("\n")
        self.assertEqual(lines[0], 'script_key="KEY123";')
        self.assertTrue(lines[1].startswith("_bsdata0={339253403"))
        self.assertTrue(lines[2].startswith("superflow_bytecode={"))
        self.assertIn("ldrupd8m=[========[INITTEXT]========];", lines[3])
        # the statement that sits between the blob and the chunk in the init
        # file is carried over instead of being dropped
        self.assertEqual(lines[4], "x=1;")
        self.assertIn(':TK()("f07dbcbe19a-sephal");', lines[5])

    def test_build_input_default_key(self):
        s = L.parse_stub(STUB)
        ini = L.parse_init(INIT)
        text = L.build_input(s, ini, "f07dbcbe19a-sephal", None, "x")
        self.assertTrue(text.startswith('script_key="'))  # placeholder filled

    def test_parse_init_keeps_blob_runtime_concat(self):
        """The blob's last element embeds a runtime concat with _bsdata0[10]
        (LUARMOR_NOTES.md section 12) -- the concat must survive parsing."""
        text = ('superflow_bytecode={"\\136\\221"}.._bsdata0[10];'
                + "return setmetatable({[1]=x},{}):TK()(...);")
        ini = L.parse_init(text)
        self.assertIn(".._bsdata0[10]", ini["blob_stmt"])
        s = L.parse_stub(STUB)
        built = L.build_input(s, ini, "f07dbcbe19a-sephal", "KEY123", "T")
        self.assertIn(".._bsdata0[10]", built)
        # the concat must sit right after the table literal, and _bsdata0 before it
        self.assertLess(built.index("_bsdata0={"), built.index(".._bsdata0[10]"))

    def test_parse_init_concat_does_not_swallow_the_chunk(self):
        """A concat with no statement terminator must not eat the VM chunk."""
        text = ('superflow_bytecode={"\\136\\221"}.._bsdata0[10]'
                + "return setmetatable({[1]=x},{}):TK()(...);")
        ini = L.parse_init(text)
        self.assertIn("return setmetatable", ini["chunk"])
        self.assertIn(":TK()(__MODULE_ID__);", ini["chunk"])

    def test_parse_init_multiline_blob(self):
        text = ('superflow_bytecode={\n"\\136\\221"\n}\n'
                + "return setmetatable({[1]=x},{}):TK()(...);")
        ini = L.parse_init(text)
        self.assertIn("\\136", ini["blob"])
        self.assertIn("return setmetatable", ini["chunk"])

    def test_parse_init_brace_inside_string(self):
        """A '}' inside a blob string must not end the table."""
        text = ('superflow_bytecode={"a}b","\\136"}'
                + "return setmetatable({[1]=x},{}):TK()(...);")
        ini = L.parse_init(text)
        self.assertTrue(ini["blob"].endswith('"\\136"}'))

    def test_parse_init_keeps_interleaved_statements(self):
        text = ('superflow_bytecode={"\\136"}'
                + "superflow_bytecode=superflow_bytecode.._bsdata0[10];"
                + "return setmetatable({[1]=x},{}):TK()(...);")
        ini = L.parse_init(text)
        self.assertIn("_bsdata0[10]", ini["extra"])
        s = L.parse_stub(STUB)
        built = L.build_input(s, ini, "f07dbcbe19a-sephal", "KEY123", "T")
        self.assertIn("superflow_bytecode=superflow_bytecode.._bsdata0[10];", built)

    def test_parse_init_rejects_non_luarmor(self):
        with self.assertRaises(ValueError):
            L.parse_init("print('hello world')")


class TimePinTest(unittest.TestCase):
    def test_time_pin_picks_epoch(self):
        import time
        now = int(time.time())
        stub = "_bsdata0={1,%d,2};" % (now - 3600)
        self.assertEqual(L.loader_time_pin(stub), now - 3600)

    def test_time_pin_falls_back_to_now(self):
        import time
        pin = L.loader_time_pin("_bsdata0={1,2,3};")
        self.assertAlmostEqual(pin, int(time.time()), delta=5)


class HandshakeTest(unittest.TestCase):
    def test_extract_handshake(self):
        raw = ('Url = "https://x.luarmor.net/a9b90889ea88d2a9cfaac?a=fa6607'
               '&d=abcd&b=1234"\n--   https://other.example/x\n'
               'Error: State848\nError: State848\nScreenGui\nLocalPlayer:Kick("x")')
        hs = L.extract_handshake(raw)
        self.assertEqual(hs["a"], "fa6607")
        self.assertEqual(hs["d"], "abcd")
        self.assertEqual(hs["b"], "1234")
        self.assertEqual(hs["states"], ["State848"])
        self.assertTrue(hs["gui"])
        self.assertTrue(hs["kicked"])
        self.assertIn("https://other.example/x", hs["urls"])

    def test_extract_handshake_prefers_the_signed_url(self):
        """Other URLs get logged too (CDN init, region hosts); the handshake is
        the one carrying the a/d/b signature, not simply the first URL."""
        raw = ('Url = "https://cdn.luarmor.net/v4_init_sephal.lua"\n'
               'Url = "https://x.luarmor.net/abc?a=fa6607&d=abcd&b=1234"\n')
        hs = L.extract_handshake(raw)
        self.assertEqual(hs["url"], "https://x.luarmor.net/abc?a=fa6607&d=abcd&b=1234")
        self.assertEqual(hs["b"], "1234")

    def test_extract_handshake_region_host(self):
        """The auth host is not hardcoded to x.luarmor.net."""
        raw = 'Url = "https://us1-roblox-auth.luarmor.net/eu1/auth/abc/init?a=1&b=2&d=3"\n'
        hs = L.extract_handshake(raw)
        self.assertIsNotNone(hs["url"])
        self.assertEqual(hs["a"], "1")
        self.assertEqual(hs["b"], "2")
        self.assertEqual(hs["d"], "3")

    def test_extract_handshake_ignores_unsigned_urls(self):
        """Without a signed handshake there is nothing to replay, so url stays
        None -- replaying an arbitrary logged URL would hit the wrong endpoint."""
        raw = 'Url = "https://cdn.luarmor.net/v4_init_sephal.lua"\n'
        hs = L.extract_handshake(raw)
        self.assertIsNone(hs["url"])
        self.assertIsNone(hs["b"])
        self.assertEqual(hs["logged_urls"], ["https://cdn.luarmor.net/v4_init_sephal.lua"])


if __name__ == "__main__":
    unittest.main()
