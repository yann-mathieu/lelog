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

The browser profile is kept between runs (see --profile), so the model is
downloaded once and every later run starts from cache. Delete that directory
to test a cold download.

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


def serve(root):
    """Serve the repo on an ephemeral port. IndexedDB needs a real origin."""
    handler = functools.partial(Handler, directory=root)

    class Quiet(socketserver.TCPServer):
        allow_reuse_address = True

        def handle_error(self, *a):
            pass

    srv = Quiet(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html"


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
    ap.add_argument("--timeout", type=int, default=1200,
                    help="seconds to wait for the report (default 1200)")
    args = ap.parse_args()

    srv = None
    if args.url:
        url = args.url
    else:
        srv, url = serve(ROOT)

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
        launch = dict(user_data_dir=args.profile, headless=args.headless, args=flags)
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
        shown, deadline = 0, time.time() + args.timeout
        report = ""
        while time.time() < deadline:
            report = page.input_value("#diagOut")
            lines = report.split("\n")
            for line in lines[shown:]:
                print(line, flush=True)
            shown = len(lines)
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
