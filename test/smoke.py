#!/usr/bin/env python3
"""Le Log — Playwright smoke suite.

Covers capture, edit, tombstone delete, search, export/import round-trip,
reload persistence, schema shape, and service worker registration.

The app needs a real origin — IndexedDB and service workers do not work over
file:// — so this serves the repo root over http on an ephemeral port and
drives it with headless Chromium.

Each test gets a fresh browser context, so IndexedDB, localStorage and the
service worker cache start empty and tests cannot leak into each other.

Usage:
    python3 test/smoke.py            # all tests
    python3 test/smoke.py search     # only tests whose name contains "search"

Setup, once:
    pip install playwright
    python3 -m playwright install chromium
"""

import base64
import functools
import hashlib
import http.server
import json
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(
        "playwright is not installed.\n"
        "  pip install playwright && python3 -m playwright install chromium"
    )

ROOT = Path(__file__).resolve().parent.parent

# The v2 schema every record must carry, from newRecord() in index.html.
# Invariant 2: v0 writes the full schema so captured data never needs migrating.
# If a change to the app adds or drops a key here, that is a schema migration
# and it must be a deliberate decision, not a side effect.
V2_KEYS = {
    "id", "schemaVersion", "raw", "capturedAt", "captureSource", "enrichment",
    "type", "title", "occurredAt", "tags", "rating", "details", "links",
    "userEdited", "media", "createdAt", "updatedAt", "deleted",
}

# Only ever present on a tombstoned record.
OPTIONAL_KEYS = {"deletedAt"}

# The enrichment sub-object's own keys, from newRecord() in index.html.
ENRICHMENT_KEYS = {"status", "model", "at", "confidence", "needsReview", "suggestion"}


# ---------- server ----------

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server():
    """Serve the repo root on a free port. Returns (base_url, shutdown)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    handler = functools.partial(QuietHandler, directory=str(ROOT))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/", httpd.shutdown


# ---------- app helpers ----------

def boot(page, base_url):
    """Load the app and wait for the first render to settle."""
    page.goto(base_url)
    page.wait_for_selector("#list")
    # Boot is async (openDB -> getAll -> render). The empty state or an entry
    # appearing is what tells us that chain finished.
    page.wait_for_function(
        "() => document.querySelector('#list').children.length > 0"
    )


def capture(page, text):
    """Type an entry and save it. Returns the number of entries afterwards."""
    before = page.locator(".entry").count()
    page.fill("#input", text)
    page.wait_for_selector("#saveBtn:not([disabled])")
    page.click("#saveBtn")
    page.wait_for_function(
        "n => document.querySelectorAll('.entry').length === n", arg=before + 1
    )
    return before + 1


def records(page):
    """Every record in IndexedDB, tombstones included.

    Opens without a version so this keeps working when DB_VERSION is bumped.
    """
    return page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const db = req.result;
                const r = db.transaction('memories', 'readonly')
                            .objectStore('memories').getAll();
                r.onsuccess = () => resolve(r.result || []);
                r.onerror = () => reject(r.error);
            };
        })
    """)


def open_sheet(page):
    page.click("#settingsBtn")
    page.wait_for_selector("#sheet.open")


def close_sheet(page):
    page.click("#closeSheetBtn")
    page.wait_for_selector("#sheet.open", state="detached")


def export_backup(page):
    """Click Export and return (payload, download path, filename).

    Leaves the sheet closed, so callers can go on clicking the list without
    the scrim swallowing the click.
    """
    open_sheet(page)
    with page.expect_download() as dl:
        page.click("#exportBtn")
    download = dl.value
    path = download.path()
    close_sheet(page)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload, str(path), download.suggested_filename


def texts(page):
    return page.locator(".entry .raw").all_inner_texts()


# ---------- tests ----------

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def test_capture_saves_an_entry(page, base_url):
    boot(page, base_url)
    assert "Nothing logged yet" in page.inner_text("#list")

    capture(page, "bo bun at le petit cambodge with marie")

    assert texts(page) == ["bo bun at le petit cambodge with marie"]
    assert "1 entry" in page.inner_text("#count")

    # Capture never blocks (invariant 4): the box is clear and ready again.
    assert page.input_value("#input") == ""
    assert page.locator("#saveBtn").is_disabled()


@test
def test_capture_writes_the_full_v2_schema(page, base_url):
    boot(page, base_url)
    capture(page, "dune, finally")

    rows = records(page)
    assert len(rows) == 1
    rec = rows[0]

    extra = set(rec) - V2_KEYS - OPTIONAL_KEYS
    missing = V2_KEYS - set(rec)
    assert not extra, f"unexpected keys on a fresh record: {sorted(extra)}"
    assert not missing, f"missing schema keys: {sorted(missing)}"

    assert rec["schemaVersion"] == 2
    assert rec["raw"] == "dune, finally"
    assert rec["captureSource"] == "text"
    assert rec["deleted"] is False
    assert rec["id"].startswith("mem_")
    # Everything the model will later fill is present but empty, never absent.
    assert rec["enrichment"] == {
        "status": "pending", "model": None, "at": None, "confidence": None,
        "needsReview": False, "suggestion": None
    }
    assert (rec["type"], rec["title"], rec["occurredAt"], rec["rating"]) == \
        (None, None, None, None)
    assert (rec["tags"], rec["links"], rec["userEdited"], rec["media"]) == \
        ([], [], [], [])
    assert rec["details"] == {}


@test
def test_edit_rewrites_raw_and_bumps_updatedat(page, base_url):
    boot(page, base_url)
    capture(page, "coffee at ten belles")

    before = records(page)[0]

    page.click(".entry .raw")
    page.wait_for_selector(".entry.editing .edit-area")
    page.fill(".edit-area", "coffee at ten belles, the filter was excellent")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    assert texts(page) == ["coffee at ten belles, the filter was excellent"]

    after = records(page)[0]
    assert after["id"] == before["id"]
    assert after["raw"] == "coffee at ten belles, the filter was excellent"
    assert after["capturedAt"] == before["capturedAt"], "capturedAt must not move"
    assert after["createdAt"] == before["createdAt"], "createdAt must not move"
    assert after["updatedAt"] >= before["updatedAt"]


@test
def test_edit_can_be_cancelled(page, base_url):
    boot(page, base_url)
    capture(page, "leave me alone")

    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "clobbered")
    page.click(".act-cancel")
    page.wait_for_selector(".entry.editing", state="detached")

    assert texts(page) == ["leave me alone"]
    assert records(page)[0]["raw"] == "leave me alone"


@test
def test_delete_is_a_tombstone_not_a_removal(page, base_url):
    boot(page, base_url)
    capture(page, "keep this one")
    capture(page, "delete this one")

    page.once("dialog", lambda d: d.accept())
    page.click(".entry:has-text('delete this one') .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 1")

    # Gone from the list...
    assert texts(page) == ["keep this one"]

    # ...but still in the database, flagged. Invariant 3: deletes must survive
    # as tombstones or they cannot propagate over sync.
    rows = records(page)
    assert len(rows) == 2, "the record was removed instead of tombstoned"
    dead = [r for r in rows if r["deleted"]]
    assert len(dead) == 1
    tomb = dead[0]
    assert tomb["raw"] == "delete this one", "raw must survive a delete"
    assert tomb["deletedAt"], "tombstone needs a deletedAt"
    assert tomb["updatedAt"] == tomb["deletedAt"]

    extra = set(tomb) - V2_KEYS - OPTIONAL_KEYS
    assert not extra, f"unexpected keys on a tombstone: {sorted(extra)}"


@test
def test_search_filters_and_highlights(page, base_url):
    boot(page, base_url)
    capture(page, "bo bun at le petit cambodge")
    capture(page, "dune, finally finished it")
    capture(page, "marie mentioned a podcast about bees")

    page.fill("#search", "bo bun")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 1")
    assert texts(page) == ["bo bun at le petit cambodge"]
    assert page.locator(".entry mark").count() >= 1

    # All terms must match, not any.
    page.fill("#search", "dune bees")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")
    assert "Nothing matches" in page.inner_text("#list")

    page.click("#clearSearch")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 3")


@test
def test_search_does_not_find_tombstones(page, base_url):
    boot(page, base_url)
    capture(page, "a secret worth forgetting")

    page.once("dialog", lambda d: d.accept())
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")

    page.fill("#search", "secret")
    page.wait_for_timeout(100)
    assert page.locator(".entry").count() == 0


@test
def test_entries_survive_a_reload(page, base_url):
    boot(page, base_url)
    capture(page, "this must outlive the tab")
    capture(page, "and so must this")

    page.reload()
    boot(page, base_url)

    assert sorted(texts(page)) == sorted(
        ["this must outlive the tab", "and so must this"]
    )
    assert len(records(page)) == 2


