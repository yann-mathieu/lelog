#!/usr/bin/env python3
"""Run Le Log's self-test in a browser that has a real GPU.

`test/smoke.py` deliberately never touches WebGPU or downloads real model
weights: it has to run offline, in seconds, in a cloud session. That leaves a
hole exactly where this app keeps breaking — the model itself. This script is
the other half. It serves the repo, opens it in the Chrome you already have
installed, clicks Settings -> Run self-test, and prints the report as it fills
in.

    python3 test/live.py                 # real Chrome, visible window
    python3 test/live.py --headless      # no window (WebGPU may be absent)
    python3 test/live.py --model qwen-1.5b --f32
    python3 test/live.py --url https://yann-mathieu.github.io/lelog/

The browser profile is kept between runs (see --profile) and the port is
fixed (see --port), so the model is downloaded once and every later run starts
from cache. Both matter: the Cache API is keyed by origin, and the port is
part of the origin. Delete the profile directory to test a cold download.

Read two lines of the report before anything else:

  webgpu   "absent" means this browser has no WebGPU and nothing below that
           line ran. Use real Chrome (the default) rather than --channel
           bundled.
  gpu      "swiftshader" means WebGPU fell back to software rendering. It
           works, but every timing in the report is meaningless and f16 will
           be unavailable. A real adapter names the actual hardware.
"""

