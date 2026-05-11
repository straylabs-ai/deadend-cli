# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Authentication tool: browser, JSON/API, and HTTP Basic flows.

A single :func:`authenticate` tool is exposed to the LLM. Internally we
dispatch on ``auth_flow`` so all three flows persist the same
:class:`AuthContext` shape and can be transparently consumed by
``pw_send_payload(auth_profile=...)`` and ``browser_run_steps(auth_profile=...)``.

Flow dispatch table:

* ``form`` / ``oauth`` / ``authorization_code`` / ``callback`` / unset
  → real browser via :class:`BrowserSession` (Pydoll / CDP).
* ``json`` → POST credentials over ``aiohttp``, extract token by JSON path,
  capture ``Set-Cookie`` cookies.
* ``http`` → HTTP Basic auth: build ``Authorization: Basic <b64>`` from the
  wallet, optionally probe ``auth_url`` to validate.
"""

from __future__ import annotations

import asyncio
import ssl
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import aiohttp
from pydantic_ai import RunContext

from deadend_agent.auth_resolver import (
    AuthContext,
    AuthContextHandler,
    AuthFlow,
    AuthType,
    CredentialsRefs,
    auth_context_from_api_response,
    auth_context_from_browser_state,
    build_basic_auth_header,
    cookies_from_aiohttp_jar,
    extract_token_by_path,
    render_credential_template,
    safe_auth_summary,
    write_playwright_storage_state,
)
from deadend_agent.logging import logger
from deadend_agent.tools.browser.browser import BrowserSession, InteractionStep
from deadend_agent.tools.browser.run_browser_steps_tool import (
    BrowserStep,
    browser_step_to_interaction,
    parse_browser_steps,
)
from deadend_agent.tools.tool_wrappers import with_tool_events
from deadend_agent.utils.structures import RequesterDeps


# ---------------------------------------------------------------------------
# Flow dispatch
# ---------------------------------------------------------------------------

_BROWSER_FLOWS = {
    AuthFlow.FORM,
    AuthFlow.OAUTH,
    AuthFlow.AUTHORIZATION_CODE,
    AuthFlow.CALLBACK,
}


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))


def _coerce_auth_flow(value: Any) -> AuthFlow | None:
    if value is None or isinstance(value, AuthFlow):
        return value
    if isinstance(value, str):
        try:
            return AuthFlow(value)
        except ValueError:
            return None
    return None


def _resolve_credentials(
    creds: CredentialsRefs,
    *,
    override_username: str | None,
    override_password: str | None,
) -> tuple[str | None, str | None]:
    """Effective credentials for this call: explicit tool args > wallet.

    The model is allowed to pass credentials directly (for instance when
    credentials were discovered in context or pasted by the user). When it
    does, they take precedence over the wallet for this call. When it does
    not, the wallet still provides the values, so wallet-only flows keep
    working unchanged.
    """
    username = override_username if override_username is not None else creds.username
    password = override_password if override_password is not None else creds.password
    return username, password


def _merge_auth_context(
    user_context: Mapping[str, Any] | None,
    creds: CredentialsRefs,
    *,
    override_username: str | None = None,
    override_password: str | None = None,
) -> dict[str, Any]:
    """Merge model-provided context with resolved credentials.

    Precedence (highest first):

    1. Explicit ``override_username`` / ``override_password`` passed by the
       model (use case: creds discovered in context, creds typed by the user).
    2. Wallet-resolved credentials (``CredentialsRefs``).
    3. Other keys in ``user_context`` (e.g. ``tenant``, ``org``) are preserved
       as-is.

    ``login_url`` / ``refresh_url`` are filled from the wallet only if the
    caller did not provide them.
    """
    merged = dict(user_context or {})
    username, password = _resolve_credentials(
        creds,
        override_username=override_username,
        override_password=override_password,
    )
    if username is not None:
        merged["username"] = username
    if password is not None:
        merged["password"] = password
    if creds.login_url is not None:
        merged.setdefault("login_url", creds.login_url)
    if creds.refresh_url is not None:
        merged.setdefault("refresh_url", creds.refresh_url)
    return merged


def _failure(
    *,
    target: str,
    target_slug: str,
    agent_id: Any,
    session_id: Any,
    profile: str,
    error: str,
    auth_flow: Any = None,
    auth_type: Any = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "success": False,
        "auth_context_saved": False,
        "target": target,
        "target_slug": target_slug,
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "profile": profile,
        "auth_flow": _enum_value(auth_flow),
        "auth_type": _enum_value(auth_type),
        "error": error,
    }
    if extra:
        out.update(dict(extra))
    return out


def _persist_and_summarise(
    handler: AuthContextHandler,
    auth_context: AuthContext,
    profile: str,
    target: str,
    extra_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Save AuthContext + Playwright storage state and return a safe summary."""
    handler.save_context(profile, auth_context)
    write_playwright_storage_state(
        auth_context,
        handler.playwright_storage_path(profile),
        target=target,
    )
    summary = safe_auth_summary(auth_context)
    summary.update(
        {
            "success": True,
            "auth_context_saved": True,
            "playwright_storage_path": str(handler.playwright_storage_path(profile)),
        }
    )
    if extra_summary:
        summary.update(dict(extra_summary))
    return summary