@test
def test_export_payload_shape(page, base_url):
    boot(page, base_url)
    capture(page, "something worth backing up")

    payload, _, filename = export_backup(page)

    assert payload["app"] == "memvault"
    assert payload["schemaVersion"] == 2
    assert payload["exportedAt"]
    assert payload["count"] == 1
    assert isinstance(payload["memories"], list)
    assert len(payload["memories"]) == 1
    assert filename.startswith("log-backup-"), filename
    assert filename.endswith(".json"), filename

    # Export is the entire safety net until sync exists: every record must go
    # out whole, with exactly the schema keys and nothing bolted on.
    rec = payload["memories"][0]
    extra = set(rec) - V2_KEYS - OPTIONAL_KEYS
    missing = V2_KEYS - set(rec)
    assert not extra, f"export leaked non-schema keys: {sorted(extra)}"
    assert not missing, f"export dropped schema keys: {sorted(missing)}"
    assert rec["raw"] == "something worth backing up"


@test
def test_export_includes_tombstones(page, base_url):
    boot(page, base_url)
    capture(page, "alive")
    capture(page, "doomed")

    page.once("dialog", lambda d: d.accept())
    page.click(".entry:has-text('doomed') .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 1")

    payload, _, _ = export_backup(page)

    raws = {r["raw"]: r for r in payload["memories"]}
    assert set(raws) == {"alive", "doomed"}
    assert raws["doomed"]["deleted"] is True
    assert raws["alive"]["deleted"] is False


@test
def test_export_import_round_trip(page, base_url):
    boot(page, base_url)
    capture(page, "first entry")
    capture(page, "second entry")
    capture(page, "third entry")

    payload, path, _ = export_backup(page)
    original = {r["id"]: r for r in payload["memories"]}

    # Wipe everything, the way losing the phone would.
    open_sheet(page)
    page.once("dialog", lambda d: d.accept())
    page.click("#wipeBtn")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")
    assert records(page) == []

    # Import the backup back in.
    page.set_input_files("#fileInput", path)
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 3")

    restored = {r["id"]: r for r in records(page)}
    assert set(restored) == set(original), "ids did not survive the round trip"
    for rid, before in original.items():
        assert restored[rid] == before, f"record {rid} changed in the round trip"

    # And it is durable, not just on screen.
    page.reload()
    boot(page, base_url)
    assert len(page.locator(".entry").all()) == 3


@test
def test_import_merges_and_keeps_the_newer_copy(page, base_url):
    boot(page, base_url)
    capture(page, "shared entry")
    payload, path, _ = export_backup(page)
    shared_id = payload["memories"][0]["id"]

    # Edit locally so the on-device copy is strictly newer than the backup.
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "shared entry, edited locally")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    capture(page, "local only entry")

    # Re-importing an older backup must not undo newer local edits, and must
    # not drop entries the backup never knew about.
    page.set_input_files("#fileInput", path)
    page.wait_for_timeout(300)

    rows = {r["id"]: r for r in records(page)}
    assert len(rows) == 2
    assert rows[shared_id]["raw"] == "shared entry, edited locally", \
        "an older backup overwrote a newer local edit"
    assert any(r["raw"] == "local only entry" for r in rows.values()), \
        "import dropped an entry that was not in the backup"


@test
def test_import_of_a_newer_backup_wins(page, base_url):
    """The other direction: a backup newer than the local copy must apply."""
    boot(page, base_url)
    capture(page, "original text")

    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "newer text")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    payload, path, _ = export_backup(page)

    # Roll the local copy back to something older than the backup.
    page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onsuccess = () => {
                const db = req.result;
                const store = db.transaction('memories', 'readwrite')
                                .objectStore('memories');
                const all = store.getAll();
                all.onsuccess = () => {
                    const rec = all.result[0];
                    rec.raw = 'stale text';
                    rec.updatedAt = '2000-01-01T00:00:00.000Z';
                    const w = store.put(rec);
                    w.onsuccess = () => resolve();
                    w.onerror = () => reject(w.error);
                };
            };
            req.onerror = () => reject(req.error);
        })
    """)
    page.reload()
    boot(page, base_url)
    assert texts(page) == ["stale text"]

    page.set_input_files("#fileInput", path)
    page.wait_for_function(
        "() => document.querySelector('.entry .raw')"
        "      && document.querySelector('.entry .raw').innerText === 'newer text'"
    )
    assert records(page)[0]["raw"] == "newer text"


@test
def test_import_rejects_junk_without_losing_data(page, base_url, tmp_files):
    boot(page, base_url)
    capture(page, "precious")

    junk = tmp_files / "not-a-backup.json"
    junk.write_text("this is not json at all", encoding="utf-8")
    page.set_input_files("#fileInput", str(junk))
    page.wait_for_selector("#toast.show")
    assert "valid backup" in page.inner_text("#toast")

    wrong = tmp_files / "wrong-shape.json"
    wrong.write_text(json.dumps({"app": "something-else"}), encoding="utf-8")
    page.set_input_files("#fileInput", str(wrong))
    page.wait_for_timeout(200)

    # The entry is still there either way.
    assert texts(page) == ["precious"]
    assert len(records(page)) == 1


@test
def test_sync_stores_exist_and_records_stay_clean(page, base_url):
    """Sync bookkeeping gets its own stores, beside the records not inside them."""
    boot(page, base_url)
    capture(page, "a record that must not grow sync fields")

    names = page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onsuccess = () => resolve(Array.from(req.result.objectStoreNames));
            req.onerror = () => reject(req.error);
        })
    """)
    assert set(names) == {"memories", "syncmeta", "syncstate"}, names

    # The record itself is untouched by the new stores existing.
    rec = records(page)[0]
    assert set(rec) - V2_KEYS - OPTIONAL_KEYS == set()


@test
def test_upgrade_from_v1_preserves_entries(page, base_url):
    """A v0 device upgrading to the sync build must not lose a single entry.

    This is the one migration where a mistake is unrecoverable: until sync
    works the phone is the only copy, so the upgrade is exercised directly
    rather than trusted.
    """
    # Set up the old database from a same-origin page that is not the app, so
    # no app connection is open to block the write. A 404 serves fine.
    page.goto(base_url + "__origin__")

    seeded = page.evaluate("""
        () => new Promise((resolve, reject) => {
            // Exactly the v0 shape: version 1, memories store only.
            const req = indexedDB.open('memvault', 1);
            req.onupgradeneeded = () => {
                const s = req.result.createObjectStore('memories', { keyPath: 'id' });
                s.createIndex('capturedAt', 'capturedAt');
            };
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const db = req.result;
                const now = '2026-08-19T10:00:00.000Z';
                const rec = {
                    id: 'mem_LEGACYV1RECORD00000000000', schemaVersion: 2,
                    raw: 'written before sync existed', capturedAt: now,
                    captureSource: 'text',
                    enrichment: { status: 'pending', model: null, at: null, confidence: null },
                    type: null, title: null, occurredAt: null,
                    tags: [], rating: null, details: {}, links: [],
                    userEdited: [], media: [],
                    createdAt: now, updatedAt: now, deleted: false
                };
                const w = db.transaction('memories', 'readwrite')
                            .objectStore('memories').put(rec);
                w.onsuccess = () => { db.close(); resolve(rec.id); };
                w.onerror = () => reject(w.error);
            };
        })
    """)
    assert seeded == "mem_LEGACYV1RECORD00000000000"

    # Now load the app, which opens at version 2 and triggers the upgrade.
    boot(page, base_url)

    assert texts(page) == ["written before sync existed"]

    rows = records(page)
    assert len(rows) == 1, "the upgrade lost the entry"
    assert rows[0]["id"] == seeded
    assert rows[0]["raw"] == "written before sync existed"
    assert rows[0]["capturedAt"] == "2026-08-19T10:00:00.000Z"

    version, names = page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onsuccess = () => resolve([
                req.result.version, Array.from(req.result.objectStoreNames)
            ]);
            req.onerror = () => reject(req.error);
        })
    """)
    assert version == 2, version
    assert set(names) == {"memories", "syncmeta", "syncstate"}, names

    # And the upgraded record still exports whole.
    payload, _, _ = export_backup(page)
    assert payload["memories"][0]["raw"] == "written before sync existed"
    assert set(payload["memories"][0]) - V2_KEYS - OPTIONAL_KEYS == set()


@test
def test_wipe_clears_sync_bookkeeping(page, base_url):
    """Wiping must reset the delta cursor, or Dropbox's copy never comes back.

    Clearing records while keeping a cursor would make the next pull a no-op:
    the remote files still exist but the delta reports no changes, so the data
    would look permanently gone.
    """
    boot(page, base_url)
    capture(page, "about to be wiped")

    # Plant sync state the way a real sync would have.
    page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const db = req.result;
                const t = db.transaction(['syncmeta', 'syncstate'], 'readwrite');
                t.objectStore('syncmeta').put({
                    id: 'mem_SOMETHING', path: '/memories/2026/mem_SOMETHING.json',
                    rev: '0123456789abcdef', syncedUpdatedAt: '2026-08-19T10:00:00.000Z'
                });
                t.objectStore('syncstate').put({ key: 'cursor', value: 'AAEjhg...' });
                t.objectStore('syncstate').put({ key: 'auth', value: { refresh: 'keep-me' } });
                t.oncomplete = () => resolve();
                t.onerror = () => reject(t.error);
            };
        })
    """)

    open_sheet(page)
    page.once("dialog", lambda d: d.accept())
    page.click("#wipeBtn")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")

    left = page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const db = req.result;
                const t = db.transaction(['memories', 'syncmeta', 'syncstate'], 'readonly');
                const out = {};
                const m = t.objectStore('memories').getAll();
                const s = t.objectStore('syncmeta').getAll();
                const c = t.objectStore('syncstate').get('cursor');
                const a = t.objectStore('syncstate').get('auth');
                t.oncomplete = () => resolve({
                    memories: m.result.length, syncmeta: s.result.length,
                    cursor: c.result || null, auth: a.result || null
                });
                t.onerror = () => reject(t.error);
            };
        })
    """)
    assert left["memories"] == 0
    assert left["syncmeta"] == 0, "stale revs survived the wipe"
    assert left["cursor"] is None, "the delta cursor survived the wipe"
    assert left["auth"], "the wipe should not disconnect Dropbox"


# ---------- dropbox oauth ----------
#
# The Dropbox endpoints are intercepted, so these run offline and never touch
# a real account. The consent screen is faked by redirecting straight back to
# the app with a code, which is exactly what Dropbox does after you approve.

APP_KEY = "ajrhuiu0r1aexyx"


def stub_dropbox(page, seen, *, token_status=200, token_body=None):
    """Intercept the authorize redirect and the token endpoint."""

    def on_authorize(route):
        q = dict(parse_qsl(urlparse(route.request.url).query))
        seen.append(("authorize", q))
        back = f"{q.get('redirect_uri', '')}?code=test-auth-code"
        if "state" in q:
            back += "&state=" + q["state"]
        route.fulfill(status=302, headers={"Location": back})

    def on_token(route):
        body = dict(parse_qsl(route.request.post_data or ""))
        seen.append(("token", body))
        if token_status != 200:
            route.fulfill(status=token_status, body='{"error":"invalid_grant"}')
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(token_body or {
                "access_token": "sl.short-lived-token",
                "refresh_token": "refresh-token-abc",
                "expires_in": 14400,
                "token_type": "bearer",
                "account_id": "dbid:TESTACCOUNT",
                "scope": "files.content.read files.content.write files.metadata.read",
            }),
        )

    page.route("https://www.dropbox.com/oauth2/authorize*", on_authorize)
    page.route("https://api.dropboxapi.com/oauth2/token", on_token)


def connect_dropbox(page, timeout=15000):
    """Run the connect flow to completion.

    Returns with the app freshly loaded and the settings sheet closed: the
    Dropbox redirect is a real navigation, so coming back is a page load and
    the sheet does not survive it. Callers that need settings reopen it.
    """
    open_sheet(page)
    page.click("#connectBtn")
    page.wait_for_function(
        "() => document.querySelector('#disconnectBtn')"
        "      && !document.querySelector('#disconnectBtn').hidden",
        timeout=timeout,
    )
    assert not page.locator("#sheet").evaluate("el => el.classList.contains('open')"), \
        "the sheet is expected to be closed after the redirect"


def stored_auth(page):
    return page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const r = req.result.transaction('syncstate', 'readonly')
                          .objectStore('syncstate').get('auth');
                r.onsuccess = () => resolve(r.result ? r.result.value : null);
                r.onerror = () => reject(r.error);
            };
        })
    """)