import argparse
import functools
import http.server
import os
import socketserver
import sys
import threading
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("needs playwright: pip install playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILE = os.path.expanduser("~/.cache/lelog-live-profile")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass  # the report is the output; access logs bury it

    def end_headers(self):
        # Never let the browser reuse a previous run's copy. The origin is
        # stable now and the profile persists, so without this a run serves the
        # index.html it cached earlier: one reported a stale APP_VERSION and
        # tested a schema that was no longer on disk, which looks exactly like
        # a fix that did not work.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


DEFAULT_PORT = 8787


def serve(root, port=DEFAULT_PORT):
    """Serve the repo on a fixed port. IndexedDB needs a real origin — and the
    port is part of that origin, so an ephemeral one gave every run a fresh,
    empty Cache and re-downloaded the weights. That is what the profile being
    kept between runs was supposed to avoid, and it is how three runs in ten
    minutes walked into Hugging Face's rate limiter."""
    handler = functools.partial(Handler, directory=root)

    class Quiet(socketserver.TCPServer):
        allow_reuse_address = True

        def handle_error(self, *a):
            pass

    try:
        srv = Quiet(("127.0.0.1", port), handler)
    except OSError as e:
        # Falling back keeps the run working, but say so: this run starts from
        # an empty cache and will download the weights again.
        print(f"port {port} is taken ({e}); using an ephemeral one, so this "
              f"run is a different origin and re-downloads the weights.",
              file=sys.stderr)
        srv = Quiet(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # A unique query per run, because Chrome served index.html straight from
    # its disk cache without revalidating — heuristic freshness on a response
    # that carried no cache headers. Same origin, so the downloaded weights in
    # the Cache API still survive; only the shell is forced to be current.
    return srv, (f"http://127.0.0.1:{srv.server_address[1]}/index.html"
                 f"?run={int(time.time())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="test a deployed build instead of this checkout")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--profile", default=DEFAULT_PROFILE,
                    help=f"browser profile dir, kept between runs (default {DEFAULT_PROFILE})")
    ap.add_argument("--model", help="model key: smol-360m, llama-1b, qwen-0.5b, qwen-1.5b")
    ap.add_argument("--f32", action="store_true", help="force the 32-bit build")
    ap.add_argument("--loose", action="store_true", help="skip the strict JSON grammar")
    ap.add_argument("--channel", default="chrome",
                    help="browser channel; 'bundled' uses Playwright's Chromium")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port to serve on (default {DEFAULT_PORT}); it is part "
                         f"of the origin, so changing it empties the model cache")
    ap.add_argument("--timeout", type=int, default=1200,
                    help="seconds to wait for the report (default 1200)")
    args = ap.parse_args()

    srv = None
    if args.url:
        url = args.url
    else:
        srv, url = serve(ROOT, args.port)

    prefs = []
    if args.model:
        prefs.append(f"localStorage.setItem('enrichModel', {args.model!r});")
    prefs.append("localStorage.%s('enrichForceF32'%s);"
                 % (("setItem", ", '1'") if args.f32 else ("removeItem", "")))
    prefs.append("localStorage.%s('enrichLooseJSON'%s);"
                 % (("setItem", ", '1'") if args.loose else ("removeItem", "")))

    # Linux Chrome often needs these to expose an adapter; they are a no-op
    # where WebGPU is already on, and are not passed on other platforms where
    # they have no meaning.
    flags = ["--enable-unsafe-webgpu", "--enable-features=Vulkan"] \
        if sys.platform.startswith("linux") else []

    os.makedirs(args.profile, exist_ok=True)

    with sync_playwright() as p:
        # Service workers blocked: this tool must run the checkout, not a shell
        # a previous run cached. With the port fixed the origin is stable, so a
        # registered worker persists between runs and will happily serve the
        # old index.html — a run that reported a stale APP_VERSION and silently
        # tested code that was no longer on disk.
        launch = dict(user_data_dir=args.profile, headless=args.headless,
                      args=flags, service_workers="block")
        if args.channel != "bundled":
            launch["channel"] = args.channel
        try:
            ctx = p.chromium.launch_persistent_context(**launch)
        except Exception as e:
            if args.channel == "bundled":
                raise
            print(f"could not launch '{args.channel}' ({e}); falling back to the "
                  f"bundled Chromium, which usually has no WebGPU.\n", file=sys.stderr)
            launch.pop("channel")
            ctx = p.chromium.launch_persistent_context(**launch)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # The report names the step that failed; these name the URL or the line
        # that did it. The engine step fetches hundreds of files, and "Request
        # failed" on its own has cost more than one debugging session.
        page.on("requestfailed", lambda r: print(
            "  ! failed   %s  %s" % (r.failure, r.url[:150]),
            file=sys.stderr, flush=True))
        page.on("response", lambda r: r.status >= 400 and print(
            "  ! http %s  %s" % (r.status, r.url[:150]),
            file=sys.stderr, flush=True))
        page.on("pageerror", lambda e: print(
            "  ! page    %s" % str(e)[:300], file=sys.stderr, flush=True))
        page.on("console", lambda m: m.type == "error" and print(
            "  ! console %s" % m.text[:300], file=sys.stderr, flush=True))
        page.add_init_script("\n".join(prefs))
        page.goto(url)
        page.wait_for_selector("#list")
        page.click("#settingsBtn")
        page.wait_for_selector("#sheet.open")
        # The cold-run warning: this is the run that is meant to download it.
        page.on("dialog", lambda d: d.accept())
        page.click("#selfTestBtn")

        # Printed as it grows rather than at the end, so a long download or a
        # hung step is visible while it is happening.
        # Diffed by content rather than by line count, because the report's
        # last line is volatile: a progress tick is rendered as a line that is
        # not part of the report yet, so the next real line reuses its index.
        # Counting lost the one line that matters — "verdict FAILED AT <step>"
        # landed on a spent tick's index and was never printed — and froze the
        # engine's progress at whatever percentage arrived first.
        emitted, deadline = [], time.time() + args.timeout
        report = ""
        while time.time() < deadline:
            report = page.input_value("#diagOut")
            lines = report.split("\n")
            for i, line in enumerate(lines):
                if i >= len(emitted):
                    print(line, flush=True)
                    emitted.append(line)
                elif emitted[i] != line:
                    print(line, flush=True)
                    emitted[i] = line
            if report.startswith("verdict") or "\nverdict" in report:
                break
            page.wait_for_timeout(500)
        else:
            print(f"\nno verdict after {args.timeout}s — the report above is "
                  f"where it stopped.", file=sys.stderr)

        ctx.close()

    if srv:
        srv.shutdown()

    return 0 if "PASS" in report.split("verdict")[-1] else 1


if __name__ == "__main__":
    sys.exit(main())
