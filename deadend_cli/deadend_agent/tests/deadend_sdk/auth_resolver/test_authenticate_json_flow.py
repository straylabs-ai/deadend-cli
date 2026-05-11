# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``authenticate_service(auth_flow=AuthFlow.JSON)`` (Phase 12).

We avoid real HTTP by patching ``aiohttp.ClientSession`` inside the
``authenticate`` module with a tiny recorder. The recorder lets each test
declare a canned response (status, JSON body, optional cookies on the jar)
and captures the method/url/kwargs passed by the implementation.

Validates:

* Credentials from the wallet are templated into ``request_body`` via
  ``{{username}} / {{password}}``; the LLM never sees real values.
* The token is extracted via ``token_path`` and saved as
  ``Authorization: Bearer <token>`` (or as a custom header per
  ``token_header_name`` / ``token_header_format``).
* Set-Cookie cookies from the response are saved when ``capture_cookies=True``.
* HTTP \u2265 400 statuses produce structured failure (no AuthContext saved).
* Missing token AND missing cookies produce a clear failure.
* The saved AuthContext is on disk under
  ``<agent_id>/<session_id>/auth_context/<profile>.json`` and the safe
  summary contains no secret material.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest

import importlib
import sys

from deadend_agent.auth_resolver import AuthContextHandler, AuthFlow, AuthType

# The submodule ``deadend_agent.tools.browser.authenticate`` collides with the
# tool function of the same name re-exported by the ``browser`` package's
# ``__init__.py``. Pull the module object explicitly via ``sys.modules`` so
# we can monkey-patch ``aiohttp`` on it.
importlib.import_module("deadend_agent.tools.browser.authenticate")
auth_module = sys.modules["deadend_agent.tools.browser.authenticate"]

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# aiohttp recorder
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_body: Any = None,
        text_body: str | None = None,
        url: str = "http://test/api/auth/login",
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self._json = json_body
        self._text = text_body if text_body is not None else json.dumps(json_body)
        self.url = url
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self, content_type=None):  # type: ignore[no-untyped-def]
        if self._json is None and self._text:
            return json.loads(self._text)
        return self._json

    async def text(self) -> str:
        return self._text or ""


class _FakeJar:
    def __init__(self, morsels):  # type: ignore[no-untyped-def]
        self._morsels = list(morsels)

    def __iter__(self):
        return iter(self._morsels)


class _FakeSession:
    def __init__(self, *, response: _FakeResponse, jar=None):  # type: ignore[no-untyped-def]
        self._response = response
        self._jar = jar or _FakeJar([])
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def cookie_jar(self):  # type: ignore[no-untyped-def]
        return self._jar

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        return self._response


