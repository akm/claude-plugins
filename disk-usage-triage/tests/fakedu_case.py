"""テストで偽の du (ファイル `disk-usage-triage/tests/fakebin/du`) を使うための基底クラス。

クラス `TriageCase` (ファイル `disk-usage-triage/tests/triage_case.py`) に、偽の du を起動するシェルスクリプトのパスを環境変数
DISK_USAGE_TRIAGE_DU に設定する処理と、偽の du の応答を決める関数・受けた引数を読む関数を足したもの。実際の du は使わない。
形は、プラグイン gh-notification-dispatch のファイル `gh-notification-dispatch/tests/fakegh_case.py` のクラス `FakeGhCase` に
ならう。

偽の du は、テストを実行している Python (`sys.executable`) で起動する。偽の du の 1 行目 (`#!/usr/bin/env python3`) に任せると、
PATH の `python3` が asdf の shim のとき、TriageCase が環境変数 HOME を一時ディレクトリに変えているので、shim が版を決められずに
起動に失敗するため。
"""

import json
import os
import shlex
import sys

from triage_case import HERE, TriageCase

FAKE_DU = os.path.join(HERE, "fakebin", "du")
FIXTURES = os.path.join(HERE, "fixtures", "du")

_ENV_KEYS = ("DISK_USAGE_TRIAGE_DU", "FAKE_DU_RESPONSES", "FAKE_DU_ARGS", "FAKE_DU_FIXTURES", "LC_ALL")


def fixture(name, kind="stdout"):
    """固定データ <name>.<kind> の中身。"""
    with open(os.path.join(FIXTURES, f"{name}.{kind}"), encoding="utf-8") as f:
        return f.read()


def du_args(path):
    """モジュール scan が du に渡す引数 (計画の KTD4)。"""
    return ["-k", "-d", "1", path]


class FakeDuCase(TriageCase):

    def setUp(self):
        super().setUp()
        self._du_saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        self.du_args_file = os.path.join(self.root, "du-args.jsonl")
        self.du_responses_file = os.path.join(self.root, "du-responses.json")
        self.du_command = os.path.join(self.make_dir("fake-du-bin"), "du")
        with open(self.du_command, "w", encoding="utf-8") as f:
            f.write(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(FAKE_DU)} "$@"\n')
        os.chmod(self.du_command, 0o755)
        os.environ["DISK_USAGE_TRIAGE_DU"] = self.du_command
        os.environ["FAKE_DU_ARGS"] = self.du_args_file
        os.environ["FAKE_DU_RESPONSES"] = self.du_responses_file
        os.environ.pop("FAKE_DU_FIXTURES", None)
        self.du_responses([])

    def tearDown(self):
        for k, v in self._du_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def du_responses(self, entries):
        """偽の du の応答の指定を書く (要素のキーは、ファイル fakebin/du の docstring)。"""
        with open(self.du_responses_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

    def du_calls(self):
        """偽の du が受けた呼び出しの配列。要素は {"args", "lc_all"}。"""
        if not os.path.exists(self.du_args_file):
            return []
        with open(self.du_args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
