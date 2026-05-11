# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Authentication resolver: persist and share auth context across tools.

This module defines the data models for authentication flows and types, plus
``AuthContextHandler`` which loads/saves auth state to disk so that multiple
tools and sub-agents can reuse the same browser session artefacts.
"""

from __future__ import annotations
from deadend_agent.constants import REUSABLE_CREDENTIALS_FILE, DEADEND_AGENTS_PATH
from deadend_agent.utils.network import slugify_target

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Cookie / header shapes (tight, matches Pydoll/Chrome CDP)
# ---------------------------------------------------------------------------

class CookieRecord(BaseModel):
    """One serialised cookie matching Pydoll's ``Cookie`` TypedDict."""

    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: float | None = None
    size: int = 0
    httpOnly: bool = False
    secure: bool = False
    session: bool = False
    sameSite: str | None = None
    priority: str | None = None
    sameParty: bool | None = None
    sourceScheme: str | None = None
    sourcePort: int | None = None
    partitionKey: dict[str, Any] | None = None


class StorageSnapshot(BaseModel):
    """Browser storage scraped from one origin at a point in time."""

    localStorage: dict[str, str] = Field(default_factory=dict)
    sessionStorage: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Credential models (target-scoped profiles)
# ---------------------------------------------------------------------------

class CredentialProfile(BaseModel):
    """One named credential set for a target."""

    username: str | None = None
    password: str | None = None
    role: str = "user"
    # Future: totp_secret, api_key, custom_headers, …


class TargetCredentials(BaseModel):
    """All credentials and metadata for a single target host."""

    credentials: dict[str, CredentialProfile] = Field(default_factory=dict)
    # ^ profile_name -> CredentialProfile  (e.g. "account_test_1")
    login_url: str | None = None
    refresh_url: str | None = None


class CredentialsRefs(BaseModel):
    """Resolved credential placeholders returned to callers (no role)."""

    username: str | None = None
    password: str | None = None
    login_url: str | None = None
    refresh_url: str | None = None


# ---------------------------------------------------------------------------
# Auth flow / type classification (LLM decides these)
# ---------------------------------------------------------------------------

class AuthFlow(str, Enum):
    """How the app expects the user to authenticate."""

    HTTP_LOGIN = "http"
    FORM = "form"
    JSON = "json"
    OAUTH = "oauth"
    AUTHORIZATION_CODE = "authorization_code"
    CALLBACK = "callback"


class AuthType(str, Enum):
    """What artefacts the agent should harvest after a successful login."""

    SESSION_COOKIE = "session_cookie"
    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


# ---------------------------------------------------------------------------
# AuthCredentials — what the LLM tells us about the target's auth setup
# ---------------------------------------------------------------------------

class AuthCredentials(BaseModel):
    """Description of the authentication mechanism discovered by recon."""

    auth_url: str | None = None
    target_origin: str | None = None
    auth_flow: AuthFlow | None = None
    auth_type: AuthType | None = None
    credential_ref: CredentialsRefs | None = None


# ---------------------------------------------------------------------------
# AuthContext — the actual harvested session state
# ---------------------------------------------------------------------------

