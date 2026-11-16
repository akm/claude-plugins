"""`gh` の実行。このモジュールの関数 `run` だけが `gh` を起動する。ほかのモジュールは `subprocess` で `gh` を呼ばず、`run` に
引数の配列を渡す。

プラグイン issue-practice のファイル `issue-practice/scripts/issue_practice/gh.py` をコピーし、このプラグインで使わない引数
(変更系の呼び出しの後の待機と、標準入力) を除いたもの。このプラグインは GitHub に書き込まない (計画
docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R12)。プラグインは別々に配布するので、ファイルは共有しない。

`run` は、終了コード・標準出力・標準エラー出力の末尾・タイムアウトで打ち切ったか・失敗の種類 (`failure`) を返す。
失敗の種類は標準エラー出力と標準出力の文言から分け、再試行はしない。失敗したときの終了コード (計画の KTD11 の 4) は
呼び出し元 (CLI の入口) が決める。

REST の GET は関数 `get` (`gh api -i`。状態コードとヘッダも返し、304 を失敗にしない) で、一覧を返す API は関数 `get_all`
(ヘッダ Link でページを送る) で読む。

テストは PATH の先頭に偽の `gh` (ファイル `gh-notification-dispatch/tests/fake-gh`) のディレクトリを加えて差し替える。
"""

import json
import re
import subprocess

DEFAULT_TIMEOUT = 60
STDERR_TAIL_LINES = 20

# 失敗の種類。None は成功。`missing` は gh が PATH に無いか実行権限が無い (入れる・権限を直すのが直し方)。
# `not_found` は API が 404 を返した (リポジトリが無いか、読む権限が無い。GitHub は読めないリポジトリにも 404 を返す)
FAILURES = ("auth", "not_found", "rate_limit", "network", "timeout", "missing", "other")

