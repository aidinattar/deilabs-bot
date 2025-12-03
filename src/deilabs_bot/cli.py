import argparse

from deilabs_bot import DeilabsConfig, DeilabsClient


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
