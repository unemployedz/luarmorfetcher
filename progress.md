# Progress Log

Chronological research/engineering log for Luarmor-Fetch. Newest entries on top.

---

## 2026-11-11 — Discord bot + Render deployment, and a protocol correction

The loader fetch is now available as a Discord command, deployable as a Render
worker, and the repo has been published to
`github.com/unemployedz/luarmorfetcher`.

### The bot

```
.fetch https://api.luarmor.net/files/v4/loaders/<md5>.lua
```

A bare `.fetch` arms a slot and takes the link pasted in the next message
(3-minute window, re-armed if the paste is not a link). The reply is an embed
with the stub's main content: module id, CDN init URL, executor cache path,
build stamp, the decoded `_bsdata0` table, and the stub source.

- `luarmor_crack/fetchcmd.py` — the logic, standard-library only and free of
  any discord.py import, so it stays unit-testable.
- `bot.py` — the thin discord.py adapter.
- `requirements.txt`, `render.yaml`, `.env.example` — deployment.

**One Discord limit bit us and is now asserted by a test:** a field *value*
caps at 1024 characters but the embed *description* allows 4096, and a real
stub is ~1.3 KB. The stub source therefore goes in the description, never in a
field -- as a field the API rejects the whole embed with a 400.

**discord.py is not a test dependency.** PyPI was unreachable from the build
sandbox, so `tests/mock_discord.py` stands in for the library; the bot's
wiring (the command, the paste follow-up, the error paths, the embed limits)
is covered by the suite without it.

### The loader URL is not a content address

The `<md5>` in `api.luarmor.net/files/v4/loaders/<md5>.lua` does not address
content: the CDN answers with the **current rotating stub for any hash**. Both
`0000...0.lua` and `ffff...f.lua` returned a valid 1.2 KB stub with fresh
`_bsdata0` blobs. The hash identifies the paste, nothing more.

Two consequences worth recording:

- The stubs rotate far faster than "about hourly" -- two fetches seconds
  apart came back with different `_bsdata0` values. The bot always fetches
  live, and never caches.
- The current live stub is the **`-ocend` flavour**, not `-sephal`: module id
  `a8a80fe17b2-ocend`, CDN init `v4_init_ocendmz.lua`. The `-sephal` shape in
  the notes is one flavour among others, so `parse_stub` already had to fall
  back to the `local f,b,a=` pattern for the module id -- that fallback is
  what makes the bot work against today's loader.

### Tests

38 -> 69 tests, all green:

```
python -m unittest discover -s tests     # 69/69
```

---

## 2026-11-11 — Review pass: eight defects fixed, 38/38 tests green

A read-through of the whole tool (every module, the CLI and the docs) turned up
eight real defects. All are fixed here, each with a regression test.

### The init parser could silently truncate the blob

`parse_init` matched the blob with `superflow_bytecode=\{.*?\}` — no `re.S`,
non-greedy, and with no statement awareness. Three ways that loses data:

| shape | old | new |
|---|---|---|
| blob spanning two lines | `ValueError` — init rejected | parsed |
| `}` inside a blob string value | truncated at that `}` | parsed |
| `superflow_bytecode={...}.._bsdata0[10]` | concat dropped | concat kept |
| a statement between the blob and the chunk | dropped | kept |

The concat case is the one the protocol notes call out (section 12: the blob's
last element embeds a runtime concat with `_bsdata0[10]`, and the assignment
order matters). The parser now scans the table literal with a quote-aware
brace matcher and carries the blob statement plus any interleaved statements
into the primed input (`blob_stmt` / `extra` / `prelude`).

**No behaviour change on the real input.** Against a section-12-shaped init the
old and the new parser produce a *byte-identical* primed input; the new one
just stops losing data on the shapes the old one got wrong.

### The handshake was pinned to one host

`extract_handshake` only looked for `x.luarmor.net`, and took the *first*
`Url = "..."` it found. The trace logs other URLs too (the CDN init fetch, the
region auth hosts), so the wrong one could win. The handshake is now picked by
its `a`/`d`/`b` signature on any `luarmor.net` host, and `url` stays `None`
when no signed handshake was seen — replaying an unsigned URL would have hit
the wrong endpoint.

### Other fixes

- `http_get` now turns HTTP/network failures into `RuntimeError`; a 404 loader
  URL used to escape the CLI's handlers as an `HTTPError` and print a
  traceback. `main.py` also catches `OSError`, so a missing `--loader` file
  is a one-line error instead of a stack trace.