@pytest.fixture
def patched_aiohttp(monkeypatch: pytest.MonkeyPatch):
    """Replace the ``aiohttp.ClientSession`` reference inside the auth module
    with a recorder that returns a programmable ``_FakeSession``.

    Returns a ``box`` dict whose ``response`` / ``jar`` keys can be set BEFORE
    calling the auth service, and whose ``session`` key is filled in after.
    """
    box: dict[str, Any] = {
        "response": _FakeResponse(status=200, json_body={"access_token": "JWT_X"}),
        "jar": _FakeJar([]),
        "session": None,
    }

    def fake_client_session(*args: Any, **kwargs: Any) -> _FakeSession:
        sess = _FakeSession(response=box["response"], jar=box["jar"])
        box["session"] = sess
        return sess

    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", fake_client_session)
    return box


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _morsel(name: str, value: str, **attrs):  # type: ignore[no-untyped-def]
    c = SimpleCookie()
    c[name] = value
    for k, v in attrs.items():
        c[name][k] = v
    return c[name]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJsonFlowSuccess:
    async def test_token_extracted_and_saved_as_bearer(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200,
            json_body={"access_token": "JWT_TOKEN", "user": {"id": 1}},
            url="http://localhost:8080/api/auth/login",
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/auth/login",
            auth_flow=AuthFlow.JSON,
            auth_type=AuthType.BEARER_TOKEN,
            request_body={"email": "{{username}}", "password": "{{password}}"},
            token_path="access_token",
        )
        assert result["success"] is True
        assert result["auth_context_saved"] is True
        assert result["auth_flow"] == "json"
        assert result["auth_type"] == "bearer_token"
        assert "token" in result["success_matched"]
        assert result["headers_available"] == ["Authorization"]

        # The body got templated with real wallet credentials.
        sess = patched_aiohttp["session"]
        assert sess is not None
        method, url, kwargs = sess.calls[0]
        assert method == "POST"
        assert url == "http://localhost:8080/api/auth/login"
        assert kwargs["json"] == {"email": "alice", "password": "p4ssw0rd!"}
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["headers"]["Accept"] == "application/json"

        # AuthContext is on disk.
        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid"
        )
        ctx = handler.load_context("default")
        assert ctx is not None
        assert ctx.headers == {"Authorization": "Bearer JWT_TOKEN"}
        # Safe summary leaks nothing.
        rendered = json.dumps(handler.summarize_context("default"))
        assert "JWT_TOKEN" not in rendered
        assert "alice" not in rendered
        assert "p4ssw0rd" not in rendered

    async def test_custom_token_header_and_format(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200,
            json_body={"data": {"key": "K"}},
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}", "p": "{{password}}"},
            token_path="data.key",
            token_header_name="X-Auth-Token",
            token_header_format="{token}",
        )
        assert result["success"] is True
        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid"
        )
        ctx = handler.load_context("default")
        assert ctx is not None
        assert ctx.headers == {"X-Auth-Token": "K"}
        assert "X-Auth-Token" in result["headers_available"]

    async def test_cookies_captured_when_enabled(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200,
            json_body={"access_token": "T"},
        )
        patched_aiohttp["jar"] = _FakeJar(
            [_morsel("sessionid", "S1", domain="localhost", path="/")]
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
            token_path="access_token",
            capture_cookies=True,
        )
        assert result["success"] is True
        assert "cookies" in result["success_matched"]
        assert result["cookie_names"] == ["sessionid"]
        assert result["cookies_count"] == 1

    async def test_cookies_only_no_token(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # API returns no usable token, but does set a session cookie.
        patched_aiohttp["response"] = _FakeResponse(
            status=200,
            json_body={"ok": True},
        )
        patched_aiohttp["jar"] = _FakeJar(
            [_morsel("sessionid", "S2", domain="localhost", path="/")]
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
            token_path=None,
            capture_cookies=True,
        )
        # No token path supplied -> auth_type defaults to session_cookie.
        assert result["success"] is True
        assert result["auth_type"] == "session_cookie"
        assert "cookies" in result["success_matched"]


class TestJsonFlowFailures:
    async def test_missing_auth_url_returns_error(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # Profile has wallet login_url -> still works. Use a target with no wallet.
        result = await auth_module.authenticate_service(
            target="http://no-wallet.test",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url=None,
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
        )
        assert result["success"] is False
        assert "auth_url" in result["error"].lower()
        assert patched_aiohttp["session"] is None

    async def test_http_error_status_fails(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=401,
            json_body={"error": "invalid_credentials"},
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
            token_path="access_token",
        )
        assert result["success"] is False
        assert "401" in result["error"]
        # No AuthContext saved on failure.
        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid"
        )
        assert handler.load_context("default") is None

    async def test_no_token_no_cookies_fails(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200,
            json_body={"ok": True},
        )
        # capture_cookies=True but no cookies in jar AND no token path matches.
        patched_aiohttp["jar"] = _FakeJar([])
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
            token_path="missing_field",
            capture_cookies=True,
        )
        assert result["success"] is False
        assert "no token" in result["error"].lower()


class TestJsonFlowProxyAndHeaders:
    async def test_proxy_url_passed_through(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "T"}
        )
        await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_body={"u": "{{username}}"},
            token_path="access_token",
            proxy_url="http://127.0.0.1:8118",
        )
        sess = patched_aiohttp["session"]
        method, url, kwargs = sess.calls[0]
        assert kwargs["proxy"] == "http://127.0.0.1:8118"

    async def test_extra_request_headers_templated(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "T"}
        )
        await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/login",
            auth_flow=AuthFlow.JSON,
            request_headers={"X-User": "{{username}}"},
            request_body={"u": "{{username}}"},
            token_path="access_token",
        )
        sess = patched_aiohttp["session"]
        method, url, kwargs = sess.calls[0]
        # Extra headers were rendered with wallet-resolved credentials.
        assert kwargs["headers"]["X-User"] == "alice"
