# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for model-supplied credentials (``authenticate(username=..., password=...)``).

Precedence:

    explicit tool args  >  wallet ``CredentialsRefs``  >  nothing

Validates:

* The unit-level helpers ``_resolve_credentials`` and ``_merge_auth_context``
  obey that precedence (incl. partial overrides and brand-new profiles).
* The JSON flow templates ``{{username}}`` / ``{{password}}`` with explicit
  args even when the wallet has different values.
* The HTTP Basic flow builds the ``Authorization`` header from explicit args
  in preference to the wallet.
* A brand-new ``profile`` that does not exist in the wallet can still be
  authenticated using explicit args, and the resulting AuthContext is saved
  under that new profile name on disk.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest

from deadend_agent.auth_resolver import AuthContextHandler, AuthFlow, AuthType, CredentialsRefs
from deadend_agent.tools.browser.authenticate import _merge_auth_context, _resolve_credentials

# Pull the actual module object (name collision with the tool function).
importlib.import_module("deadend_agent.tools.browser.authenticate")
auth_module = sys.modules["deadend_agent.tools.browser.authenticate"]


# ---------------------------------------------------------------------------
# Unit-level precedence checks
# ---------------------------------------------------------------------------


class TestResolveCredentialsPrecedence:
    WALLET = CredentialsRefs(
        username="wallet_user",
        password="wallet_pwd",
        login_url="http://t/login",
        refresh_url="http://t/refresh",
    )
    EMPTY = CredentialsRefs()

    def test_explicit_wins_over_wallet(self) -> None:
        u, p = _resolve_credentials(
            self.WALLET, override_username="explicit_user", override_password="explicit_pwd"
        )
        assert (u, p) == ("explicit_user", "explicit_pwd")

    def test_wallet_used_when_overrides_absent(self) -> None:
        u, p = _resolve_credentials(self.WALLET, override_username=None, override_password=None)
        assert (u, p) == ("wallet_user", "wallet_pwd")

    def test_partial_override_username(self) -> None:
        u, p = _resolve_credentials(
            self.WALLET, override_username="other_user", override_password=None
        )
        assert (u, p) == ("other_user", "wallet_pwd")

    def test_partial_override_password(self) -> None:
        u, p = _resolve_credentials(
            self.WALLET, override_username=None, override_password="other_pwd"
        )
        assert (u, p) == ("wallet_user", "other_pwd")

    def test_explicit_only_when_wallet_empty(self) -> None:
        u, p = _resolve_credentials(
            self.EMPTY, override_username="discovered", override_password="admin"
        )
        assert (u, p) == ("discovered", "admin")

    def test_both_empty_returns_none(self) -> None:
        u, p = _resolve_credentials(self.EMPTY, override_username=None, override_password=None)
        assert (u, p) == (None, None)


class TestMergeAuthContext:
    WALLET = CredentialsRefs(
        username="wallet_user", password="wallet_pwd",
        login_url="http://t/login", refresh_url="http://t/refresh",
    )

    def test_explicit_overrides_in_merged_context(self) -> None:
        merged = _merge_auth_context(
            {"tenant": "ACME"}, self.WALLET,
            override_username="explicit_user", override_password="explicit_pwd",
        )
        assert merged["username"] == "explicit_user"
        assert merged["password"] == "explicit_pwd"
        # Non-credential keys are preserved untouched.
        assert merged["tenant"] == "ACME"
        # Wallet still fills login_url / refresh_url.
        assert merged["login_url"] == "http://t/login"
        assert merged["refresh_url"] == "http://t/refresh"

    def test_caller_login_url_not_clobbered(self) -> None:
        merged = _merge_auth_context(
            {"login_url": "http://caller/login"}, self.WALLET,
        )
        # ``setdefault`` semantics: caller value preserved.
        assert merged["login_url"] == "http://caller/login"


# ---------------------------------------------------------------------------
# Flow-level integration (no real browser / no real network)
# ---------------------------------------------------------------------------
#
# Re-use the aiohttp recorder pattern from the existing JSON/Basic flow tests.


class _FakeResponse:
    def __init__(self, *, status=200, json_body=None, text_body=None,
                 url="http://target/api/auth/login", content_type="application/json"):
        self.status = status
        self._json = json_body
        self._text = text_body if text_body is not None else json.dumps(json_body)
        self.url = url
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None
    async def json(self, content_type=None):  # type: ignore[no-untyped-def]
        return self._json if self._json is not None else json.loads(self._text or "null")
    async def text(self): return self._text or ""


class _FakeJar:
    def __iter__(self): return iter([])


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    @property
    def cookie_jar(self): return _FakeJar()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs)); return self._response
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs)); return self._response


@pytest.fixture
def patched_aiohttp(monkeypatch: pytest.MonkeyPatch):
    box: dict[str, Any] = {
        "response": _FakeResponse(status=200, json_body={"access_token": "JWT"}),
        "session": None,
    }

    def fake_client_session(*args: Any, **kwargs: Any):
        sess = _FakeSession(box["response"])
        box["session"] = sess
        return sess

    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", fake_client_session)
    return box


