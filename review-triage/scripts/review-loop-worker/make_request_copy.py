"""回の処理の手順 8。作業側の依頼文の写しを作る。

写しでは、次の順に文字列を置き換える。置き換えた後のパスは、どれも改名の後の作業場所のパス (レビュアの実行が見るパス) で書く。
  1. 元の出力先 (依頼文の「出力先:」の行の値) の、すべての出現 → 作業場所の結果のパス
  2. バッククォートで囲んだ元の作業ツリーのパス (作業側の実体パス) → 複製のパス
  3. 作業ツリーの扱いを示す行 (「- 作業ツリーの扱い: <値>」) の値 → 使い捨て
出力先は作業ツリーのパスで始まるので、この順でないと出力先が複製の中のパスになる。元の出力先は、周回の置き場から組み立てたもの
(実体が周回の置き場で、名前が review-<識別子>.yaml) でなければならない。置き換えの後に、元の出力先か元の作業ツリーのパスが
残っているか、扱いの行がちょうど 1 つでなければ、写しを作らずに失敗とする。

引数: 依頼文・写し・識別子・周回の置き場の実体パス・作業側の実体パス・作業場所・複製の順の 7 つ。
標準出力: 失敗すれば、完了の印の error に書く文字列 (request copy failed (<理由>)) を 1 行。写しを作れれば何も出さない。
終了コード: 写しを作れれば 0、失敗すれば 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 make_request_copy が、準備のコマンドとして
(関数 run_prep で、準備のディレクトリを cwd にして) 起動する。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, re, sys

request, copy, rid, loop_real, tree_real, workspace, clone = sys.argv[1:8]
ws_result = os.path.join(workspace, f"review-{rid}.yaml")


def fail(reason):
    print(f"request copy failed ({reason})")
    sys.exit(1)


try:
    with open(request, encoding="utf-8") as f:
        text = f.read()
except (OSError, ValueError) as e:
    fail(f"cannot read the request: {e}")
m = re.search(r"^出力先: `([^`]+)`", text, re.M)
if not m:
    fail("no output line")
orig_out = m.group(1)
if not (os.path.isabs(orig_out) and os.path.basename(orig_out) == f"review-{rid}.yaml"
        and os.path.realpath(os.path.dirname(orig_out)) == loop_real):
    fail(f"output path does not point to the loop dir: {orig_out}")
text = text.replace(orig_out, ws_result)
tree_token = f"`{tree_real}`"
if tree_token not in text:
    fail(f"worktree path not found: {tree_token}")
text = text.replace(tree_token, f"`{clone}`")
lines = text.split("\n")
handling = [i for i, line in enumerate(lines) if line.startswith("- 作業ツリーの扱い:")]
if len(handling) != 1:
    fail(f"handling lines: {len(handling)}")
lines[handling[0]] = re.sub(r"^(- 作業ツリーの扱い:).*?(\r?)$", r"\1 使い捨て\2", lines[handling[0]])
text = "\n".join(lines)
# 作業場所のパスを除いてから探す (作業場所のパスの中に、元のパスと同じ文字列が偶然現れても数えないように)
rest = text.replace(workspace, "")
if orig_out in rest:
    fail("output path remains")
if tree_real in rest:
    fail("worktree path remains")
try:
    with open(copy, "w", encoding="utf-8") as f:
        f.write(text)
except OSError as e:
    fail(f"cannot write the copy: {e}")
