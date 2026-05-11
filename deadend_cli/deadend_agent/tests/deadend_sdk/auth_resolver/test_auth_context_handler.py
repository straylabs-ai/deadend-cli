# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``AuthContextHandler`` storage layout and manifest behaviour.

Validates:

* Disk layout is ``<DEADEND_AGENTS_PATH>/<agent_id>/<session_id>/auth_context/``
* ``index.json`` is the manifest only; ``<profile>.json`` holds the AuthContext;
  ``<profile>.playwright.json`` holds the Playwright storage state.
* ``target_slug`` is stored as metadata, never as a path component.
* Safe summaries never expose secrets.
* Profile deletion removes both the AuthContext and Playwright files.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from deadend_agent.auth_resolver import (
    AuthContext,
    AuthContextHandler,
    CookieRecord,
    StorageSnapshot,
    auth_context_from_browser_state,
    safe_auth_summary,
    write_playwright_storage_state,
)


TARGET = "http://localhost:8080"


class TestAuthContextHandlerLayout:
    def test_disk_layout_uses_agent_id_and_session_id(
        self, isolated_deadend_root: Path
    ) -> None:
        agent_id = uuid.uuid4()
        session_id = uuid.uuid4()
        handler = AuthContextHandler(
            target=TARGET, agent_id=agent_id, session_id=session_id
        )
        expected = (
            isolated_deadend_root / str(agent_id) / str(session_id) / "auth_context"
        )
        assert handler._auth_dir == expected
        assert expected.exists(), "auth_context directory should be created on init"

    def test_target_slug_is_metadata_not_path(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(
            target="http://example.com:3000/app",
            agent_id="aid",
            session_id="sid",
        )
        # target_slug is stored on the handler...
        assert handler.target_slug == "example.com_3000"
        # ...but the path does NOT include it.
        assert "example.com_3000" not in str(handler._auth_dir)
        assert handler._auth_dir == (
            isolated_deadend_root / "aid" / "sid" / "auth_context"
        )

    def test_playwright_storage_path_is_profile_scoped(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        path = handler.playwright_storage_path("default")
        assert path.parent == handler._auth_dir
        assert path.name == "default.playwright.json"

    def test_playwright_storage_path_sanitises_profile_name(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        # Slashes and spaces are not allowed; the handler must produce a safe filename.
        unsafe = handler.playwright_storage_path("../../etc/passwd")
        assert "/" not in unsafe.name and "\\" not in unsafe.name
        assert unsafe.parent == handler._auth_dir


class TestAuthContextHandlerSaveLoad:
    def _build_ctx(
        self,
        agent_id: str = "aid",
        session_id: str = "sid",
        token: str = "REAL_TOKEN",
        cookie_value: str = "REAL_COOKIE",
    ) -> AuthContext:
        return AuthContext(
            profile="default",
            cookies=[
                CookieRecord(name="sessionid", value=cookie_value, domain="localhost", path="/"),
            ],
            headers={"Authorization": f"Bearer {token}"},
            browser_storage=StorageSnapshot(
                localStorage={"access_token": token, "feature": "on"},
                sessionStorage={"csrf": "REAL_CSRF"},
            ),
            metadata={
                "auth_flow": "form",
                "auth_type": "session_cookie",
                "auth_url": "http://localhost:8080/login",
                "final_url": "http://localhost:8080/dashboard",
            },
        )

    def test_save_writes_profile_file_and_index(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        ctx = self._build_ctx()
        handler.save_context("default", ctx)

        profile_file = handler._auth_dir / "default.json"
        index_file = handler._auth_dir / "index.json"

        assert profile_file.exists()
        assert index_file.exists()
        # ``index.json`` is a manifest, not a Playwright storage state file.
        manifest = json.loads(index_file.read_text())
        assert "default" in manifest
        entry = manifest["default"]
        assert entry["target"] == TARGET
        assert entry["target_slug"] == "localhost_8080"
        assert entry["agent_id"] == "aid"
        assert entry["session_id"] == "sid"
        assert entry["profile"] == "default"
        assert entry["auth_flow"] == "form"
        assert entry["auth_type"] == "session_cookie"
        assert entry["cookies_count"] == 1
        assert entry["headers_available"] == ["Authorization"]
        assert sorted(entry["storage_keys"]) == sorted(
            ["access_token", "feature", "csrf"]
        )
        # The path entry must point at the profile file itself.
        assert entry["path"] == str(profile_file)

    def test_load_round_trip(self, isolated_deadend_root: Path) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        ctx = self._build_ctx(token="ROUND_TRIP_TOKEN")
        handler.save_context("default", ctx)

        loaded = handler.load_context("default")
        assert loaded is not None
        assert loaded.profile == "default"
        assert loaded.headers == {"Authorization": "Bearer ROUND_TRIP_TOKEN"}
        assert loaded.browser_storage.localStorage["access_token"] == "ROUND_TRIP_TOKEN"
        # Persistence injects target / agent_id / session_id into metadata.
        assert loaded.metadata["target"] == TARGET
        assert loaded.metadata["target_slug"] == "localhost_8080"
        assert loaded.metadata["agent_id"] == "aid"
        assert loaded.metadata["session_id"] == "sid"

    def test_load_missing_profile_returns_none(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        assert handler.load_context("does-not-exist") is None

    def test_list_profiles_only_returns_saved_profiles(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        handler.save_context("default", self._build_ctx())
        handler.save_context("admin", self._build_ctx(token="ADMIN_TOKEN"))
        assert sorted(handler.list_profiles()) == ["admin", "default"]

    def test_delete_profile_removes_profile_and_playwright_files(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        ctx = self._build_ctx()
        handler.save_context("default", ctx)
        # Materialise the playwright storage file too.
        write_playwright_storage_state(
            ctx, handler.playwright_storage_path("default"), target=TARGET
        )

        profile_file = handler._auth_dir / "default.json"
        playwright_file = handler.playwright_storage_path("default")
        assert profile_file.exists()
        assert playwright_file.exists()

        removed = handler.delete_profile("default")
        assert removed is True
        assert not profile_file.exists()
        assert not playwright_file.exists()
        assert "default" not in handler._index


class TestSafeSummary:
    """The summary surfaced to LLM/agent context must never leak secrets."""

    def test_summarize_context_redacts_secrets(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        secret_token = "VERY_SECRET_TOKEN"
        secret_cookie = "VERY_SECRET_COOKIE"
        ctx = AuthContext(
            profile="default",
            cookies=[
                CookieRecord(
                    name="sessionid", value=secret_cookie, domain="localhost", path="/"
                )
            ],
            headers={"Authorization": f"Bearer {secret_token}"},
            browser_storage=StorageSnapshot(
                localStorage={"access_token": secret_token},
                sessionStorage={},
            ),
            metadata={"auth_flow": "form", "auth_type": "session_cookie"},
        )
        handler.save_context("default", ctx)

        summary = handler.summarize_context("default")
        rendered = json.dumps(summary)
        assert summary["available"] is True
        assert summary["cookie_names"] == ["sessionid"]
        assert summary["storage_keys"] == ["access_token"]
        assert summary["headers_available"] == ["Authorization"]
        assert secret_token not in rendered
        assert secret_cookie not in rendered

    def test_summarize_missing_profile_is_safe(
        self, isolated_deadend_root: Path
    ) -> None:
        handler = AuthContextHandler(target=TARGET, agent_id="aid", session_id="sid")
        summary = handler.summarize_context("ghost")
        assert summary["available"] is False
        assert summary["profile"] == "ghost"
        assert summary["target"] == TARGET

    def test_safe_auth_summary_helper_matches_schema(
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
        summary = safe_auth_summary(ctx)
        # All expected keys present, no secrets.
        for key in (
            "available",
            "profile",
            "target",
            "target_slug",
            "auth_flow",
            "auth_type",
            "cookies_count",
            "cookie_names",
            "storage_keys",
            "headers_available",
        ):
            assert key in summary, f"missing {key!r} in safe summary"
        rendered = json.dumps(summary)
        assert "REAL_BEARER_TOKEN" not in rendered
        assert "REAL_SESSION_VALUE" not in rendered
        assert "REAL_CSRF" not in rendered