- `decode_lua_escapes` used `str.isdigit()`, which also accepts e.g. the
  superscript two — `int()` then raised and the parse died. Now only ASCII
  digits count; `\z`, `\u{...}` and line continuations are handled too.
- `probe --split` printed "split: -> <dir>" even when there was no payload
  boundary to split on and nothing was written. It now says so, and
  `split_payload` returns `None` instead of a path it never produced.
- `probe` reported the re-encoded text length as the file size (wrong for any
  non-UTF-8 client); it now reports the real size.
- `two-phase` counted `_bsdata0` entries by counting commas, which overcounts
  when a blob contains one. It uses the real parse.
- The plant step stopped reading at the `PLANT-` marker, which is a prefix of
  `PLANT-OK` — if the harness wrote the marker and its payload in separate
  writes, the "OK <len>" was missed and a working plant was reported as
  failed. The read now lets the rest of the marker line arrive, and checks the
  reported size when the harness gives one.

### Docs

`README.md`'s *Known limits* still described State848 as the open frontier,
which the 2026-10-01 entry above had already closed. It now states what the
chain actually reaches and flags the sandbox-side plant-MISS fix as an
out-of-repo dependency a reproducing run needs.

### Tests

21 -> 38 tests. All green:

```
python -m unittest discover -s tests     # 38/38
```

### Not done here

The live `fetch` / `two-phase` runs were not executed: they need the
Deobfuscator-Luraph-V15 sandbox repo (luau + the envlog harness), a fresh
loader URL, a cached sephal init and a real script key. The fixes above are
verified against fixtures and the CLI, not against a live Luarmor host.

---

## 2026-10-01 — Full chain completes: past State848, client recovered

First end-to-end run with a **real script key** (fresh loader, cached sephal
init, compatible locally-built luau). The chain ran to success — **no
State848, no kick**:

```
round 1 NEEDFETCH  ->  session-response (630 B)      handshake accepted
round 2 NEEDFETCH  ->  json (412,648 B)              encrypted client chunk
round 3 NEEDFETCH  ->  json (230,077 B)              encrypted client chunk
loadstring() of 624,009 bytes                        decrypted client
run finished: fetches=3 states=- kicked=False
```

The 624,009-byte `loadstring`'d chunk is the decrypted Luarmor client:
`-- This file was protected using Luraph Obfuscator v14.7 [https://lura.ph/]`.
The tool now recovers it automatically (`fetcher.run_two_phase` scans the run's
`\0<nonce>CHUNK` markers → `work/out/recovered_<key>.lua`).

### Root cause of the previous State848 wall

With the placeholder key the chain always died at State848 *before* a second
request, so the serve handler's second-round path was never exercised. The real
key makes round 1 decrypt, and the loader issues a **second** request (the
client-chunk fetch). That URL isn't planted yet (it's the driver's cue to fetch
it), so it takes the `urls.__lrm_plant` **plant-MISS** branch — which should log
and fall through to `NEEDFETCH`. But the diagnostics in that branch called
`R.math.min`/`R.math.max`, and `R.math` is nil in that handler's scope (the only
`R.math` site in `envlog.luau`, hence latent). The nil-index crash aborted the
run → "Luarmor V4 loader failed to fetch a chunk: ...attempt to index nil with
'min'" → the baked-in Loader-Failed UI (a 281-byte spawner) → Kick.

### The fix (sandbox dependency, not this repo)

`runtime/envlog.luau` plant-MISS diagnostics made math-free (plain comparisons
instead of `R.math.min`/`R.math.max`) so a MISS logs and falls through to the
`NEEDFETCH` yield. With that, round 2/3 fetch cleanly and the client decrypts.

> This edit lives in the **discovered Deobfuscator-Luraph-V15 clone**, not in
> Luarmor-Fetch (the sandbox is not vendored here). It is a one-line-class,
> reversible change and should be upstreamed to that repo separately. Recorded
> here so the result is reproducible.

### Where it stands now

- The outer Luarmor protocol is **fully traversed**: auth → session → client
  chunk fetch → decrypt → load. The recovered payload is a *further* layer
  (Luraph Obfuscator v14.7); peeling that is the parent repo's Luraph
  devirtualizer's job, a separate stage from the Luarmor loader chain.
- Reproduce: `LRM_SCRIPT_KEY=<key> python main.py two-phase --loader-url <fresh>
  --init <cached sephal init> --output work/out` (needs a luau that runs on the
  host and the envlog plant-MISS fix above).

## 2026-10-01 — Extraction into a standalone, Node-free tool

