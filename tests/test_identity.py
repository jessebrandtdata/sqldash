"""No person's name is hardcoded in tracked source; docs say "the user" and "the maintainer"."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The maintainer's name tokens, case-insensitively.
TOKEN_RE = re.compile(r"jesse|brandt", re.IGNORECASE)

# Strings that contain a token but are system identifiers, not a person: the GitHub
# organisation slug and the host login in a home path. Removed before the scan.
ALLOWED_TOKENS = ("jessebrandtdata", "/home/jesse")

# Directories walked past when git is unavailable (built bundles under dist/ are read).
SKIP_DIRS = {".git", "node_modules", ".superpowers", "__pycache__", ".pytest_cache"}

# This file spells the name, so it is the one file never scanned.
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()


def tracked_paths(root):
    """Repo-relative paths from `git ls-files -z`, or None when git is absent or fails."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return sorted(p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p)


def walked_paths(root):
    """Repo-relative paths of every readable file under root, skipping SKIP_DIRS."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            found.append((Path(dirpath) / name).relative_to(root).as_posix())
    return sorted(found)


def source_files(root=ROOT):
    """Yield (relative path, text) for each readable text file, minus this file."""
    rels = tracked_paths(root)
    if rels is None:
        rels = walked_paths(root)
    for rel in rels:
        if rel == THIS_FILE or SKIP_DIRS & set(rel.split("/")):
            continue
        path = Path(root) / rel
        if not path.is_file():
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_personal_name_in_source():
    offenders = []
    for rel, text in source_files():
        for n, line in enumerate(text.splitlines(), 1):
            probe = line
            for token in ALLOWED_TOKENS:
                probe = probe.replace(token, "")
            if TOKEN_RE.search(probe):
                offenders.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert offenders == [], "personal name in source:\n" + "\n".join(offenders)


def test_allowed_slug_is_clean_and_bare_name_is_not():
    for line in ("github.com/jessebrandtdata/sqldash", "cd /home/jesse/dev/sqldash"):
        probe = line
        for token in ALLOWED_TOKENS:
            probe = probe.replace(token, "")
        assert not TOKEN_RE.search(probe)
    assert TOKEN_RE.search("for Jesse to review")


def test_walk_stands_in_for_git(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    rels = [rel for rel, _ in source_files()]
    assert "serve" in rels and THIS_FILE not in rels
