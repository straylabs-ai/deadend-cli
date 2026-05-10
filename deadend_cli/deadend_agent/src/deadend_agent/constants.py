# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.
"""Canonical path constants for the DeadEnd agent storage layout.

Two roots are used:

* ``~/.deadend/`` — persistent data that should survive across runs
  (config, credentials, per-agent DBs, auth contexts, crawled webpages).

* ``~/.cache/deadend/`` — runtime data
  (traces, context dumps, metrics, tool JSONL results).

Both trees share the same hierarchy:

    agents/<agent_id>/<target_slug>/

``agent_id`` is the resumable session UUID.
``target_slug`` is the filesystem-safe target identifier (e.g. ``localhost_8080``).
"""
from __future__ import annotations
from pathlib import Path

ROOT_DEADEND_PATH = Path.home() / ".deadend"
MODEL_CONFIG_PATH = ROOT_DEADEND_PATH / "config.json"
SETTINGS_CONFIG_PATH = ROOT_DEADEND_PATH / "settings.json"
DEADEND_AGENTS_PATH = ROOT_DEADEND_PATH / "agents"
DEADEND_VALIDATION_CONFIG_PATH = ROOT_DEADEND_PATH / "validation.yaml"
REUSABLE_CREDENTIALS_FILE: Path = ROOT_DEADEND_PATH / "reusable_credentials.json"
DEADEND_PROMPTS_PATH = ROOT_DEADEND_PATH / "prompts"

CACHE_DEADEND_PATH = Path.home() / ".cache" / "deadend"
CACHE_DEADEND_AGENTS_PATH = CACHE_DEADEND_PATH / "agents"
CACHE_TRACES_PATH = CACHE_DEADEND_PATH / "traces"
CACHE_METRICS_PATH = CACHE_DEADEND_PATH / "metrics"
CACHE_TOOL_RESULTS = CACHE_DEADEND_PATH / "tool_results"
CACHE_DEADEND_LOGS = CACHE_DEADEND_PATH / "logs"



