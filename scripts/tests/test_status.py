#!/usr/bin/env python3
"""スクリプト scripts/plugins.py の、状況の表示 (サブコマンド status) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s scripts/tests

本物の claude は実行せず、GitHub に接続しない (共通の準備はファイル scripts/tests/plugintest.py)。スクリプトの中の関数は
差し替えない。スクリプトを作業用のリポジトリにコピーし、プロセスとして実行して、標準出力・標準エラー出力・終了コードと、
偽の claude の記録を見る。claude plugin list --json の出力の形の誤りも、状況の表示を通したプロセスの単位で確認する。

ファイル scripts/tests/test_makefile.py が、クラス StatusTestCase と関数 parse_status を使う。

このファイルの R・KD・KTD の番号は、計画のファイル docs/plans/2026-11-02-1748-feat-plugin-install-status-plan.md の
Requirements (R)・Key Decisions (KD)・Key Technical Decisions (KTD) の番号。
"""

import json
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import plugintest  # noqa: E402

MP = plugintest.MARKETPLACE
PUBLISHED = [("doc-dag", "0.2.0"), ("pr-teeth", "0.5.1"), ("wording-guard", "0.28.0")]
NAMES = [name for name, _ in PUBLISHED]
AUTO_UPDATE_DOC_URL = "https://code.claude.com/docs/ja/plugins/install#turn-auto-update-on-or-off-for-a-marketplace"
LOCAL_PROJECT = "/Users/example/local-project"

# 状況の表示の、プラグインごとの最初の行 (名前と最新の版) と、その下のスコープごとの行
_HEADER_RE = re.compile(r"^(?P<name>\S+)\s+最新の版 (?P<latest>\S+)$")
_SCOPE_RE = re.compile(r"^  (?P<scope>user|project|local)\s+(?P<rest>\S.*)$")


def parse_status(stdout):
    """状況の表示を、プラグインの名前 → {"latest": 最新の版, "scopes": [(スコープ, 値の配列)]} の dict にする (表示の順)。

    値の配列は、スコープの行のスコープより後ろを空白で区切ったもの (3 つ目より後ろは区切らない)。インストールされて
    いない行は ["インストールされていない"] になる。プラグインの行とスコープの行のほかの行 (見出し・まとめ・案内) は使わない。
    """
    result = {}
    current = None
    for line in stdout.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            current = {"latest": m.group("latest"), "scopes": []}
            result[m.group("name")] = current
            continue
        m = _SCOPE_RE.match(line)
        if m and current is not None:
            current["scopes"].append((m.group("scope"), m.group("rest").split(None, 2)))
            continue
        if not line.startswith(" "):
            current = None
    return result


class StatusTestCase(plugintest.PluginTestCase):
    """配布元と作業用のリポジトリを作り、スクリプトを作業用のリポジトリにコピーする。マーケットプレイスは登録済み。"""

    def setUp(self):
        super().setUp()
        self.make_repos(PUBLISHED)
        self.copy_into_work([plugintest.SCRIPT_REL])
        self.write_state({"marketplaces": plugintest.REGISTERED})

    def set_installed(self, *entries):
        self.write_state({"marketplaces": plugintest.REGISTERED, "installed": list(entries)})

    def set_plugin_list_output(self, elements):
        """偽の claude の plugin list --json が、elements をそのまま JSON にして返すようにする。"""
        self.write_state({"marketplaces": plugintest.REGISTERED, "faults": [
            {"prefix": ["plugin", "list"], "action": "no_change", "stdout": json.dumps(elements)}]})

    def run_status(self, *args, cwd=None):
        """スクリプトの status を、メソッド run_script で実行する。"""
        return self.run_script("status", *args, cwd=cwd)

    def assert_shown(self, r):
        """終了コード 0 で終了し、標準エラー出力が空であること。状況の表示を parse_status の形で返す。"""
        self.assertEqual(r.returncode, 0, f"終了コード 0 で終了すること: {r.stderr}")
        self.assertEqual(r.stderr, "", "成功したときは標準エラー出力に何も書かないこと")
        return parse_status(r.stdout)

    def assert_stopped_without_change(self, r, *fragments):
        """メソッド plugintest.PluginTestCase.assert_stopped_without_change の検査に加えて、状況を表示していないこと。"""
        super().assert_stopped_without_change(r, *fragments)
        self.assertEqual(r.stdout, "", "エラーになったときは状況を表示しないこと")


