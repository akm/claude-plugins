#!/usr/bin/env python3
"""スクリプト scripts/plugins.py の、インストール (サブコマンド install) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s scripts/tests

本物の claude は実行せず、GitHub に接続しない (共通の準備はファイル scripts/tests/plugintest.py)。スクリプトの中の関数は
差し替えない。スクリプトを作業用のリポジトリにコピーし、プロセスとして実行して、標準出力・標準エラー出力・終了コードと、
偽の claude の記録と状態を見る。失敗・成功を返して版を変えない・Ctrl-C は、偽の claude の状態のファイルの faults で起こす。
Ctrl-C は、偽の claude が親のプロセス (スクリプト) に SIGINT を送って起こす。

ファイル scripts/tests/test_makefile.py が、クラス InstallTestCase を使う。

このファイルの R・KD・KTD の番号は、計画のファイル docs/plans/2026-11-02-1748-feat-plugin-install-status-plan.md の
Requirements (R)・Key Decisions (KD)・Key Technical Decisions (KTD) の番号。
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import plugintest  # noqa: E402

MP = plugintest.MARKETPLACE
# 配布元の main にある版 (最新の版)。marketplace.json はこの順にする。名前の辞書順と違う順にして、
# インストールの順が marketplace.json の順であることを確認する
PUBLISHED = [("wording-guard", "0.28.0"), ("doc-dag", "0.2.0"), ("pr-teeth", "0.5.1")]
LATEST = dict(PUBLISHED)
# マーケットプレイスの clone にある版 (最新の版より古い)。plugin marketplace update で、配布元の版に置き換わる
CLONE = {"wording-guard": "0.27.0", "doc-dag": "0.1.0", "pr-teeth": "0.5.0"}
# 状態を変えない claude のコマンド (plugintest.READ_COMMANDS の 2 つ)
LIST = ["plugin", "list", "--json"]
MARKETPLACE_LIST = ["plugin", "marketplace", "list", "--json"]
UPDATE = ["plugin", "marketplace", "update", MP]
LOAD = "実行中のセッションに読み込む方法"
UNKNOWN = "版が変わったか分からない"
STATUS_HINT = "make plugins-status"
# インストールが確認を求めて失敗したときの進め方 (中止の文の直し方) の一部
CONFIRM_GUIDE = "を実行し、表示されたコマンドを確認してからインストールする"


def install_args(name):
    """プラグイン name を user スコープにインストールする claude の引数。"""
    return ["plugin", "install", f"{name}@{MP}", "--scope", "user", "--json"]


def list_element(name, version, install_path):
    """claude plugin list --json の、user スコープの要素を作る (偽の claude の出力を差し替えるときに使う)。"""
    return {"id": f"{name}@{MP}", "version": version, "scope": "user", "enabled": True, "installPath": install_path}


def setup_command(install_path):
    """実行の後の案内に出る、textlint を入れるコマンド。"""
    return f"python3 {install_path}/scripts/wording_lint.py setup"


def error_text(r):
    """標準エラー出力のうち、エラーの文 (プログラム名で始まる行) だけを、改行でつないで返す。"""
    return "\n".join(line for line in r.stderr.splitlines() if line.startswith("plugins.py: "))


class InstallTestCase(plugintest.PluginTestCase):
    """配布元と作業用のリポジトリを作り、スクリプトを作業用のリポジトリにコピーする。

    マーケットプレイスは登録済みで、その clone は配布元より古い。インストール済みのプラグインは無い。
    """

    def setUp(self):
        super().setUp()
        self.make_repos(PUBLISHED)
        self.copy_into_work([plugintest.SCRIPT_REL])
        self.set_state()

    def set_state(self, installed_entries=(), faults=(), marketplaces=plugintest.REGISTERED):
        self.write_state({"marketplaces": marketplaces, "clone": {MP: dict(CLONE)}, "published": {MP: dict(LATEST)},
                          "installed": list(installed_entries), "faults": list(faults)})

    def run_install(self, *args, cwd=None):
        """スクリプトの install を、メソッド run_script で実行する。"""
        return self.run_script("install", *args, cwd=cwd)

    def commands(self):
        """偽の claude が受けた引数を、呼び出しの順に返す。"""
        return [entry["args"] for entry in self.read_record()]

    def changes(self):
        """偽の claude が受けた引数のうち、状態を変えないコマンドでないものを、呼び出しの順に返す。"""
        return [args for args in self.commands() if args not in plugintest.READ_COMMANDS]

    def user_versions(self):
        """偽の claude の状態から、user スコープにインストール済みのプラグインの名前 → 版を返す。"""
        return {e["id"].partition("@")[0]: e["version"] for e in self.read_state()["installed"] if e["scope"] == "user"}

    def install_path(self, name, version):
        """偽の claude が plugin list --json で返す展開先。"""
        return os.path.join(self.config_dir, "plugins", "cache", MP, name, version)

    def assert_succeeded(self, r):
        """終了コード 0 で終了したこと。"""
        self.assertEqual(r.returncode, 0, f"終了コード 0 で終了すること: {r.stderr}")

    def assert_aborted(self, r, code=4):
        """終了コード code で終了し、エラーの文 (プログラム名で始まる行) が標準エラー出力の最後にあること。"""
        self.assertEqual(r.returncode, code, f"終了コード {code} で終了すること: {r.stderr}")
        last = r.stderr.rstrip("\n").splitlines()[-1]
        self.assertTrue(last.startswith("plugins.py: "), f"最後にエラーの文を書くこと: {r.stderr}")


class InstallTest(InstallTestCase):
    """user スコープに無いものだけを、marketplace.json の順にインストールする (R13・KD11・KTD8)。"""

    def test_installs_only_missing_in_marketplace_order(self):
        self.set_state([self.installed("pr-teeth", "user", "0.5.0"),
                        self.installed("doc-dag", "project", "0.1.0", project_path=plugintest.OTHER_PROJECT)])
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertEqual(self.commands(), [
            MARKETPLACE_LIST, LIST,
            UPDATE,
            install_args("wording-guard"), LIST,
            install_args("doc-dag"), LIST,
        ], "マーケットプレイスの定義を 1 回取得し直してから、user スコープに無いものを marketplace.json の順に 1 つずつ"
           "インストールし、そのたびに plugin list --json を再度読み込むこと")
        for args in self.commands():
            with self.subTest(args=args):
                self.assertNotIn(args[:2], (["plugin", "update"], ["plugin", "enable"], ["plugin", "disable"]),
                                 "plugin update・plugin enable・plugin disable を実行しないこと")
        self.assertEqual(self.user_versions(), {"wording-guard": "0.28.0", "doc-dag": "0.2.0", "pr-teeth": "0.5.0"},
                         "user スコープに無いものは最新の版でインストールし、古いものは扱わないこと")

    def test_reports_installed_and_load_note(self):
        self.set_state([self.installed("pr-teeth", "user", "0.5.0")])
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertEqual(r.stderr, "", "成功したときは標準エラー出力に何も書かないこと")
        lines = r.stdout.splitlines()
        self.assertIn("インストールしたもの (user スコープ): wording-guard 0.28.0, doc-dag 0.2.0", lines,
                      "インストールしたものの一覧を、インストールした版とともに表示すること")
        self.assertIn(LOAD, r.stdout, "インストールしたものがあれば、読み込みの案内を表示すること (R18)")
        self.assertIn("pr-teeth", r.stdout, "user スコープにインストール済みなので扱わなかったものを表示すること")

    def test_wording_guard_setup_uses_reread_install_path(self):
        reread = "/Users/example/reread-cache/wording-guard/0.28.0"
        self.set_state(faults=[{"prefix": LIST, "skip": 1, "action": "no_change",
                                "stdout": json.dumps([list_element("wording-guard", "0.28.0", reread)])}])
        r = self.run_install("--plugins", "wording-guard")
        self.assert_succeeded(r)
        self.assertIn(setup_command(reread), r.stdout.splitlines()[-1],
                      "textlint を入れるコマンドを、インストールの後に再度読み込んだ展開先で表示すること (KTD8)")

    def test_wording_guard_setup_with_install_path_from_fake(self):
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertIn(setup_command(self.install_path("wording-guard", "0.28.0")), r.stdout,
                      "wording-guard をインストールしたら、textlint を入れるコマンドを表示すること (R18)")

    def test_install_path_with_space_is_quoted(self):
        reread = "/Users/example/claude config/wording-guard/0.28.0"
        self.set_state(faults=[{"prefix": LIST, "skip": 1, "action": "no_change",
                                "stdout": json.dumps([list_element("wording-guard", "0.28.0", reread)])}])
        r = self.run_install("--plugins", "wording-guard")
        self.assert_succeeded(r)
        self.assertIn(f"python3 '{reread}/scripts/wording_lint.py' setup", r.stdout,
                      "展開先に空白があれば、コピーしてそのまま実行できるよう、シェルの引用符で囲むこと")

    def test_no_wording_guard_setup_when_wording_guard_is_unchanged(self):
        self.set_state([self.installed("wording-guard", "user", "0.27.0")])
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertEqual(self.changes(), [UPDATE, install_args("doc-dag"), install_args("pr-teeth")])
        self.assertIn(LOAD, r.stdout)
        self.assertNotIn("wording_lint.py", r.stdout, "wording-guard を変えなかったときは、textlint を入れるコマンドを表示しないこと")

    def test_nothing_to_install(self):
        self.set_state([self.installed("wording-guard", "user", "0.28.0"), self.installed("doc-dag", "user", "0.1.0"),
                        self.installed("pr-teeth", "user", "0.6.0")])
        before = self.read_state()
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.changes(), [],
                         "入れるものが無いときは、plugin marketplace update も含めて、変える操作を実行しないこと (KD20)")
        self.assertEqual(self.read_state(), before, "インストール済みのプラグインもマーケットプレイスの clone も変えないこと")
        self.assertIn(plugintest.NOTHING_CHANGED, r.stdout, "何も変えていないことを表示すること")
        self.assertNotIn(LOAD, r.stdout, "何も変えていないときは、読み込みの案内を表示しないこと")

    def test_plugins_option_limits_targets(self):
        r = self.run_install("--plugins", "pr-teeth,wording-guard")
        self.assert_succeeded(r)
        self.assertEqual(self.changes(), [UPDATE, install_args("wording-guard"), install_args("pr-teeth")],
                         "--plugins で指定したものだけを、marketplace.json の順にインストールすること")


class AbortTest(InstallTestCase):
    """claude の失敗と、成功を返したのに版が最新でないときの中止 (R15・R16・R18・KD12・KD14・KD19)。"""

    def test_marketplace_update_failure(self):
        self.set_state(faults=[{"prefix": UPDATE, "action": "fail", "stdout": "update stdout\n",
                                "stderr": "network error\n"}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertEqual(self.changes(), [UPDATE], "マーケットプレイスの定義の取得し直しが失敗したら、インストールを実行しないこと")
        self.assertIn(f"マーケットプレイス {MP}", r.stderr, "失敗したマーケットプレイスの名前を標準エラー出力に書くこと")
        self.assertIn("network error", r.stderr, "失敗したコマンドの出力を標準エラー出力に書くこと")
        self.assertIn("update stdout", r.stderr)
        self.assertIn("処理しなかったもの: wording-guard, doc-dag, pr-teeth", r.stderr.splitlines())
        self.assertNotIn(LOAD, r.stderr + r.stdout, "何もインストールしていないときは、読み込みの案内を表示しないこと")

    def test_second_install_fails(self):
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "fail", "stderr": "doc-dag のエラー\n"}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertEqual(self.commands()[-2:], [install_args("doc-dag"), LIST],
                         "インストールが失敗したら、plugin list --json を再度読み込んでから中止すること")
        self.assertNotIn(install_args("pr-teeth"), self.commands(), "失敗した後のプラグインは処理しないこと (KD12)")
        lines = r.stderr.splitlines()
        self.assertIn("doc-dag のエラー", r.stderr, "失敗したコマンドの出力を標準エラー出力に書くこと")
        self.assertIn("インストールしたもの (user スコープ): wording-guard 0.28.0", lines,
                      "中止する前にインストールしたものを示すこと")
        self.assertIn("処理中だったもの: doc-dag は、user スコープにインストールされていない (再度読み込んだ結果)", lines,
                      "再度読み込んだ、失敗したプラグインの実際の状態を示すこと (R15)")
        self.assertIn("処理しなかったもの: pr-teeth", lines, "処理しなかったプラグインの名前を示すこと")
        self.assertIn(f"claude plugin install doc-dag@{plugintest.MARKETPLACE} --scope user を実行し", r.stderr,
                      "確認を求めて失敗したときに、端末でインストールする進め方を直し方で示すこと")
        self.assertIn(LOAD, r.stderr, "中止したときも、インストールしたものがあれば読み込みの案内を表示すること (R18)")
        error = error_text(r)
        self.assertIn("doc-dag", error, "エラーの文に、失敗したプラグインの名前を書くこと")
        self.assertIn("一部が変わっている", error, "変える操作の途中で中止したことをエラーの文に書くこと")

    def test_reread_after_failure_also_fails(self):
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "fail"},
                               {"prefix": LIST, "skip": 2, "action": "fail", "stderr": "list のエラー\n"}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertNotIn(install_args("pr-teeth"), self.commands())
        lines = r.stderr.splitlines()
        self.assertIn(f"doc-dag は、{UNKNOWN}", r.stderr,
                      "再度の読み込みも失敗したら、処理中だったものを「版が変わったか分からない」と示すこと (KTD8)")
        self.assertIn(STATUS_HINT, r.stderr)
        self.assertIn("処理しなかったもの: pr-teeth", lines)
        self.assertIn(LOAD, r.stderr, "版が変わったか分からないものがあれば、読み込みの案内を表示すること (R18)")
        self.assertIn(CONFIRM_GUIDE, r.stderr,
                      "再度読み込めず、インストールされたか分からないときは、確認の進め方を示すこと")

    def test_failed_install_found_latest_after_reread(self):
        reread = [list_element("wording-guard", "0.28.0", self.install_path("wording-guard", "0.28.0")),
                  list_element("doc-dag", "0.2.0", self.install_path("doc-dag", "0.2.0"))]
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "fail"},
                               {"prefix": LIST, "skip": 2, "action": "no_change", "stdout": json.dumps(reread)}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertNotIn(install_args("pr-teeth"), self.commands(), "インストールが失敗を返したら、版が最新でも中止すること")
        lines = r.stderr.splitlines()
        self.assertIn("インストールしたもの (user スコープ): wording-guard 0.28.0, doc-dag 0.2.0", lines,
                      "再度読み込んで最新の版で入っていたものは、インストールしたものとして示すこと")
        self.assertIn("処理しなかったもの: pr-teeth", lines)
        self.assertNotIn(CONFIRM_GUIDE, r.stderr,
                         "再度読み込んでインストールされていると分かったときは、確認の進め方を示さないこと")

    def test_failed_install_found_old_version_after_reread(self):
        reread = [list_element("wording-guard", "0.28.0", self.install_path("wording-guard", "0.28.0")),
                  list_element("doc-dag", "0.1.0", self.install_path("doc-dag", "0.1.0"))]
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "fail"},
                               {"prefix": LIST, "skip": 2, "action": "no_change", "stdout": json.dumps(reread)}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertIn("処理中だったもの: doc-dag は、user スコープの版が 0.1.0 で、最新の版 0.2.0 と違う (再度読み込んだ結果)",
                      r.stderr.splitlines(), "再度読み込んで古い版で入っていたものは、最新の版と違うと示すこと")
        self.assertNotIn(CONFIRM_GUIDE, r.stderr,
                         "再度読み込んで古い版でインストールされていると分かったときも、確認の進め方を示さないこと")

    def test_install_output_not_utf8_judged_by_exit_code_and_reread(self):
        # 偽の claude の bad_utf8 は状態を変えないので、再度読み込むと doc-dag はインストールされていない
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "bad_utf8"}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertIn("プラグイン doc-dag のインストールは成功を返したが", r.stderr,
                      "変える操作の標準出力を UTF-8 として読めなくても、終了コード 0 なら成功を返したとして扱い、"
                      "再度の読み込みで版を検査すること (KTD7)")
        self.assertNotIn("UTF-8 として読めない", r.stderr, "変える操作の標準出力は読まないこと (KTD7)")
        self.assertNotIn(CONFIRM_GUIDE, r.stderr,
                         "claude が終了コード 0 で終了したときは、確認の進め方を示さないこと")

    def test_install_output_not_utf8_continues_when_latest(self):
        reread = [list_element(name, version, self.install_path(name, version)) for name, version in PUBLISHED]
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "bad_utf8"},
                               {"prefix": LIST, "skip": 2, "action": "no_change", "stdout": json.dumps(reread)}])
        r = self.run_install()
        self.assert_succeeded(r)
        self.assertIn(install_args("pr-teeth"), self.commands(),
                      "標準出力を UTF-8 として読めなくても、終了コード 0 で再度読み込んだ版が最新の版なら、続けてインストールすること")
        self.assertIn("インストールしたもの (user スコープ): wording-guard 0.28.0, doc-dag 0.2.0, pr-teeth 0.5.1",
                      r.stdout.splitlines())

    def test_reread_output_not_utf8_aborts(self):
        self.set_state(faults=[{"prefix": LIST, "skip": 1, "action": "bad_utf8"}])
        r = self.run_install()
        self.assert_aborted(r)
        self.assertIn("UTF-8 として読めない", r.stderr,
                      "出力を使う読み取りのコマンドは、標準出力を UTF-8 として読めなければ失敗として中止すること")
        self.assertIn("wording-guard は、版が変わったか分からない", r.stderr)

    def test_success_without_latest_version(self):
        cases = [
            # 成功を返したのに、インストールされていない
            ("インストールされていない", [{"prefix": install_args("doc-dag"), "action": "no_change"}],
             "doc-dag", ["wording-guard"], {"wording-guard": "0.28.0"}),
            # マーケットプレイスの定義の取得し直しが成功を返したのに clone が古いままで、古い版がインストールされる
            ("0.27.0", [{"prefix": UPDATE, "action": "no_change"}],
             "wording-guard", [], {"wording-guard": "0.27.0"}),
        ]
        for actual, faults, name, before_names, expected_versions in cases:
            with self.subTest(actual=actual):
                self.set_state(faults=faults)
                self.reset_record()
                r = self.run_install()
                self.assert_aborted(r)
                self.assertEqual(self.changes()[-1], install_args(name),
                                 "版が最新の版にならなかったら、その時点で中止すること (R16)")
                self.assertEqual(self.user_versions(), expected_versions)
                error = error_text(r)
                self.assertIn(name, error, "エラーの文に、版が最新にならなかったプラグインの名前を書くこと")
                self.assertIn(LATEST[name], error, "エラーの文に、最新の版を書くこと")
                self.assertIn(actual, r.stderr, "再度読み込んだ実際の状態を示すこと")
                self.assertIn("インストールしたもの (user スコープ): " + (", ".join(
                    f"{n} {LATEST[n]}" for n in before_names) or "なし"), r.stderr.splitlines())
                self.assertIn(LOAD, r.stderr, "user スコープの状態を変えたので、読み込みの案内を表示すること")


class InterruptTest(InstallTestCase):
    """Ctrl-C での中断 (R17・R18・KD16・KTD8)。偽の claude が、指定した呼び出しで親のプロセスに SIGINT を送る。"""

    def test_ctrl_c_during_second_install(self):
        self.set_state(faults=[{"prefix": install_args("doc-dag"), "action": "sigint"}])
        r = self.run_install()
        self.assert_aborted(r, 130)
        self.assertEqual(self.commands()[-1], install_args("doc-dag"), "中断したら、それ以上コマンドを実行しないこと")
        lines = r.stderr.splitlines()
        self.assertIn("インストールしたもの (user スコープ): wording-guard 0.28.0", lines,
                      "中断する前にインストールしたものを示すこと")
        self.assertIn(f"処理中だったもの: doc-dag は、{UNKNOWN}。{STATUS_HINT} で確認する", lines,
                      "処理中だったものを「版が変わったか分からない」と示し、make plugins-status で確認するよう案内すること")
        self.assertIn("処理しなかったもの: pr-teeth", lines)
        self.assertIn(LOAD, r.stderr, "中断したときも、インストールしたものがあれば読み込みの案内を表示すること (R18)")
        error = error_text(r)
        self.assertIn("Ctrl-C で中断した", error, "中断したことをエラーの文に書くこと")

    def test_ctrl_c_during_marketplace_update(self):
        self.set_state(faults=[{"prefix": UPDATE, "action": "sigint"}])
        r = self.run_install()
        self.assert_aborted(r, 130)
        self.assertEqual(self.changes(), [UPDATE], "中断したら、それ以上コマンドを実行しないこと")
        self.assertIn("処理しなかったもの: wording-guard, doc-dag, pr-teeth", r.stderr.splitlines())
        self.assertIn(STATUS_HINT, r.stderr)
        self.assertNotIn(LOAD, r.stderr, "プラグインを 1 つも処理していないときは、読み込みの案内を表示しないこと")


class PipeClosedTest(InstallTestCase):
    """標準出力を読むプロセスが先に終了したとき (R24・KD26)。"""

    def test_closed_before_changes(self):
        cases = [
            # 最初の表示 (インストールするもの) は、cmd_install の中で、変える操作を始める前に書く
            ("user スコープに無いものだけ", []),
            # 最初の表示 (インストール済みのもの) は、cmd_install の try の外で書き、関数 main が捕まえる
            ("user スコープにあるものも含む", [self.installed("pr-teeth", "user", "0.5.0")]),
        ]
        for label, installed in cases:
            with self.subTest(label):
                self.set_state(installed)
                self.reset_record()
                r = self.run_script_closing_stdout("install")
                self.assert_succeeded(r)
                self.assertIn("標準出力を読むプロセスが先に終了したので、表示を途中でやめた。何も変えていない。", r.stderr,
                              "変える操作を始める前に標準出力が閉じられたら、何も変えていないことを書くこと")
                self.assertNotIn("Traceback", r.stderr, "トレースバックを出さないこと")
                self.assertEqual(self.changes(), [], "変える操作を 1 つも実行しないこと")

    def test_closed_during_install(self):
        r = self.run_script_closing_stdout("install", after="wording-guard 0.28.0 を user スコープにインストールした")
        self.assert_aborted(r)
        self.assertIn("plugins.py: 標準出力を読むプロセスが先に終了したので、中止した。それ以上 claude のコマンドを実行していない。",
                      r.stderr.splitlines(), "インストールの途中で標準出力が閉じられたら、中止と同じく扱うこと")
        self.assertNotIn("Traceback", r.stderr, "トレースバックを出さないこと")
        # 閉じた直後の表示 (doc-dag をインストールする) が閉じる前に書けていれば、doc-dag のインストールの後の表示で失敗する
        self.assertNotIn(install_args("pr-teeth"), self.commands(), "標準出力が閉じられたら、それ以上コマンドを実行しないこと")
        self.assertTrue(any(line.startswith("インストールしたもの (user スコープ): wording-guard 0.28.0")
                            for line in r.stderr.splitlines()),
                        f"閉じられる前にインストールしたものを、標準エラー出力に示すこと: {r.stderr}")
        self.assertIn(LOAD, r.stderr, "インストールしたものがあれば、読み込みの案内を標準エラー出力に示すこと (R18)")


class PreconditionTest(InstallTestCase):
    """前提の検査でエラーになったときは、変える操作を 1 つも実行しない (R8)。"""

    def test_no_change_on_precondition_errors(self):
        cases = [
            ("登録されていない", {"marketplaces": []}, []),
            ("載っていない", {}, ["--plugins", "doc-dag,no-such"]),
            ("形が想定と違う", {"faults": [{"prefix": LIST, "action": "no_change", "stdout": "{}"}]}, []),
        ]
        for fragment, state, args in cases:
            with self.subTest(fragment=fragment):
                self.set_state(faults=state.get("faults", ()), marketplaces=state.get("marketplaces", plugintest.REGISTERED))
                self.reset_record()
                before = self.read_state()
                r = self.run_install(*args)
                self.assertEqual(r.returncode, 3, f"終了コード 3 で終了すること: {r.stderr}")
                self.assertIn(fragment, r.stderr)
                self.assertIn(plugintest.NOTHING_CHANGED, r.stderr)
                self.assertEqual(self.changes(), [], "前提の検査でエラーになったら、変える操作を実行しないこと")
                self.assertEqual(self.read_state(), before)

    def test_no_change_when_origin_is_other_repository(self):
        plugintest.git(self.work, "remote", "set-url", "origin", "https://github.com/someone/other.git", env=self.env)
        r = self.run_install()
        self.assertEqual(r.returncode, 3, f"終了コード 3 で終了すること: {r.stderr}")
        self.assertIn(plugintest.NOTHING_CHANGED, r.stderr)
        self.assertEqual(self.changes(), [], "前提の検査でエラーになったら、変える操作を実行しないこと")


if __name__ == "__main__":
    unittest.main()
