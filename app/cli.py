"""Admin CLI.  python -m app.cli create-user --email alice@example.com --name "Alice" --role analyst   (password is prompted)"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.core.config import Settings
from app.db.init import init_database
from app.db.session import connect
from app.services import auth_service


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", default=None)
    cu.add_argument("--role", choices=["analyst", "admin"], required=True)
    args = p.parse_args(argv)
    settings = Settings.from_env()
    init_database(settings)
    pw = getpass.getpass("Password (min 10 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    conn = connect(settings.db_path)
    try:
        auth_service.create_user(conn, args.email, pw, args.role, args.name)
    except Exception as exc:  # AppError carries a user-facing message
        print(f"Error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Created {args.role} '{args.email}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
