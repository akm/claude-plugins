"""hook (スクリプト doc-structured/hook-scripts/guard-generated.py) のテスト。

Claude Code が PreToolUse の hook に渡す JSON を標準入力で渡し、生成したファイルへの Edit・Write・NotebookEdit を拒否すること、
手書きのファイルとまだ無いファイルへの編集を拒否しないことを確認する。Claude Code が hook を実際に読み込むことは、
自動テストでは確認できないので、Issue #195 に書いた手順で確認する。
"""

import json
import shutil
import subprocess
import unittest

from doc_structured import generated_header as gh
from tooltest import PLUGIN_DIR, PYTHON, ProjectTestCase, clean_env

HOOK_SCRIPT = PLUGIN_DIR / "hook-scripts" / "guard-generated.py"
HOOKS_JSON = PLUGIN_DIR / "hooks" / "hooks.json"
MODELS = "docs/domains/02-loans/models.md"
HANDWRITTEN = "docs/domains/02-loans/concept.md"


class GuardGeneratedHookTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()
        self.write(HANDWRITTEN, "# 貸出の概念\n\n手書きの文書。\n")

    def run_hook(self, tool_name: str, path: str, cwd=None):
        key = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {key: path},
            "cwd": str(cwd or self.project),
        }
        return subprocess.run(
            [PYTHON, str(HOOK_SCRIPT)],
            input=json.dumps(payload),
            cwd=self.tmp,
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def assert_denied(self, result, source: str):
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        reason = output["permissionDecisionReason"]
        self.assertIn("生成したファイル", reason)
        self.assertIn(f"生成元 {source}", reason)
        self.assertIn("bin/doc-structured generate", reason)
        self.assertIn("doc-structured:generate", reason)
        return reason

    def assert_allowed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_denies_edit_write_and_notebook_edit_of_generated_markdown(self):
        for tool_name in ("Edit", "Write", "NotebookEdit"):
            with self.subTest(tool=tool_name):
                reason = self.assert_denied(
                    self.run_hook(tool_name, str(self.project / MODELS)), "docs/domains/02-loans/"
                )
                self.assertIn(MODELS, reason)

    def test_denies_generated_gitattributes(self):
        # 内容は生成したファイルの一覧から作るので、生成元の YAML ではなく、属性を足す場所を案内する
        result = self.run_hook("Edit", str(self.project / "docs/.gitattributes"))
        self.assertEqual(result.returncode, 0, result.stderr)
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn(gh.GITATTRIBUTES_GUIDE, reason)
        self.assertNotIn("生成元 docs/domains/", reason)
        self.assertIn("bin/doc-structured generate", reason)

    def test_denies_generated_markdown_with_frontmatter(self):
        path = self.write(
            "docs/generated-with-frontmatter.md",
            "---\n" + gh.hash_line("docs/domains/02-loans/") + "\ntitle: x\n---\n\n# 本文\n",
        )
        self.assert_denied(self.run_hook("Write", str(path)), "docs/domains/02-loans/")

    def test_denies_generated_file_saved_with_bom(self):
        path = self.project / MODELS
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assert_denied(self.run_hook("Edit", str(path)), "docs/domains/02-loans/")

    def test_relative_path_is_resolved_from_cwd(self):
        self.assert_denied(self.run_hook("Edit", MODELS), "docs/domains/02-loans/")
        self.assert_allowed(self.run_hook("Edit", HANDWRITTEN))

    def test_reason_shows_absolute_path_and_bases(self):
        # 対象は cwd に関わらず絶対パスで示し、生成元とコマンドの基準 (リポジトリのルート) を書く
        for cwd, path in ((self.project, MODELS), (self.project / "docs", "../" + MODELS)):
            with self.subTest(cwd=cwd):
                reason = self.assert_denied(self.run_hook("Edit", path, cwd=cwd), "docs/domains/02-loans/")
                self.assertTrue(reason.startswith(f"{self.project / MODELS} は "), reason)
                self.assertIn("(リポジトリのルートからの相対パス)", reason)
                self.assertIn("リポジトリのルートで実行するコマンド bin/doc-structured generate", reason)

    def test_allows_handwritten_files(self):
        for tool_name in ("Edit", "Write"):
            with self.subTest(tool=tool_name):
                self.assert_allowed(self.run_hook(tool_name, str(self.project / HANDWRITTEN)))
        # 先頭の 3 行より後に先頭の記述と同じ文字列があっても、生成したファイルではない
        path = self.write("docs/notes.md", "# メモ\n\n説明\n" + gh.markdown_line("docs/domains/") + "\n")
        self.assert_allowed(self.run_hook("Edit", str(path)))

    def test_allows_writing_new_file(self):
        self.assert_allowed(self.run_hook("Write", str(self.project / "docs/domains/02-loans/design.md")))

    def test_allows_input_without_path(self):
        self.assert_allowed(self.run_hook("Edit", ""))

    def test_works_without_project_config(self):
        shutil.rmtree(self.project / ".claude")
        self.assert_denied(self.run_hook("Edit", str(self.project / MODELS)), "docs/domains/02-loans/")
        self.assert_allowed(self.run_hook("Edit", str(self.project / HANDWRITTEN)))

    def test_invalid_input_is_reported_without_deciding(self):
        # JSON として読めない・オブジェクトでない・tool_input がオブジェクトでない・パスが文字列でない・cwd が文字列でない
        for text in (
            "{",
            "[]",
            '{"tool_input": "x"}',
            '{"tool_input": {"file_path": 1}}',
            '{"tool_input": {"file_path": "docs/glossary.md"}, "cwd": 1}',
            # 偽と評価される値も、型が違えば誤りとして報告する
            '{"tool_input": 0}',
            '{"tool_input": {"file_path": false}}',
            '{"tool_input": {"file_path": "docs/glossary.md"}, "cwd": 0}',
            '{"tool_input": {"file_path": "docs/glossary.md"}, "cwd": false}',
        ):
            with self.subTest(input=text):
                result = subprocess.run(
                    [PYTHON, str(HOOK_SCRIPT)], input=text, cwd=self.tmp, env=clean_env(), capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.startswith("doc-structured: "), result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_registered_as_pre_tool_use_hook(self):
        hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["PreToolUse"])
        [entry] = hooks["PreToolUse"]
        self.assertEqual(entry["matcher"], "Edit|Write|NotebookEdit")
        [command] = entry["hooks"]
        self.assertEqual(command["type"], "command")
        self.assertEqual(command["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/hook-scripts/guard-generated.py"')


if __name__ == "__main__":
    unittest.main()
