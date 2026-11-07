"""設定ファイルの探索と読み込み (モジュール config) のテスト。

形が違う設定を 1 つずつ与え、例外 ConfigError の文に、ファイルのパスと何が違うかが入ることを確認する。
"""

import unittest

from doc_structured.config import ConfigError, find_config, load_config
from tooltest import SAMPLE_CONFIG, ProjectTestCase


class FindConfigTest(ProjectTestCase):
    def test_finds_config_from_subdirectory(self):
        path = self.write_config()
        sub = self.project / "docs" / "domains"
        sub.mkdir(parents=True)
        self.assertEqual(find_config(sub), path)

    def test_error_when_not_found(self):
        with self.assertRaises(ConfigError) as cm:
            find_config(self.project)
        self.assertIn("設定ファイル", str(cm.exception))
        self.assertIn(str(self.project), str(cm.exception))


class LoadConfigTest(ProjectTestCase):
    def assert_error(self, text: str, *fragments: str):
        path = self.write_config(text)
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        message = str(cm.exception)
        self.assertIn(str(path), message)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_valid_config(self):
        config = load_config(self.write_config())
        self.assertEqual(config.version, "0.1.0")

    def test_not_yaml(self):
        self.assert_error("version: [0.1.0\n", "YAML として読めない")

    def test_not_mapping(self):
        self.assert_error("- version: 0.1.0\n", "マッピング")

    def test_missing_version(self):
        self.assert_error("# 空の設定\n{}\n", "キー version が無い")

    def test_unknown_key(self):
        self.assert_error(SAMPLE_CONFIG + "paths:\n  tests: spec/\n", "知らないキー", "paths")

    def test_version_as_number(self):
        # 1.2 は YAML では数値になり、「version: X.Y.Z」の形でもない
        self.assert_error("version: 1.2\n", "1 行だけ要る", "0 行")

    def test_version_quoted(self):
        self.assert_error('version: "0.1.0"\n', "1 行だけ要る", "0 行")

    def test_version_with_comment_on_same_line(self):
        self.assert_error("version: 0.1.0  # ツールのバージョン\n", "1 行だけ要る", "0 行")

    def test_duplicate_version_key(self):
        # 「version: X.Y.Z」の形の行が 2 行あるファイルは、YAML としてキーが重複しているので、その時点でエラーになる
        self.assert_error("version: 0.1.0\n# 旧:\nversion: 0.0.9\n", "YAML として読めない", "duplicate key")


if __name__ == "__main__":
    unittest.main()
