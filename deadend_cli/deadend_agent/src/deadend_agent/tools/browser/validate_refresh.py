# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Validation and refresh services for saved AuthContext profiles (Phase 13).

- validate_auth_context_service: probes a saved AuthContext against an
  authenticated endpoint passed by the AuthenticatorAgent and updates the
  saved context's metadata with the verdict. JWTs are short-circuited
  locally using the ``exp`` claim before any network call.

- refresh_auth_context_service: renews an existing AuthContext using the
  wallet / metadata ``refresh_url`` without re-running the browser flow.
  Cookies and the ``Authorization`` header are updated in place.

The two pydantic-ai tools at the bottom expose these services to the
AuthenticatorAgent.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import ssl
import uuid
from collections.abc import Mapping
from http.cookies import SimpleCookie
from typing import Any

import aiohttp
from pydantic_ai import RunContext
from yarl import URL

from deadend_agent.auth_resolver import (
    AuthContext,
    AuthContextHandler,
    cookies_from_aiohttp_jar,
    extract_bearer_token,
    extract_token_by_path,
    is_jwt_expired,
    parse_jwt_exp,
    render_credential_template,
    safe_auth_summary,
    write_playwright_storage_state,
)
from deadend_agent.auth_resolver.auth_resolver import CookieRecord
from deadend_agent.logging import logger
from deadend_agent.tools.tool_wrappers import with_tool_events
from deadend_agent.utils.structures import RequesterDeps


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _build_aiohttp_connector(verify_ssl: bool) -> aiohttp.TCPConnector:
    if verify_ssl:
        return aiohttp.TCPConnector()
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ssl_ctx)


def _attach_cookies_to_jar(jar: aiohttp.CookieJar, ctx: AuthContext) -> None:
    """Seed an aiohttp.CookieJar from saved AuthContext cookies."""
    for cookie in ctx.cookies:
        sc: SimpleCookie = SimpleCookie()
        sc[cookie.name] = cookie.value
        morsel = sc[cookie.name]
        if cookie.domain:
            morsel["domain"] = cookie.domain
        if cookie.path:
            morsel["path"] = cookie.path
        if cookie.secure:
            morsel["secure"] = True
        if cookie.httpOnly:
            morsel["httponly"] = True
        if cookie.sameSite:
            morsel["samesite"] = cookie.sameSite
        host = cookie.domain.lstrip(".") if cookie.domain else ""
        scheme = "https" if cookie.secure else "http"
        try:
            response_url = URL(f"{scheme}://{host}/") if host else URL("/")
            jar.update_cookies(sc, response_url=response_url)
        except Exception:
            # Some cookie shapes (e.g. domainless) may be rejected by the jar;
            # we silently skip them - they wouldn't have matched anyway.
            continue


def _persist_metadata(handler: AuthContextHandler, ctx: AuthContext) -> None:
    """Re-save the AuthContext (and Playwright snapshot) after metadata edits."""
    handler.save_context(ctx.profile, ctx)
    write_playwright_storage_state(
        ctx,
        handler.playwright_storage_path(ctx.profile),
        target=ctx.metadata.get("target", handler.target),
    )


def _failure_summary(
    target: str,
    target_slug: str,
    agent_id: Any,
    session_id: Any,
    profile: str,
    *,
    error: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "success": False,
        "target": target,
        "target_slug": target_slug,
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "profile": profile,
        "error": error,
    }
    if extra:
        out.update(dict(extra))
    return out


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


