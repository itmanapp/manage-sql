import os


class Detection:
    def __init__(self, file_type, label, writable, note=""):
        self.file_type = file_type
        self.label = label
        self.writable = writable
        self.note = note

    def __repr__(self):
        return f"Detection({self.file_type!r}, writable={self.writable})"


SQLITE_MAGIC = b"SQLite format 3\x00"
JET_MAGIC = b"Standard Jet DB"
ACE_MAGIC = b"Standard ACE DB"

DBF_VERSION_BYTES = {
    0x02, 0x03, 0x04, 0x05,
    0x30, 0x31, 0x32,
    0x42, 0x43, 0x62, 0x63,
    0x7B, 0x83, 0x87, 0x8B, 0x8E,
    0xB3, 0xF5, 0xFB,
}


def _looks_like_dbf(header):
    if len(header) < 12 or header[0] not in DBF_VERSION_BYTES:
        return False
    year = header[1]
    month = header[2]
    day = header[3]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    header_length = int.from_bytes(header[8:10], "little")
    record_length = int.from_bytes(header[10:12], "little")
    return 33 <= header_length <= 65535 and 1 <= record_length <= 65535


def _looks_like_mdf(path, header):
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    aligned = size > 0 and size % 8192 == 0
    ext_match = str(path).lower().endswith(".mdf")
    if not aligned:
        return False
    if ext_match:
        return True
    with open(path, "rb") as fh:
        chunk = fh.read(1024 * 1024)
    return b"Microsoft" in chunk


def detect_database(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到資料庫檔案：{path}")
    with open(path, "rb") as fh:
        header = fh.read(64)

    if header.startswith(SQLITE_MAGIC):
        return Detection(
            "sqlite",
            "SQLite 資料庫",
            True,
            "單檔式 SQL 資料庫，可直接讀寫",
        )
    if len(header) >= 19 and header[4:19] == JET_MAGIC:
        return Detection(
            "mdb",
            "Microsoft Access 資料庫（Jet MDB）",
            False,
            "此格式僅支援讀取查詢，無法寫入",
        )
    if len(header) >= 19 and header[4:19] == ACE_MAGIC:
        return Detection(
            "accdb",
            "Microsoft Access 資料庫（ACE ACCDB）",
            False,
            "此格式僅支援讀取查詢，無法寫入",
        )
    if _looks_like_dbf(header):
        return Detection(
            "dbf",
            "dBASE / FoxPro 資料表（DBF）",
            True,
            "單表格式，可直接讀寫欄位資料",
        )
    if _looks_like_mdf(path, header):
        return Detection(
            "mdf",
            "Microsoft SQL Server 資料檔（MDF）",
            True,
            "需先附加至 SQL Server 引擎才能讀寫（見 README「正式環境」）",
        )
    raise ValueError(
        f"無法辨識的資料庫檔案類型：{path}\n"
        "支援格式：SQLite (.db/.sqlite)、Access (.mdb/.accdb)、dBASE (.dbf)、SQL Server (.mdf)"
    )
