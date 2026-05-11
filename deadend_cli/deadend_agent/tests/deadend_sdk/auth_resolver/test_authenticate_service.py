# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``authenticate_service`` that don't require a real browser.

We exercise:

* The pre-flight error path when no ``auth_url`` is provided AND the wallet has
  no ``login_url`` for the profile (no browser is launched).
* The credential merge rule that wallet-resolved credentials win over caller
  context (so the LLM never overrides real ``username`` / ``password``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deadend_agent.auth_resolver import CredentialsRefs
from deadend_agent.tools.browser.authenticate import (
    _merge_auth_context,
    authenticate_service,
)


class TestMergeAuthContext:
    def test_wallet_credentials_override_caller_context(self) -> None:
        creds = CredentialsRefs(
            username="alice",
            password="p4ssw0rd!",
            login_url="http://t/login",
            refresh_url="http://t/refresh",
        )
        merged = _merge_auth_context(
            {"username": "ATTACKER", "password": "ATTACKER", "csrf": "abc"},
            creds,
        )
        # Wallet wins for sensitive fields...
        assert merged["username"] == "alice"
        assert merged["password"] == "p4ssw0rd!"
        # ...non-sensitive caller keys are preserved.
        assert merged["csrf"] == "abc"
        # login_url / refresh_url are filled if missing.
        assert merged["login_url"] == "http://t/login"
        assert merged["refresh_url"] == "http://t/refresh"

    def test_caller_login_url_wins_when_explicitly_set(self) -> None:
        creds = CredentialsRefs(
            username=None,
            password=None,
            login_url="http://wallet/login",
            refresh_url=None,
        )
        merged = _merge_auth_context(
            {"login_url": "http://caller/login"}, creds
        )
        # ``setdefault`` semantics: caller-provided login_url is preserved.
        assert merged["login_url"] == "http://caller/login"

    def test_empty_wallet_keeps_caller_context(self) -> None:
        merged = _merge_auth_context({"username": "x"}, CredentialsRefs())
        assert merged == {"username": "x"}


class TestAuthenticateServicePreflight:
    pytestmark = pytest.mark.asyncio

    async def test_returns_error_when_no_auth_url_resolvable(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,  # has login_url for localhost:8080 only
    ) -> None:
        result = await authenticate_service(
            target="http://no-wallet.test",  # not in wallet => no login_url
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url=None,                    # caller does not override
            steps=[],
        )
        assert result["success"] is False
        assert result["auth_context_saved"] is False
        assert result["target"] == "http://no-wallet.test"
        assert result["agent_id"] == "aid"
        assert result["session_id"] == "sid"
        assert "auth_url" in result["error"].lower()
        # The handler always creates the ``auth_context`` directory eagerly
        # (on init); on the failure path we just need to confirm no profile or
        # Playwright snapshot was written.
        path = isolated_deadend_root / "aid" / "sid" / "auth_context"
        if path.exists():
            files = sorted(p.name for p in path.iterdir())
            assert "default.json" not in files
            assert "default.playwright.json" not in files
