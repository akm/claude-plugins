#!/usr/bin/env python3
"""設定の読み込み (issue-dispatch/scripts/issue_dispatch/config.py) と、CLI の `config` のサブコマンドのテスト。

標準ライブラリの unittest だけで動く。`gh` は使わない。

  python3 -m unittest discover -s issue-dispatch/tests

一時ディレクトリを管理ディレクトリとリポジトリのルートとして使い、そこに設定ファイルを作って読み込みの結果
(デフォルト値の適用・警告・エラー・`files` のパターンの表記) を確認する。
キーと未設定のときの扱いの SSOT は issue-dispatch/skills/issue-dispatch/references/project-config.md。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import config  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")


def _write_config(root, data):
    path = os.path.join(root, config.CONFIG_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _warnings_about(result, key):
    return [w for w in result["warnings"] if w["key"] == key]


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class ManagerConfigTest(ConfigTestBase):
    """管理ディレクトリの設定。"""

    def test_defaults_when_keys_missing(self):
        """未設定のキーに KTD15 のデフォルト値を使う。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}})
        result = config.load(self.root, "manager")
        self.assertEqual(result["status"], "ok", "設定ファイルを読めること")
        self.assertEqual(result["errors"], [], "必須のキーがそろっていればエラーは無いこと")
        c = result["config"]
        self.assertEqual(c["project"], {"owner": "akm", "number": 3})
        self.assertEqual(c["record_dir"], "tmp/issue-dispatch", "record_dir のデフォルト値")
        self.assertEqual(c["poll_minutes"], 3, "poll_minutes のデフォルト値")
        self.assertEqual(c["wait_minutes"], 60, "wait_minutes のデフォルト値")
        self.assertEqual(c["declare_deadline_minutes"], 60, "declare_deadline_minutes のデフォルト値")
        self.assertEqual(c["third_party_edit_check"], [], "third_party_edit_check は空 (どのリポジトリも確認しない)")
        self.assertEqual(c["resources"], {}, "resources は空")
        self.assertEqual(c["repositories"], {}, "repositories は空")
        self.assertEqual(result["warnings"], [], "未設定は値の誤りではないので警告しないこと")

    def test_project_required_in_manager_config(self):
        """管理ディレクトリの設定の `project` は必須で、無ければデフォルト値ではなくエラー。"""
        _write_config(self.root, {"poll_minutes": 5})
        result = config.load(self.root, "manager")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([e["key"] for e in result["errors"]], ["project"], "project が無いことをエラーで返すこと")
        self.assertNotIn("project", result["config"], "project にデフォルト値を作らないこと")

    def test_project_shape_is_checked(self):
        """`project` は owner (文字列) と number (1 以上の整数) を持つ。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": "3"}})
        result = config.load(self.root, "manager")
        self.assertEqual([e["key"] for e in result["errors"]], ["project"], "number が文字列ならエラー")

    def test_missing_file(self):
        """設定ファイルが無ければ、status は missing で、デフォルト値を返し、project のエラーを返す。"""
        result = config.load(self.root, "manager")
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["config"]["poll_minutes"], 3)
        self.assertEqual([e["key"] for e in result["errors"]], ["project"])

    def test_unreadable_file(self):
        """JSON として読めない設定は status が unreadable で、デフォルト値で続ける。"""
        _write_config(self.root, "{ not json")
        result = config.load(self.root, "manager")
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["config"]["wait_minutes"], 60, "読めなくてもデフォルト値を返すこと")
        self.assertTrue(any(e["key"] == "(file)" for e in result["errors"]), "読めないことをエラーで返すこと")

    def test_not_an_object(self):
        """JSON だがオブジェクトでない設定も unreadable。"""
        _write_config(self.root, "[1, 2]")
        result = config.load(self.root, "manager")
        self.assertEqual(result["status"], "unreadable")

    def test_integer_keys_reject_empty_string_and_bad_values(self):
        """整数のキーは空文字列を未設定と読まず、値の誤りはデフォルト値で続行して警告する。"""
        _write_config(self.root, {
            "project": {"owner": "akm", "number": 3},
            "poll_minutes": "",
            "wait_minutes": "abc",
            "declare_deadline_minutes": 0,
        })
        result = config.load(self.root, "manager")
        c = result["config"]
        self.assertEqual(c["poll_minutes"], 3, "空文字列はデフォルト値で続ける")
        self.assertEqual(c["wait_minutes"], 60, "整数でない値はデフォルト値で続ける")
        self.assertEqual(c["declare_deadline_minutes"], 60, "1 未満はデフォルト値で続ける")
        self.assertEqual(sorted(w["key"] for w in result["warnings"]),
                         ["declare_deadline_minutes", "poll_minutes", "wait_minutes"],
                         "値の誤りはキーごとに 1 つ警告すること")
        self.assertEqual(result["errors"], [], "値の誤りはエラーにしないこと")

    def test_bool_is_not_an_integer(self):
        """真偽値は整数と読まない (Python では bool が int の部分型のため、明示的に確認する)。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": True})
        result = config.load(self.root, "manager")
        self.assertEqual(result["config"]["poll_minutes"], 3)
        self.assertEqual([w["key"] for w in result["warnings"]], ["poll_minutes"])

    def test_poll_not_less_than_wait(self):
        """`poll_minutes` が `wait_minutes` 以上なら、2 つとも値の誤りとして警告し、両方をデフォルト値に戻す。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": 60, "wait_minutes": 60})
        result = config.load(self.root, "manager")
        c = result["config"]
        self.assertEqual((c["poll_minutes"], c["wait_minutes"]), (3, 60))
        self.assertEqual(sorted(w["key"] for w in result["warnings"]), ["poll_minutes", "wait_minutes"])

    def test_pair_check_after_individual_defaults(self):
        """組の検査は、個別の検査でデフォルト値を当てた後の組で行い、以上なら両方をデフォルト値に戻す。
        個別の検査で警告したキーには重ねて警告しない。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": 0, "wait_minutes": 2})
        result = config.load(self.root, "manager")
        c = result["config"]
        self.assertEqual((c["poll_minutes"], c["wait_minutes"]), (3, 60), "3 >= 2 なので両方をデフォルト値に戻す")
        self.assertEqual([w["key"] for w in result["warnings"]], ["poll_minutes", "wait_minutes"],
                         "poll_minutes は値の誤りの 1 件、wait_minutes は組の 1 件")

    def test_pair_check_when_wait_is_invalid(self):
        """wait_minutes が値の誤りでデフォルト値 60 になり、poll_minutes 90 が 60 以上なら、両方をデフォルト値に戻す
        (誤った組 (90, 60) を返すと、作業のセッションの待機が引数の検査で拒否される)。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": 90, "wait_minutes": 0})
        result = config.load(self.root, "manager")
        c = result["config"]
        self.assertEqual((c["poll_minutes"], c["wait_minutes"]), (3, 60))
        self.assertEqual([w["key"] for w in result["warnings"]], ["wait_minutes", "poll_minutes"],
                         "wait_minutes は値の誤り、poll_minutes は組の警告")

    def test_third_party_edit_check_elements(self):
        """`third_party_edit_check` は `owner/repo` の配列。形の違う要素は警告して外す。"""
        _write_config(self.root, {
            "project": {"owner": "akm", "number": 3},
            "third_party_edit_check": ["akm/a", "not-a-repo", 3],
        })
        result = config.load(self.root, "manager")
        self.assertEqual(result["config"]["third_party_edit_check"], ["akm/a"])
        self.assertEqual(len(_warnings_about(result, "third_party_edit_check")), 2, "外した要素ごとに警告すること")

    def test_repositories_and_resources_shape(self):
        """`repositories` は `owner/repo` → 絶対パス、`resources` は名前 → 属性のオブジェクト。形の違う要素は警告して外す。"""
        _write_config(self.root, {
            "project": {"owner": "akm", "number": 3},
            "repositories": {"akm/a": "/Users/x/a", "akm/b": "relative/path", "bad": "/x"},
            "resources": {"dev-port": {"capacity": 2}, "bad": "x"},
        })
        result = config.load(self.root, "manager")
        c = result["config"]
        self.assertEqual(c["repositories"], {"akm/a": "/Users/x/a"})
        self.assertEqual(c["resources"], {"dev-port": {"capacity": 2}}, "属性の中身は確認しない (resources.md の SSOT は U11)")
        self.assertEqual(len(_warnings_about(result, "repositories")), 2)
        self.assertEqual(len(_warnings_about(result, "resources")), 1)

    def test_unknown_keys_are_warned(self):
        """知らないキーと、もう一方の役割のキーは、使わずに警告する。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "typo_key": 1, "protected_paths": ["x"]})
        result = config.load(self.root, "manager")
        self.assertNotIn("typo_key", result["config"])
        self.assertNotIn("protected_paths", result["config"], "リポジトリの設定のキーは管理ディレクトリでは使わない")
        self.assertEqual(sorted(w["key"] for w in result["warnings"]), ["protected_paths", "typo_key"])


