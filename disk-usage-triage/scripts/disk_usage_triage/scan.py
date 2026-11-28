"""ディレクトリの調査 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R4・R5・KD2・KTD4)。

調べるディレクトリ (設定のキー `scan_dirs`) と、一覧で指定した項目のディレクトリを、コマンド `du -k -d 1` で調べ、1 つ下の
階層の項目とその使用量 (バイト) を返す。一覧・番号・並べ替え・表示は、モジュール lists が行う。du を実行する方法と、
結果を使う条件の SSOT は計画の KTD4。

- du は `/usr/bin/du` を絶対パスで、環境変数 `LC_ALL=en_US.UTF-8` を足して実行する。C ロケールでは、macOS の du が ASCII で
  ない名前を書き換えて出力するため。PATH の du を使わないのは、GNU の du が先に見つかると、読めないディレクトリの行の形が違う
  ため。テストでは、環境変数 DISK_USAGE_TRIAGE_DU で偽の du (ファイル `disk-usage-triage/tests/fakebin/du`) のパスを渡す。
- du には、`~` と `~/` を展開し、シンボリックリンクを解決したパスを渡す。シンボリックリンクのパスを渡すと、du はリンク先を
  たどらずに 0 の行だけを出すため。項目のパスも、解決した後のパスになる。
- 時間の上限 (計画の R4) は、ディレクトリごとに付ける。上限を超えたディレクトリは結果を出さず、ほかのディレクトリは調べ続ける。
"""

import os
import re

from . import proc

DU_ENV = "DISK_USAGE_TRIAGE_DU"
DEFAULT_DU = "/usr/bin/du"
DU_LOCALE = "en_US.UTF-8"

STATUS_OK = "ok"  # 結果を使う
STATUS_TIMED_OUT = "timed_out"  # 時間内に完了しなかった
STATUS_FAILED = "failed"  # 誤りがあったので、結果を出さない

_LINE = re.compile(r"([0-9]+)\t(.*)")  # 標準出力の行。キロバイトの値・タブ・パス (\d は ASCII でない数字にも一致する)
_DENIED = re.compile(r"du: (.+): (?:Operation not permitted|Permission denied)")  # 読めなかったパス
_VANISHED = re.compile(r"du: (.+): No such file or directory")  # 名前を読んだ後に消えたパス
_SHOWN_LINES = 5  # 誤りの理由に含める、標準エラー出力の行の数


def du_command():
    """du として実行するコマンドのパス。環境変数 DISK_USAGE_TRIAGE_DU があればその値 (テストで使う)。"""
    return os.environ.get(DU_ENV) or DEFAULT_DU


def _resolve(path):
    """`~` と `~/` を展開し、シンボリックリンクを解決した絶対パス。それ以外の相対パスは ValueError。"""
    if not isinstance(path, str) or path == "" or "\0" in path:
        raise ValueError(f"パスが空か、文字列でないか、NUL 文字を含む: {path!r}")
    if path == "~" or path.startswith("~/"):
        path = os.path.expanduser(path)
    elif not os.path.isabs(path):
        raise ValueError(f"絶対パスか、~ か ~/ で始まるパスでない: {path!r}")
    return os.path.realpath(path)


