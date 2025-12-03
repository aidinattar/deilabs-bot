# src/deilabs_bot/client.py
import os
from datetime import datetime

from playwright.sync_api import sync_playwright, Page

from .config import DeilabsConfig, DEILABS_URL, LAB_IN_OUT_URL
from .selectors import LAB_SELECTORS, ENTER_BUTTON_SELECTORS
from .logger import Logger


class DeilabsClient:
    def __init__(self, config: DeilabsConfig):
        self.config = config

    # ---------- Helpers ----------

    def _is_inside_lab(self, page: Page) -> bool:
        """Return True if the page indicates that the user is already inside the lab."""
        html = page.content()
        return ("You have entered the lab" in html) or ("Exit from lab" in html)

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
                page.wait_for_selector(sel, timeout=5000)
                page.select_option(sel, label=self.config.lab_name)
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
                page.click(btn_sel)
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

        page.wait_for_timeout(2000)

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
        # piccolo check amichevole sul DISPLAY
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

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(storage_state=self.config.storage_state_path)
            page = context.new_page()

            page.goto(LAB_IN_OUT_URL)
            page.wait_for_timeout(2000)
            Logger.log(
                "page_loaded",
                "laboratory_in_outs page opened.",
                url=page.url,
                user_id=self.config.user_id,
            )

            if self.config.debug:
                self.save_state(page, "before")

            # If redirected to login, session is expired
            if "login" in page.url or "shibboleth" in page.url:
                msg = (
                    "Session expired: please run the interactive login again "
                    f"for user_id={self.config.user_id}."
                )
                Logger.log(
                    "session_expired",
                    msg,
                    level="WARNING",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                browser.close()
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
                browser.close()
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
                    browser.close()
                    raise

            if self.config.debug:
                self.save_state(page, "after")

            browser.close()
            return msg

    def get_status(self) -> str:
        """
        Check current status without changing anything.

        Possibili risultati:
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

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(storage_state=self.config.storage_state_path)
            page = context.new_page()

            page.goto(LAB_IN_OUT_URL)
            page.wait_for_timeout(2000)

            if "login" in page.url or "shibboleth" in page.url:
                msg = (
                    "Session expired: please run the interactive login again "
                    f"for user_id={self.config.user_id}."
                )
                Logger.log(
                    "status_session_expired",
                    msg,
                    level="WARNING",
                    url=page.url,
                    user_id=self.config.user_id,
                    success=False,
                )
                browser.close()
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
                browser.close()
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
            browser.close()
            return msg