@test
def test_oauth_pkce_round_trip(page, base_url):
    seen = []
    stub_dropbox(page, seen)

    boot(page, base_url)
    open_sheet(page)
    assert "Not connected" in page.inner_text("#syncNote")

    page.click("#connectBtn")
    # The redirect leaves and comes back to the app, which then exchanges.
    page.wait_for_function(
        "() => document.querySelector('#disconnectBtn')"
        "      && !document.querySelector('#disconnectBtn').hidden",
        timeout=15000,
    )

    kinds = [k for k, _ in seen]
    assert kinds == ["authorize", "token"], kinds
    authorize = seen[0][1]
    token = seen[1][1]

    # PKCE, public client: a challenge goes up front, no secret ever.
    assert authorize["client_id"] == APP_KEY
    assert authorize["response_type"] == "code"
    assert authorize["code_challenge_method"] == "S256"
    assert authorize["token_access_type"] == "offline", \
        "without offline we get no refresh token and reauthorise every 4h"
    assert authorize["state"]
    assert authorize["redirect_uri"] == base_url
    assert "client_secret" not in authorize

    # The challenge really is S256 of the verifier that was later sent.
    verifier = token["code_verifier"]
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert authorize["code_challenge"] == expected, "code_challenge is not S256(verifier)"
    assert 43 <= len(verifier) <= 128, f"verifier length {len(verifier)} out of spec"

    assert token["grant_type"] == "authorization_code"
    assert token["code"] == "test-auth-code"
    assert token["client_id"] == APP_KEY
    assert token["redirect_uri"] == base_url
    assert "client_secret" not in token

    # Tokens are persisted where sync will look for them.
    saved = stored_auth(page)
    assert saved["refreshToken"] == "refresh-token-abc"
    assert saved["accessToken"] == "sl.short-lived-token"
    assert saved["accountId"] == "dbid:TESTACCOUNT"
    assert saved["expiresAt"] > 0

    # The authorization code is scrubbed from the URL so a reload cannot
    # replay it and it never lingers in history.
    assert "code=" not in page.url
    assert page.url.rstrip("/") == base_url.rstrip("/")

    assert "Connected to Dropbox" in page.inner_text("#syncNote")


@test
def test_connection_survives_a_reload(page, base_url):
    seen = []
    stub_dropbox(page, seen)
    boot(page, base_url)
    connect_dropbox(page)

    page.reload()
    boot(page, base_url)
    open_sheet(page)
    page.wait_for_function(
        "() => !document.querySelector('#disconnectBtn').hidden", timeout=10000
    )
    assert stored_auth(page)["refreshToken"] == "refresh-token-abc"
    # No second trip to Dropbox just to know we are connected.
    assert [k for k, _ in seen] == ["authorize", "token"]


@test
def test_oauth_rejects_a_mismatched_state(page, base_url):
    """A code arriving with the wrong state is not ours — refuse to exchange it."""
    seen = []
    stub_dropbox(page, seen)
    boot(page, base_url)
    open_sheet(page)

    # Start a real connect so a verifier is pending, then hand the app a code
    # carrying a state we never issued.
    page.evaluate("""
        () => localStorage.setItem('dbxPending', JSON.stringify(
            { verifier: 'a'.repeat(64), state: 'the-real-state', manual: false }))
    """)
    page.goto(base_url + "?code=attacker-code&state=some-other-state")
    page.wait_for_selector("#toast.show")

    assert "try again" in page.inner_text("#toast")
    assert stored_auth(page) is None, "exchanged a code with a mismatched state"
    assert not any(k == "token" for k, _ in seen), "token endpoint was called anyway"
    # The pending verifier is burned either way, so it cannot be reused.
    assert page.evaluate("() => localStorage.getItem('dbxPending')") is None


@test
def test_oauth_handles_a_declined_consent(page, base_url):
    boot(page, base_url)
    page.goto(base_url + "?error=access_denied&error_description=denied")
    page.wait_for_selector("#toast.show")

    assert "cancelled" in page.inner_text("#toast")
    assert stored_auth(page) is None
    assert "code=" not in page.url and "error=" not in page.url

    open_sheet(page)
    assert "Not connected" in page.inner_text("#syncNote")
    assert page.locator("#connectBtn").is_visible()


@test
def test_disconnect_forgets_the_tokens(page, base_url):
    seen = []
    stub_dropbox(page, seen)
    page.route(
        "https://api.dropboxapi.com/2/auth/token/revoke",
        lambda route: (seen.append(("revoke", {})), route.fulfill(status=200, body="{}")),
    )

    boot(page, base_url)
    capture(page, "an entry that must survive disconnecting")
    connect_dropbox(page)

    open_sheet(page)
    page.once("dialog", lambda d: d.accept())
    page.click("#disconnectBtn")
    page.wait_for_function("() => !document.querySelector('#connectBtn').hidden")

    assert stored_auth(page) is None
    assert any(k == "revoke" for k, _ in seen), "the token was not revoked upstream"
    assert "Not connected" in page.inner_text("#syncNote")

    # Disconnecting is not a delete.
    close_sheet(page)
    assert texts(page) == ["an entry that must survive disconnecting"]
    assert len(records(page)) == 1


@test
def test_a_refused_token_exchange_leaves_the_app_usable(page, base_url):
    seen = []
    stub_dropbox(page, seen, token_status=400)

    boot(page, base_url)
    capture(page, "still here after a failed connect")
    open_sheet(page)
    page.click("#connectBtn")
    page.wait_for_selector("#toast.show", timeout=15000)

    assert "Could not connect" in page.inner_text("#toast")
    assert stored_auth(page) is None
    assert "Not connected" in page.inner_text("#syncNote")
    assert page.locator("#connectBtn").is_hidden() is False

    # The failure is confined to the sync section: entries and export are fine.
    assert texts(page) == ["still here after a failed connect"]
    payload, _, _ = export_backup(page)
    assert payload["memories"][0]["raw"] == "still here after a failed connect"


