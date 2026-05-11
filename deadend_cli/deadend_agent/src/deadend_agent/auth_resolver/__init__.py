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
from deadend_agent.auth_resolver.auth_context_utils import (
    auth_context_from_api_response,
    auth_context_from_browser_state,
    browser_state_from_auth_context,
    build_basic_auth_header,
    cookie_header_from_auth_context,
    cookies_from_aiohttp_jar,
    extract_bearer_token,
    extract_token_by_path,
    inject_headers_into_raw_request,
    is_jwt_expired,
    parse_jwt_exp,
    parse_jwt_payload,
    playwright_storage_state_from_auth_context,
    render_credential_template,
    safe_auth_summary,
    write_playwright_storage_state,
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
    "auth_context_from_api_response",
    "auth_context_from_browser_state",
    "browser_state_from_auth_context",
    "build_basic_auth_header",
    "cookie_header_from_auth_context",
    "cookies_from_aiohttp_jar",
    "extract_bearer_token",
    "extract_token_by_path",
    "inject_headers_into_raw_request",
    "is_jwt_expired",
    "parse_jwt_exp",
    "parse_jwt_payload",
    "playwright_storage_state_from_auth_context",
    "render_credential_template",
    "safe_auth_summary",
    "write_playwright_storage_state",
]
