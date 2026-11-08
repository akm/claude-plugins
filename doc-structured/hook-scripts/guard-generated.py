#!/usr/bin/env python3
"""生成したファイルの直接の編集を拒否する PreToolUse の hook (プラグイン doc-structured)。

Edit・Write・NotebookEdit の対象のファイルが、ツール doc-structured で生成したファイルなら、編集が実行される前に拒否し、
直す元のファイル (生成元) と生成のコマンドを Claude に伝える。
  - 生成したファイルかどうかは、ファイル自身の先頭の記述で判定する。判定にはプラグインの中のモジュール
    tool/src/doc_structured/generated_header.py を使う (判定の規則はバージョンをまたいで変えないので、
    プロジェクトが設定したツールのバージョンと違っても結果は同じ)
  - プロジェクトの設定は読まない。検査も実行しない
  - まだ無いファイルと、先頭の記述の無いファイル (手書きのファイル) は拒否しない
  - Bash での編集と人のエディタでの編集は、この hook では防げない。検査 a が検出する

このスクリプトは、Python 3.12 より古い python3 でも構文の誤りにならないように書き、版を確認してからモジュールを読み込む。
古い python3 や読めない入力では判定をせず、標準エラー出力に理由を書いて終了コード 1 で終了する
(Claude Code は編集をそのまま実行する。古い Python の環境で、すべての編集を拒否しないため)。
"""

import json
import os
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = "doc-structured:generate"


def error(message):
    sys.stderr.write("doc-structured: " + message + "\n")
    return 1


def deny(reason):
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main():
    if sys.version_info < (3, 12):
        found = ".".join(str(n) for n in sys.version_info[:3])
        return error(
            "生成したファイルの編集を拒否する hook には Python 3.12 以上の python3 が要る (見つかったのは "
            + found + ")。生成したファイルかどうかを判定せずに、編集を実行させる"
        )
    sys.path.insert(0, os.path.join(PLUGIN_ROOT, "tool", "src"))
    from doc_structured import generated_header

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        return error(f"hook の入力を JSON として読めない ({e})。生成したファイルかどうかを判定せずに、編集を実行させる")
    if not isinstance(data, dict):
        return error("hook の入力が JSON のオブジェクトでない。生成したファイルかどうかを判定せずに、編集を実行させる")
    # デフォルト値を使うのはキーが無いときだけ。値があって型が違えば (0 や false も)、入力の誤りとして報告する
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return error("hook の入力の tool_input が JSON のオブジェクトでない。生成したファイルかどうかを判定せずに、編集を実行させる")
    path = ""
    for key in ("file_path", "notebook_path"):
        if key not in tool_input:
            continue
        if not isinstance(tool_input[key], str):
            return error(f"hook の入力の {key} が文字列でない。生成したファイルかどうかを判定せずに、編集を実行させる")
        path = path or tool_input[key]
    if not path:
        return 0
    cwd = data.get("cwd", "")
    if not isinstance(cwd, str):
        return error("hook の入力の cwd が文字列でない。生成したファイルかどうかを判定せずに、編集を実行させる")
    cwd = cwd or os.getcwd()
    full_path = os.path.join(cwd, path)
    if not os.path.isfile(full_path):
        return 0
    try:
        header = generated_header.read_file_header(full_path)
    except OSError as e:
        return error(f"{full_path} を読めない ({e})。生成したファイルかどうかを判定せずに、編集を実行させる")
    if header is None:
        return 0

    # 対象のパスは絶対パスで示す。生成元とコマンドはリポジトリのルートが基準で、hook はリポジトリのルートを知らないため
    shown = os.path.normpath(full_path)
    command = header.command or generated_header.GENERATE_COMMAND
    run = f"スキル {SKILL} (リポジトリのルートで実行するコマンド {command})"
    if os.path.basename(full_path) == ".gitattributes":
        how = f"{generated_header.GITATTRIBUTES_GUIDE}。生成し直すときは {run} を使う"
    elif header.source:
        how = f"生成元 {header.source} (リポジトリのルートからの相対パス) を直し、{run} で生成し直す"
    else:
        how = f"先頭の記述から生成元を読み取れなかった。生成元を直し、{run} で生成し直す"
    deny(f"{shown} は doc-structured が生成したファイル (先頭に doc-structured:generated の記述がある) なので、直接編集しない。{how}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