class StatusDisplayTest(StatusTestCase):
    """スコープごとの版と、最新の版と比べた結果の表示 (R9〜R11・KD5・KD6・KD15)。"""

    def test_user_scope_compared_with_latest(self):
        self.set_installed(self.installed("doc-dag", "user", "0.1.0"), self.installed("pr-teeth", "user", "0.5.1"),
                           self.installed("wording-guard", "user", "0.29.0"))
        shown = self.assert_shown(self.run_status())
        self.assertEqual([(name, p["latest"]) for name, p in shown.items()], PUBLISHED,
                         "対象のプラグインごとに、最新の版を marketplace.json の順に表示すること")
        self.assertEqual(shown["doc-dag"]["scopes"], [("user", ["0.1.0", "古い", "有効"])])
        self.assertEqual(shown["pr-teeth"]["scopes"], [("user", ["0.5.1", "同じ", "有効"])])
        self.assertEqual(shown["wording-guard"]["scopes"], [("user", ["0.29.0", "新しい", "有効"])],
                         "インストール済みの版の方が新しいときは「新しい」と表示すること (KD15)")

    def test_not_installed_in_user_scope(self):
        self.set_installed(self.installed("doc-dag", "user", "0.2.0"),
                           self.installed("pr-teeth", "project", "0.5.1", project_path=plugintest.OTHER_PROJECT))
        shown = self.assert_shown(self.run_status())
        self.assertEqual(shown["pr-teeth"]["scopes"],
                         [("user", ["インストールされていない"]), ("project", ["0.5.1", "同じ", plugintest.OTHER_PROJECT])],
                         "user スコープに無いことを、ほかのスコープにあっても示すこと (R11)")
        self.assertEqual(shown["wording-guard"]["scopes"], [("user", ["インストールされていない"])])

    def test_user_and_other_scopes(self):
        self.set_installed(self.installed("doc-dag", "project", "0.1.0", enabled=False, project_path=plugintest.OTHER_PROJECT),
                           self.installed("doc-dag", "user", "0.2.0"),
                           self.installed("doc-dag", "local", "0.2.0", enabled=True, project_path=LOCAL_PROJECT))
        shown = self.assert_shown(self.run_status())
        self.assertEqual(shown["doc-dag"]["scopes"],
                         [("user", ["0.2.0", "同じ", "有効"]),
                          ("project", ["0.1.0", "古い", plugintest.OTHER_PROJECT]),
                          ("local", ["0.2.0", "同じ", LOCAL_PROJECT])],
                         "user スコープの行を先に、project / local スコープの行にはプロジェクトのパスを表示すること")
        for scope, values in shown["doc-dag"]["scopes"][1:]:
            with self.subTest(scope=scope):
                self.assertNotIn("有効", values, "project / local スコープの行には、有効か無効かを表示しないこと (KD6)")
                self.assertNotIn("無効", values, "project / local スコープの行には、有効か無効かを表示しないこと (KD6)")

    def test_disabled_in_user_scope(self):
        self.set_installed(self.installed("doc-dag", "user", "0.2.0", enabled=False), self.installed("pr-teeth", "user", "0.5.1"))
        shown = self.assert_shown(self.run_status())
        self.assertEqual(shown["doc-dag"]["scopes"], [("user", ["0.2.0", "同じ", "無効"])],
                         "user スコープの enabled が false のときは無効と表示すること (R10)")
        self.assertEqual(shown["pr-teeth"]["scopes"], [("user", ["0.5.1", "同じ", "有効"])])

    def test_other_elements_are_not_shown(self):
        self.set_installed(self.installed("doc-dag", "user", "0.2.0"), self.installed("wording-guard", "user", "0.28.0"),
                           self.installed("removed-plugin", "user", "0.1.0"),
                           {"id": "discord@claude-plugins-official", "scope": "user", "version": "0.0.4", "enabled": False})
        r = self.run_status("--plugins", "pr-teeth,doc-dag")
        shown = self.assert_shown(r)
        self.assertEqual(list(shown), ["doc-dag", "pr-teeth"], "--plugins で指定したものだけを、marketplace.json の順に表示すること")
        for name in ("wording-guard", "removed-plugin", "discord"):
            with self.subTest(name=name):
                self.assertNotIn(name, r.stdout,
                                 "ほかのマーケットプレイスの要素と、対象でないプラグインの要素は表示しないこと")

    def test_empty_plugin_list(self):
        shown = self.assert_shown(self.run_status())
        self.assertEqual(list(shown), NAMES)
        for name in NAMES:
            with self.subTest(name=name):
                self.assertEqual(shown[name]["scopes"], [("user", ["インストールされていない"])],
                                 "plugin list --json が空の配列のときは、すべてがインストールされていないと表示すること")

    def test_header_shows_marketplace_and_origin_main(self):
        r = self.run_status()
        self.assert_shown(r)
        self.assertIn(MP, r.stdout.splitlines()[0], "最初の行にマーケットプレイスの名前を表示すること")
        self.assertIn(self.origin_main_sha()[:12], r.stdout, "最新の版を読んだ origin/main のコミットを表示すること")

    def test_summary_of_user_scope(self):
        self.set_installed(self.installed("doc-dag", "user", "0.1.0", enabled=False),
                           self.installed("pr-teeth", "project", "0.5.0", project_path=plugintest.OTHER_PROJECT),
                           self.installed("wording-guard", "user", "0.27.9"))
        lines = self.run_status().stdout.splitlines()
        self.assertIn("user スコープの版が最新の版より古いもの: doc-dag, wording-guard", lines)
        self.assertIn("user スコープにインストールされていないもの: pr-teeth", lines,
                      "project スコープにだけあるものも、user スコープに無いものとして挙げること")
        self.assertIn("user スコープで無効なもの: doc-dag", lines)

    def test_summary_when_nothing_to_report(self):
        self.set_installed(*(self.installed(name, "user", version) for name, version in PUBLISHED))
        lines = self.run_status().stdout.splitlines()
        for label in ("user スコープの版が最新の版より古いもの", "user スコープにインストールされていないもの",
                      "user スコープで無効なもの"):
            with self.subTest(label=label):
                self.assertIn(f"{label}: なし", lines, "当てはまるものが無いときは「なし」と表示すること")