class AuthContext(BaseModel):
    """Snapshot of an authenticated browser session.

    Saved after a successful ``authenticate`` tool call and re-loaded by
    later tools (e.g. ``browser_run_steps``) so the browser starts warm.
    """

    profile: str
    cookies: list[CookieRecord] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    browser_storage: StorageSnapshot = Field(default_factory=StorageSnapshot)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # metadata auto-populated keys:
    #   - auth_flow (str)
    #   - auth_type (str)
    #   - auth_url (str)
    #   - target_origin (str)
    #   - captured_at (ISO-8601)
    #   - source_url (final URL after login)
    #   - source_title (page title after login)

    def model_post_init(self, __context: Any) -> None:
        """Ensure timestamps are present."""
        self.metadata.setdefault(
            "captured_at",
            datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# CredentialsStore — reads reusable_credentials.json
# ---------------------------------------------------------------------------

class CredentialsStore:
    """Reads the user's credential wallet from disk.

    Structured by **target**::

        {
          "targets": {
            "pwn.me": {
              "credentials": {
                "account_test_1": {"username": "...", "password": "...", "role": "user"},
                "account_test_2": {"username": "...", "password": "...", "role": "admin"}
              },
              "login_url": "https://pwn.me/login",
              "refresh_url": "https://pwn.me/refresh"
            }
          }
        }
    """

    _wallet_path: Path = REUSABLE_CREDENTIALS_FILE

    @classmethod
    def _load_wallet(cls, path_credentials: Path | None) -> dict[str, Any]:
        if path_credentials is None:
            user_credentials = cls._wallet_path
        else:
            user_credentials = path_credentials
        try:
            with open(user_credentials, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"targets": {}}

    @classmethod
    def _normalise_target(cls, target: str) -> str:
        """Strip scheme and path so keys match consistently."""
        t = target.lower()
        for prefix in ("https://", "http://"):
            if t.startswith(prefix):
                t = t[len(prefix):]
        # drop any path or port
        t = t.split("/")[0].split(":")[0]
        return t

    @classmethod
    def get_target_credentials(cls, target: str, path_credentials: Path | None = None) -> TargetCredentials | None:
        """Return the ``TargetCredentials`` block for *target*, or ``None``."""
        wallet = cls._load_wallet(path_credentials)
        targets: dict[str, Any] = wallet.get("targets", {})
        key = cls._normalise_target(target)

        # Exact match first, then fallback to any key that ends with our domain
        raw = targets.get(key)
        if raw is None:
            for k, v in targets.items():
                if k.endswith(key) or key.endswith(k):
                    raw = v
                    break
        if raw is None:
            return None
        return TargetCredentials.model_validate(raw)

    @classmethod
    def list_profiles(cls, target: str) -> list[str]:
        """Return all credential profile names registered for *target*."""
        tc = cls.get_target_credentials(target)
        if tc is None:
            return []
        return list(tc.credentials.keys())

    @classmethod
    def resolve(
        cls,
        target: str,
        profile: str = "default",
    ) -> CredentialsRefs:
        """Return real credentials for *target* + *profile*.

        If *profile* is not found under the target, an empty
        ``CredentialsRefs`` is returned.
        """
        tc = cls.get_target_credentials(target)
        if tc is None:
            return CredentialsRefs()

        cp = tc.credentials.get(profile)
        if cp is None:
            return CredentialsRefs()

        return CredentialsRefs(
            username=cp.username,
            password=cp.password,
            login_url=tc.login_url,
            refresh_url=tc.refresh_url,
        )


# ---------------------------------------------------------------------------
# AuthContextHandler — persist / load / enumerate auth contexts
# ---------------------------------------------------------------------------

class AuthContextHandler:
    """Owner of all saved auth contexts for one agent + target pair.

    Disk layout::

        ~/.deadend/agents/
        └── <agent_id>/<session_id>/auth_context/
            ├── default.json
            ├── default.playwright.json
            ├── admin.json
            └── index.json       # manifest of all saved profiles
    """

    def __init__(self, target: str, agent_id: uuid.UUID | None, session_id: uuid.UUID | None) -> None:
        self.target = target
        self.target_slug = slugify_target(target)
        self.agent_id = agent_id
        self.session_id = session_id
        self._auth_dir = (
            DEADEND_AGENTS_PATH
            / str(agent_id)
            / str(session_id)
            / "auth_context"
        )
        self._auth_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._auth_dir / "index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index()

    # -- index manipulation ------------------------------------------------

    def _load_index(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self._index_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as fh:
            json.dump(self._index, fh, indent=2, default=str)

    def _profile_path(self, profile: str) -> Path:
        # Sanitise profile name for filesystem safety
        safe = "".join(c for c in profile if c.isalnum() or c in "-_").lower()
        if not safe:
            safe = "default"
        return self._auth_dir / f"{safe}.json"

    # -- public API --------------------------------------------------------

    def list_profiles(self) -> list[str]:
        """Return all saved profile names."""
        return list(self._index.keys())

    def resolve_credentials(
        self,
        profile: str = "default",
    ) -> CredentialsRefs:
        """Resolve real credentials for *profile* from the credential wallet."""
        return CredentialsStore.resolve(self.target, profile)

    def list_wallet_profiles(self) -> list[str]:
        """Return credential profile names available in the wallet for our target."""
        return CredentialsStore.list_profiles(self.target)

    def load_context(self, profile: str) -> AuthContext | None:
        """Load a previously saved context from disk.

        Returns ``None`` if the profile does not exist or the file is corrupt.
        """
        path = self._profile_path(profile)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return AuthContext.model_validate(raw)
        except (json.JSONDecodeError, Exception):
            # Corrupt file — clean up index entry
            self._index.pop(profile, None)
            self._save_index()
            return None

    def save_context(self, profile: str, context: AuthContext) -> None:
        """Persist *context* under *profile* and update the manifest."""
        path = self._profile_path(profile)
        context.metadata.setdefault("target", self.target)
        context.metadata.setdefault("target_slug", self.target_slug)
        context.metadata.setdefault("agent_id", str(self.agent_id))
        context.metadata.setdefault("session_id", str(self.session_id))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(context.model_dump_json(indent=2))

        self._index[profile] = {
            "target": self.target,
            "target_slug": self.target_slug,
            "agent_id": str(self.agent_id),
            "session_id": str(self.session_id),
            "profile": profile,
            "auth_flow": context.metadata.get("auth_flow"),
            "auth_type": context.metadata.get("auth_type"),
            "captured_at": context.metadata.get("captured_at"),
            "cookies_count": len(context.cookies),
            "storage_keys": sorted(
                set(context.browser_storage.localStorage.keys())
                | set(context.browser_storage.sessionStorage.keys())
            ),
            "headers_available": sorted(context.headers.keys()),
            "path": str(path),
        }
        self._save_index()

    def update_context(self, profile: str, **kwargs: Any) -> AuthContext | None:
        """Merge *kwargs* into an existing context and re-save.

        *kwargs* are shallow-merged into ``context.metadata``.
        Returns the updated context or ``None`` if the profile did not exist.
        """
        ctx = self.load_context(profile)
        if ctx is None:
            return None
        ctx.metadata.update(kwargs)
        self.save_context(profile, ctx)
        return ctx

    def delete_profile(self, profile: str) -> bool:
        """Remove a profile from disk and the manifest.

        Returns ``True`` if the profile existed and was removed.
        """
        path = self._profile_path(profile)
        removed = False
        if path.exists():
            path.unlink()
            removed = True
        playwright_path = self.playwright_storage_path(profile)
        if playwright_path.exists():
            playwright_path.unlink()
        self._index.pop(profile, None)
        self._save_index()
        return removed

    def playwright_storage_path(self, profile: str) -> Path:
        """Return the Playwright-compatible storage-state path for *profile*."""
        safe = "".join(c for c in profile if c.isalnum() or c in "-_").lower()
        if not safe:
            safe = "default"
        return self._auth_dir / f"{safe}.playwright.json"

    def summarize_context(self, profile: str) -> dict[str, Any]:
        """Return a secret-free summary for one saved auth profile."""
        ctx = self.load_context(profile)
        if ctx is None:
            return {
                "available": False,
                "target": self.target,
                "target_slug": self.target_slug,
                "agent_id": str(self.agent_id),
                "session_id": str(self.session_id),
                "profile": profile,
            }
        from deadend_agent.auth_resolver.auth_context_utils import safe_auth_summary

        return safe_auth_summary(ctx)

    def list_context_summaries(self) -> dict[str, dict[str, Any]]:
        """Return secret-free summaries for all saved auth profiles."""
        return {profile: self.summarize_context(profile) for profile in self.list_profiles()}

    async def authenticate(self, credential_ref: CredentialsRefs) -> AuthContext:
        """Placeholder — will be implemented in Phase 2 (authenticate tool).

        This stub exists so that ``AuthContextHandler`` remains the single
        owner of auth state; the actual browser automation lives in the tool.
        """
        raise NotImplementedError(
            "Use the authenticate tool in deadend_agent.tools.browser"
        )


__all__ = [
    "CookieRecord",
    "StorageSnapshot",
    "CredentialProfile",
    "TargetCredentials",
    "CredentialsRefs",
    "AuthFlow",
    "AuthType",
    "AuthCredentials",
    "AuthContext",
    "CredentialsStore",
    "AuthContextHandler",
]
