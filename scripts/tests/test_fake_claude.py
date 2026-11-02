#!/usr/bin/env python3
"""偽の claude (scripts/tests/fake-claude) と、テストの共通の準備 (scripts/tests/plugintest.py) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s scripts/tests

本物の claude は実行せず、GitHub に接続しない。共通の準備は、偽の claude を PATH の先頭のディレクトリに claude の名前で置き、
使う前に偽物であることを 2 つの方法で確認する。git のテストは、一時ディレクトリに作った bare リポジトリ (配布元の代わり) と
作業用のリポジトリで行う。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import plugintest  # noqa: E402

MP = plugintest.MARKETPLACE
WG = f"wording-guard@{MP}"
DD = f"doc-dag@{MP}"
# 偽の claude の状態の marketplaces。このリポジトリのマーケットプレイスだけを登録した状態 (plugintest.REGISTERED とは別のもの)
REGISTERED_OWN_ONLY = [{"name": MP, "source": "github", "repo": plugintest.MARKETPLACE_REPO}]


def _write_script(path, body):
    """python3 で実行するスクリプトを書き、実行できるようにする。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\n" + body)
    os.chmod(path, 0o755)
    return path


class FakeClaudeCheckTest(plugintest.PluginTestCase):
    """偽の claude を使う前の 2 つの確認。"""

    def put_as_claude(self, path):
        """PATH の先頭のディレクトリの claude を、path へのリンクに置き換える。"""
        link = os.path.join(self.bin, "claude")
        os.remove(link)
        os.symlink(path, link)

    def test_checks_pass_with_fake_first_on_path(self):
        plugintest.check_fake_claude(self.env)
        r = self.run_claude("--fake-claude-identity")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, plugintest.FAKE_CLAUDE_IDENTITY + "\n", "決めた文字列を返すこと")

    def test_path_check_fails_and_does_not_run_other_claude(self):
        marker = os.path.join(self.root, "other-ran")
        # 実行されたら記録を残し、決めた文字列も返すスクリプト。2 つ目の確認だけでは判別できない
        other = _write_script(os.path.join(self.root, "other-claude"),
                              f"open({marker!r}, 'w').close()\nprint({plugintest.FAKE_CLAUDE_IDENTITY!r})\n")
        self.put_as_claude(other)
        with self.assertRaises(plugintest.FakeClaudeCheckError) as cm:
            plugintest.check_fake_claude(self.env)
        self.assertEqual(cm.exception.check, "path", "1 つ目の確認 (実体のパス) で失敗すること")
        self.assertFalse(os.path.exists(marker), "偽の claude でないファイルを実行しないこと")

    def test_identity_check_fails_when_output_differs(self):
        marker = os.path.join(self.root, "other-ran")
        other = _write_script(os.path.join(self.root, "other-claude"),
                              f"open({marker!r}, 'w').close()\nprint('not the identity')\n")
        self.put_as_claude(other)
        with self.assertRaises(plugintest.FakeClaudeCheckError) as cm:
            plugintest.check_fake_claude(self.env, fake=other)
        self.assertEqual(cm.exception.check, "identity", "2 つ目の確認 (固有のオプションの出力) で失敗すること")
        self.assertTrue(os.path.exists(marker), "1 つ目の確認を通った後に、2 つ目の確認で実行したこと")


class PreparedEnvTest(plugintest.PluginTestCase):
    """準備の後の環境変数。前のテストが os.environ に残した値を真似てから準備する。"""

    LEFTOVERS = {"FAKE_CLAUDE_STATE": "/nonexistent/previous-state.json", "FAKE_CLAUDE_LEFTOVER": "1",
                 "CLAUDE_CONFIG_DIR": "/nonexistent/claude-config", "GIT_DIR": "/nonexistent/.git"}

    def setUp(self):
        patcher = mock.patch.dict(os.environ, self.LEFTOVERS)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_home_and_config_dir_are_temporary(self):
        self.assertTrue(self.root.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep),
                        "準備のディレクトリが一時ディレクトリの中にあること")
        for key in ("HOME", "CLAUDE_CONFIG_DIR"):
            with self.subTest(key=key):
                self.assertTrue(self.env[key].startswith(self.root + os.sep), f"{key} がこのテストの一時ディレクトリの中を指すこと")
                self.assertTrue(os.path.isdir(self.env[key]), f"{key} のディレクトリがあること")
        self.assertEqual(os.path.realpath(os.path.join(self.bin, "python3")), os.path.realpath(sys.executable),
                         "PATH の先頭の python3 が、テストを実行している python を指すこと")

    def test_fake_variables_are_not_left_from_previous_tests(self):
        fake = {k: v for k, v in self.env.items() if k.startswith("FAKE_")}
        self.assertEqual(sorted(fake), ["FAKE_CLAUDE_RECORD", "FAKE_CLAUDE_STATE"], "準備が決めた FAKE_ の変数だけがあること")
        for key, value in fake.items():
            with self.subTest(key=key):
                self.assertTrue(value.startswith(self.root + os.sep), f"{key} がこのテストの一時ディレクトリの中を指すこと")
        self.assertNotIn("GIT_DIR", self.env, "git の実行先を変える環境変数を消すこと")
        self.assertEqual(self.env["GIT_ALLOW_PROTOCOL"], "file", "git の取得先を手元のファイルに限ること")