async def validate_auth_context_service(
    *,
    target: str,
    agent_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    profile: str = "default",
    validation_url: str | None = None,
    expected_status: tuple[int, ...] = (200, 201, 202, 203, 204, 206, 207),
    failure_status: tuple[int, ...] = (401, 403),
    success_substring: str | None = None,
    success_jsonpath: str | None = None,
    skip_jwt_exp_shortcut: bool = False,
    jwt_exp_leeway_s: int = 0,
    verify_ssl: bool = False,
    proxy_url: str | None = None,
    timeout_ms: float | None = 15_000,
) -> dict[str, Any]:
    """Probe the saved AuthContext to confirm it is still authenticated.

    Decision tree:

    1. If the AuthContext stores a JWT bearer token AND it is mathematically
       past ``exp`` (with ``jwt_exp_leeway_s`` slack), mark the context as
       expired locally and return without any network call.
    2. Otherwise, resolve the validation URL: explicit argument ->
       ``metadata['validation_url']`` -> ``metadata['final_url']``.
    3. GET that URL with saved cookies + saved headers attached. Status in
       ``failure_status`` -> invalid; status in ``expected_status`` -> valid
       (subject to optional substring / JSON-path checks); other statuses
       are treated as ambiguous and reported as invalid.
    4. Patch ``metadata`` (``validated``, ``last_validated_at``,
       ``last_validation_status``, ``expired``, ``expired_reason``) and re-save.

    Returns a safe summary (no secret values).
    """
    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    ctx = handler.load_context(profile)
    if ctx is None:
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error=f"No saved auth context for profile {profile!r}",
            extra={"validated": False, "expired": None},
        )

    # ---- 1. JWT exp shortcut -------------------------------------------------
    bearer = extract_bearer_token(ctx)
    jwt_exp_value = parse_jwt_exp(bearer) if bearer else None
    if jwt_exp_value is not None:
        ctx.metadata["jwt_exp"] = jwt_exp_value
    if not skip_jwt_exp_shortcut and bearer:
        expired_locally = is_jwt_expired(bearer, leeway_s=jwt_exp_leeway_s)
        if expired_locally is True:
            ctx.metadata.update(
                {
                    "validated": False,
                    "expired": True,
                    "expired_reason": "jwt_exp",
                    "last_validated_at": _now_iso(),
                    "last_validation_status": None,
                }
            )
            _persist_metadata(handler, ctx)
            summary = safe_auth_summary(ctx)
            summary.update(
                {
                    "success": False,
                    "validated": False,
                    "expired": True,
                    "expired_reason": "jwt_exp",
                    "reason": "JWT past exp claim",
                    "jwt_exp": jwt_exp_value,
                }
            )
            return summary

    # ---- 2. Resolve probe URL ------------------------------------------------
    effective_url = (
        validation_url
        or ctx.metadata.get("validation_url")
        or ctx.metadata.get("final_url")
    )
    if not effective_url:
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error="No validation_url provided and metadata has no final_url to fall back to",
            extra={"validated": None},
        )

    # ---- 3. Network probe ----------------------------------------------------
    timeout_s = (timeout_ms or 15_000) / 1000.0
    jar = aiohttp.CookieJar(unsafe=True)
    _attach_cookies_to_jar(jar, ctx)
    headers: dict[str, str] = {"Accept": "*/*"}
    for k, v in (ctx.headers or {}).items():
        if v:
            headers[k] = v

    request_kwargs: dict[str, Any] = {"headers": headers, "allow_redirects": True}
    if proxy_url:
        request_kwargs["proxy"] = proxy_url

    status: int | None = None
    final_url: str = effective_url
    response_preview: str = ""
    try:
        async with aiohttp.ClientSession(
            cookie_jar=jar,
            connector=_build_aiohttp_connector(verify_ssl),
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as session:
            async with session.get(effective_url, **request_kwargs) as resp:
                status = resp.status
                final_url = str(resp.url)
                try:
                    text = await resp.text()
                except Exception:
                    text = ""
                response_preview = (text or "")[:500]
    except Exception as exc:
        logger.warning("Validation probe failed: %s", exc)
        ctx.metadata.update(
            {
                "validated": False,
                "expired": None,
                "expired_reason": "probe_error",
                "last_validated_at": _now_iso(),
                "last_validation_status": None,
            }
        )
        _persist_metadata(handler, ctx)
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error=str(exc),
            extra={"validated": False},
        )

    # ---- 4. Decide -----------------------------------------------------------
    validated = False
    expired = False
    expired_reason: str | None = None
    if status in failure_status:
        expired = True
        expired_reason = f"http_{status}"
    elif status in expected_status:
        validated = True
        if success_substring and success_substring not in (response_preview or ""):
            validated = False
            expired_reason = "missing_substring"
        if validated and success_jsonpath:
            try:
                payload = _json.loads(response_preview)
            except Exception:
                payload = None
            if extract_token_by_path(payload, success_jsonpath) is None:
                validated = False
                expired_reason = "missing_jsonpath"
    else:
        validated = False
        expired_reason = f"http_{status}"

    ctx.metadata.update(
        {
            "validation_url": effective_url,
            "validated": validated,
            "expired": expired,
            "expired_reason": expired_reason if not validated else None,
            "last_validated_at": _now_iso(),
            "last_validation_status": status,
        }
    )
    _persist_metadata(handler, ctx)

    summary = safe_auth_summary(ctx)
    summary.update(
        {
            "success": validated,
            "validated": validated,
            "expired": expired,
            "expired_reason": expired_reason if not validated else None,
            "validation_url": effective_url,
            "last_validation_status": status,
            "last_validated_at": ctx.metadata["last_validated_at"],
            "probe_final_url": final_url,
        }
    )
    return summary


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


