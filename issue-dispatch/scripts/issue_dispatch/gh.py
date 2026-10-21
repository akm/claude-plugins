"""`gh` の実行。このモジュールの関数 `run` だけが `gh` を起動する (R31・KTD14)。ほかのモジュールは `subprocess` で `gh` を
呼ばず、`run` に引数の配列を渡す。

`run` は、終了コード・標準出力・標準エラー出力の末尾・タイムアウトで打ち切ったか・失敗の種類 (`failure`) を返す。
失敗の種類は標準エラー出力と標準出力の文言から分け、再試行や再開時刻までの待ちはしない。待つかどうかと終了コード
(KTD6 の 8・3・4) は呼び出し側 (待機のサブコマンドなど) が決める。

テストは PATH の先頭に偽の `gh` (issue-dispatch/tests/fake-gh) のディレクトリを加えて差し替える。
"""

import json
import re
import subprocess
import time

DEFAULT_TIMEOUT = 60
STDERR_TAIL_LINES = 20
MUTATION_INTERVAL = 1.0  # 変更系の呼び出しの間隔 (秒。KTD14)

# 失敗の種類。None は成功
FAILURES = ("auth", "rate_limit", "network", "timeout", "other")

_AUTH_RE = re.compile(r"HTTP 401|Bad credentials|gh auth login|not logged in", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"rate limit|RATE_LIMITED|secondary rate|abuse detection", re.IGNORECASE)
_NETWORK_RE = re.compile(
    r"dial tcp|connection refused|connection reset|no such host|i/o timeout|TLS handshake|proxyconnect|"
    r"network is unreachable|error connecting|could not resolve host",
    re.IGNORECASE,
)

_last_mutation_end = None


def _graphql_error_types(stdout):
    """標準出力が GraphQL の応答なら、トップレベルの errors[].type の集合。読めなければ空。"""
    try:
        data = json.loads(stdout)
        return {e.get("type") for e in data.get("errors", []) if isinstance(e, dict)}
    except (ValueError, AttributeError):
        return set()


def classify(exit_code, stdout, stderr, timed_out):
    """終了コードと出力から失敗の種類を決める。成功 (終了コード 0) なら None。

    文言を見るのは `gh` 自身が書く標準エラー出力だけ。標準出力 (API の応答) には Issue の本文など利用者の書いた
    文字列が入るので、正規表現では見ず、JSON として読めたときのトップレベルの errors[].type だけを見る。
    """
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return None
    if _AUTH_RE.search(stderr):
        return "auth"
    if _RATE_LIMIT_RE.search(stderr) or "RATE_LIMITED" in _graphql_error_types(stdout):
        return "rate_limit"
    if _NETWORK_RE.search(stderr):
        return "network"
    return "other"


def _tail(text, lines=STDERR_TAIL_LINES):
    return "\n".join(text.splitlines()[-lines:])


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run(args, timeout=DEFAULT_TIMEOUT, mutation=False):
    """`gh` を引数の配列で実行する。

    mutation が真なら、前の変更系の呼び出しの終わりから MUTATION_INTERVAL 秒以上空けてから実行する。
    返り値: {"args", "exit_code" (タイムアウトなら None), "stdout", "stderr_tail", "timed_out", "failure", "json"
    (標準出力が JSON として読めればその値、読めなければ None)}
    """
    global _last_mutation_end
    args = list(args)
    if mutation and _last_mutation_end is not None:
        wait = MUTATION_INTERVAL - (time.monotonic() - _last_mutation_end)
        if wait > 0:
            time.sleep(wait)
    try:
        completed = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        exit_code, stdout, stderr, timed_out = completed.returncode, completed.stdout, completed.stderr, False
    except subprocess.TimeoutExpired as e:
        exit_code, stdout, stderr, timed_out = None, _text(e.stdout), _text(e.stderr), True
    finally:
        if mutation:
            _last_mutation_end = time.monotonic()
    try:
        parsed = json.loads(stdout) if stdout.strip() else None
    except ValueError:
        parsed = None
    return {
        "args": args,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr_tail": _tail(stderr),
        "timed_out": timed_out,
        "failure": classify(exit_code, stdout, stderr, timed_out),
        "json": parsed,
    }


def rate_limit_reset_at(timeout=DEFAULT_TIMEOUT):
    """GraphQL のレート制限の再開時刻 (UNIX 時刻の秒) を `gh api rate_limit` で読む。読めなければ None。
    REST の rate_limit はレート制限に数えられないので、制限の間でも読める。"""
    result = run(["api", "rate_limit"], timeout=timeout)
    data = result["json"]
    try:
        return int(data["resources"]["graphql"]["reset"])
    except (TypeError, KeyError, ValueError):
        return None
