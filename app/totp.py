import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6
WINDOW = 1


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(encoded):
    padding = "=" * ((8 - len(encoded) % 8) % 8)
    return base64.b32decode(encoded.upper() + padding)


def hotp_at(secret, counter):
    digest = hmac.new(
        _decode_secret(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret, code, last_used_step=None, now=None):
    if not secret or not code or not code.isdigit() or len(code) != DIGITS:
        return False
    current = int(time.time() if now is None else now) // STEP
    for counter in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(hotp_at(secret, counter), code):
            if last_used_step is not None and counter <= last_used_step:
                return False
            return counter
    return False


def provisioning_uri(secret, account, issuer="MdfQuery"):
    query = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP,
        }
    )
    label = f"{urllib.parse.quote(issuer)}:{urllib.parse.quote(str(account), safe='')}"
    return f"otpauth://totp/{label}?{query}"