async def refresh_auth_context_service(
    *,
    target: str,
    agent_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    profile: str = "default",
    refresh_url: str | None = None,
    refresh_method: str = "POST",
    refresh_headers: Mapping[str, str] | None = None,
    refresh_body: Any = None,
    # Model-supplied credential overrides for {{username}} / {{password}}
    # placeholders. Explicit values win over the wallet for this call.
    username: str | None = None,
    password: str | None = None,
    new_token_path: str = "access_token",
    new_token_header_name: str = "Authorization",
    new_token_header_format: str = "Bearer {token}",
    capture_cookies: bool = True,
    verify_ssl: bool = False,
    proxy_url: str | None = None,
    timeout_ms: float | None = 15_000,
) -> dict[str, Any]:
    """Refresh a saved AuthContext using a refresh endpoint.

    Looks up the refresh URL in this order:

    1. Explicit ``refresh_url`` argument.
    2. ``metadata['refresh_url']`` saved at authenticate-time.
    3. ``CredentialsStore.resolve(target, profile).refresh_url`` (wallet).

    The refresh request body supports the same ``{{key}}`` template syntax as
    JSON-flow authentication and additionally exposes ``{{access_token}}`` and
    ``{{refresh_token}}`` derived from the existing AuthContext.

    Cookies in the response are merged into the AuthContext (when
    ``capture_cookies=True``) and the ``Authorization`` header is rewritten
    from the new token. The AuthContext is re-saved IN PLACE under the same
    profile path.
    """
    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    ctx = handler.load_context(profile)
    if ctx is None:
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error=f"No saved auth context for profile {profile!r}",
        )

    creds = handler.resolve_credentials(profile)
    effective_refresh_url = (
        refresh_url
        or ctx.metadata.get("refresh_url")
        or creds.refresh_url
    )
    if not effective_refresh_url:
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error="No refresh_url available (explicit / metadata / wallet)",
            extra={"refreshed": False},
        )

    # Build the template context from credentials + existing tokens.
    # Precedence: explicit tool args > wallet > nothing.
    template_ctx: dict[str, Any] = {}
    eff_username = username if username is not None else creds.username
    eff_password = password if password is not None else creds.password
    if eff_username is not None:
        template_ctx["username"] = eff_username
    if eff_password is not None:
        template_ctx["password"] = eff_password
    bearer = extract_bearer_token(ctx)
    if bearer:
        template_ctx["access_token"] = bearer
    rt: str | None = None
    if ctx.browser_storage:
        rt = ctx.browser_storage.localStorage.get("refresh_token")
    if not rt:
        for cookie in ctx.cookies:
            if cookie.name.lower() == "refresh_token":
                rt = cookie.value
                break
    if rt:
        template_ctx["refresh_token"] = rt

    rendered_body = render_credential_template(refresh_body, template_ctx)
    headers: dict[str, str] = {"Accept": "application/json"}
    if rendered_body is not None and not isinstance(rendered_body, (str, bytes)):
        headers["Content-Type"] = "application/json"
    if refresh_headers:
        for k, v in refresh_headers.items():
            headers[str(k)] = str(render_credential_template(v, template_ctx))

    request_kwargs: dict[str, Any] = {"headers": headers}
    if proxy_url:
        request_kwargs["proxy"] = proxy_url
    if rendered_body is None:
        pass
    elif isinstance(rendered_body, (dict, list)):
        request_kwargs["json"] = rendered_body
    elif isinstance(rendered_body, (str, bytes)):
        request_kwargs["data"] = rendered_body
    else:
        request_kwargs["json"] = rendered_body

    timeout_s = (timeout_ms or 15_000) / 1000.0
    jar = aiohttp.CookieJar(unsafe=True)
    _attach_cookies_to_jar(jar, ctx)

    method = (refresh_method or "POST").upper()
    status: int | None = None
    final_url: str = effective_refresh_url
    payload: Any = None
    body_preview: str = ""
    new_token: str | None = None
    new_cookies: list[dict[str, Any]] = []
    try:
        async with aiohttp.ClientSession(
            cookie_jar=jar,
            connector=_build_aiohttp_connector(verify_ssl),
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as session:
            async with session.request(method, effective_refresh_url, **request_kwargs) as resp:
                status = resp.status
                final_url = str(resp.url)
                try:
                    payload = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    body_preview = (text or "")[:500]
                    try:
                        payload = _json.loads(text)
                    except Exception:
                        payload = None
                if status >= 400:
                    return _failure_summary(
                        target,
                        handler.target_slug,
                        agent_id,
                        session_id,
                        profile,
                        error=f"Refresh request returned HTTP {status}",
                        extra={
                            "final_url": final_url,
                            "response_preview": body_preview,
                            "refreshed": False,
                        },
                    )
                new_token = extract_token_by_path(payload, new_token_path)
                if capture_cookies:
                    new_cookies = cookies_from_aiohttp_jar(session.cookie_jar)
    except Exception as exc:
        logger.warning("Refresh request failed: %s", exc)
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error=str(exc),
            extra={"refreshed": False},
        )

    if not new_token and not new_cookies:
        return _failure_summary(
            target,
            handler.target_slug,
            agent_id,
            session_id,
            profile,
            error=(
                "Refresh response yielded no token and no cookies - refine "
                "new_token_path or set capture_cookies=true"
            ),
            extra={"final_url": final_url, "refreshed": False},
        )

    # Update AuthContext IN PLACE so other consumers keep their references.
    if new_token:
        try:
            ctx.headers[new_token_header_name] = new_token_header_format.format(token=new_token)
        except (KeyError, IndexError):
            ctx.headers[new_token_header_name] = new_token
    if new_cookies:
        existing_by_name = {c.name: c for c in ctx.cookies}
        for raw in new_cookies:
            try:
                existing_by_name[raw["name"]] = CookieRecord.model_validate(raw)
            except Exception:
                continue
        ctx.cookies = list(existing_by_name.values())
    ctx.metadata.update(
        {
            "last_refreshed_at": _now_iso(),
            "last_refresh_status": status,
            "refresh_url": effective_refresh_url,
            "validated": True,
            "expired": False,
            "expired_reason": None,
            "last_validated_at": _now_iso(),
            "last_validation_status": status,
            "cookies_count": len(ctx.cookies),
            "cookie_names": sorted({c.name for c in ctx.cookies}),
            "headers_available": sorted(ctx.headers.keys()),
        }
    )
    new_bearer = extract_bearer_token(ctx)
    if new_bearer:
        new_exp = parse_jwt_exp(new_bearer)
        if new_exp is not None:
            ctx.metadata["jwt_exp"] = new_exp
        else:
            ctx.metadata.pop("jwt_exp", None)
    _persist_metadata(handler, ctx)

    summary = safe_auth_summary(ctx)
    summary.update(
        {
            "success": True,
            "refreshed": True,
            "refresh_url": effective_refresh_url,
            "last_refreshed_at": ctx.metadata["last_refreshed_at"],
            "last_refresh_status": status,
            "validated": True,
            "new_token_obtained": bool(new_token),
            "new_cookies_obtained": bool(new_cookies),
        }
    )
    return summary


