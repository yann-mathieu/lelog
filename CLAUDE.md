# Le Log — project context

A private capture app for things worth remembering: books, people, meals, places, podcasts. Later it quizzes you on the parts worth having in your head.

Full design rationale lives in **`docs/architecture.md`**. Read it before making architectural changes — most of the non-obvious decisions there have reasons that aren't visible from the code.

Unscheduled ideas live in **`docs/ideas.md`** — things worth building, not yet committed to, with the reasoning attached. Add to it freely; don't treat anything in it as agreed work.

## Current state

**Phases 0 and 1 shipped, in daily use since August 2026.** One text box, list, search, edit, soft delete, export/import, and Dropbox sync. Installable PWA, works offline.

**Phase 2's first slice shipped 4 September 2026:** on-device extraction (WebLLM/WebGPU, opt-in from Settings), filling type, title, tags, rating and per-type `details`. Nothing leaves the phone — no cloud API. High/medium-confidence extractions apply (medium gets a quiet review marker); low-confidence guesses sit unapplied in `enrichment.suggestion`. A model that does not report a confidence at all is treated as medium rather than as zero — small models are poor at self-rating, and discarding a correct extraction over a missing meta-field is worse than applying it with a marker. No entity resolution, no interactive review queue yet — see the roadmap.

**Enrichment is manual, per entry, by deliberate choice (7 September 2026).** Capture does not enqueue it and launching does not sweep a backlog: you enrich an entry from its row when you want it, or everything at once from Settings. This departs from §2.5 of the architecture doc, which has capture queue enrichment automatically. Entries staying raw for ever is a normal outcome, so `enrichment.status: 'pending'` means "never asked for", not "queued", and the UI reports it quietly rather than as work outstanding. Instructions to the extractor live in `hints` on the record and are replayed on every later pass.

Sync is done: OAuth 2 with PKCE, one JSON file per record under `memories/{year}/`, cursor-based delta pull, `WriteMode.update(rev)` on push, record-level last-write-wins merge, and automatic syncing on change and on launch. §5 of the architecture doc describes the design; §5.3 records where the implementation deliberately departs from the original plan.

Vanilla HTML/CSS/JS in a single `index.html`. **No build step, no bundled dependencies, no framework.** The one exception: enrichment lazy-loads WebLLM from a pinned CDN URL, only once turned on in Settings — nothing is vendored into the repo or fetched on a cold load. The whole app is still six files at the repo root and that simplicity is a feature. Keep it that way — the architecture doc's §7 tech stack table names React, Vite, Dexie and Tailwind, and none of them were used; that section documents an abandoned plan, not the code.

## Invariants — do not break these

1. **`raw` is immutable.** AI enrichment writes to separate fields alongside the user's text, never over it. Fields the user edits by hand are recorded in `userEdited` and are never re-derived — there is no UI yet to hand-edit an extracted field, so this gate exists but isn't reachable from the UI.
2. **Records already use the full v2 schema** — `raw`, `capturedAt`, `enrichment`, `type`, `title`, `occurredAt`, `tags`, `rating`, `details`, `links`, `userEdited`, `media`, timestamps, `deleted`. Everything except the user's text is null/empty in v0. This exists so no captured data ever needs migrating. Don't strip unused fields.
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

94 Playwright tests in `test/smoke.py`. No test runner, no framework — the file serves the repo on an ephemeral port, drives it with headless Chromium, and gives each test a fresh browser context. Dropbox endpoints are stubbed, so it runs offline and never touches a real account. On-device enrichment is stubbed the same way, via `window.__LELOG_TEST_EXTRACTOR__` — no test touches real WebGPU or downloads real model weights.

```bash
python3 test/smoke.py            # all
python3 test/smoke.py search     # only tests matching "search"
```

Needs Playwright once: `pip install playwright && python3 -m playwright install chromium`.

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

**The device is the thing you do not have.** No WebGPU, and the network here
blocks `huggingface.co`, `cdn.jsdelivr.net` and `unpkg.com`. So the model
never runs in this environment, and anything about *this GPU* or *this
network* can only come from the phone. Everything else can and should be
settled here first — most of the round trips in this feature's history were
avoidable, not device-specific.

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

**Ask for the diagnostics blob, not one fact at a time.** Settings →
Enrichment → *Copy diagnostics* returns version, GPU and adapter, whether
`shader-f16` is really supported, which model resolved and whether it is
cached, the settings in force, entry counts, last timing and last error. One
paste answers what previously took several exchanges. If a report arrives
without it, ask for that before theorising.

**Look at UI before shipping it.** Drive the app with Playwright at a phone
width (412×915) and screenshot the state being changed. A toast with no
`max-width`, and per-type `details` that were extracted but rendered
nowhere, both shipped because nobody looked.

**Say which half is unverified.** When a change cannot be exercised here,
state that plainly rather than implying it works.

## Working from a phone

Cloud sessions start cold with only this repo, so this file, `docs/architecture.md` and `docs/ideas.md` are the entire context. Keep them true.

The cloud environment needs a setup script to run the tests — see `.claude/cloud-setup.sh`. Point the environment's setup script at it, and allow `cdn.playwright.dev` in the environment's network access or the Chromium download will fail.
