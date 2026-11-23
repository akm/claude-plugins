"""行の単位の YAML の書き換え (モジュール yaml_edit) のテスト。

書き換えない行が変わらないこと、コメントの行が意図した項目と一緒に消えること・残ること、インデントがファイルに合うことを確認する。
決めた経緯は Issue #208 のコメントの 8。
"""

import unittest

from doc_structured.yaml_edit import Document, Double, Flow, YamlEditError, new_document, scalar

TABLES = """\
# ファイルの先頭のコメント
tables:
  books:
    primary_key: [id]
    columns:
      id:
        type: text  # 行末のコメント
        definition: 図書を識別する値。
      # タイトルの説明
      title:
        type: text
      # 作った時刻
      created_at:
        type: integer
        definition: 行を作った時刻。
    indexes:
      # 題名で探す
      - columns: [title]
      - columns: [created_at]
        unique: true

  members:
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 利用者を識別する値。

  loans:
    columns:
      id:
        type: text
        definition: 貸出を識別する値。
"""

COLUMN_ORDER = ("type", "nullable", "default", "references", "attribute", "planned", "in_overview", "definition")


class InsertAndSetTest(unittest.TestCase):
    def test_insert_key_by_order(self):
        document = Document(TABLES)
        document.set_key(("tables", "books", "columns", "title"), "planned", True, COLUMN_ORDER)
        document.set_key(("tables", "books", "columns", "title"), "nullable", True, COLUMN_ORDER)
        self.assertEqual(
            document.text,
            TABLES.replace(
                "      title:\n        type: text\n",
                "      title:\n        type: text\n        nullable: true\n        planned: true\n",
            ),
        )

    def test_insert_key_before_the_first_key(self):
        document = Document(TABLES)
        document.set_key(("tables", "members"), "planned", True, ("planned", "definition", "primary_key", "columns"))
        self.assertEqual(
            document.text,
            TABLES.replace("  members:\n    primary_key", "  members:\n    planned: true\n    primary_key"),
        )

    def test_set_key_keeps_end_of_line_comment(self):
        document = Document(TABLES)
        document.set_key(("tables", "books", "columns", "id"), "type", "integer", COLUMN_ORDER)
        self.assertEqual(document.text, TABLES.replace("type: text  # 行末のコメント", "type: integer  # 行末のコメント"))

    def test_set_flow_sequence(self):
        document = Document(TABLES)
        document.set_key(("tables", "books"), "primary_key", Flow(["id", "title"]), ())
        self.assertEqual(document.text, TABLES.replace("primary_key: [id]", "primary_key: [id, title]", 1))

    def test_quotes_values_that_are_not_plain(self):
        self.assertEqual(scalar(Double("'on_loan'")), "\"'on_loan'\"")
        self.assertEqual(scalar(Double("false")), '"false"')
        self.assertEqual(scalar("text"), "text")
        self.assertEqual(scalar("true"), '"true"')
        self.assertEqual(scalar("型: 番号 # 注"), '"型: 番号 # 注"')
        self.assertEqual(scalar('a "b"'), 'a "b"')

    def test_insert_column_before_next_column_and_its_comment(self):
        document = Document(TABLES)
        document.insert_key(
            ("tables", "books", "columns"), "isbn", {"type": "text", "nullable": True, "definition": "ISBN。"}, 2
        )
        self.assertEqual(
            document.text,
            TABLES.replace(
                "      # 作った時刻\n",
                "      isbn:\n        type: text\n        nullable: true\n        definition: ISBN。\n      # 作った時刻\n",
            ),
        )

    def test_insert_table_at_end_keeps_blank_lines_between_tables(self):
        document = Document(TABLES)
        document.insert_key(
            ("tables",), "fines",
            {"definition": "延滞金。", "primary_key": Flow(["id"]), "columns": {"id": {"type": "text", "definition": "延滞金の ID。"}}},
            3,
        )
        self.assertEqual(
            document.text,
            TABLES
            + "\n  fines:\n    definition: 延滞金。\n    primary_key: [id]\n    columns:\n      id:\n        type: text\n"
            "        definition: 延滞金の ID。\n",
        )

    def test_insert_key_with_sequence_value(self):
        document = Document(TABLES)
        document.insert_key(("tables", "members"), "indexes", [{"columns": Flow(["id"]), "unique": True}], 2)
        self.assertEqual(
            document.text,
            TABLES.replace(
                "        definition: 利用者を識別する値。\n",
                "        definition: 利用者を識別する値。\n    indexes:\n      - columns: [id]\n        unique: true\n",
            ),
        )

    def test_existing_key(self):
        with self.assertRaises(YamlEditError):
            Document(TABLES).insert_key(("tables", "books"), "columns", {}, 0)


