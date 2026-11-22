"""テーブルとカラム (ファイル名が schema で始まる YAML) のテスト。読み込みと検査 h (モジュール domains と tables)・
検査 i (モジュール direction) の、失敗する例と成功する例を確認する。"""

import unittest

from doc_structured.direction import check_direction
from doc_structured.domains import load_project
from tooltest import ProjectTestCase

CATALOG = "docs/domains/01-catalog/domain.yaml"
CATALOG_SCHEMA = "docs/domains/01-catalog/schema.yaml"
LOANS = "docs/domains/02-loans/domain.yaml"
LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"

CATALOG_DOMAIN = """\
domain:
  description: 図書を扱う。
"""
LOANS_DOMAIN = """\
domain:
  description: 貸出を扱う。
"""
BOOKS = """\
tables:
  books:
    definition: 図書の行。
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 図書を識別する値。
      isbn:
        type: text
        definition: ISBN。
    indexes:
      - columns: [isbn]
        unique: true
"""
# LOANS_TABLE の columns の下に足す行は、行 LOANS_TABLE_LINES + 1 から始まる
LOANS_TABLE = """\
tables:
  loans:
    definition: 貸出の行。
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 貸出を識別する値。
      book_id:
        type: text
        definition: 貸し出した図書。
        references: d-catalog-t-books-c-id
"""
LOANS_TABLE_LINES = 12


class SchemaTestCase(ProjectTestCase):
    def files(self, loans_schema: str = LOANS_TABLE, **extra: str) -> dict[str, str]:
        files = {CATALOG: CATALOG_DOMAIN, CATALOG_SCHEMA: BOOKS, LOANS: LOANS_DOMAIN, LOANS_SCHEMA: loans_schema}
        files.update({k.replace("__", "/"): v for k, v in extra.items()})
        return files

    def problems_for(self, files: dict[str, str]) -> list[str]:
        for relative, text in files.items():
            self.write(relative, text)
        _, problems = load_project(self.project)
        self.assertTrue(all(p.check == "h" for p in problems))
        return [p.format() for p in problems]

    def assert_problem(self, files: dict[str, str], expected: str) -> None:
        found = self.problems_for(files)
        self.assertTrue(any(expected in p for p in found), f"{expected!r} が無い: {found}")


class LoadTablesTest(SchemaTestCase):
    """成功する例: テーブルとカラムを読み、ID と完全な名前を作る。"""

    def test_valid_tables_have_no_problems(self):
        self.assertEqual(self.problems_for(self.files()), [])

    def test_ids_full_names_and_specs(self):
        for relative, text in self.files().items():
            self.write(relative, text)
        project, _ = load_project(self.project)
        loans = project.domains[1]
        self.assertEqual([t.id for t in loans.tables], ["d-loans-t-loans"])
        column = project.entries["d-loans-t-loans-c-book_id"]
        self.assertEqual(column.full_name(), "ドメイン `loans` のテーブル `loans` のカラム `book_id`")
        self.assertEqual(column.owner, "テーブル loans のカラム book_id")
        self.assertEqual(column.spec.type, "text")
        self.assertEqual(column.reference("references").target, "d-catalog-t-books-c-id")
        books = project.entries["d-catalog-t-books"]
        self.assertEqual(books.spec.primary_key, ["id"])
        self.assertEqual([(i.columns, i.unique) for i in books.spec.indexes], [(["isbn"], True)])
        # テーブルとカラムは、用語の索引に載せる定義 (Domain.entries) に含めない
        self.assertNotIn(column, list(loans.entries()))

    def test_schema_files_in_any_depth_and_name(self):
        files = self.files(**{"docs__domains__02-loans__sub__schema-holds.yaml": "tables:\n  holds:\n    definition: 取り置き。\n"
                              "    columns:\n      id:\n        type: text\n        definition: 識別する値。\n"})
        self.assertEqual(self.problems_for(files), [])

    def test_nullable_default_planned_in_overview(self):
        extra = (
            "      returned_at:\n        type: integer\n        definition: 返った時刻。\n        nullable: true\n"
            "        planned: true\n"
            "      status:\n        type: text\n        definition: 状態。\n        default: \"'on_loan'\"\n"
            "        in_overview: true\n"
        )
        for relative, text in self.files(LOANS_TABLE + extra).items():
            self.write(relative, text)
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        returned_at = project.entries["d-loans-t-loans-c-returned_at"].spec
        self.assertEqual((returned_at.nullable, returned_at.planned), (True, True))
        status = project.entries["d-loans-t-loans-c-status"].spec
        self.assertEqual((status.default, status.in_overview), ("'on_loan'", True))


