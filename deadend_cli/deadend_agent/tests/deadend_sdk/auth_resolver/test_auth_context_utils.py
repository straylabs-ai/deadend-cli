# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``auth_context_utils`` conversion helpers.

Validates:

* ``auth_context_from_browser_state`` derives bearer/api-key headers from
  common storage token names without leaking values into metadata.
* ``browser_state_from_auth_context`` is a faithful inverse for cookies and
  storage so ``BrowserSession.import_state`` can re-hydrate the session.
* ``playwright_storage_state_from_auth_context`` produces Playwright's
  expected ``cookies`` + ``origins[].localStorage`` shape and strips CDP-only
  read-only fields (``size``, ``session``, ``sourcePort``, ...).
* ``cookie_header_from_auth_context`` filters cookies by host correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deadend_agent.auth_resolver import (
    AuthContext,
    CookieRecord,
    StorageSnapshot,
    auth_context_from_browser_state,
    browser_state_from_auth_context,
    cookie_header_from_auth_context,
    playwright_storage_state_from_auth_context,
    write_playwright_storage_state,
)
from deadend_agent.auth_resolver.auth_context_utils import derive_headers_from_storage


TARGET = "http://localhost:8080"


class TestAuthContextFromBrowserState:
    def test_includes_cookies_storage_and_safe_metadata(
        self, fake_browser_state: dict
    ) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state=fake_browser_state,
            auth_url="http://localhost:8080/login",
            auth_flow="form",
            auth_type="session_cookie",
        )
        # Cookies are recorded with their values (real material lives on disk).
        names = sorted(c.name for c in ctx.cookies)
        assert names == ["csrftoken", "sessionid"]
        sessionid = next(c for c in ctx.cookies if c.name == "sessionid")
        assert sessionid.value == "REAL_SESSION_VALUE"
        # Storage is preserved verbatim.
        assert ctx.browser_storage.localStorage["access_token"] == "REAL_BEARER_TOKEN"
        assert ctx.browser_storage.sessionStorage["csrf"] == "REAL_CSRF"
        # Metadata is structured + secret-free.
        meta = ctx.metadata
        assert meta["target"] == TARGET
        assert meta["target_slug"] == "localhost_8080"
        assert meta["agent_id"] == "aid"
        assert meta["session_id"] == "sid"
        assert meta["auth_flow"] == "form"
        assert meta["auth_type"] == "session_cookie"
        assert meta["final_url"] == "http://localhost:8080/dashboard"
        assert meta["cookies_count"] == 2
        assert sorted(meta["cookie_names"]) == ["csrftoken", "sessionid"]
        assert sorted(meta["storage_keys"]) == sorted(
            ["access_token", "feature_flag", "csrf"]
        )
        assert meta["headers_available"] == ["Authorization"]
        # Metadata must NOT carry the actual secret values.
        rendered_meta = json.dumps(meta)
        assert "REAL_BEARER_TOKEN" not in rendered_meta
        assert "REAL_SESSION_VALUE" not in rendered_meta

    def test_derives_authorization_header_from_access_token(self) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state={
                "cookies": [],
                "localStorage": {"access_token": "JWT.HEADER.PAYLOAD"},
                "sessionStorage": {},
                "url": TARGET,
                "title": "",
            },
        )
        assert ctx.headers == {"Authorization": "Bearer JWT.HEADER.PAYLOAD"}

    def test_does_not_double_prefix_existing_bearer(self) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state={
                "cookies": [],
                "localStorage": {"access_token": "Bearer ALREADY_PREFIXED"},
                "sessionStorage": {},
                "url": TARGET,
                "title": "",
            },
        )
        assert ctx.headers == {"Authorization": "Bearer ALREADY_PREFIXED"}

    def test_derives_api_key_header(self) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state={
                "cookies": [],
                "localStorage": {"api_key": "K123"},
                "sessionStorage": {},
                "url": TARGET,
                "title": "",
            },
        )
        assert ctx.headers == {"X-API-Key": "K123"}

    def test_ignores_unrelated_storage_keys(self) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state={
                "cookies": [],
                "localStorage": {"theme": "dark", "lang": "en"},
                "sessionStorage": {},
                "url": TARGET,
                "title": "",
            },
        )
        assert ctx.headers == {}

    def test_skips_cookies_without_name(self) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state={
                "cookies": [
                    {"value": "no-name"},
                    {"name": "sessionid", "value": "v", "domain": "localhost", "path": "/"},
                ],
                "localStorage": {},
                "sessionStorage": {},
                "url": TARGET,
                "title": "",
            },
        )
        assert [c.name for c in ctx.cookies] == ["sessionid"]


