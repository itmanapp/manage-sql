import time

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import totp
from .security import check_csrf, csrf_token
from .users import MAX_FAILURES, hash_password, verify_password

bp = Blueprint("auth", __name__)

_dummy_hash_cache = None


def _dummy_hash():
    global _dummy_hash_cache
    if _dummy_hash_cache is None:
        _dummy_hash_cache = hash_password("timing-equalizer")
    return _dummy_hash_cache


@bp.app_context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("search.index"))
    if request.method == "POST":
        if not check_csrf():
            abort(400)
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = current_app.extensions["users"]
        user = users.get(username)
        if user and user["locked_until"] and user["locked_until"] > time.time():
            minutes = int(user["locked_until"] - time.time()) // 60 + 1
            flash(f"失敗次數過多，帳號已暫時鎖定，請約 {minutes} 分鐘後再試", "error")
        elif user is None:
            verify_password(password, _dummy_hash())
            flash("帳號、密碼或驗證碼錯誤", "error")
        elif not verify_password(password, user["pw_hash"]):
            users.record_failure(username)
            fresh = users.get(username)
            attempts_left = MAX_FAILURES - (fresh["failed_attempts"] or 0)
            message = "帳號、密碼或驗證碼錯誤"
            if attempts_left > 0:
                message += f"（剩餘 {attempts_left} 次機會）"
            flash(message, "error")
        else:
            users.reset_failures(username)
            session["pending_user"] = username
            return redirect(url_for("auth.totp_step"))
    return render_template("login.html")


@bp.route("/login/totp", methods=["GET", "POST"])
def totp_step():
    username = session.get("pending_user")
    if not username:
        return redirect(url_for("auth.login"))
    users = current_app.extensions["users"]
    user = users.get(username)
    if user is None:
        session.pop("pending_user", None)
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        if not check_csrf():
            abort(400)
        code = request.form.get("code", "").strip().replace(" ", "")
        step = totp.verify(user["totp_secret"], code, user["totp_last_step"])
        if step is False:
            flash("動態驗證碼錯誤或已被使用，請重新輸入", "error")
        else:
            users.mark_totp_used(username, step)
            identity = username
            session.clear()
            session["user"] = identity
            session.permanent = True
            csrf_token()
            return redirect(url_for("search.index"))
    return render_template("totp.html", username=username)


@bp.route("/logout", methods=["POST"])
def logout():
    if not check_csrf():
        abort(400)
    session.clear()
    flash("已登出", "info")
    return redirect(url_for("auth.login"))
