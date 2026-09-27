"""ディレクトリを改名する (rename(2) をそのまま呼ぶ)。準備のディレクトリを作業場所のパスに改名するのに使う。

引数: 1 つ目は改名するディレクトリ、2 つ目は改名の後のパス。
標準出力: 失敗すれば理由を 1 行。改名できれば何も出さない。
終了コード: 改名できれば 0、失敗すれば 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 rename_dir。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, sys

try:
    os.rename(sys.argv[1], sys.argv[2])
except OSError as e:
    print(e.strerror or e)
    sys.exit(1)
