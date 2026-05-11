# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for the JSON / API / Basic-auth helpers (Phase 12).

Validates:

* ``render_credential_template`` does string-level ``{{key}}`` substitution
  recursively through dict/list/scalar shapes and leaves unknown placeholders
  intact.
* ``extract_token_by_path`` resolves dot-paths through dicts and list indices,
  and returns ``None`` on misses.
* ``cookies_from_aiohttp_jar`` adapts ``http.cookies.Morsel`` objects into the
  CookieRecord-compatible dict shape.
* ``build_basic_auth_header`` produces a base64 ``Basic <token>`` header and
  ``None`` for fully empty credentials.
* ``auth_context_from_api_response`` builds a header- and cookie-only
  AuthContext (no browser storage), with safe metadata only.
* ``inject_headers_into_raw_request`` adds missing headers without overriding
  existing ones, preserving line endings.
"""

from __future__ import annotations

import base64
import json
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from deadend_agent.auth_resolver import (
    auth_context_from_api_response,
    build_basic_auth_header,
    cookies_from_aiohttp_jar,
    extract_token_by_path,
    inject_headers_into_raw_request,
    render_credential_template,
    safe_auth_summary,
)


class TestRenderCredentialTemplate:
    def test_string_substitution(self) -> None:
        out = render_credential_template(
            "user_{{username}}", {"username": "alice"}
        )
        assert out == "user_alice"

    def test_nested_dict_and_list(self) -> None:
        out = render_credential_template(
            {
                "email": "{{username}}",
                "password": "{{password}}",
                "tags": ["x", "{{username}}"],
                "nested": {"who": "{{username}}"},
            },
            {"username": "alice", "password": "p"},
        )
        assert out == {
            "email": "alice",
            "password": "p",
            "tags": ["x", "alice"],
            "nested": {"who": "alice"},
        }

    def test_unknown_placeholder_is_preserved(self) -> None:
        out = render_credential_template("{{ghost}}", {})
        assert out == "{{ghost}}"

    def test_non_string_scalars_passthrough(self) -> None:
        assert render_credential_template(7, {"x": "y"}) == 7
        assert render_credential_template(True, {"x": "y"}) is True
        assert render_credential_template(None, {"x": "y"}) is None

    def test_whitespace_and_underscore_keys(self) -> None:
        out = render_credential_template(
            "{{  user_name  }}", {"user_name": "alice"}
        )
        assert out == "alice"


class TestExtractTokenByPath:
    def test_dict_path(self) -> None:
        assert (
            extract_token_by_path({"data": {"token": "X"}}, "data.token") == "X"
        )

    def test_list_index_path(self) -> None:
        payload = {"items": [{"v": "a"}, {"v": "b"}]}
        assert extract_token_by_path(payload, "items.1.v") == "b"

    def test_missing_segment_returns_none(self) -> None:
        assert extract_token_by_path({"a": 1}, "a.b") is None
        assert extract_token_by_path({"a": [1, 2]}, "a.10") is None

    def test_empty_path_returns_none(self) -> None:
        assert extract_token_by_path({"a": 1}, "") is None
        assert extract_token_by_path({"a": 1}, None) is None

    def test_value_stringification(self) -> None:
        assert extract_token_by_path({"n": 42}, "n") == "42"


class TestCookiesFromAiohttpJar:
    def _morsel(self, name: str, value: str, **attrs):  # type: ignore[no-untyped-def]
        c = SimpleCookie()
        c[name] = value
        for k, v in attrs.items():
            c[name][k] = v
        return c[name]

    def test_minimal_morsel(self) -> None:
        morsel = self._morsel("sessionid", "v")
        out = cookies_from_aiohttp_jar([morsel])
        assert out == [
            {
                "name": "sessionid",
                "value": "v",
                "domain": "",
                "path": "/",
                "secure": False,
                "httpOnly": False,
                "sameSite": None,
            }
        ]

    def test_full_morsel_attributes(self) -> None:
        morsel = self._morsel(
            "sid",
            "abc",
            domain="localhost",
            path="/api",
            secure=True,
            httponly=True,
            samesite="Lax",
        )
        out = cookies_from_aiohttp_jar([morsel])
        assert out[0]["domain"] == "localhost"
        assert out[0]["path"] == "/api"
        assert out[0]["secure"] is True
        assert out[0]["httpOnly"] is True
        assert out[0]["sameSite"] == "Lax"


class TestBuildBasicAuthHeader:
    def test_standard(self) -> None:
        token = build_basic_auth_header("alice", "p4ss")
        assert token == "Basic " + base64.b64encode(b"alice:p4ss").decode("ascii")

    def test_empty_credentials_returns_none(self) -> None:
        assert build_basic_auth_header(None, None) is None
        assert build_basic_auth_header("", "") is None

    def test_password_only(self) -> None:
        token = build_basic_auth_header(None, "secret")
        assert token == "Basic " + base64.b64encode(b":secret").decode("ascii")


class TestAuthContextFromApiResponse:
    def test_token_becomes_authorization_header(self) -> None:
        ctx = auth_context_from_api_response(
            profile="default",
            target="http://localhost:8080",
            agent_id="aid",
            session_id="sid",
            token="JWT",
            cookies=[],
            final_url="http://localhost:8080/me",
            auth_flow="json",
            auth_type="bearer_token",
        )
        assert ctx.headers == {"Authorization": "Bearer JWT"}
        assert ctx.cookies == []
        assert ctx.browser_storage.localStorage == {}
        assert ctx.metadata["target_slug"] == "localhost_8080"
        assert ctx.metadata["auth_flow"] == "json"
        assert ctx.metadata["headers_available"] == ["Authorization"]

    def test_custom_header_format(self) -> None:
        ctx = auth_context_from_api_response(
            profile="default",
            target="http://t",
            agent_id="aid",
            session_id="sid",
            token="K",
            token_header_name="X-Auth",
            token_header_format="Token {token}",
        )
        assert ctx.headers == {"X-Auth": "Token K"}

    def test_extra_headers_merged_without_override(self) -> None:
        ctx = auth_context_from_api_response(
            profile="default",
            target="http://t",
            agent_id="aid",
            session_id="sid",
            token="K",
            extra_headers={"Authorization": "should-not-override", "X-App": "deadend"},
        )
        # Token-derived Authorization wins over extras.
        assert ctx.headers["Authorization"] == "Bearer K"
        assert ctx.headers["X-App"] == "deadend"

    def test_basic_only_no_token(self) -> None:
        ctx = auth_context_from_api_response(
            profile="default",
            target="http://t",
            agent_id="aid",
            session_id="sid",
            token=None,
            extra_headers={"Authorization": "Basic xxx"},
            auth_flow="http",
            auth_type="api_key",
        )
        assert ctx.headers == {"Authorization": "Basic xxx"}
        assert ctx.metadata["auth_flow"] == "http"
        assert ctx.metadata["auth_type"] == "api_key"

    def test_safe_summary_does_not_leak_token(self) -> None:
        ctx = auth_context_from_api_response(
            profile="default",
            target="http://t",
            agent_id="aid",
            session_id="sid",
            token="VERY_SECRET_JWT",
            cookies=[{"name": "sid", "value": "VERY_SECRET_COOKIE", "domain": "t"}],
        )
        rendered = json.dumps(safe_auth_summary(ctx))
        assert "VERY_SECRET_JWT" not in rendered
        assert "VERY_SECRET_COOKIE" not in rendered


class TestInjectHeadersIntoRawRequest:
    RAW = (
        "GET /api/me HTTP/1.1\r\n"
        "Host: localhost:8080\r\n"
        "User-Agent: ua/1.0\r\n"
        "\r\n"
    )

    def test_injects_missing_header(self) -> None:
        out = inject_headers_into_raw_request(self.RAW, {"Authorization": "Bearer X"})
        assert "Authorization: Bearer X\r\n" in out
        # Original headers preserved verbatim.
        assert "Host: localhost:8080" in out
        assert "User-Agent: ua/1.0" in out
        # And the head/body separator is still there.
        assert out.endswith("\r\n\r\n") or "\r\n\r\n" in out

    def test_does_not_override_existing_header_case_insensitive(self) -> None:
        raw = (
            "GET /api/me HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "authorization: keep-me\r\n"
            "\r\n"
        )
        out = inject_headers_into_raw_request(raw, {"Authorization": "Bearer X"})
        assert "authorization: keep-me" in out
        # No second Authorization line was inserted.
        assert out.lower().count("authorization:") == 1

    def test_preserves_body(self) -> None:
        raw = (
            "POST /api HTTP/1.1\r\n"
            "Host: t\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 13\r\n"
            "\r\n"
            "{\"a\":\"b\"}\r\n"
        )
        out = inject_headers_into_raw_request(raw, {"X-Custom": "1"})
        assert "X-Custom: 1" in out
        assert "{\"a\":\"b\"}" in out

    def test_no_op_when_headers_empty(self) -> None:
        assert inject_headers_into_raw_request(self.RAW, {}) == self.RAW

    def test_lf_only_line_endings_preserved(self) -> None:
        raw = "GET / HTTP/1.1\nHost: t\n\n"
        out = inject_headers_into_raw_request(raw, {"X": "1"})
        assert "\r\n" not in out
        assert "X: 1\n" in out
