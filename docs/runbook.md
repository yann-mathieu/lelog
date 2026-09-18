# Runbook — running Le Log yourself

Everything a Claude Code session does to this repo, as commands you run by
hand, and how to read what comes back when the on-device model misbehaves.

There is a formatted version of this page at
<https://claude.ai/code/artifact/281bbeec-f155-43f9-ac94-3d5784577964>.
**This file is the source of truth** — if the two disagree, believe this one,
and if this one disagrees with the code, believe the code.

Written 13 September 2026, at `log-v3-8`.

| | |
|---|---|
| version | `log-v3-8` |
| tests | 141 / 141 passing |
| app | `index.html`, ~3,000 lines, no build step |
| default model | `qwen-1.5b` → `q4f32_1`, always — the 16-bit build is never used |
| verified | `qwen-1.5b` extracts a real title on an Adreno 7xx; `llama-1b` does not |
| unverified | extraction quality on the phone; `details` has never come back filled |

---

## Set the machine up, once

Debian and Ubuntu refuse a plain `pip install` now (PEP 668,
"externally-managed-environment"). Use a venv, and keep it **outside** the
checkout — a checkout inside a synced folder would otherwise sync a few
hundred megabytes of virtualenv.

```bash
# if venv is missing: sudo apt install python3.12-venv
python3 -m venv ~/.venvs/lelog
~/.venvs/lelog/bin/pip install playwright

# only needed for smoke.py — live.py drives the Chrome you already have
~/.venvs/lelog/bin/python -m playwright install chromium
```

Run everything with that interpreter; there is nothing to activate. The app
itself needs no dependencies at all.

---

## Three things you can run

```bash
# 141 tests. Offline, stubbed Dropbox, no GPU, no weights. ~6 minutes.
~/.venvs/lelog/bin/python test/smoke.py
~/.venvs/lelog/bin/python test/smoke.py search   # just matching names
```

```bash
# The real thing: your Chrome, your GPU, real weights, real model.
~/.venvs/lelog/bin/python test/live.py
~/.venvs/lelog/bin/python test/live.py --model qwen-1.5b
~/.venvs/lelog/bin/python test/live.py --url https://yann-mathieu.github.io/lelog/
```

Or open the app and press the button yourself: **Settings → Enrichment → Run
self-test**.

`live.py` serves the checkout, opens it in the installed Chrome, clicks the
self-test and prints the report line by line as it fills in. It exits `0` on
`PASS`, so it drops straight into a shell loop.

**The weights download once, and it takes two things.** The profile persists
at `~/.cache/lelog-live-profile`, *and* the port is fixed (`--port`, default
8787) — the Cache API is keyed by origin and the port is part of the origin,
so an ephemeral port silently gave every run an empty cache and downloaded
the whole model again. Delete the profile directory to reproduce a cold
download deliberately; that is where most of the reported failures have
actually been. A second line of defence against the opposite mistake: the
shell is served no-store behind a per-run query string, because a stable
origin plus a kept profile let Chrome serve a cached `index.html` and report
a version no longer on disk.

Other flags: `--headless`, `--loose` (skip the strict JSON grammar),
`--channel bundled`, `--timeout`, `--profile`, `--port`. Model keys are
`smol-360m`, `llama-1b`, `qwen-0.5b`, `qwen-1.5b`.

---

## When one entry came out wrong

The self-test answers *does the model work here*. It does not answer *why did
this entry come out like that* — that needs the conditions **that** pass ran
under, which are now kept on the record itself.

Turn on **Settings → Enrichment → Show the full run on each entry**, then tap
the entry. Under the extracted fields you get:

```
model       Llama-3.2-1B-Instruct-q4f32_1-MLC
grammar     none · output unconstrained
parsed      salvaged from broken JSON
confidence  not reported · treated as medium
total       27.4s
first word  15.2s
```

Anything in amber was not the default, and is the first thing to look at:

