# Personal Memory Vault — Architecture & Plan

**Status:** Draft v4, with phase 1 corrections
**Date:** 13 August 2026; corrected 2 September 2026
**Name:** Le Log *(was MemoryVault; §10 question 1 is settled)*

**Corrections of 2 September 2026.** Phases 0 and 1 are built and in daily use. Where this document and the code disagree, the code is right and the disagreement is marked inline. Three sections were materially wrong: §5.1–5.3 (folder name, merge strategy), §7 (tech stack), §10 (the name). Everything else stands.

**Changes since v4.0:** added §1.1 — this is a log, not a diary or a notes app, and the design consequences that follow (no streaks, no calendar view, no daily prompt).

**Changes since v3:** the capture model is now free text with AI enrichment (§2), which restructures much of the document. Types become emergent rather than chosen (§4). The security model changes materially (§6) because every note now passes through a language model. The quiz engine and the enrichment engine turn out to be the same machine (§8).

---

## 1. What we're building

A private app where you dump a sentence about something you want to remember — a book, a person, a meal, a place — and it does the filing. Later, it quizzes you on the parts worth having in your head.

**Decisions locked in:**

| Decision | Choice | Why |
|---|---|---|
| Platform | Android, PWA | Silent updates, no app store, no APK sideloading. |
| Storage | Your own Dropbox | No server to run, pay for, or breach. Backup and version history free. |
| **Capture** | **One free-text box. AI extracts structure afterwards.** | Structure is valuable; making *you* produce it is what kills these apps. |
| Types | Emergent, not chosen at capture | You never pick from a menu. The model proposes; you correct. |
| Relations | Proposed by AI, confirmed by you | Answers the linking objection: links stop being manual work. |
| Security | Cloud, with a real tension to resolve (§6) | Enrichment means notes leave the device. This is now the central trade-off. |
| Existing data | Nothing to import | |

**Principles, revised:**

1. **The data outlives the app.** Plain readable JSON in your Dropbox. Abandon this in five years and you still have everything.
2. **Offline-first.** Capture never waits for anything — not the network, not the model, not you.
3. **Your words are sacred.** The AI adds structure alongside what you wrote. It never rewrites it. (§2.3)
4. **Capture friction is the enemy.** The entire point of this rewrite.

### 1.1 What this is, precisely — it's a log

Once capture is a free-text box, the app starts to resemble both a diary and a notes app. It is neither, and being clear about which resolves a dozen downstream decisions.

- A **diary** is organised by *time*. The day is the unit, gaps feel like failure, and you write to reflect.
- A **notes app** is organised by *topic or nothing* — a searchable pile holding anything, including tasks and drafts.
- **This is a log.** The unit is an *encounter*: a thing you met, read, ate, or visited. Factual, timestamped, a sentence long, written for later retrieval and recall. Closer to a ship's log or a field notebook than to either of the above.

**Design consequences, which is why this matters:**

| | If it were a diary | Because it's a log |
|---|---|---|
| Primary view | Calendar, by day | By entity, type, and search |
| Missing days | A visible gap | Meaningless — nothing to display |
| **Streaks** | Natural motivator | **Excluded. Actively harmful.** |
| Empty week | Failure | Nothing happened worth logging |
| Entry length | Paragraphs | A sentence |
| Opening prompt | "How was your day?" | Just a cursor |

The streak exclusion is deliberate and worth defending: a streak pushes you to log *something* daily to keep it alive, which produces filler, which degrades exactly the data the quiz engine depends on. Same reasoning kills the daily prompt — "how was your day?" is an invitation to write the wrong thing.

**The boundary is "anchored to an encounter," not "no subjectivity."** *"Loud but great"* is an assessment worth keeping. *"Marie seemed down"* is precisely the observation that makes the people side valuable. A judgement about a thing is in scope; a free-floating feeling about your life is diary.

