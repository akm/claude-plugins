"""ドメインの YAML の読み込みと検査 h (モジュール domains) のテスト。

誤りごとに、失敗する例 (検査 h の問題が、ファイルと位置付きで出る) と、成功する例 (サンプルのプロジェクトで問題が出ない) を確かめる。
"""

import unittest

from doc_structured.domains import load_project
from tooltest import ProjectTestCase

MINIMAL_DOMAIN = """\
domain:
  description: 図書の貸出と返却を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
"""


class SampleProjectTest(ProjectTestCase):
    """成功する例: サンプルのプロジェクトは問題なく読める。"""

    def test_sample_project_loads_without_problems(self):
        project, problems = load_project(self.copy_sample())
        self.assertEqual([p.format() for p in problems], [])
        self.assertEqual([d.dir for d in project.domains], [
            "docs/domains/01-catalog", "docs/domains/02-loans", "docs/domains/03-members",
        ])
        loans = project.domains[1]
        self.assertEqual(loans.description, "図書の貸出と返却を扱う。")
        # 直下の domain.yaml のモデルが先、サブディレクトリのモデルが後
        self.assertEqual([m.name for m in loans.models], ["loan", "reservation"])
        self.assertEqual([t.id for t in loans.terms], ["d-loans-ut-business_day"])

    def test_ids_and_full_names(self):
        project, _ = load_project(self.copy_sample())
        value = project.entries["d-loans-m-loan-a-status-v-on_loan"]
        self.assertEqual(value.name_ja, "貸出中")
        self.assertEqual(value.full_name(), "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」")
        self.assertEqual(value.path, "docs/domains/02-loans/domain.yaml")
        attribute = project.entries["d-loans-m-loan-a-book"]
        self.assertEqual(attribute.refers_to, "d-catalog-m-book")

    def test_no_domains_directory(self):
        project, problems = load_project(self.project)
        self.assertEqual((project.domains, problems), ([], []))


