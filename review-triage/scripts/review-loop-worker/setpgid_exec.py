"""引数のコマンドを、専用のプロセスグループ (自分の PID と同じ番号) にしてから実行する。

レビュアの実行と準備のコマンドをこれで起動する (上限を越えたときと割り込みを受けたときに、プロセスグループごと止めるため)。

引数: 1 つ目は実行するコマンド (環境変数 PATH から探す)、2 つ目以降はその引数。
標準出力と終了コード: このプロセスがコマンドに置き換わる (exec) ので、コマンドのもの。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 run_prep と run_reviewer。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, sys

os.setpgid(0, 0)
os.execvp(sys.argv[1], sys.argv[1:])