| Row | What amber means |
|---|---|
| `grammar` | The strict schema was skipped. The model may return anything, including a key that is not in the schema at all, and a whole pass can be lost to it. |
| `parsed` | The output did not parse cleanly. `repaired` is ordinary; `salvaged from broken JSON` means fields were pulled out of a broken document; `degenerate` means the model looped instead of answering. |
| `confidence` | The model did not rate itself. Treated as medium and applied, deliberately — but under the strict grammar this **cannot** happen, because `confidence` is a required property. If you see it, the grammar was not in force. |

`model` always ends `q4f32_1` now. The app used to follow the adapter's
`shader-f16` feature, with a Settings switch for drivers that advertise it
and then fail — which a Qualcomm Adreno 7xx does, reporting `shader-f16 yes`
and then killing `CreateComputePipelines` with `VK_ERROR_UNKNOWN`. The flag
cannot be trusted and the switch only helped someone who already knew to
reach for it, so the 32-bit build — bigger, slower, runs anywhere WebGPU
does — is now the only one built.

**Copy run + device** puts that run and the whole diagnostics blob on the
clipboard in one go. It includes the entry's own text, because a wrong
extraction is a question about the note; the button says so next to it. This
is the paste to send when a specific entry came out wrong — unlike the
self-test, it needs no model download.

Conditions are recorded per pass, so an old entry reports what it actually
ran under rather than today's settings.

---

## Reading a report

One pass over a fixed sample sentence — never one of your entries, so a
report is safe to paste anywhere and comparable between two machines.

```
webgpu       present
gpu          qualcomm adreno-7xx
shader-f16   advertised (unused) · 19 features
```

**Read those two first.** `absent` means the browser has no WebGPU and
nothing below that line ran at all. `google swiftshader` means it fell back
to software rendering: it works, but f16 is gone and every timing below is
fiction.

```
on disk      Llama-3.2-1B-Instruct-q4f32_1-MLC · on this device
resolved     Llama-3.2-1B-Instruct-q4f32_1-MLC
```

This used to report *both* quantisations, because the 16/32-bit switch
resolved a different model id and a model that had just run perfectly could
truthfully report itself uncached — which looked like a bug for a week. With
the switch gone there is one id, and it is named outright.

```
prompt       528 chars · 12 known tags · strict JSON grammar
first token  2.1s
finished     6.8s · 84 tokens · 12.4/s
```

**Where the time actually goes.** Everything before the first token is
prefill — the prompt, plus the JSON grammar being compiled into a decoder.
The prompt is reported by length only: it embeds your tag vocabulary, and
this report is meant to be pasted.

```
output       "{\"type\":\"restaurant\",…
parse        repaired
result       restaurant · "Le Servan" · 5/5 · confidence 0.8 → high
```

**The model's own words, verbatim.** Every parse failure so far has been
obvious the moment the actual characters were visible, and invisible before
that. `parse` says how hard the parser had to work: *as-is*, *trimmed to the
braces*, *repaired*, or *salvaged from broken JSON*. Anything past *as-is* is
the model being sloppy, not a failure.

```
verdict      PASS
```

Otherwise `FAILED AT <step>`, with an `error` line carrying the driver or
host diagnosis.

---

### When it says the GPU device is gone

> Could not enrich this entry — A valid external Instance reference no longer exists.

That is Chrome's WebGPU implementation (Dawn) reporting a **lost device**, not
anything to do with the model or your note. Android reclaims GPU memory under
pressure, and a tab left in the background long enough loses its device. TVM's
own `device.lost` handler then disposes the instance, so every later call lands
on a dead handle.

The app now throws the dead engine away when this happens, so pressing
**Enrich** again rebuilds it — from the weights already on the device, with no
download. Before that fix the engine was cached for the life of the page and
only ever discarded when *creation* failed, so one device loss broke enrichment
until the page was reloaded, and nothing said so.

If it happens repeatedly rather than once, the model is probably too big for
the device's GPU memory: try a smaller one in Settings.

---

## The seven places it can stop

In execution order. The report names the one it died at; that is the point of
it.

1. **`storage`** — the quota and persistence lookup. Almost never the real
   problem; a failure here means site data is blocked outright.
