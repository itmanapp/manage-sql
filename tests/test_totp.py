import unittest

from app.totp import hotp_at, provisioning_uri, verify

RFC_KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TotpTests(unittest.TestCase):
    def test_rfc4226_vectors(self):
        vectors = [
            (0, "755224"), (1, "287082"), (2, "359152"),
            (3, "969429"), (4, "338314"), (5, "254676"),
            (6, "287922"), (7, "162583"), (8, "399871"),
            (9, "520489"),
        ]
        for counter, expected in vectors:
            with self.subTest(counter=counter):
                self.assertEqual(hotp_at(RFC_KEY, counter), expected)

    def test_verify_current_window(self):
        now = 59
        self.assertEqual(verify(RFC_KEY, "287082", now=now), 1)

    def test_verify_rejects_wrong_code(self):
        self.assertFalse(verify(RFC_KEY, "000000", now=59))

    def test_verify_rejects_bad_format(self):
        for bad in ["", "12a456", "12345", "12345678", None]:
            with self.subTest(code=bad):
                self.assertFalse(verify(RFC_KEY, bad, now=59))

    def test_replay_blocked(self):
        now = 59
        step = verify(RFC_KEY, "287082", last_used_step=None, now=now)
        self.assertEqual(step, 1)
        replayed = verify(RFC_KEY, "287082", last_used_step=step, now=now)
        self.assertFalse(replayed)

    def test_provisioning_uri(self):
        uri = provisioning_uri("ABC234DEF", "alice")
        self.assertTrue(uri.startswith("otpauth://totp/MdfQuery:alice?"))
        self.assertIn("secret=ABC234DEF", uri)


if __name__ == "__main__":
    unittest.main()
