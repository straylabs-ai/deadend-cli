# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``validate_auth_context_service`` and ``refresh_auth_context_service``.

Phase 13 - the AuthenticatorAgent's validation and refresh services.

We mock ``aiohttp.ClientSession`` so no real network is needed. Each test
seeds a saved AuthContext via ``AuthContextHandler`` and asserts the verdict
plus the side-effect on saved metadata.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest

from deadend_agent.auth_resolver import (
    AuthContext,
    AuthContextHandler,
    CookieRecord,
    StorageSnapshot,
)

# The submodule ``validate_refresh`` does not have a name collision with any
# re-exported attribute, but we use the same ``sys.modules`` pattern as the
# Phase 12 tests for consistency.
importlib.import_module("deadend_agent.tools.browser.validate_refresh")
vr_module = sys.modules["deadend_agent.tools.browser.validate_refresh"]

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# aiohttp recorder (shared with JSON-flow tests in spirit)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_body: Any = None,
        text_body: str | None = None,
        url: str = "http://target/api/me",
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
    def __init__(self, morsels=(), *args, **kwargs):  # type: ignore[no-untyped-def]
        # Accept aiohttp's positional/keyword args (e.g. ``unsafe=True``) so
        # the validator can instantiate ``aiohttp.CookieJar(unsafe=True)`` after
        # we monkey-patch it.
        self._morsels = list(morsels) if not isinstance(morsels, bool) else []

    def __iter__(self):
        return iter(self._morsels)

    def update_cookies(self, *_, **__):  # type: ignore[no-untyped-def]
        return None


class _FakeSession:
    def __init__(self, *, response: _FakeResponse, jar=None) -> None:  # type: ignore[no-untyped-def]
        self._response = response
        self._jar = jar or _FakeJar()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def cookie_jar(self):  # type: ignore[no-untyped-def]
        return self._jar

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self._response

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        return self._response


def _morsel(name: str, value: str, **attrs):  # type: ignore[no-untyped-def]
    c = SimpleCookie()
    c[name] = value
    for k, v in attrs.items():
        c[name][k] = v
    return c[name]


def _make_jwt(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )
    return f"{header}.{payload}.sig"


@pytest.fixture
def patched_aiohttp(monkeypatch: pytest.MonkeyPatch):
    box: dict[str, Any] = {
        "response": _FakeResponse(status=200, json_body={"user": {"id": 1}}),
        "jar": _FakeJar(),
        "session": None,
    }

    def fake_client_session(*args: Any, **kwargs: Any) -> _FakeSession:
        sess = _FakeSession(response=box["response"], jar=box["jar"])
        box["session"] = sess
        return sess

    monkeypatch.setattr(vr_module.aiohttp, "ClientSession", fake_client_session)
    # Replace CookieJar with a permissive fake; some cookie shapes raise here.
    monkeypatch.setattr(vr_module.aiohttp, "CookieJar", _FakeJar)
    return box


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_bearer_context(
    target: str,
    agent_id: str,
    session_id: str,
    profile: str,
    *,
    token: str = "BEARER",
    final_url: str = "http://target/api/me",
    validation_url: str | None = None,
    refresh_url: str | None = None,
) -> AuthContextHandler:
    ctx = AuthContext(
        profile=profile,
        cookies=[CookieRecord(name="sid", value="v", domain="target", path="/")],
        headers={"Authorization": f"Bearer {token}"},
        browser_storage=StorageSnapshot(),
        metadata={
            "auth_flow": "json",
            "auth_type": "bearer_token",
            "final_url": final_url,
            "validation_url": validation_url,
            "refresh_url": refresh_url,
        },
    )
    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    handler.save_context(profile, ctx)
    return handler


# ---------------------------------------------------------------------------
# validate_auth_context_service
# ---------------------------------------------------------------------------


