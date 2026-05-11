from __future__ import annotations
from pydoll.exceptions import ArgumentAlreadyExistsInOptions

import asyncio
import json
import math
from collections.abc import Mapping, Sequence, Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.browser.tab import Tab
from pydoll.constants import Key
from pydoll.elements.web_element import WebElement
from pydoll.protocol.network.types import Cookie


def _timeout_seconds(timeout_ms: float | None, *, default_ms: float = 30_000, cap_s: int = 600) -> int:
    ms = float(timeout_ms if timeout_ms is not None else default_ms)
    seconds = max(1, int(math.ceil(ms / 1000.0)))
    return min(seconds, cap_s)

def _resolve_keyboard_key(key_name: str) -> Key:
    name = key_name.strip()
    aliases = {
        "Return": "ENTER",
        "Esc": "ESCAPE",
        "Spacebar": "SPACE",
        " ": "SPACE",
    }
    enum_name = aliases.get(name, name.replace(" ", "_").upper())
    if hasattr(Key, enum_name):
        return getattr(Key, enum_name)
    if len(name) == 1 and name.isalpha():
        letter = name.upper()
        if hasattr(Key, letter):
            return getattr(Key, letter)
    raise ValueError(
        f"Unsupported key_name {key_name!r} for Pydoll; use names from pydoll.constants.Key "
        f"(e.g. Enter → ENTER)."
    )


async def _query_one(tab: Tab, selector: str, *, timeout_ms: float | None) -> WebElement:
    timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
    el = await tab.query(selector, timeout=timeout_s, find_all=False, raise_exc=True)
    if el is None:
        raise RuntimeError(f"Element not found for selector: {selector!r}")
    if isinstance(el, list):
        raise RuntimeError(f"Expected one element for selector: {selector!r}")
    return el


async def _select_with_script(
    tab: Tab,
    selector: str,
    raw_value: Any,
    by: Literal["value", "label", "index"],
    *,
    timeout_ms: float | None,
) -> None:
    await _query_one(tab, selector, timeout_ms=timeout_ms)
    sel_json = json.dumps(selector)
    if by == "index":
        idx = int(raw_value)
        script = f"""
        (() => {{
          const el = document.querySelector({sel_json});
          if (!el || el.tagName !== 'SELECT') throw new Error('Expected SELECT');
          const idx = {idx};
          if (idx < 0 || idx >= el.options.length) throw new Error('index out of range');
          el.selectedIndex = idx;
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }})()
        """
    else:
        val_json = json.dumps(str(raw_value))
        by_json = json.dumps(by)
        script = f"""
        (() => {{
          const el = document.querySelector({sel_json});
          if (!el || el.tagName !== 'SELECT') throw new Error('Expected SELECT');
          const by = {by_json};
          const val = {val_json};
          let idx = -1;
          if (by === 'value') {{
            for (let i = 0; i < el.options.length; i++) {{
              if (String(el.options[i].value) === val) {{ idx = i; break; }}
            }}
          }} else {{
            for (let i = 0; i < el.options.length; i++) {{
              if (String(el.options[i].textContent).trim() === val) {{ idx = i; break; }}
            }}
          }}
          if (idx < 0 || idx >= el.options.length) throw new Error('option not found');
          el.selectedIndex = idx;
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }})()
        """
    await tab.execute_script(script)