class FakeClaudeTest(plugintest.PluginTestCase):
    """偽の claude の振る舞い。"""

    def fixture_keys(self):
        """固定データの要素のキーを、スコープごとに返す。"""
        with open(plugintest.FIXTURE_PLUGIN_LIST, encoding="utf-8") as f:
            data = json.load(f)
        by_scope = {}
        for element in data:
            keys = by_scope.setdefault(element["scope"], set(element))
            self.assertEqual(set(element), keys, "固定データの同じスコープの要素が、同じキーを持つこと")
        self.assertEqual(sorted(by_scope), ["project", "user"], "固定データが user と project の要素を持つこと")
        return by_scope

    def test_plugin_list_returns_installed_with_fixture_keys(self):
        self.write_state({"installed": [
            {"id": WG, "scope": "user", "version": "0.2.7", "enabled": False},
            {"id": WG, "scope": "project", "version": "0.2.5", "projectPath": "/Users/example/other-project"},
            {"id": "skill-creator@claude-plugins-official", "scope": "user", "version": "a7ba5b93db0c"},
        ]})
        r = self.run_claude("plugin", "list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        listed = json.loads(r.stdout)
        self.assertEqual([(e["id"], e["scope"], e["version"]) for e in listed],
                         [(WG, "user", "0.2.7"), (WG, "project", "0.2.5"),
                          ("skill-creator@claude-plugins-official", "user", "a7ba5b93db0c")],
                         "状態のファイルのインストール済みのプラグインを、その順に返すこと")
        self.assertEqual([e["enabled"] for e in listed], [False, True, True], "enabled を省略した要素は有効として返すこと")
        self.assertEqual(listed[1]["projectPath"], "/Users/example/other-project")
        expected = self.fixture_keys()
        for element in listed:
            with self.subTest(id=element["id"], scope=element["scope"]):
                self.assertEqual(set(element), expected[element["scope"]], "要素のキーが固定データの要素のキーと同じであること")

    def test_marketplace_list_returns_registered(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY + [{"name": "other", "source": "git", "url": "https://example.com/other.git"}]})
        r = self.run_claude("plugin", "marketplace", "list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        listed = json.loads(r.stdout)
        self.assertEqual([(m["name"], m["source"]) for m in listed], [(MP, "github"), ("other", "git")],
                         "登録したマーケットプレイスを、その順に返すこと")
        self.assertEqual(listed[0]["repo"], plugintest.MARKETPLACE_REPO)
        self.assertEqual(listed[1]["url"], "https://example.com/other.git")
        self.assertEqual(listed[0]["installLocation"],
                         os.path.join(self.env["CLAUDE_CONFIG_DIR"], "plugins", "marketplaces", MP),
                         "clone の場所を CLAUDE_CONFIG_DIR の下のパスで返すこと")

    def test_marketplace_update_then_install(self):
        project = {"id": WG, "scope": "project", "version": "0.2.5", "projectPath": "/Users/example/other-project"}
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY,
                          "clone": {MP: {"wording-guard": "0.2.7"}},
                          "published": {MP: {"wording-guard": "0.2.8"}},
                          "installed": [project]})
        r = self.run_claude("plugin", "marketplace", "update", MP)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_state()["clone"], {MP: {"wording-guard": "0.2.8"}}, "clone の版が配布元の版になること")
        r = self.run_claude("plugin", "install", WG, "--scope", "user", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        listed = json.loads(self.run_claude("plugin", "list", "--json").stdout)
        self.assertEqual([(e["id"], e["scope"], e["version"], e["enabled"]) for e in listed],
                         [(WG, "project", "0.2.5", True), (WG, "user", "0.2.8", True)],
                         "clone の版が user スコープにインストール済みになり、project スコープの要素は変わらないこと")
        self.assertEqual(listed[1]["installPath"],
                         os.path.join(self.env["CLAUDE_CONFIG_DIR"], "plugins", "cache", MP, "wording-guard", "0.2.8"),
                         "展開先が版を含むパスになること")
        self.assertFalse(os.path.exists(os.path.join(self.env["CLAUDE_CONFIG_DIR"], "plugins")),
                         "パスを返すだけで、ファイルを作らないこと")

    def test_update_and_install_fail_for_unknown_names(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY, "clone": {MP: {"wording-guard": "0.2.8"}}})
        before = self.read_state()
        for args in (["plugin", "marketplace", "update", "no-such"],
                     ["plugin", "install", f"no-such@{MP}", "--scope", "user", "--json"],
                     ["plugin", "install", "wording-guard@no-such", "--scope", "user", "--json"]):
            with self.subTest(args=args):
                r = self.run_claude(*args)
                self.assertEqual(r.returncode, 1, "登録していないマーケットプレイスと、clone に無いプラグインは失敗すること")
                self.assertTrue(r.stderr, "標準エラー出力に理由を書くこと")
        self.assertEqual(self.read_state(), before, "状態を変えないこと")

    def test_faults_fail_or_succeed_without_change(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY,
                          "clone": {MP: {"wording-guard": "0.2.8", "doc-dag": "0.1.0"}},
                          "published": {MP: {"wording-guard": "0.2.9", "doc-dag": "0.1.1"}},
                          "faults": [
                              {"prefix": ["plugin", "install", WG], "action": "fail", "stderr": "network error\n"},
                              {"prefix": ["plugin", "install", DD], "action": "no_change"},
                              {"prefix": ["plugin", "marketplace", "update"], "action": "fail"},
                          ]})
        before = self.read_state()
        r = self.run_claude("plugin", "install", WG, "--scope", "user", "--json")
        self.assertEqual((r.returncode, r.stderr), (1, "network error\n"), "失敗を指定したコマンドは、指定の文を書いて終了コード 1 を返すこと")
        r = self.run_claude("plugin", "install", DD, "--scope", "user", "--json")
        self.assertEqual(r.returncode, 0, "成功を返して版を変えないと指定したコマンドは、終了コード 0 を返すこと")
        r = self.run_claude("plugin", "marketplace", "update", MP)
        self.assertEqual(r.returncode, 1, "失敗を指定したコマンドは、終了コード 1 を返すこと")
        self.assertTrue(r.stderr, "文を指定しない失敗でも、標準エラー出力に理由を書くこと")
        self.assertEqual(self.read_state(), before, "どれも状態を変えないこと")

    def test_fault_output_replaces_plugin_list(self):
        self.write_state({"faults": [{"prefix": ["plugin", "list", "--json"], "action": "no_change", "stdout": "[{\"scope\": \"user\"}]"}]})
        r = self.run_claude("plugin", "list", "--json")
        self.assertEqual((r.returncode, r.stdout), (0, "[{\"scope\": \"user\"}]"), "指定した標準出力をそのまま返すこと")

    def test_fault_bad_utf8_writes_undecodable_stdout(self):
        self.write_state({"faults": [{"prefix": ["plugin", "install", WG], "action": "bad_utf8"}]})
        before = self.read_state()
        r = subprocess.run(["claude", "plugin", "install", WG, "--scope", "user", "--json"], env=self.env, cwd=self.root,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=plugintest.TIMEOUT)
        self.assertEqual(r.returncode, 0, "UTF-8 として読めない出力を指定したコマンドは、終了コード 0 を返すこと")
        with self.assertRaises(UnicodeDecodeError, msg="標準出力が UTF-8 として読めないこと"):
            r.stdout.decode("utf-8")
        self.assertEqual(self.read_state(), before, "状態を変えないこと")

    def test_fault_skip_lets_earlier_calls_through(self):
        self.write_state({"faults": [{"prefix": ["plugin", "list", "--json"], "action": "fail", "skip": 1}]})
        codes = [self.run_claude("plugin", "list", "--json").returncode for _ in range(3)]
        self.assertEqual(codes, [0, 1, 1], "skip の数だけ呼び出しを通し、その後の呼び出しを失敗させること")

    def test_sigint_is_sent_to_parent(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY, "clone": {MP: {"wording-guard": "0.2.8"}},
                          "faults": [{"prefix": ["plugin", "install", WG], "action": "sigint"}]})
        before = self.read_state()
        parent = _write_script(os.path.join(self.root, "parent"), (
            "import subprocess, sys\n"
            "try:\n"
            "    r = subprocess.run(sys.argv[1:], capture_output=True)\n"
            "except KeyboardInterrupt:\n"
            "    print('interrupted')\n"
            "    sys.exit(130)\n"
            "print('returned', r.returncode)\n"))
        r = subprocess.run([sys.executable, parent, "claude", "plugin", "install", WG, "--scope", "user", "--json"],
                           env=self.env, cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=plugintest.TIMEOUT, preexec_fn=plugintest.default_sigint)
        self.assertEqual((r.returncode, r.stdout), (130, "interrupted\n"),
                         "親のプロセスが、偽の claude の実行中に SIGINT を受けること")
        self.assertEqual(self.read_state(), before, "状態を変えないこと")

    def test_unknown_args_exit_99(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY, "clone": {MP: {"wording-guard": "0.2.8"}}})
        before = self.read_state()
        for args in (["plugin", "update", WG],
                     ["plugin", "install", WG, "--scope", "user", "--json", "-y"],
                     ["plugin", "install", WG, "--scope", "project", "--json"],
                     ["plugin", "list"],
                     ["hello"],
                     []):
            with self.subTest(args=args):
                r = self.run_claude(*args)
                self.assertEqual(r.returncode, 99, "知らない引数は終了コード 99 で終えること")
                self.assertIn(repr(args), r.stderr, "受けた引数を標準エラー出力に書くこと")
        self.assertEqual(self.read_state(), before, "状態を変えないこと")

    def test_records_args_and_cwd_in_order(self):
        self.write_state({"marketplaces": REGISTERED_OWN_ONLY})
        a = os.path.join(self.root, "a")
        b = os.path.join(self.root, "b")
        os.makedirs(a)
        os.makedirs(b)
        self.run_claude("plugin", "list", "--json", cwd=a)
        self.run_claude("plugin", "marketplace", "list", "--json", cwd=b)
        self.run_claude("--fake-claude-identity", cwd=b)
        self.run_claude("no-such", cwd=a)
        self.assertEqual(self.read_record(), [
            {"args": ["plugin", "list", "--json"], "cwd": a},
            {"args": ["plugin", "marketplace", "list", "--json"], "cwd": b},
            {"args": ["--fake-claude-identity"], "cwd": b},
            {"args": ["no-such"], "cwd": a},
        ], "受けた引数と cwd を、呼び出しの順に記録すること (準備の確認の呼び出しは残さないこと)")