# ---------------------------------------------------------------------------
# pydantic-ai tools
# ---------------------------------------------------------------------------


@with_tool_events("validate_auth_context")
async def validate_auth_context(
    ctx: RunContext[RequesterDeps],
    profile: str = "default",
    validation_url: str | None = None,
    expected_status: list[int] | None = None,
    failure_status: list[int] | None = None,
    success_substring: str | None = None,
    success_jsonpath: str | None = None,
    skip_jwt_exp_shortcut: bool = False,
    jwt_exp_leeway_s: int = 0,
    verify_ssl: bool = False,
    timeout_ms: float | None = 15_000,
) -> dict[str, Any]:
    """Probe a saved AuthContext to confirm it is still authenticated.

    The AuthenticatorAgent owns this tool: it MUST pass ``validation_url``
    pointing to a real authenticated endpoint discovered in context (e.g.
    ``/api/me``, ``/profile``, ``/dashboard``). When omitted, the tool falls
    back to ``metadata['validation_url']`` / ``metadata['final_url']``.

    Returns secret-free metadata: ``validated``, ``expired``, ``expired_reason``,
    ``last_validation_status``, ``last_validated_at`` and the standard safe
    summary fields. Cookie/token values are NEVER returned.
    """
    deps = ctx.deps
    if getattr(deps, "agent_id", None) is None or getattr(deps, "session_id", None) is None:
        return {"success": False, "error": "agent_id and session_id are required"}
    return await validate_auth_context_service(
        target=deps.target,
        agent_id=deps.agent_id,
        session_id=deps.session_id,
        profile=profile,
        validation_url=validation_url,
        expected_status=tuple(expected_status) if expected_status else (200, 201, 202, 203, 204, 206, 207),
        failure_status=tuple(failure_status) if failure_status else (401, 403),
        success_substring=success_substring,
        success_jsonpath=success_jsonpath,
        skip_jwt_exp_shortcut=skip_jwt_exp_shortcut,
        jwt_exp_leeway_s=jwt_exp_leeway_s,
        verify_ssl=verify_ssl,
        proxy_url=deps.proxy_url,
        timeout_ms=timeout_ms,
    )