@test
def test_connecting_does_not_change_the_export(page, base_url):
    """Auth state must never leak into the backup file."""
    seen = []
    stub_dropbox(page, seen)

    boot(page, base_url)
    capture(page, "one")
    capture(page, "two")

    before, _, _ = export_backup(page)

    connect_dropbox(page)

    after, _, _ = export_backup(page)

    assert after["memories"] == before["memories"], \
        "connecting Dropbox changed the exported records"
    assert set(after) == set(before), "connecting Dropbox changed the export envelope"
    blob = json.dumps(after)
    for secret in ["refresh-token-abc", "sl.short-lived-token", APP_KEY, "dbid:"]:
        assert secret not in blob, f"{secret!r} leaked into the export"


@test
def test_capture_works_while_disconnected_and_offline(page, base_url):
    """Invariant 4: capture never waits on the network."""
    # Every Dropbox call fails, as it would on a plane.
    page.route("https://www.dropbox.com/**", lambda r: r.abort())
    page.route("https://api.dropboxapi.com/**", lambda r: r.abort())

    boot(page, base_url)
    capture(page, "written with no network at all")
    assert texts(page) == ["written with no network at all"]
    assert len(records(page)) == 1


# ---------- push ----------

def remote_record(rid, raw, updated, captured=None, deleted=False):
    """A record as another device would have written it."""
    ts = captured or updated
    rec = {
        "id": rid, "schemaVersion": 2, "raw": raw,
        "capturedAt": ts, "captureSource": "text",
        "enrichment": {"status": "pending", "model": None,
                       "at": None, "confidence": None},
        "type": None, "title": None, "occurredAt": None,
        "tags": [], "rating": None, "details": {}, "links": [],
        "userEdited": [], "media": [],
        "createdAt": ts, "updatedAt": updated, "deleted": deleted,
    }
    if deleted:
        rec["deletedAt"] = updated
    return rec


class FakeDropbox:
    """A stand-in for the app folder, with enough delta support to test cursors.

    Every mutation bumps a version counter and appends to a journal, so
    list_folder/continue can answer "what changed since this cursor".
    """

    def __init__(self):
        self.files = {}        # path -> (rev, content)
        self.uploads = []      # every upload arg, in order
        self.downloads = []    # every downloaded path, in order
        self.lists = []        # "fresh" / "continue", in order
        self.fail_next = None  # (count, status, body) applied to uploads
        self.reset_cursor_once = False
        self._rev = 0
        self._version = 0
        self._journal = []     # (version, path, ".tag")
        self._folders = set()  # folders persist once created, as in Dropbox

    # -- test-side helpers, standing in for another device --

    def seed(self, rec):
        path = f"/memories/{rec['capturedAt'][:4]}/{rec['id']}.json"
        self._write(path, json.dumps(rec, indent=2))
        return path

    def remove(self, path):
        self.files.pop(path, None)
        self._version += 1
        self._journal.append((self._version, path, "deleted"))

    def _write(self, path, content):
        self._folders.add(path.rsplit("/", 1)[0].lower())
        self._rev += 1
        rev = f"rev{self._rev:012d}"
        self.files[path] = (rev, content)
        self._version += 1
        self._journal.append((self._version, path, "file"))
        return rev

    def install(self, page):
        page.route("https://content.dropboxapi.com/2/files/upload", self._upload)
        page.route("https://content.dropboxapi.com/2/files/download", self._download)
        page.route("https://api.dropboxapi.com/2/files/list_folder", self._list)
        page.route(
            "https://api.dropboxapi.com/2/files/list_folder/continue",
            self._continue,
        )

    # -- endpoints --

    def _entry(self, path, tag):
        name = path.rsplit("/", 1)[-1]
        if tag == "deleted":
            return {".tag": "deleted", "name": name,
                    "path_lower": path.lower(), "path_display": path}
        rev, content = self.files[path]
        return {
            ".tag": "file", "name": name, "path_lower": path.lower(),
            "path_display": path, "id": "id:" + path, "rev": rev,
            "size": len(content), "server_modified": "2026-08-22T10:00:00Z",
            "content_hash": "x" * 64,
        }

    def _list(self, route):
        self.lists.append("fresh")
        body = json.loads(route.request.post_data or "{}")
        prefix = body.get("path", "").lower()
        under = [p for p in self.files if p.lower().startswith(prefix + "/")]
        known = any(f.startswith(prefix) for f in self._folders)
        if not under and not known:
            # A folder nothing has ever been written to does not exist. Once it
            # has, it persists even when emptied.
            route.fulfill(
                status=409,
                body='{"error_summary":"path/not_found/.",'
                     '"error":{".tag":"path","path":{".tag":"not_found"}}}',
            )
            return
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({
                "entries": [self._entry(p, "file") for p in sorted(under)],
                "cursor": str(self._version), "has_more": False,
            }),
        )

    def _continue(self, route):
        self.lists.append("continue")
        if self.reset_cursor_once:
            self.reset_cursor_once = False
            route.fulfill(
                status=409,
                body='{"error_summary":"reset/.","error":{".tag":"reset"}}',
            )
            return
        since = int(json.loads(route.request.post_data or "{}")["cursor"])
        latest = {}
        for version, path, tag in self._journal:
            if version > since:
                latest[path] = tag
        entries = []
        for path, tag in latest.items():
            if tag == "file" and path not in self.files:
                tag = "deleted"
            entries.append(self._entry(path, tag))
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({
                "entries": entries, "cursor": str(self._version),
                "has_more": False,
            }),
        )

    def _download(self, route):
        arg = json.loads(route.request.headers["dropbox-api-arg"])
        path = arg["path"]
        self.downloads.append(path)
        match = next((p for p in self.files if p.lower() == path.lower()), None)
        if match is None:
            route.fulfill(status=409, body='{"error_summary":"path/not_found/."}')
            return
        rev, content = self.files[match]
        route.fulfill(
            status=200, body=content,
            headers={
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Result": json.dumps(self._entry(match, "file")),
            },
        )

    def _upload(self, route):
        arg = json.loads(route.request.headers["dropbox-api-arg"])
        body = route.request.post_data or ""
        self.uploads.append(arg)

        if self.fail_next and self.fail_next[0] > 0:
            n, status, err = self.fail_next
            self.fail_next = (n - 1, status, err)
            route.fulfill(
                status=status, body=err,
                headers={"Retry-After": "0"} if status == 429 else {},
            )
            return

        path, mode = arg["path"], arg["mode"]
        existing = self.files.get(path)
        if isinstance(mode, dict) and mode.get(".tag") == "update":
            if not existing or existing[0] != mode["update"]:
                route.fulfill(status=409, body='{"error_summary":"path/conflict/file/."}')
                return
        elif mode == "add" and existing:
            route.fulfill(status=409, body='{"error_summary":"path/conflict/file/."}')
            return

        rev = self._write(path, body)
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({
                "name": path.rsplit("/", 1)[-1], "path_lower": path.lower(),
                "path_display": path, "id": "id:" + path, "rev": rev,
                "size": len(body), "content_hash": "x" * 64,
                "server_modified": "2026-08-22T10:00:00Z",
            }),
        )

    def reset_counters(self):
        """Forget call history, so a test can count only what follows."""
        self.uploads.clear()
        self.downloads.clear()
        self.lists.clear()

    def json_at(self, path):
        match = next(p for p in self.files if p.lower() == path.lower())
        return json.loads(self.files[match][1])

    def records(self):
        """Every record currently in the fake app folder, by id."""
        out = {}
        for path, (_rev, content) in self.files.items():
            rec = json.loads(content)
            out[rec["id"]] = rec
        return out


