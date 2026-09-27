"""起動時の確認の 12。書き込みを許す場所 (引数 --sandbox-allow-write の値) が、守る場所を含まないかを確かめる。

値の実体パスが、守る場所 (ホーム・作業側・周回の置き場・TMPDIR の実体) のどれかと同じか、その祖先なら、その値を受け付けない。
作業側と周回の置き場は、その下の場所も受け付けない (ホームと TMPDIR の下の場所は受け付ける)。値の場所はまだ無くてよい
(無い部分は、シンボリックリンクを解決せずにそのまま繋ぐ)。

引数: 1〜4 つ目は、ホーム・作業側・周回の置き場・TMPDIR の実体パス。5 つ目以降は --sandbox-allow-write の値。
標準出力: 受け付けない値があれば、最初に見つけたものの理由を 1 行。無ければ何も出さない。
終了コード: 受け付けない値があれば 1、無ければ 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 allow_write_problem。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, sys

# (呼び名, 実体パス, 下の場所も許さないか)
protected = (("ホーム", sys.argv[1], False), ("作業側", sys.argv[2], True), ("周回の置き場", sys.argv[3], True),
             ("TMPDIR の実体", sys.argv[4], False))
for value in sys.argv[5:]:
    real = os.path.realpath(value)
    for label, path, _ in protected:
        if real == path:
            print(f"--sandbox-allow-write の値 {value} (実体 {real}) は、{label}そのものなので、書き込みを許せない")
            sys.exit(1)
        if real == "/" or path.startswith(real + "/"):
            print(f"--sandbox-allow-write の値 {value} (実体 {real}) は、{label} ({path}) を含むので、書き込みを許せない")
            sys.exit(1)
    # 下の場所は、同じか祖先かをすべての守る場所で確かめてから見る (周回の置き場の祖先が作業側の下にあるときは、
    # 置き場を含むことを理由に出すため)
    for label, path, below in protected:
        if below and real.startswith(path + "/"):
            print(f"--sandbox-allow-write の値 {value} (実体 {real}) は、{label} ({path}) の下にあるので、書き込みを許せない")
            sys.exit(1)
