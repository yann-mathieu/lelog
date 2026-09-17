# Le Log — project context

A private capture app for things worth remembering: books, people, meals, places, podcasts. Later it quizzes you on the parts worth having in your head.

Full design rationale lives in **`docs/architecture.md`**. Read it before making architectural changes — most of the non-obvious decisions there have reasons that aren't visible from the code.

Running and debugging it by hand — setup, `test/live.py`, reading a self-test report, what a failure at each step of the model pipeline means — is **`docs/runbook.md`**. It is written for a person rather than a session, but it is the fastest way to orient in the model path.

Unscheduled ideas live in **`docs/ideas.md`** — things worth building, not yet committed to, with the reasoning attached. Add to it freely; don't treat anything in it as agreed work.

## How to write here

Keep it simple. Short sentences. Plain words. Say the thing and stop.

This goes for replies in chat, commit messages, comments and docs. If a
sentence has three clauses, cut it into two sentences. If a word is fancy,
use the plain one. Skip the wind-up.

Asked for on 17 September 2026, after a long run of replies that were hard
work to read.

## Current state

**Phases 0 and 1 shipped, in daily use since August 2026.** One text box, list, search, edit, soft delete, export/import, and Dropbox sync. Installable PWA, works offline.

**Phase 2's first slice shipped 4 September 2026:** on-device extraction (WebLLM/WebGPU, opt-in from Settings), filling type, title, tags, rating and per-type `details`. Nothing leaves the phone — no cloud API. High/medium-confidence extractions apply (medium gets a quiet review marker); low-confidence guesses sit unapplied in `enrichment.suggestion`. A model that does not report a confidence at all is treated as medium rather than as zero — small models are poor at self-rating, and discarding a correct extraction over a missing meta-field is worse than applying it with a marker. Model output is parsed forgivingly for the same reason (`parseModelJSON`): code fences and narration are stripped, truncated JSON is closed, and a broken document has its intact fields salvaged, because a minute of a phone's work should not be lost to one character. Settings carries a **self-test** that runs the whole real path once on a fixed sample sentence and reports every step, so a device failure arrives as one paste rather than one symptom per round trip. Every pass also records the conditions it ran under — `enrichment.grammar`, `enrichment.parse`, and, whenever the parse was not clean, the model's own output verbatim in `enrichment.output` — which Settings can render under each entry as a full run block with a one-tap **Copy run + device**; three round trips in September 2026 were spent recovering facts the device had known at the time and thrown away. No entity resolution, no interactive review queue yet — see the roadmap.

**Asking the model to write something shipped 17 September 2026.** Open an
entry and ask a question. The model answers in prose and the answer is kept
in `generated` on the record. This is not extraction and does not behave like
it. Extraction pulls fields out of your note and refuses when it cannot;
asking gets prose from what the model knows, and it will not refuse — it will
invent. So there is no grammar, no validation, and nothing is applied to any
field. Answers are shown apart from the labels, marked with the model that
wrote them, and the screen says they can be confidently wrong. Keep it that
way: when the quiz arrives, nothing in `generated` should reach it without a
person confirming it first.

**Enrichment is manual, per entry, by deliberate choice (7 September 2026).** Capture does not enqueue it and launching does not sweep a backlog: you enrich an entry from its row when you want it, or everything at once from Settings. This departs from §2.5 of the architecture doc, which has capture queue enrichment automatically. Entries staying raw for ever is a normal outcome, so `enrichment.status: 'pending'` means "never asked for", not "queued", and the UI reports it quietly rather than as work outstanding. Instructions to the extractor live in `hints` on the record and are replayed on every later pass.

Sync is done: OAuth 2 with PKCE, one JSON file per record under `memories/{year}/`, cursor-based delta pull, `WriteMode.update(rev)` on push, record-level last-write-wins merge, and automatic syncing on change and on launch. §5 of the architecture doc describes the design; §5.3 records where the implementation deliberately departs from the original plan.