def _lines(text):
    """改行 (\\n) だけで分けた行の配列。末尾の改行の後の空の行は含めない。

    str.splitlines は使わない。ほかの文字 (\\r・\\x1c など) でも行を分け、それらを名前に含むパスを読み誤るため。
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _shown(lines):
    """誤りの理由に含める、標準エラー出力の行。"""
    if not lines:
        return "標準エラー出力は空"
    text = "標準エラー出力: " + " / ".join(lines[:_SHOWN_LINES])
    if len(lines) > _SHOWN_LINES:
        text += f" (ほか {len(lines) - _SHOWN_LINES} 行)"
    return text


def _result(requested, path, status, *, total=None, items=(), unreadable=(), error=None):
    return {"requested": requested, "path": path, "status": status, "bytes": total, "items": list(items),
            "unreadable": list(unreadable), "error": error}


def _classify_stderr(stderr):
    """標準エラー出力の行を分ける。返り値は (読めなかったパスの配列, 受け入れない行の配列, 行の配列)。

    消えたパスの行は受け入れるが、項目に対応させないので返さない (計画の KTD4)。
    """
    lines = _lines(stderr)
    denied, others = [], []
    for line in lines:
        match = _DENIED.fullmatch(line)
        if match:
            denied.append(match[1])
        elif not _VANISHED.fullmatch(line):
            others.append(line)
    return denied, others, lines


def _parse_stdout(stdout, root):
    """標準出力を読む。返り値は (ディレクトリ自身の使用量 (バイト) か None, 項目の配列, 誤りか None)。"""
    prefix = root if root.endswith("/") else root + "/"
    total, items, seen = None, [], set()
    for line in _lines(stdout):
        match = _LINE.fullmatch(line)
        if not match:
            return None, [], f"du の標準出力の行の形が「数字・タブ・パス」でない: {line!r}"
        size, path = int(match[1]) * 1024, match[2]
        if path in seen:
            return None, [], f"du の標準出力に、同じパスの行が 2 つある: {path!r}"
        seen.add(path)
        if path == root:
            total = size
        elif path.startswith(prefix) and path != prefix and "/" not in path[len(prefix):]:
            items.append({"path": path, "bytes": size, "unreadable": []})
        else:
            return None, [], f"du の標準出力に、調べたディレクトリでもその 1 つ下でもないパスがある: {path!r}"
    return total, items, None


def scan_directory(path, *, timeout):
    """ディレクトリ 1 つを du で調べる。

    path は、絶対パスか、`~` か `~/` で始まるパス (設定の値をそのまま渡せる)。それ以外は ValueError (呼び出し元の誤り)。
    timeout は du の時間の上限 (秒。計画の R4)。

    結果を使うのは、終了コード 0 で標準エラー出力が受け入れる行だけ (空を含む) のときと、終了コード 1 で標準エラー出力が
    1 行以上あり、すべて受け入れる行のときだけ。受け入れる行は、読めなかったパスの行 (`du: <パス>: Operation not permitted`
    か `Permission denied`) と、消えたパスの行 (`du: <パス>: No such file or directory`)。標準出力の行の形が違うとき・調べた
    ディレクトリでもその 1 つ下でもないパスがあるとき・ディレクトリ自身の行が無いときも、結果を使わない (計画の KTD4)。

    返り値の辞書のキー:
      requested   渡された path
      path        du に渡したパス (`~` を展開し、シンボリックリンクを解決した絶対パス)
      status      ok (結果を使う)・timed_out (時間内に完了しなかった)・failed (誤りがあった)
      bytes       ディレクトリ自身の使用量 (バイト)。ok のときだけで、ほかは None
      items       1 つ下の階層の項目の配列 (du の出力の順)。要素は {path (絶対パス), bytes (使用量のバイト),
                  unreadable (その項目か、その下の階層の読めなかったパスの配列)}。ok でなければ空
      unreadable  どの項目にも入らない読めなかったパスの配列。1 つ下の階層のディレクトリそのものが読めず、du がその
                  ディレクトリの行を出さなかったもの。使用量を測れないので、bytes にも入らない。ok でなければ空
      error       timed_out と failed のときの理由。ok のときは None
    """
    root = _resolve(path)
    run = proc.run([du_command(), "-k", "-d", "1", root], timeout=timeout, extra_env={"LC_ALL": DU_LOCALE})
    if run["start_error"]:
        return _result(path, root, STATUS_FAILED, error=run["start_error"])
    if run["timed_out"]:
        return _result(path, root, STATUS_TIMED_OUT, error=f"時間の上限 ({timeout} 秒) までに du が完了しなかった")
    denied, others, lines = _classify_stderr(run["stderr"])
    if run["exit_code"] not in (0, 1):
        return _result(path, root, STATUS_FAILED, error=f"du が終了コード {run['exit_code']} で終了した。{_shown(lines)}")
    if others:
        return _result(path, root, STATUS_FAILED,
                       error=f"du の標準エラー出力に、読めなかったパスと消えたパスのほかの行がある。{_shown(others)}")
    if run["exit_code"] == 1 and not lines:
        return _result(path, root, STATUS_FAILED, error="du が終了コード 1 で終了したが、標準エラー出力が空")
    total, items, error = _parse_stdout(run["stdout"], root)
    if error is None and total is None:
        error = f"du の標準出力に、調べたディレクトリ自身の行が無い (ディレクトリが無いか、読めない)。{_shown(lines)}"
    if error:
        return _result(path, root, STATUS_FAILED, error=error)
    prefix = root if root.endswith("/") else root + "/"
    by_name = {item["path"][len(prefix):]: item for item in items}
    unmapped = []
    for denied_path in denied:
        if denied_path == root:  # macOS の du は、調べたディレクトリそのものが読めないと自身の行を出さないので、ふつうは上で返す
            unmapped.append(denied_path)
            continue
        if not denied_path.startswith(prefix):
            return _result(path, root, STATUS_FAILED,
                           error=f"du の標準エラー出力に、調べたディレクトリの外の読めなかったパスがある: {denied_path!r}")
        item = by_name.get(denied_path[len(prefix):].split("/", 1)[0])
        if item is None:
            unmapped.append(denied_path)
        else:
            item["unreadable"].append(denied_path)
    return _result(path, root, STATUS_OK, total=total, items=items, unreadable=unmapped)


def scan_directories(paths, *, timeout):
    """ディレクトリを順に du で調べ、関数 scan_directory の結果を、paths と同じ順の配列で返す。

    時間の上限 (timeout 秒) は、ディレクトリごとに付ける。上限を超えたディレクトリや誤りがあったディレクトリがあっても、
    ほかのディレクトリは調べ続ける (計画の R4)。
    """
    return [scan_directory(path, timeout=timeout) for path in paths]
