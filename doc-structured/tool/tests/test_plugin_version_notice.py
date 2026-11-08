"""スキルに共通する前置きのスクリプト scripts/plugin-version-notice のテスト。

同じ・違う・設定が無い・version の行が無い、の場合の出力と終了コードを確かめる。
"""

import json
import subprocess
import unittest

from tooltest import PLUGIN_DIR, PYTHON, ProjectTestCase, clean_env

SCRIPT = PLUGIN_DIR / "scripts" / "plugin-version-notice"
PLUGIN_VERSION = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


class PluginVersionNoticeTest(ProjectTestCase):
    def run_script(self, cwd=None):
        return subprocess.run(
            [PYTHON, str(SCRIPT)], cwd=cwd or self.project, env=clean_env(), capture_output=True, text=True
        )

    def test_script_is_executable(self):
        self.assertTrue(SCRIPT.stat().st_mode & 0o111)

    def test_same_version_prints_nothing(self):
        self.write_config(f"version: {PLUGIN_VERSION}\n")
        sub = self.project / "docs"
        sub.mkdir()
        result = self.run_script(cwd=sub)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_different_version_prints_one_line_and_succeeds(self):
        self.write_config("# 古いバージョンのまま\nversion: 0.0.1\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"プラグイン doc-structured は {PLUGIN_VERSION}、このプロジェクトの設定の version は 0.0.1 です。"
            "スキルの説明とツールの振る舞いが違う場合があります。\n",
        )

    def test_missing_config_fails(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("設定ファイル .claude/akm-claude-plugins/doc-structured/config.yaml が見つからない", result.stderr)

    def test_missing_version_line_fails(self):
        self.write_config('version: "0.2.0"\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("「version: X.Y.Z」の形の行が 1 行だけ要る", result.stderr)


if __name__ == "__main__":
    unittest.main()
