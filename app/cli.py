"""Admin CLI.  python -m app.cli create-user --username alice --role analyst   (password is prompted)"""
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
    cu.add_argument("--username", required=True)
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
        auth_service.create_user(conn, args.username, pw, args.role)
    except Exception as exc:  # AppError carries a user-facing message
        print(f"Error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Created {args.role} '{args.username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
