#!/usr/bin/env python3
"""Host-only link check: every URL in links.json and every distinct page in pg17.json must answer 200."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "web" / "public" / "docs"
PAUSE_SECONDS = 1.0


def collect():
    urls = set()
    links = json.loads((DOCS / "links.json").read_text(encoding="utf-8"))
    for dialect in links.values():
        urls.update(dialect["pages"].values())
        urls.add(dialect["search"].replace("{q}", "select"))
    index = json.loads((DOCS / "pg17.json").read_text(encoding="utf-8"))
    for entries in index["entries"].values():
        for e in entries:
            urls.add(e["url"].split("#")[0])  # the fragment is not sent to the server
    return sorted(urls)


def status(url):
    # plain curl with no custom headers; the status code comes back on stdout
    run = subprocess.run(["curl", "-s", "-o", os.devnull, "-m", "20", "-w", "%{http_code}", url],
                         capture_output=True, text=True)
    return run.stdout.strip() or f"curl exit {run.returncode}"


def main():
    if shutil.which("curl") is None:
        print("curl is not on PATH")
        return 2
    urls = collect()
    bad = []
    for url in urls:
        code = status(url)
        if code != "200":
            bad.append((code, url))
            print(f"{code} {url}", flush=True)
        time.sleep(PAUSE_SECONDS)  # pause between requests, which all go to a few hosts in turn
    print(f"checked {len(urls)} urls, {len(bad)} not 200")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
