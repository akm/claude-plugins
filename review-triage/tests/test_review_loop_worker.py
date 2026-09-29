#!/usr/bin/env python3
"""ワーカーのスクリプト (review-triage/scripts/review-loop-worker.sh) のテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s review-triage/tests

一時ディレクトリに git のリポジトリと周回の置き場を作り、claude の名前で偽のコマンド
(review-triage/tests/fake-claude) を PATH の先頭に置いて、スクリプトを subprocess で走らせる。
実際の claude は呼ばない。依頼文は、実際の雛形 (review-triage/skills/review-triage/references/
review-request-template.md) を埋めて作る — ワーカーは雛形の行 (出力先・作業ツリー・作業ツリーの扱い) を
文字列で探して写しを作るので、雛形と食い違えばテストが失敗するようにするため。

ワーカーは macOS でだけ起動する (起動時の確認で `uname -s` を見る)。CI (ubuntu) でも走るように、
uname の名前で偽のコマンド (review-triage/tests/fake-uname。既定で Darwin を返す) も PATH の先頭に置く。
ワーカーの環境変数 HOME と TMPDIR は、テストの一時ディレクトリの中の別々のディレクトリにする
(利用者の設定 ~/.claude/settings.json を読まないように、また作業場所の条件を満たすように)。
ワーカーは回ごとに TMPDIR の下に準備のディレクトリを作って複製と写しを作り、作業場所のパスに改名して、回の終わりに消す。

振る舞いの正本は review-triage/skills/review-loop/references/worker.md、
置き場のファイルの様式の正本は同じディレクトリの loop-files.md。
"""

import hashlib
import json
import os
import pty
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.join(_HERE, "..", "scripts", "review-loop-worker.sh")
_FAKE = os.path.join(_HERE, "fake-claude")
_FAKE_UNAME = os.path.join(_HERE, "fake-uname")
_LOOP_FILES = os.path.join(_HERE, "..", "skills", "review-loop", "references", "loop-files.md")
_PLUGIN_JSON = os.path.join(_HERE, "..", ".claude-plugin", "plugin.json")
_TEMPLATE = os.path.join(_HERE, "..", "skills", "review-triage", "references", "review-request-template.md")

# 偽の git。テストが PATH の先頭の bin/ に git の名前で書き、FAKE_GIT_REAL の本物の git に引数をそのまま渡す。
# FAKE_GIT_LOG があれば、git を実行するディレクトリ (cwd に -C の値を順に繋いだもの)・サブコマンド・呼び出し元
# (環境変数 FAKE_GIT_CALLER の値。偽の claude は fake-claude にする。無ければ空文字列) を、JSON の 1 行としてそのファイルに書き足す。
# サブコマンド (-C <ディレクトリ>・-c <設定> と、- で始まる引数を飛ばした最初の引数) が
# FAKE_GIT_TOUCH_ON と同じならファイル FAKE_GIT_TOUCH を作り、
# FAKE_GIT_RUN_ON と同じならシェルのコマンド FAKE_GIT_RUN を sh -c で実行し、
# FAKE_GIT_SLEEP_ON と同じなら自分の PID をファイル FAKE_GIT_PIDS に書き足してから FAKE_GIT_SLEEP 秒 (既定 1000) 待ち、
# FAKE_GIT_FAIL と同じなら本物を呼ばずに失敗する
_FAKE_GIT = """#!/usr/bin/env python3
import json, os, subprocess, sys, time

args = sys.argv[1:]
i = 0
where = os.getcwd()
while i < len(args):
    if args[i] in ("-C", "-c"):
        if args[i] == "-C" and i + 1 < len(args):
            where = os.path.join(where, args[i + 1])
        i += 2
    elif args[i].startswith("-"):
        i += 1
    else:
        break
sub = args[i] if i < len(args) else ""
if os.environ.get("FAKE_GIT_LOG"):
    with open(os.environ["FAKE_GIT_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps([os.path.realpath(where), sub, os.environ.get("FAKE_GIT_CALLER", "")]) + "\\n")
if sub and sub == os.environ.get("FAKE_GIT_TOUCH_ON"):
    open(os.environ["FAKE_GIT_TOUCH"], "w").close()
if sub and sub == os.environ.get("FAKE_GIT_RUN_ON"):
    subprocess.run(["sh", "-c", os.environ["FAKE_GIT_RUN"]], check=True)
if sub and sub == os.environ.get("FAKE_GIT_SLEEP_ON"):
    if os.environ.get("FAKE_GIT_PIDS"):
        with open(os.environ["FAKE_GIT_PIDS"], "a", encoding="utf-8") as f:
            f.write(str(os.getpid()) + " ")
    time.sleep(float(os.environ.get("FAKE_GIT_SLEEP", "1000")))
if sub and sub == os.environ.get("FAKE_GIT_FAIL"):
    print(f"fatal: 偽の git が {sub} を失敗させた", file=sys.stderr)
    sys.exit(128)
real = os.environ["FAKE_GIT_REAL"]
os.execv(real, [real] + args)
"""

# 偽の python3。テストが PATH の先頭の bin/ に python3 の名前で書き、FAKE_PY_REAL (このテストを走らせている python) に
# 引数をそのまま渡す。実行するスクリプトが文字列 FAKE_PY_SLEEP_MARK を含めば、
# ファイル FAKE_PY_TOUCH を作ってから FAKE_PY_SLEEP 秒 (既定 1000) 待ち、そのあとスクリプトを実行する。
# ワーカーが python3 で行う処理のうち 1 つだけを遅らせて、上限を越える時点や割り込みを送る時点を決めるのに使う。
# 同じく文字列 FAKE_PY_PRELUDE_MARK を含めば、ファイル FAKE_PY_PRELUDE の中身をスクリプトの前に足してから実行する
# (ワーカーの処理の途中に、別のプロセスが割り込んだのと同じ変更を起こすのに使う)。
# 実行するスクリプトは、コードを引数で渡す形 (python3 [-I] -c <コード> <引数>...) ならそのコード、標準入力から読む形
# (python3 [-I] - <引数>...) なら標準入力の中身、ファイルを渡す形 (python3 [-I] <ファイル>.py <引数>...) ならそのファイルの中身で、
# どの形でも同じ文字列で見つける。ワーカーは、ディレクトリ review-triage/scripts/review-loop-worker/ の .py の中身を起動時に
# 読み込み、python3 -I -c <読み込んだ中身> の形で実行する。見つけたときは、見つけた中身を同じ -I の有無で -c に渡して実行する
_FAKE_PYTHON = """#!/bin/sh
if [ -z "${FAKE_PY_SLEEP_MARK:-}" ] && [ -z "${FAKE_PY_PRELUDE_MARK:-}" ]; then
  exec "$FAKE_PY_REAL" "$@"
fi
opt=""
if [ "$1" = "-I" ]; then
  opt=-I
  shift
fi
case "$1" in
  -c) script=$2; shift 2 ;;
  -) script=$(cat); shift ;;
  *.py) script=$(cat "$1" 2>/dev/null) || exec "$FAKE_PY_REAL" $opt "$@"; shift ;;
  *) exec "$FAKE_PY_REAL" $opt "$@" ;;
esac
if [ -n "${FAKE_PY_SLEEP_MARK:-}" ]; then
  case "$script" in
    *"$FAKE_PY_SLEEP_MARK"*)
      if [ -n "${FAKE_PY_TOUCH:-}" ]; then : >"$FAKE_PY_TOUCH"; fi
      sleep "${FAKE_PY_SLEEP:-1000}" ;;
  esac
fi
if [ -n "${FAKE_PY_PRELUDE_MARK:-}" ]; then
  case "$script" in
    *"$FAKE_PY_PRELUDE_MARK"*)
      script="$(cat "$FAKE_PY_PRELUDE")
$script" ;;
  esac
fi
exec "$FAKE_PY_REAL" $opt -c "$script" "$@"
"""

# make_removable の途中で、前の回のレビュアの実行が残したプロセスがディレクトリをシンボリックリンクに置き換えたのと同じ変更を
# 起こす前置き (偽の python3 の FAKE_PY_PRELUDE)。名前が victim のパスを、シンボリックリンクを辿らずに stat した直後
# (関数 make_removable がディレクトリであることを確かめた直後で、chmod より前) に 1 度だけ、そのディレクトリを victim.moved に移し、
# victim を FAKE_PY_SWAP_TARGET へのシンボリックリンクにして、ファイル FAKE_PY_SWAP_DONE を作る
_SWAP_PRELUDE = """
import os as _os

_real_stat, _real_lstat = _os.stat, _os.lstat
_swapped = []


def _swap(path, dir_fd):
    if _swapped or not isinstance(path, str) or _os.path.basename(path) != "victim":
        return
    _swapped.append(path)
    if dir_fd is None:
        _os.rename(path, path + ".moved")
        _os.symlink(_os.environ["FAKE_PY_SWAP_TARGET"], path)
    else:
        _os.rename(path, path + ".moved", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        _os.symlink(_os.environ["FAKE_PY_SWAP_TARGET"], path, dir_fd=dir_fd)
    open(_os.environ["FAKE_PY_SWAP_DONE"], "w").close()


def _stat(path, *, dir_fd=None, follow_symlinks=True):
    st = _real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    if not follow_symlinks:
        _swap(path, dir_fd)
    return st


def _lstat(path, *, dir_fd=None):
    st = _real_lstat(path, dir_fd=dir_fd)
    _swap(path, dir_fd)
    return st


_os.stat, _os.lstat = _stat, _lstat
"""

# サンドボックスの中の Bash が既定で書き込める一時ディレクトリ。ワーカーは、作業側と周回の置き場がこの下にあると起動しない
_SANDBOX_TMP = f"/private/tmp/claude-{os.getuid()}"

RID = "20260926-1400-feat-x-1-code-review-opus"
RID2 = "20260926-1410-feat-x-2-code-review-opus"
LOOP_ID = "20260926-1400-feat-x"

PROMPT = "依頼文 {req} のとおりに作業し、結果を依頼文が指す出力先に書く。"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


_YAML_LINE = re.compile(r"^( *)(- )?([A-Za-z_]+):(?: (.*))?$")


def _yaml_scalar(value):
    v = value.strip()
    if v.startswith('"') or v.startswith("["):
        return json.loads(v)
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v in ("true", "false"):
        return v == "true"
    return v


