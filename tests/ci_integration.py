import os
import re
import sys
import tempfile
import time
from urllib.parse import quote_plus

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pymssql

from app import create_app, totp
from app.users import UserStore

CSRF_RE = re.compile(r'name="_csrf" value="([0-9a-f]+)"')

HOST = os.environ.get("MSSQL_HOST", "127.0.0.1")
PORT = os.environ.get("MSSQL_PORT", "11433")
PASSWORD = os.environ.get("MSSQL_SA_PASSWORD", "YourStrong!Passw0rd")
DATABASE = os.environ.get("MSSQL_DATABASE", "AdventureWorksLT2012")


def get_reference_row():
    conn = pymssql.connect(
        server=HOST,
        port=PORT,
        user="sa",
        password=PASSWORD,
        database=DATABASE,
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT TOP 1 FullName, NationalID, HomeAddress, Phone"
        " FROM dbo.Members ORDER BY NationalID"
    )
    row = cur.fetchone()
    conn.close()
    assert row and all(v is not None for v in row), f"參考資料列異常：{row}"
    return row


def build_app(tmpdir):
    config_yaml = (
        "database:\n"
        "  backend: sqlserver\n"
        "  sqlserver:\n"
        f"    host: {HOST}\n"
        f"    port: {PORT}\n"
        "    user: sa\n"
        f'    password: "{PASSWORD}"\n'
        f"    database: {DATABASE}\n"
        "    table: dbo.Members\n"
        "search:\n"
        "  page_size: 20\n"
    )
    cfg_path = os.path.join(tmpdir, "config.yaml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(config_yaml)

    store = UserStore(os.path.join(tmpdir, "users.db"))
    secret = totp.generate_secret()
    store.create("ciadmin", "CiTest#2026x", secret)

    app = create_app(
        config_path=cfg_path,
        instance_path=os.path.join(tmpdir, "instance"),
        users_store=store,
    )
    app.config["TESTING"] = True
    return app, store, secret


def csrf(client, path):
    resp = client.get(path)
    match = CSRF_RE.search(resp.get_data(as_text=True))
    assert match, f"{path} 頁面找不到 CSRF token"
    return match.group(1)


def main():
    fullname, national_id, address, phone = get_reference_row()
    print(f"[1] 真實 MDF 資料讀取成功：{fullname} / {national_id} / {phone}")

    tmpdir = tempfile.mkdtemp(prefix="ci-mssql-")
    app, store, secret = build_app(tmpdir)
    client = app.test_client()

    resp = client.get("/search")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login"), "未登入應導向 /login"
    print("[2] 未登入防護通過")

    token = csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"username": "ciadmin", "password": "WrongPassword", "_csrf": token},
    )
    assert "帳號、密碼或驗證碼錯誤" in resp.get_data(as_text=True), "錯誤密碼應被拒絕"
    print("[3] 密碼錯誤防護通過")

    token = csrf(client, "/login")
    resp = client.post(
        "/login",
        data={"username": "ciadmin", "password": "CiTest#2026x", "_csrf": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login/totp"), "密碼正確應進 TOTP 步驟"
    print("[4] 第一階段（帳號密碼）通過")

    token = csrf(client, "/login/totp")
    resp = client.post("/login/totp", data={"code": "000000", "_csrf": token})
    assert "動態驗證碼錯誤或已被使用" in resp.get_data(as_text=True), "錯誤動態碼應被拒絕"
    print("[5] TOTP 錯誤碼防護通過")

    code = totp.hotp_at(secret, int(time.time()) // totp.STEP)
    token = csrf(client, "/login/totp")
    resp = client.post(
        "/login/totp",
        data={"code": code, "_csrf": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/search"), "TOTP 通過後應登入成功"
    print(f"[6] 第二階段（TOTP：{code}）通過")

    last_name = fullname.split()[-1]
    resp = client.get(f"/search?name={quote_plus(last_name)}")
    body = resp.get_data(as_text=True)
    assert fullname in body, f"姓名搜尋「{last_name}」應找到 {fullname}"
    print(f"[7] 姓名搜尋通過（{last_name} → {fullname}）")

    resp = client.get(f"/search?idcard={quote_plus(national_id)}")
    body = resp.get_data(as_text=True)
    assert fullname in body and national_id in body, "身份證精準搜尋應命中同一筆"
    print(f"[8] 身份證搜尋通過（{national_id}）")

    phone_tail = re.sub(r"\D", "", phone)[-4:]
    resp = client.get(f"/search?phone={quote_plus(phone_tail)}")
    body = resp.get_data(as_text=True)
    assert fullname in body, f"電話部分比對「{phone_tail}」應找到 {fullname}"
    print(f"[9] 電話搜尋通過（*{phone_tail}）")

    addr_key = str(address).split(",")[0][:20]
    resp = client.get(
        f"/search?address={quote_plus(addr_key)}&name={quote_plus(last_name)}"
    )
    body = resp.get_data(as_text=True)
    assert fullname in body, "地址+姓名複合條件應命中"
    print("[10] 複合條件搜尋（地址+姓名）通過")

    bad_id = "Z" + national_id[1:]
    resp = client.get(
        f"/search?name={quote_plus(last_name)}&idcard={quote_plus(bad_id)}"
    )
    body = resp.get_data(as_text=True)
    assert "查無符合條件的資料" in body, "矛盾條件應回報查無資料"
    print("[11] AND 條件無結果情境通過")

    print("\n=== INTEGRATION TEST PASSED：真實 SQL Server + MDF 全功能驗證成功 ===")


if __name__ == "__main__":
    main()
