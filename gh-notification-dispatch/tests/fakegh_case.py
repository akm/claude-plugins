"""テストで偽の `gh` (ファイル `gh-notification-dispatch/tests/fake-gh`) を使うための基底クラス。

PATH の先頭に偽の `gh` のディレクトリを加え、環境変数で振る舞いを決める。実物の `gh` は使わない。
プラグイン issue-practice のファイル `issue-practice/tests/fakegh_case.py` のクラス `FakeGhCase` と同じ形に、記録のディレクトリ
(環境変数 GH_NOTIFICATION_DISPATCH_HOME)・一時ディレクトリ (TMPDIR)・実行しているセッションの ID
(CLAUDE_CODE_HOST_SESSION_ID)・今の時刻 (GH_NOTIFICATION_DISPATCH_NOW) を、テストごとの値にする処理を足したもの。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
ENTRY = os.path.join(SCRIPTS, "gh_notification_dispatch.py")
FAKE = os.path.join(HERE, "fake-gh")
FIXTURES = os.path.join(HERE, "fixtures", "gh")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_ENV_KEYS = ("PATH", "FAKE_GH_ARGS", "FAKE_GH_RESPONSES", "FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT",
             "GH_NOTIFICATION_DISPATCH_HOME", "GH_NOTIFICATION_DISPATCH_NOW", "CLAUDE_CODE_HOST_SESSION_ID", "TMPDIR")


def fixture(name, kind="stdout"):
    with open(os.path.join(FIXTURES, f"{name}.{kind}"), encoding="utf-8") as f:
        return f.read()


def fixture_json(name):
    return json.loads(fixture(name))


class FakeGhCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        os.symlink(FAKE, os.path.join(self.bin, "gh"))
        self.args_file = os.path.join(self.root, "args.jsonl")
        self.responses_file = os.path.join(self.root, "responses.json")
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_GH_ARGS"] = self.args_file
        os.environ["FAKE_GH_RESPONSES"] = self.responses_file
        for k in ("FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT", "GH_NOTIFICATION_DISPATCH_NOW",
                  "CLAUDE_CODE_HOST_SESSION_ID"):
            os.environ.pop(k, None)
        self.home = os.path.join(self.root, "home")  # 記録のディレクトリ。作らずに始める
        self.tmpdir = os.path.join(self.root, "tmp")
        os.makedirs(self.tmpdir)
        os.environ["GH_NOTIFICATION_DISPATCH_HOME"] = self.home
        os.environ["TMPDIR"] = self.tmpdir
        self.responses([])

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def as_session(self, session_id):
        """スクリプトを実行するセッションの ID を決める。None なら環境変数を消す。"""
        if session_id is None:
            os.environ.pop("CLAUDE_CODE_HOST_SESSION_ID", None)
        else:
            os.environ["CLAUDE_CODE_HOST_SESSION_ID"] = session_id

    def at(self, time_text):
        """今の時刻を決める (YYYY-MM-DDTHH:MM:SSZ)。"""
        os.environ["GH_NOTIFICATION_DISPATCH_NOW"] = time_text

    def home_files(self):
        """記録のディレクトリのファイルの、相対パスと中身の対応 (書き込みが無かったことを比べるため)。"""
        result = {}
        for directory, _, names in os.walk(self.home):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, encoding="utf-8") as f:
                    result[os.path.relpath(path, self.home)] = f.read()
        return result

    def read_home(self, name):
        with open(os.path.join(self.home, name), encoding="utf-8") as f:
            return json.load(f)

    def write_home(self, name, data):
        path = os.path.join(self.home, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def responses(self, entries):
        with open(self.responses_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

    def recorded_full(self):
        if not os.path.exists(self.args_file):
            return []
        with open(self.args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def recorded(self):
        return [r["args"] for r in self.recorded_full()]

    def cli(self, *args, stdin=None):
        """CLI の入口をサブプロセスで実行する。返り値は (終了コード, 標準出力を JSON として読んだ値か None, 標準エラー出力)。"""
        completed = subprocess.run([sys.executable, ENTRY, *args], capture_output=True, text=True, input=stdin,
                                   env=dict(os.environ))
        try:
            payload = json.loads(completed.stdout) if completed.stdout.strip() else None
        except ValueError:
            payload = None
        return completed.returncode, payload, completed.stderr