def _read_yaml(path):
    """ワーカーが書く YAML を読む。読めるのは、ブロック形式の対応の入れ子・対応を要素に持つブロック形式の列
    (`- <キー>: <値>` の行で要素が始まるもの)・スカラー・JSON 形式の列。二重引用符の文字列は JSON の文字列として読むので、
    エスケープが正しくなければ (制御文字がそのまま入っているなど) 例外になる。字下げが揃わない行も例外にする。"""
    rows = []  # (字下げ, キー, 値)。キーが None の行は列の要素の始まり
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            m = _YAML_LINE.match(line)
            if not m:
                raise ValueError(f"読めない行: {line!r}")
            indent = len(m.group(1))
            if m.group(2):
                # 列の要素の始まり。要素の対応のキーは「- 」の後ろの桁にあるものとして読む
                rows.append((indent, None, None))
                indent += 2
            rows.append((indent, m.group(3), m.group(4)))
    pos = 0

    def block(indent):
        nonlocal pos
        if rows[pos][1] is None:
            items = []
            while pos < len(rows) and rows[pos][0] == indent and rows[pos][1] is None:
                pos += 1
                items.append(block(indent + 2))
            return items
        out = {}
        while pos < len(rows) and rows[pos][0] == indent and rows[pos][1] is not None:
            _, key, value = rows[pos]
            pos += 1
            if value is not None:
                out[key] = _yaml_scalar(value)
            elif pos < len(rows) and rows[pos][0] > indent:
                out[key] = block(rows[pos][0])
            else:
                out[key] = {}
        return out

    root = block(0) if rows else {}
    if pos != len(rows):
        raise ValueError(f"字下げが揃わない行がある: {rows[pos]!r}")
    return root


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _contract_keys(heading):
    """loop-files.md の見出し heading の直後の表から、(必須のキーの集合, 全キーの集合) を返す。"""
    with open(_LOOP_FILES, encoding="utf-8") as f:
        text = f.read()
    start = text.index(heading)
    rows = []
    in_table = False
    for line in text[start:].splitlines()[1:]:
        if line.startswith("| キー |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip("|").split("|")]
            m = re.fullmatch(r"`([^`]+)`", cells[0])
            if m:
                rows.append((m.group(1), cells[1] == "◯"))
    return {k for k, req in rows if req}, {k for k, _ in rows}


def _group_alive(pgid):
    out = subprocess.run(
        ["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == str(pgid) and not parts[1].startswith("Z"):
            return True
    return False


def _read_pids(path):
    with open(path, encoding="utf-8") as f:
        return [int(x) for x in f.read().split()]


def _workspace_path(tmpdir, loop):
    """ワーカーが周回の置き場 loop のために TMPDIR (tmpdir) の下に作る作業場所のパス (worker.md の「回の処理」の手順 5)。"""
    loop_real = os.path.realpath(loop)
    digest = hashlib.sha256(loop_real.encode("utf-8")).hexdigest()[:8]
    return os.path.join(os.path.realpath(tmpdir), f"review-loop-{os.path.basename(loop_real)}-{digest}")


def _pid_alive(pid):
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    return bool(out) and not out.startswith("Z")


def _make_dirs_writable(top):
    """top の下のディレクトリ (シンボリックリンクを除く) に所有者の権限を足す。後始末で消せるように。"""
    for dirpath, dirnames, _ in os.walk(top):
        for d in dirnames:
            p = os.path.join(dirpath, d)
            if not os.path.islink(p):
                try:
                    os.chmod(p, os.lstat(p).st_mode & 0o7777 | 0o700)
                except OSError:
                    pass


def _make_repo(repo):
    """repo に、コミットが 1 つある git のリポジトリを作る。tmp/ は追跡しない。"""
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
        f.write("# テスト\n")
    with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("tmp/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


def _make_loop_dir(loop, repo):
    """loop に周回の置き場を作り、repo を作業側とする loop.yaml を置く。"""
    os.makedirs(loop)
    with open(os.path.join(loop, "loop.yaml"), "w", encoding="utf-8") as f:
        f.write(f'id: "{LOOP_ID}"\nrepo_dir: "{repo}"\nstate: active\n')


class WorkerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.root = root
        self.repo = os.path.join(root, "repo")
        _make_repo(self.repo)
        self.loop = os.path.join(self.repo, "tmp", "review-loop", LOOP_ID)
        _make_loop_dir(self.loop, self.repo)
        self.bin = os.path.join(root, "bin")
        os.makedirs(self.bin)
        os.symlink(os.path.realpath(_FAKE), os.path.join(self.bin, "claude"))
        os.symlink(os.path.realpath(_FAKE_UNAME), os.path.join(self.bin, "uname"))
        # HOME を差し替えると、asdf のような版の管理ツールの python3 は (HOME の下の設定を探すので) 起動しなくなる。
        # ワーカーと偽の claude が使う python3 は、このテストを走らせている python の実行ファイルにする
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        # ワーカーの HOME と TMPDIR は、リポジトリとは別の、互いに重ならない場所にする
        self.home = os.path.join(root, "home")
        self.tmpdir = os.path.join(root, "tmpdir")
        os.makedirs(self.home)
        os.makedirs(self.tmpdir)
        self.args_file = os.path.join(root, "claude-args.jsonl")
        self.record_file = os.path.join(root, "claude-record.jsonl")
        self.pids_file = os.path.join(root, "claude-pids")
        self.git_pids_file = os.path.join(root, "git-pids")
        self.env = dict(os.environ)
        self.env["PATH"] = self.bin + os.pathsep + self.env.get("PATH", "")
        self.env["HOME"] = self.home
        self.env["TMPDIR"] = self.tmpdir
        for k in [k for k in self.env if k.startswith(("FAKE_CLAUDE_", "FAKE_GIT_"))] + ["FAKE_UNAME_S"]:
            self.env.pop(k, None)
        # この端末で環境変数 CLAUDE_CONFIG_DIR が設定されていると、既存のテストが self.home/.claude/settings.json
        # ではなくそちらを見てしまう。テストがワーカーに渡す環境からは、明示的に指定しない限り外す
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.env["FAKE_CLAUDE_ARGS"] = self.args_file
        self.env["FAKE_CLAUDE_RECORD"] = self.record_file
        self.env["FAKE_CLAUDE_PIDS"] = self.pids_file
        self.env["FAKE_CLAUDE_REPO"] = self.repo
        self.env["FAKE_CLAUDE_LOOP"] = self.loop
        self.procs = []
        self.sleepers = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.communicate()
        for p in self.sleepers:
            if p.poll() is None:
                p.kill()
                p.wait()
        for path in (self.pids_file, self.git_pids_file):
            if not os.path.exists(path):
                continue
            for pid in _read_pids(path):
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        _make_dirs_writable(self.root)
        self._tmp.cleanup()

    # ---- 準備 ----

    def path(self, name):
        return os.path.join(self.loop, name)

    def head(self):
        return _git(self.repo, "rev-parse", "--short", "HEAD")

    def request_text(self, rid=RID, head=None):
        """実際の雛形を、review-request と同じ値の種類で埋めた依頼文を返す (作業ツリーの扱いは「共有」のまま)。"""
        with open(_TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        values = {
            "repo": "example/repo",
            "repo_dir": self.repo,
            "branch": _git(self.repo, "branch", "--show-current"),
            "base": "main",
            "head": head or self.head(),
            "scope": "full",
            "scope_note": "ブランチの全体",
            "skill": "code-review",
            "effort": "high",
            "model": "opus",
            "date": "2026-09-26",
            "run_id": rid,
            "output_path": self.path(f"review-{rid}.yaml"),
        }
        for k, v in values.items():
            text = text.replace("{{" + k + "}}", v)
        self.assertEqual(re.findall(r"\{\{[^}]*\}\}", text), [], "雛形に、テストが埋めていない項目がある")
        return text

    def put_request(self, rid=RID, head=None, text=None):
        if text is None:
            text = self.request_text(rid, head)
        tmp = self.path(f".review-request-{rid}.md.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.rename(tmp, self.path(f"review-request-{rid}.md"))

    def reset_loop(self):
        """subTest の間で、置き場を loop.yaml だけに戻し、偽の claude の記録を消す。"""
        for n in os.listdir(self.loop):
            if n == "loop.yaml":
                continue
            p = self.path(n)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        for f in (self.args_file, self.record_file, self.pids_file, self.git_pids_file):
            if os.path.exists(f):
                os.remove(f)

    def install_fake_git(self):
        """PATH の先頭の bin/ に偽の git (_FAKE_GIT) を置く。テスト自身が使う git (関数 _git) は本物のまま。"""
        path = os.path.join(self.bin, "git")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_FAKE_GIT)
        os.chmod(path, 0o755)
        self.env["FAKE_GIT_REAL"] = shutil.which("git")

    def delay_git(self, sub):
        """偽の git を置き、サブコマンド sub を終わらせないようにする (PID は self.git_pids_file に書かれる)。"""
        self.install_fake_git()
        self.env["FAKE_GIT_SLEEP_ON"] = sub
        self.env["FAKE_GIT_SLEEP"] = "1000"
        self.env["FAKE_GIT_PIDS"] = self.git_pids_file

    def install_fake_python(self):
        """PATH の先頭の bin/ の python3 を偽の python3 (_FAKE_PYTHON) に替える。"""
        path = os.path.join(self.bin, "python3")
        if os.path.islink(path):
            os.remove(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_FAKE_PYTHON)
            os.chmod(path, 0o755)
        self.env["FAKE_PY_REAL"] = sys.executable

    def delay_python(self, mark, seconds, touch):
        """偽の python3 を置き、実行するスクリプト (-c に渡すコード・標準入力から読むもの・引数で渡すファイルのどれか) が
        mark を含むものを seconds 秒遅らせる。遅らせ始めたときにファイル touch を作る。"""
        self.install_fake_python()
        self.env["FAKE_PY_SLEEP_MARK"] = mark
        self.env["FAKE_PY_SLEEP"] = str(seconds)
        self.env["FAKE_PY_TOUCH"] = touch

    def prelude_python(self, mark, prelude):
        """偽の python3 を置き、実行するスクリプト (-c に渡すコード・標準入力から読むもの・引数で渡すファイルのどれか) が
        mark を含むものの前に、Python のコード prelude を足す。"""
        self.install_fake_python()
        path = os.path.join(self.root, "python-prelude.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(prelude)
        self.env["FAKE_PY_PRELUDE_MARK"] = mark
        self.env["FAKE_PY_PRELUDE"] = path

    def ws_path(self):
        """この周回の作業場所のパス。"""
        return _workspace_path(self.tmpdir, self.loop)

    def prep_dirs(self):
        """TMPDIR の下に残っている、この周回の準備のディレクトリ (worker.md の「回の処理」の手順 5) のパスの列。"""
        prefix = "review-loop-prep-" + os.path.basename(self.ws_path())[len("review-loop-"):] + "."
        tmp = os.path.realpath(self.tmpdir)
        return sorted(os.path.join(tmp, n) for n in os.listdir(tmp) if n.startswith(prefix))

    def spawn_sleeper(self, cwd, *args):
        """cwd を作業ディレクトリにして、別のセッションで待ち続けるプロセスを起動する。args は起動引数に足すだけで使わない。"""
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(1000)", *args], cwd=cwd, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.sleepers.append(p)
        return p

    def write_dead_worker_yaml(self, workspace):
        """kill -9 で消えたレビュー中のワーカーが残した形の worker.yaml を書く (pid は終わったプロセスのもの)。"""
        dead = subprocess.Popen(["true"])
        dead.wait()
        with open(self.path("worker.yaml"), "w", encoding="utf-8") as f:
            f.write(f'state: reviewing\ncurrent_request: "{RID}"\nworkspace: {json.dumps(workspace)}\npid: {dead.pid}\n')

    def put_stream(self, lines):
        p = os.path.join(os.path.dirname(self.args_file), "stream.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for line in lines:
                f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
        self.env["FAKE_CLAUDE_STREAM"] = p

    def write_user_settings(self, content, config_dir=None):
        """利用者の設定 settings.json を書く。config_dir を省略すると HOME/.claude、指定するとそのディレクトリの直下
        (環境変数 CLAUDE_CONFIG_DIR を指定したときの置き場)。content が文字列ならそのまま書く。"""
        d = config_dir if config_dir is not None else os.path.join(self.home, ".claude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    # ---- 起動と観察 ----

    def start(self, *extra, cwd=None, env=None, loop=None, shell="bash"):
        args = [shell, _WORKER, loop or self.loop, "--model", "opus", "--effort", "high", *extra]
        p = subprocess.Popen(
            args, cwd=cwd or self.repo, env=env or self.env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.procs.append(p)
        return p

    def start_unavailable(self, *extra, contains, cwd=None, env=None, loop=None):
        """起動時の確認が通らず、worker.yaml が unavailable と理由 (contains を含む) で書かれ、終了コード 2 で終わることを確かめる。"""
        loop = loop or self.loop
        yaml_path = os.path.join(loop, "worker.yaml")
        if os.path.exists(yaml_path):
            os.remove(yaml_path)
        p = self.start(*extra, cwd=cwd, env=env, loop=loop)
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2, err)
        state = _read_yaml(yaml_path)
        self.assertEqual(state["state"], "unavailable", state)
        for s in contains if isinstance(contains, (list, tuple)) else [contains]:
            self.assertIn(s, state["error"])
        self.assert_contract("## `worker.yaml`", state)
        return state

    def start_idle(self, *extra, cwd=None, env=None, loop=None):
        """起動時の確認が通り、worker.yaml が idle で書かれることを確かめ、止めて (標準出力, worker.yaml の中身) を返す。"""
        p = self.start(*extra, cwd=cwd, env=env, loop=loop)
        state = self.wait_for(
            lambda: self.worker_state().get("pid") == p.pid and self.worker_state(),
            what="この起動が worker.yaml を書くこと")
        self.assertEqual(state["state"], "idle", state)
        _, out, _ = self.finish(p)
        return out, state

    def wait_for(self, pred, timeout=20, interval=0.1, what="条件"):
        deadline = time.time() + timeout
        while time.time() < deadline:
            v = pred()
            if v:
                return v
            time.sleep(interval)
        self.fail(f"{timeout} 秒待っても{what}が成り立たない")

    def worker_state(self):
        try:
            return _read_yaml(self.path("worker.yaml"))
        except (OSError, ValueError):
            return {}

    def wait_state(self, state, timeout=20):
        return self.wait_for(lambda: self.worker_state().get("state") == state and self.worker_state(),
                             timeout=timeout, what=f"worker.yaml の state: {state}")

    def wait_marker(self, rid=RID, timeout=25):
        p = self.path(f"delivered-{rid}.yaml")
        self.wait_for(lambda: os.path.exists(p), timeout=timeout, what=f"完了の印 {rid}")
        return _read_yaml(p)

    def wait_pids(self, path, count):
        """ファイル path に PID が count 個以上書かれるのを待って、その列を返す。"""
        def ready():
            try:
                pids = _read_pids(path)
            except (OSError, ValueError):
                return None
            return pids if len(pids) >= count else None
        return self.wait_for(ready, what=f"{path} に PID が {count} 個書かれること")

    def finish(self, p, sig=signal.SIGTERM, timeout=20):
        p.send_signal(sig)
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err

    def claude_calls(self):
        if not os.path.exists(self.args_file):
            return []
        with open(self.args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def claude_records(self):
        """偽の claude が起動されたときの様子 (cwd・複製の中の git の結果・--settings・写しの中身) の列。"""
        if not os.path.exists(self.record_file):
            return []
        with open(self.record_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def workspaces(self):
        """TMPDIR の下に残っている作業場所と準備のディレクトリ (どちらも名前が review-loop- で始まる) の名前の列。"""
        return sorted(n for n in os.listdir(self.tmpdir) if n.startswith("review-loop-"))

    def run_round(self, *extra, rid=RID):
        """ワーカーを起動し、完了の印を待って止める。(完了の印, ワーカーの標準エラー) を返す。"""
        p = self.start(*extra)
        marker = self.wait_marker(rid)
        self.wait_state("idle")
        _, _, err = self.finish(p)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        return marker, err

    def assert_contract(self, heading, data):
        required, allowed = _contract_keys(heading)
        keys = set(_flatten(data))
        self.assertTrue(required, f"{heading} の表からキーを読めなかった")
        self.assertLessEqual(required, keys, f"必須のキーが無い: {sorted(required - keys)}")
        self.assertLessEqual(keys, allowed, f"表に無いキーがある: {sorted(keys - allowed)}")


def _option_values(args, name):
    """--allowedTools のような可変長の引数の値を、次の -- で始まる引数の手前まで集める。"""
    i = args.index(name)
    out = []
    for a in args[i + 1:]:
        if a.startswith("--"):
            break
        out.append(a)
    return out


def _assert_not_run_values(test, marker):
    """レビュアの実行を起動しなかった回の印も、ワーカーの版と、値が unknown のログから読む項目を持つこと (KTD15)。"""
    test.assertEqual(marker["worker_version"], _plugin_version())
    test.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "unknown"})
    test.assertEqual(marker["sandbox_blocked"], {"count": "unknown", "calls": []})


# ---- ログ (stream-json) の行。形は Claude Code 2.1.273 で実測したログに合わせる ----

def _init(mode=None, parent=None, model="claude-opus-5"):
    """init の行。mode が None なら permissionMode のキーを書かない。parent は parent_tool_use_id (sub-agent の行なら値がある)。"""
    line = {"type": "system", "subtype": "init", "model": model, "session_id": "s", "parent_tool_use_id": parent}
    if mode is not None:
        line["permissionMode"] = mode
    return line


def _tool_use(tid, name, tool_input, parent=None):
    """ツールの呼び出し (type が assistant の行の message.content の tool_use)。"""
    return {"type": "assistant", "parent_tool_use_id": parent, "session_id": "s",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}}


def _tool_result(tid, content, is_error, parent=None):
    """ツールの結果 (type が user の行の message.content の tool_result)。content は文字列か text の要素の列。"""
    return {"type": "user", "parent_tool_use_id": parent, "session_id": "s",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tid, "content": content,
                                     "is_error": is_error}]}}


_RESULT_LINE = {"type": "result", "subtype": "success", "is_error": False, "session_id": "s",
                "permission_denials": []}


class TestHappyPath(WorkerTestBase):
    def test_stdlib_named_files_in_repo_are_not_imported(self):
        # 作業側 (ワーカーのカレントディレクトリ) に標準ライブラリと同名のファイルがあっても、ワーカーの python3 はそれを読まない
        # (python3 を isolated mode (-I) で起動する)。読まれると import した時点で終わり、印が書かれない
        for name in ("json", "re", "hashlib", "stat"):
            with open(os.path.join(self.repo, f"{name}.py"), "w", encoding="utf-8") as f:
                f.write(f'raise SystemExit("作業側の {name}.py が読まれた")\n')
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "標準ライブラリと同名のファイル")
        self.put_request()
        marker, err = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        self.assertNotIn("が読まれた", err)

    def test_one_round(self):
        # AE1: idle → reviewing (識別子入り) → idle と遷移し、ok の印とログが残る
        self.env["FAKE_CLAUDE_SLEEP"] = "2"
        p = self.start()
        idle = self.wait_state("idle")
        self.assertEqual(idle["current_request"], "")
        self.assertEqual(idle["workspace"], "")
        self.assert_contract("## `worker.yaml`", idle)
        head = self.head()
        self.put_request()
        reviewing = self.wait_state("reviewing", timeout=10)
        self.assertEqual(reviewing["current_request"], RID)
        # レビュー中の worker.yaml には、起動し直したワーカーが片付けられるように、その回の作業場所のパスがある
        self.assertEqual(reviewing["workspace"], self.ws_path())
        self.assert_contract("## `worker.yaml`", reviewing)
        marker = self.wait_marker()
        self.assertEqual(self.wait_state("idle")["workspace"], "")

        self.assertEqual(marker["status"], "ok", marker)
        self.assertEqual(marker["id"], RID)
        self.assertEqual(marker["worker_version"], _plugin_version())
        self.assertEqual(marker["model"], {"specified": "opus", "effective": "opus-5"})
        self.assertEqual(marker["effort"], "high")
        self.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "auto"})
        self.assertIs(marker["skill_called"], True)
        self.assertEqual(marker["permission_denials"], {"count": 0, "tools": []})
        self.assertEqual(marker["sandbox_blocked"], {"count": 0, "calls": []})
        self.assertEqual(marker["head_before"], head)
        self.assertEqual(marker["head_after"], head)
        self.assertIs(marker["tree_clean_after"], True)
        self.assertEqual(marker["exit_code"], 0)
        self.assertEqual(marker["log"], f"{RID}.log")
        self.assertNotIn("error", marker)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        self.assertTrue(os.path.exists(self.path(f"{RID}.log")))
        self.assertEqual([n for n in os.listdir(self.loop) if n.endswith(".tmp")], [])
        self.assertEqual(self.worker_state()["rounds_served"], 1)

        # 偽の claude が受けた引数。プロンプトは作業場所の写しを指し、結果への書き込みの許可は作業場所の結果を指す
        calls = self.claude_calls()
        self.assertEqual(len(calls), 1)
        args = calls[0]
        ws = os.path.dirname(self.claude_records()[0]["cwd"])
        self.assertEqual(args[:2], ["-p", PROMPT.format(req=os.path.join(ws, f"review-request-{RID}.md"))])
        for opt, val in (("--model", "opus"), ("--effort", "high"),
                         ("--permission-mode", "auto"), ("--output-format", "stream-json")):
            self.assertEqual(args[args.index(opt) + 1], val, opt)
        self.assertIn("--verbose", args)
        self.assertIn("AskUserQuestion", _option_values(args, "--disallowedTools"))
        tools = _option_values(args, "--allowedTools")
        self.assertIn("Read", tools)
        self.assertIn("Skill", tools)
        self.assertIn("Agent", tools)
        self.assertIn("Bash(git diff:*)", tools)
        self.assertEqual(tools[-1], "Edit(/" + os.path.join(ws, f"review-{RID}.yaml") + ")")
        self.assertTrue(tools[-1].startswith("Edit(//"))
        self.assertTrue(os.path.isfile(self.path(f"review-{RID}.yaml")))
        self.assertEqual(self.workspaces(), [])

        rc, _, _ = self.finish(p)
        self.assertEqual(rc, 143)
        self.assertEqual(self.worker_state()["state"], "left")

    def test_two_requests_in_identifier_order(self):
        self.put_request(RID2)
        self.put_request(RID)
        p = self.start()
        self.wait_marker(RID)
        self.wait_marker(RID2)
        # 作業場所のパスは周回の間変わらず、写しの名前が識別子で変わる
        prompts = [c[1] for c in self.claude_calls()]
        ws = os.path.dirname(self.claude_records()[0]["cwd"])
        self.assertEqual(prompts, [
            PROMPT.format(req=os.path.join(ws, f"review-request-{RID}.md")),
            PROMPT.format(req=os.path.join(ws, f"review-request-{RID2}.md")),
        ])
        self.assertEqual([r["cwd"] for r in self.claude_records()], [os.path.join(ws, "tree")] * 2)
        self.finish(p)

    def test_extra_args_are_passed_through(self):
        self.put_request()
        p = self.start("--", "--plugin-dir", "/x/y")
        self.wait_marker()
        args = self.claude_calls()[0]
        self.assertEqual(args[-2:], ["--plugin-dir", "/x/y"])
        self.finish(p)

    def test_allowed_tools_replace_default(self):
        # 権限モードを指定すれば既定 (auto) に代わる。0.13.0 で始めた周回は default を指定して続ける
        self.put_request()
        p = self.start("--allowed-tools", "Read", "--allowed-tools", "Bash(git diff:*)",
                       "--permission-mode", "default")
        marker = self.wait_marker()
        # 偽の claude はログの init の行に受けた権限モードを書くので、実効の権限モードも default になり、食い違わない
        self.assertEqual(marker["permission_mode"], {"specified": "default", "effective": "default"})
        self.assertEqual(marker["status"], "ok", marker)
        args = self.claude_calls()[0]
        ws = os.path.dirname(self.claude_records()[0]["cwd"])
        self.assertEqual(_option_values(args, "--allowedTools"), [
            "Read", "Bash(git diff:*)", "Edit(/" + os.path.join(ws, f"review-{RID}.yaml") + ")",
        ])
        self.assertEqual(args[args.index("--permission-mode") + 1], "default")
        self.assertEqual(self.worker_state()["permission_mode"], "default")
        self.finish(p)

    def test_heartbeat_advances_during_review(self):
        # レビュアの実行中 (偽の claude が 12 秒待つ) にも、worker.yaml の更新時刻が 5 秒おきに進む
        self.env["FAKE_CLAUDE_SLEEP"] = "12"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        seen = set()
        end = time.time() + 11
        while time.time() < end:
            seen.add(os.stat(self.path("worker.yaml")).st_mtime)
            time.sleep(0.5)
        self.assertGreaterEqual(len(seen), 3, seen)
        self.wait_marker()
        self.finish(p)


class TestResultChecks(WorkerTestBase):
    def run_one(self, mode):
        self.env["FAKE_CLAUDE_MODE"] = mode
        self.put_request()
        p = self.start()
        marker = self.wait_marker()
        self.wait_state("idle")
        self.finish(p)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        return marker

    def test_empty_run_id(self):
        # AE5。failed の回でも、結果が通常のファイルなら置き場に複写する (人間が RA1 の報告から読めるように)
        marker = self.run_one("empty_run_id")
        self.assertEqual(marker["status"], "failed")
        self.assertIn("run_id mismatch", marker["error"])
        result = self.path(f"review-{RID}.yaml")
        self.assertTrue(os.path.isfile(result) and not os.path.islink(result))
        with open(result, encoding="utf-8") as f:
            self.assertIn('run_id: ""', f.read())

    def test_no_result(self):
        marker = self.run_one("no_result")
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "no result")

    def test_no_findings(self):
        marker = self.run_one("no_findings")
        self.assertEqual(marker["status"], "failed")
        self.assertIn("no findings key", marker["error"])

    def test_dirty_tree(self):
        # 偽の claude が作業側の作業ツリーのファイルを絶対パスで書き換えると、tree_clean_after が偽で failed になる
        marker = self.run_one("dirty_tree")
        self.assertEqual(marker["status"], "failed")
        self.assertIs(marker["tree_clean_after"], False)
        self.assertIn("tree not clean (README.md)", marker["error"])

    def test_loop_dir_modified(self):
        # レビュアの実行が置き場に依頼文を置くと failed にし、その依頼文をレビュアの実行に回さない
        marker = self.run_one("write_request")
        bogus = "29990101-0000-x-9-code-review-opus"
        self.assertEqual(marker["status"], "failed")
        self.assertIn(f"loop dir modified (review-request-{bogus}.md)", marker["error"])
        self.assertEqual(len(self.claude_calls()), 1)
        self.assertFalse(os.path.exists(self.path(f"delivered-{bogus}.yaml")))

    def test_loop_dir_modified_request_is_not_picked_up_later(self):
        self.env["FAKE_CLAUDE_MODE"] = "write_request"
        self.put_request()
        p = self.start()
        self.wait_marker()
        time.sleep(7)  # 探索の周期 (5 秒) を 1 回以上待つ
        self.assertEqual(len(self.claude_calls()), 1)
        self.finish(p)

    def test_loop_yaml_rewritten_during_review_is_not_a_modification(self):
        # 作業側が再開や停止のときにレビュー中に loop.yaml を書き換えても、置き場の変化として数えない
        self.env["FAKE_CLAUDE_SLEEP"] = "4"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        time.sleep(1)
        tmp = self.path(".loop.yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f'id: "{LOOP_ID}"\nrepo_dir: "{self.repo}"\nstate: stopped\n')
        os.rename(tmp, self.path("loop.yaml"))
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)

    def test_head_mismatch_does_not_run_reviewer(self):
        # AE8: 依頼文の head と HEAD が違うと、偽の claude を呼ばずに failed の印を書く
        old = self.head()
        with open(os.path.join(self.repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("a\n")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "second")
        self.put_request(head=old)
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], f"head mismatch (expected {old}, actual {self.head()})")
        self.assertEqual(self.claude_calls(), [])
        for key in ("head_after", "tree_clean_after", "exit_code", "log"):
            self.assertNotIn(key, marker)
        self.assertEqual(marker["skill_called"], "unknown")
        _assert_not_run_values(self, marker)
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)

    def test_tree_not_clean_before_review(self):
        self.put_request()
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as f:
            f.write("x\n")
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "tree not clean (README.md)")
        self.assertEqual(self.claude_calls(), [])

    def test_malformed_request(self):
        req = self.path(f"review-request-{RID}.md")
        with open(req, "w", encoding="utf-8") as f:
            f.write("# 依頼文\n\n## 出力様式\n\nhead: \"{{head}}\"\n")
        p = self.start()
        marker = self.wait_marker()
        self.finish(p)
        self.assertEqual(marker["status"], "failed")
        self.assertIn("request malformed", marker["error"])
        self.assertEqual(self.claude_calls(), [])


