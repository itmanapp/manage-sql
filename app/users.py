import hashlib
import secrets
import sqlite3
import time

PBKDF2_ITERATIONS = 310000
SALT_BYTES = 16
MAX_FAILURES = 5
LOCK_SECONDS = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    pw_hash TEXT NOT NULL,
    totp_secret TEXT NOT NULL,
    totp_last_step INTEGER,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
)
"""


def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        salt_hex, expected_hex = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    candidate_hex = hash_password(password, salt_hex).split("$", 1)[1]
    return secrets.compare_digest(candidate_hex, expected_hex)


class UserStore:
    def __init__(self, path):
        self.path = path
        self.ensure()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure(self):
        with self._conn() as conn:
            conn.execute(_SCHEMA)

    def get(self, username):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, username, password, totp_secret):
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO users (username, pw_hash, totp_secret, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), totp_secret, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"使用者 {username} 已存在") from exc

    def reset_totp(self, username, secret):
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE users SET totp_secret = ?, totp_last_step = NULL,"
                " failed_attempts = 0, locked_until = 0 WHERE username = ?",
                (secret, username),
            )
        return cur.rowcount > 0

    def record_failure(self, username):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT failed_attempts FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not row:
                return
            attempts = row["failed_attempts"] + 1
            locked_until = time.time() + LOCK_SECONDS if attempts >= MAX_FAILURES else 0
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ?"
                " WHERE username = ?",
                (attempts, locked_until, username),
            )

    def reset_failures(self, username):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = 0"
                " WHERE username = ?",
                (username,),
            )

    def mark_totp_used(self, username, step):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET totp_last_step = ? WHERE username = ?",
                (step, username),
            )

    def list_users(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username, created_at FROM users ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]
