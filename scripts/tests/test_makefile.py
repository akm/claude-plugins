#!/usr/bin/env python3
"""リポジトリのルートの Makefile のテスト。

標準ライブラリの unittest と、make (GNU Make 3.81 以上) で動く。

  python3 -m unittest discover -s scripts/tests

Makefile とスクリプト scripts/plugins.py を作業用のリポジトリにコピーし、make をプロセスとして実行する。本物の claude は
実行せず、GitHub に接続しない (共通の準備はファイル scripts/tests/plugintest.py)。make は、ファイル
scripts/tests/test_status.py と scripts/tests/test_install.py のテストと同じ偽の claude と一時的なリポジトリで動かす。

このファイルの R・KD・KTD の番号は、計画のファイル docs/plans/2026-11-02-1748-feat-plugin-install-status-plan.md の
Requirements (R)・Key Decisions (KD)・Key Technical Decisions (KTD) の番号。
"""

import os
import shutil
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import plugintest  # noqa: E402
import test_install  # noqa: E402
import test_status  # noqa: E402

MAKEFILE_REL = "Makefile"
# make の親のプロセスから受け継ぐと、コマンドラインの変数として扱われる環境変数。テストの make には持ち込まない
MAKE_ENV_VARS = ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "MAKEFILES", "PLUGINS")


class MakeMixin:
    """Makefile を作業用のリポジトリにコピーし、make を実行する。plugintest.PluginTestCase を継承したクラスと一緒に継承する。"""

    def setUp(self):
        super().setUp()
        self.copy_into_work([MAKEFILE_REL])
        self.other = os.path.join(self.root, "other")
        os.makedirs(self.other)

    def run_make(self, *args, cwd=None, env=None):
        """make を実行する。cwd を省略したときは、作業用のリポジトリとは別のディレクトリ self.other で実行する。

        環境変数は self.env から MAKE_ENV_VARS を消したもの。env を渡すと、その値を足す。
        """
        run_env = {k: v for k, v in self.env.items() if k not in MAKE_ENV_VARS}
        run_env.update(env or {})
        return subprocess.run(["make", *args], env=run_env, cwd=cwd or self.other, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=plugintest.TIMEOUT)


