# Le Log

A private capture app. One text box, a searchable list, an export button, and Dropbox sync. No AI, no accounts.

Live at:

```
https://yann-mathieu.github.io/lelog/
```

The repo is public because GitHub Pages will not serve a private repo on a free plan. The site carries a `noindex` tag so it does not turn up in search results. **Your entries are not in this repo** — they live in IndexedDB on your device and in your own Dropbox app folder, neither of which this site serves. Someone who opens the URL gets an empty app of their own.

## Installing on your phone

The app must be served over **HTTPS** — opening `index.html` from your Files app will not work, because browsers block offline storage and home-screen install on local files. The Pages URL above is HTTPS, so it's fine.

1. Open it in **Chrome on Android**
2. Menu (⋮) → **Add to Home screen** → Install
3. Open it from the home-screen icon from then on

Step 3 matters. Installing is what makes Android grant persistent storage, which stops it from clearing your entries to reclaim space. The settings sheet shows whether that was granted.

## Using it

- Type a line, hit **Save**. That's the whole interaction.
- Tap any entry to edit or delete it.
- Search filters across everything as you type.
- The gear icon opens settings: sync, export, import, storage status.

One sentence per entry is plenty. Don't write paragraphs — this is a log, not a diary.

## Sync

Settings → **Connect Dropbox**, approve, then **Sync now**. You authorise once; the app holds a refresh token from then on.

Your entries go to **`/Apps/LeLog/`**, one readable JSON file per entry:

```
/Apps/LeLog/memories/2026/mem_01J8XQZ4K2N7.json
```

A record's path comes from its capture date, which never changes, so a file stays put for the life of the entry no matter how often you edit it.

**What it does.** Sync pulls first, then pushes. Only changes move in either direction — a stored cursor means Dropbox reports just what changed, and files already at the version we hold are not downloaded again.

**When two devices disagree.** The newer `updatedAt` wins, for the whole record. That means editing the same entry on two offline devices discards one of the edits rather than merging them; Dropbox keeps version history if you ever need to dig one back out.

**Deletes.** A delete beats a concurrent edit, but only the deletion itself — the newer text is kept. So deleting on your phone while your laptop edits the same entry leaves a tombstone carrying the newer text. Nothing is silently discarded.

**Deleting a file in Dropbox by hand does not delete the entry.** The file comes back on the next sync. Only a record whose `deleted` flag is `true` counts as a deletion, so a stray drag to the trash cannot destroy data.

**Scope.** The Dropbox app is registered with App folder access. It can only ever see `/Apps/LeLog/` and is structurally incapable of reading anything else in your account. There is no client secret: the app uses OAuth 2 with PKCE, which is the flow designed for public clients, so the app key being visible in `index.html` is expected and safe.

If connecting from the installed app fails, use **"Trouble connecting? Paste a code instead"**. An installed PWA can send the OAuth redirect to the browser rather than back into the app; that fallback exists for exactly that case.

## Backups

Sync is a second copy, not a backup — it faithfully replicates a mistake to every device. **Export is still the thing that saves you.**

Export writes a single JSON file to your downloads. The app nags you after 15 entries if you have not exported in a week, and offers one before the very first upload.

Import merges rather than overwrites: entries you already have are kept, newer versions win, so re-importing an old backup is safe.

## Publishing changes

```
git push
```

Pages redeploys in a minute or two. **Bump `CACHE` in `sw.js` whenever `index.html` changes**, or clients keep serving the old shell from the service worker cache and never see the update.

To set Pages up from scratch: **Settings → Pages** → Source *Deploy from a branch* → Branch `main`, folder `/ (root)`. The branch has to exist first — Pages cannot target an empty repo.

## Testing

```
python3 test/smoke.py            # all tests
python3 test/smoke.py search     # only tests matching "search"
```

Needs Playwright once: `pip install playwright && python3 -m playwright install chromium`.

The suite serves the repo over http on an ephemeral port and drives it with headless Chromium; each test gets a fresh browser context. Dropbox endpoints are stubbed, so it runs offline and never touches a real account. Run it before and after any change.

## What's inside

| File | Purpose |
|---|---|
| `index.html` | The entire app — markup, styles, logic |
| `manifest.webmanifest` | Makes it installable |
| `sw.js` | Service worker, so it works offline |
| `icon-*.png` | Home-screen icons |
| `test/smoke.py` | Playwright smoke suite |
| `docs/architecture.md` | Design rationale |

No build step, no dependencies, no framework.

## About the data format

Every entry is stored in the **full schema the finished app expects** — `raw`, `capturedAt`, `enrichment`, `type`, `tags`, `details`, `links`, `userEdited` and the rest — with everything except your text left null or empty.

That's deliberate. When AI enrichment arrives, it fills in those blanks on the entries you have already written. **Nothing you capture now will need migrating.** The files in Dropbox are exactly these records, so abandoning the app still leaves you with plain readable JSON you own.

Deletes are tombstones (`deleted: true`) rather than removals. That is what makes a delete propagate to your other devices instead of the entry simply reappearing.

## Current limits

- No AI. Nothing is typed, tagged, linked, or quizzed — entries are raw text you can search.
- Sync is manual. You press **Sync now**; it does not yet run on save or on launch.
- Concurrent edits to the same entry on two devices lose one side (see Sync).
- No photos or voice yet.
