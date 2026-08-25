import os
import tempfile
import unittest

from app.db import DatabaseError, SqliteBackend, create_backend


class SqliteWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wsqlite-")
        self.path = os.path.join(self.tmp, "demo.db")
        self.backend = SqliteBackend({"path": self.path, "table": "Members"})
        self.backend.seed_demo()

    def test_insert_and_search(self):
        n = self.backend.insert(
            {"name": "測試人", "idcard": "Y999999999", "address": "台北市", "phone": "0900-000-000"}
        )
        self.assertEqual(n, 1)
        rows, total = self.backend.search({"idcard": "Y999999999"}, 1, 10)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["姓名"], "測試人")

    def test_delete_by_exact_match(self):
        self.backend.insert(
            {"name": "待刪除", "idcard": "X888888888", "phone": "0911-111-111"}
        )
        removed = self.backend.delete({"idcard": "X888888888"})
        self.assertEqual(removed, 1)
        rows, total = self.backend.search({"idcard": "X888888888"}, 1, 10)
        self.assertEqual(total, 0)

    def test_delete_empty_criteria_rejected(self):
        with self.assertRaises(DatabaseError):
            self.backend.delete({})

    def test_delete_multiple_rows_with_same_value(self):
        self.backend.insert({"name": "雙胞胎甲", "idcard": "Y111111111", "phone": "0900-111-111"})
        self.backend.insert({"name": "雙胞胎乙", "idcard": "Y222222222", "phone": "0900-111-111"})
        removed = self.backend.delete({"phone": "0900-111-111"})
        self.assertEqual(removed, 2)
        _, remaining = self.backend.search({"phone": "0900-111-111"}, 1, 10)
        self.assertEqual(remaining, 0)


class DbfBackendTests(unittest.TestCase):
    def _make_dbf(self, path):
        import dbf

        table = dbf.Table(
            path,
            "NAME C(20); IDCARD C(12); ADDRESS C(40); PHONE C(15)",
            codepage=240,
        )
        table.open(mode=dbf.READ_WRITE)
        table.append(("王小美", "A289635741", "台北市大安區仁愛路", "0912-345-678"))
        table.append(("王大明", "B187654320", "新北市板橋區文化路", "0922-111-222"))
        table.append(("李俊宏", "C276154839", "台中市西屯區台灣大道", "0933-555-888"))
        table.close()
        return path

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wdbf-")
        self.path = self._make_dbf(os.path.join(self.tmp, "members.dbf"))
        self.backend = create_backend(
            {"backend": "auto", "file": self.path}
        )

    def test_auto_detection_is_dbf(self):
        self.assertIsNotNone(self.backend.detection)
        self.assertEqual(self.backend.detection.file_type, "dbf")
        self.assertTrue(self.backend.can_write)

    def test_columns_auto_mapped(self):
        mapping = self.backend.resolve_mapping()
        self.assertEqual(mapping["name"], "NAME")
        self.assertEqual(mapping["idcard"], "IDCARD")
        self.assertIn("ADDRESS", mapping.values())
        self.assertIn("PHONE", mapping.values())

    def test_search_partial_match_chinese(self):
        rows, total = self.backend.search({"name": "王小"}, 1, 10)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["IDCARD"], "A289635741")

    def test_insert_append_new_record(self):
        n = self.backend.insert(
            {"name": "陳美玲", "idcard": "F298765431", "address": "高雄市", "phone": "0966-333-222"}
        )
        self.assertEqual(n, 1)
        rows, total = self.backend.search({"idcard": "F298765431"}, 1, 10)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["PHONE"], "0966-333-222")

    def test_delete_removes_only_matching_record(self):
        removed = self.backend.delete({"idcard": "B187654320"})
        self.assertEqual(removed, 1)
        _, total = self.backend.search({"idcard": "B187654320"}, 1, 10)
        self.assertEqual(total, 0)
        _, remaining = self.backend.search({"name": "王"}, 1, 10)
        self.assertEqual(remaining, 1)

    def test_describe_mentions_dbf(self):
        text = self.backend.describe()
        self.assertIn("DBF", text)


class AutoModeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="autoroute-")

    def test_sqlite_file_routed_to_sqlite_backend(self):
        path = os.path.join(self.tmp, "s.db")
        backend = SqliteBackend({"path": path, "table": "Members"})
        backend.seed_demo()
        routed = create_backend({"backend": "auto", "file": path, "table": "Members"})
        self.assertIsInstance(routed, SqliteBackend)
        self.assertEqual(routed.detection.file_type, "sqlite")

    def test_mdf_in_auto_mode_guides_user(self):
        path = os.path.join(self.tmp, "x.mdf")
        page = bytearray(8192)
        marker = b"Microsoft SQL Server"
        page[100:100 + len(marker)] = marker
        with open(path, "wb") as fh:
            fh.write(page)
            fh.write(bytearray(8192))
        with self.assertRaises(DatabaseError) as ctx:
            create_backend({"backend": "auto", "file": path})
        self.assertIn("sqlserver", str(ctx.exception))

    def test_unknown_backend_name_rejected(self):
        with self.assertRaises(DatabaseError):
            create_backend({"backend": "oracle"})


if __name__ == "__main__":
    unittest.main()
