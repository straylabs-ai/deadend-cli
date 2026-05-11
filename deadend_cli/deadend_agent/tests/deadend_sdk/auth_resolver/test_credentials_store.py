# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for ``CredentialsStore`` wallet resolution."""

from __future__ import annotations

from pathlib import Path

from deadend_agent.auth_resolver import CredentialsStore


class TestCredentialsStore:
    def test_resolve_default_profile(
        self, reusable_credentials_wallet: Path
    ) -> None:
        creds = CredentialsStore.resolve("http://localhost:8080", profile="default")
        assert creds.username == "alice"
        assert creds.password == "p4ssw0rd!"
        assert creds.login_url == "http://localhost:8080/login"
        assert creds.refresh_url == "http://localhost:8080/refresh"

    def test_resolve_admin_profile(self, reusable_credentials_wallet: Path) -> None:
        creds = CredentialsStore.resolve("http://localhost:8080", profile="admin")
        assert creds.username == "root"
        assert creds.password == "rootpass"

    def test_resolve_unknown_target_returns_empty(
        self, reusable_credentials_wallet: Path
    ) -> None:
        creds = CredentialsStore.resolve("http://nope.test", profile="default")
        assert creds.username is None
        assert creds.password is None
        assert creds.login_url is None

    def test_resolve_unknown_profile_returns_empty(
        self, reusable_credentials_wallet: Path
    ) -> None:
        creds = CredentialsStore.resolve(
            "http://localhost:8080", profile="ghost-profile"
        )
        assert creds.username is None
        assert creds.password is None

    def test_list_profiles(self, reusable_credentials_wallet: Path) -> None:
        assert sorted(
            CredentialsStore.list_profiles("http://localhost:8080")
        ) == ["admin", "default"]

    def test_target_normalisation(self, reusable_credentials_wallet: Path) -> None:
        # Trailing path / scheme prefix should not break lookup.
        creds = CredentialsStore.resolve(
            "https://localhost:8080/some/page", profile="default"
        )
        assert creds.username == "alice"