class TestValidateService:
    async def test_jwt_exp_shortcut_skips_network(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        expired_jwt = _make_jwt({"exp": int(time.time()) - 100})
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default", token=expired_jwt
        )

        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            validation_url="http://target/api/me",
        )
        assert result["success"] is False
        assert result["expired"] is True
        assert result["expired_reason"] == "jwt_exp"
        # No network call.
        assert patched_aiohttp["session"] is None
        # Metadata was persisted.
        ctx = handler.load_context("default")
        assert ctx is not None
        assert ctx.metadata["expired"] is True
        assert ctx.metadata["validated"] is False
        assert ctx.metadata["expired_reason"] == "jwt_exp"

    async def test_explicit_validation_url_wins(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OPAQUE",  # not a JWT - no shortcut
            final_url="http://target/should-not-be-used",
            validation_url="http://target/also-not-used",
        )
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"user": {"id": 7}}, url="http://target/api/me"
        )

        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            validation_url="http://target/api/me",
        )
        assert result["validated"] is True
        # Single probe to the EXPLICIT url.
        sess = patched_aiohttp["session"]
        assert sess is not None
        assert [c[1] for c in sess.calls] == ["http://target/api/me"]
        # AuthContext.headers were attached.
        _, _, kwargs = sess.calls[0]
        assert kwargs["headers"]["Authorization"] == "Bearer OPAQUE"

    async def test_falls_back_to_metadata_validation_url(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OPAQUE",
            final_url=None,  # type: ignore[arg-type]
            validation_url="http://target/api/me-from-metadata",
        )
        patched_aiohttp["response"] = _FakeResponse(status=200, json_body={})
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
        )
        sess = patched_aiohttp["session"]
        assert [c[1] for c in sess.calls] == ["http://target/api/me-from-metadata"]
        assert result["validation_url"] == "http://target/api/me-from-metadata"

    async def test_401_marks_expired(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default", token="OPAQUE"
        )
        patched_aiohttp["response"] = _FakeResponse(status=401, json_body={"error": "no"})
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            validation_url="http://target/api/me",
        )
        assert result["validated"] is False
        assert result["expired"] is True
        assert result["expired_reason"] == "http_401"
        # Persisted to disk.
        ctx = handler.load_context("default")
        assert ctx is not None
        assert ctx.metadata["expired"] is True
        assert ctx.metadata["last_validation_status"] == 401

    async def test_substring_check_can_invalidate_200(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        """When an app serves the login form at the protected URL with a 200 status,
        we should still detect the expiry via ``success_substring``."""
        _seed_bearer_context("http://target", "aid", "sid", "default", token="OPAQUE")
        patched_aiohttp["response"] = _FakeResponse(
            status=200, text_body="<html><body>Please sign in</body></html>",
            content_type="text/html",
        )
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            validation_url="http://target/dashboard",
            success_substring="Sign out",
        )
        assert result["validated"] is False
        assert result["expired_reason"] == "missing_substring"

    async def test_jsonpath_check_can_invalidate_200(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context("http://target", "aid", "sid", "default", token="OPAQUE")
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"ok": True}  # no user.id
        )
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            validation_url="http://target/api/me",
            success_jsonpath="user.id",
        )
        assert result["validated"] is False
        assert result["expired_reason"] == "missing_jsonpath"

    async def test_missing_validation_url_returns_error(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OPAQUE", final_url=None,  # type: ignore[arg-type]
        )
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
        )
        assert result["success"] is False
        assert "validation_url" in result["error"]
        assert patched_aiohttp["session"] is None

    async def test_missing_profile_returns_error(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        result = await vr_module.validate_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="ghost",
            validation_url="http://target/api/me",
        )
        assert result["success"] is False
        assert "ghost" in result["error"]


# ---------------------------------------------------------------------------
# refresh_auth_context_service
# ---------------------------------------------------------------------------


