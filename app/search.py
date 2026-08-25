from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .db import FIELD_LABELS, FIELD_ORDER, DatabaseError
from .security import check_csrf, login_required

bp = Blueprint("search", __name__)


def _base_context():
    return {
        "fields": FIELD_ORDER,
        "labels": FIELD_LABELS,
        "mapping": {},
        "visible_fields": [],
        "criteria": {},
        "rows": [],
        "total": None,
        "page": 1,
        "pages": 0,
        "page_size": 20,
        "error": None,
        "warning": None,
        "can_write": False,
        "description": "",
    }


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

    context = _base_context()
    context["page_size"] = page_size
    context["can_write"] = bool(getattr(backend, "can_write", False))
    try:
        context["description"] = backend.describe()
    except Exception:
        context["description"] = ""

    try:
        mapping = backend.resolve_mapping()
    except DatabaseError as exc:
        context["error"] = str(exc)
        return render_template("search.html", **context)
    context["mapping"] = mapping
    context["visible_fields"] = [f for f in FIELD_ORDER if f in mapping]
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


@bp.route("/add", methods=["POST"])
@login_required
def add_row():
    if not check_csrf():
        abort(400)
    backend = current_app.extensions["db"]
    values = {
        field: request.form.get(field, "").strip()[:200]
        for field in FIELD_ORDER
    }
    if not any(values.values()):
        flash("請至少填寫一個欄位", "error")
        return redirect(url_for("search.index"))
    try:
        inserted = backend.insert(values)
        flash(f"已新增 {inserted} 筆資料", "info")
    except DatabaseError as exc:
        flash(f"新增失敗：{exc}", "error")
    return redirect(url_for("search.index"))


@bp.route("/delete", methods=["POST"])
@login_required
def delete_row():
    if not check_csrf():
        abort(400)
    backend = current_app.extensions["db"]
    criteria = {
        field: request.form.get(field)
        for field in FIELD_ORDER
        if field in request.form
    }
    try:
        removed = backend.delete(criteria)
        if removed:
            flash(f"已刪除 {removed} 筆資料", "info")
        else:
            flash("沒有符合條件的資料被刪除", "error")
    except DatabaseError as exc:
        flash(f"刪除失敗：{exc}", "error")
    return redirect(url_for("search.index"))
