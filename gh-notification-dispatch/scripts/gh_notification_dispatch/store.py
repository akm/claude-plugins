"""記録のディレクトリの読み書きとロック (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の KTD3)。

ファイルの様式の SSOT は文書 `gh-notification-dispatch/references/records.md`。

記録のディレクトリに書くのは配信のセッションだけにする (計画の R19)。書き込みは、関数 `transaction` が返す
`Transaction` の `write` だけで行う。`transaction` は、ロックを取る前と取った後に、実行しているセッションの ID
(環境変数 `CLAUDE_CODE_HOST_SESSION_ID`) が記録の配信のセッションの ID と同じかを確認し、違えば `NotDispatcher` を
送出する。確認しないのは、配信のセッションを記録するサブコマンド `dispatcher set` が使う `transaction(setting_dispatcher=True)`
だけ。確認をサブコマンドごとに書かず、ここに置く (KTD3)。

受信のセッションの一覧の番号の対応は、記録のディレクトリの外 (`${TMPDIR:-/tmp}/gh-notification-dispatch/<ID>/`) に
書くので、この確認をしない (計画の R6)。
"""

import contextlib
import datetime
import fcntl
import json
import os
import tempfile

from . import messages

HOME_ENV = "GH_NOTIFICATION_DISPATCH_HOME"
SESSION_ENV = "CLAUDE_CODE_HOST_SESSION_ID"
NOW_ENV = "GH_NOTIFICATION_DISPATCH_NOW"
DEFAULT_HOME = os.path.join("~", ".claude", "gh-notification-dispatch")
VERSION = 1

STATE = "state.json"
SUBSCRIPTIONS = "subscriptions.json"
SNAPSHOTS = "snapshots"
DELIVERED = "delivered.json"
OUTBOX = "outbox.json"
LOG = "log.jsonl"
LOCK = "lock"
LOG_MAX_BYTES = 1_000_000  # log.jsonl がこれを超えたら、新しい LOG_KEEP_LINES 行だけを残す
LOG_KEEP_LINES = 1000
RECEIVER_DIR = "gh-notification-dispatch"
RECEIVER_SNAPSHOT = "snapshot.json"

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class NotDispatcher(Exception):
    """実行しているセッションが記録の配信のセッションでないので、記録のディレクトリに書けない。

    属性 dispatcher は、記録の配信のセッション (state.json の dispatcher。記録が無ければ None)。
    """

    def __init__(self, message, dispatcher=None):
        super().__init__(message)
        self.dispatcher = dispatcher


def home():
    """記録のディレクトリの絶対パス。環境変数 GH_NOTIFICATION_DISPATCH_HOME があればその場所 (テストで使う)。"""
    return os.path.abspath(os.path.expanduser(os.environ.get(HOME_ENV) or DEFAULT_HOME))


def current_session_id():
    """スクリプトを実行しているセッションの ID。環境変数が無いか空なら None。"""
    value = os.environ.get(SESSION_ENV, "").strip()
    return value or None


def now():
    """今の時刻 (UTC、秒まで)。環境変数 GH_NOTIFICATION_DISPATCH_NOW があればその時刻 (計画の KTD9。テストで使う)。"""
    value = os.environ.get(NOW_ENV)
    if value:
        return parse_time(value)
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def format_time(value):
    return value.astimezone(datetime.timezone.utc).strftime(TIME_FORMAT)


def parse_time(text):
    return datetime.datetime.strptime(text, TIME_FORMAT).replace(tzinfo=datetime.timezone.utc)


def _read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def read(name):
    """記録のディレクトリのファイルを読む。無ければ None。ロックは取らない (書き込みは名前を変えて置き換えるので、
    読んだ内容は書き込みの前か後のどちらか一方になる)。"""
    return _read_file(os.path.join(home(), name))


def dispatcher(state=None):
    """記録の配信のセッション (state.json の dispatcher)。記録が無ければ None。"""
    state = read(STATE) if state is None else state
    return (state or {}).get("dispatcher")


def check_dispatcher(state):
    """実行しているセッションが、state の配信のセッションかを確認する。違えば NotDispatcher を送出する。"""
    current = current_session_id()
    recorded = dispatcher(state or {})
    if current is None:
        raise NotDispatcher(f"環境変数 {SESSION_ENV} が無いので、このセッションが配信のセッションかを確認できない",
                            recorded)
    if not recorded:
        raise NotDispatcher("配信のセッションが記録されていない (配信のセッションで、スキル dispatch の start を先に行う)")
    if recorded.get("session_id") != current:
        raise NotDispatcher(f"このセッション ({current}) は、記録の配信のセッション ({recorded.get('name')}、"
                            f"{recorded.get('session_id')}) ではない", recorded)


def _write_atomic(path, data):
    """同じディレクトリの一時ファイルに書いてから名前を変える。途中で失敗したら一時ファイルを消し、元のファイルを残す。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


class Transaction:
    """ロックを取った間の、記録のディレクトリの読み書き。関数 transaction だけが作る。"""

    def __init__(self, directory):
        self.directory = directory

    def read(self, name):
        return _read_file(os.path.join(self.directory, name))

    def write(self, name, data):
        _write_atomic(os.path.join(self.directory, name), data)

    def append_log(self, entry):
        """log.jsonl に 1 行を足す。LOG_MAX_BYTES を超えたら、新しい LOG_KEEP_LINES 行だけを残す。"""
        path = os.path.join(self.directory, LOG)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if os.path.getsize(path) > LOG_MAX_BYTES:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-LOG_KEEP_LINES:]
            directory = os.path.dirname(path)
            fd, temporary = tempfile.mkstemp(prefix=f".{LOG}.", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                os.replace(temporary, path)
            except BaseException:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary)
                raise


@contextlib.contextmanager
def transaction(setting_dispatcher=False):
    """記録のディレクトリのロックを取り、Transaction を返す。

    setting_dispatcher が偽なら、ロックを取る前に (記録のディレクトリを作る前に) 確認し、ロックを取った後の記録で
    確認し直す。ロックを取るまでの間に、配信のセッションが切り替わることがあるため。真なのは dispatcher set だけ。
    """
    directory = home()
    if not setting_dispatcher:
        check_dispatcher(read(STATE))
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, LOCK), "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # ファイルを閉じるとロックは外れる
        tx = Transaction(directory)
        if not setting_dispatcher:
            check_dispatcher(tx.read(STATE))
        yield tx


def _checked_session_id(session_id):
    error = messages.check_session_id(session_id)
    if error:
        raise ValueError(error)  # パスの一部にするので、呼び出し元が先に検査する
    return session_id


def dispatcher_snapshot_name(session_id):
    """配信のセッションの一覧の番号の対応の、記録のディレクトリの中の名前。"""
    return os.path.join(SNAPSHOTS, f"{_checked_session_id(session_id)}.json")


def receiver_snapshot_path(session_id):
    """受信のセッションの一覧の番号の対応のパス (記録のディレクトリの外。計画の R6)。"""
    base = os.environ.get("TMPDIR") or "/tmp"
    return os.path.join(base, RECEIVER_DIR, _checked_session_id(session_id), RECEIVER_SNAPSHOT)


def read_receiver_snapshot(session_id):
    return _read_file(receiver_snapshot_path(session_id))


def write_receiver_snapshot(session_id, data):
    _write_atomic(receiver_snapshot_path(session_id), data)