@with_tool_events("refresh_auth_context")
async def refresh_auth_context(
    ctx: RunContext[RequesterDeps],
    profile: str = "default",
    refresh_url: str | None = None,
    refresh_method: str = "POST",
    refresh_headers: dict[str, str] | None = None,
    refresh_body: Any = None,
    # Model-supplied credentials (override wallet for this call only).
    username: str | None = None,
    password: str | None = None,
    new_token_path: str = "access_token",
    new_token_header_name: str = "Authorization",
    new_token_header_format: str = "Bearer {token}",
    capture_cookies: bool = True,
    verify_ssl: bool = False,
    timeout_ms: float | None = 15_000,
) -> dict[str, Any]:
    """Refresh a saved AuthContext using a refresh endpoint.

    Use this when ``validate_auth_context`` reports ``expired=true`` and the
    wallet (or saved metadata) declares a ``refresh_url``. The tool updates
    the existing AuthContext in place: same profile, same disk file, same
    cookies (merged with new ones from the response). Only the bearer header
    and selected metadata fields change.

    ``refresh_body`` supports the same ``{{...}}`` template syntax as the
    JSON authenticate flow, plus ``{{access_token}}`` and ``{{refresh_token}}``
    pulled from the existing AuthContext.
    """
    deps = ctx.deps
    if getattr(deps, "agent_id", None) is None or getattr(deps, "session_id", None) is None:
        return {"success": False, "error": "agent_id and session_id are required"}
    return await refresh_auth_context_service(
        target=deps.target,
        agent_id=deps.agent_id,
        session_id=deps.session_id,
        profile=profile,
        refresh_url=refresh_url,
        refresh_method=refresh_method,
        refresh_headers=refresh_headers,
        refresh_body=refresh_body,
        username=username,
        password=password,
        new_token_path=new_token_path,
        new_token_header_name=new_token_header_name,
        new_token_header_format=new_token_header_format,
        capture_cookies=capture_cookies,
        verify_ssl=verify_ssl,
        proxy_url=deps.proxy_url,
        timeout_ms=timeout_ms,
    )


