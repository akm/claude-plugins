"""テストの基底クラス。

保存先のディレクトリ (環境変数 DISK_USAGE_TRIAGE_HOME。計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD2) と、
利用者のホームディレクトリ (環境変数 HOME。設定の `~` で始まるパスを展開する先) を、テストごとの一時ディレクトリにする。
手元の `~/.claude/disk-usage-triage/` とホームディレクトリは、読みも書きもしない。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
ENTRY = os.path.join(SCRIPTS, "disk_usage_triage.py")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_ENV_KEYS = ("DISK_USAGE_TRIAGE_HOME", "HOME")


class TriageCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        self.home = os.path.join(self.root, "home")  # 保存先のディレクトリ。作らずに始める
        os.environ["DISK_USAGE_TRIAGE_HOME"] = self.home
        self.user_home = self.make_dir("user-home")  # 利用者のホームディレクトリ
        os.environ["HOME"] = self.user_home

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def make_dir(self, *parts):
        """一時ディレクトリの下にディレクトリを作り、その絶対パスを返す。"""
        path = os.path.join(self.root, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def home_files(self):
        """保存先のディレクトリのファイルの、相対パスと中身の対応 (書き込みが無かったことを比べるため)。"""
        result = {}
        for directory, _, names in os.walk(self.home):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, encoding="utf-8", errors="surrogateescape") as f:
                    result[os.path.relpath(path, self.home)] = f.read()
        return result

    def read_home(self, name):
        with open(os.path.join(self.home, name), encoding="utf-8") as f:
            return json.load(f)

    def write_home_text(self, name, text):
        path = os.path.join(self.home, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def write_home(self, name, data):
        self.write_home_text(name, json.dumps(data, ensure_ascii=False))

    def cli(self, *args, env=None):
        """CLI の入口をサブプロセスで実行する。返り値は (終了コード, 標準出力を JSON として読んだ値か None, 標準エラー出力)。"""
        completed = subprocess.run([sys.executable, ENTRY, *args], capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, env=dict(os.environ) if env is None else env)
        try:
            payload = json.loads(completed.stdout) if completed.stdout.strip() else None
        except ValueError:
            payload = None
        return completed.returncode, payload, completed.stderr
