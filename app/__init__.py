import os
import secrets

from flask import Flask

from .auth import bp as auth_bp
from .config import load_config
from .db import create_backend
from .search import bp as search_bp
from .users import UserStore


def _load_or_create_secret(instance_path):
    path = os.path.join(instance_path, "secret_key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key)
    return key


def create_app(
    config_path=None,
    instance_path=None,
    users_store=None,
    db_backend=None,
):
    app = Flask(__name__, instance_path=instance_path)
    resolved_path = (
        config_path
        or os.environ.get("MDFEDIT_CONFIG")
        or os.path.join(app.root_path, "..", "config.yaml")
    )
    cfg = load_config(resolved_path)
    app.config["APP_CFG"] = cfg
    os.makedirs(app.instance_path, exist_ok=True)
    app.secret_key = _load_or_create_secret(app.instance_path)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=1800,
        MAX_CONTENT_LENGTH=64 * 1024,
    )

    if users_store is None:
        users_store = UserStore(os.path.join(app.instance_path, "users.db"))
    if db_backend is None:
        db_backend = create_backend(
            cfg.get("database"), cfg.get("search", {}).get("columns")
        )
    app.extensions["users"] = users_store
    app.extensions["db"] = db_backend

    app.register_blueprint(auth_bp)
    app.register_blueprint(search_bp)
    return app