Extracted the working Luarmor tooling out of **Deobfuscator-Luraph-V15**
(`tools/luarmor_fetch.py`, `tools/luarmor_two_phase.py`, `tools/luarmor_probe.py`,
`docs/LUARMOR_NOTES.md`, `test/luarmor_fetch_test.py`) and refactored it into
this standalone repo.

**What changed in the extraction**

- **Node.js removed.** The parent tool shelled out to `scripts/run_raw.js`
  (sandbox run) and `scripts/patch_primed.js` (VM entry/spin patch). Both are
  now driven directly from Python: `core/harness.py` for
  `build_harness`/`run_once`/serve mode, and
  `core/obfuscators/luraph_v15/driver.py` for `patch_entries`/`patch_spin`.
  No `node` process is spawned anywhere.
- **Hardcoded paths removed.** The `/home/z/my-project/...` constants in the
  two-phase driver are gone. The sandbox repo is discovered at runtime
  (`common.find_sandbox_repo`: `--repo` → `LUARMOR_REPO` → sibling scan), and
  the luau binary is resolved separately (`common.resolve_luau`: `--luau` →
  `LUARMOR_LUAU` → `bin/luau` → PATH).
- **Modular package.** `common` (http, classify, Lua escapes, discovery),
  `loader` (pure stub/init parsing + input assembly + handshake extraction),
  `fetcher` (sandbox bootstrap, live handshake, two-phase driver), `probe`
  (static analyzer). A single `main.py` exposes `fetch` / `two-phase` / `probe`.
- **Preflight self-test.** Before any sandbox run the tool executes a trivial
  luau script. If luau can't run (e.g. the prebuilt `bin/luau` was built for an
  incompatible microarchitecture and aborts with `SIGILL`), it raises a clear,
  actionable `SandboxError` instead of surfacing an empty trace downstream.

**Validation done**

- Unit tests: 21/21 pass (`python -m unittest discover -s tests`) covering stub
  parsing, `_bsdata0` decode, init split, input assembly, time-pin derivation,
  handshake extraction, response classification, Lua escapes, discovery, and
  the probe detector/splitter.
- `probe` verified end-to-end on real text (no sandbox needed).
- Sandbox wiring verified: harness + luraph_v15 driver import from the
  discovered repo; `patch_spin` applies; `run_once` builds and launches the
  luau subprocess.
- Environment note: the sandbox repo's prebuilt `bin/luau` aborts with `SIGILL`
  (invalid opcode at a fixed address) on this container's CPU — it runs
  `--help` but faults in the VM dispatch path on any script. The tool detects
  this via preflight; a locally compiled patched luau (`build_luau.py`) is the
  fix. Live `fetch`/`two-phase` runs therefore require a compatible luau build
  on the host.

## Inherited protocol state (from Deobfuscator-Luraph-V15)

The reversing that this tool packages, condensed (full detail in
`docs/LUARMOR_NOTES.md`):

- **Bootstrap mapped.** The public v4 loader stub, the sephal init
  (`superflow_bytecode` blob + Luraph v15 chunk), and the stub-faithful primed
  input are fully understood and reproduced.
- **Handshake accepted live.** With a fresh loader, the sandbox-built `b`
  signature is accepted by `x.luarmor.net` (the earlier "outdated" rejections
  were stale `_bsdata0`, not sandbox detection).
- **Same-process decrypt works.** The two-phase driver gets the real session
  response back into the same process (same nonce) and runs the session decrypt
  in-sandbox — no State848 on the first response, no harness crash.
- **Frontier: State848** *(as of the extraction — since closed, see the
  2026-10-01 entry above)*. With a real key the run still ends in the baked-in
  fail state. The verdict is parsed by pure VM arithmetic (zero
  string/table/bit32/buffer calls recorded), so library interception can't read
  the plaintext. Open work: lift the nested protos behind
  `luraph_runtime1(...)` (force-decode for metatable-less tables) to read the
  verdict checks and the response cipher statically, or diff real-executor
  fingerprint/`d` bytes against the sandbox's.

## Next steps

1. **Upstream the envlog plant-MISS fix.** The chain now depends on it, and it
   lives in the *discovered* sandbox repo, not here — without it the run aborts
   on a nil index and the bootstrap's own Loader-Failed UI kicks.
2. **Peel the recovered client.** The chain's output is a Luraph v14.7 layer;
   that is the parent repo's devirtualizer's job, a separate stage.
3. **Nested-proto lift** (the response cipher + verdict logic). No longer on
   the critical path for the loader chain — it is only needed to read the
   session verdict statically instead of by running it.
