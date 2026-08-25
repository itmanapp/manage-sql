import re

FIELD_ORDER = ["name", "idcard", "address", "phone"]
FIELD_LABELS = {
    "name": "姓名",
    "idcard": "身份證",
    "address": "地址",
    "phone": "電話",
}

CANDIDATES = {
    "name": [
        "姓名", "名字", "name", "fullname", "full_name", "cname",
        "member_name", "patient_name", "user_name", "chinese_name",
    ],
    "idcard": [
        "身份證", "身分證", "idcard", "id_card", "idno", "id_no",
        "national_id", "pid", "identity", "idnumber", "id_number",
    ],
    "address": [
        "地址", "address", "addr", "home_address", "home_addr",
        "residential_address", "mailing_address",
    ],
    "phone": [
        "電話", "phone", "tel", "mobile", "cellphone", "telephone",
        "contact_number", "phone_number",
    ],
}


class DatabaseError(Exception):
    pass


def _normalize(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(text).lower())


def match_column(columns, candidates):
    normalized = {col: _normalize(col) for col in columns}
    for cand in candidates:
        target = _normalize(cand)
        for col, norm in normalized.items():
            if norm == target:
                return col
    for cand in candidates:
        target = _normalize(cand)
        if not target:
            continue
        for col, norm in normalized.items():
            if target in norm:
                return col
    return None


class BaseBackend:
    param = "?"

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self._columns = None
        self._mapping = None

    def table_name(self):
        table = self.cfg.get("table")
        if not table:
            raise DatabaseError("config.yaml 未設定 database.<backend>.table")
        return table

    def quote_ident(self, ident):
        raise NotImplementedError

    def columns(self):
        if self._columns is None:
            self._columns = self._fetch_columns()
        return self._columns

    def resolve_mapping(self):
        if self._mapping is not None:
            return self._mapping
        explicit = self.cfg.get("columns") or {}
        cols = self.columns()
        mapping = {}
        for field in FIELD_ORDER:
            col = explicit.get(field) or match_column(cols, CANDIDATES[field])
            if col and col in cols:
                mapping[field] = col
        missing = [FIELD_LABELS[f] for f in FIELD_ORDER if f not in mapping]
        if not mapping:
            raise DatabaseError(
                "無法偵測任何搜尋欄位，請於 config.yaml search.columns 明確指定欄位名稱"
            )
        if missing:
            self.mapping_warning = "未偵測到欄位：" + "、".join(missing)
        else:
            self.mapping_warning = None
        self._mapping = mapping
        return mapping

    @staticmethod
    def escape_like(value):
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

    def build_where(self, mapping, criteria):
        clauses = []
        params = []
        for field in FIELD_ORDER:
            value = criteria.get(field)
            if value:
                col = self.quote_ident(mapping[field])
                clauses.append(f"{col} LIKE {self.param} ESCAPE '\\'")
                params.append(f"%{self.escape_like(value)}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def search(self, criteria, page, page_size):
        raise NotImplementedError

    def seed_demo(self):
        raise DatabaseError("此後端不支援示範資料寫入")


class SqlServerBackend(BaseBackend):
    param = "%s"

    def _connect(self):
        try:
            import pymssql
        except ImportError as exc:
            raise DatabaseError(
                "未安裝 pymssql，請先執行 pip install -r requirements.txt"
            ) from exc
        try:
            return pymssql.connect(
                server=self.cfg["host"],
                port=str(self.cfg.get("port", 1433)),
                user=self.cfg["user"],
                password=self.cfg["password"],
                database=self.cfg["database"],
                login_timeout=10,
                timeout=15,
                charset="utf8",
            )
        except KeyError as exc:
            raise DatabaseError(f"config.yaml 缺少 sqlserver 設定：{exc}") from exc
        except Exception as exc:
            raise DatabaseError(f"無法連線至 SQL Server：{exc}") from exc

    def quote_ident(self, ident):
        clean = str(ident).strip("[]").replace("]", "]]")
        return f"[{clean}]"

    @staticmethod
    def _split_table(table):
        parts = [p.strip("[]") for p in table.split(".")]
        if len(parts) == 2:
            schema, name = parts
        else:
            schema, name = "dbo", parts[0]
        return schema, name

    def _fetch_columns(self):
        schema, name = self._split_table(self.table_name())
        sql = (
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS"
            " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s"
            " ORDER BY ORDINAL_POSITION"
        )
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, (schema, name))
            cols = [row[0] for row in cur.fetchall()]
        if not cols:
            raise DatabaseError(f"找不到資料表 {schema}.{name} 或其中沒有欄位")
        return cols

    def _qualified_table(self):
        schema, name = self._split_table(self.table_name())
        return f"{self.quote_ident(schema)}.{self.quote_ident(name)}"

    def search(self, criteria, page, page_size):
        mapping = self.resolve_mapping()
        where, params = self.build_where(mapping, criteria)
        table = self._qualified_table()
        select_cols = ", ".join(
            self.quote_ident(mapping[f]) for f in FIELD_ORDER if f in mapping
        )
        order_col = self.quote_ident(mapping.get("idcard") or next(iter(mapping.values())))
        offset = (page - 1) * page_size
        count_sql = f"SELECT COUNT(*) FROM {table}{where}"
        data_sql = (
            f"SELECT {select_cols} FROM {table}{where}"
            f" ORDER BY {order_col}"
            f" OFFSET {int(offset)} ROWS FETCH NEXT {int(page_size)} ROWS ONLY"
        )
        with self._connect() as conn:
            cur = conn.cursor(as_dict=False)
            cur.execute(count_sql, tuple(params))
            total = cur.fetchone()[0]
            cur.execute(data_sql, tuple(params))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
        return rows, total