# ---------------------------------------------------------------------------
# Browser flow (form / SPA / OAuth / popup OAuth)
# ---------------------------------------------------------------------------


async def _authenticate_via_browser(
    *,
    handler: AuthContextHandler,
    target: str,
    agent_id: Any,
    session_id: Any,
    profile: str,
    creds: CredentialsRefs,
    override_username: str | None,
    override_password: str | None,
    effective_auth_url: str,
    auth_flow: AuthFlow | None,
    auth_type: AuthType | None,
    steps: Sequence[BrowserStep | dict[str, Any]],
    context: Mapping[str, Any] | None,
    expects_popup: bool,
    popup_steps: Sequence[BrowserStep | dict[str, Any]],
    callback_url_contains: str | None,
    popup_callback_url_contains: str | None,
    wait_for_popup_close: bool,
    success_url_contains: str | None,
    success_selector: str | None,
    success_cookie_names: Sequence[str],
    success_storage_keys: Sequence[str],
    post_login_wait_ms: int,
    headless: bool,
    verify_ssl: bool,
    proxy_url: str | None,
    navigation_timeout_ms: float | None,
    action_timeout_ms: float | None,
) -> dict[str, Any]:
    parsed_steps = parse_browser_steps(steps)
    internal_steps: list[InteractionStep] = [browser_step_to_interaction(s) for s in parsed_steps]
    parsed_popup_steps = parse_browser_steps(popup_steps)
    internal_popup_steps: list[InteractionStep] = [
        browser_step_to_interaction(s) for s in parsed_popup_steps
    ]
    run_context = _merge_auth_context(
        context,
        creds,
        override_username=override_username,
        override_password=override_password,
    )

    callback_observed = False
    popup_callback_observed = False
    popup_closed = None

    try:
        async with BrowserSession(
            headless=headless,
            verify_ssl=verify_ssl,
            proxy_url=proxy_url,
        ) as browser:
            main_page = await browser.default_page()
            await browser.goto(effective_auth_url, page=main_page, timeout_ms=navigation_timeout_ms)

            if expects_popup:
                known_targets = await browser.current_target_ids()
                await browser.run_steps(
                    internal_steps,
                    run_context,
                    timeout_ms=action_timeout_ms,
                    page=main_page,
                )
                popup = await browser.wait_for_new_tab(
                    known_targets,
                    timeout_ms=navigation_timeout_ms,
                )
                await popup.bring_to_front()
                if internal_popup_steps:
                    await browser.run_steps(
                        internal_popup_steps,
                        run_context,
                        timeout_ms=action_timeout_ms,
                        page=popup,
                    )
                if popup_callback_url_contains:
                    popup_callback_observed = await browser.wait_for_url(
                        popup_callback_url_contains,
                        timeout_ms=navigation_timeout_ms,
                        page=popup,
                    )
                if wait_for_popup_close:
                    popup_closed = await browser.wait_for_tab_closed(
                        popup,
                        timeout_ms=navigation_timeout_ms,
                    )
                await main_page.bring_to_front()
            else:
                await browser.run_steps(
                    internal_steps,
                    run_context,
                    timeout_ms=action_timeout_ms,
                    page=main_page,
                )
                if callback_url_contains:
                    callback_observed = await browser.wait_for_url(
                        callback_url_contains,
                        timeout_ms=navigation_timeout_ms,
                        page=main_page,
                    )

            auth_success = await browser.wait_for_auth_success(
                success_url_contains=success_url_contains,
                success_selector=success_selector,
                success_cookie_names=success_cookie_names,
                success_storage_keys=success_storage_keys,
                timeout_ms=navigation_timeout_ms,
                page=main_page,
            )
            if not auth_success.get("success"):
                return _failure(
                    target=target,
                    target_slug=handler.target_slug,
                    agent_id=agent_id,
                    session_id=session_id,
                    profile=profile,
                    error=auth_success.get("error") or "Authentication success condition not met",
                    auth_flow=auth_flow,
                    auth_type=auth_type,
                    extra={
                        "callback_observed": callback_observed,
                        "popup_callback_observed": popup_callback_observed,
                        "popup_closed": popup_closed,
                    },
                )

            if post_login_wait_ms > 0:
                await asyncio.sleep(post_login_wait_ms / 1000.0)

            state = await browser.export_state(page=main_page)
    except Exception as exc:
        logger.warning("Browser authentication failed: %s", exc)
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error=str(exc),
            auth_flow=auth_flow,
            auth_type=auth_type,
        )

    auth_context = auth_context_from_browser_state(
        profile=profile,
        target=target,
        agent_id=str(agent_id),
        session_id=str(session_id),
        state=state,
        auth_url=effective_auth_url,
        auth_flow=_enum_value(auth_flow),
        auth_type=_enum_value(auth_type),
        extra_metadata={
            "callback_url_contains": callback_url_contains,
            "callback_observed": callback_observed,
            "expects_popup": expects_popup,
            "popup_callback_url_contains": popup_callback_url_contains,
            "popup_callback_observed": popup_callback_observed,
            "popup_closed": popup_closed,
            "success_matched": auth_success.get("matched", []),
        },
    )
    return _persist_and_summarise(
        handler,
        auth_context,
        profile,
        target,
        extra_summary={"success_matched": auth_success.get("matched", [])},
    )


