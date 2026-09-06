import os
import sqlite3
import tempfile
import time
import unittest

from app.users import (
    MAX_FAILURES,
    MAX_TOTP_FAILURES,
    TOTP_LOCK_SECONDS,
    UserStore,
    hash_password,
    verify_password,
)


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wusers-")
        self.path = os.path.join(self.tmp, "users.db")
        self.store = UserStore(self.path)
        self.store.create("alice", "SecretPass1", "ABC123DEF456")

    def test_verify_password_roundtrip(self):
        user = self.store.get("alice")
        self.assertTrue(verify_password("SecretPass1", user["pw_hash"]))
        self.assertFalse(verify_password("WrongPass9", user["pw_hash"]))

    def test_legacy_schema_auto_migrated(self):
        # 模擬舊版資料庫：無 totp_failures / totp_locked_until 欄位
        legacy = os.path.join(self.tmp, "legacy.db")
        conn = sqlite3.connect(legacy)
        conn.execute(
            "CREATE TABLE users ("
            " username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL,"
            " totp_secret TEXT NOT NULL, totp_last_step INTEGER,"
            " failed_attempts INTEGER NOT NULL DEFAULT 0,"
            " locked_until REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO users (username, pw_hash, totp_secret, created_at)"
            " VALUES ('bob', ?, ?, 0)",
            (hash_password("OldPass123"), "SECRET"),
        )
        conn.commit()
        conn.close()
        store = UserStore(legacy)
        user = store.get("bob")
        self.assertEqual(user["totp_failures"], 0)
        self.assertEqual(user["totp_locked_until"], 0)

    def test_totp_failures_record_and_reset(self):
        for _ in range(MAX_TOTP_FAILURES):
            self.store.record_totp_failure("alice")
        user = self.store.get("alice")
        self.assertEqual(user["totp_failures"], MAX_TOTP_FAILURES)
        self.assertGreater(user["totp_locked_until"], 0)
        self.store.reset_totp_failures("alice")
        user = self.store.get("alice")
        self.assertEqual(user["totp_failures"], 0)
        self.assertEqual(user["totp_locked_until"], 0)

    def test_lock_activates_at_max_failures(self):
        for _ in range(MAX_TOTP_FAILURES - 1):
            self.store.record_totp_failure("alice")
        user = self.store.get("alice")
        self.assertEqual(user["totp_locked_until"], 0)  # 未達上限不鎖
        self.store.record_totp_failure("alice")
        user = self.store.get("alice")
        self.assertGreater(user["totp_locked_until"], time.time())
        self.assertLessEqual(
            user["totp_locked_until"] - time.time(), TOTP_LOCK_SECONDS + 1
        )

    def test_reset_totp_clears_all_lock_state(self):
        for _ in range(MAX_TOTP_FAILURES):
            self.store.record_totp_failure("alice")
        for _ in range(MAX_FAILURES):
            self.store.record_failure("alice")
        self.assertTrue(self.store.reset_totp("alice", "NEWSECRET"))
        user = self.store.get("alice")
        self.assertEqual(user["totp_failures"], 0)
        self.assertEqual(user["totp_locked_until"], 0)
        self.assertEqual(user["failed_attempts"], 0)
        self.assertEqual(user["locked_until"], 0)
        self.assertEqual(user["totp_secret"], "NEWSECRET")
        self.assertIsNone(user["totp_last_step"])

    def test_db_file_permissions_restricted(self):
        if os.name == "nt":
            self.skipTest("Windows 無 POSIX 權限")
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()