#!/usr/bin/env python3
"""Claude Code PostToolUse hook: push to origin after a successful `git commit`.

Reads a PostToolUse event JSON from stdin. Fires only when:
  * tool_name == "Bash"
  * the executed command actually invoked `git commit` (not `git diff`, etc.)
  * the commit produced a new revision (skips "nothing to commit" no-ops)

If the current branch has no upstream, sets it to ``origin/<branch>`` on the
first push. Otherwise plain ``git push``.

All output is sent to stderr so it shows up in the user's transcript without
polluting tool stdout.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/hjkim24/RADP")


def _log(msg: str) -> None:
    print(f"[auto-push] {msg}", file=sys.stderr)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if event.get("tool_name") != "Bash":
        return 0
    cmd = (event.get("tool_input") or {}).get("command", "")
    # Match `git commit` as an actual command boundary, not a substring.
    if not re.search(r"(^|[ &;|])git commit\b", cmd):
        return 0

    # Did the commit actually happen? Check that the most-recent reflog entry
    # points at a commit younger than ~10 seconds. Avoids pushing if the
    # commit was rejected by commit-msg hook or by "nothing to commit".
    res = _git("log", "-1", "--format=%H %ct")
    if res.returncode != 0 or not res.stdout.strip():
        _log("no commits yet; skipping push")
        return 0
    head_sha, head_ts = res.stdout.strip().split()
    import time
    if time.time() - int(head_ts) > 10:
        _log(f"HEAD ({head_sha[:7]}) is older than 10s; commit probably did not happen, skipping push")
        return 0

    upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream.returncode == 0:
        push = _git("push")
    else:
        branch = _git("branch", "--show-current").stdout.strip()
        if not branch:
            _log("detached HEAD; refusing to push")
            return 0
        push = _git("push", "-u", "origin", branch)

    output = (push.stdout + push.stderr).strip()
    if push.returncode == 0:
        _log(f"pushed HEAD ({head_sha[:7]}) — {output.splitlines()[-1] if output else 'ok'}")
    else:
        _log(f"push failed (exit {push.returncode}): {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