class MakefileStatusTest(MakeMixin, test_status.StatusTestCase):
    """ターゲット plugins-status と変数 PLUGINS (KTD11)。"""

    def shown_names(self, r):
        self.assertEqual(r.returncode, 0, f"make が終了コード 0 で終了すること: {r.stderr}")
        return list(test_status.parse_status(r.stdout))

    def test_make_c_from_other_directory(self):
        r = self.run_make("-C", self.work, "plugins-status")
        self.assertEqual(self.shown_names(r), test_status.NAMES)
        self.assertIn(self.origin_main_sha()[:12], r.stdout, "作業用のリポジトリの origin/main を読むこと")
        self.assert_only_reads()

    def test_script_path_comes_from_makefile_location(self):
        r = self.run_make("-f", os.path.join(self.work, MAKEFILE_REL), "plugins-status")
        self.assertEqual(self.shown_names(r), test_status.NAMES,
                         "make を実行したディレクトリではなく、Makefile のあるディレクトリのスクリプトを実行すること")
        self.assertIn(self.origin_main_sha()[:12], r.stdout)

    def copy_work_to_path_with_space(self):
        """作業用のリポジトリを、空白を含むパスのディレクトリにコピーし、そのパスを返す。"""
        spaced = os.path.join(self.root, "with space", "repo")
        shutil.copytree(self.work, spaced, symlinks=True)
        return spaced

    def test_repository_path_with_space(self):
        spaced = self.copy_work_to_path_with_space()
        for args, cwd in ((["-C", spaced], None), ([], spaced)):
            with self.subTest(args=args, cwd=cwd):
                r = self.run_make(*args, "plugins-status", cwd=cwd)
                self.assertEqual(self.shown_names(r), test_status.NAMES,
                                 "リポジトリのパスに空白があっても、make と make -C で状況を表示すること")
        self.assert_only_reads()

    def test_makefile_path_with_glob_characters_given_by_f(self):
        # make の $(wildcard) は proj[1] を proj1 などに一致するパターンとして扱う。一致する別のディレクトリを作っておく
        bracketed = os.path.join(self.root, "proj[1]", "repo")
        shutil.copytree(self.work, bracketed, symlinks=True)
        os.makedirs(os.path.join(self.root, "proj1", "repo"))
        r = self.run_make("-f", os.path.join(bracketed, MAKEFILE_REL), "plugins-status")
        self.assertEqual(self.shown_names(r), test_status.NAMES,
                         "パスに [ ] があり、そのパターンに一致する別のディレクトリがあっても、make -f で状況を表示すること")

    def test_makefile_path_with_space_given_by_f_fails_with_reason(self):
        spaced = self.copy_work_to_path_with_space()
        r = self.run_make("-f", os.path.join(spaced, MAKEFILE_REL), "plugins-status")
        self.assertNotEqual(r.returncode, 0, "空白を含むパスの Makefile を -f で指定したときは、終了コード 0 以外で終了すること")
        self.assertIn("空白", r.stderr, f"空白を含むパスでは動かないことを、エラーの文で示すこと: {r.stderr}")
        self.assertIn("make -C", r.stderr, "直し方として make -C を示すこと")
        self.assertEqual(self.read_record(), [], "claude を実行しないこと")

    def test_makefile_without_script_fails_with_reason(self):
        alone = os.path.join(self.root, "alone")
        os.makedirs(alone)
        shutil.copy(os.path.join(self.work, MAKEFILE_REL), alone)
        r = self.run_make("-f", os.path.join(alone, MAKEFILE_REL), "plugins-status")
        self.assertNotEqual(r.returncode, 0, "Makefile だけを別のディレクトリにコピーしたときは、終了コード 0 以外で終了すること")
        self.assertIn("リポジトリのルートの Makefile", r.stderr,
                      f"空白の無いパスでも、リポジトリのルートの Makefile を使うよう示すこと: {r.stderr}")
        self.assertEqual(self.read_record(), [], "claude を実行しないこと")

    def test_plugins_variable_limits_targets(self):
        cases = [("PLUGINS=wording-guard,doc-dag", ["doc-dag", "wording-guard"]),
                 ("PLUGINS=", test_status.NAMES)]
        for assignment, expected in cases:
            with self.subTest(assignment=assignment):
                r = self.run_make("-C", self.work, "plugins-status", assignment)
                self.assertEqual(self.shown_names(r), expected,
                                 "コマンドラインの PLUGINS で対象を絞り、空の値はすべてを対象にすること")

    def test_environment_variable_is_ignored(self):
        r = self.run_make("-C", self.work, "plugins-status", env={"PLUGINS": "doc-dag"})
        self.assertEqual(self.shown_names(r), test_status.NAMES, "環境変数の PLUGINS では対象を絞らないこと")

    def test_unknown_name_fails(self):
        r = self.run_make("-C", self.work, "plugins-status", "PLUGINS=no-such")
        self.assertNotEqual(r.returncode, 0, "載っていない名前を指定したら、make が終了コード 0 以外で終了すること")
        self.assertIn("no-such", r.stderr)
        self.assertIn(plugintest.NOTHING_CHANGED, r.stderr)
        self.assert_only_reads()


class MakefileInstallTest(MakeMixin, test_install.InstallTestCase):
    """ターゲット plugins-install と変数 PLUGINS (KTD11)。"""

    def test_plugins_variable_limits_targets(self):
        r = self.run_make("-C", self.work, "plugins-install", "PLUGINS=doc-dag")
        self.assertEqual(r.returncode, 0, f"make が終了コード 0 で終了すること: {r.stderr}")
        self.assertEqual(self.changes(), [test_install.UPDATE, test_install.install_args("doc-dag")],
                         "コマンドラインの PLUGINS で指定したものだけをインストールすること")
        self.assertEqual(self.user_versions(), {"doc-dag": "0.2.0"})


if __name__ == "__main__":
    unittest.main()
