# Tool by @adi.codz (Discord)
"""Unit tests for the Discord bot (bot.py).

discord.py is not a test dependency: a mock stands in for it (see
mock_discord.py) so the bot's command wiring -- the `.fetch` command, the
paste-the-link follow-up, the error paths -- is covered by the suite without
pulling in the library. The bot's own logic lives in luarmor_crack.fetchcmd
and is tested there.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mock_discord                                    # noqa: E402
mock_discord.install()                                 # noqa: E402

import bot as botmod                                   # noqa: E402
from luarmor_crack import common                      # noqa: E402

from test_fetchcmd import EXAMPLE_URL, STUB           # noqa: E402


def fake_http_get(url, *a, **kw):
    """Stand in for the live GET -- no network in the unit tests."""
    if "0000" in url:
        raise RuntimeError("HTTP 404 from %s (Not Found)" % url)
    return 200, STUB


class BotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(common, "http_get", side_effect=fake_http_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bot = botmod.build_bot()

    # -- the command ---------------------------------------------------------
    async def test_fetch_with_a_url_replies_with_an_embed(self):
        ctx = mock_discord.Ctx()
        await self.bot.fetch(ctx, url=EXAMPLE_URL)
        self.assertEqual(ctx.replies, [])
        self.assertEqual(len(ctx.sent), 1)
        embed = ctx.sent[0]["embed"]
        self.assertIn("a8a80fe17b2-ocend", embed.title)
        self.assertEqual(embed.url, EXAMPLE_URL)
        self.assertIn("_bsdata0", embed.description)

    async def test_fetch_without_a_url_asks_for_the_link(self):
        ctx = mock_discord.Ctx(channel_id=2, author_id=20)
        await self.bot.fetch(ctx)
        self.assertTrue(ctx.replies[0])
        self.assertIn((2, 20), self.bot.pending)

    async def test_fetch_rejects_junk(self):
        ctx = mock_discord.Ctx()
        await self.bot.fetch(ctx, url="not a url")
        self.assertTrue(ctx.replies[0])
        self.assertEqual(ctx.sent, [])

    async def test_fetch_reports_a_fetch_failure(self):
        ctx = mock_discord.Ctx()
        await self.bot.fetch(ctx, url="https://api.luarmor.net/files/v4/loaders/"
                                      + "0" * 32 + ".lua")
        self.assertTrue(ctx.replies[0])
        self.assertIn("Fetch failed", ctx.replies[0])

    async def test_fetch_reports_a_non_loader(self):
        with mock.patch.object(common, "http_get", return_value=(200, "print(1)")):
            ctx = mock_discord.Ctx()
            await self.bot.fetch(ctx, url=EXAMPLE_URL)
        self.assertTrue(ctx.replies[0])
        self.assertIn("did not return", ctx.replies[0])

    # -- the pasted-link follow-up ------------------------------------------
    async def test_pasted_link_completes_the_command(self):
        arm = mock_discord.Ctx(channel_id=3, author_id=30)
        await self.bot.fetch(arm)
        msg = mock_discord.Ctx(channel_id=3, author_id=30)
        msg.content = "here %s" % EXAMPLE_URL
        await self.bot.on_message(msg)
        self.assertEqual(len(msg.sent), 1)
        self.assertIn("a8a80fe17b2-ocend", msg.sent[0]["embed"].title)
        self.assertNotIn((3, 30), self.bot.pending)

    async def test_pasted_non_link_keeps_the_slot_armed(self):
        arm = mock_discord.Ctx(channel_id=4, author_id=40)
        await self.bot.fetch(arm)
        msg = mock_discord.Ctx(channel_id=4, author_id=40)
        msg.content = "hmm, not yet"
        await self.bot.on_message(msg)
        self.assertTrue(msg.replies[0])
        self.assertIn((4, 40), self.bot.pending)

    async def test_expired_slot_is_ignored(self):
        arm = mock_discord.Ctx(channel_id=5, author_id=50)
        await self.bot.fetch(arm)
        self.bot.pending[(5, 50)] = 0.0        # already expired
        msg = mock_discord.Ctx(channel_id=5, author_id=50)
        msg.content = EXAMPLE_URL
        await self.bot.on_message(msg)
        self.assertEqual(msg.sent, [])
        self.assertEqual(msg.replies, [])

    async def test_unrelated_message_does_nothing(self):
        msg = mock_discord.Ctx(channel_id=6, author_id=60)
        msg.content = EXAMPLE_URL
        await self.bot.on_message(msg)
        self.assertEqual(msg.sent, [])
        self.assertEqual(msg.replies, [])

    # -- wiring --------------------------------------------------------------
    def test_intents_and_prefix(self):
        bot = botmod.build_bot()
        self.assertTrue(bot.intents.message_content)
        self.assertEqual(bot.command_prefix, ".")

    async def test_help_command(self):
        ctx = mock_discord.Ctx()
        await self.bot.help_cmd(ctx)
        self.assertTrue(ctx.sent[0]["content"])

    def test_missing_token_is_a_clean_error(self):
        import contextlib
        import io
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stderr(err):
                rc = botmod.main()
        self.assertEqual(rc, 1)
        self.assertIn("DISCORD_TOKEN", err.getvalue())


if __name__ == "__main__":
    unittest.main()
