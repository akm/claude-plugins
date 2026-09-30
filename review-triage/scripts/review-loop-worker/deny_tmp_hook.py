"""レビュアの実行の PreToolUse のフック (ツールを実行する前に Claude Code が呼ぶフック)。
Bash のコマンドの文字列がルートのディレクトリ /tmp を指すパスを含めば、そのコマンドを実行する前に拒否する。
説明の正本は、ファイル review-triage/skills/review-loop/references/worker.md の「/tmp を含むコマンドを拒否するフック」。

ワーカーはこのファイルを、ほかの .py と同じく起動時に読み込み、2 か所で使う。
  - review-loop-worker/build_settings_json.py が、中身をレビュアの実行に渡す --settings のフックのコマンド
    (python3 -I -c <中身>) に埋め込む。Claude Code がそのコマンドを実行すると、__name__ が "__main__" になり、下の処理が実行される
  - review-loop-worker/read_log_facts.py が、中身を __name__ を "__main__" 以外にして実行し、関数 denies と文字列 REASON を使って、
    このフックが拒否した呼び出しを見分ける

標準入力: Claude Code が渡すフックの入力 (JSON)。
標準出力: 拒否するときだけ、拒否を表す JSON を 1 行。拒否しないときは何も出さない。
終了コード: 0。入力を JSON のオブジェクトとして読めなければ、例外で 0 以外になる (Claude Code はそのままツールを実行し、
サンドボックスが書き込みを止めれば、今までどおりその回はレビュー不成立になる)。
"""

import json, re, sys

# ルートのディレクトリ /tmp を指すパス。/tmp の前がパスの一部になる文字 (英数字・. ~ $ } / -) なら当てない
# (./tmp・~/tmp・$TMPDIR/tmp・${D}/tmp・/private/tmp など)。/tmp の後が名前の続きになる文字 (英数字・. -) でも当てない (/tmpfile など)
TMP_PATH = re.compile(r"(?<![\w.~$}/-])/tmp(?![\w.-])")

REASON = ("このコマンドは実行していない: レビューのワーカーは、/tmp を含む Bash のコマンドを実行前に拒否する"
          " (/tmp への書き込みはサンドボックスが止める)。一時ファイルは作業ツリー (このレビューのための使い捨ての複製) の中、"
          "例えば ./tmp に作るように書き直して実行する。ファイルを探す・読むだけなら、Grep か Read のツールを使う。")


def denies(command):
    """Bash のコマンドの文字列 command を、このフックが拒否するか。"""
    return isinstance(command, str) and TMP_PATH.search(command) is not None


if __name__ == "__main__":
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input")
    if event.get("tool_name") == "Bash" and isinstance(tool_input, dict) and denies(tool_input.get("command")):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }}, ensure_ascii=False))
