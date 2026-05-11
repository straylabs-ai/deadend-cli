# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for tools that *consume* a saved AuthContext via ``auth_profile``.

We avoid launching a real browser by monkey-patching ``BrowserSession`` inside
``run_browser_steps_tool`` to a recorder that captures whether ``import_state``
was called and with what payload.
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
    auth_context_from_browser_state,
)
from deadend_agent.auth_resolver.auth_resolver import CookieRecord, StorageSnapshot, AuthContext
from deadend_agent.tools.browser import run_browser_steps_tool
from deadend_agent.tools.browser.run_browser_steps_tool import (
    browser_run_steps,
    run_browser_steps,
)
from deadend_agent.tools.python_interpreter import read_auth_storage


class _RecordingBrowser:
    """Minimal ``BrowserSession`` stand-in that records the calls a test cares about."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.imported_state: dict[str, Any] | None = None
        self.goto_calls: list[str] = []
        self.steps_calls: list[Any] = []

    async def __aenter__(self) -> "_RecordingBrowser":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def goto(self, url: str, *, timeout_ms: float | None = None) -> None:
        self.goto_calls.append(url)

    async def import_state(self, state: dict[str, Any]) -> None:
        self.imported_state = state

    async def run_steps(
        self,
        steps,
        context,
        *,
        optional_keys: bool = False,
        timeout_ms: float | None = None,
    ) -> None:
        self.steps_calls.append((list(steps), dict(context)))

    async def get_url(self) -> str:
        return "http://localhost:8080/dashboard"

    async def get_title(self) -> str:
        return "Dashboard"


class _FakeCtx:
    def __init__(self, deps: Any) -> None:
        self.deps = deps


def _seed_auth_context(
    isolated_root: Path, target: str, agent_id: str, session_id: str, profile: str
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


@pytest.fixture
def patched_browser_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch BrowserSession to the recorder. Returns a dict whose ``last`` key
    points at the most recently constructed recorder."""
    captured: dict[str, Any] = {"last": None}

    def factory(*args: Any, **kwargs: Any) -> _RecordingBrowser:
        instance = _RecordingBrowser(*args, **kwargs)
        captured["last"] = instance
        return instance

    monkeypatch.setattr(run_browser_steps_tool, "BrowserSession", factory)
    return captured


class TestRunBrowserStepsAuthProfile:
    """``run_browser_steps`` (the internal helper) should import auth_state and
    revisit the URL so the app boots authenticated."""

    pytestmark = pytest.mark.asyncio

    async def test_authenticated_run_imports_state_and_revisits(
        self,
        isolated_deadend_root: Path,
        patched_browser_session: dict[str, Any],
    ) -> None:
        auth_state = {
            "cookies": [{"name": "sessionid", "value": "v"}],
            "localStorage": {"access_token": "TOK"},
            "sessionStorage": {},
            "url": "http://localhost:8080/dashboard",
            "title": "Dashboard",
        }
        result = await run_browser_steps(
            page_url="http://localhost:8080/protected",
            context={},
            steps=[],
            auth_state=auth_state,
            auth_profile="default",
        )
        assert result["success"] is True
        assert result["authenticated"] is True
        assert result["auth_profile"] == "default"
        recorder = patched_browser_session["last"]
        assert recorder is not None
        assert recorder.imported_state == auth_state
        # Goto called twice: once before import, once after to apply auth.
        assert recorder.goto_calls == [
            "http://localhost:8080/protected",
            "http://localhost:8080/protected",
        ]

    async def test_unauthenticated_run_does_not_import_state(
        self,
        isolated_deadend_root: Path,
        patched_browser_session: dict[str, Any],
    ) -> None:
        result = await run_browser_steps(
            page_url="http://localhost:8080/",
            context={},
            steps=[],
        )
        assert result["success"] is True
        assert result["authenticated"] is False
        assert result["auth_profile"] is None
        recorder = patched_browser_session["last"]
        assert recorder.imported_state is None
        assert recorder.goto_calls == ["http://localhost:8080/"]


