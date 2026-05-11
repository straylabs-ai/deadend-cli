# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``pw_send_payload(auth_profile=...)`` Playwright-storage routing.

We patch ``PlaywrightSessionManager.get_session`` to a recorder so no real
browser is launched. The goal is to verify that:

* When ``auth_profile`` is set, the tool resolves the saved AuthContext via
  ``AuthContextHandler`` and writes ``<profile>.playwright.json`` next to it.
* The recorded ``get_session`` call carries the right
  ``auth_storage_state_path`` and ``auth_profile`` arguments.
* Missing profile / missing IDs return clean error strings instead of crashing.
* ``index.json`` is the manifest, NOT a Playwright storage state file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import base64
import time as _time

from deadend_agent.auth_resolver import (
    AuthContextHandler,
    auth_context_from_api_response,
    auth_context_from_browser_state,
)
from deadend_agent.auth_resolver.auth_resolver import AuthContext, CookieRecord, StorageSnapshot
from deadend_agent.tools import browser_automation as ba_pkg


class _FakeCtx:
    def __init__(self, deps: Any) -> None:
        self.deps = deps


class _RecordingPwSession:
    """Stand-in for a ``PlaywrightRequester`` instance — only what the test path
    actually invokes. Captures the request payload sent to ``send_raw_data``."""

    last_request_data: dict[str, str] = {}

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        # Each instance writes through to the class attribute so tests can
        # introspect what got sent regardless of which session object the
        # session manager handed back.
        type(self).last_request_data = {}

    async def send_raw_data(self, **kwargs: Any):  # pragma: no cover - generator skipped
        type(self).last_request_data = dict(kwargs)
        if False:
            yield b""
        return