def sync_meta(page):
    return page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const r = req.result.transaction('syncmeta', 'readonly')
                          .objectStore('syncmeta').getAll();
                r.onsuccess = () => resolve(r.result || []);
                r.onerror = () => reject(r.error);
            };
        })
    """)


def do_push(page, expect_toast=True):
    """Click Upload now from an open sheet and wait for it to settle."""
    # Clear any toast still on screen from an earlier action, so waiting for
    # one below cannot match the previous message.
    page.evaluate("() => document.querySelector('#toast').classList.remove('show')")
    page.click("#syncBtn")
    if expect_toast:
        page.wait_for_selector("#toast.show", timeout=15000)
    page.wait_for_function(
        "() => !document.querySelector('#syncBtn').disabled", timeout=15000
    )


def quiesce(page, ms=4000):
    """Wait out the sync debounce and any sync already running.

    Background syncs make exact call counts meaningless unless the test waits
    for things to go quiet first.
    """
    page.wait_for_timeout(ms)
    page.wait_for_function(
        "() => { const b = document.querySelector('#syncBtn');"
        "        return !b || !b.disabled; }",
        timeout=20000,
    )


def wait_pending(page, n):
    """Wait for the pending-upload count to settle on n.

    The sheet refreshes this asynchronously, so reading it straight after
    opening the sheet is a race.
    """
    page.wait_for_function(
        "n => document.querySelector('#sPending').textContent === String(n)",
        arg=n, timeout=10000,
    )


@test
def test_push_writes_one_json_file_per_record(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "bo bun at le petit cambodge")
    capture(page, "dune, finally")
    connect_dropbox(page)

    # Never exported, so the first push offers a backup. Decline it here; the
    # gate itself is tested separately.
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)

    assert len(dbx.files) == 2, dbx.files
    year = "2026"
    for path in dbx.files:
        assert path.startswith(f"/memories/{year}/"), path
        assert path.endswith(".json"), path

    # The uploaded bytes are exactly the record, same shape as the export.
    uploaded = [dbx.json_at(p) for p in dbx.files]
    raws = sorted(r["raw"] for r in uploaded)
    assert raws == ["bo bun at le petit cambodge", "dune, finally"]
    for rec in uploaded:
        extra = set(rec) - V2_KEYS - OPTIONAL_KEYS
        assert not extra, f"sync fields leaked into the uploaded file: {sorted(extra)}"
        assert set(rec) >= V2_KEYS

    # The path is built from the record id, so the file is findable by hand.
    for rec in uploaded:
        assert f"/memories/{year}/{rec['id']}.json" in dbx.files

    # First upload of a record uses add, not update.
    assert all(u["mode"] == "add" for u in dbx.uploads), dbx.uploads
    assert all(u["autorename"] is False for u in dbx.uploads)

    metas = sync_meta(page)
    assert len(metas) == 2
    for m in metas:
        assert m["rev"].startswith("rev")
        assert m["syncedUpdatedAt"]
        assert m["path"].startswith("/memories/")


@test
def test_push_is_incremental_and_uses_the_stored_rev(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "first")
    capture(page, "second")
    connect_dropbox(page)

    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    assert len(dbx.uploads) == 2

    # Nothing changed: a second push must upload nothing at all.
    do_push(page)
    assert len(dbx.uploads) == 2, "unchanged records were re-uploaded"
    assert "up to date" in page.inner_text("#toast").lower()

    # Edit one, and only that one goes up — with update(rev), not add.
    close_sheet(page)
    page.click(".entry:has-text('second') .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "second, revised")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    open_sheet(page)
    wait_pending(page, 1)
    do_push(page)

    assert len(dbx.uploads) == 3, dbx.uploads
    last = dbx.uploads[-1]
    assert isinstance(last["mode"], dict), "an edit must use update(rev), not add"
    assert last["mode"][".tag"] == "update"
    assert last["mode"]["update"] == "rev000000000002"

    changed = dbx.json_at(last["path"])
    assert changed["raw"] == "second, revised"
    wait_pending(page, 0)


@test
def test_push_path_is_stable_across_an_edit(page, base_url):
    """The path comes from capturedAt, which never moves.

    Deriving it from anything the user can edit would leave the old file
    orphaned in Dropbox on every edit. The edit has to cross a year boundary
    to catch it: an edit on the same day as capture looks identical either
    way, which is exactly how this regression would slip through.
    """
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "captured last year")

    # Backdate the record so the later edit lands in a different year.
    rec_id = page.evaluate("""
        () => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const store = req.result.transaction('memories', 'readwrite')
                                .objectStore('memories');
                const all = store.getAll();
                all.onsuccess = () => {
                    const rec = all.result[0];
                    const then = '2025-03-04T09:00:00.000Z';
                    rec.capturedAt = rec.createdAt = rec.updatedAt = then;
                    const w = store.put(rec);
                    w.onsuccess = () => resolve(rec.id);
                    w.onerror = () => reject(w.error);
                };
            };
        })
    """)
    page.reload()
    boot(page, base_url)

    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)

    first_path = dbx.uploads[0]["path"]
    assert first_path == f"/memories/2025/{rec_id}.json", first_path

    # Edit it today, which moves updatedAt into another year.
    close_sheet(page)
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "edited this year")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    open_sheet(page)
    do_push(page)

    assert dbx.uploads[-1]["path"] == first_path, \
        "the edit moved the file — the path is not derived from capturedAt"
    assert len(dbx.files) == 1, "the edit orphaned the original file"
    assert dbx.json_at(first_path)["raw"] == "edited this year"


@test
def test_push_uploads_tombstones(page, base_url):
    """A delete has to reach Dropbox as a file, not as a missing file."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "doomed")
    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    path = dbx.uploads[0]["path"]
    assert dbx.json_at(path)["deleted"] is False

    close_sheet(page)
    page.once("dialog", lambda d: d.accept())
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")

    open_sheet(page)
    do_push(page)

    assert len(dbx.files) == 1, "the tombstone should overwrite, not add a file"
    tomb = dbx.json_at(path)
    assert tomb["deleted"] is True
    assert tomb["raw"] == "doomed", "raw must survive into the tombstone"
    assert tomb["deletedAt"]


@test
def test_push_failure_leaves_the_record_dirty(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    # Fail more times than withRetry will attempt, so it gives up.
    dbx.fail_next = (9, 500, '{"error_summary":"internal_error/."}')

    boot(page, base_url)
    capture(page, "will not upload")
    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)

    assert "failed, will retry" in page.inner_text("#toast")
    assert sync_meta(page) == [], "a failed upload must not be recorded as synced"
    wait_pending(page, 1)  # the record must stay dirty

    # Nothing local was touched, and the safety net still works.
    close_sheet(page)
    assert texts(page) == ["will not upload"]
    payload, _, _ = export_backup(page)
    assert payload["memories"][0]["raw"] == "will not upload"

    # Once Dropbox recovers, the retry succeeds by itself.
    dbx.fail_next = None
    open_sheet(page)
    do_push(page)
    assert len(dbx.files) == 1
    wait_pending(page, 0)


@test
def test_push_retries_a_rate_limit(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.fail_next = (1, 429, '{"error_summary":"too_many_requests/."}')

    boot(page, base_url)
    capture(page, "rate limited once")
    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)

    assert len(dbx.uploads) == 2, "a 429 should be retried, not abandoned"
    assert len(dbx.files) == 1
    wait_pending(page, 0)


