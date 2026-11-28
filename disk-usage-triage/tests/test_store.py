#!/usr/bin/env python3
"""保存先のディレクトリの読み書き (ファイル `disk-usage-triage/scripts/disk_usage_triage/store.py`) のテスト。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

from triage_case import SCRIPTS, TriageCase

from disk_usage_triage import store  # noqa: E402

NAME = "example.json"


class HomeTest(TriageCase):

    def test_home_from_env(self):
        """環境変数 DISK_USAGE_TRIAGE_HOME を設定すると、その場所を使う (計画の KTD2)。"""
        self.assertEqual(store.home(), self.home)

    def test_default_home(self):
        os.environ.pop(store.HOME_ENV)
        self.assertEqual(store.home(), os.path.expanduser("~/.claude/disk-usage-triage"))

    def test_empty_env_is_default(self):
        os.environ[store.HOME_ENV] = ""
        self.assertEqual(store.home(), os.path.expanduser("~/.claude/disk-usage-triage"))

    def test_inputs_dir(self):
        """Claude が入力のファイルを書くディレクトリは、保存先のディレクトリの下の inputs (計画の KTD3)。"""
        self.assertEqual(store.inputs_dir(), os.path.join(self.home, "inputs"))


class ReadTest(TriageCase):
    """ファイルが無いことと、壊れていることを区別する (計画の KTD2)。"""

    def test_missing_is_none(self):
        self.assertIsNone(store.read(NAME))
        self.assertFalse(os.path.exists(self.home), "読むだけでは、保存先のディレクトリを作らないこと")

    def test_valid(self):
        self.write_home(NAME, {"version": 1, "value": "値"})
        self.assertEqual(store.read(NAME), {"version": 1, "value": "値"})

    def test_corrupt(self):
        cases = {
            "JSON として読めない": "{",
            "空のファイル": "",
            "オブジェクトでない": "[1, 2]",
            "version が無い": '{"value": 1}',
            "version が 1 でない": '{"version": 2}',
            "version が文字列": '{"version": "1"}',
            "version が真偽値": '{"version": true}',
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.write_home_text(NAME, text)
                with self.assertRaises(store.Corrupt) as caught:
                    store.read(NAME)
                self.assertEqual(caught.exception.path, os.path.join(self.home, NAME))
                self.assertIn(os.path.join(self.home, NAME), str(caught.exception), "壊れたファイルのパスを示すこと")

    def test_not_utf8_is_corrupt(self):
        os.makedirs(self.home)
        with open(os.path.join(self.home, NAME), "wb") as f:
            f.write(b'{"version": 1, "value": "\xff"}')
        with self.assertRaises(store.Corrupt):
            store.read(NAME)


class AtomicWriteTest(TriageCase):

    def test_write_creates_home(self):
        with store.transaction() as tx:
            tx.write(NAME, {"version": 1, "value": "値"})
        self.assertEqual(self.read_home(NAME), {"version": 1, "value": "値"})
        with open(os.path.join(self.home, NAME), encoding="utf-8") as f:
            self.assertIn("値", f.read(), "日本語をエスケープせずに書くこと")

    def test_path_not_utf8_round_trips(self):
        """UTF-8 として読めない名前のパス (surrogate のコードポイントを含む文字列) も書け、読むと元の文字列に戻る (計画の KTD2)。

        モジュール proc は、du の出力の UTF-8 として読めないバイトを surrogate のコードポイントにして残す。ファイルには、
        surrogate のコードポイントだけを JSON のエスケープにして書く。
        """
        data = {"version": 1, "path": "/Users/u/caf\udcff", "value": "値"}
        with store.transaction() as tx:
            tx.write(NAME, data)
        self.assertEqual(store.read(NAME), data)
        with open(os.path.join(self.home, NAME), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("caf\\udcff", text)
        self.assertIn("値", text, "日本語はエスケープしないこと")

    def test_dumps_escapes_only_surrogates(self):
        self.assertEqual(store.dumps({"a": "\udc80値\udcff"}), '{\n  "a": "\\udc80値\\udcff"\n}')

    def test_failed_replace_keeps_original(self):
        """一時ファイルの名前を変える前に例外が起きても、元のファイルが残り、一時ファイルも残らない。"""
        original = {"version": 1, "value": "元"}
        self.write_home(NAME, original)
        with mock.patch.object(store.os, "replace", side_effect=OSError("名前を変える前の失敗")):
            with self.assertRaises(OSError):
                with store.transaction() as tx:
                    tx.write(NAME, {"version": 1, "value": "新"})
        self.assertEqual(self.read_home(NAME), original)
        self.assertEqual(sorted(os.listdir(self.home)), [NAME, store.LOCK], "一時ファイルを残さないこと")

    def test_failed_serialization_keeps_original(self):
        original = {"version": 1, "value": "元"}
        self.write_home(NAME, original)
        with self.assertRaises(TypeError):
            with store.transaction() as tx:
                tx.write(NAME, {"version": 1, "value": object()})
        self.assertEqual(self.read_home(NAME), original)
        self.assertEqual(sorted(os.listdir(self.home)), [NAME, store.LOCK])


class LockTest(TriageCase):

    def test_concurrent_writers_are_serialized(self):
        """複数のプロセスが、ロックを取って読み、書き換え、書いても、書き込みが失われない。"""
        code = ("import sys, time; sys.path.insert(0, sys.argv[1]); from disk_usage_triage import store\n"
                "for _ in range(10):\n"
                "    with store.transaction() as tx:\n"
                "        data = tx.read('counter.json') or {'version': 1, 'count': 0}\n"
                "        time.sleep(0.005)\n"
                "        tx.write('counter.json', {'version': 1, 'count': data['count'] + 1})\n")
        processes = [subprocess.Popen([sys.executable, "-c", code, SCRIPTS], env=dict(os.environ)) for _ in range(4)]
        for p in processes:
            self.assertEqual(p.wait(timeout=60), 0)
        self.assertEqual(self.read_home("counter.json"), {"version": 1, "count": 40})

    def test_transaction_read_distinguishes_corrupt(self):
        self.write_home_text(NAME, "{")
        with store.transaction() as tx:
            with self.assertRaises(store.Corrupt):
                tx.read(NAME)
            self.assertIsNone(tx.read("missing.json"))


if __name__ == "__main__":
    unittest.main()
