from flask import Blueprint, current_app, render_template, request

from .db import FIELD_LABELS, FIELD_ORDER, DatabaseError
from .security import login_required

bp = Blueprint("search", __name__)


@bp.route("/", methods=["GET"])
@bp.route("/search", methods=["GET"])
@login_required
def index():
    backend = current_app.extensions["db"]
    cfg = current_app.config["APP_CFG"]
    try:
        page_size = int(cfg.get("search", {}).get("page_size", 20))
    except (TypeError, ValueError):
        page_size = 20
    page_size = max(min(page_size, 200), 5)

    context = {
        "fields": FIELD_ORDER,
        "labels": FIELD_LABELS,
        "mapping": {},
        "criteria": {},
        "rows": [],
        "total": None,
        "page": 1,
        "pages": 0,
        "page_size": page_size,
        "error": None,
        "warning": None,
    }

    try:
        mapping = backend.resolve_mapping()
    except DatabaseError as exc:
        context["error"] = str(exc)
        return render_template("search.html", **context)
    context["mapping"] = mapping
    context["warning"] = getattr(backend, "mapping_warning", None)

    criteria = {}
    for field in FIELD_ORDER:
        raw = request.args.get(field, "").strip()
        if raw:
            criteria[field] = raw[:100]
    context["criteria"] = criteria

    if request.args and not criteria:
        context["error"] = "請至少輸入一個搜尋條件"
        return render_template("search.html", **context)

    if criteria:
        try:
            page = max(int(request.args.get("page", "1")), 1)
        except ValueError:
            page = 1
        context["page"] = page
        try:
            rows, total = backend.search(criteria, page, page_size)
        except DatabaseError as exc:
            context["error"] = f"資料庫查詢失敗：{exc}"
            return render_template("search.html", **context)
        context["rows"] = rows
        context["total"] = total
        context["pages"] = max((total + page_size - 1) // page_size, 1)

    return render_template("search.html", **context)
