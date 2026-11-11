# Tool by @adi.codz (Discord)
"""Stage 1-2 parsing and input assembly for the Luarmor v4 bootstrap.

Everything in this module is pure: it transforms the loader stub text and the
sephal init text into the primed source the sandbox runs, plus small helpers
(time-pin derivation, handshake extraction) used by the fetcher. No I/O, no
sandbox, no network -- which keeps it fully unit-testable.

Protocol reference: docs/LUARMOR_NOTES.md sections 11-15.
"""
import re
import time

from .common import decode_lua_escapes


# ---------------------------------------------------------------------------
# stage 1: the loader stub (api.luarmor.net/files/v4/loaders/<md5>.lua)
# ---------------------------------------------------------------------------
def parse_stub(text):
    """The 5-line unobfuscated v4 stub -> {bsdata0_line, module_id, init_url}."""
    m = re.search(r'(_bsdata0=\{.*?\};)', text, re.S)
    if not m:
        raise ValueError("no _bsdata0 line in the loader stub "
                         "(is this a Luarmor v4 loader?)")
    bs_line = m.group(1).strip()

    m = re.search(r'"([0-9a-f]+-sephal)"', text)
    module_id = m.group(1) if m else None
    if not module_id:
        m = re.search(r'local f,b,a="[^"]+","([^"]+)"', text)
        module_id = m.group(1) if m else None
    if not module_id:
        raise ValueError("no module id in the loader stub")

    m = re.search(r'game:HttpGet\("([^"]+)"', text)
    init_url = m.group(1) if m else None

    return {"bsdata0_line": bs_line, "module_id": module_id,
            "init_url": init_url, "stub": text}


def parse_bsdata0(line):
    """The _bsdata0 table literal -> Lua-style 1-indexed dict of ints / bytes."""
    m = re.search(r"_bsdata0=\{(.*?)\};", line, re.S)
    if not m:
        raise ValueError("no _bsdata0 table literal to parse")
    body = m.group(1)
    parts, cur, inq, esc = [], "", False, False
    for ch in body:
        if inq:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                inq = False
        elif ch == '"':
            inq = True
            cur += ch
        elif ch == ",":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)

    def conv(p):
        p = p.strip()
        if p.startswith('"'):
            return decode_lua_escapes(p[1:-1])
        return int(p)

    return {i + 1: conv(p) for i, p in enumerate(parts)}


# ---------------------------------------------------------------------------
# stage 2: the sephal init (v4_init_sephal.lua, a Luraph v15 chunk itself)
# ---------------------------------------------------------------------------
def _scan_table(text, start):
    """Return the index just past the ``}`` closing the table opened at
    ``text[start] == '{'`` (or -1 if it never closes).

    Quote- and escape-aware, so a ``}`` inside a string value does not end the
    table. The old regex (\\{.*?\\}) stopped at the first ``}`` and silently
    truncated the blob.
    """
    depth = 0
    i = start
    n = len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _scan_statement(text, start, limit):
    """Return the index just past the end of the statement starting at
    ``text[start]`` (the first ``;`` at bracket depth 0, or ``limit``). Used to
    capture a trailing ``.. _bsdata0[10]`` concat that belongs to the blob
    assignment. Never scans past ``limit``."""
    i = start
    depth = 0
    quote = None
    while i < limit:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth <= 0:
            return i + 1
        i += 1
    return limit


def parse_init(text):
    """The sephal init -> {blob, blob_stmt, extra, prelude, chunk}.

    Layout: a short header comment, then ``superflow_bytecode={...}`` (the
    ~9.6 KB encrypted program as a global table), then the Luraph v15 VM chunk
    starting at ``return setmetatable({``. Everything may sit on one line.

    Two shapes must survive parsing (LUARMOR_NOTES.md section 12):

    * the blob assignment may continue with a runtime concat -- the last
      element embeds ``_bsdata0[10]``, so the table literal is not the whole
      statement (``superflow_bytecode={...}.._bsdata0[10]``);
    * statements may sit between the blob and the chunk.

    Both used to be dropped by the old non-greedy regex, which silently
    truncated the blob at the first ``}`` and discarded everything between the
    blob and the chunk. ``blob`` is kept as the table literal alone for
    callers that only want the table; ``blob_stmt`` is the whole assignment;
    ``extra`` holds the interleaved statements; ``prelude`` is the two
    concatenated, in source order.

    The chunk's final ``:TK()`` call is normalized to receive the module id as
    its vararg, mirroring the stub's ``loadstring(a)(module_id)`` fresh path.
    """
    m = re.search(r"superflow_bytecode\s*=", text)
    if not m:
        raise ValueError("no superflow_bytecode table in the init (wrong file?)")
    cm = re.search(r"return setmetatable\(\{", text)
    if not cm:
        raise ValueError("no VM chunk (`return setmetatable`) in the init")
    brace = text.find("{", m.end(), cm.start())
    if brace < 0 or text[m.end():brace].strip():
        raise ValueError("superflow_bytecode is not a table literal in the init")
    end = _scan_table(text, brace)
    if end < 0 or end > cm.start():
        raise ValueError("unterminated superflow_bytecode table in the init")
    blob = text[m.start():end]

    # the assignment may continue past the table literal (a `..` concat)
    stmt_end = end
    concat = re.match(r"\s*\.\.", text[end:cm.start()])
    if concat:
        stmt_end = _scan_statement(text, end + concat.end(), cm.start())
    blob_stmt = text[m.start():stmt_end].rstrip().rstrip(";")

    chunk = text[cm.start():]
    chunk = re.sub(r":TK\(\)\s*\([^;]*\)\s*;?\s*$", ':TK()(__MODULE_ID__);', chunk)
    chunk = re.sub(r":TK\(\)\s*;?\s*$", ':TK()(__MODULE_ID__);', chunk)
    if not chunk.rstrip().endswith(';'):
        chunk = chunk.rstrip() + ';'
    extra = text[stmt_end:cm.start()].strip().lstrip(";").strip()
    return {"blob": blob, "blob_stmt": blob_stmt, "extra": extra,
            "prelude": blob_stmt + (("\n" + extra) if extra else ""),
            "chunk": chunk.rstrip()}


