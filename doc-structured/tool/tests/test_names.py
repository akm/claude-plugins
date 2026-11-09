"""ID と限定付きの名前 (モジュール names) のテスト。"""

import unittest

from doc_structured import names
from doc_structured.names import IdError, Part


class NameTest(unittest.TestCase):
    def test_snake_case_names(self):
        for ok in ("loan", "on_loan", "a1", "business_day", "x2_y3"):
            self.assertTrue(names.is_name(ok), ok)
        for ng in ("", "Loan", "1loan", "on__loan", "loan_", "_loan", "on-loan", "貸出"):
            self.assertFalse(names.is_name(ng), ng)


class IdTest(unittest.TestCase):
    def test_build_and_parse_round_trip(self):
        parts = [Part("d", "loans"), Part("m", "loan"), Part("a", "status"), Part("v", "on_loan")]
        text = names.build_id(parts)
        self.assertEqual(text, "d-loans-m-loan-a-status-v-on_loan")
        self.assertEqual(names.parse_id(text), parts)

    def test_unclassified_app_term_and_file_ids(self):
        self.assertEqual(names.parse_id("d-loans-ut-business_day"), [Part("d", "loans"), Part("ut", "business_day")])
        self.assertEqual(names.parse_id("d-loans-models"), [Part("d", "loans"), Part("models", None)])
        self.assertEqual(names.kind_of("d-loans-m-loan"), "m")

    def test_handwritten_file_section_and_child_file_ids(self):
        self.assertEqual(names.parse_id("d-loans-concept"), [Part("d", "loans"), Part("concept", None)])
        self.assertEqual(
            names.parse_id("d-loans-concept-h-return_deadline"),
            [Part("d", "loans"), Part("concept", None), Part("h", "return_deadline")],
        )
        parts = [Part("d", "push"), Part("design", None), Part("f", "device_operations"), Part("h", "retry")]
        self.assertEqual(names.build_id(parts), "d-push-design-f-device_operations-h-retry")
        self.assertEqual(names.parse_id("d-push-design-f-device_operations-h-retry"), parts)
        self.assertEqual(names.kind_of("d-loans-problem-h-x"), "h")

    def test_invalid_ids(self):
        for text in (
            "m-loan",  # モデルはドメインの下にだけ書ける
            "d-loans-a-status",  # 属性はモデルの下にだけ書ける
            "d-loans-m-loan-ut-x",  # 未分類のアプリケーション用語はドメインの下にだけ書ける
            "d-loans-m",  # 名前が無い
            "d-Loans",  # 名前が snake_case でない
            "d-loans-x-y",  # 知らない記号
            "d-loans-models-m-loan",  # ファイルの種類は最後にだけ書ける
            "d-loans-m-loan-models",  # ファイルの種類はドメインの直後にだけ書ける
            "d-loans-m-loan-concept",  # 手書きのファイルの種類はドメインの直後にだけ書ける
            "d-loans-h-due",  # 節は手書きのファイルの下にだけ書ける
            "d-loans-models-h-due",  # 生成するファイルの下に節は書けない
            "d-loans-concept-h-due-h-x",  # 節の下に節は書けない
            "d-loans-concept-f-a-f-b",  # 子のファイルは 1 階層だけ
            "d-loans-concept-h-due-f-x",  # 節の下に子のファイルは書けない
            "d-loans-concept-m-loan",  # 手書きのファイルの下にモデルは書けない
            "d-loans-concept-h-Due",  # 節の名前が snake_case でない
        ):
            with self.subTest(text=text), self.assertRaises(IdError):
                names.parse_id(text)


class QualifiedNameTest(unittest.TestCase):
    def test_user_level_and_developer_level_parts(self):
        formatted = [
            names.format_part("d", "loans"),
            names.format_part("m", "貸出"),
            names.format_part("a", "貸出状態"),
            names.format_part("v", "貸出中"),
        ]
        self.assertEqual(
            names.join_parts(formatted), "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
        )

    def test_unclassified_app_term_and_file(self):
        self.assertEqual(names.format_part("ut", "開館日"), "未分類のアプリケーション用語「開館日」")
        self.assertEqual(names.format_part("models", "models.md"), "ファイル `models.md`")

    def test_handwritten_file_child_file_and_section(self):
        self.assertEqual(
            names.join_parts(
                [names.format_part("d", "loans"), names.format_part("concept", "concept.md"), names.format_part("h", "返却期限")]
            ),
            "ドメイン `loans` のファイル `concept.md` の節「返却期限」",
        )
        self.assertEqual(
            names.join_parts([names.format_part("d", "push"), names.format_part("f", "design/device_operations.md")]),
            "ドメイン `push` のファイル `design/device_operations.md`",
        )


if __name__ == "__main__":
    unittest.main()
