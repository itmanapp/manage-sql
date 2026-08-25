import os
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
    can_write = True

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self._columns = None
        self._mapping = None
        self.detection = None

    def table_name(self):
        table = self.cfg.get("table")
        if not table:
            raise DatabaseError("config.yaml 未設定 database.<backend>.table")
        return table

    def quote_ident(self, ident):
        raise NotImplementedError

    def describe(self):
        if self.detection is not None:
            mark = "可讀寫" if self.can_write else "僅可讀"
            return f"{self.detection.label}（{mark}）"
        return type(self).__name__

    def _field_pairs(self):
        mapping = self.resolve_mapping()
        return [(f, mapping[f]) for f in FIELD_ORDER if f in mapping]

    @staticmethod
    def _clean(value):
        text = "" if value is None else str(value)
        return text.strip()[:200]

    def insert(self, values):
        raise DatabaseError("此資料格式不支援寫入")

    def delete(self, criteria):
        raise DatabaseError("此資料格式不支援寫入")

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

    def describe(self):
        base = f"SQL Server 資料庫 {self.cfg.get('database', '')}（經引擎連線）"
        if self.detection is not None:
            mark = "可讀寫" if self.can_write else "僅可讀"
            return f"{self.detection.label} · {base}（{mark}）"
        return base

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

    def _qualified_insert_target(self):
        return self._qualified_table()

    def insert(self, values):
        pairs = self._field_pairs()
        cols = ", ".join(self.quote_ident(col) for _, col in pairs)
        marks = ", ".join(self.param for _ in pairs)
        params = [self._clean(values.get(field)) for field, _ in pairs]
        sql = (
            f"INSERT INTO {self._qualified_insert_target()} ({cols})"
            f" VALUES ({marks})"
        )
        with self._connect() as conn:
            cur = conn.cursor(as_dict=False)
            cur.execute(sql, tuple(params))
            return cur.rowcount

    def delete(self, criteria):
        pairs = self._field_pairs()
        clauses = []
        params = []
        for field, col in pairs:
            value = criteria.get(field)
            if value is None:
                continue
            if str(value).strip() == "":
                clauses.append(f"{self.quote_ident(col)} IS NULL")
            else:
                clauses.append(f"{self.quote_ident(col)} = {self.param}")
                params.append(str(value))
        if not clauses:
            raise DatabaseError("刪除條件不可為空，請至少提供一個欄位值")
        sql = f"DELETE FROM {self._qualified_table()} WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            cur = conn.cursor(as_dict=False)
            cur.execute(sql, tuple(params))
            return cur.rowcount


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

    def insert(self, values):
        pairs = self._field_pairs()
        table = self.quote_ident(self.table_name().strip('"'))
        cols = ", ".join(self.quote_ident(col) for _, col in pairs)
        marks = ", ".join("?" for _ in pairs)
        params = [self._clean(values.get(field)) for field, _ in pairs]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(params)
            )
            conn.commit()
            return cur.rowcount

    def delete(self, criteria):
        pairs = self._field_pairs()
        table = self.quote_ident(self.table_name().strip('"'))
        clauses = []
        params = []
        for field, col in pairs:
            value = criteria.get(field)
            if value is None:
                continue
            qcol = self.quote_ident(col)
            if str(value).strip() == "":
                clauses.append(f"({qcol} IS NULL OR {qcol} = '')")
            else:
                clauses.append(f"{qcol} = ?")
                params.append(str(value))
        if not clauses:
            raise DatabaseError("刪除條件不可為空，請至少提供一個欄位值")
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE " + " AND ".join(clauses), tuple(params)
            )
            conn.commit()
            return cur.rowcount

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


