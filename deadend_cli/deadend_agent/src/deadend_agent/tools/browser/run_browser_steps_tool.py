# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from pydantic_ai import RunContext
from pydantic import BaseModel, Field, TypeAdapter
from deadend_agent.tools.browser.browser import BrowserSession
from deadend_agent.tools.tool_wrappers import with_tool_events
from deadend_agent.utils.structures import RequesterDeps
from deadend_agent.auth_resolver import AuthContextHandler, browser_state_from_auth_context
from deadend_agent.tools.browser.validate_refresh import auto_validate_before_consume


# --- LLM / tool-call surface: JSON-serializable steps (discriminated by `action`) ---
#
# The model passes three bundles to ``run_browser_steps`` / the ``browser_run_steps`` tool:
#   1) page_url — string, full URL to open first.
#   2) context — JSON object (string keys); values are looked up by each step's ``key`` field.
#   3) steps — JSON array; each item is one object with required ``action`` plus fields below.
# Steps run strictly in array order. Each ``fill``/``select``/``check`` reads ``context[key]``.
# See ``run_browser_steps`` for end-to-end behavior and return shape.


class BrowserFillStep(BaseModel):
    """One ``fill`` step: the model passes this object inside the ``steps`` array.

    **What the model passes:** ``{"action": "fill", "selector": "<css>", "key": "<context_key>"}``.
    ``selector`` must match exactly one visible control. ``key`` is the name of a key in the
    flat ``context`` object (not nested paths).

    **How it works:** After navigation, Pydoll resolves ``selector`` to a ``WebElement``, clears it,
    then inserts ``str(context[key])``. Missing ``key`` raises unless the run uses
    ``optional_missing_context_keys``.
    """

    model_config = {"extra": "forbid"}

    action: Literal["fill"] = "fill"
    selector: str = Field(
        ...,
        description="CSS selector for one visible input or textarea (e.g. #email, input[name='q']).",
    )
    key: str = Field(
        ...,
        description="Name of a key in `context`; its value is stringified and typed into the field.",
    )


class BrowserSelectStep(BaseModel):
    """One ``select`` step: the model passes this object inside the ``steps`` array.

    **What the model passes:** a dict with ``action``: ``"select"``, ``selector``, ``key``, and
    optional ``select_by`` (``"value"``, ``"label"``, or ``"index"``; default ``"value"``).

    **How it works:** A small in-page script selects the matching ``<option>`` on the ``<select>``
    found by ``selector`` and dispatches ``input``/``change`` events.
    """

    model_config = {"extra": "forbid"}

    action: Literal["select"] = "select"
    selector: str = Field(..., description="CSS selector for the <select> element.")
    key: str = Field(
        ...,
        description="Name of a key in `context`; its value is used as option value, visible label, or index.",
    )
    select_by: Literal["value", "label", "index"] = Field(
        default="value",
        description="How to match the option: HTML `value`, visible `label`, or 0-based `index` (context value must be an integer for index).",
    )


class BrowserCheckStep(BaseModel):
    """One ``check`` step: the model passes this object inside the ``steps`` array.

    **What the model passes:** ``{"action": "check", "selector": "<css>", "key": "<context_key>"}``.

    **How it works:** An in-page script sets ``checked`` from ``bool(context[key])`` and dispatches
    ``input``/``change`` on the checkbox.
    """

    model_config = {"extra": "forbid"}

    action: Literal["check"] = "check"
    selector: str = Field(..., description="CSS selector for the checkbox input.")
    key: str = Field(
        ...,
        description="Name of a key in `context`; truthy checks the box, falsey unchecks.",
    )


class BrowserClickStep(BaseModel):
    """One ``click`` step: the model passes this object inside the ``steps`` array.

    **What the model passes:** ``{"action": "click", "selector": "<css>"}``. No ``key``; nothing
    is read from ``context`` for this step.

    **How it works:** Pydoll clicks the first element matching ``selector``.
    """

    model_config = {"extra": "forbid"}

    action: Literal["click"] = "click"
    selector: str = Field(
        ...,
        description="CSS selector for the element to click (e.g. button[type='submit'], #login-btn).",
    )


class BrowserPressStep(BaseModel):
    """One ``press`` step: the model passes this object inside the ``steps`` array.

    **What the model passes:**
    ``{"action": "press", "selector": "<css>", "key_name": "Enter"}``. ``key_name`` defaults to
    ``"Enter"`` if omitted. No ``context`` lookup.

    **How it works:** The element is focused, then ``tab.keyboard.press`` sends a ``Key`` from
    Pydoll's enum (e.g. ``Enter`` → ``Key.ENTER``). Unsupported names raise a clear error.
    """

    model_config = {"extra": "forbid"}

    action: Literal["press"] = "press"
    selector: str = Field(
        ...,
        description="CSS selector for the element to focus before sending the key.",
    )
    key_name: str = Field(
        default="Enter",
        description="Key name (Pydoll ``Key`` enum), e.g. Enter, Tab, Escape.",
    )


