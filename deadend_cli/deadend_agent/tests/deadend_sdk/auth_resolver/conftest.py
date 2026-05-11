# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Shared fixtures for auth_resolver / authentication tool tests.

Each test gets its own isolated ``DEADEND_AGENTS_PATH`` so we never touch the
real ``~/.deadend`` tree. The patch is applied to **both** ``constants`` and
``auth_resolver.auth_resolver`` because the latter does
``from deadend_agent.constants import DEADEND_AGENTS_PATH`` at import time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

import deadend_agent.auth_resolver.auth_resolver as auth_resolver_module
import deadend_agent.constants as constants_module


@pytest.fixture
def isolated_deadend_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DEADEND_AGENTS_PATH to a per-test tmp directory."""
    agents_root = tmp_path / "agents"
    monkeypatch.setattr(constants_module, "DEADEND_AGENTS_PATH", agents_root)
    monkeypatch.setattr(auth_resolver_module, "DEADEND_AGENTS_PATH", agents_root)
    return agents_root


@pytest.fixture
def fake_browser_state() -> dict[str, Any]:
    """Realistic ``BrowserSession.export_state()`` output for tests."""
    return {
        "cookies": [
            {
                "name": "sessionid",
                "value": "REAL_SESSION_VALUE",
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
                "size": 80,            # CDP read-only field, must be stripped on import
                "session": False,
                "sourcePort": 8080,    # CDP read-only field
            },
            {
                "name": "csrftoken",
                "value": "CSRF_VAL",
                "domain": "localhost",
                "path": "/",
            },
        ],
        "localStorage": {
            "access_token": "REAL_BEARER_TOKEN",
            "feature_flag": "on",
        },
        "sessionStorage": {
            "csrf": "REAL_CSRF",
        },
        "url": "http://localhost:8080/dashboard",
        "title": "Dashboard",
    }


@pytest.fixture
def reusable_credentials_wallet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Plant a temporary reusable_credentials.json wallet for tests."""
    wallet_path = tmp_path / "reusable_credentials.json"
    # ``CredentialsStore._normalise_target`` strips scheme, path, and **port**,
    # so the wallet key must be the bare host (e.g. "localhost", not
    # "localhost:8080").
    wallet = {
        "targets": {
            "localhost": {
                "credentials": {
                    "default": {
                        "username": "alice",
                        "password": "p4ssw0rd!",
                        "role": "user",
                    },
                    "admin": {
                        "username": "root",
                        "password": "rootpass",
                        "role": "admin",
                    },
                },
                "login_url": "http://localhost:8080/login",
                "refresh_url": "http://localhost:8080/refresh",
            },
            # A second target that has credentials but NO login_url, so Basic
            # auth tests can verify the "no probe" branch.
            "basic-only.test": {
                "credentials": {
                    "default": {
                        "username": "basicuser",
                        "password": "basicpass",
                        "role": "user",
                    },
                },
            },
        }
    }
    wallet_path.write_text(json.dumps(wallet), encoding="utf-8")
    monkeypatch.setattr(
        auth_resolver_module, "REUSABLE_CREDENTIALS_FILE", wallet_path
    )
    monkeypatch.setattr(constants_module, "REUSABLE_CREDENTIALS_FILE", wallet_path)
    # ``CredentialsStore._wallet_path`` is read at class-level, override it too.
    monkeypatch.setattr(
        auth_resolver_module.CredentialsStore, "_wallet_path", wallet_path
    )
    return wallet_path