class RepoTest(plugintest.PluginTestCase):
    """配布元の代わりの bare リポジトリと、作業用のリポジトリ。"""

    def test_origin_is_github_and_fetch_reads_bare(self):
        self.make_repos([("wording-guard", "0.2.8"), ("doc-dag", "0.1.0")])
        url = plugintest.git(self.work, "config", "--get", "remote.origin.url", env=self.env).stdout.strip()
        self.assertEqual(url, plugintest.ORIGIN_URL, "remote.origin.url の設定値が GitHub の URL であること")
        with open(os.path.join(self.work, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            marketplace = json.load(f)
        self.assertEqual(marketplace["name"], MP)
        self.assertEqual([p["name"] for p in marketplace["plugins"]], ["wording-guard", "doc-dag"],
                         "作業ツリーの marketplace.json に、渡した順にプラグインが並ぶこと")
        self.assertEqual(marketplace["plugins"][0]["source"],
                         {"source": "git-subdir", "url": plugintest.SOURCE_URL, "path": "wording-guard", "ref": "main"})

        self.publish_version("wording-guard", "0.2.9")
        r = plugintest.git(self.work, "fetch", "origin", "main", env=self.env, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = plugintest.git(self.work, "show", "origin/main:wording-guard/.claude-plugin/plugin.json", env=self.env).stdout
        self.assertEqual(json.loads(shown)["version"], "0.2.9", "配布元にコミットした新しい版を、git fetch で取得できること")
        self.assertEqual(self.read_state()["published"], {MP: {"wording-guard": "0.2.9"}},
                         "偽の claude の配布元の版も、コミットした版にすること")

    def test_fetch_without_insteadof_is_refused(self):
        self.make_repos([("wording-guard", "0.2.8")])
        plugintest.git(self.work, "config", "--unset", f"url.{self.source}.insteadOf", env=self.env)
        r = plugintest.git(self.work, "fetch", "origin", "main", env=self.env, check=False)
        self.assertNotEqual(r.returncode, 0, "insteadOf が無ければ git fetch が失敗すること")
        self.assertIn("not allowed", r.stderr, "git が GIT_ALLOW_PROTOCOL=file によって https での取得を拒否すること")

    def test_copy_into_work(self):
        self.make_repos([("wording-guard", "0.2.8")])
        self.copy_into_work([".github/test-targets.txt"])
        with open(os.path.join(plugintest.REPO_ROOT, ".github", "test-targets.txt"), "rb") as f:
            original = f.read()
        with open(os.path.join(self.work, ".github", "test-targets.txt"), "rb") as f:
            self.assertEqual(f.read(), original, "リポジトリのファイルを、同じ相対パスで作業用のリポジトリにコピーすること")


if __name__ == "__main__":
    unittest.main()
