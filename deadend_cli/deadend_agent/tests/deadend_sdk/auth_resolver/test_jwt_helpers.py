# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tests for the JWT helpers used by the Phase 13 validation flow.

Covers:

* ``parse_jwt_payload`` decodes the middle segment without signature checks.
* ``parse_jwt_exp`` returns ``None`` for opaque tokens and malformed JWTs.
* ``is_jwt_expired`` returns ``True`` / ``False`` based on ``exp`` and respects
  ``leeway_s`` and the ``now_s`` override.
* ``extract_bearer_token`` only recognises the ``Bearer`` scheme.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from deadend_agent.auth_resolver import (
    AuthContext,
    StorageSnapshot,
    extract_bearer_token,
    is_jwt_expired,
    parse_jwt_exp,
    parse_jwt_payload,
)


def _make_jwt(claims: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )
    return f"{header}.{payload}.sig"


class TestParseJwt:
    def test_payload_extraction(self) -> None:
        token = _make_jwt({"sub": "alice", "exp": 1736000000})
        payload = parse_jwt_payload(token)
        assert payload == {"sub": "alice", "exp": 1736000000}

    def test_exp_returned_as_int(self) -> None:
        assert parse_jwt_exp(_make_jwt({"exp": 1736000000})) == 1736000000

    def test_float_exp_is_truncated(self) -> None:
        assert parse_jwt_exp(_make_jwt({"exp": 1736000000.9})) == 1736000000

    @pytest.mark.parametrize(
        "token",
        [
            "",
            None,  # type: ignore[list-item]
            "opaque-token",
            "only.two",
            "too.many.dots.here",
            "..",  # three empty segments
            "header.notb64*.sig",
        ],
    )
    def test_non_jwt_returns_none(self, token) -> None:  # type: ignore[no-untyped-def]
        assert parse_jwt_payload(token) is None
        assert parse_jwt_exp(token) is None

    def test_bool_exp_is_rejected(self) -> None:
        # ``bool`` is a subclass of ``int`` - parse_jwt_exp must explicitly reject.
        assert parse_jwt_exp(_make_jwt({"exp": True})) is None


class TestIsJwtExpired:
    def test_past_exp_is_expired(self) -> None:
        now = int(time.time())
        assert is_jwt_expired(_make_jwt({"exp": now - 100})) is True

    def test_future_exp_is_not_expired(self) -> None:
        now = int(time.time())
        assert is_jwt_expired(_make_jwt({"exp": now + 100})) is False

    def test_leeway_keeps_slightly_expired_token_alive(self) -> None:
        now = int(time.time())
        assert (
            is_jwt_expired(_make_jwt({"exp": now - 50}), leeway_s=100) is False
        )

    def test_now_override_for_deterministic_tests(self) -> None:
        token = _make_jwt({"exp": 1000})
        assert is_jwt_expired(token, now_s=999) is False
        assert is_jwt_expired(token, now_s=1000) is True
        assert is_jwt_expired(token, now_s=2000) is True

    def test_opaque_token_returns_none(self) -> None:
        assert is_jwt_expired("opaque-token") is None

    def test_jwt_without_exp_returns_none(self) -> None:
        assert is_jwt_expired(_make_jwt({"sub": "alice"})) is None


class TestExtractBearerToken:
    def test_standard_bearer(self) -> None:
        ctx = AuthContext(
            profile="d",
            cookies=[],
            headers={"Authorization": "Bearer TOK"},
            browser_storage=StorageSnapshot(),
            metadata={},
        )
        assert extract_bearer_token(ctx) == "TOK"

    def test_basic_is_not_bearer(self) -> None:
        ctx = AuthContext(
            profile="d",
            cookies=[],
            headers={"Authorization": "Basic abc"},
            browser_storage=StorageSnapshot(),
            metadata={},
        )
        assert extract_bearer_token(ctx) is None

    def test_missing_header_returns_none(self) -> None:
        ctx = AuthContext(
            profile="d",
            cookies=[],
            headers={},
            browser_storage=StorageSnapshot(),
            metadata={},
        )
        assert extract_bearer_token(ctx) is None

    def test_lowercase_header_name(self) -> None:
        ctx = AuthContext(
            profile="d",
            cookies=[],
            headers={"authorization": "Bearer LOWER"},
            browser_storage=StorageSnapshot(),
            metadata={},
        )
        assert extract_bearer_token(ctx) == "LOWER"

    def test_empty_token_returns_none(self) -> None:
        ctx = AuthContext(
            profile="d",
            cookies=[],
            headers={"Authorization": "Bearer "},
            browser_storage=StorageSnapshot(),
            metadata={},
        )
        assert extract_bearer_token(ctx) is None
