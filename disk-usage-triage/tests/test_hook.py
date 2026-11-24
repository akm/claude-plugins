#!/usr/bin/env python3
"""hook PreToolUse (サブコマンド `hook pre-tool-use`。ファイル `disk-usage-triage/scripts/disk_usage_triage/hook.py`) のテスト。

計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U8 のテストシナリオと、KTD8・KTD9。CLI の入口をサブプロセスで
実行し、標準入力に hook の入力の JSON を渡す。MCP ツール `mcp__terminal__run_in_terminal` の入力は、U8 の確認で、Claude Desktop
のセッションの hook が受け取った JSON (2026-11-25) の形を、値を置き換えて固定データ (ディレクトリ
`disk-usage-triage/tests/fixtures/hook-input/`) にしたもの。`tool_input` の形は、計画の U1 でセッションの記録から読んだ形と同じ。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import json
import os
import unittest

from triage_case import HERE, TriageCase

from disk_usage_triage import hook  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "hook-input")
HOOKS_JSON = os.path.join(HERE, "..", "hooks", "hooks.json")

TRIAGE_ID = "20261124-120000"
DEFAULT_RUN = f"~/.claude/disk-usage-triage/runs/{TRIAGE_ID}"
SCRIPT = "disk-usage-triage-delete.sh"
ENTRY_COMMAND = "python3 disk-usage-triage/scripts/disk_usage_triage.py"

# 削除のシェルスクリプトを実行する・読むコマンド (計画の U8 のテストシナリオの 1 つ目)
DELETE_SCRIPT_COMMANDS = (
    f"bash {DEFAULT_RUN}/{SCRIPT}",
    f"bash {DEFAULT_RUN}/{SCRIPT} --dry-run",
    f"cat {DEFAULT_RUN}/{SCRIPT}",
    f"cd {DEFAULT_RUN} && ./{SCRIPT}",
)

# このリポジトリの開発のコマンドと、拒否しないコマンド (計画の U8 のテストシナリオ・KTD8)
ALLOWED_COMMANDS = (
    "python3 -m unittest discover -s disk-usage-triage/tests",
    f"{ENTRY_COMMAND} scan --run {TRIAGE_ID}",
    f"{ENTRY_COMMAND} config set --input-file ~/.claude/disk-usage-triage/inputs/config-set.json",
    f"{ENTRY_COMMAND} records add --input-file ~/.claude/disk-usage-triage/inputs/records-add.json",
    f"{ENTRY_COMMAND} judge set --input-file ~/.claude/disk-usage-triage/inputs/judge-set.json",
    "git commit -F tmp/commit-message.txt",
    "gh pr create --body-file tmp/pr-body.md",
)


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def event(tool_name, tool_input):
    """Bash・Write などの hook の入力。共通のキーは固定データと同じにする。キー mcp_server は MCP ツールの入力にだけある。"""
    data = load_fixture("run-in-terminal-new-tab.json")
    data["tool_name"] = tool_name
    data["tool_input"] = tool_input
    if not tool_name.startswith("mcp__"):
        del data["mcp_server"]
    return data


def terminal_event(command):
    """MCP ツール mcp__terminal__run_in_terminal で、新しいタブを開いてコマンドを実行するときの hook の入力。"""
    data = load_fixture("run-in-terminal-new-tab.json")
    data["tool_input"]["command"] = command
    return data


class HookCase(TriageCase):

    def run_hook(self, data, env=None):
        """hook を実行する。保存先のディレクトリを作らないこと (書かないこと) も確認する。"""
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        code, out, err = self.cli("hook", "pre-tool-use", stdin=text, env=env)
        self.assertFalse(os.path.exists(self.home), "hook は保存先のディレクトリを作らない")
        return code, out, err

    def assert_denied(self, data, env=None):
        code, out, err = self.run_hook(data, env=env)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertIsNotNone(out, "拒否の JSON を出力すること")
        self.assertEqual(set(out), {"hookSpecificOutput"})
        specific = out["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertIn("disk-usage-triage", specific["permissionDecisionReason"])
        return specific["permissionDecisionReason"]

    def assert_allowed(self, data, env=None):
        """拒否も許可もしない (何も出力せず、終了コード 0)。"""
        code, out, err = self.run_hook(data, env=env)
        self.assertEqual(code, 0, err)
        self.assertIsNone(out, "何も出力しないこと")
        self.assertEqual(err, "")


class CommandToolTest(HookCase):
    """Bash ツールと mcp__terminal__run_in_terminal の入力 (計画の KTD8・KTD9)。

    入力 tool_input のすべての文字列を検査する (計画の U8 を実装するときに利用者が決めた。2026-11-24)。
    """

    def both(self, command):
        return (("Bash", event("Bash", {"command": command, "description": "確認"})),
                ("mcp__terminal__run_in_terminal", terminal_event(command)))

    def test_delete_script_commands_are_denied(self):
        for command in DELETE_SCRIPT_COMMANDS:
            for tool, data in self.both(command):
                with self.subTest(tool=tool, command=command):
                    self.assert_denied(data)

    def test_each_string_alone_is_denied(self):
        """runs のパスだけ・ファイル名だけを含むコマンドも拒否する (実行か読み取りかを問わない。計画の KD14)。"""
        for command in ("ls ~/.claude/disk-usage-triage/runs", f"cat {DEFAULT_RUN}/results.tsv", f"bash ./{SCRIPT}"):
            for tool, data in self.both(command):
                with self.subTest(tool=tool, command=command):
                    self.assert_denied(data)

    def test_changed_home_runs_is_denied(self):
        """環境変数 DISK_USAGE_TRIAGE_HOME で変えた保存先のディレクトリの runs のパスも拒否する。"""
        command = f"cat {self.home}/runs/{TRIAGE_ID}/results.tsv"
        for tool, data in self.both(command):
            with self.subTest(tool=tool):
                self.assert_denied(data)

    def test_changed_home_runs_needs_environment(self):
        """変えた場所の runs のパスを拒否するのは、hook の環境変数 DISK_USAGE_TRIAGE_HOME がその場所のときだけ。"""
        command = f"cat {self.home}/runs/{TRIAGE_ID}/results.tsv"
        env = dict(os.environ)
        del env["DISK_USAGE_TRIAGE_HOME"]
        for tool, data in self.both(command):
            with self.subTest(tool=tool):
                self.assert_allowed(data, env=env)

    def test_default_runs_is_denied_with_changed_home(self):
        """DISK_USAGE_TRIAGE_HOME を変えても、文字列 disk-usage-triage/runs を含むコマンドは拒否する。"""
        for tool, data in self.both(f"cat {DEFAULT_RUN}/results.tsv"):
            with self.subTest(tool=tool):
                self.assert_denied(data)

    def test_development_and_input_commands_are_allowed(self):
        for command in (*ALLOWED_COMMANDS, f"{ENTRY_COMMAND} config set --input-file {self.home}/inputs/config-set.json"):
            for tool, data in self.both(command):
                with self.subTest(tool=tool, command=command):
                    self.assert_allowed(data)

    def test_existing_tab_input(self):
        """入力待ちのタブに送る形 (キー tab_id) の入力も、コマンドを検査する。"""
        self.assert_allowed(load_fixture("run-in-terminal-existing-tab.json"))
        data = load_fixture("run-in-terminal-existing-tab.json")
        data["tool_input"]["command"] = f"bash {DEFAULT_RUN}/{SCRIPT}"
        self.assert_denied(data)

    def test_strings_other_than_command_are_checked(self):
        """コマンドのほかの文字列 (タブを開くディレクトリ cwd・説明 description) も検査する。"""
        data = terminal_event("bash *.sh")
        data["tool_input"]["cwd"] = f"/Users/user/.claude/disk-usage-triage/runs/{TRIAGE_ID}"
        self.assert_denied(data)
        self.assert_denied(event("Bash", {"command": "ls", "description": f"{SCRIPT} を確認する"}))

    def test_changed_input_shape_is_checked(self):
        """入力の形が変わってキー command が無くなっても、すべての文字列 (入れ子を含む) を検査する。"""
        for tool_input in ({"cmd": f"bash {DEFAULT_RUN}/{SCRIPT}"}, {"args": ["bash", f"{DEFAULT_RUN}/{SCRIPT}"]},
                           {"spec": {"argv": [f"{DEFAULT_RUN}/{SCRIPT}"]}}):
            for tool in ("Bash", "mcp__terminal__run_in_terminal"):
                with self.subTest(tool=tool, tool_input=tool_input):
                    self.assert_denied(event(tool, tool_input))
        self.assert_allowed(event("Bash", {"cmd": "ls", "timeout": 1000}))


class FileToolTest(HookCase):
    """Write・Edit・MultiEdit・NotebookEdit のファイルのパス (計画の KTD9)。"""

    def setUp(self):
        super().setUp()
        run = os.path.join(self.user_home, ".claude", "disk-usage-triage", "runs", TRIAGE_ID)
        self.script = os.path.join(run, SCRIPT)
        self.list_file = os.path.join(run, "lists", "A.json")
        self.input_file = os.path.join(self.user_home, ".claude", "disk-usage-triage", "inputs", "config-set.json")

    def inputs_for(self, path):
        return (("Write", {"file_path": path, "content": "echo\n"}),
                ("Edit", {"file_path": path, "old_string": "a", "new_string": "b", "replace_all": False}),
                ("MultiEdit", {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]}),
                ("NotebookEdit", {"notebook_path": path, "new_source": "print(1)"}))

    def test_writing_under_runs_is_denied(self):
        for path in (self.script, self.list_file, os.path.join(self.home, "runs", TRIAGE_ID, "selection.json")):
            for tool, tool_input in self.inputs_for(path):
                with self.subTest(tool=tool, path=path):
                    self.assert_denied(event(tool, tool_input))

    def test_writing_script_name_elsewhere_is_denied(self):
        path = os.path.join(self.root, "elsewhere", SCRIPT)
        for tool, tool_input in self.inputs_for(path):
            with self.subTest(tool=tool):
                self.assert_denied(event(tool, tool_input))

    def test_writing_inputs_is_allowed(self):
        for path in (self.input_file, os.path.join(self.home, "inputs", "config-set.json")):
            for tool, tool_input in self.inputs_for(path):
                with self.subTest(tool=tool, path=path):
                    self.assert_allowed(event(tool, tool_input))

    def test_content_is_not_checked(self):
        """書く内容 (content・new_string) は検査しない。削除のシェルスクリプトのファイル名を書く文書を、開発で書けるように。"""
        path = os.path.join(self.root, "docs", "files.md")
        self.assert_allowed(event("Write", {"file_path": path, "content": f"{DEFAULT_RUN}/{SCRIPT}\n"}))
        self.assert_allowed(event("Edit", {"file_path": path, "old_string": "a", "new_string": f"{DEFAULT_RUN}/{SCRIPT}",
                                           "replace_all": False}))


class OtherToolTest(HookCase):

    def test_other_tool_is_not_checked(self):
        """matcher に無いツールは検査しない (hooks.json の matcher が変わっても、ほかのツールを拒否しない)。"""
        self.assert_allowed(event("Read", {"file_path": f"/Users/user/.claude/disk-usage-triage/runs/{TRIAGE_ID}/{SCRIPT}"}))


class InvalidInputTest(HookCase):
    """入力が壊れているときは、拒否も許可もせず、誤りを標準エラー出力に書く (計画の U8 のテストシナリオ)。"""

    def assert_reported(self, data):
        code, out, err = self.run_hook(data)
        self.assertEqual(code, 3)
        self.assertIsNone(out, "標準出力に何も書かない (拒否も許可もしない)")
        self.assertIn("disk-usage-triage", err)
        return err

    def test_broken_json(self):
        self.assertIn("JSON", self.assert_reported('{"tool_name": "Bash", '))

    def test_not_object(self):
        self.assert_reported("[]")

    def test_tool_input_not_object(self):
        self.assert_reported(event("Bash", "bash x.sh"))

    def test_path_not_string(self):
        for tool, key in (("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                self.assert_reported(event(tool, {key: None}))


class HooksJsonTest(unittest.TestCase):

    def test_matcher_and_command(self):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        groups = data["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["matcher"], "Bash|mcp__terminal__run_in_terminal|Write|Edit|MultiEdit|NotebookEdit")
        self.assertEqual(groups[0]["matcher"].split("|"), list(hook.TOOLS), "matcher と hook.py のツールの一覧が一致すること")
        (command,) = groups[0]["hooks"]
        self.assertEqual(command["type"], "command")
        self.assertEqual(command["command"],
                         'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/disk_usage_triage.py" hook pre-tool-use')


if __name__ == "__main__":
    unittest.main()
