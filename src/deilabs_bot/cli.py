import argparse
from deilabs_bot import DeilabsConfig, DeilabsClient
from deilabs_bot.prefs import resolve_lab, set_lab_for_user


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

    # status
    status_parser = subparsers.add_parser("status", help="Check current lab status (no changes).")
    status_parser.add_argument("--user-id", required=True, help="User id")

    # exit
    exit_parser = subparsers.add_parser("exit", help="Leave the lab if you are inside.")
    exit_parser.add_argument("--user-id", required=True, help="User id")

    # setlab
    setlab_parser = subparsers.add_parser(
        "setlab", help="Set default lab name for this user."
    )
    setlab_parser.add_argument("--user-id", required=True, help="User id")
    setlab_parser.add_argument("--lab", required=True, help="Lab name as shown in the site.")

    return parser.parse_args()


def main():
    args = parse_args()
    cmd = args.command

    user_id = str(getattr(args, "user_id", ""))

    if cmd == "setlab":
        set_lab_for_user(user_id, args.lab)
        print(f"Default lab for user {user_id} set to: {args.lab}")
        return

    if cmd == "status":
        lab = resolve_lab(user_id, getattr(args, "lab", None))
        config = DeilabsConfig(user_id=user_id, lab_name=lab)
        client = DeilabsClient(config)
        msg = client.get_status()
        print(msg)
        return

    if cmd == "exit":
        lab = resolve_lab(user_id, getattr(args, "lab", None))
        config = DeilabsConfig(user_id=user_id, lab_name=lab)
        client = DeilabsClient(config)
        msg = client.leave_lab()
        print(msg)
        return

    if cmd == "login":
        lab = resolve_lab(user_id, getattr(args, "lab", None))
        config = DeilabsConfig(user_id=user_id, lab_name=lab, debug=True)
        client = DeilabsClient(config)
        client.interactive_login()
        return

    if cmd == "punch":
        lab = resolve_lab(user_id, getattr(args, "lab", None))
        config = DeilabsConfig(user_id=user_id, lab_name=lab, debug=getattr(args, "debug", False))
        client = DeilabsClient(config)
        msg = client.ensure_presence()
        print(msg)
        return


if __name__ == "__main__":
    main()
