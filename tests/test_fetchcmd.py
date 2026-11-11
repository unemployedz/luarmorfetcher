# Tool by @adi.codz (Discord)
"""Unit tests for luarmor_crack.fetchcmd (the Discord bot's `.fetch` logic).

The fixture is a real v4 loader stub, so the parser is exercised against the
shape it actually meets in the wild (binary `_bsdata0` entries, an `-ocend`
flavour module id, a `v4_init_ocendmz.lua` CDN init).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from luarmor_crack import fetchcmd as F  # noqa: E402

STUB = r"""-- Do not save this file
-- Always use the loadstring
  _bsdata0={1794418134,7057464,36850880,1449550953,"\4\233\255\228\28\152\133\157\151\78\77\230\228\180\7\36\34\163\193\39\176\107\233\166\16\114",16625313,3667491784,"\14\230\49\215\99\98\12\155\47\51\221\237\250\199\86\35\110\133\164\90\187\56\29\126\24","03a3d920dcb513dd4a208d84c207a660c9aefcc7a4875ad45bca1bc0132a85d3a161727185e7a25547667c2be024fc6192263950860094de265e83cf9c714ee8280746df13016f852e6d2948f53cc46b79898a58ffc5a5f6eef5f4c3fb13455f5b679f66e1a6d2eaaa962d6719543c4b0335eacc0f00aca2ad0406a4fc03982c84962cbbb4e119cf70854d145556c5e53b18b06f974a9c98e4dc507859d7384402039df16268acc4551c0f52d73814959ac2c7f358907677824454c429b192365cd7fd64002a6b7d14fa8d45d4a3dbd55ffa9c7c0b3225f4",8438972,"47ff37f515eea743c0f657f14906547860196e152c0371c0c9543490fccdf088ae495ae634e636132a5e67ff6e0e71540939017ff2089a0148dd3827df8be1de59c551d25803",14706162};
