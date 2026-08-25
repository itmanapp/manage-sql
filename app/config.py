import copy
import os

import yaml

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "database": {"backend": "sqlite"},
    "search": {"page_size": 20},
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path):
    data = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    return _merge(DEFAULTS, data)
