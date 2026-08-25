import os
import re
import tempfile
import time
import unittest

from app import create_app
from app import totp
from app.db import SqliteBackend
from app.users import UserStore

CSRF_RE = re.compile(r'name="_csrf" value="([0-9a-f]+)"')


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mdfedit-test-")
        users_db = os.path.join(self.tmp, "users.db")
        demo_db = os.path.join(self.tmp, "demo.db")

        self.store = UserStore(users_db)
        self.secret = totp.generate_secret()
        self.store.create("tester", "TestPass123!", self.secret)

        backend = SqliteBackend({"path": demo_db, "table": "Members"})
        backend.seed_demo()

        self.app = create_app(
            config_path="/nonexistent/config.yaml",
            instance_path=os.path.join(self.tmp, "instance"),
            users_store=self.store,
            db_backend=backend,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _csrf(self, resp):
        match = CSRF_RE.search(resp.get_data(as_text=True))
        self.assertIsNotNone(match, "找不到 CSRF token")
        return match.group(1)

    def _login(self, username="tester", password="TestPass123!"):
        resp = self.client.get("/login")
        token = self._csrf(resp)
        resp = self.client.post(
            "/login",
            data={"username": username, "password": password, "_csrf": token},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/login/totp"))
        resp = self.client.get("/login/totp")
        return self._csrf(resp)

    def _totp_code(self, offset_seconds=0):
        counter = int(time.time() + offset_seconds) // totp.STEP
        return totp.hotp_at(self.secret, counter)

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/login"))

    def test_wrong_password_stays_on_login(self):
        resp = self.client.get("/login")
        token = self._csrf(resp)
        resp = self.client.post(
            "/login",
            data={"username": "tester", "password": "WrongPass!", "_csrf": token},
        )
        body = resp.get_data(as_text=True)
        self.assertIn("帳號、密碼或驗證碼錯誤", body)

    def test_wrong_totp_rejected(self):
        token = self._login()
        resp = self.client.post(
            "/login/totp",
            data={"code": "000000", "_csrf": token},
        )
        body = resp.get_data(as_text=True)
        self.assertIn("動態驗證碼錯誤或已被使用", body)

    def test_full_login_and_search_by_name(self):
        token = self._login()
        resp = self.client.post(
            "/login/totp",
            data={"code": self._totp_code(), "_csrf": token},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/search"))

        resp = self.client.get("/search?name=%E7%8E%8B%E5%B0%8F%E7%BE%8E")
        body = resp.get_data(as_text=True)
        self.assertIn("王小美", body)
        self.assertIn("A289635741", body)

    def test_search_by_idcard_phone_address(self):
        self._complete_login()
        cases = [
            ("idcard", "B187654320", "王大明"),
            ("phone", "0933-555-888", "李俊宏"),
            ("address", "左營", "林雅婷"),
        ]
        for field, value, expect in cases:
            with self.subTest(field=field):
                resp = self.client.get(f"/search?{field}={value}")
                body = resp.get_data(as_text=True)
                self.assertIn(expect, body)

    def test_empty_criteria_shows_hint(self):
        self._complete_login()
        resp = self.client.get("/search")
        body = resp.get_data(as_text=True)
        self.assertIn("請至少填寫一個搜尋條件", body)

    def test_no_result_row(self):
        self._complete_login()
        resp = self.client.get("/search?idcard=ZZZ999999")
        body = resp.get_data(as_text=True)
        self.assertIn("查無符合條件的資料", body)

    def test_totp_replay_blocked_across_sessions(self):
        code = self._totp_code()
        token1 = self._login()
        resp = self.client.post(
            "/login/totp",
            data={"code": code, "_csrf": token1},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.client.delete_cookie("localhost")

        other = self.app.test_client()
        resp = other.get("/login")
        token2 = CSRF_RE.search(resp.get_data(as_text=True)).group(1)
        other.post(
            "/login",
            data={"username": "tester", "password": "TestPass123!", "_csrf": token2},
        )
        resp = other.get("/login/totp")
        token2 = CSRF_RE.search(resp.get_data(as_text=True)).group(1)
        resp = other.post("/login/totp", data={"code": code, "_csrf": token2})
        self.assertIn("動態驗證碼錯誤或已被使用", resp.get_data(as_text=True))

    def test_logout_requires_csrf(self):
        self._complete_login()
        resp = self.client.post("/logout", data={})
        self.assertEqual(resp.status_code, 400)
        page = self.client.get("/search")
        token = self._csrf(page)
        resp = self.client.post("/logout", data={"_csrf": token}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/login"))

    def _complete_login(self):
        token = self._login()
        resp = self.client.post(
            "/login/totp",
            data={"code": self._totp_code(), "_csrf": token},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)


if __name__ == "__main__":
    unittest.main()
