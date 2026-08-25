import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import totp

secret = os.environ["SECRET"]
print(totp.hotp_at(secret, int(time.time()) // totp.STEP))