class FileAndTableTest(SchemaTestCase):
    """失敗する例: ファイルとテーブルの形。"""

    def test_tables_key_only_in_schema_files(self):
        self.assert_problem(
            self.files(**{"docs__domains__02-loans__more.yaml": "tables: {}\n"}),
            "docs/domains/02-loans/more.yaml:1:1: 検査 h: キー tables は、ファイル名が schema で始まる YAML にだけ書ける",
        )

    def test_schema_files_have_only_tables(self):
        self.assert_problem(
            self.files(LOANS_TABLE + "models: {}\n"),
            f"{LOANS_SCHEMA}:{LOANS_TABLE_LINES + 1}:1: 検査 h: ファイル名が schema で始まる YAML には、キー tables だけを書ける",
        )

    def test_table_name_must_be_snake_case(self):
        self.assert_problem(
            self.files("tables:\n  Loans:\n    columns:\n      id:\n        type: text\n"),
            f"{LOANS_SCHEMA}:2:3: 検査 h: テーブルの名前 Loans が snake_case でない",
        )

    def test_same_table_name_in_two_domains(self):
        self.assert_problem(
            self.files(LOANS_TABLE + BOOKS.replace("tables:\n", "")),
            f"{LOANS_SCHEMA}:{LOANS_TABLE_LINES + 1}:3: 検査 h: テーブル books は、{CATALOG_SCHEMA}:2 にもある "
            "(テーブル名は、ドメインが違っても同じにできない)",
        )

    def test_columns_required_and_not_empty(self):
        self.assert_problem(
            self.files("tables:\n  loans:\n    definition: 貸出。\n"),
            f"{LOANS_SCHEMA}:2:3: 検査 h: テーブル loans に必須の項目 columns が無い",
        )
        self.setUp()
        self.assert_problem(
            self.files("tables:\n  loans:\n    definition: 貸出。\n    columns: {}\n"),
            f"{LOANS_SCHEMA}:4:14: 検査 h: テーブル loans の columns は、空にできない",
        )

    def test_unknown_keys(self):
        self.assert_problem(
            self.files(LOANS_TABLE + "        unique: true\n"),
            f"{LOANS_SCHEMA}:{LOANS_TABLE_LINES + 1}:9: 検査 h: 知らないキー unique (書けるキー: type, nullable, default, "
            "references, attribute, definition, planned, in_overview)",
        )


