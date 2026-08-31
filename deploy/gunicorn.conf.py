# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""gunicorn configuration for the badge server."""

import multiprocessing
import os

bind = os.environ.get("BIND", "127.0.0.1:4000")
workers = int(os.environ.get("WEB_CONCURRENCY", min(3, multiprocessing.cpu_count() + 1)))
worker_class = "sync"
timeout = int(os.environ.get("WEB_TIMEOUT", "30"))
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100

# Log to stdout/stderr so the systemd journal captures everything.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
proc_name = "badgeserver"