class DeleteTest(unittest.TestCase):
    def test_delete_key(self):
        document = Document(TABLES)
        document.delete_key(("tables", "books", "indexes", 1), "unique")
        self.assertEqual(document.text, TABLES.replace("      - columns: [created_at]\n        unique: true\n", "      - columns: [created_at]\n"))

    def test_delete_column_with_its_comment_and_keep_next_comment(self):
        document = Document(TABLES)
        document.delete_key(("tables", "books", "columns"), "title")
        self.assertEqual(document.text, TABLES.replace("      # タイトルの説明\n      title:\n        type: text\n", ""))

    def test_delete_middle_table_leaves_one_blank_line(self):
        document = Document(TABLES)
        document.delete_key(("tables",), "members")
        self.assertEqual(
            document.text,
            TABLES.replace(
                "  members:\n    primary_key: [id]\n    columns:\n      id:\n        type: text\n"
                "        definition: 利用者を識別する値。\n\n",
                "",
            ),
        )

    def test_delete_last_table_removes_blank_line_before_it(self):
        document = Document(TABLES)
        document.delete_key(("tables",), "loans")
        self.assertEqual(document.text, TABLES.split("\n  loans:")[0])

    def test_delete_index_with_its_comment(self):
        document = Document(TABLES)
        document.delete_item(("tables", "books", "indexes"), 0)
        self.assertEqual(document.text, TABLES.replace("      # 題名で探す\n      - columns: [title]\n", ""))

    def test_delete_last_index_item(self):
        document = Document(TABLES)
        document.delete_item(("tables", "books", "indexes"), 1)
        self.assertEqual(document.text, TABLES.replace("      - columns: [created_at]\n        unique: true\n", ""))

    def test_cannot_delete_the_only_key_or_item(self):
        document = Document("tables:\n  a:\n    columns:\n      id:\n        type: text\n    indexes:\n      - columns: [id]\n")
        with self.assertRaises(YamlEditError):
            document.delete_item(("tables", "a", "indexes"), 0)
        with self.assertRaises(YamlEditError):
            document.delete_key(("tables", "a", "columns", "id"), "type")


class AppendItemTest(unittest.TestCase):
    def test_append_index(self):
        document = Document(TABLES)
        document.append_item(("tables", "books", "indexes"), {"columns": Flow(["id", "title"]), "unique": True})
        self.assertEqual(
            document.text,
            TABLES.replace(
                "        unique: true\n\n  members",
                "        unique: true\n      - columns: [id, title]\n        unique: true\n\n  members",
            ),
        )


FOUR_SPACES = """\
tables:
    books:
        columns:
            id:
                type: text
                definition: 図書を識別する値。
        indexes:
        -   columns: [id]
"""


class IndentationTest(unittest.TestCase):
    def test_follows_four_space_indentation(self):
        document = Document(FOUR_SPACES)
        document.insert_key(
            ("tables",), "members", {"columns": {"id": {"type": "text"}}, "indexes": [{"columns": Flow(["id"])}]}, 1
        )
        document.append_item(("tables", "books", "indexes"), {"columns": Flow(["id"]), "unique": True})
        self.assertEqual(
            document.text,
            FOUR_SPACES
            + "        -   columns: [id]\n            unique: true\n"
            "    members:\n        columns:\n            id:\n                type: text\n"
            "        indexes:\n        -   columns: [id]\n",
        )

    def test_sequence_at_the_column_of_the_key_belongs_to_the_key(self):
        document = Document(FOUR_SPACES)
        document.set_key(("tables", "books"), "planned", True, ("planned", "columns", "indexes"))
        document.insert_key(("tables", "books"), "primary_key", Flow(["id"]), 3)
        self.assertEqual(
            document.text,
            FOUR_SPACES.replace("    books:\n", "    books:\n        planned: true\n") + "        primary_key: [id]\n",
        )


class FlowStyleTest(unittest.TestCase):
    def test_refuses_to_edit_inside_flow_mapping(self):
        document = Document("tables:\n  books:\n    columns:\n      id: {type: text, definition: 番号。}\n")
        for edit in (
            lambda: document.set_key(("tables", "books", "columns", "id"), "nullable", True, COLUMN_ORDER),
            lambda: document.delete_key(("tables", "books", "columns", "id"), "definition"),
        ):
            with self.assertRaises(YamlEditError) as raised:
                edit()
            self.assertIn("ブロックスタイルで書いてから実行する", str(raised.exception))


class NewDocumentTest(unittest.TestCase):
    def test_new_document(self):
        document = new_document("tables", {"fines": {"definition": "延滞金。", "columns": {"id": {"type": "text"}}}})
        self.assertEqual(
            document.text, "tables:\n  fines:\n    definition: 延滞金。\n    columns:\n      id:\n        type: text\n"
        )


if __name__ == "__main__":
    unittest.main()