class ColumnTest(SchemaTestCase):
    """失敗する例: カラムの項目。"""

    def column(self, lines: str) -> dict[str, str]:
        return self.files(LOANS_TABLE + "      extra:\n" + lines)

    def test_type_required(self):
        self.assert_problem(
            self.column("        definition: 余り。\n"),
            f"{LOANS_SCHEMA}:{LOANS_TABLE_LINES + 1}:7: 検査 h: テーブル loans のカラム extra に必須の項目 type が無い",
        )

    def test_nullable_true_only(self):
        self.assert_problem(
            self.column("        type: text\n        definition: 余り。\n        nullable: false\n"),
            f"{LOANS_SCHEMA}:{LOANS_TABLE_LINES + 4}:19: 検査 h: テーブル loans のカラム extra の nullable に false は書けない "
            "(NOT NULL のカラムは、nullable を省く)",
        )
        self.setUp()
        self.assert_problem(
            self.column("        type: text\n        definition: 余り。\n        nullable: yes\n"),
            "検査 h: テーブル loans のカラム extra の nullable は、true だけを書ける",
        )

    def test_default_is_sql_string(self):
        cases = {
            "0": 'YAML の数値は引用符で囲む。例 default: "0"',
            "false": 'YAML の真偽値は引用符で囲む。例 default: "false"',
            '""': "SQL の式の空でない文字列でなければならない",
        }
        for written, expected in cases.items():
            with self.subTest(default=written):
                self.setUp()
                self.assert_problem(
                    self.column(f"        type: text\n        definition: 余り。\n        default: {written}\n"),
                    f"検査 h: テーブル loans のカラム extra の default は、{expected}" if written == '""' else expected,
                )

    def test_references_target(self):
        cases = {
            "d-catalog-t-books-c-title": "の参照先 d-catalog-t-books-c-title が無い",
            "d-catalog-t-books": "の参照先 d-catalog-t-books はカラムでない (参照できるのはカラムだけ)",
            "books.id": "の値が ID の形でない",
        }
        for target, expected in cases.items():
            with self.subTest(target=target):
                self.setUp()
                self.assert_problem(
                    self.column(f"        type: text\n        definition: 余り。\n        references: {target}\n"),
                    f"テーブル loans のカラム extra の references {expected}",
                )

    def test_references_target_must_be_unique(self):
        self.assert_problem(
            self.column("        type: text\n        definition: 余り。\n        references: d-catalog-t-books-c-id\n")
            | {CATALOG_SCHEMA: BOOKS.replace("    primary_key: [id]\n", "")},
            "テーブル loans のカラム book_id の references の参照先 d-catalog-t-books-c-id は、テーブル books の 1 カラムの主キーでも、"
            "そのカラムだけの一意のインデックスを持つカラムでもない (外部キーの参照先は、主キーか一意の制約を持つカラムにする)",
        )
        self.setUp()
        # そのカラムだけの一意のインデックスを持つカラムは参照できる
        self.assertEqual(
            self.problems_for(self.column("        type: text\n        definition: 余り。\n        references: d-catalog-t-books-c-isbn\n")),
            [],
        )

    def test_planned(self):
        self.assert_problem(
            self.column("        type: text\n        definition: 余り。\n        planned: false\n"),
            "テーブル loans のカラム extra の planned に false は書けない (実装済みなら、planned を省く)",
        )
        self.setUp()
        self.assert_problem(
            self.files(LOANS_TABLE.replace("    definition: 貸出の行。\n", "    definition: 貸出の行。\n    planned: true\n")
                       + "        planned: true\n"),
            "テーブル loans に planned があるので、テーブル loans のカラム book_id に planned を書けない "
            "(未実装のテーブルのカラムとインデックスは、すべて未実装として扱う)",
        )

    def test_implemented_column_cannot_reference_planned_column(self):
        planned_books = BOOKS.replace("    definition: 図書の行。\n", "    definition: 図書の行。\n    planned: true\n")
        self.assert_problem(
            self.files() | {CATALOG_SCHEMA: planned_books},
            "テーブル loans のカラム book_id は実装済みなので、未実装のカラム d-catalog-t-books-c-id を references で参照できない "
            "(このカラムにも planned を書くか、参照先の planned を外す)",
        )
        self.setUp()
        # 参照するカラムも未実装なら成功する
        self.assertEqual(
            self.problems_for(self.files(LOANS_TABLE + "        planned: true\n") | {CATALOG_SCHEMA: planned_books}), []
        )

    def test_in_overview(self):
        self.assert_problem(
            self.files(LOANS_TABLE + "        in_overview: true\n"),
            "テーブル loans のカラム book_id はキーのカラム (FK) で、全体の図にいつも描かれるので、in_overview を書けない",
        )
        self.setUp()
        self.assert_problem(
            self.column("        type: text\n        definition: 余り。\n        in_overview: false\n"),
            "の in_overview に false は書けない (全体の図に描かないカラムは、in_overview を省く)",
        )


