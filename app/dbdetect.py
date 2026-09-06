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


MDF_PAGE_SIZE = 8192
# 每個 8KB 頁標頭：位元組 0 為標頭版本（=1），位元組 1 為頁面型別
# （經真實 AdventureWorks MDF 驗證：頁0=15 檔案標頭、頁1=11 PFS、
#  頁2=8 GAM、頁3=9 SGAM）
MDF_PAGE_TYPE_OFFSET = 1
MDF_PAGE_TYPE_FILE_HEADER = 15  # 第 0 頁（檔案標頭）
MDF_MANAGEMENT_TYPES = {8, 9, 11, 13}  # GAM / SGAM / PFS / Boot


def _looks_like_mdf(path, header):
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    aligned = size > 0 and size % MDF_PAGE_SIZE == 0
    ext_match = str(path).lower().endswith(".mdf")
    if not aligned:
        return False
    # 主要判別：檢查前幾個 8KB 頁的頁面型別。
    # 真實 MDF：第 0 頁為檔案標頭（型別 15），第 1~3 頁為
    # PFS(11)/GAM(8)/SGAM(9) 等管理頁，是資料檔獨有的結構特徵。
    if size >= MDF_PAGE_SIZE * 4:
        with open(path, "rb") as fh:
            first = fh.read(MDF_PAGE_SIZE * 4)
        types = [
            first[i * MDF_PAGE_SIZE + MDF_PAGE_TYPE_OFFSET]
            for i in range(4)
            if len(first) >= (i + 1) * MDF_PAGE_SIZE
        ]
        if len(types) == 4:
            if (
                types[0] == MDF_PAGE_TYPE_FILE_HEADER
                and any(t in MDF_MANAGEMENT_TYPES for t in types[1:])
            ):
                return True
    # 頁面型別不符（例如檔案過小）時，僅對 .mdf 副檔名且內含
    # SQL Server 特徵字串的檔案放行，避免假檔誤判。
    if ext_match:
        with open(path, "rb") as fh:
            chunk = fh.read(1024 * 1024)
        return b"Microsoft SQL Server" in chunk or b"SQL Server" in chunk
    return False


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