**And the app enforces this without refusing anything.** Write three paragraphs about your week and the extractor finds no entity, files it as an untyped `note`, and never generates a card from it. Nothing is rejected; it simply doesn't acquire structure. The boundary holds through what earns enrichment rather than through a rule you'd have to remember — which is the only kind of boundary that survives contact with real use.

---

## 2. The capture model

### 2.1 The change

The v3 design asked you to pick a type, then fill a form. That was backwards. Every field is a small tax collected at the exact moment you're least able to pay it — standing in a restaurant, half in a conversation, about to put your phone away.

The v4 design: **one text box.** You write

> *bo bun at le petit cambodge with marie and tom, 10e, loud but great, book ahead*

and you're done. Three seconds. Everything else happens later, without you.

The model then extracts: this is a `restaurant`, called Le Petit Cambodge, in the 10th, you ate bo bun, you rated it positively, and Marie and Tom — both already people in your vault — were there. It writes the structure, proposes the links, and gets on with it.

### 2.2 What this kills

Worth being explicit, because it deletes a lot of the previous plan:

- **The 25-type catalogue** stops being a build task. Types are an *output* now. The model can suggest new ones when it notices a pattern ("you've logged eleven wines as notes — want a wine type?").
- **The `details` field specifications** become hints for the extractor rather than forms you fill in.
- **Your linking objection is resolved.** Links were only ever suspect because they were manual. Now they're proposed from text you already wrote.
- **The type-picker friction** — the thing I flagged as the main risk to the whole project — is gone.

### 2.3 The rule that makes this safe

**The raw text is immutable. The AI writes to separate fields. It never touches what you wrote.**

This is non-negotiable and it's what makes the whole approach low-risk:

- If the model misreads something, your words are still there, exactly as typed.
- Every derived field is marked with its provenance and confidence, so you can always see what you said versus what was guessed.
- Because `raw` is preserved forever, **enrichment can be re-run** — with a better model in 2028, over your entire history, at no cost to you. Your archive improves without you doing anything.

That last property is worth more than it first appears. It means capturing badly today is fine.

### 2.4 The record

```json
{
  "id": "mem_01J8XQZ4K2N7",
  "schemaVersion": 2,

  "raw": "bo bun at le petit cambodge with marie and tom, 10e, loud but great, book ahead",
  "capturedAt": "2026-08-11T21:04:33Z",
  "captureSource": "text",

  "enrichment": {
    "status": "done",
    "model": "claude-sonnet-4-5",
    "at": "2026-08-11T21:06:02Z",
    "confidence": 0.91
  },

  "type": "restaurant",
  "title": "Le Petit Cambodge",
  "occurredAt": "2026-08-11",
  "tags": ["paris", "asian"],
  "rating": 4,
  "details": {
    "cuisine": "Cambodian",
    "neighbourhood": "10e",
    "dish": "Bo bun",
    "wouldReturn": true
  },
  "links": [
    { "rel": "with", "to": "mem_PERSON_MARIE", "confidence": 0.88, "confirmed": true },
    { "rel": "with", "to": "mem_PERSON_TOM",   "confidence": 0.62, "confirmed": false }
  ],

  "userEdited": ["title"],
  "media": [],
  "createdAt": "2026-08-11T21:04:33Z",
  "updatedAt": "2026-08-11T21:06:02Z",
  "deleted": false
}
```

Two fields carry more weight than they look:

**`userEdited`** lists fields you corrected by hand. Those are locked — re-enrichment will never overwrite them. You correct something once, forever.

**`confirmed`** on each link distinguishes a confident auto-applied link from a guess awaiting your nod. See §3.3.

### 2.5 The pipeline

Capture and enrichment are completely decoupled. This is what preserves offline-first.

1. **Save.** Raw text hits IndexedDB immediately, `enrichment.status: "pending"`. The UI is done. No spinner, no network, no waiting. This step works on a plane.
2. **Queue.** The record joins the enrichment queue.
3. **Enrich.** When there's network, a batch goes to the model along with context: your existing people, your current tag vocabulary, your type list, and recent captures for continuity.
4. **Apply.** High-confidence extractions are applied silently. Low-confidence ones land in the review queue (§2.6).
5. **Sync.** Dropbox gets both raw and derived fields.