class KeyAndIndexTest(SchemaTestCase):
    """失敗する例: 主キーとインデックス。"""

    def test_primary_key(self):
        cases = {
            "[]": "テーブル loans の primary_key は、空の配列にできない (主キーが無いテーブルは、primary_key を省く)",
            "[code]": "テーブル loans の primary_key のカラム code は、テーブル loans に無い",
            "[id, id]": "テーブル loans の primary_key に id が 2 回ある",
            "id": "テーブル loans の primary_key は、カラム名の配列でなければならない",
        }
        for written, expected in cases.items():
            with self.subTest(primary_key=written):
                self.setUp()
                self.assert_problem(self.files(LOANS_TABLE.replace("[id]", written)), expected)

    def test_primary_key_column_cannot_be_nullable(self):
        self.assert_problem(
            self.files(LOANS_TABLE.replace("        definition: 貸出を識別する値。\n",
                                           "        definition: 貸出を識別する値。\n        nullable: true\n")),
            "テーブル loans のカラム id は主キーのカラムなので、nullable: true を書けない",
        )

    def test_indexes(self):
        cases = {
            "    indexes: []\n": "テーブル loans の indexes は、空の配列にできない (インデックスが無いテーブルは、indexes を省く)",
            "    indexes:\n      - unique: true\n": "テーブル loans の indexes の 1 番目に必須の項目 columns が無い",
            "    indexes:\n      - columns: [code]\n": "テーブル loans の indexes の 1 番目の columns のカラム code は、テーブル loans に無い",
            "    indexes:\n      - columns: [book_id]\n        unique: false\n":
                "テーブル loans の indexes の 1 番目の unique に false は書けない (一意でないインデックスは、unique を省く)",
            "    indexes:\n      - columns: [book_id]\n      - columns: [book_id]\n":
                "テーブル loans の indexes の 2 番目は、1 番目と columns と unique が同じ",
        }
        for written, expected in cases.items():
            with self.subTest(indexes=written):
                self.setUp()
                self.assert_problem(self.files(LOANS_TABLE + written), expected)
        self.setUp()
        # columns が同じでも、unique が違えば別のインデックス
        self.assertEqual(
            self.problems_for(self.files(LOANS_TABLE + "    indexes:\n      - columns: [book_id]\n      - columns: [book_id]\n"
                                         "        unique: true\n")),
            [],
        )

    def test_implemented_index_cannot_include_planned_column(self):
        planned = LOANS_TABLE + "        planned: true\n"
        self.assert_problem(
            self.files(planned + "    indexes:\n      - columns: [book_id]\n"),
            "テーブル loans の indexes の 1 番目は実装済みなので、未実装のカラム book_id を含められない "
            "(インデックスにも planned を書くか、カラムの planned を外す)",
        )
        self.setUp()
        self.assertEqual(
            self.problems_for(self.files(planned + "    indexes:\n      - columns: [book_id]\n        planned: true\n")), []
        )