@pytest.fixture
def recording_session_manager(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``PlaywrightSessionManager.get_session`` with a recorder."""
    captured: dict[str, Any] = {"calls": [], "sessions": []}

    async def fake_get_session(**kwargs: Any) -> _RecordingPwSession:
        sess = _RecordingPwSession()
        captured["calls"].append(kwargs)
        captured["sessions"].append(sess)
        return sess

    monkeypatch.setattr(
        ba_pkg.PlaywrightSessionManager, "get_session", staticmethod(fake_get_session)
    )
    return captured


def _seed_auth_context(
    target: str, agent_id: str, session_id: str, profile: str
) -> AuthContextHandler:
    state = {
        "cookies": [
            {"name": "sessionid", "value": "v", "domain": "localhost", "path": "/"},
        ],
        "localStorage": {"access_token": "TOK"},
        "sessionStorage": {},
        "url": f"{target}/dashboard",
        "title": "Dashboard",
    }
    ctx = auth_context_from_browser_state(
        profile=profile,
        target=target,
        agent_id=agent_id,
        session_id=session_id,
        state=state,
        auth_url=f"{target}/login",
        auth_flow="form",
        auth_type="session_cookie",
    )
    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    handler.save_context(profile, ctx)
    return handler


_RAW_REQUEST = (
    "GET /api/me HTTP/1.1\r\n"
    "Host: localhost:8080\r\n"
    "User-Agent: TestAgent/1.0\r\n"
    "\r\n"
)


class TestPwSendPayloadAuthProfile:
    pytestmark = pytest.mark.asyncio

    async def test_existing_profile_writes_playwright_state_and_passes_path(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        target = "http://localhost:8080"
        handler = _seed_auth_context(target, "aid", "sid", "default")
        # Pre-condition: only profile + manifest exist; no .playwright.json yet.
        assert not handler.playwright_storage_path("default").exists()

        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        result = await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host=target,
            raw_request=_RAW_REQUEST,
            verify_ssl=False,
            auth_profile="default",
            skip_auth_validation=True,
        )
        # tool returns the (empty) responses list as a string here; what we
        # really check is the Playwright manager call.
        assert isinstance(result, str)

        # The Playwright storage state file has been materialised on disk and
        # is a valid Playwright shape (cookies + origins).
        pw_path = handler.playwright_storage_path("default")
        assert pw_path.exists()
        loaded = json.loads(pw_path.read_text())
        assert "cookies" in loaded
        assert "origins" in loaded
        names = {item["name"] for item in loaded["origins"][0]["localStorage"]}
        assert "access_token" in names
        # And the path was passed into ``get_session``.
        calls = recording_session_manager["calls"]
        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["auth_storage_state_path"] == str(pw_path)
        assert kwargs["auth_profile"] == "default"
        assert kwargs["session_key"] == "sid"
        assert kwargs["agent_id"] == "aid"

    async def test_index_json_is_manifest_not_playwright_state(
        self, isolated_deadend_root: Path
    ) -> None:
        target = "http://localhost:8080"
        handler = _seed_auth_context(target, "aid", "sid", "default")
        index_file = handler._auth_dir / "index.json"
        assert index_file.exists()
        manifest = json.loads(index_file.read_text())
        # Manifest schema, not Playwright schema.
        assert "default" in manifest
        assert "cookies" not in manifest
        assert "origins" not in manifest

    async def test_missing_profile_returns_error_string(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        deps = SimpleNamespace(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            proxy_url=None,
        )
        result = await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host="http://localhost:8080",
            raw_request=_RAW_REQUEST,
            auth_profile="ghost",
        )
        assert isinstance(result, str)
        assert result.startswith("Error")
        assert "ghost" in result
        # No Playwright session created for the failure path.
        assert recording_session_manager["calls"] == []

    async def test_missing_ids_returns_error_string(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        deps = SimpleNamespace(
            target="http://localhost:8080",
            agent_id=None,
            session_id=None,
            proxy_url=None,
        )
        result = await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host="http://localhost:8080",
            raw_request=_RAW_REQUEST,
            auth_profile="default",
        )
        assert isinstance(result, str)
        assert result.startswith("Error")
        assert "agent_id" in result and "session_id" in result
        assert recording_session_manager["calls"] == []

    async def test_json_auth_context_injects_authorization_header(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        """Phase 12: a JSON-derived AuthContext stores ``AuthContext.headers``
        but no localStorage. ``pw_send_payload(auth_profile=...)`` MUST inject
        those headers into the raw request so the bearer token actually
        reaches the wire."""
        target = "http://localhost:8080"
        # Seed a JSON-style AuthContext: headers only, no browser storage.
        ctx = auth_context_from_api_response(
            profile="default",
            target=target,
            agent_id="aid",
            session_id="sid",
            token="JWT_TOKEN",
            cookies=[],
            final_url=f"{target}/me",
            auth_flow="json",
            auth_type="bearer_token",
        )
        handler = AuthContextHandler(target=target, agent_id="aid", session_id="sid")
        handler.save_context("default", ctx)

        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host=target,
            raw_request=_RAW_REQUEST,
            auth_profile="default",
            skip_auth_validation=True,
        )
        # The recording session captured the raw request that was sent.
        sent = _RecordingPwSession.last_request_data.get("request_data", "")
        assert "Authorization: Bearer JWT_TOKEN" in sent

    async def test_explicit_authorization_header_wins_over_saved_one(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        """Header injection must NOT clobber an explicit Authorization header
        that the LLM provided in the raw request — e.g. when testing token
        substitution / privilege escalation."""
        target = "http://localhost:8080"
        ctx = auth_context_from_api_response(
            profile="default",
            target=target,
            agent_id="aid",
            session_id="sid",
            token="SAVED_TOKEN",
            cookies=[],
            auth_flow="json",
            auth_type="bearer_token",
        )
        AuthContextHandler(target=target, agent_id="aid", session_id="sid").save_context(
            "default", ctx
        )
        raw_with_explicit_auth = (
            "GET /api/me HTTP/1.1\r\n"
            "Host: localhost:8080\r\n"
            "Authorization: Bearer ATTACKER_TOKEN\r\n"
            "User-Agent: TestAgent/1.0\r\n"
            "\r\n"
        )
        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host=target,
            raw_request=raw_with_explicit_auth,
            auth_profile="default",
            skip_auth_validation=True,
        )
        sent = _RecordingPwSession.last_request_data.get("request_data", "")
        assert "Authorization: Bearer ATTACKER_TOKEN" in sent
        assert "SAVED_TOKEN" not in sent

    async def test_expired_jwt_blocks_pw_send_payload(
        self,
        isolated_deadend_root: Path,
        recording_session_manager: dict[str, Any],
    ) -> None:
        """Phase 13: pw_send_payload must refuse to send when the saved
        AuthContext is locally-detectable as expired (JWT past ``exp``)."""
        target = "http://localhost:8080"
        header_b64 = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(
            f'{{"exp":{int(_time.time()) - 100}}}'.encode()
        ).rstrip(b"=").decode()
        jwt = f"{header_b64}.{payload_b64}.sig"
        ctx = AuthContext(
            profile="default",
            cookies=[CookieRecord(name="sid", value="v", domain="localhost", path="/")],
            headers={"Authorization": f"Bearer {jwt}"},
            browser_storage=StorageSnapshot(),
            metadata={
                "auth_flow": "json",
                "auth_type": "bearer_token",
                "final_url": f"{target}/api/me",
            },
        )
        AuthContextHandler(target=target, agent_id="aid", session_id="sid").save_context(
            "default", ctx
        )

        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        result = await ba_pkg.pw_send_payload(
            ctx=_FakeCtx(deps),
            target_host=target,
            raw_request=_RAW_REQUEST,
            auth_profile="default",
        )
        assert isinstance(result, str)
        assert result.startswith("Error")
        assert "no longer valid" in result
        assert "jwt_exp" in result
        # No Playwright session was created.
        assert recording_session_manager["calls"] == []