class SqliteBackend(BaseBackend):
    param = "?"

    def _connect(self):
        import os
        import sqlite3

        path = self.cfg.get("path")
        if not path:
            raise DatabaseError("config.yaml 缺少 sqlite 設定：path")
        if not os.path.exists(path):
            raise DatabaseError(f"找不到 SQLite 資料庫檔案：{path}")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def quote_ident(self, ident):
        clean = str(ident).strip('"').replace('"', '""')
        return f'"{clean}"'

    def _fetch_columns(self):
        table = self.table_name().strip('"')
        with self._connect() as conn:
            rows = conn.execute(
                f"PRAGMA table_info({self.quote_ident(table)})"
            ).fetchall()
        cols = [r[1] for r in rows]
        if not cols:
            raise DatabaseError(f"找不到資料表 {table} 或其中沒有欄位")
        return cols

    def search(self, criteria, page, page_size):
        mapping = self.resolve_mapping()
        where, params = self.build_where(mapping, criteria)
        table = self.quote_ident(self.table_name().strip('"'))
        select_cols = ", ".join(
            self.quote_ident(mapping[f]) for f in FIELD_ORDER if f in mapping
        )
        order_col = self.quote_ident(mapping.get("idcard") or next(iter(mapping.values())))
        offset = (page - 1) * page_size
        count_sql = f"SELECT COUNT(*) FROM {table}{where}"
        data_sql = (
            f"SELECT {select_cols} FROM {table}{where}"
            f" ORDER BY {order_col} LIMIT {int(page_size)} OFFSET {int(offset)}"
        )
        with self._connect() as conn:
            cur = conn.execute(count_sql, tuple(params))
            total = cur.fetchone()[0]
            cur = conn.execute(data_sql, tuple(params))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
        return rows, total

    def seed_demo(self):
        import os
        import sqlite3

        path = self.cfg.get("path") or "instance/demo.db"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        demo_rows = [
            ("王小美", "A289635741", "台北市大安區仁愛路四段300巷12號5樓", "0912-345-678"),
            ("王大明", "B187654320", "新北市板橋區文化路二段88號11樓", "0922-111-222"),
            ("李俊宏", "C276154839", "台中市西屯區台灣大道三段99號", "0933-555-888"),
            ("林雅婷", "D332145687", "高雄市左營區博愛二路777號", "0912-345-999"),
            ("張家豪", "E125634789", "台南市東區中華東路三段35號", "0955-234-111"),
            ("陳美玲", "F298765431", "台北市士林區中山北路六段400號", "0966-333-222"),
            ("黃志明", "G212345097", "桃園市中壢區中央西路二段20號", "0922-111-333"),
            ("吳淑芬", "H345671208", "新竹市東區光復路二段151號", "0933-555-444"),
            ("劉建國", "J198765243", "台北市萬華區西門町徒步區6號", "0955-234-666"),
            ("鄭怡君", "K256341870", "彰化縣員林市中山路二段36號", "0966-333-777"),
            ("蔡文雄", "L321450987", "基隆市仁愛區愛三路50號", "0912-345-123"),
            ("謝佳穎", "M178654302", "台北市信義區忠孝東路五段297號", "0922-111-456"),
        ]
        with sqlite3.connect(path) as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS "Members" ('
                '"姓名" TEXT, "身分證字號" TEXT, "戶籍地址" TEXT, "聯絡電話" TEXT)'
            )
            cur = conn.execute('SELECT COUNT(*) FROM "Members"')
            if cur.fetchone()[0] == 0:
                conn.executemany(
                    'INSERT INTO "Members" VALUES (?, ?, ?, ?)', demo_rows
                )
                inserted = len(demo_rows)
            else:
                inserted = 0
        self._columns = None
        self._mapping = None
        return inserted


_BACKENDS = {
    "sqlserver": SqlServerBackend,
    "mssql": SqlServerBackend,
    "sqlite": SqliteBackend,
}


def create_backend(db_cfg, search_columns=None):
    db_cfg = dict(db_cfg or {})
    name = str(db_cfg.get("backend", "sqlite")).lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise DatabaseError(f"未知資料庫後端：{name}")
    section_key = "sqlite" if name == "sqlite" else "sqlserver"
    section = dict(db_cfg.get(section_key) or {})
    explicit = {k: v for k, v in (search_columns or {}).items() if v}
    if explicit:
        section["columns"] = explicit
    return cls(section)