If enrichment never runs — no network, no API key, you turned it off — you still have a searchable pile of timestamped text. **The app degrades to something useful rather than something broken.** That property is load-bearing.

### 2.6 Clarifying questions

Your instinct here is right: the moment just after capture is when your memory is richest, and a good question then ("who else was there?", "what did you actually order?") captures detail that's gone in a week.

But this is also the single most dangerous feature in the app. An app that interrogates you every time you use it gets deleted. So:

- **Never at capture.** Capture ends when you hit save. Always.
- **Batched, not immediate.** Questions accumulate in a queue.
- **Always skippable**, and skipping is never punished or re-asked immediately.
- **Idle-moment framing** — a "polish" screen you open when you feel like it, not a notification that nags.
- **Ask only where the answer is worth having.** A missing `priceLevel` isn't worth a question. A missing person at a dinner is.

**And here's the part that makes this elegant:** the enrichment queue and the quiz queue are the same screen with a different time offset.

> *"Who were you with at Le Petit Cambodge?"*

Asked tomorrow, that's enrichment — you know, and the answer fills a gap. Asked in eight months, that's a quiz — you half-remember, and answering strengthens it. **Same question generator, same interface, same interaction. Only the timing and the grading differ.** Build it once.

This collapses two features into one and is the strongest argument for your proposal.

### 2.7 Capture surfaces

All feeding the same box:

- **Text** — the default. One tap from the home screen to a cursor in a field.
- **Voice** — dictate; the transcript is the raw text. Best in-the-moment option, and the model handles the messiness of speech better than a form ever could.
- **Share** — share a podcast episode, article, or map pin from any Android app; the shared text and URL become the raw capture.
- **Photo** — a book cover, a business card, a wine label. The image is the capture; the model reads it. *(Later phase.)*

---

## 3. What the model actually does

### 3.1 Extraction

Given raw text plus context, the model returns: type, title, date, tags, rating, type-specific details, and proposed links. Structured output with a strict schema, so it can't invent field names or drift.

**Guarding against taxonomy drift** — the main risk of letting a model choose categories:

- **Types come from a closed list.** The model picks one or returns `note`. It can *propose* a new type separately, which you approve once, and only then does it enter the list.
- **Tags come from your existing vocabulary.** New tags are proposed, not silently created. Without this you get four hundred near-duplicate tags within a year — `paris`, `Paris`, `paris-france`, `trip-paris` — which is worse than no tags.
- **Uncertainty is allowed.** A `null` type is a fine answer. Guessing wrong is worse than not guessing.

### 3.2 Confidence and what happens at each level

| Confidence | Behaviour |
|---|---|
| High | Applied silently. You never see it happen. |
| Medium | Applied, but flagged in the review queue for a glance. |
| Low | Not applied. Sits as a suggestion you accept or ignore. |
| Refused | Left as an untyped note. Perfectly acceptable outcome. |

### 3.3 Entity resolution is the hard part

"Marie" → *which* Marie? This is where the model will be wrong most often, and **a wrong link is worse than no link**, because it silently corrupts what you'll later be quizzed on.

Mitigations:

- Your existing people go to the model as context, so it matches against a real list rather than guessing from nothing.
- Only unambiguous matches auto-confirm. One Marie in your vault and a first-name match is fine. Two Maries is always a question.
- Unconfirmed links are visually distinct and never used to generate quiz cards until confirmed.
- New people are *proposed*, never silently created. Otherwise a typo becomes a permanent phantom friend.

### 3.4 Re-enrichment

Because `raw` is immutable and `userEdited` is respected, the whole archive can be reprocessed at any time — after a model upgrade, after you add a type, after you fix a tag vocabulary. It's a background job over files you already own, and your manual corrections survive it.