# モデルとの対応のテストの、ドメイン loans のモデル。貸出は、図書 (ドメイン catalog) と予約を参照し、状態の遷移を持つ
MAPPED_LOANS_DOMAIN = """\
domain:
  description: 貸出を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 1 回の貸出。
    attributes:
      book:
        name_ja: 貸出図書
        definition: 貸し出した図書。
        refers_to: d-catalog-m-book
      status:
        name_ja: 貸出状態
        definition: 貸出の段階。
        values:
          on_loan:
            name_ja: 貸出中
            definition: 手元にある。
          returned:
            name_ja: 返却済み
            definition: 戻った。
        state_machine:
          transitions:
            - from: [on_loan]
              to: returned
      holds:
        name_ja: 取り置き
        definition: この貸出に付けた取り置き。
        refers_to: d-loans-m-hold
  hold:
    name_ja: 取り置き
    definition: 図書の取り置き。
"""
MAPPED_CATALOG_DOMAIN = """\
domain:
  description: 図書を扱う。
models:
  book:
    name_ja: 図書
    definition: 1 冊の本。
"""
MAPPED_BOOKS = BOOKS.replace("    definition: 図書の行。\n", "    model: d-catalog-m-book\n")
MAPPED_LOANS = """\
tables:
  loans:
    model: d-loans-m-loan
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 貸出を識別する値。
      book_id:
        type: text
        references: d-catalog-t-books-c-id
        attribute: d-loans-m-loan-a-book
      status:
        type: text
        attribute: d-loans-m-loan-a-status
  loan_holds:
    attribute: d-loans-m-loan-a-holds
    columns:
      loan_id:
        type: text
        definition: 貸出。
        references: d-loans-t-loans-c-id
"""


class MappingTest(SchemaTestCase):
    """モデルと属性との対応 (テーブルの model・attribute、カラムの attribute) の、成功する例と失敗する例。"""

    def mapped(self, loans_schema: str = MAPPED_LOANS) -> dict[str, str]:
        return {
            CATALOG: MAPPED_CATALOG_DOMAIN, CATALOG_SCHEMA: MAPPED_BOOKS, LOANS: MAPPED_LOANS_DOMAIN, LOANS_SCHEMA: loans_schema,
        }

    def test_valid_mapping_has_no_problems(self):
        self.assertEqual(self.problems_for(self.mapped()), [])

    def test_model_and_attribute_kinds(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("model: d-loans-m-loan\n", "model: d-loans-m-loan-a-book\n")),
            "テーブル loans の model の参照先 d-loans-m-loan-a-book はモデルでない (参照できるのはモデルだけ)",
        )
        self.setUp()
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("attribute: d-loans-m-loan-a-status", "attribute: d-loans-m-loan")),
            "テーブル loans のカラム status の attribute の参照先 d-loans-m-loan は属性でない (参照できるのは属性だけ)",
        )

    def test_model_and_attribute_together(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("    model: d-loans-m-loan\n", "    model: d-loans-m-loan\n    attribute: d-loans-m-loan-a-holds\n")),
            f"{LOANS_SCHEMA}:4:5: 検査 h: テーブル loans には、model と attribute のどちらか 1 つだけを書ける",
        )

    def test_mapping_to_other_domain(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("model: d-loans-m-loan\n", "model: d-catalog-m-book\n")),
            "テーブル loans の model の参照先 d-catalog-m-book は、ほかのドメインの定義 "
            "(テーブルとカラムは、対応するモデルと属性と同じドメインに書く)",
        )

    def test_column_attribute_needs_table_model(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("        definition: 貸出。\n", "        attribute: d-loans-m-loan-a-book\n")),
            "テーブル loan_holds のカラム loan_id の attribute は、model を書いたテーブルのカラムにだけ書ける "
            "(中間テーブルと、対応するモデルが無いテーブルのカラムには書けない)",
        )

    def test_column_attribute_must_belong_to_table_model(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace(
                "  loan_holds:\n", "  holds:\n    model: d-loans-m-hold\n    columns:\n      x:\n        type: text\n"
                "        attribute: d-loans-m-loan-a-book\n  loan_holds:\n"
            )),
            "テーブル holds のカラム x の attribute の参照先 d-loans-m-loan-a-book は、テーブル holds の model (d-loans-m-hold) の属性でない",
        )

    def test_references_must_match_refers_to(self):
        unmapped_books = MAPPED_BOOKS.replace("    model: d-catalog-m-book\n", "    definition: 図書の行。\n")
        self.assert_problem(
            self.mapped() | {CATALOG_SCHEMA: unmapped_books},
            "テーブル loans のカラム book_id の references が指すテーブル books の model (無し) が、attribute の参照先 "
            "d-loans-m-loan-a-book の refers_to (d-catalog-m-book) と違う",
        )

    def test_definition_with_mapping(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("    model: d-loans-m-loan\n", "    model: d-loans-m-loan\n    definition: 貸出の行。\n")),
            f"{LOANS_SCHEMA}:4:5: 検査 h: テーブル loans には対応するモデルか属性を書いたので、definition を書けない "
            "(定義は、対応するモデルか属性にある)",
        )
        self.setUp()
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("        attribute: d-loans-m-loan-a-status\n",
                                             "        attribute: d-loans-m-loan-a-status\n        definition: 状態。\n")),
            "テーブル loans のカラム status には対応する属性を書いたので、definition を書けない",
        )

    def test_definition_without_mapping(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("        definition: 貸出を識別する値。\n", "")),
            f"{LOANS_SCHEMA}:6:7: 検査 h: テーブル loans のカラム id に definition が無い (対応する属性を書かないカラムには、definition が必須)",
        )
        self.setUp()
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("    attribute: d-loans-m-loan-a-holds\n", "")),
            "テーブル loan_holds に definition が無い (対応するモデルか属性を書かないテーブルには、definition が必須)",
        )

    def test_every_attribute_of_mapped_model_has_column(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("  loan_holds:\n    attribute: d-loans-m-loan-a-holds\n",
                                             "  loan_holds:\n    definition: 中間テーブルの行。\n")),
            f"{LOANS_SCHEMA}:3:12: 検査 h: モデル loan の属性 holds (d-loans-m-loan-a-holds) に対応するカラムが無い "
            "(テーブル loans が model でこのモデルを指すので、属性ごとに、カラムの attribute か中間テーブルの attribute で対応を書く)",
        )

    def test_in_overview_on_state_machine_column(self):
        self.assert_problem(
            self.mapped(MAPPED_LOANS.replace("        attribute: d-loans-m-loan-a-status\n",
                                             "        attribute: d-loans-m-loan-a-status\n        in_overview: true\n")),
            "テーブル loans のカラム status は状態の遷移を持つ属性 d-loans-m-loan-a-status に対応し、全体の図にいつも描かれるので、"
            "in_overview を書けない",
        )

    def test_mapping_direction(self):
        for relative, text in (self.mapped() | {"docs/domains/02-loans/sub/hold.yaml": "models: {}\n"}).items():
            self.write(relative, text)
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        self.assertEqual(check_direction(project), [])