class RepoConfigTest(ConfigTestBase):
    """リポジトリの設定。"""

    def test_defaults_and_wait_values(self):
        """`poll_minutes`・`wait_minutes` を読み、無ければデフォルト値 (作業のセッションの待機の --interval・--minutes に渡す)。"""
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": 2})
        result = config.load(self.root, "repo")
        c = result["config"]
        self.assertEqual(result["errors"], [])
        self.assertEqual(c["poll_minutes"], 2)
        self.assertEqual(c["wait_minutes"], 60)
        self.assertEqual(c["files"], [], "files は空 (デフォルトの表だけと照合する)")
        self.assertEqual(c["protected_paths"], [])
        self.assertTrue(c["hooks"]["guard_other_worktrees"], "設定があれば guard_other_worktrees は真")
        self.assertEqual(c["project"], {"owner": "akm", "number": 3})

    def test_project_is_optional_in_repo_config(self):
        """リポジトリの設定では `project` は省略できる。"""
        _write_config(self.root, {})
        result = config.load(self.root, "repo")
        self.assertEqual(result["errors"], [])
        self.assertNotIn("project", result["config"])

    def test_missing_file_disables_hooks(self):
        """設定が無いリポジトリでは、フックは何もしない (guard_other_worktrees は偽)。"""
        result = config.load(self.root, "repo")
        self.assertEqual(result["status"], "missing")
        self.assertFalse(result["config"]["hooks"]["guard_other_worktrees"])
        self.assertEqual(result["config"]["poll_minutes"], 3)

    def test_unreadable_file_keeps_hooks_enabled(self):
        """読めない設定でも、設定ファイルがあればフックは有効 (guard_other_worktrees は真)。"""
        _write_config(self.root, "{ not json")
        result = config.load(self.root, "repo")
        self.assertEqual(result["status"], "unreadable")
        self.assertTrue(result["config"]["hooks"]["guard_other_worktrees"], "書き損じた設定でフックを無効にしないこと")

    def test_hooks_value_must_be_bool(self):
        _write_config(self.root, {"hooks": {"guard_other_worktrees": "yes"}})
        result = config.load(self.root, "repo")
        self.assertTrue(result["config"]["hooks"]["guard_other_worktrees"], "値の誤りはデフォルト値 (真) で続ける")
        self.assertEqual([w["key"] for w in result["warnings"]], ["hooks.guard_other_worktrees"])

    def test_file_patterns_are_normalized(self):
        """`./dist/**` と `dist//**` は `dist/**` と同じに照合する。末尾の `/` は取り除かない。"""
        _write_config(self.root, {"files": [
            {"pattern": "./dist/**", "kind": "generated"},
            {"pattern": "dist//**", "kind": "generated"},
            {"pattern": "docs/", "kind": "divisible", "unit_notation": "markdown-heading"},
            {"pattern": "docs/./a.md", "kind": "unstable"},
            {"pattern": "././x/", "kind": "generated"},
            {"pattern": "dist/.", "kind": "generated"},
        ]})
        result = config.load(self.root, "repo")
        rules = result["config"]["files"]
        self.assertEqual([r["pattern"] for r in rules], ["dist/**", "dist/**", "docs/", "docs/a.md", "x/", "dist/"],
                         "途中の /./ と重ねた ./ も取り除き、末尾の / (/. で終わる場合も) は残すこと")
        self.assertEqual(rules[2]["unit_notation"], "markdown-heading", "省略できる属性はそのまま渡すこと")
        self.assertEqual(result["warnings"], [])

    def test_file_patterns_outside_root_are_warned(self):
        """`/dist/**`・`../x/**`・`dist/../x` は、その規則を使わずに警告する。"""
        _write_config(self.root, {"files": [
            {"pattern": "/dist/**", "kind": "generated"},
            {"pattern": "../x/**", "kind": "generated"},
            {"pattern": "dist/../x", "kind": "generated"},
            {"pattern": "ok/**", "kind": "generated"},
        ]})
        result = config.load(self.root, "repo")
        self.assertEqual([r["pattern"] for r in result["config"]["files"]], ["ok/**"])
        self.assertEqual(len(_warnings_about(result, "files")), 3, "規則ごとに警告すること")

    def test_file_rule_needs_pattern_and_kind(self):
        """`files` の要素は `pattern` と `kind` が必須。無い要素は警告して外す。"""
        _write_config(self.root, {"files": [{"pattern": "a/**"}, {"kind": "generated"}, "x"]})
        result = config.load(self.root, "repo")
        self.assertEqual(result["config"]["files"], [])
        self.assertEqual(len(_warnings_about(result, "files")), 3)

    def test_repository_names_use_allowed_characters(self):
        """リポジトリの名前は、名前に使える文字 (英数字と ._-) の 1 文字以上を `/` で区切った形。空白や区切りの崩れは通らない。"""
        _write_config(self.root, {"files": []})
        for name, ok in (("akm/.github", True), ("akm/_private", True), ("my-org/a.b-c_d", True), ("alice_acme/notes", True),
                         ("akm/", False), ("/x", False), ("akm/x y", False), ("akm/x/y", False), ("akm", False)):
            with self.subTest(name=name):
                self.assertEqual(bool(config.REPO_NAME_RE.match(name)), ok)

    def test_file_rule_kind_must_be_a_rule_kind(self):
        """`kind` は規則に書ける種類 (file-kinds.md の表の 2〜6 番目)。`unknown-content` と知らない値は警告して外す。"""
        _write_config(self.root, {"files": [
            {"pattern": "a/**", "kind": "unknown-content"},
            {"pattern": "b/**", "kind": "sectioned"},
            {"pattern": "c/**", "kind": "unknown-structure"},
        ]})
        result = config.load(self.root, "repo")
        self.assertEqual([r["pattern"] for r in result["config"]["files"]], ["c/**"])
        self.assertEqual(len(_warnings_about(result, "files")), 2, "規則ごとに警告すること")

    def test_manager_only_keys_are_ignored_in_repo(self):
        _write_config(self.root, {"record_dir": "x", "repositories": {}})
        result = config.load(self.root, "repo")
        self.assertNotIn("record_dir", result["config"])
        self.assertEqual(sorted(w["key"] for w in result["warnings"]), ["record_dir", "repositories"])


