# Log — v0

A private capture app. One text box, a searchable list, and an export button. No AI, no sync, no accounts.

## Publishing from this repo

All files sit at the repo root, which is what GitHub Pages expects.

1. In the repo, click **Add file → Upload files**
2. Drag in all seven files (select them all — don't drag the folder, or they end up nested)
3. Commit to `main`
4. **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, folder `/ (root)` → Save

After a minute or two the app is live at:

```
https://yann-mathieu.github.io/lelog/
```

All paths in the app are relative, so serving from a `/lelog/` subdirectory works without changes.

## Installing on your phone

The app must be served over **HTTPS** — opening `index.html` from your Files app will not work, because browsers block offline storage and home-screen install on local files. The GitHub Pages URL above is HTTPS, so it's fine.

Once the URL is live:

1. Open it in **Chrome on Android**
2. Menu (⋮) → **Add to Home screen** → Install
3. Open it from the home-screen icon from then on

Step 3 matters. Installing is what makes Android grant persistent storage, which stops it from clearing your entries to reclaim space. The settings sheet shows whether that was granted.

## Using it

- Type a line, hit **Save**. That's the whole interaction.
- Tap any entry to edit or delete it.
- Search filters across everything as you type.
- The gear icon opens settings: export, import, storage status.

One sentence per entry is plenty. Don't write paragraphs — this is a log, not a diary.

## Backups matter right now

**This phone is the only copy.** Until Dropbox sync exists, the export button is your entire safety net.

Export writes a single JSON file to your downloads. Put it somewhere that syncs — Drive, Dropbox, email it to yourself. The app nags you after 15 entries if you have not exported in a week.

Import merges rather than overwrites: entries you already have are kept, newer versions win, so re-importing an old backup is safe.

## What's inside

| File | Purpose |
|---|---|
| `index.html` | The entire app — markup, styles, logic |
| `manifest.webmanifest` | Makes it installable |
| `sw.js` | Service worker, so it works offline |
| `icon-*.png` | Home-screen icons |

No build step, no dependencies, no framework. Five files.

## About the data format

Every entry is stored in the **full schema the finished app expects** — `raw`, `capturedAt`, `enrichment`, `type`, `tags`, `details`, `links`, `userEdited` and the rest — with everything except your text left null or empty.

That's deliberate. When AI enrichment arrives, it fills in those blanks on the entries you have already written. When Dropbox sync arrives, these records upload as-is. **Nothing you capture now will need migrating.**

Deletes are tombstones (`deleted: true`) rather than removals, for the same reason: that's what will make deletes propagate correctly once more than one device is involved.

## Known limits of v0

- No AI. Nothing is typed, tagged, linked, or quizzed — entries are raw text you can search.
- No sync. One device.
- Clearing Chrome's site data, or uninstalling the app, deletes everything. Export.
- No photos or voice yet.