Vanilla HTML/CSS/JS in a single `index.html`. **No build step, no bundled dependencies, no framework.** The one exception: enrichment lazy-loads WebLLM from a pinned CDN URL, only once turned on in Settings — nothing is vendored into the repo or fetched on a cold load. The whole app is still six files at the repo root and that simplicity is a feature. Keep it that way — the architecture doc's §7 tech stack table names React, Vite, Dexie and Tailwind, and none of them were used; that section documents an abandoned plan, not the code.

## Invariants — do not break these

1. **`raw` is immutable.** AI enrichment writes to separate fields alongside the user's text, never over it. Fields the user edits by hand are recorded in `userEdited` and are never re-derived. **Reachable since 15 September 2026:** tapping a tile opens the entry's own full screen, where type, title, when, rating and tags are all editable, and every hand-edit records the field. `raw` itself is *not* recorded in `userEdited` — that list is about fields the model fills, and the user's own sentence was never one of them.
2. **Records already use the full v2 schema** — `raw`, `capturedAt`, `enrichment`, `type`, `title`, `occurredAt`, `tags`, `rating`, `details`, `links`, `hints`, `generated`, `userEdited`, `media`, timestamps, `deleted`. Everything except the user's text is null/empty in v0. This exists so no captured data ever needs migrating. Don't strip unused fields.
3. **Deletes are tombstones** (`deleted: true`), never removals. Required for sync to propagate deletes correctly later.
4. **Capture never blocks.** No spinner, no network, no required field, no type picker. Save is instant and works offline. Enrichment is always async and always optional.
5. **This is a log, not a diary.** No streaks, no calendar view, no "how was your day?" prompt, no visible gaps for missed days. The unit is an *encounter*, not a day. See §1.1 of the architecture doc.
6. **Export must keep working.** Sync is replication, not backup — it copies a mistake to every device faithfully. Export is still the only thing that recovers from one. Any change touching the record shape must keep the exported JSON exactly the v2 schema; there is a test asserting it.
7. **Sync never deletes local data.** Only a record whose `deleted` flag is `true` counts as a deletion. A file missing from Dropbox means re-upload it, never delete it locally, and an empty remote folder means nothing has been uploaded yet — never that everything was deleted. Three tests cover this; it is the path by which the only copy of the data could be lost.
8. **Dropbox bookkeeping stays out of the record.** Revs, cursors and tokens live in the `syncmeta` and `syncstate` stores. Export is a straight dump of the record objects, so anything added to a record lands in the backup file.

## Roadmap

