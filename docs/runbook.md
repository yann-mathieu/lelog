# Runbook — running Le Log yourself

Everything a Claude Code session does to this repo, as commands you run by
hand, and how to read what comes back when the on-device model misbehaves.

There is a formatted version of this page at
<https://claude.ai/code/artifact/281bbeec-f155-43f9-ac94-3d5784577964>.
**This file is the source of truth** — if the two disagree, believe this one,
and if this one disagrees with the code, believe the code.

Written at `e28943d`, 11 September 2026.

| | |
|---|---|
| deployed | `log-v3-4`, Pages build succeeded |
| tests | 106 / 106 passing |
| app | `index.html`, ~3,000 lines, no build step |
| default model | `llama-1b` → `Llama-3.2-1B-Instruct-q4f16_1-MLC` |
| unverified | the model has never run on a real GPU under observation |

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
# 106 tests. Offline, stubbed Dropbox, no GPU, no weights. ~6 minutes.
~/.venvs/lelog/bin/python test/smoke.py
~/.venvs/lelog/bin/python test/smoke.py search   # just matching names
```

```bash
# The real thing: your Chrome, your GPU, real weights, real model.
~/.venvs/lelog/bin/python test/live.py
~/.venvs/lelog/bin/python test/live.py --model qwen-1.5b --f32
~/.venvs/lelog/bin/python test/live.py --url https://yann-mathieu.github.io/lelog/
```

Or open the app and press the button yourself: **Settings → Enrichment → Run
self-test**.

`live.py` serves the checkout, opens it in the installed Chrome, clicks the
self-test and prints the report line by line as it fills in. It exits `0` on
`PASS`, so it drops straight into a shell loop. The browser profile persists
at `~/.cache/lelog-live-profile`, so the weights download once — delete that
directory to reproduce a cold download deliberately, which is where most of
the reported failures have actually been.

Other flags: `--headless`, `--loose` (skip the strict JSON grammar),
`--channel bundled`, `--timeout`, `--profile`. Model keys are `smol-360m`,
`llama-1b`, `qwen-0.5b`, `qwen-1.5b`.

---

## Reading a report

One pass over a fixed sample sentence — never one of your entries, so a
report is safe to paste anywhere and comparable between two machines.

```
webgpu       present
gpu          qualcomm adreno-7xx
shader-f16   yes · 19 features
```

**Read those two first.** `absent` means the browser has no WebGPU and
nothing below that line ran at all. `google swiftshader` means it fell back
to software rendering: it works, but f16 is gone and every timing below is
fiction.

```
16-bit build Llama-3.2-1B-Instruct-q4f16_1-MLC · on this device
32-bit build Llama-3.2-1B-Instruct-q4f32_1-MLC · not downloaded
resolved     Llama-3.2-1B-Instruct-q4f16_1-MLC
```

**Both builds, deliberately.** Flipping the 32-bit switch in Settings
resolves a *different model id*, so a model that has just run perfectly can
truthfully report itself uncached. That looked like a bug for a week; these
three lines are the answer to it.

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
   or shader is the driver, and the 32-bit build is the thing to try;
   anything naming fetch, cache or network is the download, and the report
   already names the host that refused.
6. **`extract`** — the model loaded and then failed or hung generating.
   Capped at 15 minutes, so a wedged model still produces a report rather
   than a blank box.
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

**Is the phone's f16 claim honest?** Android drivers advertise `shader-f16`
and then fail to compile it. The self-test prints the claim and the outcome
in the same report, so one run on the phone settles it — and `--f32` is the
fallback if it does not.

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
storage        414      rendering     2015
dropbox auth   521      actions       2164
push           813      self-test     2654
pull           934      boot          2971
sync          1131
enrichment    1247   <- everything model-related, ~670 lines
```

---

## If you do one thing

Run the self-test on a desktop and on the phone, and put the two reports side
by side. The diff between them separates a driver problem from a code problem
in a single step — and that distinction is what nearly every round trip in
this feature's history was spent guessing at.
