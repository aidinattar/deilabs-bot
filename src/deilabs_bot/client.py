import os
import atexit
import threading
from datetime import datetime
from time import monotonic
from contextlib import contextmanager

from playwright.sync_api import (
    sync_playwright,
    Page,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from .config import DeilabsConfig, DEILABS_URL, LAB_IN_OUT_URL
from .selectors import LAB_SELECTORS, ENTER_BUTTON_SELECTORS, EXIT_BUTTON_SELECTORS
from .logger import Logger
# from playwright.sync_api import sync_playwright, TimeoutError


class DeilabsClient:
    _thread_local = threading.local()
    _runtime_lock = threading.Lock()
    _runtimes = []
    _atexit_registered = False

    def __init__(self, config: DeilabsConfig):
        self.config = config
        self.page_wait_timeout_ms = int(os.getenv("DEILABS_PAGE_WAIT_TIMEOUT_MS", "8000"))
        self.action_wait_timeout_ms = int(os.getenv("DEILABS_ACTION_WAIT_TIMEOUT_MS", "8000"))
        self.poll_interval_ms = int(os.getenv("DEILABS_POLL_INTERVAL_MS", "250"))
        self.selector_timeout_ms = int(os.getenv("DEILABS_SELECTOR_TIMEOUT_MS", "1200"))
        self.nav_retries = max(0, int(os.getenv("DEILABS_NAV_RETRIES", "2")))
        self.nav_retry_delay_ms = max(0, int(os.getenv("DEILABS_NAV_RETRY_DELAY_MS", "700")))
        self.reuse_browser = os.getenv("DEILABS_REUSE_BROWSER", "1").lower() not in {"0", "false", "no"}

    # ---------- Helpers ----------
    def _session_expired_message(self) -> str:
        return (
            "Session expired: please login again with "
            f"`deilabs login --user-id {self.config.user_id}`.\n"
            f"If you use the Telegram bot, upload the refreshed `auth_{self.config.user_id}.json` file."
        )

    def _is_session_expired(self, page: Page) -> bool:
        url = (page.url or "").lower()
        if "login" in url or "shibboleth" in url:
            return True
        html = page.content().lower()
        return ("session expired" in html) or ("session seems to have expired" in html)

    def _is_inside_lab(self, page: Page) -> bool:
        """Return True if the page indicates that the user is already inside the lab."""
        html = page.content()
        return ("You have entered the lab" in html) or ("Exit from lab" in html)

    @classmethod
    def _register_atexit(cls) -> None:
        if cls._atexit_registered:
            return
        with cls._runtime_lock:
            if cls._atexit_registered:
                return
            atexit.register(cls.shutdown_shared_browsers)
            cls._atexit_registered = True

    @classmethod
    def shutdown_shared_browsers(cls) -> None:
        with cls._runtime_lock:
            runtimes = list(cls._runtimes)
            cls._runtimes.clear()

        for runtime in runtimes:
            browser = runtime.get("browser")
            playwright = runtime.get("playwright")
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright is not None:
                    playwright.stop()
            except Exception:
                pass

    def _get_thread_runtime(self):
        runtime = getattr(self._thread_local, "runtime", None)
        if runtime is not None:
            browser = runtime.get("browser")
            try:
                if browser is not None and browser.is_connected():
                    return runtime
            except Exception:
                pass

        self._register_atexit()
        playwright = sync_playwright().start()
        browser = playwright.firefox.launch(headless=True)
        runtime = {"playwright": playwright, "browser": browser}
        self._thread_local.runtime = runtime
        with self._runtime_lock:
            self._runtimes.append(runtime)
        return runtime

    @contextmanager
    def _session_page(self):
        if self.reuse_browser:
            runtime = self._get_thread_runtime()
            context = runtime["browser"].new_context(storage_state=self.config.storage_state_path)
            page = context.new_page()
            try:
                yield page
            finally:
                context.close()
            return

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(storage_state=self.config.storage_state_path)
            page = context.new_page()
            try:
                yield page
            finally:
                browser.close()

    def _wait_until(self, page: Page, predicate, timeout_ms: int) -> bool:
        """Poll a predicate until it becomes true or timeout expires."""
        deadline = monotonic() + (timeout_ms / 1000.0)
        while monotonic() < deadline:
            try:
                if predicate():
                    return True
            except Exception:
                pass
            page.wait_for_timeout(self.poll_interval_ms)
        try:
            return bool(predicate())
        except Exception:
            return False

    def _wait_for_page_ready(self, page: Page) -> None:
        """Wait for a stable state after opening the in/out page."""
        def ready() -> bool:
            if self._is_session_expired(page):
                return True
            if self._are_labs_closed(page):
                return True
            if self._is_inside_lab(page):
                return True
            for sel in LAB_SELECTORS:
                if page.query_selector(sel) is not None:
                    return True
            return False

        self._wait_until(page, ready, timeout_ms=self.page_wait_timeout_ms)

    def _is_retryable_navigation_error(self, exc: Exception) -> bool:
        if isinstance(exc, PlaywrightTimeoutError):
            return True
        msg = str(exc).lower()
        retry_markers = (
            "ns_error_net_interrupt",
            "net::err_",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "network changed",
        )
        return any(marker in msg for marker in retry_markers)

    def _open_lab_page(self, page: Page) -> None:
        attempts = self.nav_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                page.goto(
                    LAB_IN_OUT_URL,
                    wait_until="domcontentloaded",
                    timeout=self.page_wait_timeout_ms,
                )
                return
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                if self._is_retryable_navigation_error(exc) and attempt < attempts:
                    Logger.log(
                        "lab_page_retry",
                        f"Navigation error ({attempt}/{attempts}): {exc}",
                        level="WARNING",
                        url=LAB_IN_OUT_URL,
                        user_id=self.config.user_id,
                        success=False,
                    )
                    page.wait_for_timeout(self.nav_retry_delay_ms * attempt)
                    continue
                raise

    def save_state(self, page: Page, tag: str) -> None:
        """Save screenshot + HTML for debugging."""
        os.makedirs("screenshots", exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base = os.path.join("screenshots", f"{timestamp}_{tag}")

        try:
            page.screenshot(path=f"{base}.png", full_page=True)
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            Logger.log(
                "save_state",
                f"Saved screenshot and HTML as {base}.*",
                url=page.url,
                user_id=self.config.user_id,
            )
        except Exception as e:
            Logger.log(
                "save_state_error",
                f"Could not save state: {e}",
                level="ERROR",
                user_id=self.config.user_id,
            )

    def _enter_lab(self, page: Page) -> str:
        """Select the lab and click Enter, with robust fallbacks and logging."""
        select_found = False
        for sel in LAB_SELECTORS:
            try:
                if page.query_selector(sel) is None:
                    continue
                page.select_option(sel, label=self.config.lab_name, timeout=self.selector_timeout_ms)
                Logger.log(
                    "select_lab",
                    f"Selected lab '{self.config.lab_name}' via selector {sel}",
                    url=page.url,
                    user_id=self.config.user_id,
                )
                select_found = True
                break
            except Exception:
                continue

        if not select_found:
            self.save_state(page, "no_select")
            return f"Could not find lab select element for '{self.config.lab_name}'."

        # --- Click the Enter button ---
        clicked = False
        for btn_sel in ENTER_BUTTON_SELECTORS:
            try:
                page.click(btn_sel, timeout=self.selector_timeout_ms, no_wait_after=True)
                Logger.log(
                    "click_enter",
                    f"Clicked Enter via selector {btn_sel}",
                    url=page.url,
                    user_id=self.config.user_id,
                )
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            self.save_state(page, "no_enter_button")
            return "Could not click Enter button."

        self._wait_until(
            page,
            lambda: self._is_inside_lab(page) or self._is_session_expired(page),
            timeout_ms=self.action_wait_timeout_ms,
        )

        if self._is_inside_lab(page):
            return f"Presence logged successfully for lab: {self.config.lab_name}"
        else:
            self.save_state(page, "enter_uncertain")
            return "Tried to log presence, but could not confirm success."

    def _are_labs_closed(self, page: Page) -> bool:
        """Return True if the page shows 'laboratories closed' message."""
        html = page.content()
        return (
            "Laboratories close" in html
            or "Laboratories are closed at this time" in html
        )

    # ---------- Public API ----------
    def interactive_login(self) -> None:
        """
        Open a visible browser window so the user can log in manually.
        After login, the authenticated storage state is saved to config.storage_state_path.

        NOTE: must be run from a graphical session (or via ssh -X / ssh -Y).
        """
        # Friendly sanity check on DISPLAY availability
        if not os.environ.get("DISPLAY"):
            Logger.log(
                "interactive_login_error",
                "No DISPLAY found. Run this command from a graphical session or via ssh -X.",
                level="ERROR",
                user_id=self.config.user_id,
            )
            raise RuntimeError(
                "No DISPLAY found. Run `cli.py login` from a graphical session "
                "on the machine, or via `ssh -X`, or perform login on another "
                "machine and copy the corresponding auth_<user_id>.json file."
            )

        Logger.log(
            "interactive_login_start",
            "Starting interactive login...",
            url=DEILABS_URL,
            user_id=self.config.user_id,
        )

        from playwright.sync_api import sync_playwright  # local import ok

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            page.goto(DEILABS_URL)
            Logger.log(
                "interactive_login",
                "Browser opened, please complete UniPD login.",
                url=page.url,
                user_id=self.config.user_id,
            )
            input(
                "When you see the DeiLabs page logged in, press ENTER here to save session... "
            )

            context.storage_state(path=self.config.storage_state_path)
            browser.close()

        Logger.log(
            "interactive_login_done",
            f"Session saved to {self.config.storage_state_path}",
            user_id=self.config.user_id,
            success=True,
        )

    def ensure_presence(self) -> str:
        """
        Headless run:
          - loads storage_state_path
          - opens the laboratory_in_outs page
          - checks if already inside
          - if not, selects lab and clicks Enter
        """
        Logger.log(
            "ensure_presence_start",
            "Ensuring lab presence (headless)...",
            url=LAB_IN_OUT_URL,
            user_id=self.config.user_id,
        )

        with self._session_page() as page:
            self._open_lab_page(page)
            self._wait_for_page_ready(page)
            Logger.log(
                "page_loaded",
                "laboratory_in_outs page opened.",
                url=page.url,
                user_id=self.config.user_id,
            )

            if self.config.debug:
                self.save_state(page, "before")

            # If redirected to login or explicit session-expired page, session is expired
            if self._is_session_expired(page):
                msg = self._session_expired_message()
                Logger.log(
                    "session_expired",
                    msg,
                    level="WARNING",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                return msg
            
            if self._are_labs_closed(page):
                msg = (
                    "Laboratories are currently closed. "
                    "Presence cannot be logged at this time."
                )
                Logger.log(
                    "labs_closed",
                    msg,
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                return msg

            if self._is_inside_lab(page):
                msg = "You are already inside the lab. Nothing to do."
                Logger.log(
                    "already_inside",
                    msg,
                    url=page.url,
                    user_id=self.config.user_id,
                    success=True,
                )
            else:
                try:
                    msg = self._enter_lab(page)
                    Logger.log(
                        "enter_lab",
                        msg,
                        url=page.url,
                        user_id=self.config.user_id,
                        success="successfully" in msg.lower(),
                    )
                except Exception as e:
                    Logger.log(
                        "enter_lab_error",
                        str(e),
                        level="ERROR",
                        url=page.url,
                        user_id=self.config.user_id,
                        success=False,
                    )
                    self.save_state(page, "enter_error")
                    raise

            if self.config.debug:
                self.save_state(page, "after")

            return msg
        
    def leave_lab(self) -> str:
        """
        Leave the lab if currently inside.

        - If the session is expired -> report it
        - If already outside -> return a coherent message (even when labs are closed)
        - If inside -> click 'Exit from lab' and verify the result
        """
        Logger.log(
            "leave_start",
            "Trying to leave lab...",
            url=LAB_IN_OUT_URL,
            user_id=self.config.user_id,
        )

        with self._session_page() as page:
            self._open_lab_page(page)
            self._wait_for_page_ready(page)

            if self._is_session_expired(page):
                msg = self._session_expired_message()
                Logger.log(
                    "leave_session_expired",
                    msg,
                    level="WARNING",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                return msg

            if not self._is_inside_lab(page):
                # Not inside: differentiate closed labs vs open labs
                if self._are_labs_closed(page):
                    msg = "You are not in any lab and laboratories are currently closed."
                else:
                    msg = "You are not in any lab."
                Logger.log(
                    "leave_not_inside",
                    msg,
                    url=page.url,
                    user_id=self.config.user_id,
                    success=True,
                )
                return msg

            clicked = False
            for sel in EXIT_BUTTON_SELECTORS:
                try:
                    page.click(sel, timeout=self.selector_timeout_ms, no_wait_after=True)
                    Logger.log(
                        "click_exit",
                        f"Clicked Exit via selector {sel}",
                        url=page.url,
                        user_id=self.config.user_id,
                    )
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                self.save_state(page, "no_exit_button")
                msg = "Could not find Exit button."
                Logger.log(
                    "leave_no_button",
                    msg,
                    level="ERROR",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                return msg

            self._wait_until(
                page,
                lambda: (not self._is_inside_lab(page)) or self._is_session_expired(page),
                timeout_ms=self.action_wait_timeout_ms,
            )

            # Double-check status
            if self._is_inside_lab(page):
                self.save_state(page, "exit_uncertain")
                msg = "Tried to leave lab, but status is uncertain (still appears inside)."
                success = False
            else:
                msg = "You have exited the lab."
                success = True

            Logger.log(
                "leave_result",
                msg,
                url=page.url,
                user_id=self.config.user_id,
                success=success,
            )
            return msg


    def get_status(self) -> str:
        """
        Check current status without changing anything.

        Possible outcomes:
        - "Session expired ..."
        - "Laboratories are currently closed ..."
        - "You are already inside the lab."
        - "You are not in any lab."
        """
        Logger.log(
            "status_start",
            "Checking lab status...",
            url=LAB_IN_OUT_URL,
            user_id=self.config.user_id,
        )

        with self._session_page() as page:
            self._open_lab_page(page)
            self._wait_for_page_ready(page)

            if self._is_session_expired(page):
                msg = self._session_expired_message()
                Logger.log(
                    "status_session_expired",
                    msg,
                    level="WARNING",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                return msg

            if self._are_labs_closed(page):
                msg = "Laboratories are currently closed."
                Logger.log(
                    "status_labs_closed",
                    msg,
                    url=page.url,
                    user_id=self.config.user_id,
                    success=True,
                )
                return msg

            if self._is_inside_lab(page):
                msg = "You are already inside the lab."
            else:
                msg = "You are not in any lab."

            Logger.log(
                "status_result",
                msg,
                url=page.url,
                user_id=self.config.user_id,
                success=True,
            )
            return msg
