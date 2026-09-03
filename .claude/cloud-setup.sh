#!/usr/bin/env bash
# Setup script for Claude Code cloud sessions.
#
# Point the cloud environment's setup script at this file:
#     bash .claude/cloud-setup.sh
#
# The app itself needs nothing installed — no build step, no dependencies.
# This exists solely so the test suite can run, which matters more here than
# it sounds: the sync code's safety properties are only checked by those
# tests, and editing this app without being able to run them is guesswork.
#
# Network access: the environment must allow cdn.playwright.dev, which is
# where the browser download comes from. PyPI is covered by the default
# Trusted access level; cdn.playwright.dev is not a package registry and is
# not included by default. Without it, pip succeeds and the browser install
# fails.
#
# Budget: setup scripts get roughly five minutes. The browser is ~115MB, so
# it is downloaded in the background rather than blocking session start. The
# first test run may wait a few seconds for it; every run after that is
# instant.

set -euo pipefail

echo "==> installing playwright"
pip install --quiet --break-system-packages playwright

echo "==> downloading chromium in the background"
# Logged rather than discarded, so a failure here is diagnosable instead of
# showing up later as a confusing test error.
nohup python3 -m playwright install chromium \
  > /tmp/playwright-install.log 2>&1 &

echo "==> setup done; chromium continues in the background"
echo "    if tests fail to launch a browser, check /tmp/playwright-install.log"