class TestJsonFlowWithModelSuppliedCredentials:
    """``authenticate(auth_flow=json, username=..., password=...)`` must render
    the explicit values into the request body via ``{{username}} / {{password}}``
    placeholders, even when the wallet has different values."""

    pytestmark = pytest.mark.asyncio

    async def test_explicit_args_appear_in_request_body(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,  # wallet has alice/p4ssw0rd!
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "JWT_TOKEN"},
        )
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="user_supplied",            # NEW profile, not in wallet
            auth_url="http://localhost:8080/api/auth/login",
            auth_flow=AuthFlow.JSON,
            auth_type=AuthType.BEARER_TOKEN,
            username="USER_FROM_MODEL",
            password="PASS_FROM_MODEL",
            request_body={"email": "{{username}}", "password": "{{password}}"},
            token_path="access_token",
        )
        assert result["success"] is True
        # Saved under the brand-new profile name.
        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid",
        )
        assert handler.load_context("user_supplied") is not None

        sess = patched_aiohttp["session"]
        assert sess is not None
        _, _, kwargs = sess.calls[0]
        # Body templated with EXPLICIT values, not wallet.
        assert kwargs["json"] == {
            "email": "USER_FROM_MODEL",
            "password": "PASS_FROM_MODEL",
        }

    async def test_partial_override_username_only(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "JWT"},
        )
        # Wallet profile ``default`` -> alice/p4ssw0rd!
        await auth_module.authenticate_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_url="http://localhost:8080/api/auth/login",
            auth_flow=AuthFlow.JSON,
            username="OVERRIDE_USER",           # only username overridden
            request_body={"email": "{{username}}", "password": "{{password}}"},
            token_path="access_token",
        )
        sess = patched_aiohttp["session"]
        _, _, kwargs = sess.calls[0]
        assert kwargs["json"] == {
            "email": "OVERRIDE_USER",
            "password": "p4ssw0rd!",            # wallet still provides password
        }


class TestBasicFlowWithModelSuppliedCredentials:
    """``authenticate(auth_flow=http, username=..., password=...)`` builds the
    Basic header from the explicit values, ignoring the wallet for this call."""

    pytestmark = pytest.mark.asyncio

    async def test_explicit_creds_in_basic_header(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        result = await auth_module.authenticate_service(
            target="http://localhost:8080",   # wallet profile ``default`` = alice
            agent_id="aid",
            session_id="sid",
            profile="discovered_admin",       # brand-new profile
            auth_flow=AuthFlow.HTTP_LOGIN,
            auth_type=AuthType.API_KEY,
            username="admin",
            password="admin",
            auth_url=None,                    # no probe; just save
        )
        assert result["success"] is True
        # No HTTP call (no probe URL).
        assert patched_aiohttp["session"] is None

        handler = AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid",
        )
        ctx = handler.load_context("discovered_admin")
        assert ctx is not None
        expected = "Basic " + base64.b64encode(b"admin:admin").decode("ascii")
        assert ctx.headers == {"Authorization": expected}
        # And the wallet values for ``default`` were NOT used here.
        assert "alice" not in json.dumps(handler.summarize_context("discovered_admin"))

    async def test_basic_without_wallet_or_args_fails_cleanly(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # Target not in the wallet AND no explicit args -> fail.
        result = await auth_module.authenticate_service(
            target="http://nowhere.test",
            agent_id="aid",
            session_id="sid",
            profile="default",
            auth_flow=AuthFlow.HTTP_LOGIN,
        )
        assert result["success"] is False
        assert "username" in result["error"] and "password" in result["error"]


class TestRefreshWithModelSuppliedCredentials:
    """Refresh body placeholders ``{{username}} / {{password}}`` also honour
    the explicit override args, on top of the existing access/refresh-token
    auto-injection."""

    pytestmark = pytest.mark.asyncio

    async def test_explicit_creds_in_refresh_body(
        self,
        isolated_deadend_root: Path,
        reusable_credentials_wallet: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # Seed an AuthContext directly so we can drive refresh.
        from deadend_agent.auth_resolver import (
            auth_context_from_api_response,
        )
        seed = auth_context_from_api_response(
            profile="default",
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            token="OLD_TOKEN",
            cookies=[],
            auth_flow="json",
            auth_type="bearer_token",
            extra_metadata={"refresh_url": "http://localhost:8080/api/auth/refresh"},
        )
        AuthContextHandler(
            target="http://localhost:8080", agent_id="aid", session_id="sid",
        ).save_context("default", seed)

        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "NEW_TOKEN"},
        )
        from deadend_agent.tools.browser.validate_refresh import refresh_auth_context_service

        result = await refresh_auth_context_service(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            profile="default",
            username="EXPLICIT_USER",
            password="EXPLICIT_PWD",
            refresh_body={
                "user": "{{username}}",
                "secret": "{{password}}",
                "current": "{{access_token}}",
            },
        )
        assert result["success"] is True
        sess = patched_aiohttp["session"]
        _, _, kwargs = sess.calls[0]
        body = kwargs["json"]
        assert body["user"] == "EXPLICIT_USER"
        assert body["secret"] == "EXPLICIT_PWD"
        # Access token is still auto-injected from the existing AuthContext.
        assert body["current"] == "OLD_TOKEN"