@test
def test_push_does_not_clobber_a_conflicting_remote_copy(page, base_url):
    """update(rev) must turn a moved remote copy into an error, not a clobber."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "mine")
    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    path = dbx.uploads[0]["path"]

    # Another device writes the same record, moving the rev.
    dbx.files[path] = ("rev999999999999", json.dumps({"raw": "theirs"}))

    close_sheet(page)
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "mine, edited")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    open_sheet(page)
    do_push(page)

    assert "failed, will retry" in page.inner_text("#toast")
    assert json.loads(dbx.files[path][1])["raw"] == "theirs", \
        "the remote copy was clobbered instead of the conflict being reported"
    wait_pending(page, 1)  # the conflict must stay pending


@test
def test_first_push_offers_a_backup(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "never backed up")
    connect_dropbox(page)
    open_sheet(page)

    prompts = []
    page.once("dialog", lambda d: (prompts.append(d.message), d.accept()))
    with page.expect_download() as dl:
        page.click("#syncBtn")
    page.wait_for_function(
        "() => !document.querySelector('#syncBtn').disabled", timeout=15000
    )

    assert prompts, "the first upload did not offer a backup"
    assert "only safety net" in prompts[0]
    backup = json.loads(Path(dl.value.path()).read_text(encoding="utf-8"))
    assert backup["memories"][0]["raw"] == "never backed up"
    assert len(dbx.files) == 1, "the upload should still happen after exporting"

    # Only ever offered once.
    close_sheet(page)
    capture(page, "a second entry")
    open_sheet(page)
    second = []
    page.on("dialog", lambda d: (second.append(d.message), d.dismiss()))
    do_push(page)
    assert second == [], "the backup gate fired a second time"
    assert len(dbx.files) == 2


@test
def test_push_needs_no_export_when_one_already_exists(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "already safe")
    export_backup(page)  # sets lastBackup

    connect_dropbox(page)
    open_sheet(page)
    prompts = []
    page.on("dialog", lambda d: (prompts.append(d.message), d.dismiss()))
    do_push(page)

    assert prompts == [], "prompted for a backup that already exists"
    assert len(dbx.files) == 1


@test
def test_push_leaves_the_export_untouched(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "one")
    capture(page, "two")
    before, _, _ = export_backup(page)

    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    after, _, _ = export_backup(page)
    assert after["memories"] == before["memories"], \
        "uploading changed the exported records"

    blob = json.dumps(after)
    for secret in ["rev0000", "refresh-token-abc", "sl.short-lived-token"]:
        assert secret not in blob, f"{secret!r} leaked into the export"


@test
def test_push_without_a_connection_does_nothing(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "not connected")
    open_sheet(page)

    # The button is not even offered while disconnected.
    assert page.locator("#syncBtn").is_hidden()
    assert page.locator("#syncStats").is_hidden()
    assert dbx.uploads == []


# ---------- pull and merge ----------

OLD = "2026-01-01T00:00:00.000Z"
NEW = "2026-08-20T12:00:00.000Z"


def local_record(page, rid):
    for r in records(page):
        if r["id"] == rid:
            return r
    return None


def set_local(page, rid, **fields):
    """Rewrite fields on a local record, standing in for an earlier edit."""
    return page.evaluate("""
        ([id, fields]) => new Promise((resolve, reject) => {
            const req = indexedDB.open('memvault');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => {
                const store = req.result.transaction('memories', 'readwrite')
                                .objectStore('memories');
                const g = store.get(id);
                g.onsuccess = () => {
                    const rec = Object.assign(g.result, fields);
                    const w = store.put(rec);
                    w.onsuccess = () => resolve(rec);
                    w.onerror = () => reject(w.error);
                };
            };
        })
    """, [rid, fields])


@test
def test_pull_brings_down_another_devices_entries(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_FROMLAPTOP0000000000000001", "written on the laptop", NEW))
    dbx.seed(remote_record("mem_FROMLAPTOP0000000000000002", "and this one too", NEW))

    boot(page, base_url)
    connect_dropbox(page)

    # No button pressed: connecting is enough, the sync on launch fetches them.
    page.wait_for_function(
        "() => document.querySelectorAll('.entry').length === 2", timeout=20000
    )
    assert "2 down" in page.inner_text("#toast"), \
        "arriving entries should be announced even on a background sync"
    assert sorted(texts(page)) == ["and this one too", "written on the laptop"]

    # They land as full records, not as fragments.
    rec = local_record(page, "mem_FROMLAPTOP0000000000000001")
    assert set(rec) - V2_KEYS - OPTIONAL_KEYS == set()
    assert V2_KEYS - set(rec) == set()

    # And they are already accounted for, so nothing bounces straight back up.
    assert dbx.uploads == []


@test
def test_first_sync_against_an_empty_remote_keeps_everything(page, base_url):
    """An empty app folder means nothing has been uploaded — never "all deleted".

    This is the specific path by which the only copy of the data could be
    lost, so it gets its own test.
    """
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "the only copy")
    capture(page, "also the only copy")
    connect_dropbox(page)

    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)

    close_sheet(page)
    assert sorted(texts(page)) == ["also the only copy", "the only copy"]
    assert len(records(page)) == 2
    assert len(dbx.files) == 2, "an empty remote should have been filled, not obeyed"


@test
def test_pull_never_deletes_a_local_record(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_ONLYONEREMOTE00000000000001", "the remote one", NEW))

    boot(page, base_url)
    capture(page, "local only, never uploaded")
    connect_dropbox(page)

    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    # The remote knew about one record; the local one must survive and go up.
    assert sorted(texts(page)) == ["local only, never uploaded", "the remote one"]
    assert len(records(page)) == 2
    assert len(dbx.files) == 2


@test
def test_remote_tombstone_propagates(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    rid = "mem_DELETEDELSEWHERE0000000001"
    dbx.seed(remote_record(rid, "deleted on the other device", NEW, deleted=True))

    boot(page, base_url)
    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    # Hidden from the list...
    assert texts(page) == []
    # ...but present as a tombstone, so it can propagate on from here.
    rec = local_record(page, rid)
    assert rec is not None, "the tombstone was dropped instead of stored"
    assert rec["deleted"] is True
    assert rec["raw"] == "deleted on the other device"


@test
def test_merge_takes_the_newer_side(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "mine, older")
    rid = records(page)[0]["id"]
    set_local(page, rid, updatedAt=OLD)
    page.reload()
    boot(page, base_url)

    # The remote copy of the same record is newer.
    dbx.seed(remote_record(rid, "theirs, newer", NEW,
                           captured=records(page)[0]["capturedAt"]))

    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    assert texts(page) == ["theirs, newer"]
    assert local_record(page, rid)["updatedAt"] == NEW
    # Both sides agree, so nothing needs uploading.
    assert dbx.records()[rid]["raw"] == "theirs, newer"


@test
def test_merge_keeps_the_newer_local_side_and_pushes_it(page, base_url):
    """The other direction, and the path by which a step-3 conflict heals."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "mine, newer")
    rec = records(page)[0]
    rid = rec["id"]

    dbx.seed(remote_record(rid, "theirs, older", OLD, captured=rec["capturedAt"]))

    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    # Local wins and is written back up, so the two sides converge.
    assert texts(page) == ["mine, newer"]
    assert dbx.records()[rid]["raw"] == "mine, newer", \
        "the newer local copy was not pushed back"
    open_sheet(page)
    wait_pending(page, 0)


@test
def test_a_delete_beats_an_edit_but_keeps_the_newer_text(page, base_url):
    """Delete wins for the flag only; the newest text is still kept.

    Straight tombstone-wins would honour the delete and silently discard the
    concurrent edit, losing content that neither side asked to lose.
    """
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "original text")
    rec = records(page)[0]
    rid = rec["id"]

    # Deleted here, at the older time.
    page.once("dialog", lambda d: d.accept())
    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 0")
    set_local(page, rid, updatedAt=OLD, deletedAt=OLD)
    page.reload()
    boot(page, base_url)

    # Edited on the other device, later, without knowing about the delete.
    dbx.seed(remote_record(rid, "edited elsewhere, later", NEW,
                           captured=rec["capturedAt"]))

    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    merged = local_record(page, rid)
    assert merged["deleted"] is True, "the delete was undone by a newer edit"
    assert merged["raw"] == "edited elsewhere, later", \
        "the concurrent edit was discarded"
    assert texts(page) == []

    # The merged tombstone goes back up, so the other device learns about it.
    assert dbx.records()[rid]["deleted"] is True
    assert dbx.records()[rid]["raw"] == "edited elsewhere, later"


@test
def test_a_file_deleted_in_dropbox_is_restored_not_obeyed(page, base_url):
    """Deleting a file by hand in Dropbox must heal, not destroy."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "do not lose me")
    connect_dropbox(page)
    page.once("dialog", lambda d: d.dismiss())
    open_sheet(page)
    do_push(page)
    path = dbx.uploads[0]["path"]
    assert len(dbx.files) == 1

    # Someone deletes the file directly in Dropbox.
    dbx.remove(path)
    assert dbx.files == {}

    do_push(page)
    close_sheet(page)

    assert texts(page) == ["do not lose me"], "the local record was deleted"
    assert len(records(page)) == 1
    assert len(dbx.files) == 1, "the file was not restored"
    assert dbx.json_at(path)["raw"] == "do not lose me"


@test
def test_a_deletion_arriving_as_a_delta_is_also_restored(page, base_url):
    """The same rule as above, but reached through list_folder/continue.

    A full listing reports a deletion by omission; a delta reports it as an
    explicit deleted entry. Both paths must refuse to delete local data, and
    they are different code.
    """
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    rid = "mem_DELTADELETION00000000001"
    path = dbx.seed(remote_record(rid, "arrived from the laptop", NEW))

    boot(page, base_url)
    connect_dropbox(page)
    quiesce(page)

    # The sync on launch did a full listing and stored a cursor, so anything
    # from here on is a delta.
    assert dbx.lists == ["fresh"], dbx.lists
    assert local_record(page, rid)["raw"] == "arrived from the laptop"
    dbx.reset_counters()

    # The file is deleted directly in Dropbox.
    dbx.remove(path)
    open_sheet(page)
    do_push(page)

    assert dbx.lists == ["continue"], dbx.lists
    close_sheet(page)

    assert texts(page) == ["arrived from the laptop"], "the local record was deleted"
    assert local_record(page, rid) is not None
    assert local_record(page, rid)["deleted"] is False, \
        "a missing file was treated as a tombstone"
    assert len(dbx.files) == 1, "the file was not restored"
    assert dbx.records()[rid]["raw"] == "arrived from the laptop"


@test
def test_sync_uses_the_cursor_for_later_runs(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_CURSORTEST000000000000001", "first remote", NEW))

    boot(page, base_url)
    connect_dropbox(page)
    quiesce(page)

    # The sync on launch listed the folder and fetched the one record.
    assert dbx.lists == ["fresh"], dbx.lists
    assert len(dbx.downloads) == 1
    dbx.reset_counters()

    # Nothing changed remotely: the delta is empty and nothing is downloaded.
    open_sheet(page)
    do_push(page)
    assert dbx.lists == ["continue"], dbx.lists
    assert dbx.downloads == [], "an unchanged record was downloaded again"

    # One new record appears remotely; only that one comes down.
    dbx.seed(remote_record("mem_CURSORTEST000000000000002", "second remote", NEW))
    do_push(page)
    assert len(dbx.downloads) == 1, dbx.downloads
    close_sheet(page)
    assert sorted(texts(page)) == ["first remote", "second remote"]


@test
def test_a_reset_cursor_falls_back_to_a_full_list(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_RESETTEST0000000000000001", "before the reset", NEW))

    boot(page, base_url)
    connect_dropbox(page)
    quiesce(page)
    dbx.reset_counters()

    # Dropbox forgets the cursor. Re-listing must recover rather than fail.
    dbx.reset_cursor_once = True
    dbx.seed(remote_record("mem_RESETTEST0000000000000002", "after the reset", NEW))
    open_sheet(page)
    do_push(page)

    assert dbx.lists == ["continue", "fresh"], dbx.lists
    close_sheet(page)
    assert sorted(texts(page)) == ["after the reset", "before the reset"]


@test
def test_an_unreadable_remote_file_is_skipped(page, base_url):
    """One corrupt file must not wedge sync for everything else."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_GOODFILE000000000000000001", "perfectly fine", NEW))
    dbx._write("/memories/2026/mem_BROKEN000000000000000001.json", "{not json at all")

    boot(page, base_url)
    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    assert texts(page) == ["perfectly fine"]
    assert len(records(page)) == 1