# ---------------------------------------------------------------------------
# JSON / API auth flow
# ---------------------------------------------------------------------------


def _build_aiohttp_connector(verify_ssl: bool) -> aiohttp.TCPConnector:
    if verify_ssl:
        return aiohttp.TCPConnector()
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ssl_ctx)


async def _authenticate_via_json(
    *,
    handler: AuthContextHandler,
    target: str,
    agent_id: Any,
    session_id: Any,
    profile: str,
    creds: CredentialsRefs,
    override_username: str | None,
    override_password: str | None,
    effective_auth_url: str,
    auth_flow: AuthFlow | None,
    auth_type: AuthType | None,
    request_method: str,
    request_headers: Mapping[str, str] | None,
    request_body: Any,
    token_path: str | None,
    token_header_name: str,
    token_header_format: str,
    capture_cookies: bool,
    context: Mapping[str, Any] | None,
    verify_ssl: bool,
    proxy_url: str | None,
    navigation_timeout_ms: float | None,
) -> dict[str, Any]:
    if not effective_auth_url:
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error="JSON auth requires auth_url (login endpoint)",
            auth_flow=auth_flow,
            auth_type=auth_type,
        )

    template_context = _merge_auth_context(
        context,
        creds,
        override_username=override_username,
        override_password=override_password,
    )
    rendered_body = render_credential_template(request_body, template_context)
    headers: dict[str, str] = {"Accept": "application/json"}
    if rendered_body is not None and not isinstance(rendered_body, (str, bytes)):
        headers["Content-Type"] = "application/json"
    if request_headers:
        for k, v in request_headers.items():
            headers[str(k)] = str(render_credential_template(v, template_context))

    timeout_s = (navigation_timeout_ms or 30_000) / 1000.0
    connector = _build_aiohttp_connector(verify_ssl)
    method = (request_method or "POST").upper()

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

    final_url: str | None = None
    status: int | None = None
    body_preview: str = ""
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as session:
            async with session.request(method, effective_auth_url, **request_kwargs) as resp:
                status = resp.status
                final_url = str(resp.url)
                content_type = resp.headers.get("Content-Type", "")
                payload: Any = None
                text_body = ""
                try:
                    if "application/json" in content_type:
                        payload = await resp.json(content_type=None)
                    else:
                        text_body = await resp.text()
                        try:
                            payload = await resp.json(content_type=None)
                        except Exception:
                            payload = None
                except Exception:
                    payload = None
                    text_body = text_body or await resp.text()
                body_preview = (text_body or (str(payload) if payload is not None else ""))[:500]

                if status >= 400:
                    return _failure(
                        target=target,
                        target_slug=handler.target_slug,
                        agent_id=agent_id,
                        session_id=session_id,
                        profile=profile,
                        error=f"JSON auth request returned HTTP {status}",
                        auth_flow=auth_flow,
                        auth_type=auth_type,
                        extra={"final_url": final_url, "response_preview": body_preview},
                    )

                token = extract_token_by_path(payload, token_path) if token_path else None
                cookies = (
                    cookies_from_aiohttp_jar(session.cookie_jar) if capture_cookies else []
                )
    except Exception as exc:
        logger.warning("JSON authentication failed: %s", exc)
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error=str(exc),
            auth_flow=auth_flow,
            auth_type=auth_type,
        )

    if not token and not cookies:
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error=(
                "JSON auth response yielded no token and no cookies — refine "
                "token_path or set capture_cookies=true"
            ),
            auth_flow=auth_flow,
            auth_type=auth_type,
            extra={"final_url": final_url, "response_preview": body_preview},
        )

    auth_context = auth_context_from_api_response(
        profile=profile,
        target=target,
        agent_id=str(agent_id),
        session_id=str(session_id),
        token=token,
        token_header_name=token_header_name,
        token_header_format=token_header_format,
        cookies=cookies,
        final_url=final_url,
        auth_url=effective_auth_url,
        auth_flow=_enum_value(auth_flow) or AuthFlow.JSON.value,
        auth_type=_enum_value(auth_type) or (AuthType.BEARER_TOKEN.value if token else AuthType.SESSION_COOKIE.value),
        extra_metadata={
            "request_method": method,
            "response_status": status,
            "token_path": token_path,
            "token_header_name": token_header_name if token else None,
            "captured_cookies": bool(cookies),
        },
    )
    matched: list[str] = []
    if token:
        matched.append("token")
    if cookies:
        matched.append("cookies")
    return _persist_and_summarise(
        handler,
        auth_context,
        profile,
        target,
        extra_summary={"success_matched": matched, "response_status": status},
    )