---

## 4. Types, now emergent

Types still exist — the quiz engine needs them to know what questions to ask, and `mode` (§8.1) still decides whether something gets drilled at all. But you never choose one at capture.

**Seed list, kept deliberately small:** `book`, `person`, `place`, `restaurant`, `podcast`, `film`, `idea`, `conversation`, `note`.

Nine, not twenty-five. The rest arrive by evidence: when the model has filed eleven things as notes that all look like wine, it proposes a `wine` type with the fields it's been seeing. You approve, it re-enriches those eleven, and the type exists. **The catalogue grows from your actual life instead of from our guesses**, which is what the v3 phased list was clumsily trying to approximate.

`mode` — `recall`, `reference`, or `ideas` — is a property of each type and drives §8. People and conversations are recall; restaurants and places are reference; books, podcasts and ideas are ideas.

---

## 5. Storage and sync

Substantially unchanged from v3 — the file-per-record design turns out to be exactly right for this, since enrichment rewrites individual records asynchronously.

### 5.1 Dropbox

An app registered with **App folder** scope: it can only ever see `/Apps/LeLog/`, structurally incapable of reading anything else in your Dropbox. OAuth 2 with PKCE (supported for public clients), `token_access_type=offline` for a refresh token so you authorise once.

### 5.2 Layout

```
/Apps/LeLog/
├── memories/2026/mem_01J8XQZ4K2N7.json
├── reviews/2026-08.ndjson        ← append-only
├── media/mem_01J8XQZ4K2N7/cover.jpg
└── meta.json                     ← types, tag vocabulary, settings
```

`meta.json` now matters more: it holds the type list and tag vocabulary the extractor is constrained by, so the controlled vocabulary syncs across devices along with everything else.

### 5.3 Local cache and sync

Full local copy in IndexedDB, written directly rather than through Dexie — see §7. Dropbox is the source of truth; the phone is a rebuildable cache, which is precisely why the standard PWA objection about storage eviction doesn't bite.

Push uses `WriteMode.update(rev)` so concurrent edits are detected rather than clobbered. Pull uses `files/list_folder/continue` with a stored cursor, so only changes come down. Sync runs pull-then-push, which is what makes a rejected push heal by itself: the pull brings down the remote copy and its current rev, the merge picks a winner, and the push then writes with a rev Dropbox accepts. No conflict is ever surfaced to the user.

**Correction: conflicts do not merge field-by-field.** This paragraph originally specified field-level merge on `updatedAt`. That is not implementable against this schema — a record carries one record-level `updatedAt`, so there are no per-field clocks to compare. The charitable reading, "newer record wins but fill nulls from the older one", is worse than useless: deleting a tag on one device would see it restored from an older copy on another, so removing a *value* could never propagate.

What is built instead is **record-level last-write-wins on `updatedAt`, with remote winning ties.** Remote-wins is what makes two devices converge — the device holding the remote copy is already in that state, so both sides reach the same answer. An early note here proposed breaking ties on `rev`; that was wrong, revs are not meaningfully comparable.

**Deletion is the one departure from plain LWW.** If either side has `deleted: true` the result is deleted, but everything else still follows last-write-wins. Delete on your phone while your laptop edits the text and you get a tombstone carrying the newer text. Strict tombstone-wins would honour the delete and silently discard the edit; since a tombstone retains `raw`, this way neither side loses content.

**What this costs.** Editing the same entry on two offline devices discards one edit rather than merging them, and `updatedAt` is wall-clock time from whichever device wrote it, so a device with a skewed clock systematically wins or loses. Dropbox version history is the recovery path. Per-field clocks would fix both and belong in phase 2, when enrichment starts writing to records concurrently with the user — which is the first time genuinely concurrent field-level writes can occur at all. Until then, field-level merge is machinery for a conflict that cannot happen.

