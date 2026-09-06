import os
import struct
import tempfile
import unittest

from app.dbdetect import detect_database


def make_sqlite(path):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.db import SqliteBackend

    backend = SqliteBackend({"path": path, "table": "Members"})
    backend.seed_demo()
    return path


def make_dbf(path):
    import dbf

    table = dbf.Table(
        path,
        "NAME C(20); IDCARD C(12); ADDRESS C(40); PHONE C(15)",
        codepage=240,
    )
    table.open(mode=dbf.READ_WRITE)
    table.append(("王小美", "A289635741", "台北市大安區", "0912-345-678"))
    table.close()
    return path


def make_mdf(path):
    """建立具真實 SQL Server 頁面型別結構的假 MDF（4 個 8KB 頁）。"""
    pages = []
    page0 = bytearray(8192)
    page0[0] = 1
    page0[1] = 15  # 第 0 頁：檔案標頭（FILE_HEADER）
    marker = b"AdventureWorksLT2012\x00Microsoft SQL Server"
    page0[100:100 + len(marker)] = marker
    pages.append(page0)
    page1 = bytearray(8192)
    page1[0] = 1
    page1[1] = 11  # PFS
    pages.append(page1)
    page2 = bytearray(8192)
    page2[0] = 1
    page2[1] = 8  # GAM
    pages.append(page2)
    page3 = bytearray(8192)
    page3[0] = 1
    page3[1] = 9  # SGAM
    pages.append(page3)
    with open(path, "wb") as fh:
        for page in pages:
            fh.write(page)
    return path


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="detect-")

    def _path(self, name):
        return os.path.join(self.tmp, name)

    def test_sqlite_detected(self):
        det = detect_database(make_sqlite(self._path("a.db")))
        self.assertEqual(det.file_type, "sqlite")
        self.assertTrue(det.writable)

    def test_dbf_detected(self):
        det = detect_database(make_dbf(self._path("b.dbf")))
        self.assertEqual(det.file_type, "dbf")
        self.assertTrue(det.writable)

    def test_mdb_jet_magic(self):
        p = self._path("c.mdb")
        with open(p, "wb") as fh:
            fh.write(b"\x00\x01\x00\x00" + b"Standard Jet DB" + b"\x00" * 64)
        det = detect_database(p)
        self.assertEqual(det.file_type, "mdb")
        self.assertFalse(det.writable)

    def test_accdb_ace_magic(self):
        p = self._path("d.accdb")
        with open(p, "wb") as fh:
            fh.write(b"\x00\x02\x00\x00" + b"Standard ACE DB" + b"\x00" * 64)
        det = detect_database(p)
        self.assertEqual(det.file_type, "accdb")

    def test_mdf_by_extension_and_alignment(self):
        det = detect_database(make_mdf(self._path("e.mdf")))
        self.assertEqual(det.file_type, "mdf")

    def test_mdf_by_content_even_without_ext(self):
        p = self._path("noext")
        make_mdf(p)
        det = detect_database(p)
        self.assertEqual(det.file_type, "mdf")

    def test_aligned_mdf_extension_without_structure_rejected(self):
        # 僅 8KB 對齊 + .mdf 副檔名但沒有頁面型別結構／特徵字串 → 應拒絕
        p = self._path("fake-aligned.mdf")
        data = bytearray(8192 * 4)
        for i in range(4):
            data[i * 8192 + 13] = 90  # 無效頁面型別
        with open(p, "wb") as fh:
            fh.write(data)
        with self.assertRaises(ValueError):
            detect_database(p)

    def test_random_aligned_noext_not_mdf(self):
        # 無副檔名、8KB 對齊但無頁面型別 → 不應誤判為 MDF
        p = self._path("random-aligned")
        data = bytearray(8192 * 4)
        for i in range(4):
            data[i * 8192 + 13] = 90
        with open(p, "wb") as fh:
            fh.write(data)
        with self.assertRaises(ValueError):
            detect_database(p)

    def test_unknown_file_rejected(self):
        p = self._path("junk.bin")
        with open(p, "wb") as fh:
            fh.write(b"hello world this is not a database")
        with self.assertRaises(ValueError):
            detect_database(p)

    def test_missing_file_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            detect_database(self._path("missing.db"))

    def test_dbf_false_positive_avoided_for_random_bytes(self):
        p = self._path("fake.dbf")
        with open(p, "wb") as fh:
            fh.write(struct.pack("B", 0x03) + b"\x99\x99" + os.urandom(60))
        with self.assertRaises(ValueError):
            detect_database(p)


if __name__ == "__main__":
    unittest.main()
