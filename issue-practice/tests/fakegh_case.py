"""テストで偽の `gh` (ファイル `issue-practice/tests/fake-gh`) を使うための基底クラス。

PATH の先頭に偽の `gh` のディレクトリを加え、環境変数で振る舞いを決める。実物の `gh` は使わない。
プラグイン issue-dispatch のファイル `issue-dispatch/tests/test_project.py` のクラス `FakeGhCase` と同じ形。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
ENTRY = os.path.join(SCRIPTS, "issue_practice.py")
FAKE = os.path.join(HERE, "fake-gh")
FIXTURES = os.path.join(HERE, "fixtures", "gh")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_ENV_KEYS = ("PATH", "FAKE_GH_ARGS", "FAKE_GH_RESPONSES", "FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT")


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
        for k in ("FAKE_GH_MODE", "FAKE_GH_SLEEP", "FAKE_GH_EXIT"):
            os.environ.pop(k, None)
        self.responses([])

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

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
