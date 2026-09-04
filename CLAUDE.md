# Le Log — project context

A private capture app for things worth remembering: books, people, meals, places, podcasts. Later it quizzes you on the parts worth having in your head.

Full design rationale lives in **`docs/architecture.md`**. Read it before making architectural changes — most of the non-obvious decisions there have reasons that aren't visible from the code.

Unscheduled ideas live in **`docs/ideas.md`** — things worth building, not yet committed to, with the reasoning attached. Add to it freely; don't treat anything in it as agreed work.

## Current state

**Phases 0 and 1 shipped, in daily use since August 2026.** One text box, list, search, edit, soft delete, export/import, and Dropbox sync. Installable PWA, works offline.

**Phase 2's first slice shipped 4 September 2026:** on-device extraction (WebLLM/WebGPU, opt-in from Settings), filling type, title, tags, rating and per-type `details`. Nothing leaves the phone — no cloud API. High/medium-confidence extractions apply automatically (medium gets a quiet review marker); low-confidence guesses sit unapplied in `enrichment.suggestion`. No entity resolution, no interactive review queue yet — see the roadmap.

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

72 Playwright tests in `test/smoke.py`. No test runner, no framework — the file serves the repo on an ephemeral port, drives it with headless Chromium, and gives each test a fresh browser context. Dropbox endpoints are stubbed, so it runs offline and never touches a real account. On-device enrichment is stubbed the same way, via `window.__LELOG_TEST_EXTRACTOR__` — no test touches real WebGPU or downloads real model weights.

```bash
python3 test/smoke.py            # all
python3 test/smoke.py search     # only tests matching "search"
```

Needs Playwright once: `pip install playwright && python3 -m playwright install chromium`.

**Run it before and after every change.** Several tests exist specifically to catch regressions that would silently destroy data — the export shape, the three sync-never-deletes rules, and the v1→v2 database upgrade. When adding behaviour, add the test that fails without it, then check the test actually fails when you break the code deliberately. That practice has caught two real gaps in this suite already, both in sync paths that looked covered but were not.

`file://` will not work — IndexedDB and service workers need a real origin.

## Deployment

`git push` → GitHub Pages redeploys from `main` in a minute or two → `https://yann-mathieu.github.io/lelog/`. All paths are relative so the `/lelog/` subdirectory works unchanged.

**Bump `CACHE` in `sw.js` whenever `index.html` changes**, or the service worker keeps serving the old shell and clients never see the update.

The repo is public because Pages will not serve a private repo on a free plan. `index.html` carries a `noindex` tag so the app stays out of search results. Nothing sensitive is in here: entries live in IndexedDB and the user's Dropbox, and the Dropbox app key in `index.html` is public by design under PKCE. Don't commit backup JSON.

## Working from a phone

Cloud sessions start cold with only this repo, so this file, `docs/architecture.md` and `docs/ideas.md` are the entire context. Keep them true.

The cloud environment needs a setup script to run the tests — see `.claude/cloud-setup.sh`. Point the environment's setup script at it, and allow `cdn.playwright.dev` in the environment's network access or the Chromium download will fail.