2. **`webgpu`** — no `navigator.gpu`, or no adapter behind it. *The browser
   or the driver, not this app.* Playwright's bundled Chromium has no
   WebGPU; real Chrome does. On Linux, `--enable-unsafe-webgpu
   --enable-features=Vulkan`, which `live.py` already passes.
3. **`module`** — could not fetch WebLLM from `esm.run`. A network or
   blocked-CDN problem, nothing device-specific. This is where a cloud
   session always dies.
4. **`cache`** — the on-disk check itself threw. Rare: the Cache API
   unavailable, or storage evicted mid-check.
5. **`engine`** — *the interesting one.* Either the download fell over
   (retried once automatically) or the driver refused to compile the shaders.
   The error text says which: anything naming `VK_`, Vulkan, Dawn, pipeline
   or shader is the driver, and since this is already the 32-bit build the
   lever is a smaller model, not the quantisation;
   anything naming fetch, cache or network is the download, and the report
   already names the host that refused.

   `Failed to execute 'add' on 'Cache': Request failed` is the download, and
   in practice it has meant **Hugging Face rate-limiting**: WebLLM fetches
   shards in parallel, and `us.aws.cdn.hf.co` answers a burst of anonymous
   requests with 429. The app's diagnosis talks you out of this — it probes
   with a simple request, cannot read a status code off an opaque response,
   and so reports both hosts reachable. `curl` succeeding on a shard while
   the browser fails is the signature. `live.py` prints the 429s; waiting
   ten minutes clears it, and not re-downloading every run avoids it.
6. **`extract`** — the model loaded and then failed or hung generating.
   Capped at 15 minutes, so a wedged model still produces a report rather
   than a blank box.

   **Zero tokens for the full cap means the grammar, not the model.**
   XGrammar throws on schema constructs it does not support — a union type
   (`{ type: ['string', 'null'] }`) is one — and web-llm compiles the grammar
   in a promise executor
   with no `reject`, so the throw escapes as an unhandled error and the await
   never returns. There is nothing to catch. `--loose` generating fine while
   the default hangs is the tell. Write nullable as
   `anyOf: [{ type: 'string' }, { type: 'null' }]`, and see the test in
   `smoke.py` that rejects union types.
7. **`parse`** — output that could not be salvaged even after repair. The
   `output` line directly above prints what it actually said; that is what to
   look at, not the character offset.

---

## The rules that bite

**Bump both, or nobody sees it.** `APP_VERSION` in `index.html` and `CACHE`
in `sw.js` must match. Miss it and the service worker keeps serving the old
shell forever. A test asserts they agree — but only if you run the suite.

- **Run the suite before and after every change.** Several tests exist purely
  to catch changes that would silently destroy data: the export shape, the
  three sync-never-deletes rules, the v1→v2 upgrade.
- **New behaviour needs the test that fails without it** — and you have to
  break the code deliberately and watch it fail. That practice has caught two
  real gaps already.
- **Two test seams, and the difference matters.**
  `window.__LELOG_TEST_EXTRACTOR__` replaces the extractor: quick, but it
  skips every line that has ever broken in the field.
  `window.__LELOG_TEST_WEBLLM__` replaces the WebLLM *module*, so engine
  creation, quantisation choice, streaming and cache checks all actually run.
  Anything touching the model uses the second one.
- **Never put GPU or real weights into `smoke.py`.** That suite has to stay
  runnable offline, in seconds, on a machine with no GPU. Real-model checks
  live in `live.py`, run by hand.
- **`raw` is immutable**, deletes are tombstones, sync never deletes local
  data, export must keep working. The full list with reasons is in
  `CLAUDE.md`; read it before touching the record shape.

Deploying:

```bash
# 1. bump APP_VERSION in index.html and CACHE in sw.js to the same string
# 2. run the suite
# 3. push
git push origin main   # Pages redeploys in a minute or two
```

---

## What is still open

**Does re-enriching reset the derived fields?** Never actually decided. Today
a second pass overwrites `type`, `title`, `tags`, `rating` and `details` for
any field not in `userEdited`, but a field the new pass simply omits keeps
its old value. That is an accident of the implementation, not a choice.