async def _set_checked_with_script(
    tab: Tab,
    selector: str,
    checked: bool,
    *,
    timeout_ms: float | None,
) -> None:
    await _query_one(tab, selector, timeout_ms=timeout_ms)
    lit = "true" if checked else "false"
    script = f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) throw new Error('element not found');
      el.checked = {lit};
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """
    await tab.execute_script(script)


# ---------------------------------------------------------------------------
# Internal step dataclasses (shared between BrowserSession and tooling)
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class FillStep:
    selector: str
    context_key: str


@dataclass(frozen=True)
class SelectStep:
    selector: str
    context_key: str
    by: Literal["value", "label", "index"] = "value"


@dataclass(frozen=True)
class CheckStep:
    selector: str
    context_key: str


@dataclass(frozen=True)
class ClickStep:
    selector: str


@dataclass(frozen=True)
class PressStep:
    selector: str
    key: str = "Enter"


InteractionStep = FillStep | SelectStep | CheckStep | ClickStep | PressStep


class BrowserSession:
    """Generic browser automation engine backed by Pydoll (Chrome DevTools Protocol).

    This is the single source of truth for all browser interaction in the agent.
    It handles lifecycle (start/stop), navigation, DOM interaction, state
    extraction (cookies, storage, page source, screenshots), and session
    import/export so that authentication context can be persisted and resumed.

    All methods operate on the *default tab* unless a ``page`` argument is
    provided.  Callers outside this module never need to touch a Pydoll
    ``Tab`` directly.
    """

    def __init__(
        self,
        headless: bool = True,
        verify_ssl: bool = True,
        proxy_url: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._browser: Chrome | None = None
        self._tab: Tab | None = None
        self._default_tab: Tab | None = None
        self._headless = headless
        self._verify_ssl = verify_ssl
        self._proxy_url = proxy_url
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        self._browser_contexts: list[str] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _build_chromium_options(self) -> ChromiumOptions:
        """Build and return Chromium options with stealth, proxy and SSL flags."""
        opts = ChromiumOptions()
        opts.headless = self._headless
        try:
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--disable-extensions")
            opts.add_argument("--disable-popup-blocking")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-sync")
            opts.add_argument("--disable-translate")
            if self._proxy_url:
                opts.add_argument(f"--proxy-server={self._proxy_url}")
            if not self._verify_ssl:
                opts.add_argument("ignore-certification-errors")
            if self._user_agent:
                opts.add_argument(f"--user-agent={self._user_agent}")
            else:
                opts.add_argument(
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
        except ArgumentAlreadyExistsInOptions as e:
            print(f"Argument already exists in chromium options: {e}")
        return opts

    @property
    def started(self) -> bool:
        return self._browser is not None and self._tab is not None

    @property
    def browser(self) -> Chrome | None:
        """Active Pydoll ``Chrome`` instance, if started."""
        return self._browser

    @property
    def tab(self) -> Tab | None:
        """Primary tab used for ``goto`` / steps, if started."""
        return self._tab

    async def start(self) -> None:
        if self.started:
            return

        options = self._build_chromium_options()
        self._browser = Chrome(options=options)
        await self._browser.__aenter__()

        self._tab = await self._browser.start()
        self._browser_contexts.append(await self._browser.create_browser_context())
        self._default_tab = self._tab

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.__aexit__(None, None, None)
        self._browser = None
        self._tab = None
        self._default_tab = None

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        await self.stop()
        return None

    # ------------------------------------------------------------------
    # Tab helpers
    # ------------------------------------------------------------------

    async def _active_tab(self, page: Tab | None = None) -> Tab:
        if page is not None:
            return page
        if self._tab is not None:
            return self._tab
        raise RuntimeError("BrowserSession is not started; call start() or use async with.")

    async def new_tab(self) -> Tab:
        if not self._browser:
            raise RuntimeError("BrowserSession is not started; call start() or use async with.")
        return await self._browser.new_tab()

    async def list_tabs(self) -> list[Tab]:
        """Return all currently opened page tabs known to Chrome."""
        if not self._browser:
            raise RuntimeError("BrowserSession is not started; call start() or use async with.")
        return await self._browser.get_opened_tabs()

    async def current_target_ids(self) -> set[str]:
        """Return target IDs for all open page tabs."""
        tabs = await self.list_tabs()
        return {
            target_id
            for tab in tabs
            if (target_id := getattr(tab, "_target_id", None))
        }

    async def wait_for_new_tab(
        self,
        known_target_ids: set[str],
        *,
        timeout_ms: float | None = 15_000,
    ) -> Tab:
        """Wait for a new page tab/popup target not present in ``known_target_ids``."""
        timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
        end = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < end:
            for tab in await self.list_tabs():
                target_id = getattr(tab, "_target_id", None)
                if target_id and target_id not in known_target_ids:
                    return tab
            await asyncio.sleep(0.25)
        raise RuntimeError("No new browser tab/popup opened before timeout")

    async def wait_for_tab_closed(
        self,
        tab: Tab,
        *,
        timeout_ms: float | None = 30_000,
    ) -> bool:
        """Poll until ``tab`` disappears from Chrome's page targets."""
        target_id = getattr(tab, "_target_id", None)
        if not target_id:
            return True
        timeout_s = _timeout_seconds(timeout_ms, default_ms=30_000)
        end = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < end:
            ids = await self.current_target_ids()
            if target_id not in ids:
                return True
            await asyncio.sleep(0.25)
        return False

    async def default_page(self) -> Tab:
        """Return the main tab (Pydoll ``Tab``)."""
        if self._default_tab is None:
            raise RuntimeError("BrowserSession is not started; call start() or use async with.")
        return self._default_tab

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def goto(
        self,
        url: str,
        *,
        page: Tab | None = None,
        timeout_ms: float | None = None,
    ) -> None:
        """Navigate ``url`` on the active tab (or ``page``)."""
        tab = await self._active_tab(page)
        timeout_s = _timeout_seconds(timeout_ms, default_ms=30_000)
        await tab.go_to(url, timeout=timeout_s)

    async def refresh(self, *, page: Tab | None = None) -> None:
        """Refresh the active tab."""
        tab = await self._active_tab(page)
        await tab.refresh()

    # ------------------------------------------------------------------
    # State extraction (generic primitives for tooling)
    # ------------------------------------------------------------------

    async def get_url(self, *, page: Tab | None = None) -> str:
        tab = await self._active_tab(page)
        return await tab.current_url

    async def get_title(self, *, page: Tab | None = None) -> str:
        tab = await self._active_tab(page)
        return await tab.title

    async def get_page_source(self, *, page: Tab | None = None) -> str:
        tab = await self._active_tab(page)
        return await tab.page_source

    async def get_cookies(self, *, page: Tab | None = None) -> list[Cookie]:
        """Return all cookies visible to the active tab as plain dicts.

        Pydoll returns ``list[Cookie]`` where ``Cookie`` is a TypedDict.
        We forward the dicts verbatim so no field (e.g. ``size``, ``session``,
        ``sourcePort``) is lost.
        """
        tab = await self._active_tab(page)
        return await tab.get_cookies()

    async def set_cookies(
        self,
        cookies: Sequence[dict[str, Any]],
        *,
        page: Tab | None = None,
    ) -> None:
        """Install cookies into the browser context.

        Each cookie dict should have keys matching Pydoll's ``CookieParam``.
        Keys that are read-only in CDP (``size``, ``session``) are stripped
        automatically because ``CookieParam`` does not accept them.
        """
        tab = await self._active_tab(page)
        clean = []
        read_only = {"size", "session", "sameParty", "sourceScheme", "sourcePort"}
        for c in cookies:
            param = {k: v for k, v in c.items() if k not in read_only and v is not None}
            clean.append(param)
        if clean:
            await tab.set_cookies(clean)  # type: ignore[arg-type]

    async def delete_all_cookies(self, *, page: Tab | None = None) -> None:
        tab = await self._active_tab(page)
        await tab.delete_all_cookies()

    def _unwrap_evaluate(self, response: Any) -> Any:
        """Extract the JS value from a Pydoll ``EvaluateResponse``."""
        exc = response.get("result", {}).get("exceptionDetails")
        if exc:
            raise RuntimeError(exc.get("text", str(exc)))
        return response.get("result", {}).get("result", {}).get("value")

    async def get_local_storage(self, *, page: Tab | None = None) -> dict[str, str]:
        """Fetch ``localStorage`` for the current origin as a flat dict."""
        tab = await self._active_tab(page)
        response = await tab.execute_script("""
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out[k] = localStorage.getItem(k);
            }
            return out;
        """)
        value = self._unwrap_evaluate(response)
        return value if isinstance(value, dict) else {}

    async def get_session_storage(self, *, page: Tab | None = None) -> dict[str, str]:
        """Fetch ``sessionStorage`` for the current origin as a flat dict."""
        tab = await self._active_tab(page)
        response = await tab.execute_script("""
            const out = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                out[k] = sessionStorage.getItem(k);
            }
            return out;
        """)
        value = self._unwrap_evaluate(response)
        return value if isinstance(value, dict) else {}

    async def execute_script(self, script: str, *, page: Tab | None = None) -> Any:
        """Execute arbitrary JavaScript on the active tab and return the deserialized result."""
        tab = await self._active_tab(page)
        response = await tab.execute_script(script)
        return self._unwrap_evaluate(response)

    async def screenshot(
        self,
        *,
        path: str | Path | None = None,
        as_base64: bool = False,
        full_page: bool = False,
        page: Tab | None = None,
    ) -> str | None:
        """Take a screenshot of the active tab.

        Args:
            path: File path to save the screenshot (extension sets format).
            as_base64: Return a base64 string instead of saving.
            full_page: Scroll to bottom and capture the entire page.
            page: Optional tab override.

        Returns:
            Base64 string if ``as_base64=True``, otherwise ``None``.
        """
        tab = await self._active_tab(page)
        return await tab.take_screenshot(
            path=str(path) if path else None,
            as_base64=as_base64,
            beyond_viewport=full_page,
        )

    # ------------------------------------------------------------------
    # Waiting
    # ------------------------------------------------------------------

    async def wait_for_selector(
        self,
        selector: str,
        *,
        visible: bool = False,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> WebElement:
        """Wait up to ``timeout_ms`` for an element matching ``selector``.

        Raises ``RuntimeError`` if the element is not found.
        """
        tab = await self._active_tab(page)
        timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
        el = await tab.query(selector, timeout=timeout_s, find_all=False, raise_exc=True)
        if el is None:
            raise RuntimeError(f"Element not found for selector: {selector!r}")
        if isinstance(el, list):
            raise RuntimeError(f"Expected one element for selector: {selector!r}")
        if visible:
            await el.wait_until(is_visible=True, timeout=timeout_s)
        return el

    async def wait_for_url(
        self,
        predicate: str | Callable,
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> bool:
        """Poll until the current URL matches ``predicate``.

        ``predicate`` may be a substring to look for or a callable
        ``(url: str) -> bool``.
        """
        tab = await self._active_tab(page)
        timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
        if isinstance(predicate, str):
            check = lambda u: predicate in u
        else:
            check = predicate  # type: ignore[assignment]

        end = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < end:
            url = await tab.current_url
            if check(url):
                return True
            await asyncio.sleep(0.5)
        return False

    async def wait_for_cookie(
        self,
        cookie_names: Sequence[str],
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> bool:
        """Poll until at least one named cookie is present."""
        names = {n for n in cookie_names if n}
        if not names:
            return False
        timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
        end = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < end:
            try:
                cookies = await self.get_cookies(page=page)
                if any(c.get("name") in names for c in cookies):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def wait_for_storage_key(
        self,
        keys: Sequence[str],
        *,
        storage: Literal["local", "session", "any"] = "any",
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> bool:
        """Poll until at least one storage key is present."""
        wanted = {k for k in keys if k}
        if not wanted:
            return False
        timeout_s = _timeout_seconds(timeout_ms, default_ms=15_000)
        end = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < end:
            try:
                if storage in ("local", "any"):
                    local = await self.get_local_storage(page=page)
                    if wanted.intersection(local.keys()):
                        return True
                if storage in ("session", "any"):
                    session = await self.get_session_storage(page=page)
                    if wanted.intersection(session.keys()):
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def wait_for_auth_success(
        self,
        *,
        success_url_contains: str | None = None,
        success_selector: str | None = None,
        success_cookie_names: Sequence[str] | None = None,
        success_storage_keys: Sequence[str] | None = None,
        timeout_ms: float | None = 30_000,
        page: Tab | None = None,
    ) -> dict[str, Any]:
        """Wait until any configured authentication success signal is observed.

        Returns a dict with ``success`` and ``matched``. If no success signals are
        configured, returns success immediately so callers can still snapshot the
        browser state after running steps.
        """
        checks_configured = any([
            success_url_contains,
            success_selector,
            success_cookie_names,
            success_storage_keys,
        ])
        if not checks_configured:
            return {"success": True, "matched": ["no_explicit_success_condition"]}

        timeout_s = _timeout_seconds(timeout_ms, default_ms=30_000)
        end = asyncio.get_event_loop().time() + timeout_s
        matched: list[str] = []
        while asyncio.get_event_loop().time() < end:
            matched.clear()
            if success_url_contains:
                try:
                    if success_url_contains in await self.get_url(page=page):
                        matched.append("url")
                except Exception:
                    pass
            if success_selector:
                try:
                    await self.wait_for_selector(success_selector, timeout_ms=1_000, page=page)
                    matched.append("selector")
                except Exception:
                    pass
            if success_cookie_names:
                try:
                    cookies = await self.get_cookies(page=page)
                    names = {c.get("name") for c in cookies}
                    if names.intersection(set(success_cookie_names)):
                        matched.append("cookie")
                except Exception:
                    pass
            if success_storage_keys:
                try:
                    local = await self.get_local_storage(page=page)
                    session = await self.get_session_storage(page=page)
                    keys = set(local.keys()) | set(session.keys())
                    if keys.intersection(set(success_storage_keys)):
                        matched.append("storage")
                except Exception:
                    pass
            if matched:
                return {"success": True, "matched": list(matched)}
            await asyncio.sleep(0.5)
        return {"success": False, "matched": [], "error": "Timed out waiting for auth success"}

    # ------------------------------------------------------------------
    # DOM interaction (instance methods, no leaking Tab handles)
    # ------------------------------------------------------------------

    async def click(
        self,
        selector: str,
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        el = await self.wait_for_selector(selector, timeout_ms=timeout_ms, page=page)
        await el.click()

    async def fill(
        self,
        selector: str,
        value: str,
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        """Clear the element and type ``value`` into it."""
        el = await self.wait_for_selector(selector, timeout_ms=timeout_ms, page=page)
        await el.clear()
        await el.insert_text(value)

    async def select(
        self,
        selector: str,
        value: Any,
        *,
        by: Literal["value", "label", "index"] = "value",
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        """Select an option on a ``<select>`` element via in-page script."""
        tab = await self._active_tab(page)
        await _select_with_script(tab, selector, value, by, timeout_ms=timeout_ms)

    async def check(
        self,
        selector: str,
        checked: bool = True,
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        """Set ``checked`` on a checkbox / radio via in-page script."""
        tab = await self._active_tab(page)
        await _set_checked_with_script(tab, selector, checked, timeout_ms=timeout_ms)

    async def press(
        self,
        selector: str,
        key: str = "Enter",
        *,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        """Focus the element and send a keypress."""
        el = await self.wait_for_selector(selector, timeout_ms=timeout_ms, page=page)
        await el.focus()
        tab = await self._active_tab(page)
        await tab.keyboard.press(_resolve_keyboard_key(key))

    # ------------------------------------------------------------------
    # Context-driven steps (backward-compatible helpers)
    # ------------------------------------------------------------------

    @staticmethod
    def _context_value(
        context: Mapping[str, Any],
        key: str,
        *,
        optional: bool,
    ) -> Any:
        if key not in context:
            if optional:
                return None
            raise KeyError(key)
        return context[key]

    async def fill_from_context(
        self,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        optional: bool = False,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        value = self._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        text = "" if value is None else str(value)
        await self.fill(selector, value=text, timeout_ms=timeout_ms, page=page)

    async def select_from_context(
        self,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        by: Literal["value", "label", "index"] = "value",
        optional: bool = False,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        value = self._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        await self.select(selector, value, by=by, timeout_ms=timeout_ms, page=page)

    async def check_from_context(
        self,
        selector: str,
        context_key: str,
        context: Mapping[str, Any],
        *,
        optional: bool = False,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        value = self._context_value(context, context_key, optional=optional)
        if value is None and optional:
            return
        await self.check(selector, checked=bool(value), timeout_ms=timeout_ms, page=page)

    async def run_steps(
        self,
        steps: Sequence[InteractionStep],
        context: Mapping[str, Any],
        *,
        optional_keys: bool = False,
        timeout_ms: float | None = None,
        page: Tab | None = None,
    ) -> None:
        """Execute a batch of interaction steps on the default tab."""
        for step in steps:
            if isinstance(step, FillStep):
                await self.fill_from_context(
                    step.selector,
                    step.context_key,
                    context,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                    page=page,
                )
            elif isinstance(step, SelectStep):
                await self.select_from_context(
                    step.selector,
                    step.context_key,
                    context,
                    by=step.by,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                    page=page,
                )
            elif isinstance(step, CheckStep):
                await self.check_from_context(
                    step.selector,
                    step.context_key,
                    context,
                    optional=optional_keys,
                    timeout_ms=timeout_ms,
                    page=page,
                )
            elif isinstance(step, ClickStep):
                await self.click(step.selector, timeout_ms=timeout_ms, page=page)
            elif isinstance(step, PressStep):
                await self.press(step.selector, step.key, timeout_ms=timeout_ms, page=page)
            else:
                raise TypeError(f"Unsupported step type: {type(step)!r}")

    # ------------------------------------------------------------------
    # Session import / export (for auth persistence across tools)
    # ------------------------------------------------------------------

    async def export_state(self, *, page: Tab | None = None) -> dict[str, Any]:
        """Capture the current browser state as a JSON-serializable dict.

        Returns keys: ``cookies``, ``localStorage``, ``sessionStorage``,
        ``url``, ``title``.
        """
        return {
            "cookies": await self.get_cookies(page=page),
            "localStorage": await self.get_local_storage(page=page),
            "sessionStorage": await self.get_session_storage(page=page),
            "url": await self.get_url(page=page),
            "title": await self.get_title(page=page),
        }

    async def import_state(
        self,
        state: Mapping[str, Any],
        *,
        page: Tab | None = None,
        skip_navigation: bool = True,
    ) -> None:
        """Restore a previously exported browser state.

        Args:
            state: Dict produced by :meth:`export_state`.
            skip_navigation: If ``False``, also navigate to ``state["url"]``
                before restoring storage.
            page: Optional tab override.
        """
        if not skip_navigation and state.get("url"):
            await self.goto(state["url"], page=page)

        if state.get("cookies"):
            await self.set_cookies(state["cookies"], page=page)  # type: ignore[arg-type]

        if state.get("localStorage") or state.get("sessionStorage"):
            tab = await self._active_tab(page)
            ls = state.get("localStorage", {})
            ss = state.get("sessionStorage", {})
            script = f"""
            (() => {{
                const ls = {json.dumps(ls)};
                const ss = {json.dumps(ss)};
                Object.entries(ls).forEach(([k, v]) => localStorage.setItem(k, v));
                Object.entries(ss).forEach(([k, v]) => sessionStorage.setItem(k, v));
            }})()
            """
            await tab.execute_script(script)