# ---------------------------------------------------------------------------
# HTTP Basic auth flow
# ---------------------------------------------------------------------------


async def _authenticate_via_http_basic(
    *,
    handler: AuthContextHandler,
    target: str,
    agent_id: Any,
    session_id: Any,
    profile: str,
    creds: CredentialsRefs,
    override_username: str | None,
    override_password: str | None,
    effective_auth_url: str | None,
    auth_flow: AuthFlow | None,
    auth_type: AuthType | None,
    request_headers: Mapping[str, str] | None,
    verify_ssl: bool,
    proxy_url: str | None,
    navigation_timeout_ms: float | None,
) -> dict[str, Any]:
    eff_username, eff_password = _resolve_credentials(
        creds,
        override_username=override_username,
        override_password=override_password,
    )
    basic_header = build_basic_auth_header(eff_username, eff_password)
    if not basic_header:
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error="HTTP Basic auth requires both username and password in the wallet",
            auth_flow=auth_flow,
            auth_type=auth_type,
        )

    final_url: str | None = None
    status: int | None = None
    probed = False

    if effective_auth_url:
        probed = True
        timeout_s = (navigation_timeout_ms or 30_000) / 1000.0
        connector = _build_aiohttp_connector(verify_ssl)
        headers: dict[str, str] = {"Authorization": basic_header}
        if request_headers:
            for k, v in request_headers.items():
                headers[str(k)] = str(v)
        request_kwargs: dict[str, Any] = {"headers": headers}
        if proxy_url:
            request_kwargs["proxy"] = proxy_url
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as session:
                async with session.get(effective_auth_url, **request_kwargs) as resp:
                    status = resp.status
                    final_url = str(resp.url)
                    if status in (401, 403):
                        return _failure(
                            target=target,
                            target_slug=handler.target_slug,
                            agent_id=agent_id,
                            session_id=session_id,
                            profile=profile,
                            error=f"HTTP Basic probe returned {status} (credentials rejected)",
                            auth_flow=auth_flow,
                            auth_type=auth_type,
                            extra={"final_url": final_url},
                        )
        except Exception as exc:
            logger.warning("HTTP Basic probe failed: %s", exc)
            return _failure(
                target=target,
                target_slug=handler.target_slug,
                agent_id=agent_id,
                session_id=session_id,
                profile=profile,
                error=str(exc),
                auth_flow=auth_flow,
                auth_type=auth_type,
            )

    auth_context = auth_context_from_api_response(
        profile=profile,
        target=target,
        agent_id=str(agent_id),
        session_id=str(session_id),
        token=None,
        extra_headers={"Authorization": basic_header},
        cookies=[],
        final_url=final_url,
        auth_url=effective_auth_url,
        auth_flow=_enum_value(auth_flow) or AuthFlow.HTTP_LOGIN.value,
        auth_type=_enum_value(auth_type) or AuthType.API_KEY.value,
        extra_metadata={
            "probed": probed,
            "response_status": status,
            "scheme": "basic",
        },
    )
    matched: list[str] = ["basic"]
    if probed:
        matched.append("probe")
    return _persist_and_summarise(
        handler,
        auth_context,
        profile,
        target,
        extra_summary={"success_matched": matched, "response_status": status},
    )