class TestWorkspace(WorkerTestBase):
    """回の作業場所・複製・写し・レビュアの実行の引数・結果の複写・作業場所の削除
    (worker.md の「回の処理」の手順 5〜10 と「レビュアの実行の権限」)。"""

    def assert_not_run(self, marker):
        """レビュアの実行を起動しなかった回の印で、偽の claude が呼ばれず、作業場所が残っていないこと。"""
        self.assertEqual(marker["status"], "failed", marker)
        self.assertEqual(self.claude_calls(), [])
        for key in ("head_after", "tree_clean_after", "exit_code", "log"):
            self.assertNotIn(key, marker)
        _assert_not_run_values(self, marker)
        self.assertEqual(self.workspaces(), [])

    def test_reviewer_runs_in_clone(self):
        # AE1: cwd は作業場所の tree/ で、依頼の head を detached で取り出し、remote が無い。
        # 結果は印より先に置き場に現れ、回の後に作業場所は残らない
        self.put_request()
        full = _git(self.repo, "rev-parse", "HEAD")
        p = self.start()
        marker_path = self.path(f"delivered-{RID}.yaml")
        self.wait_for(lambda: os.path.exists(marker_path), what="完了の印")
        self.assertTrue(os.path.isfile(self.path(f"review-{RID}.yaml")), "印が現れた時点で結果が置き場に無い")
        self.wait_state("idle")
        self.finish(p)
        marker = _read_yaml(marker_path)
        self.assertEqual(marker["status"], "ok", marker)

        rec = self.claude_records()[0]
        ws = os.path.dirname(rec["cwd"])
        self.assertEqual(os.path.basename(rec["cwd"]), "tree")
        self.assertEqual(os.path.dirname(ws), os.path.realpath(self.tmpdir))
        self.assertRegex(os.path.basename(ws), rf"^review-loop-{re.escape(LOOP_ID)}-[0-9a-f]{{8}}$")
        self.assertEqual(rec["head"], full)
        self.assertEqual(rec["branch"], "")
        self.assertEqual(rec["remotes"], "")
        with open(self.path(f"review-{RID}.yaml"), encoding="utf-8") as f:
            self.assertIn(f'run_id: "{RID}"', f.read())
        self.assertEqual(self.workspaces(), [])

    def test_preparation_in_separate_directory(self):
        # 複製と写しは、作業場所とは別の、新しく作った準備のディレクトリで作り、作業場所のパスに改名してからレビュアの実行を起動する。
        # 準備の間は作業場所のパスに何も無く、git は準備のディレクトリの中でだけ実行し、作業場所のパスの下では 1 度も実行しない
        # (worker.md の「回の処理」の手順 5〜8 と、不変条件)
        ws = self.ws_path()
        seen = os.path.join(self.root, "seen-at-checkout")
        git_log = os.path.join(self.root, "git-log.jsonl")
        self.install_fake_git()
        self.env["FAKE_GIT_LOG"] = git_log
        self.env["FAKE_GIT_RUN_ON"] = "checkout"
        self.env["FAKE_GIT_RUN"] = (
            f"{{ pwd -P; if [ -e {shlex.quote(ws)} ] || [ -L {shlex.quote(ws)} ]; then echo exists; else echo absent; fi; }}"
            f" > {shlex.quote(seen)}")
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)

        with open(seen, encoding="utf-8") as f:
            prep, ws_state = f.read().split()
        self.assertEqual(os.path.dirname(prep), os.path.realpath(self.tmpdir))
        self.assertRegex(os.path.basename(prep),
                         rf"^review-loop-prep-{re.escape(LOOP_ID)}-[0-9a-f]{{8}}\.[A-Za-z0-9]{{6}}$")
        # 作業場所のパスの文字列で始まらない (書き込みの許可がパスの接頭辞で判定されても、準備のディレクトリに及ばない)
        self.assertFalse(prep.startswith(ws), prep)
        self.assertEqual(ws_state, "absent", "準備の途中に作業場所のパスに何かがある")

        # ワーカーが実行した git (偽の claude が実行したものを除く)
        with open(git_log, encoding="utf-8") as f:
            runs = [json.loads(line) for line in f if line.strip()]
        runs = [(where, sub) for where, sub, caller in runs if caller != "fake-claude"]
        in_prep = [sub for where, sub in runs if where == prep or where.startswith(prep + "/")]
        self.assertEqual(in_prep, ["clone", "remote", "fetch", "checkout", "ls-files"])
        self.assertEqual([r for r in runs if r[0] == ws or r[0].startswith(ws + "/")], [])

        # レビュアの実行の時点では、複製・写し・書き込みの許可はどれも作業場所のパスに揃っていて、準備のディレクトリを指さない
        rec = self.claude_records()[0]
        self.assertEqual(rec["cwd"], os.path.join(ws, "tree"))
        self.assertEqual(rec["head"], _git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(rec["request_path"], os.path.join(ws, f"review-request-{RID}.md"))
        self.assertIn(f"出力先: `{ws}/review-{RID}.yaml`", rec["request"])
        self.assertNotIn(prep, rec["request"])
        self.assertEqual(rec["settings"][0]["sandbox"]["filesystem"]["allowWrite"], [ws])
        self.assertNotIn(prep, json.dumps(self.claude_calls()[0], ensure_ascii=False))
        self.assertFalse(os.path.lexists(prep))
        self.assertEqual(self.workspaces(), [])

    def test_workspace_path_taken_before_rename(self):
        # 前の回のレビュアの実行が残したプロセスが、準備の間に作業場所のパスを作り直した (偽の git の checkout の途中に作る) とき、
        # シンボリックリンクと空でないディレクトリなら、リンクの先を変えずに改名が失敗し、レビュアの実行を起動せずに failed の印を書く。
        # 空のディレクトリなら改名で置き換わり、その回は通る
        ws = self.ws_path()
        victim = os.path.join(self.root, "victim")
        os.makedirs(victim)
        with open(os.path.join(victim, "keep.txt"), "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        os.chmod(victim, 0o755)
        self.install_fake_git()
        self.env["FAKE_GIT_RUN_ON"] = "checkout"
        q = shlex.quote(ws)
        cases = (
            ("シンボリックリンク", f"ln -s {shlex.quote(victim)} {q}", False),
            ("空でないディレクトリ", f"mkdir {q} && echo planted > {q}/planted.txt", False),
            ("空のディレクトリ", f"mkdir {q}", True),
        )
        for label, command, passes in cases:
            with self.subTest(label):
                self.reset_loop()
                self.env["FAKE_GIT_RUN"] = command
                self.put_request()
                marker, _ = self.run_round()
                if passes:
                    self.assertEqual(marker["status"], "ok", marker)
                    self.assertEqual(self.claude_records()[0]["cwd"], os.path.join(ws, "tree"))
                    self.assertEqual(self.workspaces(), [])
                else:
                    self.assert_not_run(marker)
                    self.assertTrue(marker["error"].startswith(f"workspace failed (rename to {ws}: "), marker["error"])
                self.assertEqual(os.listdir(victim), ["keep.txt"])
                self.assertEqual(stat.S_IMODE(os.stat(victim).st_mode), 0o755)

    def test_reviewer_arguments(self):
        # AE1: --permission-mode auto・--strict-mcp-config・--setting-sources user,project・--settings (1 つ)・拒否の規則・
        # 結果への書き込みの許可。
        # --settings では、サンドボックスの制限を外す真偽値のキー (allowAppleEvents・filesystem.disabled・
        # network.allowAllUnixSockets) を false にする
        cache = os.path.join(self.root, "cache")
        self.put_request()
        marker, _ = self.run_round("--sandbox-allow-write", cache,
                                   "--sandbox-allowed-domain", "proxy.golang.org",
                                   "--sandbox-allowed-domain", "sum.golang.org")
        self.assertEqual(marker["status"], "ok", marker)
        args = self.claude_calls()[0]
        rec = self.claude_records()[0]
        clone = rec["cwd"]
        ws = os.path.dirname(clone)
        self.assertEqual(args[args.index("--permission-mode") + 1], "auto")
        self.assertIn("--strict-mcp-config", args)
        # 複製のローカルの設定 (.claude/settings.local.json) を読ませない
        self.assertEqual(args[args.index("--setting-sources") + 1], "user,project")
        self.assertEqual(args.count("--settings"), 1)
        self.assertEqual(rec["settings"], [{
            "sandbox": {
                "enabled": True,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
                "failIfUnavailable": True,
                "allowAppleEvents": False,
                "filesystem": {"allowWrite": [ws, cache], "disabled": False},
                "network": {"strictAllowlist": True, "allowedDomains": ["proxy.golang.org", "sum.golang.org"],
                            "allowAllUnixSockets": False},
            },
            "autoMemoryEnabled": False,
        }])
        self.assertEqual(_option_values(args, "--disallowedTools"), [
            "AskUserQuestion",
            "Edit(~/**)",
            f"Edit(/{self.repo}/**)",
            f"Edit(/{self.loop}/**)",
            f"Edit(/{clone}/.claude/**)",
            f"Edit(/{clone}/.git/**)",
            f"Edit(/{clone}/.mcp.json)",
            "Bash(git push:*)",
        ])
        tools = _option_values(args, "--allowedTools")
        self.assertEqual(tools[-1], f"Edit(/{ws}/review-{RID}.yaml)")

    def test_extra_settings_are_merged(self):
        # 追加の引数の --settings (enabledPlugins だけ) は、ワーカーの --settings に合成して 1 つだけ渡す。--plugin-dir はそのまま渡す
        plugin = os.path.join(self.root, "plugin")
        os.makedirs(plugin)
        self.put_request()
        marker, _ = self.run_round("--", "--plugin-dir", plugin, "--settings",
                                   json.dumps({"enabledPlugins": {"review-triage@akm": False}}))
        self.assertEqual(marker["status"], "ok", marker)
        args = self.claude_calls()[0]
        self.assertEqual(args.count("--settings"), 1)
        self.assertEqual(args[-2:], ["--plugin-dir", plugin])
        settings = self.claude_records()[0]["settings"]
        self.assertEqual(len(settings), 1)
        self.assertEqual(settings[0]["enabledPlugins"], {"review-triage@akm": False})
        self.assertIs(settings[0]["sandbox"]["enabled"], True)
        self.assertIs(settings[0]["sandbox"]["allowUnsandboxedCommands"], False)
        self.assertIs(settings[0]["autoMemoryEnabled"], False)

    def test_sandbox_boolean_keys_are_overridden_not_checked(self):
        # 利用者の設定とブランチの設定で、サンドボックスの制限を外す真偽値のキーが true でも、回は止めない。
        # --settings はそれらの設定より優先されるので、ワーカーは false を渡して値を上書きする
        # (worker.md の「サンドボックス」)
        loose = {"sandbox": {"allowAppleEvents": True, "filesystem": {"disabled": True},
                             "network": {"allowAllUnixSockets": True}}}
        self.write_user_settings(loose)
        path = os.path.join(self.repo, ".claude", "settings.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(loose, f)
        _git(self.repo, "add", ".claude/settings.json")
        _git(self.repo, "commit", "-q", "-m", "settings")
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        sandbox = self.claude_records()[0]["settings"][0]["sandbox"]
        self.assertIs(sandbox["allowAppleEvents"], False)
        self.assertIs(sandbox["filesystem"]["disabled"], False)
        self.assertIs(sandbox["network"]["allowAllUnixSockets"], False)

    def test_request_copy(self):
        # AE1: プロンプトが指す写しには、元の出力先と元の作業ツリーのパスが無く、扱いの行が「使い捨て」。作業側の依頼文は変わらない
        self.put_request()
        req = self.path(f"review-request-{RID}.md")
        with open(req, "rb") as f:
            before = f.read()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        rec = self.claude_records()[0]
        clone = rec["cwd"]
        ws = os.path.dirname(clone)
        self.assertEqual(rec["request_path"], os.path.join(ws, f"review-request-{RID}.md"))
        text = rec["request"]
        self.assertNotIn(self.path(f"review-{RID}.yaml"), text)
        self.assertNotIn(self.repo, text)
        self.assertEqual(re.findall(r"^- 作業ツリーの扱い:.*$", text, re.M), ["- 作業ツリーの扱い: 使い捨て"])
        self.assertIn(f"出力先: `{ws}/review-{RID}.yaml`", text)
        self.assertIn(f"(作業ツリー: `{clone}`)", text)
        with open(req, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_branch_names_resolve_in_clone(self):
        # AE2: 作業側が feature ブランチにいて main が別のコミットを指すとき、複製の中でもブランチ・リモート追跡ブランチ・
        # タグが作業側と同じコミットに解決できる。作業側のブランチを取り出したままでも、複製の作成が失敗しない
        main = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "tag", "v1")
        _git(self.repo, "update-ref", "refs/remotes/origin/main", main)
        _git(self.repo, "checkout", "-q", "-b", "feat/x")
        with open(os.path.join(self.repo, "b.txt"), "w", encoding="utf-8") as f:
            f.write("b\n")
        _git(self.repo, "add", "b.txt")
        _git(self.repo, "commit", "-q", "-m", "feature")
        feat = _git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(feat, main)
        self.env["FAKE_CLAUDE_REVS"] = "main origin/main v1 feat/x"
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        rec = self.claude_records()[0]
        self.assertEqual(rec["revs"], {"main": main, "origin/main": main, "v1": main, "feat/x": feat})
        self.assertEqual(rec["head"], feat)
        self.assertEqual(rec["branch"], "")

    def test_request_copy_cannot_be_made(self):
        # AE6: 扱いの行が無い (0.13.0 の依頼文)・2 つある・出力先が置き場を指さない・作業ツリーのパスが無い依頼文では、
        # レビュアの実行を起動せずに failed の印を書き、作業場所を残さない
        line = "- 作業ツリーの扱い: 共有\n"
        cases = (
            ("扱いの行が無い", lambda t: t.replace(line, ""), "handling lines: 0"),
            ("扱いの行が 2 つ", lambda t: t.replace(line, line + line), "handling lines: 2"),
            ("出力先が置き場を指さない",
             lambda t: t.replace(self.path(f"review-{RID}.yaml"), os.path.join(self.root, f"review-{RID}.yaml")),
             "output path does not point to the loop dir"),
            ("作業ツリーのパスが無い", lambda t: t.replace(f"`{self.repo}`", "`/nowhere`"), "worktree path not found"),
        )
        for label, change, contains in cases:
            with self.subTest(label):
                self.reset_loop()
                text = self.request_text()
                changed = change(text)
                self.assertNotEqual(changed, text)
                self.put_request(text=changed)
                marker, _ = self.run_round()
                self.assert_not_run(marker)
                self.assertIn("request copy failed", marker["error"])
                self.assertIn(contains, marker["error"])

    def test_clone_stage_failure(self):
        # AE7: 複製の作成の段 (複製・remote の設定の削除・取り込み・チェックアウト) のどれかが失敗すると、
        # レビュアの実行を起動せずに failed の印を書き、error に失敗した段を書く。作業場所は残らない
        self.install_fake_git()
        for sub, stage in (("clone", "clone"), ("remote", "remove remote"), ("fetch", "fetch refs"),
                           ("checkout", "checkout")):
            with self.subTest(stage):
                self.reset_loop()
                self.env["FAKE_GIT_FAIL"] = sub
                self.put_request()
                marker, _ = self.run_round()
                self.assert_not_run(marker)
                self.assertTrue(marker["error"].startswith(f"clone failed ({stage}: "), marker["error"])
                self.assertIn("偽の git", marker["error"])

    def test_submodule(self):
        # 複製に submodule の項目 (モード 160000) があれば、複製の作成の失敗とする (submodule はサポートしない)
        sha = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},sub")
        _git(self.repo, "commit", "-q", "-m", "submodule")
        os.makedirs(os.path.join(self.repo, "sub"))  # 取り出していない submodule の形にして、作業ツリーを clean にする
        self.put_request()
        marker, _ = self.run_round()
        self.assert_not_run(marker)
        self.assertEqual(marker["error"], "clone failed (submodule: sub)")

    def test_clone_settings(self):
        # AE16: 複製の .claude/settings.json か .claude/settings.local.json に、空でない sandbox.excludedCommands か
        # sandbox.network.allowUnixSockets があるか、sandbox.network.allowLocalBinding が偽でないか、JSON として読めなければ、
        # レビュアの実行を起動せずに failed の印を書く
        sockets = json.dumps({"sandbox": {"network": {"allowUnixSockets": ["/var/run/docker.sock"]}}})
        binding = json.dumps({"sandbox": {"network": {"allowLocalBinding": True}}})
        cases = (
            ("excludedCommands", ".claude/settings.json", json.dumps({"sandbox": {"excludedCommands": ["docker"]}}),
             "sandbox.excludedCommands"),
            ("JSON として読めない", ".claude/settings.local.json", "{ not json", "not readable as JSON"),
            ("allowUnixSockets", ".claude/settings.json", sockets,
             'sandbox.network.allowUnixSockets is not empty (["/var/run/docker.sock"])'),
            ("allowUnixSockets (local)", ".claude/settings.local.json", sockets,
             'sandbox.network.allowUnixSockets is not empty (["/var/run/docker.sock"])'),
            ("allowLocalBinding", ".claude/settings.json", binding,
             "sandbox.network.allowLocalBinding is not false (true)"),
            ("allowLocalBinding (local)", ".claude/settings.local.json", binding,
             "sandbox.network.allowLocalBinding is not false (true)"),
            ("allowLocalBinding が真偽値でない", ".claude/settings.json",
             json.dumps({"sandbox": {"network": {"allowLocalBinding": "true"}}}),
             'sandbox.network.allowLocalBinding is not false ("true")'),
        )
        for label, rel, content, contains in cases:
            with self.subTest(label):
                self.reset_loop()
                path = os.path.join(self.repo, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                _git(self.repo, "add", "-f", rel)
                _git(self.repo, "commit", "-q", "-m", f"add {rel}")
                self.put_request()
                marker, _ = self.run_round()
                self.assert_not_run(marker)
                self.assertIn(f"clone settings ({rel}: ", marker["error"])
                self.assertIn(contains, marker["error"])
                _git(self.repo, "rm", "-q", rel)
                _git(self.repo, "commit", "-q", "-m", f"remove {rel}")

    def test_clone_settings_without_excluded_commands(self):
        # 空の sandbox.excludedCommands と sandbox.network.allowUnixSockets、偽の sandbox.network.allowLocalBinding は止めない。
        # 検査しないキー (sandbox.enableWeakerNetworkIsolation) も止めない
        path = os.path.join(self.repo, ".claude", "settings.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"sandbox": {"excludedCommands": [], "enableWeakerNetworkIsolation": True,
                                   "network": {"allowUnixSockets": [], "allowLocalBinding": False}},
                       "permissions": {"deny": ["Bash(rm:*)"]}}, f)
        _git(self.repo, "add", ".claude/settings.json")
        _git(self.repo, "commit", "-q", "-m", "settings")
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)

    def test_reviewer_git_config_is_not_run(self):
        # AE12: レビュアの実行が複製の .git/config に core.fsmonitor・core.hooksPath・filter.<名前>.clean を書き、
        # .git/hooks/post-checkout を置いても、ワーカーはどれも実行しない (レビュアの実行の後に、複製の中で git を使わない)
        mark = os.path.join(self.root, "git-mark")
        self.env["FAKE_CLAUDE_MODE"] = "git_config"
        self.env["FAKE_CLAUDE_GIT_MARK"] = mark
        self.put_request()
        marker, _ = self.run_round()
        self.assertTrue(os.path.exists(mark + "-written"), "偽の claude が複製の git の設定を書いていない")
        for kind in ("fsmonitor", "hooksPath", "clean", "post-checkout"):
            self.assertFalse(os.path.exists(f"{mark}-{kind}"), f"{kind} のコマンドが実行された")
        self.assertEqual(marker["status"], "ok", marker)
        self.assertEqual(self.workspaces(), [])

    def test_reviewer_writes_loop_result_directly(self):
        # AE13: レビュアの実行が置き場の出力先に直接書くと、置き場が変わったとして failed
        self.env["FAKE_CLAUDE_MODE"] = "write_loop_result"
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "failed")
        self.assertIn(f"loop dir modified (review-{RID}.yaml)", marker["error"])

    def test_result_copy_failure(self):
        # AE15: 置き場の結果の一時名の場所にディレクトリがあると複写が失敗し、failed の印の error に複写の失敗を書く。ok の印は書かない
        os.makedirs(self.path(f".review-{RID}.yaml.tmp"))
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "failed")
        self.assertTrue(marker["error"].startswith("result copy failed ("), marker["error"])
        self.assertFalse(os.path.exists(self.path(f"review-{RID}.yaml")))
        self.assertEqual(self.workspaces(), [])

    def test_result_file_conditions(self):
        # 結果がシンボリックリンク・FIFO・ディレクトリのとき、実体が作業場所の外にあるとき、大きさが上限を越えるときに、
        # 止まらずに failed の印を書き、結果を置き場に複写しない
        outside = os.path.join(self.root, "outside-result.yaml")
        self.env["FAKE_CLAUDE_OUTSIDE"] = outside
        cases = (
            ("シンボリックリンク", "result_symlink", "result not a regular file (symbolic link)"),
            ("実体が作業場所の外", "result_symlink_outside", "result outside workspace"),
            ("FIFO", "result_fifo", "result not a regular file (FIFO)"),
            ("ディレクトリ", "result_dir", "result not a regular file (directory)"),
            ("上限を越える大きさ", "result_large", "result too large"),
        )
        for label, mode, contains in cases:
            with self.subTest(label):
                self.reset_loop()
                self.env["FAKE_CLAUDE_MODE"] = mode
                self.put_request()
                marker, _ = self.run_round()
                self.assertEqual(marker["status"], "failed", marker)
                self.assertIn(contains, marker["error"])
                self.assertFalse(os.path.lexists(self.path(f"review-{RID}.yaml")))
                self.assertEqual(self.workspaces(), [])

    def test_end_during_preparation(self):
        # 準備の途中 (複製の作成中) に置き場に end が現れた回は、failed・loop dir modified の印を書いてから、end を見て終わる
        self.install_fake_git()
        self.env["FAKE_GIT_TOUCH_ON"] = "clone"
        self.env["FAKE_GIT_TOUCH"] = self.path("end")
        self.put_request()
        p = self.start()
        marker = self.wait_marker()
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(marker["status"], "failed")
        self.assertIn("loop dir modified (end)", marker["error"])

    def test_workspace_replaced_by_symlink(self):
        # レビュアの実行が作業場所をシンボリックリンクに置き換えても、リンクの先は消さない。
        # 次の回は、残ったリンクだけを消して作業場所を作り直す
        target = os.path.join(self.root, "link-target")
        os.makedirs(target)
        keep = os.path.join(target, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        self.env["FAKE_CLAUDE_MODE"] = "symlink_workspace"
        self.env["FAKE_CLAUDE_LINK_TARGET"] = target
        self.put_request()
        marker, err = self.run_round()
        ws = os.path.dirname(self.claude_records()[0]["cwd"])
        self.assertEqual(marker["status"], "failed", marker)
        self.assertIn("result outside workspace", marker["error"])
        self.assertTrue(os.path.islink(ws))
        self.assertTrue(os.path.exists(keep))
        self.assertTrue(os.path.exists(os.path.join(target, f"review-{RID}.yaml")))
        self.assertIn(ws, err)

        self.env["FAKE_CLAUDE_MODE"] = "ok"
        self.put_request(RID2)
        marker, _ = self.run_round(rid=RID2)
        self.assertEqual(marker["status"], "ok", marker)
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.lexists(ws))

    def test_leftover_process_is_stopped(self):
        # 正常に終わったレビュアの実行が、別のプロセスグループで cwd が複製の中の子を残しても、回の後にその子は残らない
        self.env["FAKE_CLAUDE_MODE"] = "leave_child"
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        child = _read_pids(self.pids_file)[0]
        self.wait_for(lambda: not _pid_alive(child), timeout=3, what=f"残した子 {child} の終了")
        self.assertEqual(self.workspaces(), [])

    def test_readonly_directory(self):
        # 作業場所の中に読み取り専用のディレクトリがあっても、回の後に作業場所は残らない。印の exit_code は偽の claude の終了コードのまま
        self.env["FAKE_CLAUDE_MODE"] = "readonly_dir"
        self.env["FAKE_CLAUDE_EXIT"] = "5"
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)
        self.assertEqual(marker["exit_code"], 5)
        self.assertEqual(self.workspaces(), [])

    def make_outside_readonly_dir(self):
        """作業場所の外に、所有者の書き込みの権限が無いディレクトリ (中にファイルが 1 つ) を作ってパスを返す。"""
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "keep.txt"), "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        os.chmod(outside, 0o555)
        return outside

    def remove_workspace_at_end(self, fill):
        """ワーカーを idle にし、関数 fill で作業場所の中身を作ってから end を置いて、ワーカーが作業場所を消して終わるのを待つ。"""
        p = self.start()
        self.wait_state("idle")
        fill(self.ws_path())
        open(self.path("end"), "w").close()
        _, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        self.assertFalse(os.path.lexists(self.ws_path()), err)
        return err

    def test_removal_does_not_change_symlink_targets(self):
        # 作業場所を消すときに所有者の権限を足すのは、作業場所の中のディレクトリだけで、シンボリックリンクの先 (作業場所の外) の
        # 権限は変えない。読み取り専用のディレクトリは消せる
        outside = self.make_outside_readonly_dir()

        def fill(ws):
            os.makedirs(os.path.join(ws, "tree", "ro", "sub"))
            os.symlink(outside, os.path.join(ws, "tree", "ro", "link"))
            os.symlink(outside, os.path.join(ws, "link-top"))
            os.chmod(os.path.join(ws, "tree", "ro", "sub"), 0o555)
            os.chmod(os.path.join(ws, "tree", "ro"), 0o555)

        self.remove_workspace_at_end(fill)
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), 0o555)
        self.assertEqual(os.listdir(outside), ["keep.txt"])

    def test_removal_does_not_follow_symlink_swapped_in(self):
        # 作業場所の中のディレクトリを、確かめてから chmod するまでの間にシンボリックリンクに置き換えられても (前の回のレビュアの実行が
        # 残したプロセスの書き込みを、偽の python3 の前置きで起こす)、リンクの先の権限を変えない
        if os.chmod not in os.supports_follow_symlinks:
            self.skipTest("この OS には lchmod が無い (chmod でシンボリックリンクを辿らない方法を、macOS でだけ確かめられる)")
        outside = self.make_outside_readonly_dir()
        done = os.path.join(self.root, "swap-done")
        self.prelude_python("add_owner_rwx", _SWAP_PRELUDE)
        self.env["FAKE_PY_SWAP_TARGET"] = outside
        self.env["FAKE_PY_SWAP_DONE"] = done

        def fill(ws):
            os.makedirs(os.path.join(ws, "tree", "victim"))
            os.chmod(os.path.join(ws, "tree", "victim"), 0o555)

        self.remove_workspace_at_end(fill)
        self.assertTrue(os.path.exists(done), "作業場所を消す途中で、ディレクトリをシンボリックリンクに置き換えていない")
        self.assertEqual(stat.S_IMODE(os.stat(outside).st_mode), 0o555)
        self.assertEqual(os.listdir(outside), ["keep.txt"])