_AUTH_RE = re.compile(r"HTTP 401|Bad credentials|gh auth login|not logged in", re.IGNORECASE)
_NOT_FOUND_RE = re.compile(r"\(HTTP 404\)")
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

    文言を見るのは `gh` 自身が書く標準エラー出力だけ。標準出力 (API の応答) には PR の題名など利用者の書いた
    文字列が入るので、正規表現では見ず、JSON として読めたときのトップレベルの errors[].type だけを見る。
    """
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return None
    if _AUTH_RE.search(stderr):
        return "auth"
    if _NOT_FOUND_RE.search(stderr):
        return "not_found"
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


def run(args, timeout=DEFAULT_TIMEOUT, expect_json=False):
    """`gh` を引数の配列で実行する。標準入力は渡さない (/dev/null)。

    返り値: {"args", "exit_code" (タイムアウトと起動できなかったときは None), "stdout", "stderr_tail", "timed_out",
    "failure", "json" (標準出力が JSON として読めればその値、読めなければ None), "json_error" (expect_json が真で、
    標準出力が空でないのに JSON として読めなかったときの理由。それ以外は None)}

    expect_json は、呼び出し元が標準出力に JSON を期待するときに真を渡す (`gh api` や `--json` で JSON を受け取る
    呼び出し)。引数から推測しない。`--jq` や `--template` で文字列を取り出す呼び出しでは渡さない。

    `gh api --paginate` は、ページごとの JSON をつないで出すので 1 つの JSON として読めない。`--slurp` と一緒に使い、
    全ページを 1 つの配列で受け取る。
    """
    args = list(args)
    try:
        completed = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout,
                                   stdin=subprocess.DEVNULL)
        exit_code, stdout, stderr, timed_out = completed.returncode, completed.stdout, completed.stderr, False
    except subprocess.TimeoutExpired as e:
        exit_code, stdout, stderr, timed_out = None, _text(e.stdout), _text(e.stderr), True
    except OSError as e:
        # 起動できなかったことを返り値で伝える。gh が PATH に無い (FileNotFoundError)・実行権限が無い (PermissionError) は
        # `missing`。それ以外 (引数が長すぎる E2BIG など、gh が入っていても起きるもの) は `other`
        failure = "missing" if isinstance(e, (FileNotFoundError, PermissionError)) else "other"
        return {"args": args, "exit_code": None, "stdout": "", "stderr_tail": f"gh を起動できない: {e}",
                "timed_out": False, "failure": failure, "json": None, "json_error": None}
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


API_ORIGIN = "https://api.github.com/"
MAX_PAGES = 100  # 一覧のページ送りの上限。超えたら失敗として返す (Link が次のページを示し続けても、読み続けないため)
_STATUS_RE = re.compile(r"HTTP/\S+ (\d{3})")
_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _split_response(stdout):
    """`gh api -i` の標準出力を (状態コード, ヘッダ (キーは小文字), 本文) に分ける。状態行が無ければ (None, {}, 標準出力)。"""
    text = stdout.replace("\r\n", "\n")
    head, separator, body = text.partition("\n\n")
    lines = head.split("\n")
    match = _STATUS_RE.match(lines[0]) if lines else None
    if not match or not separator:
        return None, {}, stdout
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return int(match.group(1)), headers, body


def get(endpoint, headers=None, timeout=DEFAULT_TIMEOUT):
    """REST の GET を `gh api -i <endpoint>` で実行し、状態コードとヘッダも返す。

    返り値は `run` の結果に、"status" (状態コード。読めなければ None)・"headers" (キーは小文字) を足したもの。"json" は本文を
    読んだ値。headers は要求のヘッダ (`If-None-Match` など) で、`-H` で渡す。

    304 (Not Modified) は失敗にしない。`gh` は 304 でも終了コード 1 で終了し、標準エラー出力に「gh: HTTP 304」を出す
    (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の KTD5 と U1)。
    """
    args = ["api", "-i", endpoint]
    for name, value in (headers or {}).items():
        args += ["-H", f"{name}: {value}"]
    result = run(args, timeout=timeout)
    status, response_headers, body = _split_response(result["stdout"])
    result = {**result, "status": status, "headers": response_headers, "json": None, "json_error": None}
    if status == 304 and result["exit_code"] == 1:
        result["failure"] = None
        return result
    if result["failure"] is not None:
        return result
    if status is None:
        result["json_error"] = "gh api -i の出力に状態行が無い"
        return result
    try:
        result["json"] = json.loads(body)
    except ValueError as e:
        result["json_error"] = f"本文を JSON として読めない: {e}"
    return result


def next_page(headers):
    """ヘッダ Link の rel="next" の URL を、`gh api` に渡すパス (API_ORIGIN を除いたもの) にする。無ければ None。

    API_ORIGIN 以外の URL なら ValueError (このプラグインは github.com だけを扱う)。
    """
    match = _NEXT_RE.search(headers.get("link", ""))
    if not match:
        return None
    url = match.group(1)
    if not url.startswith(API_ORIGIN):
        raise ValueError(f"次のページの URL が {API_ORIGIN} で始まらない: {url}")
    return url[len(API_ORIGIN):]


def get_all(endpoint, headers=None, timeout=DEFAULT_TIMEOUT):
    """一覧を返す API の全ページを読む (計画の KTD4。ページ送りは API ごとに書かず、この関数で行う)。

    headers は 1 ページ目だけに付ける (`If-None-Match` で条件付きの要求をするため)。
    返り値は (要素の配列, 1 ページ目の結果, 失敗した結果)。成功なら失敗した結果は None。1 ページ目が 304 なら要素は None。
    どれかのページが失敗したら、(None, 1 ページ目の結果, そのページの結果) を返す。
    """
    first = get(endpoint, headers=headers, timeout=timeout)
    if failed(first):
        return None, first, first
    if first["status"] == 304:
        return None, first, None
    items, page, path = [], first, endpoint
    for count in range(1, MAX_PAGES + 1):
        if not isinstance(page["json"], list):
            return None, first, {**page, "json_error": f"{path} の応答が配列でない"}
        items.extend(page["json"])
        try:
            path = next_page(page["headers"])
        except ValueError as e:
            return None, first, {**page, "json_error": str(e)}
        if path is None:
            return items, first, None
        if count == MAX_PAGES:
            return None, first, {**page, "json_error": f"{endpoint} のページが {MAX_PAGES} を超えた"}
        page = get(path, timeout=timeout)
        if failed(page):
            return None, first, page
    raise AssertionError("到達しない")


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
