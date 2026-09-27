"""ディレクトリ (作業場所か準備のディレクトリ) の中を cwd にしているプロセスを止める (回の終わりの処理の 1 と、起動時の確認の 2)。

TERM を送り、猶予の秒数のうちに消えなければ KILL を送る。プロセスグループでは見つけられない (Bash のコマンドは
レビュアの実行とは別のプロセスグループで動く) ので、cwd で見つける。cwd は、/proc があれば /proc/<PID>/cwd から
(Linux。CI のテストが通る経路)、無ければコマンド lsof で (macOS) 読む。

引数: 1 つ目はディレクトリの実体パス。2 つ目は TERM を送ってから KILL を送るまでの猶予の秒数。3 つ目は出力に書くディレクトリの呼び名。
標準エラー: シグナルを送ったプロセスと、列挙できなかったことか止められなかったことを書く。標準エラーに書けなくても
  (ワーカーを動かしていた端末を閉じたときなど)、シグナルを送って止める処理は続ける。
終了コード: 止めるものが無いか、すべて止まれば 0。列挙できないか止められなければ 1。

呼び出し元: ファイル review-triage/scripts/review-loop-worker.sh の関数 stop_cwd_procs。
語の意味と振る舞いの正本は、ファイル review-triage/skills/review-loop/references/worker.md。
"""

import os, signal, subprocess, sys, time

workspace, grace, label = sys.argv[1], float(sys.argv[2]), sys.argv[3]
me = os.getpid()


def note(msg):
    """標準エラーへの報告。書けなくても (端末を閉じた後の OSError など) 無視して、止める処理は続ける。"""
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        pass


def inside(path):
    return path == workspace or path.startswith(workspace + "/")


def scan():
    found = set()
    if os.path.isdir("/proc/self"):
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    cwd = os.readlink(f"/proc/{name}/cwd")
                except OSError:
                    continue
                if inside(cwd):
                    found.add(int(name))
    else:
        try:
            r = subprocess.run(["lsof", "-w", "-d", "cwd", "-Fpn"], capture_output=True, text=True, errors="replace")
        except OSError as e:
            raise RuntimeError(f"lsof を実行できない ({e})")
        pid, listed = None, False
        for line in r.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid, listed = int(line[1:]), True
            elif line.startswith("n") and pid is not None and inside(line[1:]):
                found.add(pid)
        # lsof は自分自身の cwd も出力するので、プロセスが 1 つも無ければ列挙に失敗している
        if not listed:
            raise RuntimeError(f"lsof の出力にプロセスが無い (終了コード {r.returncode}: {r.stderr.strip()[:200]})")
    found.discard(me)
    return found


try:
    pids = scan()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not pids:
            sys.exit(0)
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        note(f"review-loop-worker: {label} {workspace} の中を cwd にしているプロセスが残っているので、"
             f"{sig.name} を送る (PID: {' '.join(str(p) for p in sorted(pids))})")
        deadline = time.time() + grace
        while True:
            time.sleep(0.2)
            pids = scan()
            if not pids or time.time() >= deadline:
                break
except RuntimeError as e:
    note(f"review-loop-worker: {label} {workspace} の中を cwd にしているプロセスを列挙できない: {e}")
    sys.exit(1)
if pids:
    note(f"review-loop-worker: {label} {workspace} の中を cwd にしているプロセスが止まらない "
         f"(PID: {' '.join(str(p) for p in sorted(pids))})")
    sys.exit(1)
