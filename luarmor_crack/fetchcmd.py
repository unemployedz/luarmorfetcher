# Tool by @adi.codz (Discord)
"""Pure logic behind the Discord bot's ``.fetch`` command.

Nothing here imports discord.py: URL extraction, the loader parse and the
report rendering are plain functions, so they stay unit-testable without the
bot runtime and the CLI keeps its standard-library-only guarantee.

The command works on Luarmor's *public* v4 loader stub -- the ungated 5-line
file at ``api.luarmor.net/files/v4/loaders/<md5>.lua``. It reports what the
stub contains; it does not touch keys, licenses or the auth handshake.
"""
import re
import time

from .loader import loader_time_pin, parse_bsdata0, parse_stub

# The canonical v4 loader URL. Loader blobs rotate roughly hourly, so the
# stub must be fetched fresh; a saved copy goes stale within the hour.
LOADER_URL_TEMPLATE = "https://api.luarmor.net/files/v4/loaders/%s.lua"

CANONICAL_URL_RE = re.compile(
    r"https?://api\.luarmor\.net/files/v4/loaders/([0-9a-fA-F]{8,64})\.lua")
ANY_URL_RE = re.compile(r"https?://[^\s<>\"'`]+")
LOADER_PATH_RE = re.compile(r"^https?://[^\s]+/loaders/[^\s]+\.lua$")
BARE_HASH_RE = re.compile(r"\b([0-9a-fA-F]{32})\b")

# `local f,b,a="static_content_170926","<module>-<flavour>";` in the stub
STUB_LOCAL_RE = re.compile(r'local\s+f\s*,\s*b\s*,\s*a\s*=\s*"([^"]*)"\s*,\s*"([^"]*)"')

# Discord embed limits. The stub source goes in the *description* (4096),
# never in a field -- a field value caps at 1024 and a real stub is ~1.3 KB.
MAX_EMBED_DESCRIPTION = 4096
MAX_EMBED_FIELD_NAME = 256
MAX_EMBED_FIELD_VALUE = 1024
MAX_RAW_BLOCK = 3500


def _fence(text):
    """Wrap a value in a code fence, staying inside the field-value limit."""
    body = "```\n%s\n```" % text
    if len(body) > MAX_EMBED_FIELD_VALUE:
        body = body[: MAX_EMBED_FIELD_VALUE - 3] + "\n```"
    return body


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------
def extract_loader_url(text):
    """Pull a Luarmor loader URL out of a message.

    Accepts the canonical ``api.luarmor.net/files/v4/loaders/<md5>.lua``, any
    other ``*/loaders/*.lua`` URL, or a bare 32-char md5 hash. Returns None
    when the text carries no loader reference at all.
    """
    if not text:
        return None
    m = CANONICAL_URL_RE.search(text)
    if m:
        return m.group(0)
    for m in ANY_URL_RE.finditer(text):
        url = m.group(0).rstrip(".,);]}\"'")
        if LOADER_PATH_RE.match(url):
            return url
    m = BARE_HASH_RE.search(text)
    if m:
        return LOADER_URL_TEMPLATE % m.group(1)
    return None


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------
def describe_loader(text, url=None):
    """Parse a loader stub into a structured report.

    Raises ValueError when the text is not a Luarmor v4 loader stub, so the
    caller can tell the user "that was not a loader" instead of dumping a
    half-parsed result.
    """
    stub = parse_stub(text)
    bs = parse_bsdata0(stub["bsdata0_line"])

    entries = []
    for idx in sorted(bs):
        value = bs[idx]
        if isinstance(value, int):
            entries.append({"index": idx, "kind": "int", "size": 4,
                            "value": value, "preview": str(value)})
        else:
            hexed = value.hex()
            entries.append({
                "index": idx, "kind": "binary", "size": len(value),
                "value": None,
                "preview": hexed[:48] + ("..." if len(hexed) > 48 else ""),
            })

    local = STUB_LOCAL_RE.search(text)
    cache_dir = local.group(1) if local else "static_content_170926"

    return {
        "url": url,
        "module_id": stub["module_id"],
        "init_url": stub["init_url"],
        "cache_path": "%s/init-%s.lua" % (cache_dir, stub["module_id"]),
        "time_pin": loader_time_pin(text),
        "entries": entries,
        "entry_count": len(entries),
        "kind_counts": _kind_counts(entries),
        "raw": text,
        "bytes": len(text.encode("latin-1", errors="replace")),
    }


def _kind_counts(entries):
    counts = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


def format_stamp(epoch):
    """Render a build stamp as a UTC string (epoch seconds)."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(epoch)))
    except (TypeError, ValueError, OSError):
        return "?"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def summary_lines(report):
    """The summary as ``(label, value)`` pairs -- embed fields, or plain text."""
    counts = report["kind_counts"]
    kinds = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))
    lines = [
        ("module id", report["module_id"] or "-"),
        ("init url", report["init_url"] or "-"),
        ("cache path", report["cache_path"]),
        ("build stamp", "%s\n%s" % (report["time_pin"],
                                    format_stamp(report["time_pin"]))),
        ("_bsdata0", "%d entries (%s)" % (report["entry_count"], kinds)),
    ]
    return lines


def render_entries(report, limit=12):
    """The decoded ``_bsdata0`` table as plain text lines."""
    out = []
    for e in report["entries"][:limit]:
        if e["kind"] == "int":
            out.append("  [%2d] int     %s" % (e["index"], e["preview"]))
        else:
            out.append("  [%2d] binary  %d B  %s" % (e["index"], e["size"],
                                                      e["preview"]))
    if report["entry_count"] > limit:
        out.append("  ... %d more" % (report["entry_count"] - limit))
    return "\n".join(out)


def render_raw_block(report, limit=MAX_RAW_BLOCK):
    """The stub source as a fenced code block, truncated to fit an embed."""
    raw = report["raw"].rstrip()
    truncated = False
    if len(raw) > limit:
        raw = raw[:limit].rsplit("\n", 1)[0]
        truncated = True
    block = "```lua\n%s\n```" % raw
    if truncated:
        block += "\n*(truncated -- full stub attached as a file)*"
    return block


def render_plain(report):
    """A single plain-text block with everything, for non-embed contexts."""
    head = ["%s: %s" % (label, value) for label, value in summary_lines(report)]
    return "\n".join(head + ["", render_entries(report), "", render_raw_block(report)])


def build_embed_spec(report):
    """The reply, as a plain dict -- title/url/description/fields/footer.

    Kept free of discord.py so the Discord limits can be asserted in a unit
    test without the bot runtime. ``bot.py`` turns this into an ``Embed``.
    """
    fields = []
    for label, value in summary_lines(report):
        fields.append({"name": label[:MAX_EMBED_FIELD_NAME],
                       "value": _fence(value), "inline": False})
    fields.append({"name": "_bsdata0 entries",
                   "value": _fence(render_entries(report)),
                   "inline": False})
    description = render_raw_block(report, MAX_EMBED_DESCRIPTION - 200)
    return {
        "title": "Luarmor loader -- %s" % (report["module_id"] or "?")[:256],
        "url": report["url"],
        "description": description,
        "fields": fields,
        "footer": "%d bytes -- loader blobs rotate about hourly" % report["bytes"],
    }
