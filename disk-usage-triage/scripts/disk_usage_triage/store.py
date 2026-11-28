"""保存先のディレクトリの読み書きとロック (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD2)。

保存先のディレクトリは、設定・記録・トリアージのファイルを保存するディレクトリ `~/.claude/disk-usage-triage/` (計画の R3)。
ファイルの様式の SSOT は文書 `disk-usage-triage/references/files.md`。

プラグイン gh-notification-dispatch のファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/store.py` を元に、
このプラグインで使う部分 (場所・読み取り・ロック・書き込み) だけを持つ形にしたもの。プラグインは別々に配布するので、
ファイルは共有しない。

書き込みは、関数 `transaction` が返す `Transaction` の `write` だけで行う。ファイル `lock` の排他ロックを取ってから、同じ
ディレクトリの一時ファイルに書いて `os.replace` で名前を変える。

読み取りは、ファイルが無いことと壊れていることを区別する。無ければ None を返し、壊れていれば `Corrupt` を送出する。壊れた
ファイルを空として扱うと、利用者が書いた内容を上書きして失うことがあるため (ファイル
`docs/solutions/architecture-patterns/fail-soft-by-data-class.md`)。壊れたファイルをどう扱うか (終了コード 3 で示すか、
調べ直すよう示すか) は、データの種類ごとに呼び出し元が決める。
"""

import contextlib
import fcntl
import json
import os
import re
import tempfile

HOME_ENV = "DISK_USAGE_TRIAGE_HOME"
DEFAULT_HOME = os.path.join("~", ".claude", "disk-usage-triage")
VERSION = 1
LOCK = "lock"
INPUTS = "inputs"

_SURROGATE = re.compile("[\ud800-\udfff]")


class Corrupt(Exception):
    """ファイルが壊れている (JSON として読めない・オブジェクトでない・`version` が 1 でない・中身の形が違う)。

    属性 path は壊れたファイルの絶対パス、reason は壊れている理由。
    """

    def __init__(self, path, reason):
        super().__init__(f"{path} が壊れている: {reason}")
        self.path = path
        self.reason = reason


def home():
    """保存先のディレクトリの絶対パス。環境変数 DISK_USAGE_TRIAGE_HOME があればその場所 (テストで使う。計画の KTD2)。"""
    return os.path.abspath(os.path.expanduser(os.environ.get(HOME_ENV) or DEFAULT_HOME))


def inputs_dir():
    """Claude が Write ツールで入力のファイルを書くディレクトリの絶対パス (計画の KTD3)。"""
    return os.path.join(home(), INPUTS)


def dumps(data):
    """data を JSON の文字列にする。日本語はエスケープせず、surrogate のコードポイントだけを JSON のエスケープ (`\\udcff` の形) にする。

    モジュール proc は、du の出力のうち UTF-8 として読めないバイトを surrogate のコードポイントにして残すので、項目のパスに
    入ることがある。そのまま UTF-8 で書くと UnicodeEncodeError になるため。JSON の文字列の外 (区切りの記号) には ASCII の文字しか
    出ないので、置き換えるのは文字列の中だけになる。再度読み込むと、元のパス (surrogate のコードポイントを含む文字列) に戻る
    (計画の KTD2)。ファイルの書き込みと、入口のファイルの標準出力の JSON の両方に使う。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return _SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


def _read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as e:  # JSON として読めない (json.JSONDecodeError) か、UTF-8 として読めない (UnicodeDecodeError)
        raise Corrupt(path, f"JSON として読めない ({e})") from None
    if not isinstance(data, dict):
        raise Corrupt(path, "JSON のオブジェクトでない")
    version = data.get("version")
    if type(version) is not int or version != VERSION:  # 真偽値 (int の派生) も誤りにする
        raise Corrupt(path, f"version が {VERSION} でない ({json.dumps(version, ensure_ascii=False)})")
    return data


def read(name):
    """保存先のディレクトリのファイルを読む。無ければ None、壊れていれば Corrupt を送出する。

    ロックは取らない (書き込みは名前を変えて置き換えるので、読んだ内容は書き込みの前か後のどちらか一方になる)。
    保存先のディレクトリが無くても作らない。
    """
    return _read_file(os.path.join(home(), name))


def _write_atomic(path, data):
    """同じディレクトリの一時ファイルに書いてから名前を変える。途中で失敗したら一時ファイルを消し、元のファイルを残す。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dumps(data))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


class Transaction:
    """ロックを取った間の、保存先のディレクトリの読み書き。関数 transaction だけが作る。"""

    def __init__(self, directory):
        self.directory = directory

    def read(self, name):
        return _read_file(os.path.join(self.directory, name))

    def write(self, name, data):
        _write_atomic(os.path.join(self.directory, name), data)


@contextlib.contextmanager
def transaction():
    """保存先のディレクトリを作り、ファイル lock の排他ロックを取って Transaction を返す。

    同じマシンで並行して動くスクリプトどうしの書き込みを順にするため、ロックを取ったまま読み、書き換え、書く。
    """
    directory = home()
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, LOCK), "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # ファイルを閉じるとロックは外れる
        yield Transaction(directory)
