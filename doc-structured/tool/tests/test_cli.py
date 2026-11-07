"""コマンド doc-structured (モジュール cli) のテスト。

python -m doc_structured をサンプルのプロジェクトの中で実行し、標準出力・標準エラー出力・終了コードを見る。
"""

import subprocess
import unittest

from doc_structured import __version__
from tooltest import PYTHON, ProjectTestCase, clean_env


class CliTest(ProjectTestCase):
    def run_tool(self, *args: str, cwd=None):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args],
            cwd=cwd or self.project,
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def test_version_subcommand(self):
        self.write_config()
        result = self.run_tool("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"doc-structured {__version__}\n")

    def test_version_subcommand_from_subdirectory(self):
        self.write_config()
        sub = self.project / "docs"
        sub.mkdir()
        result = self.run_tool("version", cwd=sub)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_option_does_not_need_config(self):
        result = self.run_tool("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"doc-structured {__version__}\n")

    def test_unknown_subcommand_exits_with_2(self):
        self.write_config()
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("generate", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_subcommand_exits_with_2(self):
        self.write_config()
        result = self.run_tool()
        self.assertEqual(result.returncode, 2)

    def test_missing_config_exits_with_1(self):
        result = self.run_tool("version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("設定ファイル", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_invalid_config_exits_with_1(self):
        self.write_config("version: 1.2\n")
        result = self.run_tool("version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("version: X.Y.Z", result.stderr)


if __name__ == "__main__":
    unittest.main()