local f,b,a="static_content_170926","a8a80fe17b2-ocend";pcall(function()a=readfile(f.."/init-"..b..".lua")end) if a and #a>2000 then a=loadstring(a) else a=nil; end;
if a then return a() else pcall(makefolder,f) a=game:HttpGet("https://cdn.luarmor.net/v4_init_ocendmz.lua"..(_ca920af6193 or "")) writefile(f.."/init-"..b..".lua", a); ldrupd8m=a; return loadstring(a)(b) end
"""

EXAMPLE_URL = ("https://api.luarmor.net/files/v4/loaders/"
               "b477c6c716098ac8ffb336fe5b96b796.lua")


class ExtractUrlTest(unittest.TestCase):
    def test_canonical_url(self):
        self.assertEqual(F.extract_loader_url(EXAMPLE_URL), EXAMPLE_URL)

    def test_url_inside_a_sentence(self):
        msg = "hey can u fetch %s for me thanks" % EXAMPLE_URL
        self.assertEqual(F.extract_loader_url(msg), EXAMPLE_URL)

    def test_url_with_trailing_punctuation(self):
        self.assertEqual(F.extract_loader_url("see %s." % EXAMPLE_URL), EXAMPLE_URL)

    def test_bare_hash(self):
        self.assertEqual(
            F.extract_loader_url("b477c6c716098ac8ffb336fe5b96b796"),
            EXAMPLE_URL)

    def test_rejects_unrelated_text(self):
        self.assertIsNone(F.extract_loader_url("hello there"))
        self.assertIsNone(F.extract_loader_url("https://example.com/index.html"))
        self.assertIsNone(F.extract_loader_url(""))

    def test_rejects_a_non_loader_luarmor_url(self):
        self.assertIsNone(
            F.extract_loader_url("https://cdn.luarmor.net/v4_init_ocendmz.lua"))


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.report = F.describe_loader(STUB, EXAMPLE_URL)

    def test_identifiers(self):
        self.assertEqual(self.report["module_id"], "a8a80fe17b2-ocend")
        self.assertEqual(self.report["init_url"],
                         "https://cdn.luarmor.net/v4_init_ocendmz.lua")
        self.assertEqual(self.report["cache_path"],
                         "static_content_170926/init-a8a80fe17b2-ocend.lua")
        self.assertEqual(self.report["url"], EXAMPLE_URL)

    def test_bsdata0_entries(self):
        self.assertEqual(self.report["entry_count"], 12)
        self.assertEqual(self.report["kind_counts"], {"int": 8, "binary": 4})
        first = self.report["entries"][0]
        self.assertEqual(first["index"], 1)
        self.assertEqual(first["kind"], "int")
        self.assertEqual(first["value"], 1794418134)
        fifth = self.report["entries"][4]
        self.assertEqual(fifth["kind"], "binary")
        self.assertEqual(fifth["size"], 26)
        self.assertTrue(fifth["preview"].startswith("04e9ffe4"))

    def test_build_stamp_is_an_epoch(self):
        self.assertIsInstance(self.report["time_pin"], int)
        self.assertGreater(self.report["time_pin"], 1600000000)

    def test_rejects_a_non_loader(self):
        with self.assertRaises(ValueError):
            F.describe_loader("print('hello world')")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.report = F.describe_loader(STUB, EXAMPLE_URL)

    def test_summary_lines(self):
        labels = [label for label, _ in F.summary_lines(self.report)]
        self.assertIn("module id", labels)
        self.assertIn("_bsdata0", labels)
        blob = dict(F.summary_lines(self.report))["_bsdata0"]
        self.assertIn("12 entries", blob)
        self.assertIn("8 int", blob)
        self.assertIn("4 binary", blob)

    def test_render_entries(self):
        text = F.render_entries(self.report)
        self.assertIn("[ 1] int", text)
        self.assertIn("[ 5] binary", text)
        self.assertIn("26 B", text)

    def test_render_raw_block(self):
        block = F.render_raw_block(self.report)
        self.assertTrue(block.startswith("```lua"))
        self.assertIn("_bsdata0", block)
        self.assertIn("a8a80fe17b2-ocend", block)

    def test_render_raw_block_truncates(self):
        report = dict(self.report)
        report["raw"] = "x" * 5000
        block = F.render_raw_block(report, limit=100)
        self.assertIn("truncated", block)
        self.assertLess(len(block), 400)

    def test_render_plain_has_everything(self):
        text = F.render_plain(self.report)
        self.assertIn("module id: a8a80fe17b2-ocend", text)
        self.assertIn("_bsdata0", text)
        self.assertIn("```lua", text)


class EmbedSpecTest(unittest.TestCase):
    """The reply must fit Discord's embed limits or the API rejects it."""

    def setUp(self):
        self.report = F.describe_loader(STUB, EXAMPLE_URL)
        self.spec = F.build_embed_spec(self.report)

    def test_limits(self):
        self.assertLessEqual(len(self.spec["title"]), 256)
        self.assertLessEqual(len(self.spec["description"]), F.MAX_EMBED_DESCRIPTION)
        for field in self.spec["fields"]:
            self.assertLessEqual(len(field["name"]), F.MAX_EMBED_FIELD_NAME)
            self.assertLessEqual(len(field["value"]), F.MAX_EMBED_FIELD_VALUE)

    def test_stub_source_is_in_the_description_not_a_field(self):
        """A field value caps at 1024 and a real stub is ~1.3 KB -- the stub
        has to live in the description (4096) or the embed is rejected."""
        self.assertIn("_bsdata0", self.spec["description"])
        self.assertGreater(len(self.spec["description"]), F.MAX_EMBED_FIELD_VALUE)
        for field in self.spec["fields"]:
            self.assertNotIn("superflow_bytecode", field["value"])

    def test_total_under_the_embed_budget(self):
        total = len(self.spec["title"]) + len(self.spec["description"])
        total += sum(len(f["name"]) + len(f["value"]) for f in self.spec["fields"])
        self.assertLessEqual(total, 6000)

    def test_a_huge_stub_is_truncated_not_rejected(self):
        report = dict(self.report)
        report["raw"] = "x" * 20000
        spec = F.build_embed_spec(report)
        self.assertLessEqual(len(spec["description"]), F.MAX_EMBED_DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
