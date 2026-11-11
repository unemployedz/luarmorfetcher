"""Mock `discord` package so bot.py can be exercised without discord.py installed.

It implements just enough of the API bot.py touches (Intents, Embed,
commands.Bot, commands.command, a ctx with reply/send/typing) to run the
command flow end to end -- so the bot's wiring is covered by the unit tests
without pulling in the library.
"""
import sys
import types


class _Intents:
    def __init__(self):
        self.message_content = False

    @classmethod
    def default(cls):
        return cls()


class Embed:
    def __init__(self, title=None, url=None, description=None, color=0):
        self.title, self.url, self.description, self.color = title, url, description, color
        self.fields, self.footer = [], None

    def add_field(self, name, value, inline=True):
        self.fields.append({"name": name, "value": value, "inline": inline})

    def set_footer(self, text):
        self.footer = text


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Ctx:
    """A stand-in for discord's Context that records what was sent."""

    def __init__(self, channel_id=1, author_id=2, content=""):
        self.channel, self.author = _Channel(channel_id), _Author(author_id)
        self.content = content
        self.replies, self.sent = [], []

    def typing(self):
        return _Typing()

    async def reply(self, text=None, **kw):
        self.replies.append(text)

    async def send(self, content=None, embed=None, **kw):
        self.sent.append({"content": content, "embed": embed, "kw": kw})


class _Channel:
    def __init__(self, cid):
        self.id = cid


class _Author:
    def __init__(self, aid):
        self.id = aid
        self.bot = False


def _make_command_module():
    m = types.ModuleType("discord.ext.commands")

    class Bot:
        def __init__(self, command_prefix=None, intents=None, help=None, **kw):
            self.command_prefix = command_prefix
            self.intents = intents
            self.help = help
            self.pending = {}

        def run(self, token, **kw):
            self.token = token

        async def process_commands(self, message):
            return None

    def command(name=None, help=None, **kw):
        def deco(fn):
            fn.__command_name__ = name or fn.__name__
            return fn
        return deco

    m.Bot = Bot
    m.command = command
    return m


def install():
    d = types.ModuleType("discord")
    d.Intents = _Intents
    d.Embed = Embed
    ext = types.ModuleType("discord.ext")
    ext.commands = _make_command_module()
    d.ext = ext
    sys.modules["discord"] = d
    sys.modules["discord.ext"] = ext
    sys.modules["discord.ext.commands"] = ext.commands
    return d
