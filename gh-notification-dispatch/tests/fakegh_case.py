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
             "GH_NOTIFICATION_DISPATCH_HOME", "GH_NOTIFICATION_DISPATCH_NOW", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_PID", "TMPDIR")


def fixture(name, kind="stdout"):
    with open(os.path.join(FIXTURES, f"{name}.{kind}"), encoding="utf-8") as f:
        return f.read()


def fixture_json(name):
    return json.loads(fixture(name))


def http(status, body=None, headers=None):
    """`gh api -i` の標準出力の形 (状態行・ヘッダ・空の行・本文) を作る。形は、2026-11-16 に実物の gh 2.103.3 で確認したもの。"""
    reason = {200: "OK", 304: "Not Modified", 403: "Forbidden", 404: "Not Found"}.get(status, "")
    lines = [f"HTTP/2.0 {status} {reason}", "Content-Type: application/json; charset=utf-8"]
    lines += [f"{name}: {value}" for name, value in (headers or {}).items()]
    text = "" if body is None else json.dumps(body, ensure_ascii=False)
    return "\n".join(lines) + "\n\n" + text


def notification(repo, number, updated_at, title="題名", unread=True, subject_type="PullRequest", reason="review_requested"):
    """API GET /notifications の要素。キーは 2026-11-16 に実物で確認した形で、値は公開してよいものにしている。"""
    kind = "pulls" if subject_type == "PullRequest" else "issues"
    return {"id": f"{number}{len(repo)}", "unread": unread, "reason": reason, "updated_at": updated_at,
            "last_read_at": None if unread else updated_at,
            "subject": {"title": title, "url": f"https://api.github.com/repos/{repo}/{kind}/{number}",
                        "latest_comment_url": None, "type": subject_type},
            "repository": {"full_name": repo, "name": repo.split("/")[1], "private": False},
            "url": f"https://api.github.com/notifications/threads/{number}",
            "subscription_url": f"https://api.github.com/notifications/threads/{number}/subscription"}


def timeline_event(event_id, created_at, login=None, team_id=None, event="review_requested", team_slug="reviewers"):
    """API GET /repos/{owner}/{repo}/issues/{number}/timeline の要素。キーは 2026-11-16 に公開のリポジトリで確認した形。"""
    item = {"id": event_id, "event": event, "created_at": created_at,
            "actor": {"login": "requester", "id": 1, "type": "User"},
            "review_requester": {"login": "requester", "id": 1, "type": "User"}}
    if login is not None:
        item["requested_reviewer"] = {"login": login, "id": 2, "type": "User"}
    if team_id is not None:
        item["requested_team"] = {"id": team_id, "name": team_slug, "slug": team_slug, "organization_id": 9}
    return item


def pull(repo, number, state="open", merged_at=None, title="題名", requested=(), teams=()):
    """API GET /repos/{owner}/{repo}/pulls/{number} の応答のうち、判定に使うキー。キーは 2026-11-16 に公開のリポジトリで
    確認した形。merged_at があれば、state は closed にする (マージされた PR は閉じている)。"""
    return {"number": number, "state": "closed" if merged_at else state, "title": title,
            "html_url": f"https://github.com/{repo}/pull/{number}", "merged": merged_at is not None, "merged_at": merged_at,
            "requested_reviewers": [{"login": login, "id": 2, "type": "User"} for login in requested],
            "requested_teams": [{"id": team_id, "name": f"team{team_id}", "slug": f"team{team_id}"} for team_id in teams],
            "base": {"repo": {"full_name": repo}}}


def review(login, review_id=1, state="APPROVED", submitted_at="2026-11-16T06:10:00Z"):
    """API GET /repos/{owner}/{repo}/pulls/{number}/reviews の要素のうち、判定に使うキー (GitHub の文書の形)。"""
    return {"id": review_id, "user": {"login": login, "id": 3, "type": "User"}, "state": state,
            "submitted_at": submitted_at}


def link_next(path, last_page=9):
    """ヘッダ Link の値 (rel="next" と rel="last")。path は API_ORIGIN を除いたパス。"""
    return f'<https://api.github.com/{path}>; rel="next", <https://api.github.com/{path}&last={last_page}>; rel="last"'


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
                  "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_PID"):
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

    def home_files(self, ignore_lock=False):
        """記録のディレクトリのファイルの、相対パスと中身の対応 (書き込みが無かったことを比べるため)。

        ignore_lock が真なら、ロックのファイル lock (中身は空で、配信のセッションの書き込みの処理が作る) を除く。
        """
        result = {}
        for directory, _, names in os.walk(self.home):
            for name in names:
                if ignore_lock and directory == self.home and name == "lock":
                    continue
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