class DbfFileBackend(BaseBackend):
    can_write = True
    _CODEPAGES = {
        "utf-8": 240,
        "utf8": 240,
        "big5": 120,
        "cp950": 120,
        "gbk": 77,
        "cp936": 77,
        "ascii": 0,
    }

    def __init__(self, cfg):
        super().__init__(cfg)
        self.path = cfg.get("path")
        if not self.path:
            raise DatabaseError("config.yaml 缺少檔案路徑：file")
        enc = str(cfg.get("encoding", "utf-8")).lower()
        codepage = self._CODEPAGES.get(enc)
        if codepage is None:
            raise DatabaseError(
                f"不支援的 DBF 編碼：{enc}（可用：utf-8、big5/cp950、gbk）"
            )
        self.codepage = codepage

    def table_name(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    def quote_ident(self, ident):
        return str(ident)

    def _open(self, write=False):
        try:
            import dbf as dbflib
        except ImportError as exc:
            raise DatabaseError("未安裝 dbf 套件，請先執行 pip install -r requirements.txt") from exc
        mode = dbflib.READ_WRITE if write else dbflib.READ_ONLY
        try:
            table = dbflib.Table(self.path, codepage=self.codepage)
            table.open(mode=mode)
            return table
        except Exception as exc:
            raise DatabaseError(f"無法開啟 DBF 檔：{exc}") from exc

    @staticmethod
    def _cell(value):
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str):
            return value.strip()
        return "" if value is None else str(value)

    def _fetch_columns(self):
        table = self._open()
        try:
            cols = list(table.field_names)
        finally:
            table.close()
        if not cols:
            raise DatabaseError("DBF 檔沒有任何欄位")
        return cols

    def search(self, criteria, page, page_size):
        mapping = self.resolve_mapping()
        wanted = {
            field: str(criteria[field]).strip().lower()
            for field in FIELD_ORDER
            if criteria.get(field) and field in mapping
        }
        rows = []
        total = 0
        offset = (page - 1) * page_size
        table = self._open()
        try:
            names = [c for c in table.field_names]
            for record in table:
                row = {name: self._cell(record[name]) for name in names}
                if all(
                    wanted[f] in str(row.get(mapping[f], "")).lower()
                    for f in wanted
                ):
                    total += 1
                    if offset <= (total - 1) < offset + page_size:
                        rows.append({mapping[f]: row.get(mapping[f]) for f in FIELD_ORDER if f in mapping})
        finally:
            table.close()
        return rows, total

    def insert(self, values):
        pairs = self._field_pairs()
        data = tuple(self._clean(values.get(field)) for field, _ in pairs)
        table = self._open(write=True)
        try:
            table.append(data)
            return 1
        except Exception as exc:
            raise DatabaseError(f"寫入 DBF 失敗（欄位長度或型別不符？）：{exc}") from exc
        finally:
            table.close()

    def delete(self, criteria):
        import dbf as dbflib

        pairs = self._field_pairs()
        wanted = {}
        for field, col in pairs:
            value = criteria.get(field)
            if value is None:
                continue
            text = str(value).strip()
            if text == "":
                wanted[col] = ""
            else:
                wanted[col] = text
        if not wanted:
            raise DatabaseError("刪除條件不可為空，請至少提供一個欄位值")
        table = self._open(write=True)
        removed = 0
        try:
            for record in list(table):
                current = {col: self._cell(record[col]) for col in wanted}
                if all(current[col] == val for col, val in wanted.items()):
                    dbflib.delete(record)
                    removed += 1
            if removed:
                table.pack()
            return removed
        except Exception as exc:
            raise DatabaseError(f"刪除 DBF 記錄失敗：{exc}") from exc
        finally:
            table.close()


