import hmac
import secrets
from functools import wraps

from flask import redirect, request, session, url_for


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_hex(16)
    return token


def check_csrf():
    sent = request.form.get("_csrf", "")
    stored = session.get("_csrf", "")
    return bool(sent) and bool(stored) and hmac.compare_digest(sent, stored)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapper
