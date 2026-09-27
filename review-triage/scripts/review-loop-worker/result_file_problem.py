"""回の終わりの処理の 3。作業場所の結果のファイルを確かめる
(ファイル review-triage/skills/review-loop/references/worker.md の「回の処理」の表の「結果のファイル」)。

通常のファイルで、実体パスが作業場所の下にあり、大きさが上限以下であれば受け付ける。中身は読まない (FIFO で止まらないように)。

引数: 1 つ目は作業場所の結果のパス、2 つ目は作業場所のパス、3 つ目は大きさの上限 (バイト)。
標準出力: 受け付けないときは、当てはまった条件を 1 行に 1 つ。受け付けるときは何も出さない。
終了コード: 受け付けるなら 0、受け付けないなら 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 result_file_problem。
語の意味と振る舞いの正本も、同じ worker.md。
"""

import os, stat, sys

path, workspace, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    st = os.lstat(path)
except OSError as e:
    print(f"result not readable ({e})")
    sys.exit(1)
problems = []
if not stat.S_ISREG(st.st_mode):
    kinds = ((stat.S_ISLNK, "symbolic link"), (stat.S_ISDIR, "directory"), (stat.S_ISFIFO, "FIFO"),
             (stat.S_ISSOCK, "socket"), (stat.S_ISCHR, "character device"), (stat.S_ISBLK, "block device"))
    kind = next((name for test, name in kinds if test(st.st_mode)), "unknown type")
    problems.append(f"result not a regular file ({kind})")
real = os.path.realpath(path)
if not real.startswith(workspace + "/"):
    problems.append(f"result outside workspace ({real})")
if stat.S_ISREG(st.st_mode) and st.st_size > limit:
    problems.append(f"result too large ({st.st_size} bytes > {limit} bytes)")
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
