#!/usr/bin/env python3
"""Pre-publish scan: fail if anything identifying or secret would be committed.

Usage: python tools/secret_scan.py [--deny <literal> ...]   (run from the repo root; scans git-tracked + untracked, not ignored)
Pass environment-specific literals (project id, project number, account email) with --deny; they are never stored here.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

PATTERNS = {
    "google_oauth_access_token": r"ya29\.[0-9A-Za-z_\-]{20,}",
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "github_token": r"gh[pousr]_[0-9A-Za-z]{30,}",
    "private_key_block": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    "refresh_token_field": r"\"refresh_token\"\s*:",
    "client_secret_field": r"\"client_secret\"\s*:",
    "sa_key_json": r"\"type\"\s*:\s*\"service_account\"",
    "run_app_url": r"https://[a-z0-9\-]+-[a-z0-9]{10}-[a-z]{2}\.a\.run\.app",
    "reasoning_engine_resource": r"projects/\d{6,}/locations/[a-z0-9\-]+/reasoningEngines/\d+",
}


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deny", action="append", default=[], help="literal that must not appear (case-insensitive)")
    args = ap.parse_args()
    hits = []
    for f in files():
        try:
            text = open(f, encoding="utf-8", errors="ignore").read()
        except (IsADirectoryError, FileNotFoundError):
            continue
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, text):
                hits.append((f, name, text.count("\n", 0, m.start()) + 1))
        low = text.lower()
        for lit in args.deny:
            i = low.find(lit.lower())
            if i >= 0:
                hits.append((f, "denied_literal", text.count("\n", 0, i) + 1))
    for f, name, line in hits:
        print(f"FAIL {name:28s} {f}:{line}")
    print(f"scanned {len(files())} files: {'CLEAN' if not hits else str(len(hits)) + ' finding(s)'}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
