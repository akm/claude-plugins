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


if __name__ == "__main__":
    unittest.main()
