"""ディレクトリ (作業場所か準備のディレクトリ) を rm -rf で消せるように、その中のディレクトリに所有者の読み取り・書き込み・実行の
権限を足す (回の終わりの処理の 5)。Go のモジュールのキャッシュなど、読み取り専用のディレクトリを作るツールがあるため。

シンボリックリンクは辿らず、リンクの先の権限は変えない (守り方は下のコメント)。権限を足せなかったディレクトリは飛ばす。

引数: ディレクトリのパス (作ったときの実体パス)。
標準出力: パスがディレクトリでないか、実体パスが引数と違う (作ったときと違う) ときは、理由を 1 行。それ以外は何も出さない。
終了コード: 理由を出したときは 1、それ以外は 0。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 make_removable。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, stat, sys

top = sys.argv[1]
try:
    st = os.lstat(top)
except OSError as e:
    print(f"状態を読めない ({e})")
    sys.exit(1)
if not stat.S_ISDIR(st.st_mode):
    print("ディレクトリではない")
    sys.exit(1)
real = os.path.realpath(top)
if real != top:
    print(f"実体パス {real} が、作ったときと違う")
    sys.exit(1)

# 作業場所の中は、前の回のレビュアの実行が残したプロセス (作業場所の外に cwd を移したもの) も書き換えられる。
# 確かめてから chmod するまでの間にディレクトリをシンボリックリンクに置き換えられても、リンクの先 (作業場所の外) の権限を
# 変えないように、次の 2 つを守る。
#   - パスの途中の部分は、名前を繋いだ文字列ではなく、開いたディレクトリのファイル記述子から辿る (os.fwalk の dir_fd)。
#     os.fwalk はシンボリックリンクの先に降りない
#   - パスの最後の部分は、chmod でシンボリックリンクを辿らない (os.chmod の follow_symlinks=False。macOS の lchmod)。
#     Linux (CI のテストだけが通る経路) には lchmod が無いので、直前の lstat でシンボリックリンクでないことだけを確かめる
NOFOLLOW = os.chmod in os.supports_follow_symlinks


def add_owner_rwx(name, dir_fd=None):
    try:
        s = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return
    if not stat.S_ISDIR(s.st_mode) or s.st_mode & 0o700 == 0o700:
        return
    try:
        if NOFOLLOW:
            os.chmod(name, stat.S_IMODE(s.st_mode) | 0o700, dir_fd=dir_fd, follow_symlinks=False)
        else:
            os.chmod(name, stat.S_IMODE(s.st_mode) | 0o700, dir_fd=dir_fd)
    except OSError:
        pass


add_owner_rwx(top)
# 上から順にたどり、下のディレクトリの権限を、そこへ降りる前に足す
for _, dirs, _, dir_fd in os.fwalk(top):
    for d in dirs:
        add_owner_rwx(d, dir_fd)