# ---------------------------------------------------------------------------
# Public service + tool
# ---------------------------------------------------------------------------


async def authenticate_service(
    *,
    target: str,
    agent_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    auth_url: str | None = None,
    profile: str = "default",
    auth_flow: AuthFlow | str | None = None,
    auth_type: AuthType | None = None,
    # Model-supplied credential overrides (highest precedence)
    username: str | None = None,
    password: str | None = None,
    # Browser flow
    steps: Sequence[BrowserStep | dict[str, Any]] = (),
    context: Mapping[str, Any] | None = None,
    expects_popup: bool = False,
    popup_steps: Sequence[BrowserStep | dict[str, Any]] = (),
    callback_url_contains: str | None = None,
    popup_callback_url_contains: str | None = None,
    wait_for_popup_close: bool = True,
    success_url_contains: str | None = None,
    success_selector: str | None = None,
    success_cookie_names: Sequence[str] = (),
    success_storage_keys: Sequence[str] = (),
    post_login_wait_ms: int = 1500,
    headless: bool = True,
    # Common HTTP options
    verify_ssl: bool = False,
    proxy_url: str | None = None,
    navigation_timeout_ms: float | None = 30_000,
    action_timeout_ms: float | None = 15_000,
    # JSON / API flow
    request_method: str = "POST",
    request_headers: Mapping[str, str] | None = None,
    request_body: Any = None,
    token_path: str | None = None,
    token_header_name: str = "Authorization",
    token_header_format: str = "Bearer {token}",
    capture_cookies: bool = True,
) -> dict[str, Any]:
    """Internal dispatcher: pick a flow based on ``auth_flow`` and persist the result."""
    handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
    creds = handler.resolve_credentials(profile)
    flow = _coerce_auth_flow(auth_flow)
    effective_auth_url = auth_url or creds.login_url

    # JSON / API flow
    if flow is AuthFlow.JSON:
        return await _authenticate_via_json(
            handler=handler,
            target=target,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            creds=creds,
            override_username=username,
            override_password=password,
            effective_auth_url=effective_auth_url or "",
            auth_flow=flow,
            auth_type=auth_type,
            request_method=request_method,
            request_headers=request_headers,
            request_body=request_body,
            token_path=token_path,
            token_header_name=token_header_name,
            token_header_format=token_header_format,
            capture_cookies=capture_cookies,
            context=context,
            verify_ssl=verify_ssl,
            proxy_url=proxy_url,
            navigation_timeout_ms=navigation_timeout_ms,
        )

    # HTTP Basic flow
    if flow is AuthFlow.HTTP_LOGIN:
        return await _authenticate_via_http_basic(
            handler=handler,
            target=target,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            creds=creds,
            override_username=username,
            override_password=password,
            effective_auth_url=effective_auth_url,
            auth_flow=flow,
            auth_type=auth_type,
            request_headers=request_headers,
            verify_ssl=verify_ssl,
            proxy_url=proxy_url,
            navigation_timeout_ms=navigation_timeout_ms,
        )

    # Browser flow (default).
    if not effective_auth_url:
        return _failure(
            target=target,
            target_slug=handler.target_slug,
            agent_id=agent_id,
            session_id=session_id,
            profile=profile,
            error="No auth_url provided and no login_url found for target/profile",
            auth_flow=auth_flow,
            auth_type=auth_type,
        )
    return await _authenticate_via_browser(
        handler=handler,
        target=target,
        agent_id=agent_id,
        session_id=session_id,
        profile=profile,
        creds=creds,
        override_username=username,
        override_password=password,
        effective_auth_url=effective_auth_url,
        auth_flow=flow,
        auth_type=auth_type,
        steps=steps,
        context=context,
        expects_popup=expects_popup,
        popup_steps=popup_steps,
        callback_url_contains=callback_url_contains,
        popup_callback_url_contains=popup_callback_url_contains,
        wait_for_popup_close=wait_for_popup_close,
        success_url_contains=success_url_contains,
        success_selector=success_selector,
        success_cookie_names=success_cookie_names,
        success_storage_keys=success_storage_keys,
        post_login_wait_ms=post_login_wait_ms,
        headless=headless,
        verify_ssl=verify_ssl,
        proxy_url=proxy_url,
        navigation_timeout_ms=navigation_timeout_ms,
        action_timeout_ms=action_timeout_ms,
    )