class TestBrowserRunStepsToolAuthProfile:
    """The pydantic-ai tool wrapper should resolve the profile via
    ``AuthContextHandler`` and feed ``run_browser_steps`` with the right state.
    Missing profiles must produce a structured error rather than crash."""

    pytestmark = pytest.mark.asyncio

    async def test_missing_profile_returns_structured_error(
        self,
        isolated_deadend_root: Path,
        patched_browser_session: dict[str, Any],
    ) -> None:
        deps = SimpleNamespace(
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            proxy_url=None,
        )
        result = await browser_run_steps(
            ctx=_FakeCtx(deps),
            page_url="http://localhost:8080",
            steps=[],
            context={},
            auth_profile="ghost",
        )
        assert result["success"] is False
        assert result["authenticated"] is False
        assert result["auth_profile"] == "ghost"
        assert "ghost" in result["error"]
        # No browser session was created for the failure path.
        assert patched_browser_session["last"] is None

    async def test_missing_session_id_returns_structured_error(
        self, isolated_deadend_root: Path, patched_browser_session: dict[str, Any]
    ) -> None:
        deps = SimpleNamespace(
            target="http://localhost:8080",
            agent_id="aid",
            session_id=None,
            proxy_url=None,
        )
        result = await browser_run_steps(
            ctx=_FakeCtx(deps),
            page_url="http://localhost:8080",
            steps=[],
            context={},
            auth_profile="default",
        )
        assert result["success"] is False
        assert "session_id" in result["error"]

    async def test_existing_profile_loads_state_into_browser(
        self, isolated_deadend_root: Path, patched_browser_session: dict[str, Any]
    ) -> None:
        target = "http://localhost:8080"
        _seed_auth_context(isolated_deadend_root, target, "aid", "sid", "default")

        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        result = await browser_run_steps(
            ctx=_FakeCtx(deps),
            page_url=f"{target}/protected",
            steps=[],
            context={},
            auth_profile="default",
            # Skip auto-validation — we are not testing Phase 13 here, just the
            # state-import path.
            skip_auth_validation=True,
        )
        assert result["success"] is True
        assert result["authenticated"] is True
        assert result["auth_profile"] == "default"
        recorder = patched_browser_session["last"]
        assert recorder.imported_state is not None
        # Cookies reach the browser session as a list of dicts...
        cookie_names = {c["name"] for c in recorder.imported_state["cookies"]}
        assert cookie_names == {"sessionid"}
        # ...and storage values are forwarded for re-import.
        assert recorder.imported_state["localStorage"] == {"access_token": "TOK"}

    async def test_expired_jwt_blocks_consume_and_returns_hint(
        self, isolated_deadend_root: Path, patched_browser_session: dict[str, Any]
    ) -> None:
        """Phase 13 auto-validation: an expired JWT must short-circuit before
        any browser session is created and must include a hint pointing at
        ``refresh_auth_context`` / ``authenticate`` so the LLM knows what to
        do next."""
        target = "http://localhost:8080"
        # Build an expired-JWT AuthContext directly.
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
                "final_url": f"{target}/dashboard",
            },
        )
        AuthContextHandler(target=target, agent_id="aid", session_id="sid").save_context(
            "default", ctx
        )

        deps = SimpleNamespace(
            target=target, agent_id="aid", session_id="sid", proxy_url=None
        )
        result = await browser_run_steps(
            ctx=_FakeCtx(deps),
            page_url=f"{target}/protected",
            steps=[],
            context={},
            auth_profile="default",
        )
        assert result["success"] is False
        assert result["authenticated"] is False
        assert result["expired"] is True
        assert result["expired_reason"] == "jwt_exp"
        assert "refresh_auth_context" in result["hint"]
        # No browser was created.
        assert patched_browser_session["last"] is None


class TestReadAuthStorage:
    """``read_auth_storage`` should default to a *safe* summary and only return
    raw secrets when explicitly requested."""

    pytestmark = pytest.mark.asyncio

    async def test_safe_summary_by_default(
        self, isolated_deadend_root: Path
    ) -> None:
        target = "http://localhost:8080"
        _seed_auth_context(isolated_deadend_root, target, "aid", "sid", "default")

        ctx = _FakeCtx(
            SimpleNamespace(target=target, agent_id="aid", session_id="sid")
        )
        result_json = await read_auth_storage(ctx, profile="default")
        result = json.loads(result_json)
        assert result["available"] is True
        assert result["profile"] == "default"
        assert result["target"] == target
        assert result["cookie_names"] == ["sessionid"]
        assert result["storage_keys"] == ["access_token"]
        assert result["headers_available"] == ["Authorization"]
        # No raw secret material.
        assert "TOK" not in result_json or "TOK" in {
            k for k in result["cookie_names"] + result["storage_keys"]
        } and "Bearer" not in result_json
        # Strict check: the raw token should not appear as a value anywhere in
        # the safe summary (it appears only in derived names).
        assert "Bearer TOK" not in result_json

    async def test_include_secrets_returns_full_context(
        self, isolated_deadend_root: Path
    ) -> None:
        target = "http://localhost:8080"
        _seed_auth_context(isolated_deadend_root, target, "aid", "sid", "default")

        ctx = _FakeCtx(
            SimpleNamespace(target=target, agent_id="aid", session_id="sid")
        )
        raw = await read_auth_storage(ctx, profile="default", include_secrets=True)
        # Now we expect the actual secret material.
        assert "Bearer TOK" in raw
        assert "access_token" in raw
        assert "sessionid" in raw

    async def test_missing_profile_reports_unavailable(
        self, isolated_deadend_root: Path
    ) -> None:
        ctx = _FakeCtx(
            SimpleNamespace(
                target="http://localhost:8080", agent_id="aid", session_id="sid"
            )
        )
        result = json.loads(await read_auth_storage(ctx, profile="ghost"))
        assert result["available"] is False
        assert result["profile"] == "ghost"

    async def test_legacy_string_ctx_does_not_crash(self) -> None:
        # Legacy callers passed a session_id string; the function should
        # respond gracefully instead of raising.
        result = json.loads(await read_auth_storage("legacy-session"))
        assert result["available"] is False
