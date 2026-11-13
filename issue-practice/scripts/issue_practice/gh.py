"""`gh` の実行。このモジュールの関数 `run` だけが `gh` を起動する (計画の KTD11)。ほかのモジュールは `subprocess` で `gh` を
呼ばず、`run` に引数の配列を渡す。

プラグイン issue-dispatch のファイル `issue-dispatch/scripts/issue_dispatch/gh.py` をコピーし、issue-practice で使わない関数
(レート制限の再開時刻を読む関数) を除いて、トークンのログインを読む関数 `viewer_login` を足したもの。プラグインは別々に
配布するので、ファイルは共有しない。

`run` は、終了コード・標準出力・標準エラー出力の末尾・タイムアウトで打ち切ったか・失敗の種類 (`failure`) を返す。
失敗の種類は標準エラー出力と標準出力の文言から分け、再試行はしない。失敗したときの終了コード (計画の KTD10 の 4) は
呼び出し元 (CLI の入口) が決める。

テストは PATH の先頭に偽の `gh` (ファイル `issue-practice/tests/fake-gh`) のディレクトリを加えて差し替える。
"""

import json
import re
import subprocess
import time

DEFAULT_TIMEOUT = 60
STDERR_TAIL_LINES = 20
MUTATION_INTERVAL = 1.0  # 変更系の呼び出しの後に待機する秒数 (次の変更系の呼び出しと 1 秒以上空ける)

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


def run(args, timeout=DEFAULT_TIMEOUT, mutation=False, expect_json=False, stdin=None):
    """`gh` を引数の配列で実行する。

    mutation が真なら、gh が終了した後に MUTATION_INTERVAL 秒待機してから返る。次の変更系の呼び出しがこのプロセスでも
    別のプロセス (CLI はサブコマンドごとに 1 プロセス) でも、1 秒以上空く。
    返り値: {"args", "exit_code" (タイムアウトと起動できなかったときは None), "stdout", "stderr_tail", "timed_out",
    "failure", "json" (標準出力が JSON として読めればその値、読めなければ None), "json_error" (expect_json が真で、
    標準出力が空でないのに JSON として読めなかったときの理由。それ以外は None)}

    stdin は、標準入力に渡す文字列 (`gh api graphql --input -` の本文など)。None なら標準入力は渡さない (/dev/null)。
    expect_json は、呼び出し元が標準出力に JSON を期待するときに真を渡す (`gh api` や `--json` で JSON を受け取る
    呼び出し)。引数から推測しない。`--jq` や `--template` で文字列を取り出す呼び出しや、URL や文章を出すコマンド
    (`gh issue comment` など) では渡さない。

    `gh api --paginate` は、ページごとの JSON をつないで出すので 1 つの JSON として読めない。`--slurp` と一緒に使い、
    全ページを 1 つの配列で受け取る。
    """
    args = list(args)
    try:
        completed = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout,
                                   input=stdin, stdin=subprocess.DEVNULL if stdin is None else None)
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


def failed(result):
    """`run` の結果が、呼び出し元から見て失敗か (gh が失敗した・JSON を期待したのに読めなかった)。"""
    return result["failure"] is not None or result["json_error"] is not None


def describe_failure(result):
    """失敗した `run` の結果を、CLI の出力の `gh_error` に入れる形にする。"""
    return {"args": result["args"], "exit_code": result["exit_code"], "failure": result["failure"],
            "stderr_tail": result["stderr_tail"], "json_error": result["json_error"]}


def viewer_login(timeout=DEFAULT_TIMEOUT):
    """トークンのログイン (`gh api user` の `login`) を読む。返り値は (ログイン, 失敗した `run` の結果)。

    読めたときは (ログイン, None)、読めなかったときは (None, 結果)。応答に `login` が無いときも読めなかったとして扱う。
    """
    result = run(["api", "user"], timeout=timeout, expect_json=True)
    if failed(result):
        return None, result
    data = result["json"]
    login = data.get("login") if isinstance(data, dict) else None
    if not isinstance(login, str) or not login:
        return None, {**result, "json_error": "応答に login が無い"}
    return login, None