| Phase | Scope |
|---|---|
| 0 ✅ | Capture, search, export. Local-only. |
| 1 ✅ | Dropbox sync (App folder scope, OAuth PKCE, one JSON file per record) |
| 2 🟡 | AI enrichment: extraction, types, tags, confidence, richer `details` ✅ on-device (WebLLM). Interactive review queue moved to phase 3. |
| 3 | Links + entity resolution, question queue (enrichment mode + phase 2's deferred review UI), app lock |
| 4 | Quiz mode over the same queue, FSRS scheduling |
| 5 | Voice + photo capture, share target, selective encryption |

The enrichment questioner and the quiz questioner are **the same component** at different time offsets — build once.

## Testing

135 Playwright tests in `test/smoke.py`. No test runner, no framework — the file serves the repo on an ephemeral port, drives it with headless Chromium, and gives each test a fresh browser context. Dropbox endpoints are stubbed, so it runs offline and never touches a real account. On-device enrichment is stubbed the same way, via `window.__LELOG_TEST_EXTRACTOR__` — no test touches real WebGPU or downloads real model weights.

```bash
python3 test/smoke.py            # all
python3 test/smoke.py search     # only tests matching "search"
```

Needs Playwright once. On any current Debian or Ubuntu a plain `pip install`
is refused (PEP 668, "externally-managed-environment"), so use a venv — and
put it outside the checkout, which may well be inside a synced folder:

```bash
python3 -m venv ~/.venvs/lelog
~/.venvs/lelog/bin/pip install playwright
~/.venvs/lelog/bin/python -m playwright install chromium
~/.venvs/lelog/bin/python test/smoke.py     # run it with that interpreter
```

(`python3 -m venv` needing `apt install python3.x-venv` first is normal on
Debian. `--break-system-packages` is for throwaway containers like
`.claude/cloud-setup.sh`, not for a machine you use.)

**Run it before and after every change.** Several tests exist specifically to catch regressions that would silently destroy data — the export shape, the three sync-never-deletes rules, and the v1→v2 database upgrade. When adding behaviour, add the test that fails without it, then check the test actually fails when you break the code deliberately. That practice has caught two real gaps in this suite already, both in sync paths that looked covered but were not.

`file://` will not work — IndexedDB and service workers need a real origin.

### Testing the model layer

**Two seams, and the difference matters.** `window.__LELOG_TEST_EXTRACTOR__`
replaces the extractor and is the quick way to drive a specific result.
`window.__LELOG_TEST_WEBLLM__` replaces the WebLLM *module* instead, so
engine creation, adapter and quantisation choice, streaming, and cache
checks all actually run — see `FAKE_WEBLLM` and `stub_model_layer` in
`test/smoke.py`.

**Prefer the module seam for anything touching the model.** Every field
failure in this feature came from code the extractor seam skips: a version
that was never published, load progress wired to one trigger and not the
other, the f16/f32 choice. 86 tests passed throughout while none of that
code had ever executed outside a phone. If a change touches
`getEnrichEngine`, `realWebLLMExtract`, `streamCompletion`, `modelCached` or
`diagnoseModelLoad`, it needs a module-seam test, and that test must be seen
to fail with the change reverted.

## Deployment

`git push` → GitHub Pages redeploys from `main` in a minute or two → `https://yann-mathieu.github.io/lelog/`. All paths are relative so the `/lelog/` subdirectory works unchanged.

**Bump `CACHE` in `sw.js` whenever `index.html` changes**, or the service worker keeps serving the old shell and clients never see the update.

The repo is public because Pages will not serve a private repo on a free plan. `index.html` carries a `noindex` tag so the app stays out of search results. Nothing sensitive is in here: entries live in IndexedDB and the user's Dropbox, and the Dropbox app key in `index.html` is public by design under PKCE. Don't commit backup JSON.

## Working on enrichment from here

**The device is the thing you do not have.** A cloud session can get WebGPU
— `test/live.py` does, via `--enable-unsafe-webgpu --enable-features=Vulkan`
on a persistent profile — but it arrives as SwiftShader, a software renderer
with no `shader-f16` and meaningless timings, and the network there blocks
`esm.run`, `cdn.jsdelivr.net`, `huggingface.co` and `unpkg.com`, so the load
dies at the module fetch regardless. The model therefore never runs in a
cloud session, and anything about *a real GPU* or *a real network* has to
come from a real machine. Everything else can and should be settled first —
most of the round trips in this feature's history were avoidable, not
device-specific.

**Verify external facts, never recall them.** `registry.npmjs.org` and
`raw.githubusercontent.com` *are* reachable. A version pin of
`@mlc-ai/web-llm@0.2.79` — a version that has never existed — cost two
round trips and was one `curl` away from being caught. Before writing a
package version, a model id, or an API shape: fetch it. `curl -sI` a model
artifact to confirm it is really there.

**Diagnostics can lie, so verify them too.** The host probe once sent a
`Range` header, which makes a cross-origin request non-simple and forces a
CORS preflight — `raw.githubusercontent.com` answers that preflight with 403
while serving the file itself perfectly well. It reported a reachable host
as unreachable, and sent a debugging session off after an outage that did
not exist. Probes use simple requests only; a test asserts it.

**Ask for the self-test report first.** Settings → Enrichment → *Run
self-test* drives the whole real path once on a fixed sample sentence and
reports every step in order: environment and storage, adapter and
`shader-f16`, which model id resolved, whether it is on disk, module and engine load times, prompt size, time to first token,
throughput, the model's output verbatim, how that output had to be parsed,
and the validated result. A failure names the step it failed at. That is one
paste in place of the dozen round trips this feature actually cost, and it is
the closest thing available to running the model here.

**Better still, ask for one entry's run.** Settings → Enrichment → *Show
the full run on each entry* turns every readout into the conditions the pass
happened under — model and quantisation, whether the strict grammar was in
force, how the output had to be parsed, confidence and its band, total and
time to first token — and adds a **Copy run + device** button that puts that
run *and* the diagnostics blob on the clipboard together. It carries the
entry's own text, which is the question whenever an extraction is wrong.
That is the paste to ask for when a specific entry came out wrong, and it
needs no model download, unlike the self-test.

Those conditions are recorded on the record (`enrichment.grammar`,
`enrichment.parse`), so an old entry reports the state it actually ran under
rather than today's settings. `parse` is the one to read first on a `done`
record: a result that had to be *salvaged from broken JSON* is a marginal
model wearing a success, and before this it was indistinguishable from a
clean one.

**`Copy diagnostics` is the lighter one**, for the state of the app rather
than a live run: version, GPU and adapter, `shader-f16`, which model resolved
and whether it is cached, the settings in force, entry counts, last timing
and last error. Ask for it when the question is about accumulated state; ask
for the self-test when the question is about the model. If a report arrives
without either, ask before theorising.

**The `shader-f16` flag is not to be trusted, in either direction.** A
Qualcomm Adreno 7xx on Android 10 advertises it and then fails
`CreateComputePipelines` with `VK_ERROR_UNKNOWN`; Chrome 137 on Linux denies
it on a Quadro T1000 that has the hardware. The app therefore stopped reading
it and builds `q4f32_1` always — bigger and slower, and it runs anywhere
WebGPU does. There is no 16/32-bit setting: the escape hatch that used to
cover this only helped someone who already knew to reach for it, and the one
person who needed it had to be told. Diagnostics still reports the claim,
marked `(unused)`, because it is a fact about the device rather than a lever.

**A phone is not the only device.** Desktop Chrome has real WebGPU and a much
faster GPU, and the app is the same URL with the same Dropbox sync. Running
the self-test on both and diffing the two reports separates a driver problem
from a code problem in one step — which is the distinction most of the
history of this feature was spent guessing at.

**The grammar is a dependency with teeth.** XGrammar — pinned transitively
by the WebLLM version in `index.html` — throws on schema constructs it does
not support, and WebLLM compiles the grammar in a promise executor with no
`reject`, so the throw becomes an unhandled error and generation waits on a
promise that never settles. Zero tokens for the full 15-minute cap, nothing
to catch, `completeWithFallback` useless. A union type
(`{ type: ['string', 'null'] }`) did this; `anyOf` is the supported spelling
and a test in `smoke.py` now rejects unions. Read the grammar it emits
rather than reasoning about what strict mode ought to forbid: `details:
{ type: 'object' }` looks restrictive and in fact compiles to
`basic_object`, which allows any key. **Property order in the schema is
load-bearing** — xgrammar reads `properties` with `ordered_keys()`, so
declaration order is emission order, and an unbounded array declared early
starves everything after it: a phone spent all 220 tokens on 22 copies of
`"tack"` inside `tags`, and `details` was empty because it was never
reached. `tags` is last for that reason — and moving it there simply relocated the
loop into `details`, which as `{ type: 'object' }` compiled to
`basic_object` and let a phone write `{"x": 0,": 0,": 0, ...` until the
tokens ran out. **0.1.0 ignores every bound there is** — `maxLength`,
`maxItems`, `maxProperties`, `minimum`, `maximum` are all in
`WarnUnsupportedKeywords` — so a bound must be structural: an `enum`, a
closed `properties` set with `additionalProperties: false`, or nothing.
`rating` is an enum because `{ type: 'integer' }` returned 2448; `details`
names every key the app knows and forbids the rest. What the grammar
still cannot say — that a date is a date, that `cuisine` belongs to a
restaurant and not a book — `validateExtraction` drops. Variants can be compiled in isolation — the
xgrammar wasm is embedded in its npm package, so it needs no weights and no
GPU, which is the cheapest real check in this whole feature.

**The schema is necessary and never sufficient.** Four rounds of closing
grammar holes ended with `llama-1b` emitting valid, complete JSON that said
`type: film, title: "film"` on an audiobook note. `qwen-1.5b` on the same
device and prompt got the title exactly right and was faster, which is why
it is the default. Before tuning a schema again, check the model can do the
task at all. And check the prompt names every field the schema requires:
`rating` was in `required` and unmentioned, so the grammar forced a number
the model knew nothing about and a note expressing no opinion came back
1/5; `tags` was mentioned only when a tag vocabulary existed, so it went
silent on a fresh log — which is where `"One", "tied", "tack"` came from.
Confidence remains worthless: every model tried reports 1.0 for everything,
so the high/medium/low bands never fire and nothing is marked for review.

**A wait that cannot say what it is doing looks like a hang.** WebLLM's
`initProgressCallback` sends `{progress, timeElapsed, text}` and this app
used only `progress` — which sits at or near 0 for minutes while shaders
compile, so an Adreno reading a 1.5B from disk rendered as a frozen
"loading model 0%" for two minutes. `text` is the field that separates
downloading (the network is involved) from reading off disk from compiling
(neither is). It is now carried on `live.text`, shortened for the tile
badge by `loadingWord()`, and shown verbatim in the entry's own live panel.

**Look at UI before shipping it.** Drive the app with Playwright at a phone
width (412×915) and screenshot the state being changed. A toast with no
`max-width`, and per-type `details` that were extracted but rendered
nowhere, both shipped because nobody looked.

**Say which half is unverified.** When a change cannot be exercised here,
state that plainly rather than implying it works.

## Working from a desktop with a real GPU

**This is the only place the model can actually be run**, and it closes the
loop that every other note in this file works around: change code, run it
against the real model, read the result, without a person relaying symptoms
in between.

`test/live.py` is that loop. It serves this checkout, opens it in the Chrome
already installed on the machine, clicks Settings → *Run self-test*, and
prints the report line by line as it fills in. Exit status is 0 on `PASS`.

```bash
python3 test/live.py                    # visible window, real Chrome
python3 test/live.py --headless
python3 test/live.py --model qwen-1.5b
python3 test/live.py --url https://yann-mathieu.github.io/lelog/
```

It drives the Chrome already installed on the machine, so it does not need
Playwright's own browser download — only the `playwright` package itself (see
Testing above for the venv).

Read two lines of its output before anything else. `webgpu absent` means the
browser has no WebGPU and nothing below that line ran — that is what
`--channel bundled` gets you, and why real Chrome is the default. `gpu
google swiftshader` means WebGPU fell back to software: it works, but f16 is
gone and every timing is fiction.

The browser profile is kept between runs (`--profile`, default
`~/.cache/lelog-live-profile`), so the weights are downloaded once. Delete
that directory to test a cold download — worth doing deliberately, since the
first-run path is where most of the reported failures have been.

**Do not move any of this into `test/smoke.py`.** That suite must keep
running offline, in seconds, in a cloud session with no GPU; the moment one
test needs real weights, it stops being runnable where most of the work
happens. Real-model checks live here, run by hand, and the two seams
(`__LELOG_TEST_EXTRACTOR__`, `__LELOG_TEST_WEBLLM__`) stay the way the suite
covers that code.

## Working from a phone

Cloud sessions start cold with only this repo, so this file, `docs/architecture.md` and `docs/ideas.md` are the entire context. Keep them true.

The cloud environment needs a setup script to run the tests — see `.claude/cloud-setup.sh`. Point the environment's setup script at it, and allow `cdn.playwright.dev` in the environment's network access or the Chromium download will fail.