class TestRefreshService:
    async def test_refresh_updates_token_in_place(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OLD_TOKEN", refresh_url="http://target/api/refresh",
        )
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "NEW_TOKEN"}
        )
        result = await vr_module.refresh_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            refresh_body={"refresh_token": "{{refresh_token}}", "user": "{{username}}"},
        )
        assert result["success"] is True
        assert result["refreshed"] is True
        assert result["new_token_obtained"] is True
        ctx = handler.load_context("default")
        assert ctx is not None
        assert ctx.headers["Authorization"] == "Bearer NEW_TOKEN"
        assert ctx.metadata["validated"] is True
        assert ctx.metadata["expired"] is False
        assert ctx.metadata["last_refresh_status"] == 200

    async def test_refresh_uses_metadata_refresh_url_when_not_passed(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OLD", refresh_url="http://target/api/refresh-from-metadata",
        )
        patched_aiohttp["response"] = _FakeResponse(
            status=200, json_body={"access_token": "NEW"}
        )
        await vr_module.refresh_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            refresh_body={"refresh_token": "x"},
        )
        sess = patched_aiohttp["session"]
        assert [c[1] for c in sess.calls] == ["http://target/api/refresh-from-metadata"]

    async def test_refresh_failure_does_not_clobber_existing_token(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OLD_TOKEN", refresh_url="http://target/api/refresh",
        )
        patched_aiohttp["response"] = _FakeResponse(status=401, json_body={"error": "no"})
        result = await vr_module.refresh_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            refresh_body={"refresh_token": "x"},
        )
        assert result["success"] is False
        assert "401" in result["error"]
        ctx = handler.load_context("default")
        # Old token still on disk; metadata not flipped to validated=true.
        assert ctx is not None
        assert ctx.headers["Authorization"] == "Bearer OLD_TOKEN"
        assert ctx.metadata.get("last_refresh_status") is None

    async def test_refresh_without_url_anywhere_fails(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OLD", refresh_url=None,
        )
        result = await vr_module.refresh_auth_context_service(
            target="http://target",
            agent_id="aid",
            session_id="sid",
            profile="default",
            refresh_body={"refresh_token": "x"},
        )
        assert result["success"] is False
        assert "refresh_url" in result["error"]


# ---------------------------------------------------------------------------
# auto_validate_before_consume - the gate used by consumer tools
# ---------------------------------------------------------------------------


class TestAutoValidate:
    async def test_returns_none_when_skip_validation(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context("http://target", "aid", "sid", "default", token="OPAQUE")
        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="default", skip_validation=True,
        )
        assert out is None
        assert patched_aiohttp["session"] is None

    async def test_returns_none_when_no_saved_context(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        # Caller will report "no auth context" on its own; the gate is a no-op.
        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="ghost",
        )
        assert out is None
        assert patched_aiohttp["session"] is None

    async def test_jwt_exp_shortcut_blocks_consume(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        expired_jwt = _make_jwt({"exp": int(time.time()) - 100})
        _seed_bearer_context(
            "http://target", "aid", "sid", "default", token=expired_jwt,
        )
        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="default",
        )
        assert out is not None
        assert out["validated"] is False
        assert out["expired"] is True
        assert out["expired_reason"] == "jwt_exp"
        # JWT shortcut is local: no network.
        assert patched_aiohttp["session"] is None

    async def test_ttl_cache_skips_probe(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default", token="OPAQUE",
        )
        # Pre-mark the context as validated 1 second ago.
        ctx = handler.load_context("default")
        assert ctx is not None
        ctx.metadata.update(
            {
                "validated": True,
                "last_validated_at": vr_module._now_iso(),
                "last_validation_status": 200,
            }
        )
        handler.save_context("default", ctx)

        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="default", validation_ttl_s=60.0,
        )
        assert out is None
        # Network was NOT touched because TTL was honoured.
        assert patched_aiohttp["session"] is None

    async def test_force_validate_ignores_ttl(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        handler = _seed_bearer_context(
            "http://target", "aid", "sid", "default", token="OPAQUE",
            validation_url="http://target/api/me",
        )
        ctx = handler.load_context("default")
        assert ctx is not None
        ctx.metadata.update(
            {
                "validated": True,
                "last_validated_at": vr_module._now_iso(),
                "last_validation_status": 200,
            }
        )
        handler.save_context("default", ctx)
        patched_aiohttp["response"] = _FakeResponse(status=200, json_body={"ok": True})

        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="default", force_validate=True,
        )
        # Validation succeeded -> None
        assert out is None
        # But the network WAS hit despite the cache.
        assert patched_aiohttp["session"] is not None
        assert [c[1] for c in patched_aiohttp["session"].calls] == [
            "http://target/api/me"
        ]

    async def test_probe_failure_bubbles_up(
        self,
        isolated_deadend_root: Path,
        patched_aiohttp: dict[str, Any],
    ) -> None:
        _seed_bearer_context(
            "http://target", "aid", "sid", "default",
            token="OPAQUE", validation_url="http://target/api/me",
        )
        patched_aiohttp["response"] = _FakeResponse(status=401, json_body={"error": "no"})

        out = await vr_module.auto_validate_before_consume(
            target="http://target", agent_id="aid", session_id="sid",
            profile="default",
        )
        assert out is not None
        assert out["validated"] is False
        assert out["expired"] is True
        assert out["expired_reason"] == "http_401"