class TestDeriveHeadersFromStorage:
    @pytest.mark.parametrize(
        "key",
        ["access_token", "accessToken", "auth_token", "jwt", "token", "id_token"],
    )
    def test_recognised_token_keys(self, key: str) -> None:
        assert derive_headers_from_storage({key: "X"}) == {"Authorization": "Bearer X"}

    @pytest.mark.parametrize("key", ["api_key", "apiKey", "X-API-Key"])
    def test_recognised_api_key_keys(self, key: str) -> None:
        assert derive_headers_from_storage({key: "X"}) == {"X-API-Key": "X"}

    def test_session_storage_also_considered(self) -> None:
        assert derive_headers_from_storage(None, {"id_token": "ID"}) == {
            "Authorization": "Bearer ID"
        }

    def test_empty_values_are_ignored(self) -> None:
        assert derive_headers_from_storage({"access_token": "", "api_key": None}) == {}


class TestBrowserStateFromAuthContext:
    def test_round_trip_preserves_cookies_and_storage(
        self, fake_browser_state: dict
    ) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state=fake_browser_state,
        )
        state = browser_state_from_auth_context(ctx)
        # Cookies preserved with values for set_cookies.
        sessionid = next(c for c in state["cookies"] if c["name"] == "sessionid")
        assert sessionid["value"] == "REAL_SESSION_VALUE"
        assert sessionid["domain"] == "localhost"
        assert sessionid["path"] == "/"
        # localStorage / sessionStorage preserved verbatim.
        assert state["localStorage"] == fake_browser_state["localStorage"]
        assert state["sessionStorage"] == fake_browser_state["sessionStorage"]
        # final_url surfaced for callers that want to revisit.
        assert state["url"] == "http://localhost:8080/dashboard"


class TestPlaywrightStorageState:
    def test_origin_uses_target_scheme_host_port(self, fake_browser_state: dict) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state=fake_browser_state,
        )
        state = playwright_storage_state_from_auth_context(ctx, target=TARGET)
        assert state["origins"][0]["origin"] == "http://localhost:8080"
        names = {item["name"] for item in state["origins"][0]["localStorage"]}
        assert names == {"access_token", "feature_flag"}

    def test_strips_cdp_only_cookie_fields(self, fake_browser_state: dict) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state=fake_browser_state,
        )
        state = playwright_storage_state_from_auth_context(ctx, target=TARGET)
        for cookie in state["cookies"]:
            for forbidden in (
                "size",
                "session",
                "priority",
                "sameParty",
                "sourceScheme",
                "sourcePort",
                "partitionKey",
            ):
                assert forbidden not in cookie

    def test_write_creates_file_with_expected_shape(
        self, tmp_path: Path, fake_browser_state: dict
    ) -> None:
        ctx = auth_context_from_browser_state(
            profile="default",
            target=TARGET,
            agent_id="aid",
            session_id="sid",
            state=fake_browser_state,
        )
        path = tmp_path / "nested" / "default.playwright.json"
        write_playwright_storage_state(ctx, path, target=TARGET)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert "cookies" in loaded
        assert "origins" in loaded


class TestCookieHeaderFromAuthContext:
    def test_filters_to_target_host(self) -> None:
        ctx = AuthContext(
            profile="default",
            cookies=[
                CookieRecord(name="a", value="1", domain="localhost", path="/"),
                CookieRecord(name="b", value="2", domain="other.test", path="/"),
                CookieRecord(name="c", value="3", domain=".localhost", path="/"),
            ],
            headers={},
            browser_storage=StorageSnapshot(),
            metadata={"target": TARGET},
        )
        header = cookie_header_from_auth_context(ctx, target=TARGET)
        # Order is preserved as iterated; just check membership.
        parts = set(header.split("; "))
        assert "a=1" in parts
        assert "c=3" in parts
        assert "b=2" not in parts