# ``BrowserStep`` is the discriminated union type for one element of ``steps``. The model passes
# a JSON array of objects; each object must set ``action`` to one of: fill, select, check, click, press.
BrowserStep = Annotated[
    Union[
        BrowserFillStep,
        BrowserSelectStep,
        BrowserCheckStep,
        BrowserClickStep,
        BrowserPressStep,
    ],
    Field(discriminator="action"),
]


def _browser_steps_adapter() -> TypeAdapter[list[BrowserStep]]:
    return TypeAdapter(list[BrowserStep])


def parse_browser_steps(steps: Sequence[BrowserStep | dict[str, Any]]) -> list[BrowserStep]:
    """Turn what the model sent into validated step objects.

    **What the model passes:** ``steps`` is a list where each element is either already a
    ``Browser*Step`` model or a plain ``dict`` shaped like the tool JSON (each dict must include
    ``action`` so Pydantic can pick the right variant: ``fill``, ``select``, ``check``, ``click``,
    or ``press``).

    **How it works:** ``TypeAdapter(list[BrowserStep]).validate_python`` coerces dicts to the
    correct step class and rejects unknown ``action`` values or wrong field sets.
    """
    return _browser_steps_adapter().validate_python(list(steps))


# --- Internal execution (used by run_browser_steps) ---

from deadend_agent.tools.browser.browser import (
    FillStep,
    SelectStep,
    CheckStep,
    ClickStep,
    PressStep,
    InteractionStep,
)


def browser_step_to_interaction(step: BrowserStep) -> InteractionStep:
    if isinstance(step, BrowserFillStep):
        return FillStep(step.selector, step.key)
    if isinstance(step, BrowserSelectStep):
        return SelectStep(step.selector, step.key, step.select_by)
    if isinstance(step, BrowserCheckStep):
        return CheckStep(step.selector, step.key)
    if isinstance(step, BrowserClickStep):
        return ClickStep(step.selector)
    if isinstance(step, BrowserPressStep):
        return PressStep(step.selector, step.key_name)
    raise TypeError(type(step))

async def run_browser_steps(
    *,
    page_url: str,
    context: Mapping[str, Any],
    steps: Sequence[BrowserStep | dict[str, Any]],
    headless: bool = True,
    verify_ssl: bool = True,
    proxy_url: str | None = None,
    optional_missing_context_keys: bool = False,
    navigation_timeout_ms: float | None = 30_000,
    action_timeout_ms: float | None = 15_000,
    auth_state: Mapping[str, Any] | None = None,
    auth_profile: str | None = None,
) -> dict[str, Any]:
    """Run a full headless browser interaction from arguments the model can supply as JSON."""
    parsed = parse_browser_steps(steps)
    internal: list[InteractionStep] = [browser_step_to_interaction(s) for s in parsed]
    out: dict[str, Any] = {
        "success": False,
        "error": None,
        "final_url": None,
        "page_title": None,
        "steps_run": len(parsed),
        "authenticated": bool(auth_state),
        "auth_profile": auth_profile,
    }
    try:
        async with BrowserSession(
            headless=headless,
            verify_ssl=verify_ssl,
            proxy_url=proxy_url,
        ) as browser:
            await browser.goto(page_url, timeout_ms=navigation_timeout_ms)
            if auth_state:
                await browser.import_state(auth_state)
                # Revisit after importing cookies/storage so the app boots with auth.
                await browser.goto(page_url, timeout_ms=navigation_timeout_ms)
            await browser.run_steps(
                internal,
                context,
                optional_keys=optional_missing_context_keys,
                timeout_ms=action_timeout_ms,
            )
            out["final_url"] = await browser.get_url()
            out["page_title"] = await browser.get_title()
            out["success"] = True
    except Exception as e:
        out["error"] = str(e)
    return out


