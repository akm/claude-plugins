"""外部のコマンドの実行 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD4)。

このモジュールの関数 `run` だけが外部のコマンド (`du`・`docker` など) を起動する。ほかのモジュールは `subprocess` を使わず、
`run` に引数の配列と時間の上限を渡す。

プラグイン gh-notification-dispatch のファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/gh.py` の関数 `run` を
元に、`gh` に固有の部分 (失敗の種類の判定・JSON の解析・REST の呼び出し) を除いたもの。プラグインは別々に配布するので、
ファイルは共有しない。`gh.py` と違い、標準エラー出力は末尾だけにせずすべてを返す。`du` の読めなかったパスを、標準エラー出力の
すべての行から読むため (計画の KTD4)。

終了コードが 0 以外のときに失敗とするかは、呼び出し元が決める。`du` は、読めないディレクトリがあると終了コード 1 を返すが、
ほかの結果は標準出力に出すため。
"""

import subprocess

ENCODING = "utf-8"
# 標準出力のパスを、UTF-8 として読めないバイトも失わずに扱うため、読めないバイトを surrogate のコードポイントにして残す
ERRORS = "surrogateescape"


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):  # 打ち切ったときの TimeoutExpired は、text=True でも bytes を持つことがある
        return value.decode(ENCODING, errors=ERRORS)
    return value


def run(args, *, timeout):
    """コマンドを引数の配列で実行する。標準入力は空 (/dev/null) にし、timeout 秒で打ち切る。

    timeout は省略できない。時間の上限を付けずに外部のコマンドを実行しないため (計画の R4・KTD4)。

    返り値: {"args" (引数の配列), "exit_code" (打ち切ったときと起動できなかったときは None), "stdout", "stderr" (どちらも
    すべて。打ち切ったときは、それまでに出た分), "timed_out" (打ち切ったか), "start_error" (起動できなかった理由。起動できたら
    None)}
    """
    args = list(args)
    try:
        completed = subprocess.run(args, capture_output=True, text=True, encoding=ENCODING, errors=ERRORS,
                                   timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return {"args": args, "exit_code": None, "stdout": _text(e.stdout), "stderr": _text(e.stderr),
                "timed_out": True, "start_error": None}
    except OSError as e:  # コマンドが PATH に無い・実行権限が無い・引数が長すぎるなど
        return {"args": args, "exit_code": None, "stdout": "", "stderr": "", "timed_out": False,
                "start_error": f"{args[0]} を起動できない: {e}"}
    return {"args": args, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
            "timed_out": False, "start_error": None}
