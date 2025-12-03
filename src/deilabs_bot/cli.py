import argparse
import json
import os
from deilabs_bot import DeilabsConfig, DeilabsClient

PREFS_FILE = "user_prefs.json"


def load_prefs():
    if not os.path.exists(PREFS_FILE):
        return {}
    with open(PREFS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_prefs(prefs):
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def get_lab_for_user(user_id: str) -> str | None:
    prefs = load_prefs()
    user = prefs.get(str(user_id))
    if not user:
        return None
    return user.get("lab_name")


def set_lab_for_user(user_id: str, lab_name: str) -> None:
    prefs = load_prefs()
    prefs[str(user_id)] = {"lab_name": lab_name}
    save_prefs(prefs)


def resolve_lab(user_id: str, lab_arg: str | None) -> str:
    if lab_arg:
        return lab_arg
    saved = get_lab_for_user(user_id)
    if saved:
        return saved
    # default fallback
    return "DEI/A | 230 DEI/A"


def parse_args():
    parser = argparse.ArgumentParser(description="DeiLabs presence helper (multi-user).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # login
    login_parser = subparsers.add_parser("login", help="Run interactive login and save session.")
    login_parser.add_argument("--user-id", required=True, help="Unique user id (e.g. Telegram id).")
    login_parser.add_argument(
        "--lab",
        type=str,
        default="DEI/A | 230 DEI/A",
        help="Lab name in the select dropdown.",
    )

    # punch
    punch_parser = subparsers.add_parser("punch", help="Ensure lab presence (headless).")
    punch_parser.add_argument("--user-id", required=True, help="Unique user id (e.g. Telegram id).")
    punch_parser.add_argument(
        "--lab",
        type=str,
        default="DEI/A | 230 DEI/A",
        help="Lab name in the select dropdown.",
    )
    punch_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (save screenshots and HTML).",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    config = DeilabsConfig(
        user_id=str(args.user_id),
        lab_name=args.lab,
        debug=getattr(args, "debug", False),
    )
    client = DeilabsClient(config)

    if args.command == "login":
        client.interactive_login()
    elif args.command == "punch":
        msg = client.ensure_presence()
        print(msg)


if __name__ == "__main__":
    main()