@with_tool_events("authenticate")
async def authenticate(
    ctx: RunContext[RequesterDeps],
    auth_url: str | None = None,
    profile: str = "default",
    auth_flow: AuthFlow | None = None,
    auth_type: AuthType | None = None,
    # Model-supplied credentials. Use only when credentials were discovered
    # in context or supplied directly by the user. Wallet credentials remain
    # the preferred source for known targets/profiles.
    username: str | None = None,
    password: str | None = None,
    # Browser-flow params
    steps: list[BrowserStep] | None = None,
    context: dict[str, Any] | None = None,
    expects_popup: bool = False,
    popup_steps: list[BrowserStep] | None = None,
    callback_url_contains: str | None = None,
    popup_callback_url_contains: str | None = None,
    wait_for_popup_close: bool = True,
    success_url_contains: str | None = None,
    success_selector: str | None = None,
    success_cookie_names: list[str] | None = None,
    success_storage_keys: list[str] | None = None,
    post_login_wait_ms: int = 1500,
    headless: bool = True,
    # Common HTTP params
    verify_ssl: bool = False,
    navigation_timeout_ms: float | None = 30_000,
    action_timeout_ms: float | None = 15_000,
    # JSON / API params
    request_method: str = "POST",
    request_headers: dict[str, str] | None = None,
    request_body: Any = None,
    token_path: str | None = None,
    token_header_name: str = "Authorization",
    token_header_format: str = "Bearer {token}",
    capture_cookies: bool = True,
) -> dict[str, Any]:
    """Authenticate against the current target and save a reusable auth context.

    Dispatch is based on ``auth_flow``:

    * ``form`` / ``oauth`` / ``authorization_code`` / ``callback`` / unset →
      real browser flow (Pydoll). Use ``steps``, ``popup_steps``, ``success_*``
      and ``callback_*`` arguments.
    * ``json`` → POST credentials over HTTP. Use ``request_method``,
      ``request_headers``, ``request_body`` (with ``{{username}}`` /
      ``{{password}}`` placeholders), ``token_path``, ``token_header_name``,
      ``token_header_format`` and ``capture_cookies``.
    * ``http`` → HTTP Basic auth. Just provide ``profile`` (and optionally an
      ``auth_url`` to probe).

    Real wallet credentials are resolved from the credentials store and never
    returned. Successful runs save cookies, browser storage and derived auth
    headers under
    ``~/.deadend/agents/<agent_id>/<session_id>/auth_context/<profile>.json``.
    """
    deps = ctx.deps
    if getattr(deps, "agent_id", None) is None:
        return {
            "success": False,
            "auth_context_saved": False,
            "error": "ctx.deps.agent_id is required",
        }
    if getattr(deps, "session_id", None) is None:
        return {
            "success": False,
            "auth_context_saved": False,
            "error": "ctx.deps.session_id is required",
        }

    return await authenticate_service(
        target=deps.target,
        agent_id=deps.agent_id,
        session_id=deps.session_id,
        auth_url=auth_url,
        profile=profile,
        auth_flow=auth_flow,
        auth_type=auth_type,
        username=username,
        password=password,
        steps=steps or [],
        context=context or {},
        expects_popup=expects_popup,
        popup_steps=popup_steps or [],
        callback_url_contains=callback_url_contains,
        popup_callback_url_contains=popup_callback_url_contains,
        wait_for_popup_close=wait_for_popup_close,
        success_url_contains=success_url_contains,
        success_selector=success_selector,
        success_cookie_names=success_cookie_names or [],
        success_storage_keys=success_storage_keys or [],
        post_login_wait_ms=post_login_wait_ms,
        headless=headless,
        verify_ssl=verify_ssl,
        proxy_url=deps.proxy_url,
        navigation_timeout_ms=navigation_timeout_ms,
        action_timeout_ms=action_timeout_ms,
        request_method=request_method,
        request_headers=request_headers,
        request_body=request_body,
        token_path=token_path,
        token_header_name=token_header_name,
        token_header_format=token_header_format,
        capture_cookies=capture_cookies,
    )


__all__ = ["authenticate", "authenticate_service"]
