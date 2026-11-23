#!/usr/bin/env python3
"""設定 (ファイル `disk-usage-triage/scripts/disk_usage_triage/config.py`) と、サブコマンド `config show`・`config set` のテスト。

計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U2 のテストシナリオと、U2 を実装するときに利用者と決めたこと
(2026-11-23): `config set` は入力の内容で設定の全体を置き換え、省いた時間の上限は 300 を書く。`scan_dirs` と `project_dirs` は
1 つ以上。`scan_dirs` の重複と入れ子は誤り。パスは `~` か `~/` で始まるものと絶対パスだけを受け付け、書いたとおりに保存する。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import json
import os
import unittest
from unittest import mock

from triage_case import TriageCase

from disk_usage_triage import config, store  # noqa: E402

CONFIG = "config.json"


class ConfigCase(TriageCase):

    def setUp(self):
        super().setUp()
        self.caches = self.make_dir("user-home", "Library", "Caches")
        self.asdf = self.make_dir("user-home", ".asdf")
        self.workspace = self.make_dir("user-home", "workspace")
        self.inputs = self.make_dir("input")  # 入力のファイル。保存先のディレクトリの外に置き、書き込みの有無と分ける

    def write_input(self, data, name="config-set.json"):
        path = os.path.join(self.inputs, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        return path

    def config_set(self, data):
        return self.cli("config", "set", "--input-file", self.write_input(data))

    def valid_input(self, **changes):
        data = {"scan_dirs": ["~/Library/Caches", "~/.asdf"], "project_dirs": ["~/workspace"]}
        data.update(changes)
        return data

    def assert_rejected(self, data, *fragments):
        """入力を誤りにし、保存先のディレクトリに何も書かないこと。"""
        before = self.home_files()
        code, payload, stderr = self.config_set(data)
        self.assertEqual(code, 3, stderr)
        self.assertIsNone(payload["config"])
        self.assertTrue(payload["errors"])
        text = "\n".join(payload["errors"])
        for fragment in fragments:
            self.assertIn(fragment, text)
        self.assertEqual(self.home_files(), before, "保存しないこと")
        return payload


class ConfigShowTest(ConfigCase):

    def test_missing_config_is_not_an_error(self):
        """設定が無いとき、終了コード 0 で、設定が無いことを出力する (計画の R1・KTD2)。"""
        code, payload, stderr = self.cli("config", "show")
        self.assertEqual(code, 0, stderr)
        self.assertFalse(payload["exists"])
        self.assertIsNone(payload["config"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["path"], os.path.join(self.home, CONFIG))
        self.assertEqual(payload["inputs_dir"], os.path.join(self.home, "inputs"))
        self.assertFalse(os.path.exists(self.home), "表示するだけでは、保存先のディレクトリを作らないこと")

    def test_existing_config(self):
        stored = {"version": 1, "scan_dirs": ["~/Library/Caches"], "project_dirs": ["~/workspace"],
                  "timeout_seconds": 600}
        self.write_home(CONFIG, stored)
        code, payload, stderr = self.cli("config", "show")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["config"], {"scan_dirs": ["~/Library/Caches"], "project_dirs": ["~/workspace"],
                                             "timeout_seconds": 600}, "version を除いた、config set の入力と同じ形")

    def test_does_not_check_directories_exist(self):
        """保存した後でディレクトリが無くなっても、表示はできる (ディレクトリがあるかは config set のときだけ確認する)。"""
        self.write_home(CONFIG, {"version": 1, "scan_dirs": ["/no/such/dir"], "project_dirs": ["~/gone"],
                                 "timeout_seconds": 300})
        code, payload, _ = self.cli("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(payload["config"]["scan_dirs"], ["/no/such/dir"])


BROKEN = {
    "JSON として読めない": "{",
    "オブジェクトでない": "[]",
    "version が 1 でない": '{"version": 2, "scan_dirs": ["~/a"], "project_dirs": ["~/b"], "timeout_seconds": 300}',
    "知らないキー": '{"version": 1, "scan_dirs": ["~/a"], "project_dirs": ["~/b"], "timeout_seconds": 300, "x": 1}',
    "キーが無い": '{"version": 1, "scan_dirs": ["~/a"], "project_dirs": ["~/b"]}',
    "配列でない": '{"version": 1, "scan_dirs": "~/a", "project_dirs": ["~/b"], "timeout_seconds": 300}',
    "空の配列": '{"version": 1, "scan_dirs": [], "project_dirs": ["~/b"], "timeout_seconds": 300}',
    "相対パス": '{"version": 1, "scan_dirs": ["a"], "project_dirs": ["~/b"], "timeout_seconds": 300}',
    "時間の上限が 0": '{"version": 1, "scan_dirs": ["~/a"], "project_dirs": ["~/b"], "timeout_seconds": 0}',
    "時間の上限が最大値を超える": '{"version": 1, "scan_dirs": ["~/a"], "project_dirs": ["~/b"], "timeout_seconds": 86401}',
    "時間の上限が真偽値": '{"version": 1, "scan_dirs": ["~/a"], "project_dirs": ["~/b"], "timeout_seconds": true}',
}


class BrokenConfigTest(ConfigCase):
    """壊れた config.json があると、config show と config set は終了コード 3 で返し、ファイルを変えない (計画の KTD2)。"""

    def test_show_and_set_refuse(self):
        for label, text in BROKEN.items():
            with self.subTest(label):
                self.write_home_text(CONFIG, text)
                before = self.home_files()
                code, payload, stderr = self.cli("config", "show")
                self.assertEqual(code, 3, stderr)
                self.assertTrue(payload["exists"])
                self.assertIsNone(payload["config"])
                self.assertIn(os.path.join(self.home, CONFIG), "\n".join(payload["errors"]), "壊れたファイルのパスを示すこと")
                code, payload, stderr = self.config_set(self.valid_input())
                self.assertEqual(code, 3, stderr)
                self.assertIn(os.path.join(self.home, CONFIG), "\n".join(payload["errors"]))
                self.assertEqual(self.home_files(), before, "ファイルを変えないこと")

    def test_broken_config_and_invalid_input_are_both_reported(self):
        self.write_home_text(CONFIG, "{")
        _, payload, _ = self.config_set(self.valid_input(scan_dirs=["relative"]))
        text = "\n".join(payload["errors"])
        self.assertIn("relative", text)
        self.assertIn(os.path.join(self.home, CONFIG), text)


class ConfigSetPathTest(ConfigCase):

    def test_saves_absolute_and_tilde_paths_without_expanding(self):
        """絶対パスと ~ で始まるパスを受け付け、~ を展開せずに保存する (計画の U2・KTD3)。"""
        code, payload, stderr = self.config_set({"scan_dirs": ["~/Library/Caches", self.asdf],
                                                 "project_dirs": ["~"]})
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["errors"], [])
        expected = {"scan_dirs": ["~/Library/Caches", self.asdf], "project_dirs": ["~"], "timeout_seconds": 300}
        self.assertEqual(payload["config"], expected)
        self.assertIsNone(payload["previous"])
        self.assertEqual(payload["path"], os.path.join(self.home, CONFIG))
        self.assertEqual(self.read_home(CONFIG), {"version": 1, **expected})

    def test_saves_paths_as_written(self):
        """末尾の / や途中の .. を直さずに、書いたとおりに保存する。"""
        written = ["~/Library/Caches/", "~/workspace/../.asdf"]
        code, payload, stderr = self.config_set(self.valid_input(scan_dirs=written))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.read_home(CONFIG)["scan_dirs"], written)

    def test_rejects_relative_path(self):
        self.assert_rejected(self.valid_input(scan_dirs=["Library/Caches"]), "Library/Caches", "相対パス")
        self.assert_rejected(self.valid_input(project_dirs=["./workspace"]), "./workspace", "相対パス")

    def test_rejects_other_users_home(self):
        """~ の後に利用者名を書いたパス (ほかの利用者のホームディレクトリ) は受け付けない。"""
        self.assert_rejected(self.valid_input(scan_dirs=["~root/Library"]), "~root/Library")
        self.assert_rejected(self.valid_input(project_dirs=["~root"]), "~root")

    def test_rejects_missing_directory(self):
        self.assert_rejected(self.valid_input(scan_dirs=["~/no-such-dir"]), "~/no-such-dir", "存在しない")
        self.assert_rejected(self.valid_input(project_dirs=[os.path.join(self.root, "nothing")]), "存在しない")

    def test_rejects_non_directory(self):
        path = os.path.join(self.user_home, "file.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        self.assert_rejected(self.valid_input(scan_dirs=["~/file.txt"]), "~/file.txt", "ディレクトリでない")
        self.assert_rejected(self.valid_input(scan_dirs=["~/file.txt/sub"]), "~/file.txt/sub", "存在しない")

    def test_accepts_symlink_to_directory(self):
        os.symlink(self.caches, os.path.join(self.user_home, "caches-link"))
        code, _, stderr = self.config_set(self.valid_input(scan_dirs=["~/caches-link"]))
        self.assertEqual(code, 0, stderr)

    def test_rejects_empty_or_non_string_paths(self):
        self.assert_rejected(self.valid_input(scan_dirs=[""]), "空")
        self.assert_rejected(self.valid_input(scan_dirs=[1]), "文字列でない")
        self.assert_rejected(self.valid_input(project_dirs=[None]), "文字列でない")
        self.assert_rejected(self.valid_input(scan_dirs=["~/a\u0000b"]), "NUL")

    def test_reports_every_invalid_path(self):
        payload = self.assert_rejected(self.valid_input(scan_dirs=["relative", "~/no-such-dir"]))
        self.assertEqual(len(payload["errors"]), 2, payload["errors"])
        self.assertIn("scan_dirs[0]", payload["errors"][0])
        self.assertIn("scan_dirs[1]", payload["errors"][1])


class ConfigSetArrayTest(ConfigCase):

    def test_arrays_need_at_least_one_directory(self):
        self.assert_rejected(self.valid_input(scan_dirs=[]), "scan_dirs")
        self.assert_rejected(self.valid_input(project_dirs=[]), "project_dirs")

    def test_rejects_duplicate_scan_dirs(self):
        """同じディレクトリを指す調べるディレクトリは、書き方が違っても誤りにする。"""
        self.assert_rejected(self.valid_input(scan_dirs=["~/.asdf", "~/.asdf"]), "同じディレクトリ")
        self.assert_rejected(self.valid_input(scan_dirs=["~/.asdf", self.asdf]), "同じディレクトリ")
        os.symlink(self.asdf, os.path.join(self.user_home, "asdf-link"))
        self.assert_rejected(self.valid_input(scan_dirs=["~/asdf-link", "~/.asdf"]), "同じディレクトリ")

    def test_rejects_nested_scan_dirs(self):
        """一方が他方の下にある調べるディレクトリは誤りにする (順序を問わない)。"""
        self.assert_rejected(self.valid_input(scan_dirs=["~", "~/Library/Caches"]), "下にある")
        self.assert_rejected(self.valid_input(scan_dirs=["~/Library/Caches", "~/Library"]), "下にある")

    def test_nested_through_symlink(self):
        """シンボリックリンクを経由して一方が他方の下にある調べるディレクトリも誤りにする。"""
        os.symlink(os.path.join(self.user_home, "Library"), os.path.join(self.user_home, "lib-link"))
        self.assert_rejected(self.valid_input(scan_dirs=["~/lib-link", "~/Library/Caches"]), "下にある")

    def test_case_only_difference_on_case_insensitive_fs(self):
        """大文字小文字を区別しないファイルシステム (macOS の標準) では、大文字小文字だけが違う書き方も同じディレクトリとする。"""
        if not os.path.isdir(os.path.join(self.user_home, "library", "caches")):
            self.skipTest("一時ディレクトリが大文字小文字を区別するファイルシステムにある")
        self.assert_rejected(self.valid_input(scan_dirs=["~/Library/Caches", "~/library/caches"]), "同じディレクトリ")
        self.assert_rejected(self.valid_input(scan_dirs=["~/library", "~/Library/Caches"]), "下にある")
        self.assert_rejected(self.valid_input(scan_dirs=["~/Library/Caches", "~/library"]), "下にある")

    def test_sibling_with_common_prefix_is_not_nested(self):
        self.make_dir("user-home", "Library", "CachesOld")
        code, _, stderr = self.config_set(self.valid_input(scan_dirs=["~/Library/Caches", "~/Library/CachesOld"]))
        self.assertEqual(code, 0, stderr)

    def test_project_dirs_may_overlap(self):
        code, _, stderr = self.config_set(self.valid_input(project_dirs=["~", "~/workspace", self.workspace]))
        self.assertEqual(code, 0, stderr)


class ConfigSetShapeTest(ConfigCase):
    """知らないキー・型の違う値を含む入力は、終了コード 3 で返し、保存しない (計画の U2・KTD3)。"""

    def test_unknown_keys(self):
        self.assert_rejected(self.valid_input(extra=1), "extra")
        self.assert_rejected(self.valid_input(version=1), "version")

    def test_missing_keys(self):
        self.assert_rejected({"scan_dirs": ["~/.asdf"]}, "project_dirs")
        self.assert_rejected({"project_dirs": ["~/workspace"]}, "scan_dirs")

    def test_wrong_types(self):
        self.assert_rejected(self.valid_input(scan_dirs="~/.asdf"), "scan_dirs", "配列でない")
        self.assert_rejected(self.valid_input(timeout_seconds="300"), "timeout_seconds")
        self.assert_rejected(self.valid_input(timeout_seconds=1.5), "timeout_seconds")
        self.assert_rejected(self.valid_input(timeout_seconds=True), "timeout_seconds")
        self.assert_rejected(self.valid_input(timeout_seconds=None), "timeout_seconds")

    def test_input_must_be_object(self):
        self.assert_rejected([], "オブジェクトでない")
        self.assert_rejected("{", "JSON として読めない")

    def test_missing_input_file(self):
        code, payload, stderr = self.cli("config", "set", "--input-file", os.path.join(self.inputs, "none.json"))
        self.assertEqual(code, 3, stderr)
        self.assertIn("none.json", payload["errors"][0])
        self.assertFalse(os.path.exists(self.home))

    def test_invalid_input_creates_nothing(self):
        self.assert_rejected(self.valid_input(scan_dirs=["relative"]))
        self.assertFalse(os.path.exists(self.home), "誤りがあれば、保存先のディレクトリも作らないこと")


class ConfigSetTimeoutTest(ConfigCase):

    def test_default_is_300(self):
        """時間の上限を省くと 300 秒になり、その値を config.json に書く (計画の R4)。"""
        code, payload, stderr = self.config_set(self.valid_input())
        self.assertEqual(code, 0, stderr)
        self.assertEqual(config.DEFAULT_TIMEOUT_SECONDS, 300)
        self.assertEqual(payload["config"]["timeout_seconds"], 300)
        self.assertEqual(self.read_home(CONFIG)["timeout_seconds"], 300)

    def test_explicit_value(self):
        code, payload, stderr = self.config_set(self.valid_input(timeout_seconds=600))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.read_home(CONFIG)["timeout_seconds"], 600)

    def test_upper_bound(self):
        """時間の上限は 86,400 秒 (1 日) 以下 (計画の R4)。macOS では、約 24.8 日を超える値を subprocess に渡すと例外になる。"""
        self.assertEqual(config.MAX_TIMEOUT_SECONDS, 86400)
        code, _, stderr = self.config_set(self.valid_input(timeout_seconds=86400))
        self.assertEqual(code, 0, stderr)
        self.assert_rejected(self.valid_input(timeout_seconds=86401), "timeout_seconds", "86400")

    def test_zero_or_negative_is_rejected(self):
        self.assert_rejected(self.valid_input(timeout_seconds=0), "timeout_seconds")
        self.assert_rejected(self.valid_input(timeout_seconds=-1), "timeout_seconds")


class ConfigSetReplaceTest(ConfigCase):

    def test_replaces_whole_config(self):
        """config set は、入力の内容で設定の全体を置き換える。省いた時間の上限は、前の値ではなく 300 になる。"""
        self.config_set(self.valid_input(timeout_seconds=600))
        code, payload, stderr = self.config_set({"scan_dirs": ["~/.asdf"], "project_dirs": ["~"]})
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["previous"], {"scan_dirs": ["~/Library/Caches", "~/.asdf"],
                                               "project_dirs": ["~/workspace"], "timeout_seconds": 600})
        self.assertEqual(self.read_home(CONFIG), {"version": 1, "scan_dirs": ["~/.asdf"], "project_dirs": ["~"],
                                                  "timeout_seconds": 300})


class HomeEnvTest(ConfigCase):

    def test_writes_under_env_home(self):
        """環境変数 DISK_USAGE_TRIAGE_HOME を設定すると、その下に書く (計画の KTD2)。"""
        other = os.path.join(self.root, "other-home")
        os.environ["DISK_USAGE_TRIAGE_HOME"] = other
        code, payload, stderr = self.config_set(self.valid_input())
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["path"], os.path.join(other, CONFIG))
        self.assertTrue(os.path.isfile(os.path.join(other, CONFIG)))
        self.assertFalse(os.path.exists(self.home))
        self.assertFalse(os.path.exists(os.path.join(self.user_home, ".claude")), "ホームディレクトリの下に書かないこと")


class AtomicWriteTest(ConfigCase):

    def test_failed_write_keeps_original(self):
        """書き込みが途中で失敗しても、元の config.json が壊れない (一時ファイルの名前を変える前に例外を起こす)。"""
        original = {"version": 1, "scan_dirs": ["~/.asdf"], "project_dirs": ["~"], "timeout_seconds": 600}
        self.write_home(CONFIG, original)
        path = self.write_input(self.valid_input())
        with mock.patch.object(store.os, "replace", side_effect=OSError("名前を変える前の失敗")):
            with self.assertRaises(OSError):
                config.set_from_file(path)
        self.assertEqual(self.read_home(CONFIG), original)
        self.assertEqual(sorted(os.listdir(self.home)), [CONFIG, store.LOCK], "一時ファイルを残さないこと")


if __name__ == "__main__":
    unittest.main()