class AddEditCheckTest(ConfigTestBase):
    """`config add-edit-check`。"""

    def test_adds_repo_and_keeps_other_keys(self):
        path = _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": 5,
                                         "third_party_edit_check": ["akm/a"], "custom": {"keep": True}})
        result = config.add_edit_check(self.root, "akm/b")
        self.assertTrue(result["changed"])
        data = _read_json(path)
        self.assertEqual(data["third_party_edit_check"], ["akm/a", "akm/b"])
        self.assertEqual(data["poll_minutes"], 5, "ほかのキーを変えないこと")
        self.assertEqual(data["custom"], {"keep": True}, "知らないキーも残すこと")

    def test_already_present_changes_nothing(self):
        path = _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "third_party_edit_check": ["akm/a"]})
        before = os.stat(path).st_mtime_ns
        result = config.add_edit_check(self.root, "akm/a")
        self.assertFalse(result["changed"])
        self.assertEqual(os.stat(path).st_mtime_ns, before, "既にあればファイルを上書きしないこと")

    def test_key_missing_is_created(self):
        path = _write_config(self.root, {"project": {"owner": "akm", "number": 3}})
        result = config.add_edit_check(self.root, "akm/a")
        self.assertTrue(result["changed"])
        self.assertEqual(_read_json(path)["third_party_edit_check"], ["akm/a"])

    def test_unreadable_is_not_overwritten(self):
        path = _write_config(self.root, "{ not json")
        result = config.add_edit_check(self.root, "akm/a")
        self.assertFalse(result["changed"])
        self.assertTrue(result["errors"])
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{ not json", "読めない設定を上書きしないこと")

    def test_non_list_value_is_not_overwritten(self):
        """既存の値が配列でなければ、捨てずにエラーを返す。"""
        path = _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "third_party_edit_check": "akm/x"})
        result = config.add_edit_check(self.root, "akm/y")
        self.assertFalse(result["changed"])
        self.assertEqual([e["key"] for e in result["errors"]], ["third_party_edit_check"])
        self.assertEqual(_read_json(path)["third_party_edit_check"], "akm/x", "利用者が書いた値を消さないこと")

    def test_missing_root_dir_is_not_created(self):
        """ルートのディレクトリが無ければ作らずにエラーを返す (--dir の打ち間違いで別の場所に設定を作らない)。"""
        root = os.path.join(self.root, "typo", "dir")
        result = config.add_edit_check(root, "akm/a")
        self.assertFalse(result["changed"])
        self.assertEqual([e["key"] for e in result["errors"]], ["(dir)"])
        self.assertFalse(os.path.exists(root), "ディレクトリを作らないこと")

    def test_invalid_repo_is_rejected(self):
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}})
        result = config.add_edit_check(self.root, "not a repo")
        self.assertFalse(result["changed"])
        self.assertTrue(result["errors"])