class DirectionTest(SchemaTestCase):
    """検査 i: カラムの references も、祖先のディレクトリの YAML の定義を参照できない。"""

    def direction_problems(self, files: dict[str, str]) -> list[str]:
        for relative, text in files.items():
            self.write(relative, text)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [])
        return [p.format() for p in check_direction(project)]

    def test_reference_to_ancestor_directory_fails(self):
        sub = "tables:\n  holds:\n    definition: 取り置き。\n    columns:\n      loan_id:\n        type: text\n" \
              "        definition: 貸出。\n        references: d-loans-t-loans-c-id\n"
        found = self.direction_problems(self.files(**{"docs__domains__02-loans__sub__schema.yaml": sub}))
        self.assertEqual(found, [
            "docs/domains/02-loans/sub/schema.yaml:8:21: 検査 i: テーブル holds のカラム loan_id の references の参照先 "
            "d-loans-t-loans-c-id は、祖先のディレクトリの docs/domains/02-loans/schema.yaml にある。"
            "参照される定義 (d-loans-t-loans-c-id) を、参照するファイルと同じディレクトリかその下に移す"
        ])

    def test_reference_to_other_domain_and_same_directory_succeeds(self):
        self.assertEqual(self.direction_problems(self.files()), [])


if __name__ == "__main__":
    unittest.main()