class AccessFileBackend(BaseBackend):
    can_write = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self.path = cfg.get("path")
        if not self.path:
            raise DatabaseError("config.yaml 缺少檔案路徑：file")
        self._rows = None

    def _parser(self):
        try:
            from access_parser import AccessParser
        except ImportError as exc:
            raise DatabaseError(
                "未安裝 access-parser 套件，請先執行 pip install -r requirements.txt"
            ) from exc
        try:
            return AccessParser(self.path)
        except Exception as exc:
            raise DatabaseError(f"無法解析 Access 檔：{exc}") from exc

    def tables(self):
        parser = self._parser()
        try:
            return sorted(parser.catalog.keys())
        except Exception as exc:
            raise DatabaseError(f"無法列舉 Access 資料表：{exc}") from exc

    def table_name(self):
        table = self.cfg.get("table")
        if not table:
            available = ", ".join(self.tables()) or "(無)"
            raise DatabaseError(
                f"請於設定指定 database.table；此 Access 檔可用資料表：{available}"
            )
        return table

    def quote_ident(self, ident):
        return str(ident)

    def _load_rows(self):
        if self._rows is not None:
            return self._rows
        parser = self._parser()
        name = self.table_name()
        try:
            parsed = parser.parse_table(name)
        except Exception as exc:
            raise DatabaseError(f"讀取 Access 資料表 {name} 失敗：{exc}") from exc
        if not parsed:
            raise DatabaseError(f"Access 資料表 {name} 是空的或無法解析")
        cols = list(parsed.keys())
        count = max(len(v) for v in parsed.values())
        self._rows = [
            {
                col: (
                    parsed[col][idx]
                    if idx < len(parsed[col])
                    else None
                )
                for col in cols
            }
            for idx in range(count)
        ]
        return self._rows

    def _fetch_columns(self):
        return list(self._load_rows()[0].keys()) if self._load_rows() else []

    def search(self, criteria, page, page_size):
        mapping = self.resolve_mapping()
        wanted = {
            field: str(criteria[field]).strip().lower()
            for field in FIELD_ORDER
            if criteria.get(field) and field in mapping
        }
        matched = []
        for row in self._load_rows():
            if all(
                wanted[f] in str(row.get(mapping[f], "")).lower()
                for f in wanted
            ):
                matched.append(row)
        offset = (page - 1) * page_size
        sliced = matched[offset:offset + page_size]
        rows = [
            {mapping[f]: r.get(mapping[f]) for f in FIELD_ORDER if f in mapping}
            for r in sliced
        ]
        return rows, len(matched)

    def insert(self, values):
        raise DatabaseError("Microsoft Access 格式為唯讀，不支援寫入")

    def delete(self, criteria):
        raise DatabaseError("Microsoft Access 格式為唯讀，不支援寫入")


_BACKENDS = {
    "sqlserver": SqlServerBackend,
    "mssql": SqlServerBackend,
    "sqlite": SqliteBackend,
}


def create_backend(db_cfg, search_columns=None):
    db_cfg = dict(db_cfg or {})
    name = str(db_cfg.get("backend", "sqlite")).lower()

    if name == "auto":
        from .dbdetect import detect_database

        file_path = db_cfg.get("file")
        if not file_path:
            raise DatabaseError("backend: auto 需要 database.file 設定（資料庫檔案路徑）")
        detection = detect_database(file_path)
        section = {
            "path": file_path,
            "table": db_cfg.get("table"),
            "encoding": db_cfg.get("encoding", "utf-8"),
        }
        explicit = {k: v for k, v in (search_columns or {}).items() if v}
        if explicit:
            section["columns"] = explicit
        if detection.file_type == "sqlite":
            backend = SqliteBackend(section)
        elif detection.file_type == "dbf":
            backend = DbfFileBackend(section)
        elif detection.file_type in ("mdb", "accdb"):
            backend = AccessFileBackend(section)
        else:
            raise DatabaseError(
                f"偵測到 {detection.label}。MDF 需先附加至 SQL Server 引擎才能存取，"
                "請改設定 backend: sqlserver（參見 README「正式環境：載入 MDF 檔」章節）"
            )
        backend.detection = detection
        return backend

    cls = _BACKENDS.get(name)
    if cls is None:
        raise DatabaseError(f"未知資料庫後端：{name}")
    section_key = "sqlite" if name == "sqlite" else "sqlserver"
    section = dict(db_cfg.get(section_key) or {})
    explicit = {k: v for k, v in (search_columns or {}).items() if v}
    if explicit:
        section["columns"] = explicit
    backend = cls(section)
    if isinstance(backend, SqlServerBackend):
        from .dbdetect import Detection

        backend.detection = Detection(
            "sqlserver", "SQL Server 資料庫", True
        )
    else:
        from .dbdetect import Detection

        backend.detection = Detection("sqlite", "SQLite 資料庫", True)
    return backend