class CliTest(ConfigTestBase):
    """CLI の入口 `issue_dispatch.py` の `config` のサブコマンド (入出力は JSON)。"""

    def _run(self, *args):
        return subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True)

    def test_config_read(self):
        _write_config(self.root, {"project": {"owner": "akm", "number": 3}, "poll_minutes": ""})
        p = self._run("config", "read", "--dir", self.root, "--role", "manager")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["config"]["poll_minutes"], 3)
        self.assertEqual([w["key"] for w in out["warnings"]], ["poll_minutes"])

    def test_config_read_errors_are_in_json_not_exit_code(self):
        """必須のキーが無いか読めないときも、JSON を出せれば終了コード 0 で、エラーは JSON の errors で伝える
        (1 と 2 は Python 自身の失敗の終了コードなので使わない。R25)。"""
        p = self._run("config", "read", "--dir", self.root, "--role", "manager")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["status"], "missing")
        self.assertEqual([e["key"] for e in out["errors"]], ["project"])

    def test_config_read_repo_role(self):
        _write_config(self.root, {"wait_minutes": 30})
        p = self._run("config", "read", "--dir", self.root, "--role", "repo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["config"]["wait_minutes"], 30)

    def test_config_add_edit_check(self):
        path = _write_config(self.root, {"project": {"owner": "akm", "number": 3}})
        p = self._run("config", "add-edit-check", "--dir", self.root, "--repo", "akm/a")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["changed"])
        self.assertEqual(_read_json(path)["third_party_edit_check"], ["akm/a"])

    def test_argument_error_exits_2(self):
        """引数の誤りは argparse の終了コード 2 (停止の条件の SSOT は R25)。"""
        p = self._run("config", "read", "--dir", self.root, "--role", "other")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
