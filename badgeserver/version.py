# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""The running version string, shown in the site footer.

Format: ``<most recent tag> (<short commit>)`` — e.g. ``v1.2.0 (a1b2c3d)`` —
or just ``(<short commit>)`` while there is no tag yet.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def app_version() -> str:
    """Best-effort version string.

    Prefers ``BADGESERVER_VERSION`` from the environment (set it in the systemd
    unit or the container image, where there is no git checkout); otherwise it
    is derived from git. Falls back to ``"unknown"``.
    """
    env = os.environ.get("BADGESERVER_VERSION", "").strip()
    if env:
        return env
    return _git_version() or "unknown"


def _git_version() -> str:
    def run(*args: str) -> str:
        try:
            proc = subprocess.run(
                # safe.directory=* -> tolerate a checkout owned by another user
                # (rsync/root deploy, app runs as "badges"); read-only ops only.
                ["git", "-c", "safe.directory=*", *args],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    short = run("rev-parse", "--short", "HEAD")
    if not short:
        return ""
    tag = run("describe", "--tags", "--abbrev=0")
    return f"{tag} ({short})" if tag else f"({short})"
