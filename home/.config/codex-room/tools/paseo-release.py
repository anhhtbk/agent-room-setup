#!/usr/bin/env python3
"""Resolve the newest published stable Paseo release to one immutable commit.

Usage: paseo-release.py resolve

Prints ``<tag> <commit>`` on stdout. Stable means a published GitHub release
that is neither draft nor prerelease and whose tag is ``vMAJOR.MINOR.PATCH``;
the highest version wins, so a later-published backport cannot downgrade.
The tag is then peeled through ``git ls-remote`` on the official source, which
callers pin for the rest of one install so a tag moving mid-install is caught.

Environment:
  PASEO_SOURCE_URL    Git source (default: official getpaseo repository).
  PASEO_RELEASES_API  Releases endpoint; ``file://`` or a path reads a JSON
                      array (used by offline fixtures).
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

OFFICIAL_SOURCE = "https://github.com/getpaseo/paseo.git"
OFFICIAL_RELEASES = "https://api.github.com/repos/getpaseo/paseo/releases"
STABLE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
PAGE_SIZE = 100
MAX_PAGES = 5


def fail(message: str) -> None:
    raise SystemExit(f"paseo-release: {message}")


def fetch_releases(endpoint: str) -> list[dict]:
    if endpoint.startswith("file://") or not re.match(r"[a-z]+://", endpoint):
        path = Path(endpoint.removeprefix("file://"))
        try:
            releases = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            fail(f"cannot read release metadata {path}: {error}")
        if not isinstance(releases, list):
            fail("release metadata must be a JSON array")
        return releases
    releases: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        request = urllib.request.Request(
            f"{endpoint}?per_page={PAGE_SIZE}&page={page}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "codex-room-setup"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.load(response)
        except (OSError, ValueError) as error:
            fail(f"cannot list Paseo releases from {endpoint}: {error}")
        if not isinstance(batch, list):
            fail("unexpected Paseo release listing")
        releases.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return releases


def latest_stable(releases: list[dict]) -> str:
    stable = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
            continue
        tag = release.get("tag_name")
        match = STABLE_TAG.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            stable.append((tuple(map(int, match.groups())), tag))
    if not stable:
        fail("no published stable Paseo release found")
    return max(stable)[1]


def peeled_commit(source: str, tag: str) -> str:
    completed = subprocess.run(
        ["git", "ls-remote", source, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        capture_output=True, text=True,
    )
    if completed.returncode:
        fail(f"cannot read {tag} from {source}: {completed.stderr.strip()}")
    refs = {}
    for line in completed.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        refs[ref] = sha
    commit = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail(f"release {tag} has no tag in {source}")
    return commit


def main() -> None:
    if sys.argv[1:] != ["resolve"]:
        fail("usage: paseo-release.py resolve")
    source = os.environ.get("PASEO_SOURCE_URL", OFFICIAL_SOURCE)
    tag = latest_stable(fetch_releases(os.environ.get("PASEO_RELEASES_API", OFFICIAL_RELEASES)))
    print(tag, peeled_commit(source, tag))


if __name__ == "__main__":
    main()