**Settled: the phone's f16 claim is a lie.** A Qualcomm Adreno 7xx on
Android 10 reports `shader-f16 yes` and then fails
`CreateComputePipelines` with `VK_ERROR_UNKNOWN`. Desktop was the mirror
image — Chrome 137 on Linux reports `shader-f16 no` on a Quadro T1000 that
has the hardware. The flag was wrong in both directions, so the app stopped
reading it: every build is `q4f32_1`. Diagnostics still prints the claim,
marked `(unused)`, because it is a fact about the device and not a lever.

**Solved: `details` came back `{}` because it was never reached.** Two
guesses missed it. The first blamed the grammar; the second blamed the
prompt. The self-test's verbatim output settled it — the phone produced

```
{"type": null, "title": null, "tags": ["One","tied","tack","tied","tack", ... ]
```

— 22 copies of `"tack"`, all 220 tokens gone inside the tags array, with
`rating`, `details` and `confidence` never written at all. Not a refusal:
starvation. XGrammar reads `properties` with `ordered_keys()`, so schema
declaration order is the order the model must emit in, and an unbounded
array declared early is a hole the budget falls into. `tags` is now last,
so everything else is committed before the looping can start.

`maxItems` is the keyword that ought to bound it, and on the pinned 0.1.0 it
does nothing — listed under `WarnUnsupportedKeywords`, and adding it leaves
the emitted grammar byte-identical. Compile both orders yourself before
believing any of this: `Grammar.fromJSONSchema(...)` stringifies to EBNF and
its wasm needs no weights and no GPU.

Closing the holes worked, and it was the last thing the schema could do.
The same note through `llama-1b` then parsed `as-is` for the first time —
valid, complete JSON — and said `type: film, title: "film"`. Well-formed
and meaningless. Under `qwen-1.5b` it became `podcast` / `"The Big Short"` /
`show: The Big Short`: the title exactly right, `details` correctly shaped,
and faster (27s against 35s). **The schema was genuinely broken four times
over and fixing it was necessary; it was never going to be sufficient.**
`qwen-1.5b` is the default for that reason.

**The prompt described four of the seven fields it demands.** `rating` sat
in the schema's `required` list and was never mentioned, so the grammar
forced a number the model had been told nothing about — a note expressing no
opinion came back `1/5`, which reads as dislike. `tags` was mentioned only
when a tag vocabulary already existed, so on a fresh log the one line that
would have helped vanished, and `llama-1b` returned `"One", "tied", "tack",
"tack"`. Both now always explained, along with the audiobook case that had
`podcast` and `book` competing with nothing to separate them.

**Confidence is still worthless.** Every model tried reports `1.0` for
everything, including `title: "film"`. The high/medium/low bands therefore
never fire and nothing is ever marked for review. Deriving a confidence the
app can trust — or dropping the bands — is open.

**The question queue.** Phase 2 shipped extraction but deferred the
interactive review screen into phase 3, where it merges with the clarifying
question queue. Those and the quiz questioner are the same component at
different time offsets; build it once.

---

## The repo in one screen

| file | |
|---|---|
| `index.html` | the entire app — vanilla, no framework, no build step |
| `sw.js` | offline shell; `CACHE` must equal `APP_VERSION` |
| `test/smoke.py` | 106 tests, offline, stubbed, no GPU |
| `test/live.py` | the real-model run, by hand |
| `CLAUDE.md` | what a cold session needs; keep it true |
| `docs/architecture.md` | why things are the way they are |
| `docs/ideas.md` | unscheduled, uncommitted, reasoning attached |
| `docs/runbook.md` | this file |

Inside `index.html`, sections are marked `// ---------- name ----------`:

```
storage        414      rendering     2021
dropbox auth   521      actions       2170
push           813      self-test     2660
pull           934      boot          2977
sync          1131
enrichment    1247   <- everything model-related, ~680 lines
```

---

## If you do one thing

Run the self-test on a desktop and on the phone, and put the two reports side
by side. The diff between them separates a driver problem from a code problem
in a single step — and that distinction is what nearly every round trip in
this feature's history was spent guessing at.
