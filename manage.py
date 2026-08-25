#!/usr/bin/env python3
import argparse
import getpass
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app import totp
from app.users import UserStore

INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def open_store():
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    return UserStore(os.path.join(INSTANCE_DIR, "users.db"))


def cmd_init_db(_args):
    open_store()
    print(f"使用者資料庫已建立：{os.path.join('instance', 'users.db')}")


def cmd_add_user(args):
    store = open_store()
    password = getpass.getpass(f"設定 {args.username} 的密碼：")
    if len(password) < 8:
        sys.exit("密碼長度至少 8 位")
    confirm = getpass.getpass("再次輸入密碼確認：")
    if password != confirm:
        sys.exit("兩次輸入的密碼不一致")
    secret = totp.generate_secret()
    try:
        store.create(args.username, password, secret)
    except ValueError as exc:
        sys.exit(str(exc))
    print()
    print(f"使用者 {args.username} 已建立。")
    print("請將下列密鑰加入離線驗證器 App（Google Authenticator、Aegis、Authy 等）：")
    print()
    print(f"  密鑰（Base32）：{secret}")
    print()
    print(f"  otpauth URI（可手動貼上或轉 QR Code）：")
    print(f"  {totp.provisioning_uri(secret, args.username)}")
    print()


def cmd_reset_totp(args):
    store = open_store()
    secret = totp.generate_secret()
    if not store.reset_totp(args.username, secret):
        sys.exit(f"找不到使用者 {args.username}")
    print(f"{args.username} 的 TOTP 密鑰已重設：{secret}")
    print(totp.provisioning_uri(secret, args.username))


def cmd_list_users(_args):
    store = open_store()
    rows = store.list_users()
    if not rows:
        print("(尚無使用者，請先執行 adduser)")
        return
    for row in rows:
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["created_at"]))
        print(f"{row['username']:<20}{created}")


def cmd_seed_demo(_args):
    from app.db import SqliteBackend

    backend = SqliteBackend({"path": os.path.join("instance", "demo.db"), "table": "Members"})
    count = backend.seed_demo()
    print(f"示範資料就緒：instance/demo.db（資料表 Members，本次新增 {count} 筆虛構資料）")


def main():
    parser = argparse.ArgumentParser(description="MDF 查詢系統管理工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="建立使用者資料庫")
    p_init.set_defaults(func=cmd_init_db)

    p_add = sub.add_parser("adduser", help="新增使用者並產生 TOTP 密鑰")
    p_add.add_argument("username")
    p_add.set_defaults(func=cmd_add_user)

    p_reset = sub.add_parser("reset-totp", help="重設使用者 TOTP 密鑰")
    p_reset.add_argument("username")
    p_reset.set_defaults(func=cmd_reset_totp)

    p_list = sub.add_parser("list-users", help="列出使用者")
    p_list.set_defaults(func=cmd_list_users)

    p_demo = sub.add_parser("seed-demo", help="寫入 SQLite 示範資料")
    p_demo.set_defaults(func=cmd_seed_demo)

    args = parser.parse_args()
    os.chdir(BASE_DIR)
    args.func(args)


if __name__ == "__main__":
    main()
