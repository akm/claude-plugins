"""回の終わりの処理の 4。作業場所の結果を、周回の置き場の出力先と同じディレクトリの一時名に書いてから改名して複写する。

結果はシンボリックリンクを辿らずに開き直し、通常のファイルで大きさが上限以下であることを確かめてから読む。
一時名もシンボリックリンクを辿らずに開く。改名の後に、出力先が通常のファイルとして在ることを確かめる。

引数: 1 つ目は作業場所の結果のパス、2 つ目は周回の置き場の出力先のパス、3 つ目は大きさの上限 (バイト)。
標準出力: 失敗すれば理由を 1 行。複写できれば何も出さない。
終了コード: 複写できれば 0、失敗すれば 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 copy_result。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, stat, sys

src, dest, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
tmp = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + ".tmp")


def fail(reason):
    print(reason)
    sys.exit(1)


try:
    with os.fdopen(os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            fail("the result is not a regular file")
        data = f.read(limit + 1)
except OSError as e:
    fail(f"cannot read the result: {e}")
if len(data) > limit:
    fail(f"the result is larger than {limit} bytes")
try:
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
except OSError as e:
    fail(f"cannot create {tmp}: {e}")
try:
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.rename(tmp, dest)
except OSError as e:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    fail(f"cannot write {dest}: {e}")
try:
    placed = stat.S_ISREG(os.lstat(dest).st_mode)
except OSError:
    placed = False
if not placed:
    fail(f"{dest} is not a regular file after the rename")
