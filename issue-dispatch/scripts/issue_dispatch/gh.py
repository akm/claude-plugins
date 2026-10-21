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
MUTATION_INTERVAL = 1.0  # 変更系の呼び出しの後に待つ秒数 (次の変更系の呼び出しと 1 秒以上空ける。KTD14)

# 失敗の種類。None は成功。`missing` は gh が PATH に無いか実行権限が無い (入れる・権限を直すのが直し方)
FAILURES = ("auth", "rate_limit", "network", "timeout", "missing", "other")

_AUTH_RE = re.compile(r"HTTP 401|Bad credentials|gh auth login|not logged in", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"rate limit|RATE_LIMITED|secondary rate|abuse detection", re.IGNORECASE)
_NETWORK_RE = re.compile(
    r"dial tcp|connection refused|connection reset|no such host|i/o timeout|TLS handshake|proxyconnect|"
    r"network is unreachable|error connecting|could not resolve host",
    re.IGNORECASE,
)


def _graphql_error_types(stdout):
    """標準出力が GraphQL の応答なら、トップレベルの errors[].type の集合。読めなければ空。"""
    try:
        data = json.loads(stdout)
    except ValueError:
        return set()
    errors = data.get("errors") if isinstance(data, dict) else None
    if not isinstance(errors, list):
        return set()  # errors が無い・null・配列でない応答
    return {e.get("type") for e in errors if isinstance(e, dict)}


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


def run(args, timeout=DEFAULT_TIMEOUT, mutation=False, expect_json=False):
    """`gh` を引数の配列で実行する。

    mutation が真なら、gh が終わった後に MUTATION_INTERVAL 秒待ってから返る。次の変更系の呼び出しがこのプロセスでも
    別のプロセス (CLI はサブコマンドごとに 1 プロセス) でも、1 秒以上空く (利用者と相談して決めた)。
    返り値: {"args", "exit_code" (タイムアウトと起動できなかったときは None), "stdout", "stderr_tail", "timed_out",
    "failure", "json" (標準出力が JSON として読めればその値、読めなければ None), "json_error" (expect_json が真で、
    標準出力が空でないのに JSON として読めなかったときの理由。それ以外は None)}

    expect_json は、呼び出し側が標準出力に JSON を期待するときに真を渡す (`gh api` や `--json` で JSON を受け取る
    呼び出し)。引数から推測しない。`--jq` や `--template` で文字列を取り出す呼び出しや、URL や文章を出すコマンド
    (`gh issue comment` など) では渡さない (利用者と相談して決めた)。

    `gh api --paginate` は、ページごとの JSON をつないで出すので 1 つの JSON として読めない。`--slurp` と一緒に使い、
    全ページを 1 つの配列で受け取る。
    """
    args = list(args)
    try:
        completed = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        exit_code, stdout, stderr, timed_out = completed.returncode, completed.stdout, completed.stderr, False
    except subprocess.TimeoutExpired as e:
        exit_code, stdout, stderr, timed_out = None, _text(e.stdout), _text(e.stderr), True
    except OSError as e:
        # 起動できなかったことを返り値で伝える。gh が PATH に無い (FileNotFoundError)・実行権限が無い (PermissionError) は
        # `missing`。それ以外 (引数が長すぎる E2BIG など、gh が入っていても起きるもの) は `other`
        failure = "missing" if isinstance(e, (FileNotFoundError, PermissionError)) else "other"
        return {"args": args, "exit_code": None, "stdout": "", "stderr_tail": f"gh を起動できない: {e}",
                "timed_out": False, "failure": failure, "json": None, "json_error": None}
    finally:
        if mutation:
            time.sleep(MUTATION_INTERVAL)
    parsed, json_error = None, None
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except ValueError as e:
            if expect_json:
                json_error = str(e)
    return {
        "args": args,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr_tail": _tail(stderr),
        "timed_out": timed_out,
        "failure": classify(exit_code, stdout, stderr, timed_out),
        "json": parsed,
        "json_error": json_error,
    }


def rate_limit_reset_at(timeout=DEFAULT_TIMEOUT):
    """GraphQL のレート制限の再開時刻 (UNIX 時刻の秒) を `gh api rate_limit` で読む。読めなければ None。
    REST の rate_limit はレート制限に数えられないので、制限の間でも読める。"""
    result = run(["api", "rate_limit"], timeout=timeout, expect_json=True)
    data = result["json"]
    try:
        return int(data["resources"]["graphql"]["reset"])
    except (TypeError, KeyError, ValueError):
        return None