**Three rules the implementation holds to, each with a test.** Pull never deletes a local record; only `deleted: true` inside a file marks a deletion. A file vanishing from Dropbox is not a tombstone — the local copy re-uploads, so deleting a file by hand heals rather than destroys. An empty or missing remote folder means nothing has been uploaded, never that everything was deleted. That last one is the specific path by which the only copy of the data could be lost.

**One new wrinkle:** enrichment will produce a second write to every record, a minute or two after capture. Handled — change-driven syncs are debounced, so a burst of writes uploads once.

### 5.4 Links, still one-sided

The child holds `partOf`; the parent never lists its children; reverse links are computed locally. If both sides stored the edge, adding a restaurant to a trip would rewrite the trip file, making busy containers a write-contention hotspot. One-sided edges mean creating a child never touches the parent.

---

## 6. Security — the tension is now central

### 6.1 What changed

In v3 the AI question was a footnote about a future quiz feature. **It is now the main capture path.** Every note you write goes to a language model. That is a real change to the security posture and it deserves the front of the document, not a footnote.

### 6.2 Threat model

| # | Scenario | Likelihood | Covered? |
|---|---|---|---|
| 1 | Phone lost or stolen | Realistic | App lock + device encryption. Data recoverable. **Solved.** |
| 2 | You delete things by accident | Realistic | Tombstones + Dropbox version history. **Solved.** |
| 3 | App bug mangles data | Realistic | Immutable `raw`, per-record files, versioning. **Better than v3** — the AI cannot destroy your original text. |
| 4 | You abandon the app | Realistic | Plain JSON you own. **Solved.** |
| 5 | Someone browses your unlocked phone | Plausible | App lock. **Solved.** |
| 6 | Dropbox breach or insider | Unlikely | Not covered by default. §6.4 |
| 7 | **LLM provider sees your notes** | **Certain, by design** | **New. This is the trade-off.** §6.3 |
| 8 | Dropbox account compromised | Unlikely | **Covered.** 2FA enabled 2 September 2026. |

Note that #3 actually *improved*. Because the model writes alongside your text rather than over it, an AI mistake is recoverable in a way a form-entry mistake never was.

### 6.3 The new one, honestly

Every capture goes to a third party for processing. Concretely: a note that a friend's father is unwell, or your private assessment of a colleague, is transmitted to an API.

Three responses, and they're genuinely different bets:

**(a) Cloud API, notes leave the device.** Best extraction quality by a wide margin. Cost is trivial — fractions of a cent per note. The major providers offer no-training-on-API-data terms and bounded retention, but the honest framing is: *you are trusting a second company to process what you'd already decided to let a first company store.* If Dropbox holding your notes is acceptable, an API processing them is a comparable — not identical — exposure. Processing is transient; storage is not.

**(b) On-device model via WebGPU.** Genuinely viable in 2026 — WebLLM runs small models in the browser, and a PWA can use it. Nothing ever leaves the phone, which resolves #6 and #7 completely and makes full encryption compatible with enrichment. Costs: a several-hundred-megabyte model download, meaningfully worse extraction (especially entity resolution, the part that's already hardest), battery, and it won't run well on older hardware.

**(c) Hybrid — the one I'd build.** Cloud by default, with a **private flag** per note and per type. Flagged content is either enriched on-device or not at all, and is encrypted before it touches Dropbox. Default the flag on for `person` and `conversation` — the social cluster, the only category holding sensitive data about people who didn't consent to being in your database.

The cost of (c) is that your most personal notes get the weakest enrichment, which is a real and slightly perverse trade. But it's the only option that doesn't force one global answer to a question that genuinely differs by content.

### 6.4 Encryption tiers, updated

| Tier | What | Compatible with cloud AI? |
|---|---|---|
| 0 | Plain JSON in Dropbox | Yes |
| 1 | + app lock, encrypted local cache | Yes |
| 2 | + client-side AES-GCM on flagged types | **Only with on-device or no enrichment for those types** |
| 3 | Everything encrypted | No cloud AI at all |

