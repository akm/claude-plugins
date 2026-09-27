"""作業場所と準備のディレクトリの名前に付けるハッシュを求める。

引数: 周回の置き場の実体パス。
標準出力: そのパスの SHA-256 の、16 進の先頭 8 文字を 1 行。
終了コード: 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 workspace_hash。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import hashlib, sys

print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest()[:8])
