#!/usr/bin/env python3
"""Host-only link check: every URL in links.json and every distinct page in pg17.json must answer 200."""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "web" / "public" / "docs"
CLIENT_NAME = "sqldash-link-check"
PAUSE_SECONDS = 0.5


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
    req = urllib.request.Request(url, headers={"User-Agent": CLIENT_NAME})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code
    except urllib.error.URLError as err:
        return str(err.reason)


def main():
    urls = collect()
    bad = []
    for url in urls:
        code = status(url)
        if code != 200:
            bad.append((code, url))
            print(f"{code} {url}")
        time.sleep(PAUSE_SECONDS)  # short pause between requests
    print(f"checked {len(urls)} urls, {len(bad)} not 200")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
