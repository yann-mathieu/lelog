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

import functools
import http.server
import json
import socket
import socketserver
import sys
import threading
from pathlib import Path

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
        "status": "pending", "model": None, "at": None, "confidence": None
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

    for asset in ["/index.html", "/manifest.webmanifest",
                  "/icon-192.png", "/icon-512.png"]:
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
