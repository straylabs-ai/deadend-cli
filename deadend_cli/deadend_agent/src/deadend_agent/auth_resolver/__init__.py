# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Authentication resolver module.

Provides data models for auth flows/types, harvested session state
(:class:`AuthContext`), and :class:`AuthContextHandler` which persists
and loads auth snapshots to/from disk.
"""

from deadend_agent.auth_resolver.auth_resolver import (
    AuthContext,
    AuthContextHandler,
    AuthCredentials,
    AuthFlow,
    AuthType,
    CookieRecord,
    CredentialProfile,
    CredentialsRefs,
    CredentialsStore,
    StorageSnapshot,
    TargetCredentials,
)

__all__ = [
    "AuthContext",
    "AuthContextHandler",
    "AuthCredentials",
    "AuthFlow",
    "AuthType",
    "CookieRecord",
    "CredentialProfile",
    "CredentialsRefs",
    "CredentialsStore",
    "StorageSnapshot",
    "TargetCredentials",
]