**Recommendation: Tier 1 at launch. Tier 2 for the social cluster once on-device enrichment is proven, or immediately for anyone who'd rather have unenriched privacy than enriched exposure.**

A metadata caveat worth knowing rather than discovering: links *pointing at* an encrypted record still reveal that a relationship exists, just not its content. Structure leaks even when text doesn't.

### 6.5 Today, regardless

Turn on 2FA for your Dropbox account. Under this architecture it is the security boundary for everything.

**Done, 2 September 2026.** Worth noting what this does and does not cover. It protects the account, so a leaked password alone no longer reaches your entries. It does nothing for threats #1 and #5 — a lost phone, or someone picking up your unlocked one — because the local IndexedDB copy is readable by anyone holding the device. App lock, scheduled for phase 3, is what closes those.

---

## 7. Tech stack

**This table describes a plan that was not followed.** Phase 0 shipped as vanilla HTML, CSS and JavaScript in one file, with no build step and no dependencies, and phase 1 kept it that way — the six Dropbox endpoints needed are about 120 lines of `fetch`. That constraint is now recorded in `CLAUDE.md` and has held through two phases. The right-hand column below records what was actually built.

| Layer | Original choice | Built as |
|---|---|---|
| Framework | React + TypeScript, Vite | None. One `index.html`. |
| PWA shell | `vite-plugin-pwa` (Workbox) | Hand-written `sw.js`, ~50 lines |
| Local DB | Dexie.js over IndexedDB | IndexedDB directly |
| Search | MiniSearch | Substring match over `raw`; revisit when enrichment adds fields to search |
| Dropbox | Official `dropbox` SDK | `fetch` against the HTTP API |
| UI | Tailwind CSS | Plain CSS with custom properties |
| **Enrichment** | **Claude API, structured outputs** | Strict schema prevents field invention |
| **On-device option** | **WebLLM / WebGPU** | Phase 5 experiment; viable but heavy |
| Spaced repetition | `ts-fsrs` | Shares the question generator with enrichment |
| Crypto | Web Crypto (AES-GCM, PBKDF2) | |
| Hosting | Cloudflare Pages, free tier | |

**On the API key:** a PWA cannot hold an API key safely — anything in the bundle is public. Two options: you paste your own key into settings and it stays in your browser (simplest, zero infrastructure, and it's your key and your bill), or a tiny serverless proxy holds it (cleaner, but reintroduces a server we'd otherwise avoided). I'd start with your own key in settings.

---

## 8. The quiz engine

### 8.1 Mode decides what gets drilled

- **Recall** (people, conversations) — drilled hard. The genuinely difficult case, and the highest payoff.
- **Ideas** (books, podcasts, ideas) — the *content* is the card, never the title.
- **Reference** (restaurants, places) — few cards or none. You don't need to recite restaurant names; you need to find them.

### 8.2 One machine, two jobs

From §2.6: the enrichment questioner and the quiz questioner are the same component.

| | Enrichment | Quiz |
|---|---|---|
| When | Days after capture | Months after |
| You | Know the answer | Half-remember it |
| Result | Fills a gap in the record | Strengthens the memory |
| Grading | None | FSRS four-button |

Same generator, same UI, same queue. Build it once in phase 3, use it for both. This is a significant simplification over v3, where they were separate features in separate phases.

### 8.3 Cards

One memory yields several independently scheduled cards — `{memoryId}:{template}`. You might reliably recall a face while consistently blanking on where you met. Scheduling those separately is what makes the difference between a useful quiz and a tedious one.

Review state lives in the separate append-only log, never inside the memory. Quiz bugs cannot corrupt memories; wiping quiz history costs you nothing else.

### 8.4 Generated questions

With cloud enrichment already in the pipeline, LLM-written questions are nearly free — and much better than templates. Templates remain the fallback for private-flagged content and offline use.

### 8.5 Sessions

Twenty cards, two minutes, bounded. A quiz that feels like homework is abandoned inside a fortnight.

---

## 9. Build order