@test
def test_sync_ignores_files_outside_memories(page, base_url):
    """meta.json and reviews/ arrive in later phases and must not be parsed."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_REALRECORD00000000000001", "a real record", NEW))
    dbx._write("/meta.json", json.dumps({"types": ["book"]}))
    dbx._write("/reviews/2026-08.ndjson", '{"card":"x"}')

    boot(page, base_url)
    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    assert texts(page) == ["a real record"]
    assert len(records(page)) == 1
    for p in dbx.downloads:
        assert p.startswith("/memories/"), p


@test
def test_sync_leaves_the_export_intact(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    dbx.seed(remote_record("mem_FROMREMOTE00000000000001", "came from Dropbox", NEW))

    boot(page, base_url)
    capture(page, "made here")
    export_backup(page)

    connect_dropbox(page)
    open_sheet(page)
    do_push(page)
    close_sheet(page)

    payload, _, _ = export_backup(page)
    raws = sorted(r["raw"] for r in payload["memories"])
    assert raws == ["came from Dropbox", "made here"]

    for rec in payload["memories"]:
        extra = set(rec) - V2_KEYS - OPTIONAL_KEYS
        assert not extra, f"sync fields leaked into the export: {sorted(extra)}"
        assert V2_KEYS - set(rec) == set()

    blob = json.dumps(payload)
    for secret in ["rev0000", "refresh-token-abc", "sl.short-lived-token", "cursor"]:
        assert secret not in blob, f"{secret!r} leaked into the export"


# ---------- automatic sync ----------
#
# The debounce in the app is 2.5s, so these wait on the effect rather than
# guessing at timing.

def prime_sync(page, dbx, text="priming entry"):
    """Get past the first-upload gate, then reset call counts.

    A background sync deliberately never makes the first upload — that has to
    be a deliberate act — so any test of automatic uploading has to press
    Sync now once before automatic behaviour is available at all.
    """
    capture(page, text)
    open_sheet(page)
    do_push(page)
    close_sheet(page)
    quiesce(page)
    dbx.reset_counters()


def wait_for_upload(page, n, timeout=20000):
    """Wait until the fake has received n uploads, without polling the app."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if len(page._dbx.uploads) >= n:
            return True
        page.wait_for_timeout(200)
    return False


@test
def test_capture_syncs_by_itself(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    page._dbx = dbx

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    prime_sync(page, dbx)

    capture(page, "typed and forgotten about")

    assert wait_for_upload(page, 1), "capture never reached Dropbox on its own"
    assert len(dbx.files) == 2
    assert "typed and forgotten about" in [
        r["raw"] for r in dbx.records().values()
    ]


@test
def test_capture_does_not_wait_for_the_network(page, base_url):
    """Invariant 4: save is instant even when Dropbox is unreachable."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    # Every upload hangs for longer than the test will wait.
    page.route(
        "https://content.dropboxapi.com/2/files/upload",
        lambda route: page.wait_for_timeout(30000),
    )

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)

    start = time.time()
    capture(page, "saved while the network hangs")
    elapsed = time.time() - start

    assert elapsed < 5, f"save blocked for {elapsed:.1f}s"
    assert texts(page) == ["saved while the network hangs"]
    assert len(records(page)) == 1

    # And a second capture still works while the first upload is stuck.
    capture(page, "and another one")
    assert len(records(page)) == 2


@test
def test_rapid_captures_debounce_into_one_sync(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    page._dbx = dbx

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    prime_sync(page, dbx)

    capture(page, "one")
    capture(page, "two")
    capture(page, "three")

    assert wait_for_upload(page, 3), "not everything was uploaded"
    page.wait_for_timeout(4000)  # let any extra sync fire

    # Three new records, three uploads — one sync, not one per capture.
    assert len(dbx.uploads) == 3, \
        f"expected one sync uploading 3 records, got {len(dbx.uploads)} uploads"
    raws = sorted(r["raw"] for r in dbx.records().values())
    assert raws == ["one", "priming entry", "three", "two"], raws


@test
def test_edit_and_delete_sync_by_themselves(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    page._dbx = dbx

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    prime_sync(page, dbx)

    capture(page, "before")
    assert wait_for_upload(page, 1)
    path = dbx.uploads[0]["path"]

    page.click(".entry .raw")
    page.wait_for_selector(".edit-area")
    page.fill(".edit-area", "after")
    page.click(".act-save")
    page.wait_for_selector(".entry.editing", state="detached")

    assert wait_for_upload(page, 2), "an edit did not sync on its own"
    assert dbx.json_at(path)["raw"] == "after"

    page.once("dialog", lambda d: d.accept())
    page.click(f".entry:has-text('after') .raw")
    page.wait_for_selector(".edit-area")
    page.click(".act-delete")
    page.wait_for_function("() => document.querySelectorAll('.entry').length === 1")

    assert wait_for_upload(page, 3), "a delete did not sync on its own"
    assert dbx.json_at(path)["deleted"] is True


@test
def test_launch_pulls_changes_made_elsewhere(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    connect_dropbox(page)

    # Another device adds an entry while this one is closed.
    dbx.seed(remote_record("mem_WHILEYOUWEREAWAY000000001", "added on the laptop", NEW))

    page.reload()
    boot(page, base_url)

    # No button pressed: launching is enough.
    page.wait_for_function(
        "() => document.querySelectorAll('.entry').length === 1", timeout=20000
    )
    assert texts(page) == ["added on the laptop"]


@test
def test_nothing_syncs_while_disconnected(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    capture(page, "no dropbox here")
    page.wait_for_timeout(4000)

    assert dbx.uploads == [], "uploaded without a connection"
    assert dbx.lists == [], "listed without a connection"
    assert texts(page) == ["no dropbox here"]


@test
def test_a_background_sync_failure_stays_quiet_and_keeps_data(page, base_url):
    """A failed background sync must not nag, and must not lose anything."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    prime_sync(page, dbx)

    # Only now does a background sync actually attempt uploads.
    dbx.fail_next = (99, 500, '{"error_summary":"internal_error/."}')
    capture(page, "will not upload yet")
    page.wait_for_timeout(6000)

    # Silent: no error toast for something the user did not ask for.
    toast_shown = page.evaluate(
        "() => document.querySelector('#toast').classList.contains('show')"
    )
    assert not toast_shown, "a background failure raised a toast"

    # Data intact, and settings tells the truth about what is outstanding.
    assert "will not upload yet" in texts(page)
    open_sheet(page)
    wait_pending(page, 1)

    # Manual sync, by contrast, does report the failure.
    do_push(page)
    assert "failed" in page.inner_text("#toast")

    # And it recovers once Dropbox does.
    dbx.fail_next = None
    do_push(page)
    wait_pending(page, 0)
    assert len(dbx.files) == 2


@test
def test_manual_sync_still_reports_up_to_date(page, base_url):
    """The explicit button stays chatty even though background syncs are not."""
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)
    page._dbx = dbx

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    prime_sync(page, dbx)

    capture(page, "already synced")
    assert wait_for_upload(page, 1)
    quiesce(page)

    open_sheet(page)
    do_push(page)
    assert "up to date" in page.inner_text("#toast").lower()


@test
def test_wipe_warns_that_dropbox_will_restore(page, base_url):
    seen, dbx = [], FakeDropbox()
    stub_dropbox(page, seen)
    dbx.install(page)

    boot(page, base_url)
    export_backup(page)
    connect_dropbox(page)
    capture(page, "still in dropbox")

    open_sheet(page)
    messages = []
    page.once("dialog", lambda d: (messages.append(d.message), d.dismiss()))
    page.click("#wipeBtn")
    page.wait_for_timeout(500)

    assert messages, "no confirmation shown"
    assert "come back on the next sync" in messages[0], messages[0]
    # Dismissed, so nothing was deleted.
    assert len(records(page)) == 1


@test
def test_service_worker_registers(page, base_url):
    boot(page, base_url)

    ok = page.wait_for_function(
        "async () => !!(await navigator.serviceWorker.getRegistration())",
        timeout=10000,
    )
    assert ok

    scope = page.evaluate(
        "async () => (await navigator.serviceWorker.getRegistration()).scope"
    )
    assert scope.startswith(base_url)