@with_tool_events("browser_run_steps")
async def browser_run_steps(
    ctx: RunContext[RequesterDeps],
    page_url: str,
    steps: list[BrowserStep],
    context: dict[str, Any],
    verify_ssl: bool = False,
    optional_missing_context_keys: bool = False,
    navigation_timeout_ms: float | None = 30_000,
    action_timeout_ms: float | None = 15_000,
    auth_profile: str | None = None,
    force_validate_auth: bool = False,
    skip_auth_validation: bool = False,
    auth_validation_ttl_s: float = 60.0,
) -> dict[str, Any]:
    """Open one URL in a headless Chrome session (Pydoll, CDP) and run a scripted list of UI actions.

    This is the **pydantic-ai tool** the LLM invokes. Arguments are JSON-serializable: there is
    no raw ``Tab`` object in the schema (Pydoll runs under the hood).

    **When to use:** HTML forms or SPAs where raw HTTP (``pw_send_payload``) is awkward—e.g. DOM
    scripts, embedded CSRF tokens, or multi-step UI. Prefer HTTP when the interaction is pure API.

    **What the model passes (tool arguments):**

    - ``page_url`` (str): Full URL opened first (e.g. ``https://example.com/login``).
    - ``context`` (dict): Flat map of string keys to string/bool/number values. Steps that use
      ``key`` read ``context[key]`` at execution time. Put credentials and any typed values here.
    - ``steps`` (list): Ordered list of step objects. Each object **must** include ``action``,
      one of ``fill``, ``select``, ``check``, ``click``, ``press``. Exact fields per action match
      the Pydantic models in ``deadend_agent.tools.browser.browser`` (e.g. ``fill`` needs
      ``selector`` and ``key``; ``click`` needs only ``selector``; ``press`` adds optional
      ``key_name``, default ``Enter``). The model should output the same shapes it would send as JSON.

    **How it works:** A new browser session is started. The tool loads ``page_url``, then runs
    each step in order on that tab (timeouts: ``navigation_timeout_ms`` for the initial load,
    ``action_timeout_ms`` for each locator action). ``ctx.deps.proxy_url`` is applied if set.
    The browser is always closed afterward, success or failure.

    **Other parameters:** ``verify_ssl`` — if false, TLS certificate errors on navigation are ignored
    (same idea as ``pw_send_payload``). ``optional_missing_context_keys`` — if true, missing
    ``context`` keys for fill/select/check are skipped instead of erroring.

    **Returns:** The same dict as ``run_browser_steps``: ``success``, ``error``, ``final_url``,
    ``page_title``, ``steps_run``. The model should read ``success`` and ``error`` first.

    **Selectors:** Use stable selectors taken from real HTML (``id``, ``name``, ``data-*``). Do not
    guess paths. This tool does not substitute credential placeholders in HTTP bodies; values must
    appear in ``context`` and be wired via ``key`` on each step.
    """
    auth_state: dict[str, Any] | None = None
    if auth_profile:
        if getattr(ctx.deps, "agent_id", None) is None:
            return {"success": False, "error": "ctx.deps.agent_id is required for auth_profile", "authenticated": False, "auth_profile": auth_profile}
        if getattr(ctx.deps, "session_id", None) is None:
            return {"success": False, "error": "ctx.deps.session_id is required for auth_profile", "authenticated": False, "auth_profile": auth_profile}
        # Phase 13: validate the saved AuthContext before consuming it.
        validation_failure = await auto_validate_before_consume(
            target=ctx.deps.target,
            agent_id=ctx.deps.agent_id,
            session_id=ctx.deps.session_id,
            profile=auth_profile,
            validation_ttl_s=auth_validation_ttl_s,
            force_validate=force_validate_auth,
            skip_validation=skip_auth_validation,
            proxy_url=ctx.deps.proxy_url,
            verify_ssl=verify_ssl,
        )
        if validation_failure is not None:
            return {
                "success": False,
                "authenticated": False,
                "auth_profile": auth_profile,
                "expired": validation_failure.get("expired"),
                "expired_reason": validation_failure.get("expired_reason"),
                "validated": False,
                "hint": "call refresh_auth_context (if a refresh_url exists) or re-run authenticate",
                "error": (
                    validation_failure.get("error")
                    or f"Saved auth_profile {auth_profile!r} is no longer valid"
                ),
            }
        handler = AuthContextHandler(ctx.deps.target, ctx.deps.agent_id, ctx.deps.session_id)
        auth_context = handler.load_context(auth_profile)
        if auth_context is None:
            return {"success": False, "error": f"No auth context saved for profile {auth_profile!r}", "authenticated": False, "auth_profile": auth_profile}
        auth_state = browser_state_from_auth_context(auth_context)

    return await run_browser_steps(
        page_url=page_url,
        steps=steps,
        context=context,
        headless=True,
        verify_ssl=verify_ssl,
        proxy_url=ctx.deps.proxy_url,
        optional_missing_context_keys=optional_missing_context_keys,
        navigation_timeout_ms=navigation_timeout_ms,
        action_timeout_ms=action_timeout_ms,
        auth_state=auth_state,
        auth_profile=auth_profile,
    )


__all__ = [
    "BrowserFillStep",
    "BrowserSelectStep",
    "BrowserCheckStep",
    "BrowserClickStep",
    "BrowserPressStep",
    "BrowserStep",
    "parse_browser_steps",
    "FillStep",
    "SelectStep",
    "CheckStep",
    "ClickStep",
    "PressStep",
    "InteractionStep",
    "browser_step_to_interaction",
    "run_browser_steps",
    "browser_run_steps",
]