| Phase | Ships | You get |
|---|---|---|
| **0** ✅ | **Built.** One text box, save, edit, search, export/import. Local-only (IndexedDB), installable PWA, offline. No AI, no sync, no accounts. | A usable capture app today |
| **1** ✅ | **Built.** Dropbox: app registration, OAuth PKCE, sync engine, automatic sync. | Backup and multi-device |
| **2** | Enrichment: extraction, types, tags, confidence, review queue | The structure appears by itself |
| **3** | Links + entity resolution, the question queue *(enrichment mode)*, app lock | Connected data, richer notes |
| **4** | Quiz mode over the same queue, FSRS scheduling | The reason for the project |
| **5** | Voice + photo capture, share-target, on-device model experiment, Tier 2 encryption | Fast capture; the privacy answer |

**Phase 0 deliberately has no AI.** It produces raw material — real captures of yours — to build and tune the extractor against in phase 2. Designing prompts against imaginary notes is guesswork; designing them against two hundred of your actual ones is engineering.

It also means the Memento trial is redundant. Phase 0 *is* the trial, in the real app, with data that never needs migrating.

**One caveat that phase 0 carries and phase 1 removes:** §5.3 argued that IndexedDB eviction was harmless because Dropbox was the source of truth. With sync deferred, that argument doesn't hold — the phone is the only copy. Phase 0 therefore ships manual export/import from day one, requests persistent storage on load, and nags after 15 entries without a backup. Installing the PWA to the home screen is what makes Android grant persistence, so it matters more than it sounds.

---

## 10. Open questions

1. ~~**Name?**~~ *Settled: Le Log. The Dropbox app folder is `/Apps/LeLog/`.*
2. **Whose API key?** Yours pasted into settings (simple, your bill, ~pennies a month) or a small proxy (cleaner, adds a server).
3. **Default for the social cluster:** cloud enrichment on, or private-by-default with weaker extraction? This is the §6.3 decision and only you can make it.
4. **Learning a language?** If so, vocabulary moves up — it's the best spaced-repetition fit in the catalogue.

---

## 11. Risks

- **Habit, still the top risk.** Mitigated far better than in v3: three seconds and no decisions is about as low as capture friction goes.
- **Extraction quality on messy real notes.** Unknown until we try. Phase 1 exists to produce the test set. The `note` fallback means bad extraction degrades to "a searchable pile of text" rather than to broken.
- **Silent wrong links.** The subtlest failure here — a wrong link quietly corrupts what you're later quizzed on. Hence confirmation gates on ambiguous entities.
- **Taxonomy drift.** Controlled vocabulary with proposal-and-approve, not free generation.
- **AI dependency.** If the API is unreachable or you stop paying, the app still captures, searches, and syncs. It loses structure, not function.
- **Privacy creep.** The convenience of enrichment will tempt you to leave everything cloud-enriched. The private flag only works if it's a real habit. Worth revisiting once you see how much sensitive content actually accumulates.
- **Drift toward diary or notes app.** The two directions this can degrade in. Diary drift produces long narrative entries the extractor can't grip and the quiz engine can't use; notes-app drift fills the vault with to-dos and drafts, where it will lose to Keep. §1.1 is the defence, and the absence of streaks, calendar view, and daily prompts is that defence made structural rather than aspirational.
- **Scope creep.** This app remembers what you've already experienced. Not a to-do list, not a journal, not a bookmark manager.

---

## Sources

- [Dropbox OAuth Guide](https://developers.dropbox.com/oauth-guide) — PKCE, App folder scoping, refresh tokens
- [Dropbox Detecting Changes Guide](https://developers.dropbox.com/detecting-changes-guide) — cursor-based delta sync
- [WebLLM: In-Browser LLM Inference Engine](https://webllm.mlc.ai/) — on-device option
- [WebLLM paper](https://arxiv.org/abs/2412.15803)
- [web.dev — PWA offline data](https://web.dev/learn/pwa/offline-data)