# ---------------------------------------------------------------------------
# Auto-validation gate used by consumer tools (Phase 13)
# ---------------------------------------------------------------------------


def _seconds_since(iso_timestamp: str | None) -> float | None:
    if not iso_timestamp:
        return None
    try:
        ts = _dt.datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds()


async def auto_validate_before_consume(
    *,
    target: str,
    agent_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    profile: str,
    validation_ttl_s: float = 60.0,
    force_validate: bool = False,
    skip_validation: bool = False,
    proxy_url: str | None = None,
    verify_ssl: bool = False,
) -> dict[str, Any] | None:
    """Run a cheap validation pass before a tool consumes an auth_profile.

    Returns:

    * ``None`` when the AuthContext is fresh enough (``last_validated_at``
      within ``validation_ttl_s``) or when ``skip_validation=True`` — the
      caller should proceed.
    * A safe-summary dict with ``success=False`` when validation says the
      auth is expired/invalid. The caller should NOT send the request and
      should surface this dict to the LLM so the supervisor can dispatch
      the AuthenticatorAgent to refresh / re-authenticate.

    JWT ``exp`` is always checked locally regardless of the TTL cache, since
    that costs nothing. The network probe only fires when no recent cached
    validation exists OR ``force_validate=True``.
    """
    if skip_validation:
        return None

    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    ctx = handler.load_context(profile)
    if ctx is None:
        # Consumer will report "no saved auth context" on its own; the auto
        # gate doesn't have anything to validate.
        return None

    # ---- Always check JWT exp locally (free) --------------------------------
    bearer = extract_bearer_token(ctx)
    if bearer:
        verdict = is_jwt_expired(bearer)
        if verdict is True:
            ctx.metadata.update(
                {
                    "validated": False,
                    "expired": True,
                    "expired_reason": "jwt_exp",
                    "last_validated_at": _now_iso(),
                    "last_validation_status": None,
                }
            )
            _persist_metadata(handler, ctx)
            summary = safe_auth_summary(ctx)
            summary.update(
                {
                    "success": False,
                    "validated": False,
                    "expired": True,
                    "expired_reason": "jwt_exp",
                    "reason": "JWT past exp claim",
                }
            )
            return summary

    # ---- Honour the cached validation if it is still fresh ------------------
    if not force_validate:
        last_validated = ctx.metadata.get("last_validated_at")
        age = _seconds_since(last_validated)
        if age is not None and age <= validation_ttl_s and ctx.metadata.get("validated"):
            return None

    # ---- Otherwise run a real probe via the standard service ----------------
    result = await validate_auth_context_service(
        target=target,
        agent_id=agent_id,
        session_id=session_id,
        profile=profile,
        validation_url=None,  # use metadata fallback chain
        proxy_url=proxy_url,
        verify_ssl=verify_ssl,
    )
    if result.get("validated") is True:
        return None
    # Validation failed (expired / probe error / no validation_url) - bubble
    # the safe summary up to the caller.
    return result


__all__ = [
    "validate_auth_context_service",
    "refresh_auth_context_service",
    "validate_auth_context",
    "refresh_auth_context",
    "auto_validate_before_consume",
]
