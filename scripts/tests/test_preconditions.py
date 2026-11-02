#!/usr/bin/env python3
"""スクリプト scripts/plugins.py の、前提の検査と最新の版の読み取りのテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s scripts/tests

本物の claude は実行せず、GitHub に接続しない (共通の準備はファイル scripts/tests/plugintest.py)。スクリプトの中の関数は
差し替えない。スクリプトを作業用のリポジトリにコピーし、次のどちらかで動かす。

- プロセスとして実行する (終了コードと標準エラー出力を見るテスト)
- 別のプロセスで、コピーしたスクリプトをモジュールとして読み込み、関数 prepare に引数で値を渡して呼ぶ (読み取った結果を見るテスト)

外部のコマンドを実行しない関数 (名前の解析・URL の正規化・版の解析・出力の検査) は、このプロセスで引数を渡して呼ぶ。
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import plugintest  # noqa: E402

MP = plugintest.MARKETPLACE
SCP_URL = "git@github.com:akm/claude-plugins.git"
PUBLISHED = [("doc-dag", "0.2.0"), ("pr-teeth", "0.5.1"), ("wording-guard", "0.28.0")]

# 作業用のリポジトリにコピーしたスクリプトを、別のプロセスでモジュールとして読み込み、関数 prepare を呼び出して、結果を JSON で出力する
DRIVER = """\
import json
import sys
sys.path.insert(0, sys.argv[1])
import plugins
names = json.loads(sys.argv[2])
json.dump({"root": plugins.ROOT, "snapshot": plugins.prepare(plugins.ROOT, names)}, sys.stdout)
"""

_module = None


def load_plugins():
    """このリポジトリのスクリプト scripts/plugins.py を、モジュールとして読み込む (外部のコマンドを実行しない関数のテストに使う)。"""
    global _module
    if _module is None:
        spec = importlib.util.spec_from_file_location("plugins", os.path.join(plugintest.REPO_ROOT, plugintest.SCRIPT_REL))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _module = module
    return _module


def marketplace_with(names, overrides):
    """関数 plugintest.marketplace_json の中身に、overrides (プラグインの名前 → source のキーと値の上書き) を当てて返す。"""
    data = plugintest.marketplace_json(names)
    for plugin in data["plugins"]:
        plugin["source"].update(overrides.get(plugin["name"], {}))
    return data


class ScriptTestCase(plugintest.PluginTestCase):
    """配布元と作業用のリポジトリを作り、スクリプトを作業用のリポジトリにコピーする。

    作業用のリポジトリの remote origin は scp 形式の配布元の URL。マーケットプレイスは akm/claude-plugins の形で登録済み。
    """

    def setUp(self):
        super().setUp()
        self.make_repos(PUBLISHED, origin_url=SCP_URL)
        self.copy_into_work([plugintest.SCRIPT_REL])
        self.write_state({"marketplaces": plugintest.REGISTERED})

    def prepare(self, names=None, cwd=None, env=None):
        """作業用のリポジトリにコピーしたスクリプトの関数 prepare を別のプロセスで呼び、読み取った結果を返す。

        env を渡すときは、PATH を self.env と同じにする (準備で確認した偽の claude を使うため)。
        """
        env = self.env if env is None else env
        self.assertEqual(env["PATH"], self.env["PATH"], "準備で確認した PATH のまま実行すること")
        r = subprocess.run([sys.executable, "-c", DRIVER, os.path.join(self.work, "scripts"), json.dumps(names)],
                           env=env, cwd=cwd or self.root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=plugintest.TIMEOUT)
        self.assertEqual(r.returncode, 0, f"前提の検査と読み取りが成功すること: {r.stderr}")
        out = json.loads(r.stdout)
        self.assertEqual(out["root"], self.work, "スクリプトのルートが、コピーした先の作業用のリポジトリであること")
        return out["snapshot"]

    def latest(self, snapshot):
        return [(p["name"], p["latest"]) for p in snapshot["plugins"]]

    def assert_stopped_without_change(self, r, *fragments):
        """メソッド plugintest.PluginTestCase.assert_stopped_without_change の検査に加えて、標準エラー出力がプログラム名で始まること。"""
        super().assert_stopped_without_change(r, *fragments)
        self.assertTrue(r.stderr.startswith("plugins.py: "), "エラーの文の前にプログラム名を付けること")

    def write_work(self, rel, content):
        plugintest.write_files(self.work, {rel: content})


class LatestVersionTest(ScriptTestCase):
    """対象のプラグインと最新の版の読み取り (R1・R3・KD2・KD3)。"""

    def test_reads_latest_from_origin_main_not_working_tree(self):
        self.write_work("doc-dag/.claude-plugin/plugin.json", plugintest.dump_json(plugintest.plugin_json("doc-dag", "9.9.9")))
        snapshot = self.prepare()
        self.assertEqual(self.latest(snapshot), PUBLISHED,
                         "origin/main の plugin.json の版を、marketplace.json の順に最新の版として読むこと (作業ツリーの版は使わない)")
        self.assertEqual(snapshot["marketplace"], MP)
        self.assertEqual(snapshot["source"], "github.com/akm/claude-plugins")
        self.assertEqual(snapshot["sha"], self.origin_main_sha(), "取得した origin/main の SHA から読むこと")
        self.assertEqual([p["path"] for p in snapshot["plugins"]], ["doc-dag", "pr-teeth", "wording-guard"])

    def test_fetches_new_version_on_each_run(self):
        self.assertEqual(self.latest(self.prepare())[0], ("doc-dag", "0.2.0"))
        self.publish_version("doc-dag", "0.3.0")
        self.assertEqual(self.latest(self.prepare())[0], ("doc-dag", "0.3.0"),
                         "実行のたびに git fetch で取得し、配布元に足した版を最新の版として読むこと")

    def test_targets_come_from_origin_main_marketplace(self):
        names = [name for name, _ in PUBLISHED]
        plugintest.commit_source(self.source_tree, {
            ".claude-plugin/marketplace.json": plugintest.dump_json(plugintest.marketplace_json(names + ["commit-squash"])),
            "commit-squash/.claude-plugin/plugin.json": plugintest.dump_json(plugintest.plugin_json("commit-squash", "0.1.0")),
        }, "commit-squash を足す")
        self.write_work(".claude-plugin/marketplace.json",
                        plugintest.dump_json(plugintest.marketplace_json(names + ["local-only"])))
        self.write_work("local-only/.claude-plugin/plugin.json",
                        plugintest.dump_json(plugintest.plugin_json("local-only", "0.1.0")))
        self.assertEqual(self.latest(self.prepare()), PUBLISHED + [("commit-squash", "0.1.0")],
                         "origin/main の marketplace.json にあるものを対象にし、作業ツリーにだけあるものは対象にしないこと")

    def test_plugins_option_limits_targets(self):
        snapshot = self.prepare(["wording-guard", "doc-dag"])
        self.assertEqual(self.latest(snapshot), [("doc-dag", "0.2.0"), ("wording-guard", "0.28.0")],
                         "指定した名前だけを、marketplace.json の順に対象にすること")

    def test_only_targets_are_checked_for_version_format(self):
        self.publish_version("pr-teeth", "0.6.0-alpha1")
        self.assertEqual(self.latest(self.prepare(["doc-dag"])), [("doc-dag", "0.2.0")],
                         "対象でないプラグインの plugin.json は読まないこと")

    def test_unknown_or_empty_names_stop_without_change(self):
        cases = [("doc-dag,no-such", ["載っていない", "no-such"]),
                 ("doc-dag,,pr-teeth", ["空の要素"]),
                 ("doc-dag,", ["空の要素"])]
        for command in ("status", "install"):
            for value, fragments in cases:
                with self.subTest(command=command, value=value):
                    self.assert_stopped_without_change(self.run_script(command, "--plugins", value), *fragments)


class PluginsOptionTest(unittest.TestCase):
    """オプション --plugins の値の解析 (R1・KD7)。"""

    def test_comma_separated_names(self):
        plugins = load_plugins()
        self.assertEqual(plugins.parse_names("a,b"), ["a", "b"])
        self.assertEqual(plugins.parse_names("doc-dag"), ["doc-dag"])
        self.assertIsNone(plugins.parse_names(None), "指定しないときは、すべてを対象にすること (None を返す)")

    def test_empty_elements_are_errors(self):
        plugins = load_plugins()
        for value in ("a,,b", "", ",a", "a,"):
            with self.subTest(value=value):
                with self.assertRaises(plugins.PluginsError) as cm:
                    plugins.parse_names(value)
                self.assertIn("空の要素", str(cm.exception))


class RegistrationTest(ScriptTestCase):
    """マーケットプレイスの登録と取得元の検査 (R4・R5・KD9・KD13・KD21)。"""

    def test_unregistered_marketplace_shows_add_command(self):
        self.write_state({"marketplaces": plugintest.REGISTERED[1:]})
        r = self.run_script("status")
        self.assert_stopped_without_change(r, "claude plugin marketplace add akm/claude-plugins")
        self.assertEqual(self.read_state()["marketplaces"], plugintest.REGISTERED[1:], "マーケットプレイスを登録しないこと")

    def test_url_registrations_are_accepted(self):
        for url in ("https://github.com/akm/claude-plugins.git", "git@github.com:akm/claude-plugins.git"):
            with self.subTest(url=url):
                self.write_state({"marketplaces": [{"name": MP, "source": "git", "url": url}]})
                self.assertEqual(self.latest(self.prepare()), PUBLISHED, "URL の形で登録した配布元も受け付けること")

    def test_other_sources_are_rejected(self):
        for entry in ({"name": MP, "source": "github", "repo": "someone/claude-plugins"},
                      {"name": MP, "source": "git", "url": "https://github.com/someone/claude-plugins.git"},
                      {"name": MP, "source": "directory", "path": "/Users/example/claude-plugins"}):
            with self.subTest(entry=entry):
                self.write_state({"marketplaces": [entry]})
                self.assert_stopped_without_change(self.run_script("status"), "取得元")

    def test_marketplace_list_failure_or_bad_output(self):
        for fault, fragment in (({"action": "fail", "stderr": "marketplace list broke\n"}, "marketplace list broke"),
                                ({"action": "no_change", "stdout": "{}"}, "配列でない")):
            with self.subTest(fault=fault):
                self.write_state({"marketplaces": plugintest.REGISTERED,
                                  "faults": [dict(fault, prefix=["plugin", "marketplace", "list"])]})
                self.assert_stopped_without_change(self.run_script("status"), fragment)


class MarketplaceListParseTest(unittest.TestCase):
    """claude plugin marketplace list --json の出力の検査 (KTD7)。"""

    def test_requires_array_of_name_and_source(self):
        plugins = load_plugins()
        for text in ("not json", "{}", '[{"name": "a"}]', '[{"source": "github"}]', '["a"]'):
            with self.subTest(text=text):
                with self.assertRaises(plugins.PluginsError):
                    plugins.parse_marketplace_list(text)
        listed = plugins.parse_marketplace_list('[{"name": "a", "source": "github", "repo": "o/r", "extra": 1}]')
        self.assertEqual([m["name"] for m in listed], ["a"], "知らないキーは無視すること")


class SourceUrlTest(unittest.TestCase):
    """URL の正規化 (KTD4 の 3)。"""

    def test_same_source(self):
        plugins = load_plugins()
        expected = plugins.source_key("https://github.com/akm/claude-plugins")
        self.assertIsNotNone(expected)
        for url in ("git@github.com:akm/claude-plugins.git", "git@github.com:akm/claude-plugins",
                    "ssh://git@github.com/akm/claude-plugins.git", "ssh://git@github.com:22/akm/claude-plugins",
                    "https://github.com/akm/claude-plugins.git", "https://github.com/akm/claude-plugins/",
                    "https://github.com/akm/claude-plugins.git/", "git://github.com/akm/claude-plugins.git",
                    "https://GitHub.com/AKM/Claude-Plugins.git", "git@GITHUB.COM:Akm/claude-plugins.git"):
            with self.subTest(url=url):
                self.assertEqual(plugins.source_key(url), expected, "同じ配布元と判定すること")

    def test_different_source(self):
        plugins = load_plugins()
        expected = plugins.source_key("https://github.com/akm/claude-plugins")
        for url in ("https://gitlab.com/akm/claude-plugins.git", "https://github.com/someone/claude-plugins.git",
                    "https://github.com/akm/other-plugins.git", "git@github-work:akm/claude-plugins.git",
                    "github-work:akm/claude-plugins.git", "/Users/example/claude-plugins", "akm/claude-plugins",
                    "https://github.com/akm/claude-plugins/tree/main", "http://github.com/akm/claude-plugins.git", ""):
            with self.subTest(url=url):
                self.assertNotEqual(plugins.source_key(url), expected, "違う配布元と判定すること")


class OriginTest(ScriptTestCase):
    """remote origin と git fetch の検査 (R6・R7・KD10)。"""

    def test_missing_origin(self):
        plugintest.git(self.work, "remote", "remove", "origin", env=self.env)
        self.assert_stopped_without_change(self.run_script("status"), "remote origin")

    def test_origin_of_other_repository(self):
        for url in ("https://github.com/someone/claude-plugins.git", "git@github-work:akm/claude-plugins.git"):
            with self.subTest(url=url):
                plugintest.git(self.work, "remote", "set-url", "origin", url, env=self.env)
                self.assert_stopped_without_change(self.run_script("status"), "remote origin", url)

    def test_fetch_failure_does_not_use_old_origin_main(self):
        old = plugintest.git(self.work, "rev-parse", "origin/main", env=self.env).stdout.strip()
        self.assertTrue(old, "作業用のリポジトリに、前に取得した origin/main があること")
        shutil.rmtree(self.source)
        self.assert_stopped_without_change(self.run_script("status"), "git fetch")


class PublishedFilesTest(ScriptTestCase):
    """origin/main の marketplace.json と plugin.json の検査 (R3・KTD4 の 4・KTD5・KTD6)。"""

    def stopped_message(self, files):
        plugintest.commit_source(self.source_tree, files, "配布元を変える")
        r = self.run_script("status")
        self.assert_stopped_without_change(r)
        return r.stderr

    def test_plugin_json_problems_have_distinct_messages(self):
        path = "doc-dag/.claude-plugin/plugin.json"
        missing = self.stopped_message({path: None})
        plugintest.commit_source(self.source_tree, {path: plugintest.dump_json(plugintest.plugin_json("doc-dag", "0.2.0"))}, "戻す")
        broken = self.stopped_message({path: "{"})
        no_version = self.stopped_message({path: plugintest.dump_json({"name": "doc-dag"})})
        fragments = {"plugin.json が無い": missing, "JSON として読めない": broken, "キー version が無い": no_version}
        for fragment, message in fragments.items():
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, message)
                for other in fragments.values():
                    if other is not message:
                        self.assertNotIn(fragment, other, "無い場合と、読めない・version が無い場合を、違う文言で示すこと")

    def test_version_must_be_x_y_z(self):
        for version in ("0.29.0-alpha1", "1.2"):
            with self.subTest(version=version):
                self.publish_version("doc-dag", version)
                self.assert_stopped_without_change(self.run_script("status"), "X.Y.Z", version)

    def test_origin_main_marketplace_must_match(self):
        names = [name for name, _ in PUBLISHED]
        renamed = plugintest.marketplace_json(names)
        renamed["name"] = "other-marketplace"
        cases = [
            ("名前", renamed),
            ("配布元", marketplace_with(names, {n: {"url": "https://github.com/someone/claude-plugins"} for n in names})),
            ("git-subdir", marketplace_with(names, {"doc-dag": {"source": "url"}})),
            ("ref", marketplace_with(names, {"pr-teeth": {"ref": "develop"}})),
        ]
        for fragment, data in cases:
            with self.subTest(fragment=fragment):
                message = self.stopped_message({".claude-plugin/marketplace.json": plugintest.dump_json(data)})
                self.assertIn(fragment, message)


class VersionTest(unittest.TestCase):
    """版の形と比較 (KTD6・KD8)。"""

    def test_parse_version(self):
        plugins = load_plugins()
        self.assertEqual(plugins.parse_version("0.28.4"), (0, 28, 4))
        self.assertEqual(plugins.parse_version("10.0.12"), (10, 0, 12))
        for value in ("0.29.0-alpha1", "1.2", "1.2.3.4", "v1.2.3", "1.2.3\n", " 1.2.3", "１.2.3", "", 1.2, None):
            with self.subTest(value=value):
                self.assertIsNone(plugins.parse_version(value), "X.Y.Z の形でなければ None を返すこと")

    def test_compare_versions(self):
        plugins = load_plugins()
        self.assertEqual(plugins.compare_versions("0.28.4", "0.28.4"), "same")
        self.assertEqual(plugins.compare_versions("0.23.0", "0.28.4"), "older")
        self.assertEqual(plugins.compare_versions("0.9.0", "0.10.0"), "older", "文字列ではなく整数として比べること")
        self.assertEqual(plugins.compare_versions("1.0.0", "0.28.4"), "newer")


class PluginListTest(ScriptTestCase):
    """claude plugin list --json の検査と読み取り (KTD7 の 1 つ目の箇条)。"""

    def test_installed_are_grouped_by_target(self):
        self.write_state({"marketplaces": plugintest.REGISTERED, "installed": [
            {"id": f"doc-dag@{MP}", "scope": "project", "version": "0.1.0", "projectPath": "/Users/example/other-project"},
            {"id": f"doc-dag@{MP}", "scope": "user", "version": "0.2.0", "enabled": False},
            {"id": f"wording-guard@{MP}", "scope": "local", "version": "0.29.0", "projectPath": "/Users/example/p"},
            {"id": f"removed-plugin@{MP}", "scope": "user", "version": "not-a-version"},
            {"id": "doc-dag@claude-plugins-official", "scope": "user", "version": "abc"},
        ]})
        snapshot = self.prepare()
        installed = {p["name"]: p["installed"] for p in snapshot["plugins"]}
        self.assertEqual([(e["scope"], e["version"], e["enabled"], e["projectPath"]) for e in installed["doc-dag"]],
                         [("project", "0.1.0", None, "/Users/example/other-project"), ("user", "0.2.0", False, None)],
                         "対象のプラグインの要素を、出力の順にまとめること (有効か無効かは user スコープの分だけ)")
        self.assertEqual(installed["doc-dag"][1]["installPath"],
                         os.path.join(self.config_dir, "plugins", "cache", MP, "doc-dag", "0.2.0"))
        self.assertEqual(installed["pr-teeth"], [], "インストールされていないプラグインは空の配列にすること")
        self.assertEqual([(e["scope"], e["projectPath"]) for e in installed["wording-guard"]],
                         [("local", "/Users/example/p")])
        self.assert_only_reads()

    def test_bad_plugin_list_stops(self):
        cases = [
            ({"faults": [{"prefix": ["plugin", "list"], "action": "no_change", "stdout": "{}"}]}, "配列でない"),
            ({"faults": [{"prefix": ["plugin", "list"], "action": "fail", "stderr": "list broke\n"}]}, "list broke"),
            ({"installed": [{"id": f"doc-dag@{MP}", "scope": "user", "version": "1.0"}]}, "X.Y.Z"),
        ]
        for state, fragment in cases:
            with self.subTest(fragment=fragment):
                self.write_state(dict(state, marketplaces=plugintest.REGISTERED))
                self.assert_stopped_without_change(self.run_script("status"), fragment)


class PluginListParseTest(unittest.TestCase):
    """claude plugin list --json の出力の検査 (KTD7 の 1 つ目の箇条)。外部のコマンドを実行しない。"""

    USER = {"id": f"doc-dag@{MP}", "scope": "user", "version": "0.2.0", "enabled": True, "installPath": "/p/0.2.0"}
    PROJECT = {"id": f"doc-dag@{MP}", "scope": "project", "version": "0.1.0", "enabled": True, "installPath": "/p/0.1.0",
               "projectPath": "/Users/example/other-project"}

    def parse(self, elements):
        return load_plugins().parse_plugin_list(json.dumps(elements), MP)

    def test_reads_own_elements_and_ignores_others(self):
        others = [{"id": "x@claude-plugins-official", "scope": "project", "version": "abc"},
                  {"id": "skill@local-skills"}]
        listed = self.parse([dict(self.USER, unknownKey=1), self.PROJECT] + others)
        self.assertEqual([(e["name"], e["scope"], e["version"], e["enabled"], e["projectPath"], e["installPath"]) for e in listed],
                         [("doc-dag", "user", "0.2.0", True, None, "/p/0.2.0"),
                          ("doc-dag", "project", "0.1.0", None, "/Users/example/other-project", "/p/0.1.0")],
                         "このリポジトリのプラグインの要素だけを返し、ほかの要素と知らないキーは検査しないこと")

    def test_rejects_wrong_shapes(self):
        plugins = load_plugins()
        cases = {
            "JSON でない": "not json",
            "配列でない": json.dumps({"id": "x"}),
            "id が無い要素": json.dumps([{"scope": "user"}]),
            "version が無い": json.dumps([plugintest.without(self.USER, "version")]),
            "scope が無い": json.dumps([plugintest.without(self.USER, "scope")]),
            "installPath が無い": json.dumps([plugintest.without(self.USER, "installPath")]),
            "user の enabled が無い": json.dumps([plugintest.without(self.USER, "enabled")]),
            "user の enabled が真偽値でない": json.dumps([dict(self.USER, enabled="true")]),
            "project の projectPath が無い": json.dumps([plugintest.without(self.PROJECT, "projectPath")]),
            "local の projectPath が無い": json.dumps([dict(plugintest.without(self.PROJECT, "projectPath"), scope="local")]),
            "知らないスコープ": json.dumps([dict(self.USER, scope="managed")]),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(plugins.PluginsError):
                    plugins.parse_plugin_list(text, MP)


class WorkingTreeMarketplaceTest(ScriptTestCase):
    """作業ツリーの marketplace.json から名前と配布元を読む (KTD4 の 1)。"""

    def test_two_sources_stop(self):
        names = [name for name, _ in PUBLISHED]
        data = marketplace_with(names, {"pr-teeth": {"url": "https://github.com/someone/claude-plugins"}})
        self.write_work(".claude-plugin/marketplace.json", plugintest.dump_json(data))
        self.assert_stopped_without_change(self.run_script("status"), "1 つの配布元")

    def test_missing_marketplace_json_stops(self):
        os.remove(os.path.join(self.work, ".claude-plugin", "marketplace.json"))
        self.assert_stopped_without_change(self.run_script("install"), ".claude-plugin/marketplace.json")
        self.assertEqual(self.read_record(), [], "claude を実行する前に終了すること")


class RootAndEnvironmentTest(ScriptTestCase):
    """ルートの決め方 (KTD3) と、外部のコマンドの実行の仕方 (KTD2)。"""

    def make_other_repo(self):
        """origin が別のリポジトリを指す、別の git リポジトリを作り、そのパスを返す。"""
        other = os.path.join(self.root, "other")
        os.makedirs(other)
        plugintest.git(other, "init", "-q", "-b", "main", env=self.env)
        plugintest.git(other, "remote", "add", "origin", "https://github.com/someone/other.git", env=self.env)
        return other

    def test_root_comes_from_script_location(self):
        other = self.make_other_repo()
        snapshot = self.prepare(cwd=other)
        self.assertEqual(snapshot["sha"], self.origin_main_sha(), "cwd のリポジトリではなく、コピーした先のリポジトリを読むこと")
        self.assertEqual(self.latest(snapshot), PUBLISHED)

    def test_git_dir_in_environment_is_ignored(self):
        env = dict(self.env, GIT_DIR=os.path.join(self.source_tree, ".git"), GIT_WORK_TREE=self.source_tree)
        snapshot = self.prepare(env=env)
        self.assertEqual(snapshot["sha"], self.origin_main_sha(),
                         "環境変数 GIT_DIR が別のリポジトリを指していても、スクリプトのルートのリポジトリを読むこと")

    def test_claude_runs_in_new_empty_directory(self):
        caller = os.path.join(self.root, "caller")
        os.makedirs(caller)
        self.prepare(cwd=caller)
        record = self.read_record()
        self.assertEqual([e["args"] for e in record], [["plugin", "marketplace", "list", "--json"], ["plugin", "list", "--json"]],
                         "marketplace list と plugin list を、この順に 1 回ずつ実行すること")
        for entry in record:
            with self.subTest(args=entry["args"]):
                self.assertNotIn(entry["cwd"], (self.work, caller), "リポジトリのルートでも呼び出した側の cwd でもないこと")
                self.assertFalse(os.path.exists(entry["cwd"]), "実行の後に一時ディレクトリを消すこと")
        self.assertNotEqual(record[0]["cwd"], record[1]["cwd"], "実行のたびに一時ディレクトリを作ること")

    def test_ctrl_c_during_preconditions(self):
        self.write_state({"marketplaces": plugintest.REGISTERED,
                          "faults": [{"prefix": ["plugin", "marketplace", "list"], "action": "sigint"}]})
        r = self.run_script("status")
        self.assertEqual(r.returncode, 130, f"Ctrl-C で中断したときは終了コード 130 で終了すること: {r.stderr}")
        self.assertIn("中断", r.stderr)
        self.assertIn(plugintest.NOTHING_CHANGED, r.stderr)
        self.assert_only_reads()


class PythonVersionTest(unittest.TestCase):
    """Python の版の検査 (KTD10)。"""

    def test_python_too_old(self):
        plugins = load_plugins()
        message = plugins.python_too_old((3, 10, 14, "final", 0))
        self.assertIsNotNone(message, "3.10 では案内を返すこと")
        self.assertIn("3.11", message)
        self.assertIn("3.10.14", message, "実行した Python の版を案内に書くこと")
        self.assertIsNone(plugins.python_too_old((3, 11, 0, "final", 0)), "3.11 では何も返さないこと")
        self.assertIsNone(plugins.python_too_old((3, 13, 3, "final", 0)))


if __name__ == "__main__":
    unittest.main()