def build_input(stub, init, module_id, script_key, init_text):
    """Stub-faithful primed source assembled in the exact order the loader's
    fresh-download path uses: script_key, _bsdata0, superflow blob, ldrupd8m
    (the raw init text the stub sets only on fresh downloads), then the VM chunk
    with the module id passed as its vararg.

    The _bsdata0-before-blob order matters: the blob's last element embeds a
    runtime concat with _bsdata0[10] (LUARMOR_NOTES.md section 12).

    Any statement that sat between the blob and the chunk in the init file is
    carried over too -- it used to be dropped by the parser, which silently
    produced a primed input missing part of the bootstrap.
    """
    key = script_key or "A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6"
    chunk = init["chunk"].replace('__MODULE_ID__', '"%s"' % module_id)
    blob_stmt = init.get("blob_stmt") or init["blob"]
    extra = init.get("extra") or ""
    parts = [
        'script_key="%s";' % key,
        stub["bsdata0_line"],
        blob_stmt,
        "ldrupd8m=[========[" + init_text + "]========];",
    ]
    if extra:
        parts.append(extra)
    parts.append(chunk)
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# sandbox-clock pinning (the loader's build stamp)
# ---------------------------------------------------------------------------
def loader_time_pin(stub_text):
    """Derive the sandbox clock from the loader's build timestamp.

    _bsdata0 carries a ~now epoch entry that rotates with the loader file. A
    stale time_pin skews the bootstrap's clock vs the server (hours after a
    container reset) and the session validation rejects -> State848. Falls back
    to wall-clock now when no plausible epoch entry is present."""
    now = int(time.time())
    m = re.search(r"_bsdata0=\{([^}]*)\}", stub_text)
    if m:
        for n in re.findall(r"\d{9,10}", m.group(1)):
            v = int(n)
            if abs(v - now) < 4 * 86400:
                return v
    return now


# ---------------------------------------------------------------------------
# trace parsing (handshake + behaviour markers)
# ---------------------------------------------------------------------------
def extract_handshake(raw):
    """Pull the captured auth request and behaviour markers from a raw trace.

    The auth request is the logged ``Url = "..."`` that carries the ``a``/``d``/
    ``b`` signature. Other URLs get logged too (the CDN init fetch, region auth
    hosts), so the handshake is picked by its signature rather than by being
    the first URL in the trace -- and by host, not by a hardcoded
    ``x.luarmor.net``, so a region host is recognized as well.

    ``url`` is only set when a signed handshake was seen: it is the URL the
    live replay sends, and replaying an unsigned URL would hit the wrong
    endpoint.
    """
    out = {"url": None, "a": None, "d": None, "b": None, "urls": [], "states": [],
           "loadstrings": [], "logged_urls": []}
    logged = re.findall(r'Url\s*=\s*"(https?://[^"]+)"', raw)
    out["logged_urls"] = logged

    def _params(u):
        return {m.group(1) for m in re.finditer(r"[?&]([a-zA-Z]+)=", u)}

    signed = [u for u in logged if _params(u) & {"a", "b", "d"}]
    chosen = signed[0] if signed else None
    if chosen:
        out["url"] = chosen
        for k in ("a", "d", "b"):
            km = re.search(r"[?&]%s=([^&]*)" % k, chosen)
            if km:
                out[k] = km.group(1)
    out["urls"] = re.findall(r"--   (https?://\S+)", raw)
    out["states"] = sorted(set(re.findall(r"Error: (State\d+)", raw)))
    out["loadstrings"] = re.findall(r"loadstring\(\) of (\d+) bytes", raw)
    out["gui"] = "ScreenGui" in raw
    out["canary"] = "P2D GetLength" in raw
    out["kicked"] = "LocalPlayer:Kick" in raw
    return out
