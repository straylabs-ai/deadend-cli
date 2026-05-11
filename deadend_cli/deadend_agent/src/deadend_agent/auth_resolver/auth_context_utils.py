# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Utilities for converting and summarising authentication contexts."""

from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from deadend_agent.auth_resolver.auth_resolver import AuthContext, CookieRecord, StorageSnapshot
from deadend_agent.utils.network import normalize_target_key, slugify_target

_TOKEN_KEYS = {
    "access_token",
    "accesstoken",
    "auth_token",
    "authtoken",
    "bearer_token",
    "bearertoken",
    "jwt",
    "token",
    "id_token",
    "idtoken",
}
_API_KEY_KEYS = {"api_key", "apikey", "x_api_key", "x-api-key"}


def _normalise_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _cookie_to_record(cookie: Mapping[str, Any]) -> CookieRecord | None:
    """Best-effort conversion of a browser/CDP cookie dict into ``CookieRecord``."""
    if not cookie.get("name"):
        return None
    data = dict(cookie)
    data.setdefault("value", "")
    data.setdefault("domain", "")
    data.setdefault("path", "/")
    return CookieRecord.model_validate(data)


def derive_headers_from_storage(
    local_storage: Mapping[str, Any] | None = None,
    session_storage: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Derive reusable HTTP auth headers from common browser storage token names.

    The returned values may contain secrets and must only be saved into AuthContext
    or used internally by tools. LLM-facing summaries should expose header names only.
    """
    headers: dict[str, str] = {}
    combined: dict[str, Any] = {}
    combined.update(local_storage or {})
    combined.update(session_storage or {})

    for key, value in combined.items():
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        nk = _normalise_key(key)
        compact = nk.replace("_", "")
        if nk in _TOKEN_KEYS or compact in _TOKEN_KEYS:
            # Avoid double-prefixing already formatted values.
            if text.lower().startswith("bearer "):
                headers.setdefault("Authorization", text)
            else:
                headers.setdefault("Authorization", f"Bearer {text}")
        elif nk in _API_KEY_KEYS or compact in _API_KEY_KEYS:
            headers.setdefault("X-API-Key", text)
    return headers


def auth_context_from_browser_state(
    *,
    profile: str,
    target: str,
    agent_id: str,
    session_id: str,
    state: Mapping[str, Any],
    auth_url: str | None = None,
    auth_flow: str | None = None,
    auth_type: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> AuthContext:
    """Build an ``AuthContext`` from ``BrowserSession.export_state()`` output."""
    local_storage = state.get("localStorage") or {}
    session_storage = state.get("sessionStorage") or {}
    cookies = [
        record
        for c in (state.get("cookies") or [])
        if (record := _cookie_to_record(c)) is not None
    ]
    headers = derive_headers_from_storage(local_storage, session_storage)
    metadata: dict[str, Any] = {
        "target": target,
        "target_slug": slugify_target(target),
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "auth_url": auth_url,
        "auth_flow": auth_flow,
        "auth_type": auth_type,
        "source_url": state.get("url"),
        "final_url": state.get("url"),
        "source_title": state.get("title"),
        "cookies_count": len(cookies),
        "cookie_names": sorted({c.name for c in cookies}),
        "storage_keys": sorted(set(local_storage.keys()) | set(session_storage.keys())),
        "headers_available": sorted(headers.keys()),
        "validated": True,
    }
    if extra_metadata:
        metadata.update(dict(extra_metadata))

    return AuthContext(
        profile=profile,
        cookies=cookies,
        headers=headers,
        browser_storage=StorageSnapshot(
            localStorage={str(k): str(v) for k, v in local_storage.items()},
            sessionStorage={str(k): str(v) for k, v in session_storage.items()},
        ),
        metadata=metadata,
    )


def browser_state_from_auth_context(context: AuthContext) -> dict[str, Any]:
    """Convert ``AuthContext`` into a shape accepted by ``BrowserSession.import_state``."""
    return {
        "cookies": [c.model_dump(exclude_none=True) for c in context.cookies],
        "localStorage": dict(context.browser_storage.localStorage),
        "sessionStorage": dict(context.browser_storage.sessionStorage),
        "url": context.metadata.get("final_url") or context.metadata.get("source_url"),
        "title": context.metadata.get("source_title"),
    }


def safe_auth_summary(context: AuthContext) -> dict[str, Any]:
    """Return LLM-safe metadata for an auth context without secret values."""
    local_keys = set(context.browser_storage.localStorage.keys())
    session_keys = set(context.browser_storage.sessionStorage.keys())
    metadata = dict(context.metadata)
    return {
        "available": True,
        "profile": context.profile,
        "target": metadata.get("target"),
        "target_slug": metadata.get("target_slug"),
        "agent_id": metadata.get("agent_id"),
        "session_id": metadata.get("session_id"),
        "auth_flow": metadata.get("auth_flow"),
        "auth_type": metadata.get("auth_type"),
        "auth_url": metadata.get("auth_url"),
        "final_url": metadata.get("final_url") or metadata.get("source_url"),
        "page_title": metadata.get("source_title"),
        "captured_at": metadata.get("captured_at"),
        "validated": metadata.get("validated"),
        "cookies_count": len(context.cookies),
        "cookie_names": sorted({c.name for c in context.cookies}),
        "storage_keys": sorted(local_keys | session_keys),
        "headers_available": sorted(context.headers.keys()),
    }


def playwright_storage_state_from_auth_context(
    context: AuthContext,
    *,
    target: str | None = None,
) -> dict[str, Any]:
    """Convert ``AuthContext`` into Playwright's storage_state JSON shape."""
    effective_target = target or context.metadata.get("target") or context.metadata.get("final_url")
    origin = normalize_target_key(str(effective_target)) if effective_target else None

    cookies = []
    for cookie in context.cookies:
        data = cookie.model_dump(exclude_none=True)
        # Playwright does not accept CDP read-only / pydoll-only fields.
        for key in ("size", "session", "priority", "sameParty", "sourceScheme", "sourcePort", "partitionKey"):
            data.pop(key, None)
        if "expires" in data and data["expires"] is None:
            data.pop("expires", None)
        cookies.append(data)

    origins = []
    if origin:
        origins.append(
            {
                "origin": origin,
                "localStorage": [
                    {"name": str(k), "value": str(v)}
                    for k, v in context.browser_storage.localStorage.items()
                ],
            }
        )
    return {"cookies": cookies, "origins": origins}


def cookie_header_from_auth_context(context: AuthContext, *, target: str | None = None) -> str:
    """Build a Cookie header value from saved cookies.

    This is used by raw HTTP tooling when directly loading browser storage is not
    necessary or not available.
    """
    if not context.cookies:
        return ""
    host = ""
    if target:
        parsed = urlparse(normalize_target_key(target))
        host = parsed.hostname or ""

    pairs: list[str] = []
    for cookie in context.cookies:
        domain = cookie.domain.lstrip(".") if cookie.domain else ""
        if host and domain and not (host == domain or host.endswith(f".{domain}")):
            continue
        pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(pairs)


def write_playwright_storage_state(context: AuthContext, path: Any, *, target: str | None = None) -> None:
    """Write Playwright storage state JSON to ``path``."""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(playwright_storage_state_from_auth_context(context, target=target), indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# JWT helpers (Phase 13 - validation)
# ---------------------------------------------------------------------------


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def parse_jwt_payload(token: str) -> dict[str, Any] | None:
    """Best-effort decode of a JWT's payload **without** signature verification.

    Returns ``None`` when the token does not look like a JWT (e.g. opaque
    bearer tokens, API keys). We deliberately never verify the signature
    — we only want to read public claims like ``exp``.
    """
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_bytes = _b64url_decode(parts[1])
        payload = json.loads(payload_bytes)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_jwt_exp(token: str) -> int | None:
    """Return the ``exp`` claim of a JWT as a Unix epoch ``int``, or ``None``.

    ``None`` is returned both when the token isn't a JWT and when it is but
    has no usable ``exp`` claim. Callers should treat ``None`` as "can't say".
    """
    payload = parse_jwt_payload(token)
    if not payload:
        return None
    exp = payload.get("exp")
    if isinstance(exp, bool):  # bool is an int subclass, exclude it
        return None
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def is_jwt_expired(
    token: str,
    *,
    leeway_s: int = 0,
    now_s: int | None = None,
) -> bool | None:
    """Return ``True``/``False`` if the JWT's ``exp`` says expired, ``None`` if unknown.

    ``leeway_s`` lets callers tolerate small clock skew. ``now_s`` overrides
    ``time.time()`` (useful for tests).
    """
    exp = parse_jwt_exp(token)
    if exp is None:
        return None
    current = int(now_s if now_s is not None else time.time())
    return current >= (exp + leeway_s)


def extract_bearer_token(auth_context: AuthContext) -> str | None:
    """Return the bearer token from ``AuthContext.headers['Authorization']``.

    Returns ``None`` when there is no Authorization header, when the scheme is
    not Bearer, or when the value is empty.
    """
    if not auth_context.headers:
        return None
    raw = auth_context.headers.get("Authorization") or auth_context.headers.get(
        "authorization"
    )
    if not raw:
        return None
    lowered = raw.lower()
    if not lowered.startswith("bearer "):
        return None
    return raw[len("bearer ") :].strip() or None


# ---------------------------------------------------------------------------
# JSON / API / Basic auth helpers (used by the ``authenticate`` tool's
# non-browser flows). These build / consume ``AuthContext`` so the same disk
# layout and downstream tools work regardless of how authentication happened.
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def render_credential_template(value: Any, context: Mapping[str, Any]) -> Any:
    """Recursively replace ``{{key}}`` placeholders in *value* using *context*.

    Strings are rendered with substring substitution: ``"user_{{username}}"``
    becomes ``"user_alice"``. Dict and list structures are traversed in place.
    Unknown placeholders are left intact (so callers can detect missing keys).
    Non-string scalars are returned unchanged.
    """
    if isinstance(value, str):
        return _PLACEHOLDER_RE.sub(
            lambda m: str(context.get(m.group(1), m.group(0))), value
        )
    if isinstance(value, Mapping):
        return {k: render_credential_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_credential_template(v, context) for v in value]
    return value


def extract_token_by_path(payload: Any, path: str | None) -> str | None:
    """Resolve a dot-path into a JSON-like *payload* and return the value as ``str``.

    Supports list indexing via numeric segments, e.g. ``data.tokens.0.value``.
    Returns ``None`` if any segment cannot be resolved or the resolved value
    is itself ``None`` / not stringifiable.
    """
    if not path:
        return None
    cur: Any = payload
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            if not part.isdigit():
                return None
            idx = int(part)
            if not 0 <= idx < len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            return None
    if cur is None:
        return None
    return str(cur)


def cookies_from_aiohttp_jar(jar: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert an iterable of ``http.cookies.Morsel`` (e.g. from
    ``aiohttp.CookieJar``) into the dict shape used by ``CookieRecord``.
    """
    out: list[dict[str, Any]] = []
    for morsel in jar:
        # Iterating an ``aiohttp.CookieJar`` yields ``Morsel`` objects.
        out.append(
            {
                "name": morsel.key,
                "value": morsel.value,
                "domain": morsel.get("domain", "") or "",
                "path": morsel.get("path", "/") or "/",
                "secure": bool(morsel.get("secure")),
                "httpOnly": bool(morsel.get("httponly")),
                "sameSite": morsel.get("samesite") or None,
            }
        )
    return out


def build_basic_auth_header(username: str | None, password: str | None) -> str | None:
    """Build an HTTP Basic ``Authorization`` header value from credentials.

    Returns ``None`` when both username and password are missing/empty so
    callers can fail-fast with a clear error.
    """
    if not username and not password:
        return None
    raw = f"{username or ''}:{password or ''}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def auth_context_from_api_response(
    *,
    profile: str,
    target: str,
    agent_id: str,
    session_id: str,
    token: str | None = None,
    token_header_name: str = "Authorization",
    token_header_format: str = "Bearer {token}",
    extra_headers: Mapping[str, str] | None = None,
    cookies: Sequence[Mapping[str, Any]] | None = None,
    final_url: str | None = None,
    auth_url: str | None = None,
    auth_flow: str | None = None,
    auth_type: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> AuthContext:
    """Build an ``AuthContext`` from an API/Basic auth response.

    Unlike :func:`auth_context_from_browser_state` there is no browser storage;
    auth material lives entirely in cookies and reusable headers.
    """
    headers: dict[str, str] = {}
    if token:
        try:
            headers[token_header_name] = token_header_format.format(token=token)
        except (KeyError, IndexError):
            # Fall back to raw token if the format string is malformed.
            headers[token_header_name] = token
    if extra_headers:
        for k, v in extra_headers.items():
            if k and v is not None:
                headers.setdefault(str(k), str(v))

    cookie_records = [
        record
        for c in (cookies or [])
        if (record := _cookie_to_record(c)) is not None
    ]
    metadata: dict[str, Any] = {
        "target": target,
        "target_slug": slugify_target(target),
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "auth_url": auth_url,
        "auth_flow": auth_flow,
        "auth_type": auth_type,
        "final_url": final_url,
        "source_url": final_url,
        "source_title": None,
        "cookies_count": len(cookie_records),
        "cookie_names": sorted({c.name for c in cookie_records}),
        "storage_keys": [],
        "headers_available": sorted(headers.keys()),
        "validated": True,
    }
    if extra_metadata:
        metadata.update(dict(extra_metadata))

    return AuthContext(
        profile=profile,
        cookies=cookie_records,
        headers=headers,
        browser_storage=StorageSnapshot(),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Raw HTTP request manipulation (used by ``pw_send_payload`` to inject saved
# auth headers without mangling the rest of the request).
# ---------------------------------------------------------------------------

_HEADER_LINE_RE = re.compile(r"^([^:]+):\s*(.*)$")


def _split_request_blocks(raw_request: str) -> tuple[str, list[str], str, str]:
    """Return ``(request_line, header_lines, body, line_ending)`` for *raw_request*.

    Preserves ``\r\n`` if present, otherwise falls back to ``\n``.
    """
    line_ending = "\r\n" if "\r\n" in raw_request else "\n"
    head_body_sep = line_ending * 2
    if head_body_sep in raw_request:
        head, body = raw_request.split(head_body_sep, 1)
    else:
        head, body = raw_request, ""
    lines = head.split(line_ending)
    request_line = lines[0] if lines else ""
    header_lines = lines[1:] if len(lines) > 1 else []
    return request_line, header_lines, body, line_ending


def inject_headers_into_raw_request(
    raw_request: str,
    extra_headers: Mapping[str, str],
) -> str:
    """Insert *extra_headers* into *raw_request* unless already present.

    Header presence is checked case-insensitively. Existing headers are never
    overridden, so the LLM (or caller) can deliberately set, e.g.,
    ``Authorization: <attacker-token>`` and that value will win over the saved
    AuthContext header.

    The line ending of the original request is preserved (``\r\n`` for
    well-formed HTTP, ``\n`` otherwise).
    """
    if not extra_headers:
        return raw_request
    request_line, header_lines, body, line_ending = _split_request_blocks(raw_request)
    existing: set[str] = set()
    for line in header_lines:
        m = _HEADER_LINE_RE.match(line)
        if m:
            existing.add(m.group(1).strip().lower())
    appended: list[str] = []
    for name, value in extra_headers.items():
        if not name or value is None:
            continue
        if name.lower() in existing:
            continue
        appended.append(f"{name}: {value}")
    if not appended:
        return raw_request
    new_head = line_ending.join([request_line, *appended, *header_lines])
    if body or raw_request.endswith(line_ending * 2):
        return new_head + line_ending * 2 + body
    return new_head + line_ending * 2