class CheckHTest(ProjectTestCase):
    """失敗する例: 誤りごとに、検査 h の問題がファイルと位置付きで出る。"""

    def problems_for(self, files: dict[str, str]) -> list[str]:
        for relative, text in files.items():
            self.write(relative, text)
        _, problems = load_project(self.project)
        self.assertTrue(all(p.check == "h" for p in problems))
        return [p.format() for p in problems]

    def assert_problem(self, files: dict[str, str], expected: str) -> None:
        found = self.problems_for(files)
        self.assertTrue(any(expected in p for p in found), f"{expected!r} が無い: {found}")

    def test_minimal_domain_is_valid(self):
        self.assertEqual(self.problems_for({"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN}), [])

    def test_domain_directory_name(self):
        for name in ("1-loans", "01-Loans", "01_loans", "loans"):
            with self.subTest(name=name):
                self.setUp()
                self.assert_problem(
                    {f"docs/domains/{name}/domain.yaml": MINIMAL_DOMAIN},
                    f"docs/domains/{name}: 検査 h: ドメインのディレクトリ名 {name} は、NN-<名前> の形",
                )

    def test_duplicate_domain_number_and_name(self):
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN, "docs/domains/01-members/domain.yaml": MINIMAL_DOMAIN},
            "docs/domains/01-members: 検査 h: ドメインの番号 01 は、docs/domains/01-loans と同じ",
        )
        self.setUp()
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN, "docs/domains/02-loans/domain.yaml": MINIMAL_DOMAIN},
            "docs/domains/02-loans: 検査 h: ドメインの名前 loans は、docs/domains/01-loans と同じ",
        )

    def test_missing_domain_file_and_key(self):
        self.assert_problem(
            {"docs/domains/01-loans/models.yaml": "models: {}\n"},
            "docs/domains/01-loans: 検査 h: ドメインのディレクトリの直下に domain.yaml が無い",
        )
        self.setUp()
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": "models: {}\n"},
            "docs/domains/01-loans/domain.yaml:1:1: 検査 h: キー domain (ドメインの説明) が無い",
        )

    def test_domain_key_only_in_root_domain_yaml(self):
        self.assert_problem(
            {
                "docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN,
                "docs/domains/01-loans/sub/more.yaml": "domain:\n  description: x\n",
            },
            "docs/domains/01-loans/sub/more.yaml:1:1: 検査 h: キー domain は、ドメインのディレクトリの直下の domain.yaml にだけ書ける",
        )

    def test_unknown_keys(self):
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN + "operations: {}\n"},
            "docs/domains/01-loans/domain.yaml:7:1: 検査 h: 知らないキー operations",
        )
        self.setUp()
        # 値は属性の下にだけ書ける
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN + "    values: {}\n"},
            "docs/domains/01-loans/domain.yaml:7:5: 検査 h: 知らないキー values (書けるキー: name_ja, definition, attributes)",
        )

    def test_required_fields(self):
        text = "domain:\n  description: x\nmodels:\n  loan:\n    name_ja: 貸出\n"
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": text},
            "docs/domains/01-loans/domain.yaml:4:3: 検査 h: モデル loan に必須の項目 definition が無い",
        )
        self.setUp()
        text = "domain:\n  description: x\nmodels:\n  loan:\n    name_ja: ''\n    definition: 123\n"
        found = self.problems_for({"docs/domains/01-loans/domain.yaml": text})
        self.assertIn("docs/domains/01-loans/domain.yaml:5:14: 検査 h: モデル loan の name_ja は、空でない文字列でなければならない", found)
        self.assertIn("docs/domains/01-loans/domain.yaml:6:17: 検査 h: モデル loan の definition は、空でない文字列でなければならない", found)
        self.setUp()
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": "domain:\n  description: ''\n"},
            "docs/domains/01-loans/domain.yaml:2:16: 検査 h: domain の description は、空でない文字列でなければならない",
        )

    def test_name_must_be_snake_case(self):
        text = MINIMAL_DOMAIN.replace("  loan:", "  Loan:")
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": text},
            "docs/domains/01-loans/domain.yaml:4:3: 検査 h: モデルの名前 Loan が snake_case でない",
        )

    def test_name_ja_forbidden_characters(self):
        text = MINIMAL_DOMAIN.replace("name_ja: 貸出", "name_ja: '貸出\"'")
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": text},
            '検査 h: モデル loan の name_ja に、改行と " は使えない',
        )

    def test_definition_and_description_must_not_contain_cr(self):
        # 生成したファイルは改行の CR を LF として読むので、CR を含む文は生成し直した内容と一致しなくなる
        text = MINIMAL_DOMAIN.replace("definition: 利用者が図書を借りてから返すまでの 1 回の記録。", 'definition: "利用者が図書を\\r借りる記録。"')
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": text},
            "docs/domains/01-loans/domain.yaml:6:17: 検査 h: モデル loan の definition に、CR は使えない",
        )
        self.setUp()
        text = MINIMAL_DOMAIN.replace("description: 図書の貸出と返却を扱う。", 'description: "図書の貸出と\\r返却を扱う。"')
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": text},
            "docs/domains/01-loans/domain.yaml:2:16: 検査 h: domain の description に、CR は使えない",
        )

    def test_duplicate_names(self):
        self.assert_problem(
            {
                "docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN,
                "docs/domains/01-loans/sub/more.yaml": MINIMAL_DOMAIN.split("models:\n")[1].join(["models:\n", ""]),
            },
            "docs/domains/01-loans/sub/more.yaml:2:3: 検査 h: モデル loan は、docs/domains/01-loans/domain.yaml:4 にもある",
        )
        self.setUp()
        # 同じファイルの中の重複は、YAML を読む時点の誤り
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN + "  loan:\n    name_ja: x\n    definition: y\n"},
            "docs/domains/01-loans/domain.yaml:7:3: 検査 h: YAML として読めない",
        )

    def test_yml_extension(self):
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN, "docs/domains/01-loans/more.yml": "models: {}\n"},
            "docs/domains/01-loans/more.yml: 検査 h: 拡張子は .yaml にする",
        )

    def test_yaml_syntax_error_has_position(self):
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": "domain:\n  description: [x\n"},
            "docs/domains/01-loans/domain.yaml:3:1: 検査 h: YAML として読めない",
        )

    def test_yaml_syntax_error_in_root_domain_yaml_is_reported_once(self):
        # 引用符の無い値の「: 」は YAML の誤り。読めないファイルに、キー domain が無いとは報告しない
        # (キーがあるかどうかは、読めないと分からないため)
        self.assertEqual(
            self.problems_for(
                {
                    "docs/domains/01-loans/domain.yaml": MINIMAL_DOMAIN
                    + "unclassified_app_terms:\n"
                    + "  opening_hours:\n"
                    + "    name_ja: 開館時間\n"
                    + "    definition: 図書館が開いている時刻の範囲 (例: 9:00〜17:00)。\n"
                }
            ),
            ["docs/domains/01-loans/domain.yaml:10:34: 検査 h: YAML として読めない: mapping values are not allowed here"],
        )

    def test_empty_root_domain_yaml_lacks_domain_key(self):
        self.assert_problem(
            {"docs/domains/01-loans/domain.yaml": ""},
            "docs/domains/01-loans/domain.yaml: 検査 h: キー domain (ドメインの説明) が無い",
        )

    def test_refers_to(self):
        def with_ref(target: str) -> str:
            return MINIMAL_DOMAIN + (
                "    attributes:\n"
                "      book:\n"
                "        name_ja: 貸出図書\n"
                "        definition: 貸し出した図書。\n"
                f"        refers_to: {target}\n"
            )

        self.assertEqual(self.problems_for({"docs/domains/01-loans/domain.yaml": with_ref("d-loans-m-loan")}), [])
        for target, expected in (
            ("d-loans-m-book", "refers_to の参照先 d-loans-m-book が無い"),
            ("d-loans-m-loan-a-book", "refers_to の参照先 d-loans-m-loan-a-book はモデルでない"),
            ("m-book", "refers_to の値が ID の形でない"),
        ):
            with self.subTest(target=target):
                self.setUp()
                self.assert_problem(
                    {"docs/domains/01-loans/domain.yaml": with_ref(target)},
                    f"docs/domains/01-loans/domain.yaml:11:20: 検査 h: {expected}",
                )


if __name__ == "__main__":
    unittest.main()