@test
def test_shell_assets_are_precached(page, base_url):
    """Everything in the ASSETS list must actually land in the cache.

    A missing icon here is a home-screen icon that breaks offline.
    """
    boot(page, base_url)
    page.wait_for_function(
        "async () => !!(await navigator.serviceWorker.getRegistration())",
        timeout=10000,
    )

    cached = page.wait_for_function("""
        async () => {
            const names = await caches.keys();
            if (!names.length) return null;
            const c = await caches.open(names[0]);
            const keys = await c.keys();
            return keys.length ? keys.map(r => new URL(r.url).pathname) : null;
        }
    """, timeout=10000).json_value()

    for asset in ["/index.html", "/manifest.webmanifest", "/icon-192.png",
                  "/icon-512.png", "/icon-512-maskable.png"]:
        assert any(p.endswith(asset) for p in cached), \
            f"{asset} was not precached: {cached}"


@test
def test_settings_sheet_opens_and_closes(page, base_url):
    boot(page, base_url)
    capture(page, "one thing")

    open_sheet(page)
    assert page.locator("#scrim").is_visible()
    assert page.inner_text("#sEntries") == "1"

    page.click("#closeSheetBtn")
    page.wait_for_selector("#sheet.open", state="detached")


# ---------- enrichment ----------
#
# On-device extraction runs entirely client-side over WebGPU — there is no
# fetch() for a test to intercept the way stub_dropbox intercepts Dropbox.
# Instead, production exposes window.__LELOG_TEST_EXTRACTOR__ (read by
# getExtractor() in index.html) plus two narrow orchestration hooks,
# __LELOG_ENQUEUE_ENRICH__ and __LELOG_SEED_USER_EDITED__, used only below.
# No test here ever touches real WebGPU or downloads real model weights.

def stub_enrichment(page, fn_js):
    """Install a fake on-device extractor before the app boots.

    fn_js is a JS expression for a function of the shape (rec, ctx) => result
    or a promise of one. Must be called before boot()/page.goto(), since
    add_init_script only applies to future navigations.
    """
    page.add_init_script(f"window.__LELOG_TEST_EXTRACTOR__ = {fn_js};")


def wait_for_record(page, pred, timeout=5000):
    """Poll IndexedDB until some record matches pred(record).

    Enrichment runs in the background, off the render/click chain capture()
    already waits on, so — like wait_for_upload for sync — this polls an
    observable side effect instead of sleeping a fixed time.
    """
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        match = next((r for r in records(page) if pred(r)), None)
        if match:
            return match
        page.wait_for_timeout(100)
    return next((r for r in records(page) if pred(r)), None)


@test
def test_capture_does_not_wait_for_enrichment(page, base_url):
    """Invariant 4: save is instant even when on-device extraction hangs."""
    stub_enrichment(page, "() => new Promise(() => {})")

    boot(page, base_url)

    start = time.time()
    capture(page, "saved while enrichment hangs")
    elapsed = time.time() - start

    assert elapsed < 5, f"save blocked for {elapsed:.1f}s"
    assert texts(page) == ["saved while enrichment hangs"]


@test
def test_enrichment_applies_high_confidence_silently(page, base_url):
    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'book', title: 'Klara and the Sun', occurredAt: null,
            tags: ['fiction'], rating: 5, details: { author: 'Ishiguro' },
            confidence: 0.9
        })
    """)

    boot(page, base_url)
    capture(page, "finished klara and the sun")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["enrichment"]["status"] == "done"
    assert rec["type"] == "book"
    assert rec["title"] == "Klara and the Sun"
    assert rec["tags"] == ["fiction"]
    assert rec["rating"] == 5
    assert rec["details"] == {"author": "Ishiguro"}
    assert rec["enrichment"]["needsReview"] is False
    assert rec["enrichment"]["suggestion"] is None

    assert page.locator(".chip.title").inner_text() == "Klara and the Sun"


@test
def test_enrichment_flags_medium_confidence(page, base_url):
    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'restaurant', title: 'Le Petit Cambodge', occurredAt: null,
            tags: [], rating: null, details: {}, confidence: 0.5
        })
    """)

    boot(page, base_url)
    capture(page, "bo bun with marie")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["type"] == "restaurant"
    assert rec["enrichment"]["needsReview"] is True
    assert page.locator(".chip.review").count() == 1


@test
def test_enrichment_does_not_apply_low_confidence(page, base_url):
    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'idea', title: 'maybe something', occurredAt: null,
            tags: [], rating: null, details: {}, confidence: 0.2
        })
    """)

    boot(page, base_url)
    capture(page, "half formed thought")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["type"] is None
    assert rec["title"] is None
    assert rec["enrichment"]["suggestion"]["type"] == "idea"
    assert page.locator(".chips").count() == 0


@test
def test_enrichment_never_overwrites_user_edited_field(page, base_url):
    boot(page, base_url)
    capture(page, "a book i am reading")
    rec_id = records(page)[0]["id"]

    page.evaluate(
        "id => window.__LELOG_SEED_USER_EDITED__(id, 'title', 'My Own Title')",
        rec_id,
    )
    page.evaluate("""
        () => { window.__LELOG_TEST_EXTRACTOR__ = (rec, ctx) => Promise.resolve({
            type: 'book', title: 'Extracted Title', occurredAt: null,
            tags: ['fiction'], rating: 4, details: {}, confidence: 0.9
        }); }
    """)
    page.evaluate("id => window.__LELOG_ENQUEUE_ENRICH__(id)", rec_id)

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] == "done")
    assert rec["title"] == "My Own Title", "a hand-edited field was overwritten"
    assert rec["type"] == "book", "a non-edited field was not applied"
    assert rec["tags"] == ["fiction"]


@test
def test_malformed_extraction_marks_failed(page, base_url):
    stub_enrichment(page, "(rec, ctx) => Promise.resolve(null)")

    boot(page, base_url)
    capture(page, "this will not parse")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["enrichment"]["status"] == "failed"
    assert rec["type"] is None
    assert rec["raw"] == "this will not parse"


@test
def test_out_of_enum_type_degrades_to_null(page, base_url):
    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'spaceship', title: 'nope', occurredAt: null,
            tags: [], rating: null, details: {}, confidence: 0.9
        })
    """)

    boot(page, base_url)
    capture(page, "an odd guess")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["enrichment"]["status"] == "done", "an unrecognised type must not fail the record"
    assert rec["type"] is None
    assert rec["enrichment"]["suggestion"] is None


@test
def test_raw_is_never_modified_by_enrichment(page, base_url):
    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'note', title: null, occurredAt: null, tags: [], rating: null,
            details: {}, confidence: 0.9, raw: 'a rogue rewrite'
        })
    """)

    boot(page, base_url)
    capture(page, "the original words")

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["raw"] == "the original words"


@test
def test_reload_recovers_pending_queue(page, base_url):
    boot(page, base_url)
    capture(page, "captured before ai was on")
    assert records(page)[0]["enrichment"]["status"] == "pending"

    stub_enrichment(page, """
        (rec, ctx) => Promise.resolve({
            type: 'idea', title: null, occurredAt: null, tags: [], rating: null,
            details: {}, confidence: 0.9
        })
    """)
    boot(page, base_url)

    rec = wait_for_record(page, lambda r: r["enrichment"]["status"] != "pending")
    assert rec["type"] == "idea", "a pending record was not picked up after reload"


@test
def test_enrichment_shape_in_export(page, base_url):
    boot(page, base_url)
    capture(page, "not yet enriched")

    payload, _, _ = export_backup(page)
    enrichment = payload["memories"][0]["enrichment"]
    extra = set(enrichment) - ENRICHMENT_KEYS
    missing = ENRICHMENT_KEYS - set(enrichment)
    assert not extra, f"enrichment object carries unexpected keys: {sorted(extra)}"
    assert not missing, f"enrichment object is missing keys: {sorted(missing)}"


# ---------- runner ----------

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    selected = [t for t in TESTS if not only or only in t.__name__]
    if not selected:
        sys.exit(f"no test matches {only!r}")

    tmp_files = ROOT / "test" / ".tmp"
    tmp_files.mkdir(exist_ok=True)

    base_url, shutdown = start_server()
    passed, failed = [], []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for t in selected:
                    ctx = browser.new_context(accept_downloads=True)
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    name = t.__name__.replace("test_", "").replace("_", " ")
                    try:
                        kwargs = {}
                        if "tmp_files" in t.__code__.co_varnames:
                            kwargs["tmp_files"] = tmp_files
                        t(page, base_url, **kwargs)
                        if errors:
                            raise AssertionError(
                                "uncaught page error: " + "; ".join(errors)
                            )
                        print(f"  \033[32mpass\033[0m  {name}")
                        passed.append(name)
                    except Exception as e:
                        first = str(e).strip().split("\n")[0][:200]
                        print(f"  \033[31mFAIL\033[0m  {name}\n        {first}")
                        failed.append(name)
                    finally:
                        ctx.close()
            finally:
                browser.close()
    finally:
        shutdown()
        for f in tmp_files.glob("*"):
            f.unlink()
        tmp_files.rmdir()

    total = len(passed) + len(failed)
    print(f"\n{len(passed)}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