class StatusReadOnlyTest(StatusTestCase):
    """状況の表示は何も変えず、古いものがあっても終了コード 0 で終了する (R12・KD18)。"""

    def test_outdated_exits_zero_with_only_reads(self):
        self.set_installed(self.installed("doc-dag", "user", "0.1.0"),
                           self.installed("pr-teeth", "project", "0.4.0", project_path=plugintest.OTHER_PROJECT))
        before = self.read_state()
        shown = self.assert_shown(self.run_status())
        self.assertEqual(shown["doc-dag"]["scopes"][0][1][1], "古い")
        records = self.read_record()
        self.assertEqual(sorted(e["args"] for e in records), sorted(plugintest.READ_COMMANDS),
                         "plugin marketplace list と plugin list を 1 回ずつ実行し、ほかの claude のコマンドを実行しないこと")
        self.assertEqual(self.read_state(), before, "インストール済みのプラグインもマーケットプレイスの clone も変えないこと")


class AutoUpdateNoteTest(StatusTestCase):
    """表示の最後の、自動更新の案内 (R21・KD22)。"""

    def test_note_at_end(self):
        self.set_installed(self.installed("doc-dag", "user", "0.1.0"))
        r = self.run_status()
        self.assert_shown(r)
        lines = r.stdout.rstrip("\n").splitlines()
        self.assertIn(AUTO_UPDATE_DOC_URL, lines[-1], "最後の行に公式ドキュメントの URL を表示すること")
        last_scope = max(i for i, line in enumerate(lines) if _SCOPE_RE.match(line))
        note = "\n".join(lines[last_scope + 1:])
        for fragment in ("自動更新", f"マーケットプレイス {MP}", "/plugin", "Marketplaces タブ", "「Update marketplace」",
                         "有効と無効を切り替え"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, note, "プラグインの行より後ろに、自動更新を確認する方法を表示すること")

    def test_note_matches_readme(self):
        """案内の公式ドキュメントの URL と /plugin の画面の項目の名前が、README.md の手順にもあること。

        README.md の節「マーケットプレイスの自動更新を有効にする」は、利用者向けに同じ URL と項目の名前を書いている。
        片方だけを直したときに、ここで検出する。
        """
        r = self.run_status()
        self.assert_shown(r)
        note = r.stdout.rstrip("\n").splitlines()
        urls = re.findall(r"https://\S+", note[-1])
        items = re.findall(r"「([^」]+)」", r.stdout) + re.findall(r"([A-Za-z]+) タブ", r.stdout)
        self.assertTrue(urls and items, f"案内から URL と項目の名前を取り出せること: {r.stdout}")
        with open(os.path.join(plugintest.REPO_ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        for fragment in urls + items:
            with self.subTest(fragment=fragment):
                # README.md の長い語や長い URL の一部として一致しないように、前後が英数字・- でないことも見る
                found = re.search(r"(?<![A-Za-z0-9-])" + re.escape(fragment) + r"(?![A-Za-z0-9-])", readme)
                self.assertTrue(found,
                                f"状況の表示の案内と README.md で、URL と項目の名前を同じにすること (README.md に無い: {fragment})")

    def test_note_uses_marketplace_name_from_marketplace_json(self):
        renamed = plugintest.marketplace_json(NAMES)
        renamed["name"] = "renamed-marketplace"
        plugintest.commit_source(self.source_tree, {".claude-plugin/marketplace.json": plugintest.dump_json(renamed)},
                                 "マーケットプレイスの名前を変える")
        plugintest.write_files(self.work, {".claude-plugin/marketplace.json": plugintest.dump_json(renamed)})
        self.write_state({"marketplaces": [dict(plugintest.REGISTERED[0], name="renamed-marketplace")]})
        r = self.run_status()
        self.assert_shown(r)
        self.assertIn("Marketplaces タブで renamed-marketplace を選ぶ", r.stdout,
                      "案内のマーケットプレイスの名前は、marketplace.json から読んだ値を使うこと")


class PluginListShapeTest(StatusTestCase):
    """claude plugin list --json の出力の形の誤りを、状況の表示を通して確認する (KTD7・KTD6)。"""

    USER = {"id": f"doc-dag@{MP}", "scope": "user", "version": "0.2.0", "enabled": True,
            "installPath": "/Users/example/.claude/plugins/cache/akm-claude-plugins/doc-dag/0.2.0"}

    def test_wrong_shapes_stop(self):
        cases = [
            ("配列でない", {"plugins": [self.USER]}),
            ("version", [plugintest.without(self.USER, "version")]),
            ("enabled", [plugintest.without(self.USER, "enabled")]),
            ("id が無い", [self.USER, {"scope": "user", "version": "1.0.0", "enabled": True}]),
        ]
        for fragment, elements in cases:
            with self.subTest(fragment=fragment):
                self.set_plugin_list_output(elements)
                self.assert_stopped_without_change(self.run_status(), fragment)

    def test_others_without_project_path_are_accepted(self):
        others = [
            # ほかのマーケットプレイスの project スコープの要素で、projectPath が無いもの
            {"id": "discord@claude-plugins-official", "scope": "project", "version": "0.0.4", "enabled": False,
             "installPath": "/Users/example/.claude/plugins/cache/claude-plugins-official/discord/0.0.4"},
            # ディレクトリ .claude/skills/ のプラグインの要素のように、このマーケットプレイスのものでなく、projectPath も版も無いもの
            {"id": "local-skill@local", "scope": "local", "enabled": True},
        ]
        self.set_plugin_list_output(others + [self.USER])
        shown = self.assert_shown(self.run_status())
        self.assertEqual(shown["doc-dag"]["scopes"], [("user", ["0.2.0", "同じ", "有効"])],
                         "このマーケットプレイスでない要素は、キーが足りなくてもエラーにしないこと")

    def test_installed_version_must_be_x_y_z(self):
        for entry in (self.installed("doc-dag", "user", "1.0"),
                      self.installed("pr-teeth", "project", "0.6.0-alpha1", project_path=plugintest.OTHER_PROJECT)):
            with self.subTest(entry=entry):
                self.set_installed(entry)
                self.assert_stopped_without_change(self.run_status(), "X.Y.Z", entry["version"])


if __name__ == "__main__":
    unittest.main()
