#!/usr/bin/env python3
# Tool by @adi.codz (Discord)
"""Luarmor-Fetch Discord bot -- the ``.fetch`` command.

In Discord:

    .fetch https://api.luarmor.net/files/v4/loaders/<md5>.lua
    .fetch                      ... then paste the link in your next message

``.fetch`` downloads Luarmor's public v4 loader stub and replies with its main
content: the module id, the CDN init URL, the executor cache path, the build
stamp, the decoded ``_bsdata0`` table, and the stub source itself. Loader
blobs rotate about hourly, so the stub is always fetched live.

Deployment (Render worker, or anywhere with Python 3.9+):

    pip install -r requirements.txt
    DISCORD_TOKEN=... python bot.py

The bot needs the privileged **Message Content** intent enabled for it in the
Discord developer portal (Bot -> Privileged Gateway Intents), otherwise it
cannot read the pasted link.
"""
import asyncio
import logging
import io
import os
import sys
import time

import discord
from discord.ext import commands

from luarmor_crack import common, fetchcmd

LOG = logging.getLogger("luarmor-fetch-bot")

PREFIX = os.environ.get("LRM_PREFIX", ".")
# how long a bare `.fetch` waits for the pasted link
PENDING_TTL = float(os.environ.get("LRM_PENDING_TTL", "180"))

HELP_TEXT = """**Luarmor-Fetch bot**

`.fetch <loader-url>` -- fetch a Luarmor v4 loader stub and show its main
content (module id, init URL, cache path, build stamp, decoded `_bsdata0`).
Send `.fetch` on its own and paste the link in your next message.

Loader URL:
`https://api.luarmor.net/files/v4/loaders/<md5>.lua`

Loader blobs rotate about hourly -- always fetch a fresh one.
"""


class FetchBot(commands.Bot):
    """A bot with one job: resolve a pasted loader link and report it."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fetch_command = FetchBot.fetch
        self.add_command(commands.Command(
            fetch_command.callback.__get__(self, type(self)),
            name="fetch",
            help="Fetch a Luarmor v4 loader stub and show its content.",
        ))
        # (channel_id, author_id) -> deadline; a bare `.fetch` arms one slot
        self.pending = {}

    async def setup_hook(self):
        # Discord's Message Content intent is privileged; without it the bot
        # sees empty message bodies and the pasted link never resolves.
        intents = self.intents
        if not intents.message_content:
            LOG.warning("the Message Content intent is not enabled -- "
                        "pasted links will not be readable")

    async def on_ready(self):
        LOG.info("logged in as %s (prefix %r)", self.user, PREFIX)
        print("Luarmor-Fetch bot ready -- prefix %r, command: .fetch" % PREFIX,
              flush=True)

    # -- the command ---------------------------------------------------------
    @commands.command(name="fetch",
                      help="Fetch a Luarmor v4 loader stub and show its content.")
    async def fetch(self, ctx, *, url=None):
        if not url:
            key = (ctx.channel.id, ctx.author.id)
            self.pending[key] = time.time() + PENDING_TTL
            LOG.info("armed follow-up for channel=%s author=%s ttl=%ss",
                     ctx.channel.id, ctx.author.id, PENDING_TTL)
            await ctx.reply("Paste the loader link here -- e.g.\n"
                            "`https://api.luarmor.net/files/v4/loaders/<md5>.lua`")
            return
        found = fetchcmd.extract_loader_url(url)
        if not found:
            await ctx.reply("That is not a loader link. Expected\n"
                            "`https://api.luarmor.net/files/v4/loaders/<md5>.lua`")
            return
        await self._report(ctx, found)

    @commands.command(name="help", help="Show how to use the bot.")
    async def help_cmd(self, ctx):
        await ctx.send(HELP_TEXT)

    # -- the pasted-link follow-up ------------------------------------------
    async def on_message(self, message):
        await self.process_commands(message)
        if message.author.bot:
            return
        # A command that arms a pending link must not be re-processed as
        # the link itself during this same on_message event.
        if message.content.strip().startswith(PREFIX):
            return
        key = (message.channel.id, message.author.id)
        deadline = self.pending.get(key)
        if deadline is None:
            return

        LOG.info("received pending follow-up: channel=%s author=%s chars=%s",
                 message.channel.id, message.author.id, len(message.content))

        if time.time() > deadline:
            self.pending.pop(key, None)
            LOG.info("follow-up expired: channel=%s author=%s",
                     message.channel.id, message.author.id)
            return

        found = fetchcmd.extract_loader_url(message.content)
        if not found:
            # not a link -- keep the slot armed so a real paste still lands
            self.pending[key] = time.time() + PENDING_TTL
            LOG.info("follow-up did not contain a recognized loader URL")
            await message.reply("That does not look like a loader link -- paste the "
                                "`https://api.luarmor.net/files/v4/loaders/<md5>.lua` URL.")
            return

        self.pending.pop(key, None)
        LOG.info("recognized loader URL in follow-up; starting fetch")
        try:
            await self._report(message, found)
        except Exception:
            LOG.exception("unexpected error while handling pasted loader URL")
            await message.reply("The bot hit an internal error while handling that link. "
                                "Check the Render logs for the traceback.")

    # -- shared reporting ----------------------------------------------------
    async def _report(self, ctx, url):
        """Fetch the stub and reply with its main content."""
        # Both commands.Context and discord.Message expose .channel, but the
        # typing indicator belongs to the channel (not Message itself).
        async with ctx.channel.typing():
            try:
                _status, body = await asyncio.to_thread(common.http_get, url)
            except Exception as e:                      # network / HTTP failure
                await ctx.reply("Fetch failed: %s" % e)
                return
            try:
                report = fetchcmd.describe_loader(body, url)
            except ValueError as e:
                await ctx.reply("That URL did not return a Luarmor v4 loader stub (%s)." % e)
                return
        # Send the fetched public loader stub as a .lua attachment only.
        # Do not print its contents in a Discord embed or code block.
        module_id = report.get("module_id") or "loader"
        safe_module_id = "".join(
            char for char in str(module_id) if char.isalnum() or char in "-_"
        )[:64] or "loader"
        payload = io.BytesIO(report["raw"].encode("utf-8"))
        attachment = discord.File(
            fp=payload,
            filename="luarmor-%s.lua" % safe_module_id,
        )
        await ctx.reply(file=attachment)

    @staticmethod
    def _embed(report):
        """Build the reply embed from the pure spec in fetchcmd."""
        spec = fetchcmd.build_embed_spec(report)
        embed = discord.Embed(title=spec["title"], url=spec["url"],
                              description=spec["description"], color=0x2F3136)
        for field in spec["fields"]:
            embed.add_field(name=field["name"], value=field["value"],
                            inline=field["inline"])
        embed.set_footer(text=spec["footer"])
        return embed


def build_bot():
    intents = discord.Intents.default()
    intents.message_content = True      # required to read a pasted link
    return FetchBot(command_prefix=PREFIX, intents=intents,
                    help="Luarmor-Fetch: fetch a Luarmor v4 loader stub")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        print("DISCORD_TOKEN is not set -- export it before starting the bot.",
              file=sys.stderr)
        return 1
    bot = build_bot()
    bot.run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
