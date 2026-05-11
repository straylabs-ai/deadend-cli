# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``authenticate_service(auth_flow=AuthFlow.HTTP_LOGIN)`` (Phase 12).

We verify the Basic-auth flow:

* Wallet credentials build ``Authorization: Basic <b64>``.
* Without a probe URL, the AuthContext is saved immediately (no HTTP call).
* With a probe URL, a single GET is made and 401/403 short-circuits with a
  clean failure (no AuthContext saved).
* The saved AuthContext exposes the Basic header in
  ``headers_available`` but **never** the password in any LLM-facing summary.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

import importlib
import sys

from deadend_agent.auth_resolver import AuthContextHandler, AuthFlow, AuthType

importlib.import_module("deadend_agent.tools.browser.authenticate")
auth_module = sys.modules["deadend_agent.tools.browser.authenticate"]

pytestmark = pytest.mark.asyncio


# Reuse the fake aiohttp session from the JSON-flow tests.
class _FakeResponse:
    def __init__(self, *, status: int = 200, url: str = "http://target/admin") -> None:
        self.status = status
        self.url = url
        self.headers = {"Content-Type": "text/html"}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    def __init__(self, *, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return self._response


@pytest.fixture
def patched_aiohttp(monkeypatch: pytest.MonkeyPatch):
    box: dict[str, Any] = {
        "response": _FakeResponse(status=200),
        "session": None,
    }

    def fake_client_session(*args: Any, **kwargs: Any) -> _FakeSession:
        sess = _FakeSession(response=box["response"])
        box["session"] = sess
        return sess

    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", fake_client_session)
    return box


class TestBasicFlow:
    async def test_no_probe_saves_context_directly(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # ``basic-only.test`` is configured in the conftest wallet with
        # credentials but no ``login_url``, so the Basic flow can't fall back
        # to a wallet-provided probe URL.
        result = await auth_module.authenticate_service(
            target="http://basic-only.test",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_flow=AuthFlow.HTTP_LOGIN,
            auth_type=AuthType.API_KEY,
            auth_url=None,  # no probe
        )
        assert result["success"] is True
        assert result["auth_flow"] == "http"
        assert result["auth_type"] == "api_key"
        assert result["headers_available"] == ["Authorization"]
        # No HTTP call performed.
        assert patched_aiohttp["session"] is None

        handler = AuthContextHandler(
            target="http://basic-only.test", agent_id="aid", session_id="sid"
        )
        ctx = handler.load_context("default")
        assert ctx is not None
        expected = "Basic " + base64.b64encode(b"basicuser:basicpass").decode("ascii")
        assert ctx.headers == {"Authorization": expected}
        # Safe summary doesn't leak the password.
        rendered = json.dumps(handler.summarize_context("default"))
        assert "basicuser" not in rendered
        assert "basicpass" not in rendered

    async def test_probe_success_saves_context_and_records_status(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200, url="http://localhost:8080/admin"
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="admin",
            auth_flow=AuthFlow.HTTP_LOGIN,
            auth_url="http://localhost:8080/admin",
        )
        assert result["success"] is True
        assert "probe" in result["success_matched"]
        sess = patched_aiohttp["session"]
        assert sess is not None
        url, kwargs = sess.calls[0]
        assert url == "http://localhost:8080/admin"
        # Authorization header is built from the WALLET, not from anything the LLM passed.
        expected = "Basic " + base64.b64encode(b"root:rootpass").decode("ascii")
        assert kwargs["headers"]["Authorization"] == expected

    @pytest.mark.parametrize("status", [401, 403])
    async def test_probe_rejection_short_circuits(
        self,
        status: int,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(status=status)
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_flow=AuthFlow.HTTP_LOGIN,
            auth_url="http://localhost:8080/admin",
        )
        assert result["success"] is False
        assert str(status) in result["error"]
        # No AuthContext saved on probe failure.
        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid"
        )
        assert handler.load_context("default") is None

    async def test_missing_credentials_fails(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # No wallet match for this target -> empty CredentialsRefs.
        result = await auth_module.authenticate_service(
            target="http://no-wallet.test",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_flow=AuthFlow.HTTP_LOGIN,
        )
        assert result["success"] is False
        assert "username" in result["error"].lower()
        assert "password" in result["error"].lower()
