import os
import json
from datetime import datetime
from typing import Optional


class Logger:
    LOG_DIR = "logs"
    LOG_FILE = "deilabs.log"

    @classmethod
    def _log_path(cls) -> str:
        os.makedirs(cls.LOG_DIR, exist_ok=True)
        return os.path.join(cls.LOG_DIR, cls.LOG_FILE)

    @classmethod
    def log(
        cls,
        event: str,
        message: str,
        level: str = "INFO",
        url: Optional[str] = None,
        success: Optional[bool] = None,
        user_id: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "event": event,
            "message": message,
            "page_url": url,
            "success": success,
            "user_id": user_id,
        }
        with open(cls._log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # console log for dev convenience
        print(f"[{level}] {event}: {message} (user={user_id}, url={url})")
