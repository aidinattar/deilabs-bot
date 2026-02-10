from dataclasses import dataclass

from .paths import AUTH_DIR

DEILABS_BASE = "https://deilabs.dei.unipd.it"
DEILABS_URL = f"{DEILABS_BASE}/"
LAB_IN_OUT_URL = f"{DEILABS_BASE}/laboratory_in_outs"


@dataclass
class DeilabsConfig:
    """
    Configuration for DeiLabs client.

    user_id: unique identifier for user (e.g. Telegram user id)
    lab_name: visible label in the lab select dropdown
    debug: if True, always save screenshots + HTML at key points
    """
    user_id: str
    lab_name: str = "DEI/A | 230 DEI/A"
    debug: bool = False

    @property
    def storage_state_path(self) -> str:
        """Path to the per-user Playwright storage state JSON."""
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        return str(AUTH_DIR / f"auth_{self.user_id}.json")
