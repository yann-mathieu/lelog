# Le Log — project context

A private capture app for things worth remembering: books, people, meals, places, podcasts. Later it quizzes you on the parts worth having in your head.

Full design rationale lives in **`docs/architecture.md`**. Read it before making architectural changes — most of the non-obvious decisions there have reasons that aren't visible from the code.

## Current state

**v0, shipped.** One text box, list, search, edit, soft delete, export/import. Local-only (IndexedDB). Installable PWA, works offline. No AI, no sync, no accounts.

Vanilla HTML/CSS/JS in a single `index.html`. **No build step, no dependencies, no framework.** Keep it that way unless there's a strong reason — the whole thing is seven files and that simplicity is a feature.

## Invariants — do not break these

1. **`raw` is immutable.** When AI enrichment lands, it writes to separate fields alongside the user's text, never over it. Fields the user edits by hand are recorded in `userEdited` and are never re-derived.
2. **Records already use the full v2 schema** — `raw`, `capturedAt`, `enrichment`, `type`, `title`, `occurredAt`, `tags`, `rating`, `details`, `links`, `userEdited`, `media`, timestamps, `deleted`. Everything except the user's text is null/empty in v0. This exists so no captured data ever needs migrating. Don't strip unused fields.
3. **Deletes are tombstones** (`deleted: true`), never removals. Required for sync to propagate deletes correctly later.
4. **Capture never blocks.** No spinner, no network, no required field, no type picker. Save is instant and works offline. Enrichment is always async and always optional.
5. **This is a log, not a diary.** No streaks, no calendar view, no "how was your day?" prompt, no visible gaps for missed days. The unit is an *encounter*, not a day. See §1.1 of the architecture doc.
6. **Export must keep working.** Until Dropbox sync exists, the phone is the only copy and export is the entire safety net.

## Roadmap

| Phase | Scope |
|---|---|
| 0 ✅ | Capture, search, export. Local-only. |
| 1 | Dropbox sync (App folder scope, OAuth PKCE, one JSON file per record) |
| 2 | AI enrichment: extraction, types, tags, confidence, review queue |
| 3 | Links + entity resolution, question queue (enrichment mode), app lock |
| 4 | Quiz mode over the same queue, FSRS scheduling |
| 5 | Voice + photo capture, share target, on-device model, selective encryption |

The enrichment questioner and the quiz questioner are **the same component** at different time offsets — build once.

## Testing

No test runner. There's a Playwright smoke suite covering capture, edit, tombstone delete, search, export/import round-trip, reload persistence, schema shape, and service worker registration. Serve locally over http (`python3 -m http.server`) — `file://` won't work, since IndexedDB and service workers need a real origin.

## Deployment

GitHub Pages from repo root → `https://yann-mathieu.github.io/lelog/`. All paths are relative so the `/lelog/` subdirectory works unchanged. Bump `CACHE` in `sw.js` when shipping changes, or clients keep the old shell.