class TestLogReading(WorkerTestBase):
    def run_with_stream(self, lines):
        self.put_stream(lines)
        self.put_request()
        marker, _ = self.run_round()
        return marker

    def test_permission_denials(self):
        marker = self.run_with_stream([
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
            {"type": "result", "subtype": "success", "permission_denials": [
                {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "make test"}},
                {"tool_name": "Write", "tool_use_id": "t2", "tool_input": {}},
            ]},
        ])
        self.assertEqual(marker["permission_denials"], {"count": 2, "tools": ["Bash", "Write"]})
        self.assertEqual(marker["skill_called"], "unknown")

    def test_no_result_line_is_unknown(self):
        # result の行が無い (実行が最後まで行かなかった) ログでは、拒否の件数も、サンドボックスが止めた件数も unknown。
        # 止められた呼び出しがあっても、件数が unknown なら calls は空
        marker = self.run_with_stream([
            {"type": "system", "subtype": "init", "model": "claude-opus-5"},
            _tool_use("toolu_1", "Bash", {"command": "touch /Users/x/y"}),
            _tool_result("toolu_1", "touch: /Users/x/y: Operation not permitted", True),
        ])
        self.assertEqual(marker["permission_denials"], {"count": "unknown", "tools": []})
        self.assertEqual(marker["sandbox_blocked"], {"count": "unknown", "calls": []})

    def test_subagent_lines_and_tool_results_are_ignored(self):
        marker = self.run_with_stream([
            "hook の出力など JSON でない行",
            {"type": "system", "subtype": "init", "model": "claude-haiku-4-5",
             "parent_tool_use_id": "toolu_sub"},
            {"type": "system", "subtype": "init", "model": "claude-opus-5", "parent_tool_use_id": None},
            {"type": "assistant", "parent_tool_use_id": None,
             "message": {"content": [{"type": "text", "text": "Skill を呼ばずに読む"}]}},
            {"type": "assistant", "parent_tool_use_id": "toolu_sub",
             "message": {"model": "claude-haiku-4-5",
                         "content": [{"type": "tool_use", "name": "Skill", "input": {}}]}},
            {"type": "user", "parent_tool_use_id": None,
             "message": {"content": [{"type": "tool_result",
                                      "content": '{"name":"Skill","model":"claude-sonnet-5"}'}]}},
            {"type": "result", "subtype": "success", "permission_denials": []},
        ])
        self.assertEqual(marker["model"]["effective"], "opus-5")
        self.assertIs(marker["skill_called"], False)
        self.assertEqual(marker["status"], "ok")

    def test_no_init_line_is_unknown(self):
        marker = self.run_with_stream(["not json"])
        self.assertEqual(marker["model"]["effective"], "unknown")
        self.assertEqual(marker["skill_called"], "unknown")

    # ---- 実効の権限モード (worker.md の「ログの読み方」) ----

    def test_permission_mode_mismatch(self):
        # AE4: 偽の claude が init の行の permissionMode に default を書く (auto モードを使えなかった) と、指定 (既定の auto) と
        # 違うので failed。error に期待したモードと実際のモードを書き、印の permission_mode に指定と実効を書く
        self.env["FAKE_CLAUDE_PERMISSION_MODE"] = "default"
        self.put_request()
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "failed", marker)
        self.assertEqual(marker["error"], "permission mode mismatch (expected auto, actual default)")
        self.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "default"})
        # failed の回でも、結果が通常のファイルなら置き場に複写する
        self.assertTrue(os.path.isfile(self.path(f"review-{RID}.yaml")))

    def test_permission_mode_without_init_line_is_unknown(self):
        # init の行が無ければ実効の権限モードは unknown で、それだけでは failed にしない
        marker = self.run_with_stream([
            _tool_use("toolu_skill", "Skill", {"skill": "code-review"}),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "unknown"})
        self.assertEqual(marker["status"], "ok", marker)

    def test_permission_mode_ignores_subagent_init_line(self):
        # sub-agent の init の行 (parent_tool_use_id がある) は使わない。最上位の init の行より前に置いて、
        # parent_tool_use_id を見ずに最初の init の行を読む誤りも検出できるようにする
        marker = self.run_with_stream([
            _init("auto", parent="toolu_agent"),
            _init("default"),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "default"})
        self.assertEqual(marker["status"], "failed", marker)
        self.assertEqual(marker["error"], "permission mode mismatch (expected auto, actual default)")

    def test_permission_mode_ignores_init_json_in_tool_result(self):
        # Bash の結果の本文に init の行の JSON (permissionMode が auto) があっても、実効の権限モードは最上位の init の行から読む。
        # Bash で出力した JSON の行は tool_result の文字列の中に入り、ログの行としては現れない (実測)
        marker = self.run_with_stream([
            _init("default"),
            _tool_use("toolu_echo", "Bash", {"command": "cat fake-init.json"}),
            _tool_result("toolu_echo", json.dumps(_init("auto")), False),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["permission_mode"], {"specified": "auto", "effective": "default"})
        self.assertEqual(marker["status"], "failed", marker)

    # ---- サンドボックスが止めた確認 (worker.md の「サンドボックスが止めた確認の数え方」) ----

    def test_sandbox_blocked_top_level_and_subagent(self):
        # AE5: 最上位の Bash の結果 (本文の文面は小文字) と、sub-agent の中の Bash の結果 (大文字で始まる) の 2 件を数え、
        # それぞれのコマンドと、本文のうち文面を含む行を印に書く。本文の形は実測したもの
        marker = self.run_with_stream([
            _init("auto"),
            _tool_use("toolu_top", "Bash", {"command": "touch /Users/x/probe.txt", "description": "プローブを置く"}),
            _tool_result("toolu_top", "Exit code 1\n(eval):1: operation not permitted: /Users/x/probe.txt", True),
            _tool_use("toolu_agent", "Agent", {"description": "確かめる", "prompt": "調べる"}),
            _tool_use("toolu_sub", "Bash", {"command": "touch /Users/x/y"}, parent="toolu_agent"),
            _tool_result("toolu_sub", "touch: /Users/x/y: Operation not permitted", True, parent="toolu_agent"),
            _tool_result("toolu_agent", [{"type": "text", "text": "調べた"}], False),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["sandbox_blocked"], {"count": 2, "calls": [
            {"command": "touch /Users/x/probe.txt",
             "message": "(eval):1: operation not permitted: /Users/x/probe.txt"},
            {"command": "touch /Users/x/y",
             "message": "touch: /Users/x/y: Operation not permitted"},
        ]})
        # サンドボックスが止めた確認は failed の条件にしない (その回を使うかは作業側が突き合わせで決める)
        self.assertEqual(marker["status"], "ok", marker)

    def test_sandbox_blocked_network_and_text_elements(self):
        # 接続を止められた結果 (本文に <sandbox_violations> のタグ) も数え、message にタグの中の行 (止められたホスト) を書く。
        # 本文が text の要素の列の形の結果も数える
        marker = self.run_with_stream([
            _init("auto"),
            _tool_use("toolu_net", "Bash", {"command": "curl -sS https://example.com/"}),
            _tool_result("toolu_net",
                         "Exit code 56\ncurl: (56) CONNECT tunnel failed, response 403\n"
                         "<sandbox_violations>\ndeny network-outbound example.com:443 (host is not on the allow list)",
                         True),
            _tool_use("toolu_py", "Bash", {"command": "python3 probe.py"}),
            _tool_result("toolu_py", [{"type": "text", "text":
                                       "Exit code 1\nTraceback (most recent call last):\n"
                                       "PermissionError: [Errno 1] Operation not permitted: '/Users/x/z'"}], True),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["sandbox_blocked"], {"count": 2, "calls": [
            {"command": "curl -sS https://example.com/",
             "message": "<sandbox_violations> deny network-outbound example.com:443 (host is not on the allow list)"},
            {"command": "python3 probe.py",
             "message": "PermissionError: [Errno 1] Operation not permitted: '/Users/x/z'"},
        ]})

    def test_sandbox_blocked_ignores_other_tools(self):
        # Bash 以外 (Read) の結果は、同じ文面があっても数えない。
        # 対応する tool_use の無い結果も、ツールが Bash と分からないので数えない
        marker = self.run_with_stream([
            _init("auto"),
            _tool_use("toolu_read", "Read", {"file_path": "/Users/x/secret"}),
            _tool_result("toolu_read", "EPERM: operation not permitted, open '/Users/x/secret'", True),
            _tool_result("toolu_nowhere", "touch: /Users/x/y: Operation not permitted", True),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["sandbox_blocked"], {"count": 0, "calls": []})
        self.assertEqual(marker["status"], "ok", marker)

    def test_sandbox_blocked_counts_successful_results(self):
        # is_error が偽の Bash の結果も、文面があれば数える。通し確認 (2026-09-28) で、出力を | tail に渡したコマンドと
        # ; echo で終わるコマンドは、止められても成功で終わった。文面を含む文書を grep しただけの結果も数える
        # (見落として記録に入れるより、止めて人間が報告を読む方を選ぶ)
        go = "cd tree/tools && go test ./... 2>&1 | tail -30"
        cat = "cat > /tmp/t_test.go <<'EOF'\npackage main\nEOF\necho skip"
        grep = "grep -rn 'operation not permitted' ."
        marker = self.run_with_stream([
            _init("auto"),
            _tool_use("toolu_go", "Bash", {"command": go}),
            _tool_result("toolu_go",
                         "# example.com/m\nopen /Users/x/Library/Caches/go-build/4c/4c9c-d: operation not permitted\n"
                         "FAIL\texample.com/m [setup failed]\nFAIL", False),
            _tool_use("toolu_cat", "Bash", {"command": cat}),
            _tool_result("toolu_cat", "(eval):1: operation not permitted: /tmp/t_test.go\nskip", False),
            _tool_use("toolu_grep", "Bash", {"command": grep}),
            _tool_result("toolu_grep", "worker.md:330:(eval):1: operation not permitted: <パス>", False),
            _RESULT_LINE,
        ])
        self.assertEqual(marker["sandbox_blocked"], {"count": 3, "calls": [
            {"command": go,
             "message": "open /Users/x/Library/Caches/go-build/4c/4c9c-d: operation not permitted"},
            {"command": "cat > /tmp/t_test.go <<'EOF' package main EOF echo skip",
             "message": "(eval):1: operation not permitted: /tmp/t_test.go"},
            {"command": grep, "message": "worker.md:330:(eval):1: operation not permitted: <パス>"},
        ]})
        # サンドボックスが止めた確認を failed の条件にしないのは今までどおり (RA1 にするのは作業側)
        self.assertEqual(marker["status"], "ok", marker)

    def test_sandbox_blocked_values_are_one_line(self):
        # 改行・タブ・引用符・バックスラッシュ・制御文字・行の区切りの文字・対になっていないサロゲート (JSON の \ud800 の
        # エスケープから入る、2 つ組で 1 文字を表す符号の片方) を含むコマンドと本文も、
        # 印の YAML を壊さずに 1 行で書く (_read_yaml は二重引用符の文字列を JSON として読むので、エスケープの誤りも例外になる)。
        # コマンドと文面は先頭 200 文字で切る
        tricky = ("cat <<'EOF' > ~/probe.txt\n\"quoted\" and \\backslash\\\tTab\x01\x7f\x85\u2028\ud800 日本語\nEOF\n")
        long_command = "echo " + "x" * 300 + " > ~/long.txt"
        long_message = "touch: /Users/x/" + "y" * 300 + ": Operation not permitted"
        marker = self.run_with_stream([
            _init("auto"),
            _tool_use("toolu_1", "Bash", {"command": tricky}),
            _tool_result("toolu_1", "Exit code 1\n(eval):1: operation not permitted: /Users/x/\"q\"\\probe.txt", True),
            _tool_use("toolu_2", "Bash", {"command": long_command}),
            _tool_result("toolu_2", long_message, True),
            _RESULT_LINE,
        ])
        calls = marker["sandbox_blocked"]["calls"]
        self.assertEqual(marker["sandbox_blocked"]["count"], 2)
        # 改行・タブ・制御文字・行の区切りの文字・サロゲートは 1 文字ずつ空白にし、前後の空白を除く
        self.assertEqual(calls[0], {
            "command": "cat <<'EOF' > ~/probe.txt \"quoted\" and \\backslash\\ Tab" + " " * 6 + "日本語 EOF",
            "message": "(eval):1: operation not permitted: /Users/x/\"q\"\\probe.txt",
        })
        self.assertEqual(calls[1], {"command": long_command[:200], "message": long_message[:200]})
        self.assertEqual(len(calls[1]["command"]), 200)


class TestStartChecks(WorkerTestBase):
    def test_other_worktree(self):
        # AE6
        wt = os.path.join(os.path.dirname(self.repo), "wt")
        _git(self.repo, "worktree", "add", "-q", "-b", "wt", wt)
        p = self.start(cwd=wt)
        _, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        state = self.worker_state()
        self.assertEqual(state["state"], "unavailable")
        self.assertIn("別の worktree", state["error"])
        self.assert_contract("## `worker.yaml`", state)

    def test_other_repository(self):
        other = os.path.join(os.path.dirname(self.repo), "other")
        os.makedirs(other)
        _git(other, "init", "-q")
        p = self.start(cwd=other)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("別の作業ツリー", self.worker_state()["error"])

    def test_end_exists(self):
        open(self.path("end"), "w").close()
        p = self.start()
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.worker_state()["state"], "unavailable")
        self.assertIn("end", self.worker_state()["error"])

    def test_missing_loop_yaml(self):
        os.remove(self.path("loop.yaml"))
        p = self.start()
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("loop.yaml", self.worker_state()["error"])

    def test_claude_missing(self):
        tools = os.path.join(os.path.dirname(self.repo), "tools")
        os.makedirs(tools)
        os.symlink(shutil.which("git"), os.path.join(tools, "git"))
        os.symlink(sys.executable, os.path.join(tools, "python3"))
        os.symlink(os.path.realpath(_FAKE_UNAME), os.path.join(tools, "uname"))
        env = dict(self.env)
        env["PATH"] = os.pathsep.join([tools, "/usr/bin", "/bin"])
        p = self.start(env=env)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn("claude", self.worker_state()["error"])

    def write_other_worker(self, pid, ago=0, state="idle"):
        path = self.path("worker.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'state: {state}\ncurrent_request: ""\npid: {pid}\n')
        if ago:
            t = time.time() - ago
            os.utime(path, (t, t))
        with open(path, "rb") as f:
            return f.read()

    def test_live_other_worker(self):
        # AE14: 他のワーカーが動いていれば、worker.yaml に触れずに終了コード 2
        before = self.write_other_worker(os.getpid())
        p = self.start()
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        self.assertIn(str(os.getpid()), err)
        with open(self.path("worker.yaml"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_live_other_worker_from_other_worktree(self):
        wt = os.path.join(os.path.dirname(self.repo), "wt")
        _git(self.repo, "worktree", "add", "-q", "-b", "wt", wt)
        before = self.write_other_worker(os.getpid(), state="reviewing")
        p = self.start(cwd=wt)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 2)
        with open(self.path("worker.yaml"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_dead_or_stale_other_worker_does_not_block(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        for label, pid, ago in (("終了したプロセス", dead.pid, 0), ("古い更新時刻", os.getpid(), 40)):
            with self.subTest(label):
                self.write_other_worker(pid, ago=ago)
                p = self.start()
                state = self.wait_for(
                    lambda: self.worker_state().get("pid") == p.pid and self.worker_state(),
                    what="新しいワーカーの worker.yaml")
                self.assertEqual(state["state"], "idle")
                self.finish(p)


class TestArguments(WorkerTestBase):
    def run_args(self, *args):
        p = subprocess.run(["bash", _WORKER, *args], cwd=self.repo, env=self.env,
                           capture_output=True, text=True, timeout=20)
        return p.returncode, p.stderr

    def test_errors(self):
        cases = {
            "--model が無い": [self.loop, "--effort", "high"],
            "--effort が無い": [self.loop, "--model", "opus"],
            "effort の値": [self.loop, "--model", "opus", "--effort", "ultra"],
            "相対パス": ["tmp/review-loop/" + LOOP_ID, "--model", "opus", "--effort", "high"],
            "bypassPermissions": [self.loop, "--model", "opus", "--effort", "high",
                                  "--permission-mode", "bypassPermissions"],
            "分の値": [self.loop, "--model", "opus", "--effort", "high", "--idle-minutes", "0"],
            "知らない引数": [self.loop, "--model", "opus", "--effort", "high", "--foo"],
            "--sandbox-allow-write の値が無い": [self.loop, "--model", "opus", "--effort", "high",
                                                "--sandbox-allow-write"],
            "--sandbox-allowed-domain の値が無い": [self.loop, "--model", "opus", "--effort", "high",
                                                   "--sandbox-allowed-domain"],
        }
        for label, args in cases.items():
            with self.subTest(label):
                rc, err = self.run_args(*args)
                self.assertEqual(rc, 2)
                self.assertIn("使い方", err)
        self.assertFalse(os.path.exists(self.path("worker.yaml")))


def _plugin_version():
    with open(_PLUGIN_JSON, encoding="utf-8") as f:
        return json.load(f)["version"]


class TestWorkerYamlOnStart(WorkerTestBase):
    """起動時の確認が通ったときに書く worker.yaml の中身。"""

    def test_defaults(self):
        # 権限の引数・--sandbox-allow-write・--sandbox-allowed-domain・-- 以降を付けない起動
        _, state = self.start_idle()
        self.assertEqual(state["permission_mode"], "auto")
        self.assertEqual(state["worker_version"], _plugin_version())
        self.assertEqual(state["sandbox_allow_write"], [])
        self.assertEqual(state["sandbox_allowed_domains"], [])
        self.assert_contract("## `worker.yaml`", state)

    def test_sandbox_values(self):
        # --sandbox-allow-write と --sandbox-allowed-domain は繰り返して指定でき、指定の順に書く。
        # --sandbox-allow-write の値の先頭の ~ は、ワーカーの HOME に展開する
        cache = os.path.join(self.root, "cache")
        _, state = self.start_idle(
            "--sandbox-allow-write", "~/Library/Caches/go-build",
            "--sandbox-allow-write", cache,
            "--sandbox-allowed-domain", "proxy.golang.org",
            "--sandbox-allowed-domain", "sum.golang.org",
        )
        self.assertEqual(state["sandbox_allow_write"],
                         [os.path.join(self.home, "Library", "Caches", "go-build"), cache])
        self.assertEqual(state["sandbox_allowed_domains"], ["proxy.golang.org", "sum.golang.org"])
        self.assert_contract("## `worker.yaml`", state)

    def test_empty_arrays_under_set_u(self):
        # -- 以降・--sandbox-allow-write・--sandbox-allowed-domain・--allowed-tools をどれも付けない (配列がどれも空の) 起動で、
        # 1 回の処理を終えられる。macOS の /bin/bash (3.2) は set -u のもとで空の配列の展開をエラーにすることがあるので、
        # /bin/bash があればそれで走らせる
        shell = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
        self.put_request()
        p = self.start(shell=shell)
        marker = self.wait_marker()
        self.wait_state("idle")
        _, _, err = self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)
        self.assertNotIn("unbound variable", err)


class TestPythonScriptsLoadedAtStart(WorkerTestBase):
    """ワーカーは、python3 で実行するファイル (ディレクトリ review-triage/scripts/review-loop-worker/ の .py) の中身を
    起動時に読み込み、読み込んだ中身を実行する (worker.md の「要るもの」)。周回の間に別のセッションがプラグインを更新して、
    古いバージョンのディレクトリの中身が消えても、ワーカーが動き続けるようにするため。"""

    def test_keeps_running_after_python_dir_moved(self):
        # プラグインのスクリプトとファイルを一時ディレクトリに写してワーカーを起動し、1 回を処理させた後に .py のディレクトリを
        # 別名に移す。次の依頼文も、ファイルを開かずに処理を終え、ok の印を書く
        copy = os.path.join(self.root, "plugin", "review-triage")
        shutil.copytree(os.path.join(_HERE, "..", "scripts"), os.path.join(copy, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(_HERE, "..", ".claude-plugin"), os.path.join(copy, ".claude-plugin"))
        pydir = os.path.join(copy, "scripts", "review-loop-worker")
        self.put_request()
        p = subprocess.Popen(
            ["bash", os.path.join(copy, "scripts", "review-loop-worker.sh"), self.loop, "--model", "opus", "--effort", "high"],
            cwd=self.repo, env=self.env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.procs.append(p)
        first = self.wait_marker()
        self.wait_state("idle")
        os.rename(pydir, pydir + ".moved")
        self.put_request(rid=RID2)
        second = self.wait_marker(RID2)
        self.wait_state("idle")
        _, _, err = self.finish(p)
        for marker in (first, second):
            self.assertEqual(marker["status"], "ok", (marker, err))
            self.assertEqual(marker["worker_version"], _plugin_version())
            self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        self.assertNotIn("can't open file", err)
        self.assertEqual(self.workspaces(), [])


class TestSandboxStartChecks(WorkerTestBase):
    """起動時の確認のうち、レビュアの実行をサンドボックスで走らせるための項目 (worker.md の「起動時の確認」の 3 と 9〜14)。"""

    def test_not_macos(self):
        # AE11: uname -s が Linux
        self.env["FAKE_UNAME_S"] = "Linux"
        self.start_unavailable(contains=["macOS", "Linux"])

    def test_not_macos_is_checked_before_loop_yaml(self):
        # 確認は worker.md の表の順に行う (3 の macOS が、4 の loop.yaml より先)
        self.env["FAKE_UNAME_S"] = "Linux"
        os.remove(self.path("loop.yaml"))
        self.start_unavailable(contains="macOS")

    def test_tmpdir(self):
        # AE11: TMPDIR が無い、またはホームの下。作業側が TMPDIR の下
        under_home = os.path.join(self.home, "tmp")
        os.makedirs(under_home)
        link_to_home = os.path.join(self.root, "tmp-link")
        os.symlink(under_home, link_to_home)
        under_repo = os.path.join(self.repo, "tmp", "t")
        os.makedirs(under_repo)
        cases = (
            ("TMPDIR が無い", None, "環境変数 TMPDIR が無い"),
            ("TMPDIR が存在しない", os.path.join(self.root, "nowhere"), "TMPDIR がディレクトリとして存在しない"),
            ("TMPDIR がホームの下", under_home, "TMPDIR の実体がホームの下にある"),
            ("TMPDIR がホームの下を指すシンボリックリンク", link_to_home, "TMPDIR の実体がホームの下にある"),
            ("TMPDIR が作業側の下", under_repo, "TMPDIR の実体が作業側の下にある"),
            ("作業側が TMPDIR の下", self.root, "作業側が TMPDIR の実体の下にある"),
        )
        for label, tmpdir, contains in cases:
            with self.subTest(label):
                env = dict(self.env)
                if tmpdir is None:
                    env.pop("TMPDIR")
                else:
                    env["TMPDIR"] = tmpdir
                self.start_unavailable(env=env, contains=contains)

    def test_sandbox_tmp(self):
        # AE11: 作業側か周回の置き場が、サンドボックスの一時ディレクトリ (/private/tmp/claude-<利用者の番号>) の下
        if not (os.path.isdir(_SANDBOX_TMP) and os.access(_SANDBOX_TMP, os.W_OK)):
            self.skipTest(f"{_SANDBOX_TMP} が無い (macOS で Claude Code のサンドボックスを使った機材でだけ確かめられる)")
        base = tempfile.mkdtemp(prefix="review-loop-worker-test-", dir=_SANDBOX_TMP)
        self.addCleanup(shutil.rmtree, base, True)
        with self.subTest("周回の置き場"):
            loop = os.path.join(base, "loop")
            _make_loop_dir(loop, self.repo)
            self.start_unavailable(loop=loop, contains=["周回の置き場", "サンドボックスの一時ディレクトリ"])
        with self.subTest("作業側"):
            repo = os.path.join(base, "repo")
            _make_repo(repo)
            loop = os.path.join(repo, "tmp", "review-loop", LOOP_ID)
            _make_loop_dir(loop, repo)
            self.start_unavailable(loop=loop, cwd=repo, contains=["作業側", "サンドボックスの一時ディレクトリ"])

    def test_special_characters_in_paths(self):
        # 許可と拒否の規則に書けない文字を、作業側・周回の置き場・TMPDIR の実体パスに含まない
        for c in "()[]{}*?!#":
            with self.subTest(f"TMPDIR に {c}"):
                tmpdir = os.path.join(self.root, f"tmp{c}dir")
                os.makedirs(tmpdir)
                self.start_unavailable(env=dict(self.env, TMPDIR=tmpdir), contains=["TMPDIR", f"「{c}」"])
        with self.subTest("周回の置き場に #"):
            loop = os.path.join(self.root, "loop#1")
            _make_loop_dir(loop, self.repo)
            self.start_unavailable(loop=loop, contains=["周回の置き場", "「#」"])
        with self.subTest("作業側に ("):
            repo = os.path.join(self.root, "repo (copy)")
            _make_repo(repo)
            loop = os.path.join(repo, "tmp", "review-loop", LOOP_ID)
            _make_loop_dir(loop, repo)
            self.start_unavailable(loop=loop, cwd=repo, contains=["作業側", "「(」"])

    def test_sandbox_allow_write_must_not_contain_protected_places(self):
        # AE11: --sandbox-allow-write ~ など。ホーム・作業側・周回の置き場と同じか、その祖先の値は受け付けない。
        # 1 つ目に問題の無い値を置いて、2 つ目以降の値も確かめていることを見る
        link = os.path.join(self.root, "home-link")
        os.symlink(self.home, link)
        cases = (
            ("~", "~", "ホーム"),
            ("ホーム", self.home, "ホーム"),
            ("ホームへのシンボリックリンク", link, "ホーム"),
            ("~/.. (ホームの祖先)", "~/..", "ホーム"),
            ("ホームの祖先", self.root, "ホーム"),
            ("/", "/", "ホーム"),
            ("作業側", self.repo, "作業側"),
            ("周回の置き場", self.loop, "周回の置き場"),
            ("周回の置き場の祖先", os.path.join(self.repo, "tmp"), "周回の置き場"),
        )
        for label, value, contains in cases:
            with self.subTest(label):
                self.start_unavailable("--sandbox-allow-write", os.path.join(self.root, "cache"),
                                       "--sandbox-allow-write", value,
                                       contains=["--sandbox-allow-write", contains])

    def test_sandbox_allow_write_must_not_be_below_repo_or_loop(self):
        # 作業側と周回の置き場は、その下の場所も受け付けない (作業側の .git や、git が無視する場所への書き込みを許さないため)。
        # ホームの下の場所は受け付ける (Go のビルドのキャッシュなど)
        loop_outside = os.path.join(self.root, "loops", LOOP_ID)
        _make_loop_dir(loop_outside, self.repo)
        cases = (
            ("作業側の .git", os.path.join(self.repo, ".git"), self.loop, "作業側"),
            ("作業側の下のまだ無い場所", os.path.join(self.repo, ".venv", "cache"), self.loop, "作業側"),
            ("作業側の外にある周回の置き場の下", os.path.join(loop_outside, "x"), loop_outside, "周回の置き場"),
        )
        for label, value, loop, contains in cases:
            with self.subTest(label):
                self.start_unavailable("--sandbox-allow-write", value, loop=loop,
                                       contains=["--sandbox-allow-write", contains, "の下にある"])
        with self.subTest("ホームの下"):
            cache = os.path.join(self.home, "Library", "Caches", "go-build")
            _, state = self.start_idle("--sandbox-allow-write", cache)
            self.assertEqual(state["sandbox_allow_write"], [cache])

    def test_sandbox_allow_write_must_not_contain_tmpdir(self):
        # TMPDIR の実体と同じか、その祖先の値も受け付けない (前の回のレビュアの実行が残したプロセスが、次の回の準備のディレクトリに
        # 書けないように)。TMPDIR の下の場所は受け付ける
        tmpdir = os.path.join(self.root, "t", "tmpdir")
        os.makedirs(tmpdir)
        link = os.path.join(self.root, "tmpdir-link")
        os.symlink(tmpdir, link)
        env = dict(self.env, TMPDIR=tmpdir)
        cases = (
            ("TMPDIR", tmpdir),
            ("TMPDIR へのシンボリックリンク", link),
            ("TMPDIR の祖先", os.path.join(self.root, "t")),
        )
        for label, value in cases:
            with self.subTest(label):
                self.start_unavailable("--sandbox-allow-write", os.path.join(self.root, "cache"),
                                       "--sandbox-allow-write", value, env=env,
                                       contains=["--sandbox-allow-write", "TMPDIR の実体"])
        with self.subTest("TMPDIR の下"):
            _, state = self.start_idle("--sandbox-allow-write", os.path.join(tmpdir, "cache"), env=env)
            self.assertEqual(state["sandbox_allow_write"], [os.path.join(tmpdir, "cache")])

    def test_sandbox_allow_write_must_be_absolute(self):
        # 相対パスは、どこを基準にするかで指す場所が変わるので受け付けない。~ の後に名前が続く形 (~ユーザー名) も展開しない
        for value in ("cache", "./cache", "~other/cache"):
            with self.subTest(value):
                self.start_unavailable("--sandbox-allow-write", value,
                                       contains=["--sandbox-allow-write", "絶対パス"])

    def test_extra_args_outside_the_allowed_list(self):
        # AE11: 追加の引数に --add-dir。--settings が JSON でない・enabledPlugins 以外のキーを持つ・値が真偽値の対応でない
        cases = (
            ("--add-dir", ["--add-dir", "/x"], "--add-dir"),
            ("--dangerously-skip-permissions", ["--dangerously-skip-permissions"], "--dangerously-skip-permissions"),
            ("受け付ける引数の後に受け付けない引数", ["--plugin-dir", "/x", "--mcp-config", "{}"], "--mcp-config"),
            ("--plugin-dir の値が無い", ["--plugin-dir"], "--plugin-dir"),
            ("--plugin-dir の値が - で始まる", ["--plugin-dir", "--add-dir"], "--plugin-dir"),
            ("--settings が JSON でない", ["--settings", "settings.json"], "JSON"),
            ("--settings のトップレベルがオブジェクトでない", ["--settings", "[]"], "enabledPlugins"),
            ("--settings に enabledPlugins が無い", ["--settings", "{}"], "enabledPlugins"),
            ("--settings に enabledPlugins 以外のキー",
             ["--settings", json.dumps({"enabledPlugins": {}, "permissions": {"allow": ["Bash"]}})], "permissions"),
            ("enabledPlugins の値が真偽値でない",
             ["--settings", json.dumps({"enabledPlugins": {"review-triage@akm": "false"}})], "真偽値"),
            ("enabledPlugins の値が対応でない",
             ["--settings", json.dumps({"enabledPlugins": ["review-triage@akm"]})], "真偽値"),
        )
        for label, extra, contains in cases:
            with self.subTest(label):
                self.start_unavailable("--", *extra, contains=["追加の引数", contains])

    def test_extra_args_in_the_allowed_list(self):
        # --plugin-dir <ディレクトリ> と、enabledPlugins だけを持つ --settings なら起動する
        plugin = os.path.join(self.root, "plugin")
        os.makedirs(plugin)
        settings = json.dumps({"enabledPlugins": {"review-triage@akm": False, "other@akm": True}})
        self.start_idle("--", "--plugin-dir", plugin, "--settings", settings)

    def test_user_settings_excluded_commands(self):
        # AE11: 利用者の設定に sandbox.excludedCommands がある。JSON として読めない設定も、検査できないので止める
        cases = (
            ("sandbox.excludedCommands がある", {"sandbox": {"excludedCommands": ["docker"]}},
             "sandbox.excludedCommands"),
            ("JSON として読めない", "{ not json", "JSON として読めない"),
            ("トップレベルがオブジェクトでない", "[]", "オブジェクト"),
        )
        for label, content, contains in cases:
            with self.subTest(label):
                self.write_user_settings(content)
                self.start_unavailable(contains=["利用者の設定", contains])

    def test_user_settings_allow_unix_sockets(self):
        # 利用者の設定に空でない sandbox.network.allowUnixSockets がある。sandbox.excludedCommands もあれば、両方を理由に書く
        docker = {"allowUnixSockets": ["/var/run/docker.sock"]}
        cases = (
            ("allowUnixSockets がある", {"sandbox": {"network": docker}},
             ["sandbox.network.allowUnixSockets", "/var/run/docker.sock"]),
            ("excludedCommands もある", {"sandbox": {"excludedCommands": ["docker"], "network": docker}},
             ["sandbox.excludedCommands", "sandbox.network.allowUnixSockets"]),
        )
        for label, content, contains in cases:
            with self.subTest(label):
                self.write_user_settings(content)
                self.start_unavailable(contains=["利用者の設定", *contains])

    def test_user_settings_without_excluded_commands(self):
        # 空の sandbox.excludedCommands と sandbox.network.allowUnixSockets は止めない。
        # 利用者の設定の sandbox.network.allowLocalBinding は、真でも止めない (止めるのはレビュー対象のブランチの設定だけ)
        cases = (
            ("excludedCommands が空", {"sandbox": {"enabled": True, "excludedCommands": []}}),
            ("allowUnixSockets が空", {"sandbox": {"network": {"allowUnixSockets": [], "allowLocalBinding": True}}}),
            ("sandbox が無い", {"permissions": {"allow": ["Read"]}}),
        )
        for label, content in cases:
            with self.subTest(label):
                self.write_user_settings(content)
                self.start_idle()

    def test_user_settings_follows_claude_config_dir(self):
        # AE11: CLAUDE_CONFIG_DIR があれば、利用者の設定は $HOME/.claude/settings.json ではなく
        # その下の settings.json (Claude Code 本体と同じ決め方)
        config_dir = os.path.join(self.root, "config-dir")
        self.write_user_settings({"sandbox": {"excludedCommands": ["docker"]}}, config_dir=config_dir)
        # $HOME/.claude/settings.json には無い (対比のため明示的に書く)
        self.write_user_settings({"permissions": {"allow": ["Read"]}})
        env = dict(self.env, CLAUDE_CONFIG_DIR=config_dir)
        self.start_unavailable(env=env, contains=["利用者の設定", os.path.join(config_dir, "settings.json"),
                                                   "sandbox.excludedCommands"])

    def test_user_settings_ignores_home_when_claude_config_dir_set(self):
        # 逆に $HOME/.claude/settings.json にだけ sandbox.excludedCommands があり、CLAUDE_CONFIG_DIR の下には
        # 無ければ起動する (実際に使われるのは CLAUDE_CONFIG_DIR の下)
        config_dir = os.path.join(self.root, "config-dir")
        self.write_user_settings({"permissions": {"allow": ["Read"]}}, config_dir=config_dir)
        self.write_user_settings({"sandbox": {"excludedCommands": ["docker"]}})
        env = dict(self.env, CLAUDE_CONFIG_DIR=config_dir)
        self.start_idle(env=env)

    def test_webfetch_domains_follows_claude_config_dir(self):
        # AE17 も CLAUDE_CONFIG_DIR の下の settings.json を見る (起動時の確認の 15)
        config_dir = os.path.join(self.root, "config-dir")
        self.write_user_settings({"permissions": {"allow": ["WebFetch(domain:example.com)"]}}, config_dir=config_dir)
        env = dict(self.env, CLAUDE_CONFIG_DIR=config_dir)
        out, _ = self.start_idle(env=env)
        self.assertIn("example.com", out)

    def test_claude_config_dir_must_be_absolute(self):
        # CLAUDE_CONFIG_DIR が相対パスだと、Claude Code 本体はレビュアの実行の cwd (複製) から解決するので、
        # ワーカーは同じファイルを確かめられず起動しない
        env = dict(self.env, CLAUDE_CONFIG_DIR="relative/config-dir")
        self.start_unavailable(env=env, contains=["CLAUDE_CONFIG_DIR", "絶対パス"])


class TestNetworkNotice(WorkerTestBase):
    """起動時の表示 (worker.md の「起動時の確認」の 15): 利用者の設定の WebFetch(domain:…) の許可は、
    サンドボックスの接続を許すホストに加わるので、それを表示する。止めはしない。"""

    def test_all_hosts(self):
        # AE17
        self.write_user_settings({"permissions": {"allow": ["Read", "WebFetch(domain:*)"]}})
        out, _ = self.start_idle()
        self.assertIn("外のすべてのホストに接続できる", out)

    def test_domains(self):
        self.write_user_settings({"permissions": {"allow": [
            "WebFetch(domain:example.com)", "Bash(ls:*)", "WebFetch(domain:docs.example.org)",
        ]}})
        out, _ = self.start_idle()
        self.assertIn("example.com", out)
        self.assertIn("docs.example.org", out)
        self.assertNotIn("すべてのホスト", out)
        self.assertNotIn("Bash(ls:*)", out)

    def test_no_webfetch_rule(self):
        self.write_user_settings({"permissions": {"allow": ["Read"]}})
        out, _ = self.start_idle()
        self.assertNotIn("WebFetch", out)


class TestEnding(WorkerTestBase):
    def test_idle_expiry(self):
        # AE10
        p = self.start("--idle-minutes", "0.05")
        out, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 124)
        self.assertEqual(self.worker_state()["state"], "expired")
        self.assertIn("この起動で応じた回: 0 回", out)

    def test_end_lists_served_rounds(self):
        # AE11
        self.put_request()
        p = self.start()
        self.wait_marker()
        self.wait_state("idle")
        with open(self.path("end"), "w", encoding="utf-8") as f:
            f.write("人間が置いた\n")
        out, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.worker_state()["state"], "left")
        self.assertIn("この起動で応じた回: 1 回", out)
        self.assertIn(RID, out)
        self.assertIn("ok", out)

    def test_interrupt_while_idle(self):
        p = self.start()
        self.wait_state("idle")
        os.killpg(p.pid, signal.SIGINT)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 130)
        self.assertEqual(self.worker_state()["state"], "left")
        self.assertEqual([n for n in os.listdir(self.loop) if n.startswith("delivered-")], [])
        self.wait_for(lambda: not _group_alive(p.pid), timeout=3, what="ワーカーのプロセスグループが空になる")

    def test_timeout(self):
        # AE15: 終わらない偽の claude を上限で止め、子プロセスも残さない
        self.env["FAKE_CLAUDE_MODE"] = "hang"
        self.put_request()
        p = self.start("--review-timeout-minutes", "0.05")
        marker = self.wait_marker(timeout=30)
        self.assertEqual(marker["status"], "failed")
        self.assertEqual(marker["error"], "timeout")
        self.wait_state("idle")
        pids = _read_pids(self.pids_file)
        for pid in pids:
            self.wait_for(lambda: not _pid_alive(pid), timeout=5, what=f"プロセス {pid} の終了")
        self.finish(p)

    def test_interrupt_while_reviewing(self):
        # AE16: 割り込みを受けたら、レビュアの実行とその子を止めて failed の印と left を書く。作業場所は残らない
        for sig, code in ((signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129)):
            with self.subTest(sig=sig.name):
                for n in os.listdir(self.loop):
                    if n != "loop.yaml" and not n.startswith("review-request-"):
                        os.remove(self.path(n))
                if os.path.exists(self.pids_file):
                    os.remove(self.pids_file)
                self.env["FAKE_CLAUDE_MODE"] = "hang"
                if not os.path.exists(self.path(f"review-request-{RID}.md")):
                    self.put_request()
                p = self.start()
                self.wait_state("reviewing")
                self.wait_for(lambda: os.path.exists(self.pids_file), what="偽の claude の起動")
                pids = _read_pids(self.pids_file)
                started = time.time()
                os.killpg(p.pid, sig)  # 端末の Ctrl-C と同じく、ワーカーのフォアグラウンドのプロセスグループに送る
                p.communicate(timeout=20)
                self.assertLess(time.time() - started, 8)
                self.assertEqual(p.returncode, code)
                marker = _read_yaml(self.path(f"delivered-{RID}.yaml"))
                self.assertEqual(marker["status"], "failed")
                self.assertEqual(marker["error"], "interrupted")
                self.assertEqual(self.worker_state()["state"], "left")
                self.assertEqual(self.worker_state()["workspace"], "")
                self.assertEqual(self.workspaces(), [])
                for pid in pids:
                    self.wait_for(lambda: not _pid_alive(pid), timeout=3, what=f"プロセス {pid} の終了")
                self.wait_for(lambda: not _group_alive(p.pid), timeout=3,
                              what="ワーカーのプロセスグループ (更新時刻を進める処理を含む) が空になる")

    def test_sigkill_during_review_leaves_no_worker_processes(self):
        # レビュー中にワーカーを SIGKILL で消すと、ワーカーのプロセスグループ (更新時刻を進める処理と、上限を測る処理) は
        # 10 秒以内に空になる。レビュアの実行は専用のプロセスグループなので残る (trap が動かないので止められない)
        self.env["FAKE_CLAUDE_MODE"] = "hang"
        self.put_request()
        p = self.start()
        self.wait_state("reviewing")
        self.wait_for(lambda: os.path.exists(self.pids_file), what="偽の claude の起動")
        os.kill(p.pid, signal.SIGKILL)
        self.wait_for(lambda: not _group_alive(p.pid), timeout=10,
                      what="ワーカーのプロセスグループが空になる")
        reviewer = _read_pids(self.pids_file)[0]
        self.assertTrue(_pid_alive(reviewer))

    def test_sigkill_stops_heartbeat(self):
        # AE17: ワーカーを SIGKILL で消すと、10 秒以内に worker.yaml の更新時刻が止まる
        p = self.start()
        self.wait_state("idle")
        os.kill(p.pid, signal.SIGKILL)
        p.communicate(timeout=20)
        time.sleep(7)
        m1 = os.stat(self.path("worker.yaml")).st_mtime
        time.sleep(6)
        m2 = os.stat(self.path("worker.yaml")).st_mtime
        self.assertEqual(m1, m2)
        self.assertFalse(_group_alive(p.pid))


class TestTimeoutDuringPreparation(WorkerTestBase):
    """上限は、依頼文を受け取ってからレビュアの実行が終わるまでを測る (worker.md の「回の処理」)。
    準備 (作業場所・複製・複製の設定・写し) の途中で越えた回は、レビュアの実行を起動しない (計画の AE8)。"""

    def assert_timeout_without_run(self, p):
        marker = self.wait_marker(timeout=30)
        self.wait_state("idle")
        self.finish(p)
        self.assertEqual(marker["status"], "failed", marker)
        self.assertEqual(marker["error"], "timeout")
        self.assertEqual(self.claude_calls(), [])
        for key in ("head_after", "tree_clean_after", "exit_code", "log"):
            self.assertNotIn(key, marker)
        self.assertEqual(self.workspaces(), [])
        self.assert_contract("## `delivered-<識別子>.yaml`", marker)
        return marker

    def test_timeout_while_cloning(self):
        # 複製の作成 (偽の git の clone) が終わらないと、上限で偽の git のプロセスグループを止め、failed・timeout の印を書く
        self.delay_git("clone")
        self.put_request()
        p = self.start("--review-timeout-minutes", "0.05")
        self.assert_timeout_without_run(p)
        for pid in _read_pids(self.git_pids_file):
            self.wait_for(lambda: not _pid_alive(pid), timeout=5, what=f"偽の git {pid} の終了")

    def test_timeout_just_before_request_copy(self):
        # 複製の設定の確認 (手順 7) を遅らせて、写しの作成 (手順 8) の直前に上限を越えさせる。
        # 準備の段の合間に越えても、次の段の前かレビュアの実行を起動する前に確かめるので、偽の claude は呼ばれない
        touch = os.path.join(self.root, "delay-started")
        self.delay_python("settings.local.json", 5, touch)
        self.put_request()
        p = self.start("--review-timeout-minutes", "0.05")
        self.assert_timeout_without_run(p)
        self.assertTrue(os.path.exists(touch), "複製の設定の確認を遅らせていない")


class TestInterruptPhases(WorkerTestBase):
    """割り込みを受けた時点ごとの扱い (worker.md の「終わり方」。計画の AE9)。レビュアの実行中の扱いは
    TestEnding.test_interrupt_while_reviewing で確かめる。シグナルは、端末の Ctrl-C と同じくワーカーのプロセスグループに送る。"""

    SIGNALS = ((signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129))

    def test_interrupt_during_preparation(self):
        # 準備の途中 (偽の git の clone が終わらない間) に割り込みを受けると、準備のプロセスグループを止め、準備のディレクトリと
        # 作業場所を消し、印を書かずに left で終わる。起動し直したワーカーが、印の無い同じ依頼文を処理する
        for sig, code in self.SIGNALS:
            with self.subTest(sig=sig.name):
                self.reset_loop()
                self.delay_git("clone")
                self.put_request()
                p = self.start()
                git_pid = self.wait_pids(self.git_pids_file, 1)[0]
                # 準備は準備のディレクトリの中で行い、作業場所のパスにはまだ何も無い
                self.assertEqual(len(self.prep_dirs()), 1, self.workspaces())
                self.assertFalse(os.path.lexists(self.ws_path()))
                os.killpg(p.pid, sig)
                p.communicate(timeout=30)
                self.assertEqual(p.returncode, code)
                self.assertFalse(os.path.exists(self.path(f"delivered-{RID}.yaml")))
                state = self.worker_state()
                self.assertEqual(state["state"], "left")
                self.assertEqual(state["workspace"], "")
                self.assertEqual(self.prep_dirs(), [])
                self.assertEqual(self.workspaces(), [])
                self.assertEqual(self.claude_calls(), [])
                self.wait_for(lambda: not _pid_alive(git_pid), timeout=5, what=f"偽の git {git_pid} の終了")
                self.wait_for(lambda: not _group_alive(p.pid), timeout=3, what="ワーカーのプロセスグループが空になる")
        del self.env["FAKE_GIT_SLEEP_ON"]
        marker, _ = self.run_round()
        self.assertEqual(marker["status"], "ok", marker)

    def test_interrupt_during_finish(self):
        # 回の終わりの処理の途中 (結果の複写を遅らせる) に割り込みを受けると、その回の印を、割り込みを受けなかったときと同じに
        # 書き終えてから left で終わる。割り込みは回の終わりの処理が起動したコマンド (遅らせた複写) にも届くが、それで止まらない
        touch = os.path.join(self.root, "delay-started")
        self.delay_python("after the rename", 3, touch)
        for sig, code in self.SIGNALS:
            with self.subTest(sig=sig.name):
                self.reset_loop()
                if os.path.exists(touch):
                    os.remove(touch)
                self.put_request()
                p = self.start()
                self.wait_for(lambda: os.path.exists(touch), what="結果の複写の開始")
                os.killpg(p.pid, sig)
                out, _ = p.communicate(timeout=30)
                self.assertEqual(p.returncode, code)
                marker = _read_yaml(self.path(f"delivered-{RID}.yaml"))
                self.assertEqual(marker["status"], "ok", marker)
                self.assertNotIn("error", marker)
                self.assertTrue(os.path.isfile(self.path(f"review-{RID}.yaml")))
                state = self.worker_state()
                self.assertEqual(state["state"], "left")
                self.assertEqual(state["rounds_served"], 1)
                self.assertIn(RID, out)
                self.assertEqual(self.workspaces(), [])


class TestRestartCleanup(WorkerTestBase):
    """起動し直したときの掃除 (worker.md の「起動時の確認」の 2 と「終わり方」の kill -9。計画の AE10)。"""

    def kill9(self, p):
        os.kill(p.pid, signal.SIGKILL)
        p.communicate(timeout=30)

    def assert_cleaned_before_pickup(self, err):
        """起動し直したワーカーの出力で、前の作業場所に残ったプロセスを止めたことが、依頼文を見つけたことより先にある。"""
        stopped = err.find("SIGTERM を送る")
        picked = err.find("依頼文を見つけた")
        self.assertNotEqual(stopped, -1, err)
        self.assertNotEqual(picked, -1, err)
        self.assertLess(stopped, picked, err)

    def test_sigkill_while_reviewing_then_restart(self):
        # レビュアの実行中にワーカーを SIGKILL で消すと、偽の claude と、その子と、別のプロセスグループで動く子が残る。
        # 同じコマンドで起動し直すと、それらを止めて前の作業場所を消してから、同じ依頼文を処理する。新しいログに前の実行の行は混ざらない
        self.env["FAKE_CLAUDE_MODE"] = "hang_leave_child"
        self.put_request()
        p = self.start()
        state = self.wait_state("reviewing")
        self.assertEqual(state["workspace"], self.ws_path())
        pids = self.wait_pids(self.pids_file, 3)
        self.kill9(p)
        for pid in pids:
            self.assertTrue(_pid_alive(pid), f"SIGKILL の後に {pid} が残っていない (テストの前提が崩れている)")
        self.assertTrue(os.path.isdir(self.ws_path()))

        self.env["FAKE_CLAUDE_MODE"] = "ok"
        p = self.start()
        marker = self.wait_marker()
        self.wait_state("idle")
        _, _, err = self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)
        for pid in pids:
            self.wait_for(lambda: not _pid_alive(pid), timeout=3, what=f"前の実行が残したプロセス {pid} の終了")
        self.assertEqual(self.workspaces(), [])
        with open(self.path(f"{RID}.log"), encoding="utf-8", errors="replace") as f:
            self.assertNotIn("fake_tick", f.read())
        self.assert_cleaned_before_pickup(err)

    def test_sigkill_while_preparing_then_restart(self):
        # 準備の途中 (偽の git の clone が終わらない間) にワーカーを SIGKILL で消すと、準備のディレクトリと、その中を cwd にした
        # 偽の git が残る。起動し直すと、それを止めて準備のディレクトリを消してから、同じ依頼文を処理する
        self.delay_git("clone")
        self.put_request()
        p = self.start()
        git_pid = self.wait_pids(self.git_pids_file, 1)[0]
        self.assertEqual(self.worker_state()["workspace"], self.ws_path())
        self.kill9(p)
        self.assertTrue(_pid_alive(git_pid), "SIGKILL の後に偽の git が残っていない (テストの前提が崩れている)")
        self.assertEqual(len(self.prep_dirs()), 1, self.workspaces())
        self.assertFalse(os.path.lexists(self.ws_path()))

        del self.env["FAKE_GIT_SLEEP_ON"]
        p = self.start()
        marker = self.wait_marker()
        self.wait_state("idle")
        _, _, err = self.finish(p)
        self.assertEqual(marker["status"], "ok", marker)
        self.wait_for(lambda: not _pid_alive(git_pid), timeout=3, what=f"前の偽の git {git_pid} の終了")
        self.assertEqual(self.workspaces(), [])
        self.assert_cleaned_before_pickup(err)

    def test_processes_outside_workspace_are_not_stopped(self):
        # 作業場所の外を cwd にしているプロセスは、起動引数に作業場所のパスがあっても止めない。中を cwd にしているものは止める
        ws = self.ws_path()
        os.makedirs(os.path.join(ws, "tree"))
        inside = self.spawn_sleeper(os.path.join(ws, "tree"))
        outside = self.spawn_sleeper(self.root, ws)
        self.write_dead_worker_yaml(ws)
        self.start_idle()
        self.wait_for(lambda: inside.poll() is not None, timeout=3, what="作業場所の中のプロセスの終了")
        self.assertIsNone(outside.poll())
        self.assertFalse(os.path.lexists(ws))

    def test_cleanup_even_when_unavailable(self):
        # 置き場に end がある状態や、ほかの確認で unavailable になる起動でも、残ったプロセスと作業場所を片付けてから止まる。
        # worker.yaml が無ければ (作業場所のパスが記録されていなければ)、決まったパスを片付ける
        cases = (
            ("end がある", True, {}, "end"),
            ("macOS でない・worker.yaml が無い", False, {"FAKE_UNAME_S": "Linux"}, "macOS"),
        )
        for label, recorded, extra_env, contains in cases:
            with self.subTest(label):
                self.reset_loop()
                ws = self.ws_path()
                os.makedirs(os.path.join(ws, "tree"))
                inside = self.spawn_sleeper(os.path.join(ws, "tree"))
                if recorded:
                    self.write_dead_worker_yaml(ws)
                if contains == "end":
                    open(self.path("end"), "w").close()
                p = self.start(env=dict(self.env, **extra_env))
                _, err = p.communicate(timeout=30)
                self.assertEqual(p.returncode, 2, err)
                state = self.worker_state()
                self.assertEqual(state["state"], "unavailable", state)
                self.assertIn(contains, state["error"])
                self.wait_for(lambda: inside.poll() is not None, timeout=3, what="作業場所の中のプロセスの終了")
                self.assertFalse(os.path.lexists(ws))

    def test_cleanup_only_workspace_shaped_directories(self):
        # worker.yaml の workspace が、作業場所の名前の形に合わないディレクトリや、シンボリックリンクを指すときは、
        # 中を cwd にしているプロセスを止めず、何も消さない
        victim = os.path.join(self.root, "victim")
        os.makedirs(victim)
        keep = os.path.join(victim, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        inside = self.spawn_sleeper(victim)
        ws = self.ws_path()
        os.symlink(victim, ws)
        for label, recorded in (("名前の形に合わない", victim), ("シンボリックリンク", ws)):
            with self.subTest(label):
                self.write_dead_worker_yaml(recorded)
                self.start_idle()
                self.assertTrue(os.path.exists(keep))
                self.assertIsNone(inside.poll())
                self.assertTrue(os.path.islink(ws))

    def test_prep_dirs_are_found_by_name(self):
        # worker.yaml が無くても (準備のディレクトリのパスは記録しない)、TMPDIR の実体の下の、この周回の準備のディレクトリの名前の形
        # (review-loop-prep-<周回 id>-<ハッシュ>.<6 文字>) に合うディレクトリは、中を cwd にしているプロセスを止めてから消す。
        # 名前の形に合わないものと、シンボリックリンクは片付けない
        key = os.path.basename(self.ws_path())[len("review-loop-"):]
        tmp = os.path.realpath(self.tmpdir)
        preps = [os.path.join(tmp, f"review-loop-prep-{key}.{s}") for s in ("a1B2c3", "zzzzzz")]
        for d in preps:
            os.makedirs(os.path.join(d, "tree", "sub"))
        os.chmod(os.path.join(preps[1], "tree", "sub"), 0o555)
        inside = self.spawn_sleeper(os.path.join(preps[0], "tree"))
        others = [os.path.join(tmp, n) for n in (f"review-loop-prep-{key}.toolong7", f"review-loop-prep-other-{key}.a1B2c3")]
        for d in others:
            os.makedirs(d)
        victim = os.path.join(self.root, "victim")
        os.makedirs(victim)
        keep = os.path.join(victim, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        link = os.path.join(tmp, f"review-loop-prep-{key}.link00")
        os.symlink(victim, link)
        self.assertFalse(os.path.exists(self.path("worker.yaml")))
        self.start_idle()
        self.wait_for(lambda: inside.poll() is not None, timeout=3, what="準備のディレクトリの中のプロセスの終了")
        for d in preps:
            self.assertFalse(os.path.lexists(d), d)
        for d in others:
            self.assertTrue(os.path.isdir(d), d)
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.exists(keep))

    def test_end_removes_workspace(self):
        # end を見て終わるとき、周回の作業場所が残っていれば消す。シンボリックリンクなら、リンクだけを消してリンクの先は消さない
        target = os.path.join(self.root, "link-target")
        os.makedirs(target)
        keep = os.path.join(target, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("消してはいけない\n")
        for label in ("ディレクトリ", "シンボリックリンク"):
            with self.subTest(label):
                self.reset_loop()
                p = self.start()
                self.wait_state("idle")
                ws = self.ws_path()
                if label == "ディレクトリ":
                    os.makedirs(os.path.join(ws, "tree", "sub"))
                    with open(os.path.join(ws, "tree", "sub", "f.txt"), "w", encoding="utf-8") as f:
                        f.write("x\n")
                else:
                    os.symlink(target, ws)
                open(self.path("end"), "w").close()
                p.communicate(timeout=30)
                self.assertEqual(p.returncode, 0)
                self.assertEqual(self.worker_state()["state"], "left")
                self.assertFalse(os.path.lexists(ws))
                self.assertTrue(os.path.exists(keep))

    def test_stopped_even_when_stderr_broken(self):
        # 指摘 #6: stop_cwd_procs は、標準エラーへの報告 (print) が OSError で失敗しても、シグナルを送って
        # 残ったプロセスを止める処理を続けなければならない。ワーカーを動かしていた端末を閉じると、その後の
        # 標準エラーへの書き込みは OSError (EIO) になる (pty の master を閉じると、slave 側への書き込みが
        # そうなる)。ワーカー全体を pty (stdin・stdout・stderr を同じ pty の slave にする) の上で走らせ、
        # 回の終わりの処理が stop_cwd_procs を呼ぶ直前 (偽の python3 の delay_python で、その python3 のスクリプトの
        # 実行そのものを遅らせて捕まえる) で master を閉じ、それから回を最後まで進めさせる。
        # 標準エラーに書けない状態でも、作業場所の中に残したプロセスが止まることを確かめる
        # (直さない場合、print が RuntimeError 以外の OSError を送出し、python3 がそこで終わって
        # os.kill に届かないので、このプロセスは止まらずに残る)。
        ws = self.ws_path()
        touch = os.path.join(self.root, "stop-started")
        self.delay_python("の中を cwd にしているプロセスが残っているので", 2, touch)
        self.put_request()

        master, slave = pty.openpty()
        args = ["bash", _WORKER, self.loop, "--model", "opus", "--effort", "high"]
        p = subprocess.Popen(
            args, cwd=self.repo, env=self.env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        self.procs.append(p)
        os.close(slave)
        closed = False
        self.addCleanup(lambda: None if closed else os.close(master))

        self.wait_state("reviewing")
        os.makedirs(os.path.join(ws, "tree"), exist_ok=True)
        inside = self.spawn_sleeper(os.path.join(ws, "tree"))

        # stop_cwd_procs の呼び出し (回の終わりの処理の 1) が始まった (sleep に入った) ら、
        # 端末を閉じたのと同じ状態にする。以降、その python3 のスクリプトの標準エラーへの書き込みは OSError になる
        self.wait_for(lambda: os.path.exists(touch), what="stop_cwd_procs の呼び出しの開始")
        os.close(master)
        closed = True

        p.wait(timeout=30)
        self.assertEqual(p.returncode, 128 + signal.SIGHUP)
        self.wait_for(lambda: inside.poll() is not None, timeout=5, what="作業場所の中のプロセスの終了")


if __name__ == "__main__":
    unittest.main()
