# Ideas

Things worth building, not yet scheduled. Nothing here is committed to.

Roadmap phases live in `CLAUDE.md`; deep design rationale lives in `architecture.md`. This file is the space in between — an idea captured before it's decided, with enough reasoning attached that picking it up later doesn't mean re-deriving it.

Add anything, however half-formed. The cost of a bad idea sitting here is nothing.

---

## Link one entry to another

**Medium. Shape decided, not scheduled.**

*Decided 2 Sep 2026: general associations between two different things — not follow-ups on one thing, not containment.*

Two entries that each stand alone, with an edge recording that they relate: this book was recommended by Marie, this restaurant is where that conversation happened.

The schema is already there. Every record carries `links: [{rel, to, confidence, confirmed}]`, written from v0 so this needs no migration. Nothing reads or writes it yet. A manual link would be `{rel: 'related', to: <id>, confidence: 1, confirmed: true}`, with `links` added to `userEdited` so later AI enrichment never overwrites a link you made by hand.

**Constraints that carry over:**

- **Never at capture.** Invariant 4 — capture stays one box and one button. Linking happens afterwards, from an entry you are already looking at, or not at all.
- **One-sided edges** (§5.4). The entry you are on holds the pointer; the other end is never rewritten. Reverse links are computed locally at render.

**Worth remembering why this is not a contradiction.** §2.2 of the architecture doc records an objection to linking, on the grounds that manual links are work you stop doing. That objection still stands, and it is the reason linking must never enter the capture path. What makes it worth building anyway: links you make by hand are the training signal for phase 2's entity resolution. What *you* treat as related is better guidance for the extractor than any guess at it.

**Open:** whether follow-ups ("went back", "finished it") deserve their own relation later, or stay as general links. Watch how the general one actually gets used before deciding.

---

## Attach a photo

**Large. Storage decided, not scheduled.**

*Decided 2 Sep 2026: photos live in Dropbox only. The JSON export keeps a reference, not the image.*

`media: []` is in the schema already. §5.2 of the architecture doc puts the files at `media/{id}/photo.jpg` in the app folder.

**The consequence of that decision, stated plainly so it is not a surprise later:** export alone stops being able to restore everything. Text is still fully recoverable from the JSON, but photos exist only in Dropbox, so a Dropbox problem takes them with it. That is a real narrowing of the safety net described in invariant 6 and in the README.

**Middle option, if that turns out to bite:** keep photos in Dropbox as decided, but let export optionally pull them down and write a zip on request. Normal export stays small and fast; a "full export" button does the slow, complete thing. Costs a small zip writer — feasible in well under 100 lines, no library, no build step.

**Also unresolved:**

- Capture must not block (invariant 4). Attaching to an existing entry is safe; a camera in the capture path is not.
- Local storage: blobs in IndexedDB. Persistent storage matters much more once photos exist.
- Upload is a separate content-type path from the JSON records, and wants its own retry handling.

---

## Connect to the services you already listen on

**Large, mostly unexplored. The most interesting idea here.**

Audible, a podcast app, a music app — the app learns what you have been listening to instead of you typing it. A book you finished, an episode you listened through, an album you had on repeat are all encounters you would otherwise have to remember to log.

**A new capture surface.** §2.7 lists text, voice, share and photo — all things you *do*. This is passive: a feed the app reads. That is a real addition to the model, not a variation on share-target.

**The design constraint that matters most.** This must **propose, never auto-log.** §1.1 is explicit that the unit is an *encounter* — something you met and thought worth noting. Importing everything you listened to produces a stream of things you never judged worth remembering, which is exactly the argument used to exclude streaks: filler degrades the data the quiz engine depends on. A feed that silently fills the log would be the single fastest way to ruin it.

So: the feed proposes, and proposing is all it does. Same pattern already used for tags, types and links — propose and approve. Possibly surfaced in the same review queue as everything else, which would mean building nothing new to hold it.

**Feasibility, roughly, and worth checking properly before committing:**

| Service | Outlook |
|---|---|
| Spotify | Best case. Public Web API with recently-played and currently-playing, OAuth. |
| Apple Music | MusicKit exists; a PWA on Android is the wrong side of that fence. |
| Last.fm | Aggregates scrobbles across many players. One integration, many sources. |
| Podcasts | Wildly app-dependent. Some expose OPML export; few have usable APIs. |
| Audible | Likely the hardest. No public personal-library API. May be out of reach. |

The unhappy asymmetry: Audible is the one specifically wanted and the one least likely to be possible. Worth confirming that early rather than after building the framework around it.

**Also:** each integration is another third party seeing something about you, which belongs in the §6.2 threat model when this gets real. Different in kind from the enrichment trade-off — this is read access to another account, not sending your text somewhere.

---

## Smaller things

*Nothing here yet.*

---

## Notes

This file is in a public repo. Nothing sensitive belongs here — sketch the idea, not anything you would mind a stranger reading.
