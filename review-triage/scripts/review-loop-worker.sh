#!/usr/bin/env bash
# review-loop のワーカー。人間が端末で起動し、周回の置き場に現れた依頼文ごとに、TMPDIR の下に回の作業場所を作り、
# その中の複製 (作業側のリポジトリを複製して、依頼の head を取り出したもの) で claude -p を走らせる。
# 結果を確かめてから置き場に複写し、作業場所を消して、完了の印を書く。
#
# 使い方:
#   review-loop-worker.sh <周回の置き場の絶対パス> --model <指定> --effort <値>
#       [--permission-mode <値>] [--allowed-tools <ツール>]...
#       [--sandbox-allow-write <パス>]... [--sandbox-allowed-domain <ドメイン>]...
#       [--idle-minutes <分>] [--review-timeout-minutes <分>] [-- <claude に渡す追加の引数>...]
#
# --model と --effort は必須で、既定を持たない (どのモデルと effort でレビューするかは人間が決める)。
# --permission-mode の既定は auto。-- の後に受け付けるのは、--plugin-dir <ディレクトリ> と、
# enabledPlugins だけを持つ JSON を値にした --settings の 2 つ (起動時の確認の 13)。
# 作業側 (review-loop) と同じ作業ツリーで起動する。周回の間は作業ツリーを変えない。
#
# 終了コード: 0 = end を見て終わった / 124 = 依頼文が無いまま --idle-minutes が過ぎた /
#             2 = 引数の誤り・起動時の確認が通らない・他のワーカーが動いている /
#             128 + シグナル番号 = 割り込み (INT / TERM / HUP)
#
# 振る舞いの正本は review-triage/skills/review-loop/references/worker.md (起動時の確認・回の処理・
# 権限の既定・ログの読み方)、置き場のファイルの様式の正本は同じディレクトリの loop-files.md。
# プラグインの設定ファイル (config.json) は読まない — 値はすべて引数で受け、作業側が案内のコマンドに埋める。
# Claude Code の利用者の設定 (~/.claude/settings.json) は読むが、使うのは起動時の確認と表示だけ。
#
# macOS でだけ動かす (起動時の確認の 3。サンドボックスの振る舞いを macOS でだけ確かめたため)。
# bash は macOS の /bin/bash (3.2) で動くように書く。テストは CI (ubuntu) でも偽の uname で走らせるので、
# GNU の stat と Linux の /proc でも動くようにしておく。python3 が要る (claude -p と準備のコマンドを専用のプロセスグループで
# 起動する・ログ (stream-json) を読む・プラグインの版を読む・--settings の値と利用者の設定と複製の設定を JSON として検査する・
# --settings の JSON を組み立てる・依頼文の写しを作る・結果を確かめて複写する・作業場所の中を cwd にしているプロセスを
# 見つける・パスの実体を求めるのに使う)。
#
# 不変条件: レビュアの実行を起動した後は、複製の中で git を実行しない (複製の .git/config やフックはレビュアの実行が
# 書き換えられるので、git を実行するとそのコマンドがサンドボックスの外で動く)。作業場所は rm -rf だけで消す。

set -u

WORKER_PID=$$
POLL_SECONDS=5              # 依頼文を探す周期と、worker.yaml の更新時刻を進める周期
OTHER_WORKER_FRESH_SECONDS=30  # 起動時の確認で、他のワーカーが動いていると判定する更新時刻の新しさ
STOP_GRACE_SECONDS=5        # レビュアの実行や作業場所に残ったプロセスを TERM で止めてから KILL を送るまでの猶予
RESULT_MAX_BYTES=1048576    # 置き場に複写する結果の大きさの上限 (1 MiB)。正本は worker.md の「回の処理」の手順 10

# 引数のコマンドを、専用のプロセスグループ (自分の PID と同じ番号) にしてから実行する python3 のスクリプト。
# レビュアの実行と準備のコマンドをこれで起動する (上限を越えたときと割り込みを受けたときに、プロセスグループごと止めるため)
SETPGID_PY='import os, sys; os.setpgid(0, 0); os.execvp(sys.argv[1], sys.argv[1:])'

# レビュアの実行に許すツールの既定の一覧 (--allowed-tools を 1 回でも指定すれば置き換わる)。
# 正本は worker.md の「レビュアの実行の権限」
DEFAULT_ALLOWED_TOOLS=(
  'Bash(git diff:*)'
  'Bash(git log:*)'
  'Bash(git show:*)'
  'Bash(git status:*)'
  'Bash(git rev-parse:*)'
  'Bash(git merge-base:*)'
  'Bash(git ls-files:*)'
  'Bash(git blame:*)'
  'Bash(git cat-file:*)'
  'Bash(git grep:*)'
  'Read'
  'Grep'
  'Glob'
  'Skill'
  'Agent'
)

usage() {
  cat >&2 <<'USAGE'
使い方: review-loop-worker.sh <周回の置き場の絶対パス> --model <指定> --effort <値>
    [--permission-mode <値>] [--allowed-tools <ツール>]...
    [--sandbox-allow-write <パス>]... [--sandbox-allowed-domain <ドメイン>]...
    [--idle-minutes <分>] [--review-timeout-minutes <分>] [-- <claude に渡す追加の引数>...]
USAGE
  exit 2
}

die_usage() {
  echo "review-loop-worker: $1" >&2
  usage
}

# ---- 引数 ----

[ $# -ge 1 ] || usage
LOOP_DIR=$1
shift
MODEL=""
EFFORT=""
PERMISSION_MODE="auto"
ALLOWED_TOOLS=()
SANDBOX_ALLOW_WRITE=()
SANDBOX_ALLOWED_DOMAINS=()
IDLE_MINUTES=180
REVIEW_TIMEOUT_MINUTES=60
EXTRA_ARGS=()

# --sandbox-allow-write の値の先頭の ~ をホームに展開する。展開するのは ~ だけの値と ~/ で始まる値で、
# ~ の後に名前が続く値 (~ユーザー名) はそのまま返す (起動時の確認の 12 で、絶対パスでないものとして止める)
expand_home() {
  case "$1" in
    "~") printf '%s' "${HOME:-}" ;;
    "~/"*) printf '%s/%s' "${HOME:-}" "${1#"~/"}" ;;
    *) printf '%s' "$1" ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --model) [ $# -ge 2 ] || usage; MODEL=$2; shift 2 ;;
    --effort) [ $# -ge 2 ] || usage; EFFORT=$2; shift 2 ;;
    --permission-mode) [ $# -ge 2 ] || usage; PERMISSION_MODE=$2; shift 2 ;;
    --allowed-tools) [ $# -ge 2 ] || usage; ALLOWED_TOOLS+=("$2"); shift 2 ;;
    --sandbox-allow-write) [ $# -ge 2 ] || usage; SANDBOX_ALLOW_WRITE+=("$(expand_home "$2")"); shift 2 ;;
    --sandbox-allowed-domain) [ $# -ge 2 ] || usage; SANDBOX_ALLOWED_DOMAINS+=("$2"); shift 2 ;;
    --idle-minutes) [ $# -ge 2 ] || usage; IDLE_MINUTES=$2; shift 2 ;;
    --review-timeout-minutes) [ $# -ge 2 ] || usage; REVIEW_TIMEOUT_MINUTES=$2; shift 2 ;;
    --) shift; EXTRA_ARGS=("$@"); break ;;
    *) die_usage "知らない引数: $1" ;;
  esac
done

case "$LOOP_DIR" in
  /*) ;;
  *) die_usage "周回の置き場は絶対パスで指定する: $LOOP_DIR" ;;
esac
[ -d "$LOOP_DIR" ] || die_usage "周回の置き場がディレクトリとして存在しない: $LOOP_DIR"
[ -n "$MODEL" ] || die_usage "--model は必須 (どのモデルでレビューするかは人間が決める)"
case "$EFFORT" in
  low|medium|high|xhigh|max) ;;
  "") die_usage "--effort は必須 (low / medium / high / xhigh / max)" ;;
  *) die_usage "--effort は low / medium / high / xhigh / max のいずれか: $EFFORT" ;;
esac
[ "$PERMISSION_MODE" != "bypassPermissions" ] || die_usage "--permission-mode bypassPermissions は使わない (レビュアの実行が結果ファイルの外を書けてしまう)"
for v in "$IDLE_MINUTES" "$REVIEW_TIMEOUT_MINUTES"; do
  echo "$v" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || die_usage "分は正の数で指定する: $v"
  awk -v m="$v" 'BEGIN { exit !(m > 0) }' || die_usage "分は正の数で指定する: $v"
done

# ---- 小さな道具 ----

now_iso() { date +%Y-%m-%dT%H:%M:%S%z; }

log() { echo "[$(date +%H:%M:%S)] $*" >&2; }

# 分を秒 (1 以上の整数。端数は切り上げ) にする
minutes_to_seconds() {
  awk -v m="$1" 'BEGIN { s = m * 60; t = int(s); if (t < s) t++; if (t < 1) t = 1; print t }'
}

# ファイルの更新時刻 (エポック秒)。GNU の stat -c が使えなければ BSD の stat -f に切り替える
mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null
}

# YAML のトップレベルの単純なキーの値を読む (前後の空白と引用符を除く)
read_key() {
  sed -n "s/^$2:[[:space:]]*//p" "$1" 2>/dev/null | head -n 1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# YAML の二重引用符の文字列にする (改行とタブは空白に)
yaml_str() {
  printf '"%s"' "$(printf '%s' "$1" | tr '\n\t' '  ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
}

# 引数を、二重引用符の文字列を並べた 1 行の列 (["a", "b"]。引数が無ければ []) にする
yaml_list() {
  local out="" v
  for v in "$@"; do out="${out:+$out, }$(yaml_str "$v")"; done
  printf '[%s]' "$out"
}

# パス $1 が、パス $2 と同じか、その下にあるか (どちらも実体パスで渡す)
is_within() {
  [ "$2" = / ] && return 0
  case "$1" in
    "$2"|"$2"/*) return 0 ;;
  esac
  return 1
}

# 標準入力を、同じディレクトリの一時名に書いてから改名する (読む側が書きかけを読まないように)
write_atomic() {
  local target=$1
  local tmp
  tmp="$(dirname "$target")/.$(basename "$target").tmp"
  cat >"$tmp" && mv -f "$tmp" "$target"
}

# 実体パス (シンボリックリンクを解決した絶対パス)
real_dir() {
  (cd "$1" 2>/dev/null && pwd -P)
}

# 複数行の文字列 ($1) の、空白だけではない最後の行
last_line() {
  printf '%s\n' "$1" | sed '/^[[:space:]]*$/d' | tail -n 1
}

# 複数行の文字列 ($1) の空でない行を、"; " で繋いで 1 行にする (完了の印の error の区切り)
join_lines() {
  printf '%s\n' "$1" | sed '/^$/d' | awk 'NR > 1 { printf "; " } { printf "%s", $0 }'
}

# そのプロセスグループに、終わっていない (ゾンビでない) プロセスが残っているか
group_alive() {
  ps -A -o pgid=,stat= 2>/dev/null | awk -v g="$1" '$1 == g && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}

# ---- 起動時の確認に使う道具 (python3 を使う。read_worker_version のほかは、起動時の確認の 8 で python3 を確かめた後に呼ぶ) ----

# ワーカーの版を、スクリプト ($1) の実体の位置からプラグインのファイル .claude-plugin/plugin.json を読んで標準出力に出す。
# 環境変数 CLAUDE_PLUGIN_ROOT は、人間が端末で起動するワーカーには設定されないので使わない。
# 読めなければ理由を標準エラーに出力して、終了コード 1 で終わる
read_worker_version() {
  python3 - "$1" <<'PY'
import json, os, sys

root = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))
path = os.path.join(root, ".claude-plugin", "plugin.json")
try:
    with open(path, encoding="utf-8") as f:
        version = json.load(f).get("version")
except (OSError, ValueError, AttributeError) as e:
    print(f"review-loop-worker: プラグインのファイル {path} から版を読めない ({e})", file=sys.stderr)
    sys.exit(1)
if not isinstance(version, str) or not version:
    print(f"review-loop-worker: プラグインのファイル {path} に版 (version) が無い", file=sys.stderr)
    sys.exit(1)
print(version)
PY
}

# 起動時の確認の 12。--sandbox-allow-write の値 (4 つ目以降の引数) の実体パスが、ホーム・作業側・周回の置き場の実体パス
# (1〜3 つ目の引数) と同じか、その祖先なら、最初に当たったものの理由を標準出力に出して、終了コード 1 で終わる。
# 値の場所はまだ無くてよい (無い部分は、シンボリックリンクを解決せずにそのまま繋ぐ)
allow_write_problem() {
  python3 - "$@" <<'PY'
import os, sys

protected = (("ホーム", sys.argv[1]), ("作業側", sys.argv[2]), ("周回の置き場", sys.argv[3]))
for value in sys.argv[4:]:
    real = os.path.realpath(value)
    for label, path in protected:
        if real == path:
            print(f"--sandbox-allow-write の値 {value} (実体 {real}) は{label}そのものなので、書き込みを許せない")
            sys.exit(1)
        if real == "/" or path.startswith(real + "/"):
            print(f"--sandbox-allow-write の値 {value} (実体 {real}) は{label} ({path}) を含むので、書き込みを許せない")
            sys.exit(1)
PY
}

# 起動時の確認の 13。追加の引数の --settings の値 ($1) が、トップレベルのキーが enabledPlugins だけで、
# その値がプラグイン名から真偽値への対応である JSON でなければ、理由を標準出力に出して、終了コード 1 で終わる
settings_arg_problem() {
  python3 - "$1" <<'PY'
import json, sys

try:
    value = json.loads(sys.argv[1])
except ValueError as e:
    print(f"JSON として読めない ({e})")
    sys.exit(1)
if not isinstance(value, dict):
    print("トップレベルが、キーに enabledPlugins だけを持つオブジェクトではない")
    sys.exit(1)
if list(value) != ["enabledPlugins"]:
    print(f"トップレベルのキーが enabledPlugins だけではない (キー: {', '.join(value) or '無し'})")
    sys.exit(1)
plugins = value["enabledPlugins"]
if not isinstance(plugins, dict) or not all(isinstance(v, bool) for v in plugins.values()):
    print("enabledPlugins の値が、プラグイン名から真偽値 (true / false) への対応ではない")
    sys.exit(1)
PY
}

# 起動時の確認の 14。利用者の設定ファイル ($1) が JSON として読めないか、空でない sandbox.excludedCommands を持てば、
# 理由を標準出力に出して、終了コード 1 で終わる。ファイルが無ければ何もしない
user_settings_problem() {
  python3 - "$1" <<'PY'
import json, sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    sys.exit(0)
except (OSError, ValueError) as e:
    print(f"利用者の設定 {path} を JSON として読めない ({e})。検査できないので起動しない")
    sys.exit(1)
if not isinstance(settings, dict):
    print(f"利用者の設定 {path} のトップレベルがオブジェクトではない。検査できないので起動しない")
    sys.exit(1)
sandbox = settings.get("sandbox")
excluded = sandbox.get("excludedCommands") if isinstance(sandbox, dict) else None
if excluded:
    shown = json.dumps(excluded, ensure_ascii=False)
    print(f"利用者の設定 {path} に sandbox.excludedCommands ({shown}) がある。当たるコマンドはサンドボックスの外で動くので、"
          "この設定を消すか空にしてから起動し直す")
    sys.exit(1)
PY
}

# 起動時の確認の 15 (表示)。利用者の設定ファイル ($1) の許可の規則 (permissions.allow) のうち、
# WebFetch(domain:<ドメイン>) の形のものから、ドメインを重ねずに 1 行に 1 つずつ出す。
# 14 の後に呼ぶので、ファイルは無いか JSON として読める
webfetch_domains() {
  python3 - "$1" <<'PY'
import json, re, sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    sys.exit(0)
permissions = settings.get("permissions") if isinstance(settings, dict) else None
allow = permissions.get("allow") if isinstance(permissions, dict) else None
domains = []
for rule in allow if isinstance(allow, list) else []:
    m = re.fullmatch(r"\s*WebFetch\(domain:(.+)\)\s*", rule) if isinstance(rule, str) else None
    if m and m.group(1).strip() not in domains:
        domains.append(m.group(1).strip())
for d in domains:
    print(d)
PY
}

# 作業場所の名前に付けるハッシュ。周回の置き場の実体パス ($1) の SHA-256 の、16 進の先頭 8 文字
workspace_hash() {
  python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest()[:8])' "$1"
}

# レビュアの実行に渡す --settings の JSON を組み立てて標準出力に出す (中身の正本は worker.md の「サンドボックス」)。
# 引数は、作業場所のパスに続けて、-w <書き込みを許す場所>・-d <接続を許すドメイン>・-s <追加の引数の --settings の値> の組を並べる。
# 追加の引数の値を合成した後に、サンドボックスと自動メモリのキーがワーカーの値のままで、ほかのキーが enabledPlugins だけであることを
# 確かめる。確かめられなければ理由を標準エラーに出して、終了コード 1 で終わる
build_settings_json() {
  python3 - "$@" <<'PY'
import json, sys

workspace, pairs = sys.argv[1], sys.argv[2:]
lists = {"-w": [], "-d": [], "-s": []}
for flag, value in zip(pairs[0::2], pairs[1::2]):
    lists[flag].append(value)
settings = {
    "sandbox": {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "failIfUnavailable": True,
        "filesystem": {"allowWrite": [workspace] + lists["-w"]},
        "network": {"strictAllowlist": True, "allowedDomains": lists["-d"]},
    },
    "autoMemoryEnabled": False,
}
worker_values = json.loads(json.dumps(settings))
for text in lists["-s"]:
    for key, value in json.loads(text).items():
        if key == "enabledPlugins":
            settings.setdefault("enabledPlugins", {}).update(value)
        else:
            settings[key] = value
if {k: v for k, v in settings.items() if k != "enabledPlugins"} != worker_values:
    print("review-loop-worker: 追加の引数の --settings を合成すると、サンドボックスか自動メモリの設定がワーカーの値から変わるか、"
          "enabledPlugins 以外のキーが加わる", file=sys.stderr)
    sys.exit(1)
print(json.dumps(settings, ensure_ascii=False))
PY
}

# ---- 作業場所の片付けに使う道具 (起動時の確認の 2 と、回の処理の手順 5・10 で使う。python3 を使う) ----

# 作業場所 ($1。実体パス) の中を cwd にしているプロセスを止める (回の終わりの処理の 1 と、起動時の確認の 2)。
# TERM を送り、STOP_GRACE_SECONDS 秒のうちに消えなければ KILL を送る。プロセスグループでは見つけられない (Bash のコマンドは
# レビュアの実行とは別のプロセスグループで動く) ので、cwd で見つける。cwd は、/proc があれば /proc/<PID>/cwd から
# (Linux。CI のテストが通る経路)、無ければコマンド lsof で (macOS) 読む。
# 列挙できないか止められなければ、理由を標準エラーに出して終了コード 1 で終わる
stop_cwd_procs() {
  python3 - "$1" "$STOP_GRACE_SECONDS" <<'PY'
import os, signal, subprocess, sys, time

workspace, grace = sys.argv[1], float(sys.argv[2])
me = os.getpid()


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
        print(f"review-loop-worker: 作業場所 {workspace} の中を cwd にしているプロセスが残っているので、"
              f"{sig.name} を送る (PID: {' '.join(str(p) for p in sorted(pids))})", file=sys.stderr)
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.time() + grace
        while True:
            time.sleep(0.2)
            pids = scan()
            if not pids or time.time() >= deadline:
                break
except RuntimeError as e:
    print(f"review-loop-worker: 作業場所 {workspace} の中を cwd にしているプロセスを列挙できない: {e}", file=sys.stderr)
    sys.exit(1)
if pids:
    print(f"review-loop-worker: 作業場所 {workspace} の中を cwd にしているプロセスが止まらない "
          f"(PID: {' '.join(str(p) for p in sorted(pids))})", file=sys.stderr)
    sys.exit(1)
PY
}

# 作業場所 ($1) を rm -rf で消せるように、その中のディレクトリに所有者の読み取り・書き込み・実行の権限を足す
# (Go のモジュールのキャッシュなど、読み取り専用のディレクトリを作るツールがあるため)。シンボリックリンクは辿らない。
# $1 がディレクトリでないか、実体パスが $1 と違えば (作ったときと違えば)、理由を標準出力に出して終了コード 1 で終わる
make_removable() {
  python3 - "$1" <<'PY'
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


def add_owner_rwx(path, mode):
    if mode & 0o700 != 0o700:
        try:
            os.chmod(path, stat.S_IMODE(mode) | 0o700)
        except OSError:
            pass


add_owner_rwx(top, st.st_mode)
# 上から順にたどり、下のディレクトリの権限を、そこへ降りる前に足す
for root, dirs, _ in os.walk(top):
    for d in dirs:
        p = os.path.join(root, d)
        try:
            s = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISDIR(s.st_mode):
            add_owner_rwx(p, s.st_mode)
PY
}

# 作業場所 ($1。実体パス) を消す (回の終わりの処理の 5)。パスがシンボリックリンクでなく、実体が作ったときと同じであることを確かめてから、
# 中のディレクトリに権限を足して rm -rf で消す。git は使わない。消さなかったか消せなければ、パスと理由を標準エラーに出して 1 を返す
remove_workspace() {
  local ws=$1 why
  if [ -L "$ws" ]; then
    log "作業場所 $ws がシンボリックリンクに置き換えられているので、消さない (リンクの先も消さない)。次の回の作業場所を作るときに、リンクだけを消す"
    return 1
  fi
  [ -e "$ws" ] || return 0
  if ! why=$(make_removable "$ws"); then
    log "作業場所 $ws を消さない: ${why:-確かめられない}。次の回の作業場所を作るときか、次の起動で消す"
    return 1
  fi
  rm -rf "$ws" 2>/dev/null
  if [ -e "$ws" ] || [ -L "$ws" ]; then
    log "作業場所 $ws を消せない。次の回の作業場所を作るときか、次の起動で消す"
    return 1
  fi
  return 0
}

# 起動時の確認の 2 (掃除)。前の起動が残した作業場所の中を cwd にしているプロセスを止め、作業場所を消す。
# 片付けるのは、前の worker.yaml のキー workspace に記録されたパス (無いか空なら、TMPDIR の実体の下の決まったパス) だけで、
# パスの名前が作業場所の名前の形 (review-loop-<周回 id>-<周回の置き場の実体パスのハッシュ>) に合い、シンボリックリンクでない
# ディレクトリのときだけ、止めて消す — worker.yaml に書かれた値だけを根拠に、ワーカーが作ったのではないディレクトリの中の
# プロセスを止めたり、ディレクトリを消したりしないため。プロセスは cwd で見つける (プロセスグループでは見つけられず、名前 (claude) は
# 利用者の対話セッションと同じなので照合しない)。確認ではないので、片付けられなくても止めない (理由とパスを標準エラーに出す)
startup_cleanup() {
  local loop_real name recorded="" tmp_real target
  if ! command -v python3 >/dev/null 2>&1; then
    log "python3 が見つからないので、前の起動の作業場所を片付けられない"
    return 0
  fi
  loop_real=$(real_dir "$LOOP_DIR") || return 0
  name="review-loop-${loop_real##*/}-$(workspace_hash "$loop_real")"
  if [ -f "$LOOP_DIR/worker.yaml" ]; then
    # yaml_str で書いた値なので、\ で始まる 2 文字 (\\ と \") を 1 文字に戻す
    recorded=$(read_key "$LOOP_DIR/worker.yaml" workspace | sed 's/\\\(.\)/\1/g')
  fi
  if [ -n "$recorded" ]; then
    case "$recorded" in
      /*/"$name") target=$recorded ;;
      *)
        log "worker.yaml の workspace の値 $recorded は作業場所の名前の形 (…/$name) に合わないので、片付けない"
        return 0 ;;
    esac
  elif [ -n "${TMPDIR:-}" ] && tmp_real=$(real_dir "$TMPDIR"); then
    target="$tmp_real/$name"
  else
    return 0
  fi
  if [ -L "$target" ]; then
    log "前の起動の作業場所のパス $target はシンボリックリンクなので、片付けない (リンクの先も消さない)"
    return 0
  fi
  [ -e "$target" ] || return 0
  if [ ! -d "$target" ]; then
    log "前の起動の作業場所のパス $target はディレクトリではないので、片付けない"
    return 0
  fi
  log "前の起動の作業場所 $target が残っているので、片付ける"
  stop_cwd_procs "$target"
  remove_workspace "$target"
  return 0
}

# ---- 状態 ----

WORKER_VERSION="unknown"
CWD_REAL=""
START_HEAD=""
STARTED=""
ROUNDS_SERVED=0
SERVED_LINES=()
IGNORED_REQUESTS=" "   # レビュアの実行の間に置き場に現れた依頼文 (この起動の間は処理しない)
HEARTBEAT_PID=""
WATCHDOG_PID=""
SLEEP_PID=""
REVIEWER_PID=""
PREP_PID=""            # 準備のコマンド (専用のプロセスグループで動かす) の PID
WAITED_RC=""           # 関数 wait_once・wait_child・stop_group が受け取った、子プロセスの終了コード
FINISHING=0
WS=""                  # 回の作業場所のパス (起動時の確認が通った後に決める)
# 回のどの部分を行っているか。割り込みを受けたときの扱いを決める (関数 on_signal)。
#   "" = 依頼文を探している / prep = 準備 (手順 2〜8) / review = レビュアの実行 (手順 9) / finish = 回の終わりの処理 (手順 10)
PHASE=""
PENDING_CODE=""        # 回の終わりの処理の途中に受けた割り込みの終了コード。印を書き終えてから、この値で終わる

# 回ごとの状態
CURRENT_RID=""
REQ_STARTED=""
REQ_STARTED_EPOCH=0
REQ_DEADLINE=0         # 上限の時刻 (エポック秒)。依頼文を受け取った時刻に --review-timeout-minutes を足したもの
HEAD_BEFORE=""
EFFECTIVE="unknown"
SKILL_CALLED="unknown"
DENIAL_COUNT="unknown"
DENIAL_TOOLS="[]"
EFFECTIVE_MODE="unknown"  # ログから読んだ実効の権限モード
SANDBOX_COUNT="unknown"   # ログから数えた、サンドボックスが止めた確認の件数
SANDBOX_CALLS=""          # 完了の印の sandbox_blocked.calls の要素 (YAML の行)。空なら calls は []
MARKER_LINE=""         # 最後に書いた完了の印の、この起動で応じた回の一覧に出す行
PREP_OUT=""            # 準備のコマンドの標準出力と標準エラーを書くファイル (作業場所の中)
PREP_TIMEOUT=0         # 準備のコマンドを、上限を越えたために止めたか起動しなかったら 1
PREP_ERROR=""          # 準備の段が通らなかったときに、完了の印の error に書く文字列

# worker.yaml を書く。キー workspace には、reviewing のときだけ回の作業場所のパスを書く (起動し直したワーカーが片付けるのに使う)
write_worker_yaml() {
  local state=$1 current=$2 error=${3:-} ws=""
  [ "$state" = reviewing ] && ws=$WS
  {
    echo "state: $state"
    echo "current_request: $(yaml_str "$current")"
    echo "workspace: $(yaml_str "$ws")"
    echo "pid: $WORKER_PID"
    echo "worker_version: $(yaml_str "$WORKER_VERSION")"
    echo "model: $(yaml_str "$MODEL")"
    echo "effort: $(yaml_str "$EFFORT")"
    echo "permission_mode: $(yaml_str "$PERMISSION_MODE")"
    echo "sandbox_allow_write: $(yaml_list ${SANDBOX_ALLOW_WRITE[@]+"${SANDBOX_ALLOW_WRITE[@]}"})"
    echo "sandbox_allowed_domains: $(yaml_list ${SANDBOX_ALLOWED_DOMAINS[@]+"${SANDBOX_ALLOWED_DOMAINS[@]}"})"
    echo "cwd: $(yaml_str "$CWD_REAL")"
    echo "head: $(yaml_str "$START_HEAD")"
    echo "started: $(yaml_str "$STARTED")"
    echo "updated: $(yaml_str "$(now_iso)")"
    echo "rounds_served: $ROUNDS_SERVED"
    if [ -n "$error" ]; then echo "error: $(yaml_str "$error")"; fi
  } | write_atomic "$LOOP_DIR/worker.yaml"
}

unavailable() {
  log "起動時の確認が通らない: $1"
  write_worker_yaml unavailable "" "$1"
  exit 2
}

# ---- 起動時の確認 (正本は worker.md の「起動時の確認」の表。番号は表の「順」) ----

STARTED=$(now_iso)

# ワーカーの版。起動時の確認が通らずに worker.yaml を unavailable で書くときにも書くので、確認より先に読む。
# python3 が無ければ unknown のまま進み、起動時の確認の 8 で止まる
if command -v python3 >/dev/null 2>&1; then
  if v=$(read_worker_version "$0"); then
    WORKER_VERSION=$v
  else
    log "ワーカーの版が分からないので、worker.yaml には unknown と書く"
  fi
fi

# 1. 他のワーカーが動いているか。動いていれば worker.yaml に触れずに終わる
if [ -f "$LOOP_DIR/worker.yaml" ]; then
  other_state=$(read_key "$LOOP_DIR/worker.yaml" state)
  other_pid=$(read_key "$LOOP_DIR/worker.yaml" pid)
  other_mtime=$(mtime "$LOOP_DIR/worker.yaml")
  case "$other_state" in
    idle|reviewing)
      if [ -n "$other_mtime" ] && [ $(( $(date +%s) - other_mtime )) -le "$OTHER_WORKER_FRESH_SECONDS" ] \
        && echo "$other_pid" | grep -Eq '^[0-9]+$' && kill -0 "$other_pid" 2>/dev/null; then
        echo "review-loop-worker: この置き場では別のワーカーが動いている (PID ${other_pid}、状態 $other_state)。" >&2
        echo "  そのワーカーの端末で Ctrl-C を押すか、kill -TERM $other_pid で止めてから起動し直す。" >&2
        exit 2
      fi ;;
  esac
fi

# 2. 前の起動の作業場所を片付ける (掃除)。worker.yaml を書くどの処理よりも前に行う — end がある周回や、ほかの確認で
# unavailable になる起動でも、kill -9 で消えたワーカーが残したプロセスと作業場所を片付けるため
startup_cleanup

# 3. macOS で動いているか
os_name=$(uname -s 2>/dev/null)
[ "$os_name" = Darwin ] || unavailable "macOS で動いていない (uname -s: ${os_name:-読めない})。サンドボックスの振る舞いを macOS でだけ確かめたので、ほかの OS では起動しない"

# 4. loop.yaml があり、repo_dir が読めるか
[ -f "$LOOP_DIR/loop.yaml" ] || unavailable "loop.yaml が無い"
REPO_DIR=$(read_key "$LOOP_DIR/loop.yaml" repo_dir)
[ -n "$REPO_DIR" ] || unavailable "loop.yaml の repo_dir が読めない"

# 5. 作業側と同じ作業ツリーで起動したか
top=$(git rev-parse --show-toplevel 2>/dev/null) || unavailable "git の作業ツリーの中で起動していない (cwd: $(pwd -P))"
CWD_REAL=$(real_dir "$top")
repo_real=$(real_dir "$REPO_DIR") || unavailable "loop.yaml の repo_dir が存在しない: $REPO_DIR"
if [ "$CWD_REAL" != "$repo_real" ]; then
  mine=$(cd "$CWD_REAL" && real_dir "$(git rev-parse --git-common-dir 2>/dev/null)")
  theirs=$(cd "$repo_real" && real_dir "$(git rev-parse --git-common-dir 2>/dev/null)")
  if [ -n "$mine" ] && [ "$mine" = "$theirs" ]; then
    unavailable "別の worktree で起動した (期待: ${repo_real}、実際: $CWD_REAL)"
  fi
  unavailable "別の作業ツリーで起動した (期待: ${repo_real}、実際: $CWD_REAL)"
fi

# 6. HEAD が読めるか
START_HEAD=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null) || unavailable "HEAD が読めない"

# 7. 周回が終わっていないか
[ ! -e "$LOOP_DIR/end" ] || unavailable "end がある (周回は終わっている)"

# 8. 使うコマンドがあるか
command -v claude >/dev/null 2>&1 || unavailable "claude コマンドが見つからない"
command -v python3 >/dev/null 2>&1 || unavailable "python3 が見つからない"

# 9. 作業場所を置ける一時ディレクトリがあるか。作業場所は書き込みを許す場所で、ホームと作業側は守る場所なので、重なってはいけない。
# TMPDIR が無くても /tmp に代えない (他の利用者も書ける場所で、作業場所の名前も予測できるため)
[ -n "${TMPDIR:-}" ] || unavailable "環境変数 TMPDIR が無い (作業場所をその下に作る。/tmp には代えない)"
TMP_REAL=$(real_dir "$TMPDIR") || unavailable "TMPDIR がディレクトリとして存在しない: $TMPDIR"
[ -n "${HOME:-}" ] || unavailable "環境変数 HOME が無い (TMPDIR がホームの外にあるかを確かめられない)"
HOME_REAL=$(real_dir "$HOME") || unavailable "ホームがディレクトリとして存在しない: $HOME"
if is_within "$TMP_REAL" "$HOME_REAL"; then
  unavailable "TMPDIR の実体がホームの下にある (TMPDIR の実体: ${TMP_REAL}、ホーム: ${HOME_REAL})。作業場所への書き込みが、ホームを守る拒否の規則に当たる"
fi
if is_within "$TMP_REAL" "$CWD_REAL"; then
  unavailable "TMPDIR の実体が作業側の下にある (TMPDIR の実体: ${TMP_REAL}、作業側: ${CWD_REAL})。書き込みを許す作業場所と、守る作業側が重なる"
fi
if is_within "$CWD_REAL" "$TMP_REAL"; then
  unavailable "作業側が TMPDIR の実体の下にある (作業側: ${CWD_REAL}、TMPDIR の実体: ${TMP_REAL})。書き込みを許す作業場所と、守る作業側が重なる"
fi

# 10. 作業側と周回の置き場が、サンドボックスの一時ディレクトリの外にあるか。サンドボックスの中の Bash はそこに既定で書けるので、
# その下にあると守れない
SANDBOX_TMP="/private/tmp/claude-$(id -u)"
LOOP_REAL=$(real_dir "$LOOP_DIR") || unavailable "周回の置き場の実体パスを求められない: $LOOP_DIR"
if is_within "$CWD_REAL" "$SANDBOX_TMP"; then
  unavailable "作業側がサンドボックスの一時ディレクトリ ${SANDBOX_TMP} の下にある (作業側: ${CWD_REAL})。サンドボックスの中の Bash が既定で書ける場所なので、守れない"
fi
if is_within "$LOOP_REAL" "$SANDBOX_TMP"; then
  unavailable "周回の置き場がサンドボックスの一時ディレクトリ ${SANDBOX_TMP} の下にある (周回の置き場: ${LOOP_REAL})。サンドボックスの中の Bash が既定で書ける場所なので、守れない"
fi

# 11. 作業側・周回の置き場・TMPDIR の実体パスを、許可と拒否の規則に書けるか (Claude Code は、これらの文字を含むパスの規則を正しく扱えない)
check_rule_chars() {
  local label=$1 path=$2 c
  for c in '(' ')' '[' ']' '{' '}' '*' '?' '!' '#'; do
    case "$path" in
      *"$c"*) unavailable "${label}の実体パスに、許可と拒否の規則に書けない文字「${c}」がある: $path" ;;
    esac
  done
}
check_rule_chars 作業側 "$CWD_REAL"
check_rule_chars 周回の置き場 "$LOOP_REAL"
check_rule_chars TMPDIR "$TMP_REAL"

# 12. 書き込みを許す場所 (--sandbox-allow-write) が、守る場所 (ホーム・作業側・周回の置き場) と同じでも、その祖先でもないか。
# 先頭の ~ は引数を読んだときにホームに展開してある
for v in ${SANDBOX_ALLOW_WRITE[@]+"${SANDBOX_ALLOW_WRITE[@]}"}; do
  case "$v" in
    /*) ;;
    *) unavailable "--sandbox-allow-write の値は絶対パスで指定する (先頭の ~ と ~/ はホームに展開する。~ユーザー名 の形は展開しない): $v" ;;
  esac
done
if [ ${#SANDBOX_ALLOW_WRITE[@]} -gt 0 ]; then
  if ! problem=$(allow_write_problem "$HOME_REAL" "$CWD_REAL" "$LOOP_REAL" "${SANDBOX_ALLOW_WRITE[@]}"); then
    [ -n "$problem" ] || problem="--sandbox-allow-write の値を検査できない"
    unavailable "$problem"
  fi
fi

# 13. 追加の引数 (-- の後) が、受け付ける一覧に収まるか。制限を弱めるフラグは列挙しきれないので、受け付けるものの一覧で検査する。
# --plugin-dir はそのまま claude に渡し (EXTRA_PASS)、--settings の値はワーカーの --settings に合成する (EXTRA_SETTINGS)
EXTRA_PASS=()
EXTRA_SETTINGS=()
i=0
while [ "$i" -lt ${#EXTRA_ARGS[@]} ]; do
  a=${EXTRA_ARGS[$i]}
  case "$a" in
    --plugin-dir|--settings)
      [ $(( i + 1 )) -lt ${#EXTRA_ARGS[@]} ] || unavailable "追加の引数 $a に値が無い"
      val=${EXTRA_ARGS[$(( i + 1 ))]}
      case "$val" in
        -*) unavailable "追加の引数 $a の値が - で始まる: $val" ;;
      esac
      if [ "$a" = --settings ]; then
        if ! problem=$(settings_arg_problem "$val"); then
          [ -n "$problem" ] || problem="検査できない"
          unavailable "追加の引数の --settings の値を受け付けない: ${problem}。受け付けるのは、enabledPlugins だけを持つ JSON"
        fi
        EXTRA_SETTINGS+=("$val")
      else
        EXTRA_PASS+=("$a" "$val")
      fi
      i=$(( i + 2 )) ;;
    *) unavailable "追加の引数 $a は受け付けない (受け付けるのは --plugin-dir <ディレクトリ> と、enabledPlugins だけを持つ JSON を値にした --settings)" ;;
  esac
done

# 14. 利用者の設定が、コマンドをサンドボックスの外で実行させないか。レビュー対象のブランチの設定は、回ごとに複製で確かめる
USER_SETTINGS="$HOME/.claude/settings.json"
if ! problem=$(user_settings_problem "$USER_SETTINGS"); then
  [ -n "$problem" ] || problem="利用者の設定 $USER_SETTINGS を検査できない"
  unavailable "$problem"
fi

# 15. (表示) 利用者の設定の WebFetch(domain:…) の許可は、サンドボックスの接続を許すホストに加わる。止めはしない
domains=$(webfetch_domains "$USER_SETTINGS")
if [ -n "$domains" ]; then
  echo "利用者の設定 $USER_SETTINGS の WebFetch(domain:…) の許可により、レビュアの実行の Bash が接続できるホストに次のドメインが加わる:"
  echo "$domains" | sed 's/^/  /'
  if echo "$domains" | grep -Fqx '*'; then
    echo "WebFetch(domain:*) があるので、レビュアの実行の Bash は外のすべてのホストに接続できる。"
    echo "  レビュー対象に埋め込まれた指示にレビュアが従うと、手元の情報を外へ送れる。接続できるホストを絞るには、利用者の設定の許可をドメインごとに書く。"
  fi
fi

IDLE_SECONDS=$(minutes_to_seconds "$IDLE_MINUTES")
REVIEW_TIMEOUT_SECONDS=$(minutes_to_seconds "$REVIEW_TIMEOUT_MINUTES")

# 回の作業場所 (worker.md の「回の処理」の手順 5)。周回の間は同じパスを使い回し、回ごとに作り直す。
# 名前は、周回 id (置き場のディレクトリ名) と、周回の置き場の実体パスから作るハッシュ。TMP_REAL は実体パスなので、
# 作業場所のパスもそのまま実体パスになる (シンボリックリンクに置き換えられていないかを、このパスと比べて確かめる)
ws_hash=$(workspace_hash "$LOOP_REAL") && [ -n "$ws_hash" ] || unavailable "作業場所の名前に付けるハッシュを求められない"
WS="$TMP_REAL/review-loop-${LOOP_REAL##*/}-$ws_hash"
CLONE="$WS/tree"

# レビュアの実行に渡す --settings の JSON。値は起動の間変わらないので、ここで 1 度だけ組み立てる
settings_args=("$WS")
for v in ${SANDBOX_ALLOW_WRITE[@]+"${SANDBOX_ALLOW_WRITE[@]}"}; do settings_args+=(-w "$v"); done
for v in ${SANDBOX_ALLOWED_DOMAINS[@]+"${SANDBOX_ALLOWED_DOMAINS[@]}"}; do settings_args+=(-d "$v"); done
for v in ${EXTRA_SETTINGS[@]+"${EXTRA_SETTINGS[@]}"}; do settings_args+=(-s "$v"); done
SETTINGS_JSON=$(build_settings_json "${settings_args[@]}") && [ -n "$SETTINGS_JSON" ] \
  || unavailable "レビュアの実行に渡す --settings の JSON を組み立てられない"

# ---- バックグラウンドの処理 ----

# ワーカーのプロセスが動いているか。終わったのに親が回収していない (ゾンビの) プロセスは動いていないとみなす
worker_alive() {
  local st
  st=$(ps -o stat= -p "$WORKER_PID" 2>/dev/null)
  case "$st" in
    ""|Z*) return 1 ;;
  esac
  return 0
}

# worker.yaml の更新時刻を 5 秒おきに進める。ワーカーのプロセスが無くなったら (kill -9 で trap が動かなかった場合も) 自分も終わる
start_heartbeat() {
  (
    hb_sleep=""
    trap 'kill "$hb_sleep" 2>/dev/null; exit 0' TERM
    while worker_alive; do
      touch -c "$LOOP_DIR/worker.yaml"
      sleep "$POLL_SECONDS" &
      hb_sleep=$!
      wait "$hb_sleep"
    done
  ) &
  HEARTBEAT_PID=$!
}

# バックグラウンドの処理 (PID $1。更新時刻を進める処理か上限を測る処理) に TERM を送り、プロセスが残っている間だけ終わりを待つ。
# 残っていなければ wait しない (正本は worker.md の「終わり方」)。これらの処理はワーカーと同じプロセスグループで動くので、
# プロセスグループに届いた HUP ではすぐに (trap が無い)、TERM では自分の trap で、ワーカーと同時に終わる (INT は、バックグラウンドの
# コマンドなので無視する)。bash 5 (Linux の 5.2 で確かめた) は、trap を設定したシグナルで wait を途中で抜けるとき、その wait の中で
# 回収した子の終わりを記録しないことがあるので、準備のコマンドやレビュアの実行を待つ wait が、同時に終わったこれらの処理を
# 回収したまま抜けることがある。終わりを記録しなかった子を wait すると、ほかの子がすべて終わるまで戻らない — まだ止めていない
# 準備のコマンドやレビュアの実行が残っていれば、ワーカーが終わらない
stop_background() {
  kill -TERM "$1" 2>/dev/null
  kill -0 "$1" 2>/dev/null || return 0
  wait "$1" 2>/dev/null
}

stop_heartbeat() {
  if [ -n "$HEARTBEAT_PID" ]; then
    stop_background "$HEARTBEAT_PID"
    HEARTBEAT_PID=""
  fi
}

# 上限の時刻 ($1。エポック秒) を過ぎたら、ワーカーに USR1 を送る。USR1 は、ワーカーが待っている wait を途中で戻すための知らせで、
# 上限を越えたかどうかはワーカーが時計で確かめる (関数 timed_out)。過ぎた後は、止められるまで 1 秒おきに送る — 1 度だけだと、
# ワーカーが wait を始める直前に届いた USR1 は wait を戻さず、その wait に上限が掛からない。更新時刻を進める処理と同じく、
# 周期ごとにワーカーが動いているかを確かめ、動いていなければ (kill -9 で trap が動かなかった場合も) 自分も終わる —
# 消えたワーカーの PID が別のプロセスに再利用されていると、USR1 (既定の動作は終了) がそのプロセスを止めてしまうため
start_watchdog() {
  (
    wd_sleep=""
    trap 'kill "$wd_sleep" 2>/dev/null; exit 0' TERM
    while worker_alive; do
      wd_left=$(( $1 - $(date +%s) ))
      if [ "$wd_left" -le 0 ]; then
        kill -USR1 "$WORKER_PID" 2>/dev/null
        wd_left=1
      fi
      [ "$wd_left" -gt "$POLL_SECONDS" ] && wd_left=$POLL_SECONDS
      sleep "$wd_left" &
      wd_sleep=$!
      wait "$wd_sleep"
    done
  ) &
  WATCHDOG_PID=$!
}

stop_watchdog() {
  if [ -n "$WATCHDOG_PID" ]; then
    stop_background "$WATCHDOG_PID"
    WATCHDOG_PID=""
  fi
}

# 上限を越えたか (依頼文を受け取った時刻から --review-timeout-minutes が過ぎたか)。時計で確かめる — USR1 は wait を戻すための
# 知らせで、前の回の上限を測る処理が止まる間際に送ったものが遅れて届くこともあるので、越えたことの根拠にしない
timed_out() {
  [ "$(date +%s)" -ge "$REQ_DEADLINE" ]
}

# 割り込みに応じられるように、sleep をバックグラウンドで起動して wait で待つ
idle_sleep() {
  sleep "$1" &
  SLEEP_PID=$!
  wait "$SLEEP_PID" 2>/dev/null
  SLEEP_PID=""
}

# 子プロセス $1 の終わりを 1 度待つ。終わっていれば終了コードを WAITED_RC に入れて 0 を返す。trap (割り込みや USR1) を実行したために
# wait が途中で戻り、子がまだ在れば 1 を返す (呼び出し元が上限を確かめてから待ち直す)。wait が途中で戻った直後に子が終わった場合も、
# 子の終了コードを受け取り直す (受け取り済みの子を待つと 127 が返るので、そのときは最初の値のままにする)
wait_once() {
  local rc
  wait "$1"
  WAITED_RC=$?
  [ "$WAITED_RC" -gt 128 ] || return 0
  kill -0 "$1" 2>/dev/null && return 1
  wait "$1" 2>/dev/null
  rc=$?
  [ "$rc" -eq 127 ] || WAITED_RC=$rc
  return 0
}

# 子プロセス $1 が終わるまで待ち、終了コードを WAITED_RC に入れる
wait_child() {
  until wait_once "$1"; do :; done
}

# プロセスグループ $1 に、終わっていないプロセスが無くなるのを $2 秒まで待つ。無くなれば 0 を返す
wait_group_gone() {
  local pgid=$1 limit=$2 i=0
  while [ "$i" -lt $(( limit * 5 )) ]; do
    group_alive "$pgid" || return 0
    sleep 0.2
    i=$(( i + 1 ))
  done
  ! group_alive "$pgid"
}

# 専用のプロセスグループで起動したコマンド (PID $1。プロセスグループの番号も同じ) を、プロセスグループごと止める。TERM を送り、
# STOP_GRACE_SECONDS 秒のうちに空にならなければ KILL を送る。待つ間に使う ps と sleep が、ワーカーのプロセスグループに届いた
# 割り込み (端末の Ctrl-C など) で止まらないように、INT・TERM・HUP を無視するサブシェルで行う (無視はコマンドに引き継がれる)。
# そのあとコマンドの終わりを待ち、終了コードを WAITED_RC に入れる
stop_group() {
  local pgid=$1
  (
    trap '' INT TERM HUP
    kill -TERM -- "-$pgid" 2>/dev/null || kill -TERM "$pgid" 2>/dev/null
    if ! wait_group_gone "$pgid" "$STOP_GRACE_SECONDS"; then
      kill -KILL -- "-$pgid" 2>/dev/null
      kill -KILL "$pgid" 2>/dev/null
      wait_group_gone "$pgid" "$STOP_GRACE_SECONDS" || log "プロセスグループ $pgid が止まらない"
    fi
  )
  wait_child "$pgid"
}

# ---- 終わり方 (正本は worker.md の「終わり方」) ----

cleanup() {
  stop_watchdog
  stop_heartbeat
  if [ -n "$SLEEP_PID" ]; then kill "$SLEEP_PID" 2>/dev/null; SLEEP_PID=""; fi
}

print_served() {
  echo "この起動で応じた回: $ROUNDS_SERVED 回"
  local line
  for line in ${SERVED_LINES[@]+"${SERVED_LINES[@]}"}; do
    echo "  $line"
  done
}

# 作業場所 (WS) が残っていれば片付ける。シンボリックリンクならリンクだけを消し (リンクの先は消さない)、ディレクトリなら、
# 中を cwd にしているプロセスを止めてから消す (回の終わりの処理の 1 と 5 の手順)
discard_workspace() {
  if [ -L "$WS" ]; then
    log "作業場所のパス $WS にシンボリックリンクが残っているので、リンクだけを消す"
    rm -f "$WS" 2>/dev/null
  elif [ -e "$WS" ]; then
    stop_cwd_procs "$WS"
    remove_workspace "$WS"
  fi
}

# 更新時刻を進める処理などを止め、worker.yaml を left にし、この起動で応じた回の一覧を出力して、終了コード $1 で終わる
leave() {
  FINISHING=1
  trap '' INT TERM HUP USR1
  CURRENT_RID=""
  PHASE=""
  cleanup
  write_worker_yaml left ""
  print_served
  exit "$1"
}

# 割り込み (INT / TERM / HUP) を受けたときの処理。受けた時点 (PHASE) で扱いが違う。
#   prep   (準備の途中): 準備のコマンドのプロセスグループを止め、作業場所を消す。印は書かない — レビュアの実行を起動していないので、
#          起動し直したワーカーが同じ依頼文を初めから処理する
#   review (レビュアの実行中): レビュアの実行を止め、回の終わりの処理を行って、failed・interrupted の印を書く
#   finish (回の終わりの処理の途中): 受けたことを控えて戻る。その回の印を書き終えてから、控えた終了コードで終わる
#          (関数 process_request)。印の無い回と、消し残した作業場所を作らないため
# finish のほかは、そのあと worker.yaml を left にして終わる
on_signal() {
  local sig=$1 code=$2
  [ "$FINISHING" = 0 ] || exit "$code"
  if [ "$PHASE" = finish ]; then
    if [ -z "$PENDING_CODE" ]; then
      PENDING_CODE=$code
      log "割り込み ($sig) を受けた。この回の印を書き終えてから終わる"
    fi
    return 0
  fi
  FINISHING=1
  trap '' INT TERM HUP USR1
  log "割り込み ($sig) を受けた"
  case "$PHASE" in
    prep)
      stop_watchdog
      if [ -n "$PREP_PID" ]; then
        stop_group "$PREP_PID"
        PREP_PID=""
      fi
      discard_workspace
      log "準備の途中だったので、印を書かずに終わる。起動し直したワーカーが、同じ依頼文を初めから処理する: $CURRENT_RID"
      ;;
    review)
      stop_watchdog
      if [ -n "$REVIEWER_PID" ]; then
        stop_group "$REVIEWER_PID"
        REVIEWER_RC=$WAITED_RC
        REVIEWER_PID=""
      fi
      run_finish interrupted
      ;;
  esac
  leave "$code"
}

trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP
# USR1 は、上限を測る処理が wait を途中で戻すための知らせ。上限を越えたかどうかは時計で確かめる (関数 timed_out)
trap ':' USR1
trap 'cleanup' EXIT

# ---- 回の処理 (正本は worker.md の「回の処理」) ----

# 置き場のファイルの一覧と更新時刻。ワーカーが回の間に書くもの (worker.yaml・その回のログ) と、
# 作業側が再開や停止のときにレビュー中でも書き換える loop.yaml は除く。その回の結果は除かない — 結果はワーカーが
# 比べた後に複写するので、比べる時点で置き場の結果が変わっていれば、レビュアの実行が置き場に書いたことになる
snapshot() {
  find "$LOOP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | LC_ALL=C sort | while IFS= read -r p; do
    n=${p##*/}
    case "$n" in
      worker.yaml|.worker.yaml.tmp|loop.yaml|.loop.yaml.tmp|"$CURRENT_RID.log") continue ;;
    esac
    echo "$n $(mtime "$p")"
  done
}

# ログ (stream-json) から、実効モデル・skill の呼び出し・拒否された呼び出し・実効の権限モード・サンドボックスが止めた確認を読む
# (読み方の正本は worker.md の「ログの読み方」)。標準出力に次の行を出す。値はどれも 1 行 (改行を含まない)。
#   1 行目: 実効モデルの名前 / 2 行目: skill_called / 3 行目: 拒否の件数 / 4 行目: 拒否されたツールの名前の列 (JSON) /
#   5 行目: 実効の権限モード / 6 行目: サンドボックスが止めた件数 /
#   7 行目から: 止められた呼び出しごとに、コマンドと文面の 2 行 (どちらも先頭 200 文字まで)
# 読めない値は unknown にする。サンドボックスが止めた件数が unknown なら、7 行目からの行は出さない
read_log_facts() {
  python3 - "$1" <<'PY'
import json, re, sys

# 印の YAML に書く値を 1 行に直すときに空白にする文字: 改行とタブを含む制御文字・行と段落の区切りの文字・
# 対になっていないサロゲート (JSON の \ud800 のように、2 つ組で 1 文字を表す符号の片方だけをエスケープで書いたもの)・
# 文字として使わない符号 (U+FFFE と U+FFFF)。どれも YAML の文字列にそのまま書けないか、書くと行が分かれるか、
# ワーカーがこの出力を行ごとに読むのを乱す
NOT_ONE_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff\ufffe\uffff]")
LIMIT = 200
PHRASE = "operation not permitted"   # ファイルの書き込みを止められたときの文面 (大文字と小文字を区別しない)
TAG = "<sandbox_violations>"         # 接続を止められたときに本文に付くタグ
TAG_END = "</sandbox_violations>"


def one_line(s, limit=None):
    s = NOT_ONE_LINE.sub(" ", s).strip()
    return s[:limit] if limit else s


def body_text(content):
    """tool_result の本文。文字列か、text の要素の text を改行で繋いだもの。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c["text"] for c in content
                         if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    return ""


def blocked_message(body):
    """本文のうち、文面を含む行と、タグの行から閉じるタグの行 (無ければ本文の終わり) までの行を、空白で繋ぐ。
    接続を止められたときは、止められたホストがタグの次の行にあるため、タグの中の行も含める。"""
    out = []
    in_tag = False
    for l in body.splitlines():
        if TAG in l:
            in_tag = True
        if in_tag or PHRASE in l.lower():
            out.append(l.strip())
        if TAG_END in l:
            in_tag = False
    return " ".join(x for x in out if x)


model = None
saw_assistant = False
skill = False
result = None
init_seen = False
mode = None
uses = {}      # tool_use の id → (ツールの名前, 入力の command)。sub-agent の行も含める
results = []   # tool_result の列 (ログの順)。sub-agent の行も含める
try:
    f = open(sys.argv[1], encoding="utf-8", errors="replace")
except OSError:
    f = []
for line in f:
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except ValueError:
        continue
    if not isinstance(o, dict):
        continue
    t = o.get("type")
    # サンドボックスが止めた確認を数えるための対応は、sub-agent の行 (parent_tool_use_id がある) からも作る
    if t in ("assistant", "user"):
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if t == "assistant" and c.get("type") == "tool_use" and isinstance(c.get("id"), str):
                inp = c.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                uses[c["id"]] = (c.get("name"), cmd if isinstance(cmd, str) else "")
            elif t == "user" and c.get("type") == "tool_result":
                results.append(c)
    # 実効モデル・skill の呼び出し・実効の権限モード・拒否は、最上位の行だけから読む
    if o.get("parent_tool_use_id"):
        continue
    if t == "system" and o.get("subtype") == "init":
        if model is None and isinstance(o.get("model"), str) and o["model"]:
            model = o["model"]
        # 実効の権限モードは、最初の init の行だけから読む (その行に無ければ unknown)
        if not init_seen:
            init_seen = True
            m = o.get("permissionMode")
            mode = one_line(m) if isinstance(m, str) else None
    elif t == "assistant":
        saw_assistant = True
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                skill = True
    elif t == "result":
        result = o

sys.stdout.reconfigure(encoding="utf-8")
name = "unknown"
if model:
    name = one_line(model[len("claude-"):] if model.startswith("claude-") else model) or "unknown"
print(name)
print(("true" if skill else "false") if saw_assistant else "unknown")
denials = result.get("permission_denials") if isinstance(result, dict) else None
if isinstance(denials, list):
    tools = []
    for d in denials:
        n = d.get("tool_name") if isinstance(d, dict) else None
        n = n if isinstance(n, str) and n else "unknown"
        if n not in tools:
            tools.append(n)
    print(len(denials))
    print(json.dumps(tools, ensure_ascii=False))
else:
    print("unknown")
    print("[]")
print(mode or "unknown")
if isinstance(result, dict):
    blocked = []
    for r in results:
        name_cmd = uses.get(r.get("tool_use_id"))
        if not name_cmd or name_cmd[0] != "Bash" or r.get("is_error") is not True:
            continue
        body = body_text(r.get("content"))
        if PHRASE in body.lower() or TAG in body:
            blocked.append((one_line(name_cmd[1], LIMIT), one_line(blocked_message(body), LIMIT)))
    print(len(blocked))
    for cmd, message in blocked:
        print(cmd)
        print(message)
else:
    print("unknown")
PY
}

# 完了の印を書き、この起動で応じた回の一覧に出す行を MARKER_LINE に入れる。ran=1 はレビュアの実行を起動した回。
# 一覧への追加 (関数 note_served) は呼び出し元が行う — 回の終わりの処理はサブシェルで行うので、ここで変数を変えても戻らないため
write_marker() {
  local status=$1 error=$2 ran=$3 head_after=${4:-} clean_after=${5:-} exit_code=${6:-}
  {
    echo "id: $(yaml_str "$CURRENT_RID")"
    echo "status: $status"
    echo "worker_version: $(yaml_str "$WORKER_VERSION")"
    echo "model:"
    echo "  specified: $(yaml_str "$MODEL")"
    echo "  effective: $(yaml_str "$EFFECTIVE")"
    echo "effort: $(yaml_str "$EFFORT")"
    echo "permission_mode:"
    echo "  specified: $(yaml_str "$PERMISSION_MODE")"
    echo "  effective: $(yaml_str "$EFFECTIVE_MODE")"
    echo "skill_called: $SKILL_CALLED"
    echo "permission_denials:"
    echo "  count: $DENIAL_COUNT"
    echo "  tools: $DENIAL_TOOLS"
    echo "sandbox_blocked:"
    echo "  count: $SANDBOX_COUNT"
    if [ -n "$SANDBOX_CALLS" ]; then
      echo "  calls:"
      printf '%s' "$SANDBOX_CALLS"
    else
      echo "  calls: []"
    fi
    echo "head_before: $(yaml_str "$HEAD_BEFORE")"
    if [ "$ran" = 1 ]; then
      echo "head_after: $(yaml_str "$head_after")"
      echo "tree_clean_after: $clean_after"
    fi
    echo "started: $(yaml_str "$REQ_STARTED")"
    echo "finished: $(yaml_str "$(now_iso)")"
    if [ "$ran" = 1 ]; then echo "exit_code: $exit_code"; fi
    if [ "$status" = failed ]; then echo "error: $(yaml_str "$error")"; fi
    if [ "$ran" = 1 ]; then echo "log: $(yaml_str "$CURRENT_RID.log")"; fi
  } | write_atomic "$LOOP_DIR/delivered-$CURRENT_RID.yaml"

  local elapsed=$(( $(date +%s) - REQ_STARTED_EPOCH ))
  local line="$CURRENT_RID  $status  model: $MODEL (実効: $EFFECTIVE)  effort: $EFFORT  所要: $(( elapsed / 60 ))分$(( elapsed % 60 ))秒"
  [ "$status" = failed ] && line="$line  error: $error"
  MARKER_LINE=$(printf '%s' "$line" | tr '\n' ' ')
  log "完了の印を書いた: $CURRENT_RID ($status${error:+: $error})"
}

# この起動で応じた回の一覧に 1 行 ($1) を足し、応じた回の数を 1 つ増やす
note_served() {
  SERVED_LINES+=("$1")
  ROUNDS_SERVED=$(( ROUNDS_SERVED + 1 ))
}

# ---- 回の作業場所・複製・写し・結果の複写に使う道具 (正本は worker.md の「回の処理」の手順 5〜10) ----

# 手順 5。作業場所を作る。前の回の作業場所が残っていれば、残ったプロセスを止めて消してから作る。
# シンボリックリンクが残っていれば、リンクだけを消す (リンクの先は消さない)。
# 作れなければ、完了の印の error に書く文字列を標準出力に出して、終了コード 1 で終わる
prepare_workspace() {
  local out
  if [ -e "$WS" ] && [ ! -L "$WS" ]; then
    log "前の回の作業場所 $WS が残っているので、消してから作る"
  fi
  discard_workspace
  if [ -e "$WS" ] || [ -L "$WS" ]; then
    echo "workspace failed (the previous workspace remains: $WS)"
    return 1
  fi
  if ! out=$(mkdir -m 700 "$WS" 2>&1); then
    echo "workspace failed (mkdir: $(last_line "$out"))"
    return 1
  fi
  if [ -L "$WS" ] || [ ! -d "$WS" ] || [ ! -O "$WS" ] || [ "$(real_dir "$WS")" != "$WS" ]; then
    echo "workspace failed (not a directory owned by the worker: $WS)"
    return 1
  fi
  return 0
}

# 手順 6 の段の失敗を、完了の印の error に書く文字列にする。$1 は段の名前、$2 は git の出力
clone_failed() {
  local detail
  detail=$(last_line "$2")
  echo "clone failed ($1${detail:+: $detail})"
}

# 準備のコマンド ($2 以降) を、作業場所を cwd にして、専用のプロセスグループでバックグラウンドに起動して待つ ($1 は出力に書く段の名前)。
# 標準出力と標準エラーは PREP_OUT に書く。レビュアの実行と同じ起動の仕方にするのは、上限を越えたときと割り込みを受けたときに、
# プロセスグループごと止められるようにするため (フォアグラウンドで待つと、bash は trap をコマンドが終わるまで遅らせる)。
# 起動する前か待つ間に上限を越えたら、プロセスグループを止め、PREP_TIMEOUT を 1 にして 1 を返す。そうでなければコマンドの終了コードを返す
run_prep() {
  local stage=$1
  shift
  if timed_out; then
    log "上限 ($REVIEW_TIMEOUT_MINUTES 分) を越えたので、準備の段 ($stage) を始めない"
    PREP_TIMEOUT=1
    return 1
  fi
  (
    cd "$WS" || exit 127
    exec python3 -c "$SETPGID_PY" "$@"
  ) </dev/null >"$PREP_OUT" 2>&1 &
  PREP_PID=$!
  until wait_once "$PREP_PID"; do
    if timed_out; then
      log "上限 ($REVIEW_TIMEOUT_MINUTES 分) を越えたので、準備の段 ($stage) のプロセスグループを止める"
      stop_group "$PREP_PID"
      PREP_PID=""
      PREP_TIMEOUT=1
      return 1
    fi
  done
  PREP_PID=""
  return "$WAITED_RC"
}

# 手順 6 の段を 1 つ行う。$1 は段の名前、残りは git の引数。通らなければ 1 を返し、上限を越えたためでなければ、
# 完了の印の error に書く文字列を PREP_ERROR に入れる
clone_stage() {
  local stage=$1
  shift
  run_prep "$stage" git "$@" && return 0
  [ "$PREP_TIMEOUT" = 1 ] || PREP_ERROR=$(clone_failed "$stage" "$(cat "$PREP_OUT" 2>/dev/null)")
  return 1
}

# 手順 6。作業側のリポジトリを作業場所の tree/ に複製し、依頼の head ($1。作業側で解決した完全な SHA) を detached HEAD で取り出す。
# 段は、複製 (clone)・remote の設定の削除 (remove remote)・ブランチとリモート追跡ブランチとタグの取り込み (fetch refs)・
# チェックアウト (checkout)・submodule の項目の検査 (submodule) の順で、どれも準備のコマンドとして起動する (関数 run_prep)。
# 通らなければ 1 を返す (理由は関数 clone_stage のとおり PREP_TIMEOUT か PREP_ERROR に入る)
make_clone() {
  local sha=$1 subs
  clone_stage clone clone -q --shared --no-checkout -- "$CWD_REAL" tree || return 1
  # remote の設定を消し、git push origin の行き先 (作業側のリポジトリ) を無くす
  clone_stage "remove remote" -C tree remote remove origin || return 1
  # --no-checkout の直後の HEAD は作業側と同じブランチを指すので、そのブランチも更新できるように --update-head-ok を付ける
  clone_stage "fetch refs" -C tree -c gc.auto=0 -c maintenance.auto=false fetch -q --update-head-ok --no-tags \
    --no-recurse-submodules "$CWD_REAL" '+refs/heads/*:refs/heads/*' '+refs/remotes/*:refs/remotes/*' \
    '+refs/tags/*:refs/tags/*' || return 1
  clone_stage checkout -C tree -c advice.detachedHead=false checkout -q --detach "$sha" || return 1
  clone_stage submodule -C tree ls-files -s || return 1
  subs=$(grep '^160000 ' "$PREP_OUT" | cut -f2 | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -n "$subs" ]; then
    PREP_ERROR="clone failed (submodule: $subs)"
    return 1
  fi
  return 0
}

# 手順 7。複製 ($1) の .claude/settings.json と .claude/settings.local.json のどちらかに、空でない sandbox.excludedCommands があるか、
# JSON として読めなければ、当たったものを 1 行に 1 つ出して、終了コード 1 で終わる。ファイルが無ければ何もしない
clone_settings_problem() {
  python3 - "$1" <<'PY'
import json, os, stat, sys

tree = sys.argv[1]
problems = []
for rel in (".claude/settings.json", ".claude/settings.local.json"):
    path = os.path.join(tree, rel)
    try:
        # シンボリックリンクなら先を読む (Claude Code もそうする)。通常のファイルでなければ読まない (/dev/zero などで止まらないように)
        if not stat.S_ISREG(os.stat(path).st_mode):
            problems.append(f"{rel}: not a regular file")
            continue
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        continue
    except (OSError, ValueError) as e:
        problems.append(f"{rel}: not readable as JSON ({e})")
        continue
    if not isinstance(settings, dict):
        problems.append(f"{rel}: top level is not an object")
        continue
    sandbox = settings.get("sandbox")
    excluded = sandbox.get("excludedCommands") if isinstance(sandbox, dict) else None
    if excluded:
        problems.append(f"{rel}: sandbox.excludedCommands is not empty ({json.dumps(excluded, ensure_ascii=False)})")
for p in problems:
    print(f"clone settings ({p})")
sys.exit(1 if problems else 0)
PY
}

# 手順 8。作業側の依頼文 ($1) の写しを、作業場所の $2 に作る。次の順に文字列を置き換える。
#   1. 元の出力先 (依頼文の「出力先:」の行の値) の、すべての出現 → 作業場所の結果のパス
#   2. バッククォートで囲んだ元の作業ツリーのパス (作業側の実体パス) → 複製のパス
#   3. 作業ツリーの扱いを示す行 (「- 作業ツリーの扱い: <値>」) の値 → 使い捨て
# 出力先は作業ツリーのパスで始まるので、この順でないと出力先が複製の中のパスになる。元の出力先は、置き場から組み立てたもの
# (実体が周回の置き場で、名前が review-<識別子>.yaml) でなければならない。置き換えの後に、元の出力先か元の作業ツリーのパスが
# 残っているか、扱いの行がちょうど 1 つでなければ通らない。写しを作る python3 は準備のコマンドとして起動する (関数 run_prep)。
# 通らなければ 1 を返し、上限を越えたためでなければ、完了の印の error に書く文字列を PREP_ERROR に入れる
make_request_copy() {
  local out
  run_prep "request copy" python3 -c "$(request_copy_py)" "$1" "$2" "$CURRENT_RID" "$LOOP_REAL" "$CWD_REAL" "$WS" "$CLONE" \
    && return 0
  [ "$PREP_TIMEOUT" = 1 ] && return 1
  out=$(last_line "$(cat "$PREP_OUT" 2>/dev/null)")
  case "$out" in
    "request copy failed ("*) PREP_ERROR=$out ;;
    *) PREP_ERROR="request copy failed (${out:-理由が分からない})" ;;
  esac
  return 1
}

# 手順 8 の写しを作る python3 のスクリプトを標準出力に出す (python3 -c に渡す)。引数は、依頼文・写し・識別子・周回の置き場の実体パス・
# 作業側の実体パス・作業場所・複製の順。通らなければ、完了の印の error に書く文字列を標準出力に出して、終了コード 1 で終わる
request_copy_py() {
  cat <<'PY'
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
PY
}

# 作業場所の結果 ($1) を確かめる (「回の処理」の表の「結果のファイル」)。通常のファイルで、実体パスが作業場所の下にあり、
# 大きさが RESULT_MAX_BYTES 以下なら何も出さずに終了コード 0 で、そうでなければ当たった条件を 1 行に 1 つ出して終了コード 1 で終わる。
# 中身は読まない (FIFO で止まらないように)
result_file_problem() {
  python3 - "$1" "$WS" "$RESULT_MAX_BYTES" <<'PY'
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
PY
}

# 手順 10 の 4。作業場所の結果 ($1) を、置き場の出力先 ($2) と同じディレクトリの一時名に書いてから改名して複写する。
# 結果はシンボリックリンクを辿らずに開き直し、通常のファイルで大きさが上限以下であることを確かめてから読む。
# 一時名もシンボリックリンクを辿らずに開く。改名の後に、出力先が通常のファイルとして在ることを確かめる。
# 失敗すれば理由を標準出力に出して、終了コード 1 で終わる
copy_result() {
  python3 - "$1" "$2" "$RESULT_MAX_BYTES" <<'PY'
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
PY
}

# ---- 回の処理の流れ (手順 2〜10) ----

# レビュアの実行を起動しなかった回の印 (依頼文・HEAD・作業ツリーの確認か、作業場所を作れない)。上限の計測を止めてから書く。
# ログから読む項目 (実効モデル・実効の権限モード・サンドボックスが止めた件数など) は、関数 process_request が回の初めに入れた
# unknown のまま書く
fail_without_run() {
  stop_watchdog
  write_marker failed "$1" 0
  note_served "$MARKER_LINE"
  CURRENT_RID=""
  PHASE=""
  write_worker_yaml idle ""
}

# 準備 (手順 5〜8) が通らなかった回。作業場所があれば、回の終わりの処理の 1 と 5 の手順で片付けてから、
# レビュアの実行を起動せずに failed の印を書く
fail_prepared() {
  discard_workspace
  fail_without_run "$1"
}

# 準備の途中で上限を越えた回。レビュアの実行を起動せずに、failed・timeout の印を書く
fail_timeout_in_preparation() {
  log "上限 ($REVIEW_TIMEOUT_MINUTES 分) を越えたので、レビュアの実行を起動しない"
  fail_prepared timeout
}

# 手順 6 か 8 が通らなかった回。上限を越えたためなら timeout を、そうでなければ段の失敗 (PREP_ERROR。無ければ $1) を error に書く
fail_preparation_stage() {
  if [ "$PREP_TIMEOUT" = 1 ]; then
    fail_timeout_in_preparation
  else
    fail_prepared "${PREP_ERROR:-$1}"
  fi
}

# 手順 10。レビュアの実行が終わった (または止めた) 後の処理と印。how は done / timeout / interrupted。
# 順序は、残ったプロセスを止める → ログを読む → 確かめる → 結果を複写する → 作業場所を消す → 印を書く。
# 関数 run_finish がサブシェルで呼ぶ。この起動で応じた回の一覧の行 (1 行目) と、この起動の間は処理しない依頼文の識別子
# (2 行目以降) を標準出力に出して、呼び出し元に返す
REVIEWER_RC=""
SNAPSHOT_BEFORE=""
finish_round() {
  local how=$1
  local ws_result="$WS/review-$CURRENT_RID.yaml"
  local dest="$LOOP_DIR/review-$CURRENT_RID.yaml"
  local errors=()
  local facts head_after full_after full_before dirty clean_after after changed problem line copyable=0 ignored="" n
  local fact fact_no=0 blocked_command=""

  # 1. 作業場所の中を cwd にしているプロセスが残っていれば止める (後始末の途中で作業場所に書かれないように)。
  # レビュアの実行の終了コード (REVIEWER_RC) は変えない
  stop_cwd_procs "$WS"

  # 2. ログを読む。行の並びは関数 read_log_facts の説明のとおり。7 行目からは、止められた呼び出しごとのコマンドと文面の 2 行で、
  # 完了の印の sandbox_blocked.calls の要素の YAML にする (値は yaml_str で二重引用符の文字列にする)
  facts=$(read_log_facts "$LOOP_DIR/$CURRENT_RID.log")
  SANDBOX_CALLS=""
  while IFS= read -r fact; do
    fact_no=$(( fact_no + 1 ))
    case $fact_no in
      1) EFFECTIVE=$fact ;;
      2) SKILL_CALLED=$fact ;;
      3) DENIAL_COUNT=$fact ;;
      4) DENIAL_TOOLS=$fact ;;
      5) EFFECTIVE_MODE=$fact ;;
      6) SANDBOX_COUNT=$fact ;;
      *)
        if [ $(( fact_no % 2 )) -eq 1 ]; then
          blocked_command=$fact
        else
          SANDBOX_CALLS="$SANDBOX_CALLS    - command: $(yaml_str "$blocked_command")
      message: $(yaml_str "$fact")
"
        fi ;;
    esac
  done <<EOF
$facts
EOF
  # python3 がログを読めずに何も出さなかったときは、読めなかったものとして扱う
  [ -n "$EFFECTIVE" ] || EFFECTIVE=unknown
  [ -n "$SKILL_CALLED" ] || SKILL_CALLED=unknown
  [ -n "$DENIAL_COUNT" ] || DENIAL_COUNT=unknown
  [ -n "$DENIAL_TOOLS" ] || DENIAL_TOOLS="[]"
  [ -n "$EFFECTIVE_MODE" ] || EFFECTIVE_MODE=unknown
  [ -n "$SANDBOX_COUNT" ] || SANDBOX_COUNT=unknown

  # 3. 確かめる。上限と割り込みで止めた回は、結果の 4 項目 (ある・ファイル・形・run_id) を確かめない。
  # 作業場所は回ごとに作り直すので、作業場所にある結果は、この回のレビュアの実行が書いたものである
  case "$how" in
    timeout) errors+=("timeout") ;;
    interrupted) errors+=("interrupted") ;;
  esac
  if [ -e "$ws_result" ] || [ -L "$ws_result" ]; then
    if problem=$(result_file_problem "$ws_result"); then
      copyable=1
      if [ "$how" = done ]; then
        grep -q '^findings:' "$ws_result" || errors+=("no findings key")
        local got
        got=$(read_key "$ws_result" run_id)
        [ "$got" = "$CURRENT_RID" ] || errors+=("run_id mismatch (expected $CURRENT_RID, actual \"$got\")")
      fi
    elif [ "$how" = done ]; then
      [ -n "$problem" ] || problem="result not checked (python3 が理由を出さずに終わった)"
      while IFS= read -r line; do
        [ -n "$line" ] && errors+=("$line")
      done <<EOF
$problem
EOF
    fi
  elif [ "$how" = done ]; then
    errors+=("no result")
  fi

  # 実効の権限モード。上限と割り込みで止めた回も確かめる。ログから読めなければ (unknown) 問わない —
  # 手動のモードに戻った回は、拒否された呼び出しとして別に現れる
  if [ "$EFFECTIVE_MODE" != unknown ] && [ "$EFFECTIVE_MODE" != "$PERMISSION_MODE" ]; then
    errors+=("permission mode mismatch (expected $PERMISSION_MODE, actual $EFFECTIVE_MODE)")
  fi

  # 作業側の HEAD と作業ツリー。git は作業側のリポジトリに対して実行する (複製では実行しない)
  head_after=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null)
  full_after=$(git -C "$CWD_REAL" rev-parse HEAD 2>/dev/null)
  full_before=$(git -C "$CWD_REAL" rev-parse --verify -q "$HEAD_BEFORE^{commit}" 2>/dev/null)
  [ "$full_after" = "$full_before" ] || errors+=("head changed (before $HEAD_BEFORE, after $head_after)")
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -z "$dirty" ]; then clean_after=true; else clean_after=false; errors+=("tree not clean ($dirty)"); fi

  # 置き場。依頼文を受け取ったときに控えた一覧と比べる (結果の複写より前に比べる)
  after=$(snapshot)
  changed=$( { echo "$SNAPSHOT_BEFORE"; echo "$after"; } | sed '/^$/d' | LC_ALL=C sort | uniq -u | sed 's/ [^ ]*$//' | LC_ALL=C sort -u | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -n "$changed" ]; then
    errors+=("loop dir modified ($changed)")
    # レビュアの実行が置いた依頼文は、この起動の間は処理しない
    for n in $(echo "$changed" | tr -d ','); do
      case "$n" in
        review-request-*.md) n=${n#review-request-}; ignored="$ignored ${n%.md}" ;;
      esac
    done
  fi

  # 4. 結果を複写する。failed の回でも、結果のファイルの条件を満たせば複写する (RA1 の報告から人間が結果を読めるように)。
  # ok の印は、置き場の出力先に結果が通常のファイルとして在ることを copy_result が確かめた後にだけ書ける
  if [ "$copyable" = 1 ]; then
    if ! problem=$(copy_result "$ws_result" "$dest"); then
      errors+=("result copy failed (${problem:-理由が分からない})")
    fi
  fi

  # 5. 作業場所を消す。消せなくても印の status は変えない (次の回の手順 5 か、次の起動の掃除で消す)
  remove_workspace "$WS"

  # 6. 印を書く
  if [ ${#errors[@]} -eq 0 ]; then
    write_marker ok "" 1 "$head_after" "$clean_after" "$REVIEWER_RC"
  else
    local joined="" e
    for e in "${errors[@]}"; do joined="${joined:+$joined; }$e"; done
    write_marker failed "$joined" 1 "$head_after" "$clean_after" "$REVIEWER_RC"
  fi
  printf '%s\n' "$MARKER_LINE"
  for n in $ignored; do printf '%s\n' "$n"; done
}

# 手順 10 (回の終わりの処理) を行う。how は done / timeout / interrupted。
# 端末の Ctrl-C のようにワーカーのプロセスグループ全体に届く割り込みで、回の終わりの処理が起動したコマンド (結果の複写や
# 作業場所の削除) が止まらないように、INT・TERM・HUP を無視するサブシェルで行う (無視はコマンドに引き継がれる)。
# ワーカー自身は、サブシェルを待つ間に受けた割り込みを控えておき (関数 on_signal)、印を書き終えてから処理する。
# サブシェルで変えた変数は戻らないので、この起動で応じた回の一覧の行と、処理しない依頼文の識別子を標準出力で受け取る
run_finish() {
  local how=$1 out line first=1
  PHASE=finish
  out=$(trap '' INT TERM HUP; finish_round "$how")
  if [ -z "$out" ]; then
    log "回の終わりの処理が、印を書いたことを知らせずに終わった: $CURRENT_RID"
    return 0
  fi
  while IFS= read -r line; do
    if [ "$first" = 1 ]; then
      note_served "$line"
      first=0
    elif [ -n "$line" ]; then
      IGNORED_REQUESTS="$IGNORED_REQUESTS$line "
    fi
  done <<EOF
$out
EOF
}

# 手順 9。レビュアの実行を、複製を cwd にして、専用のプロセスグループでバックグラウンドに起動して待つ。
# 引数の中身と理由の正本は worker.md の「レビュアの実行」と「レビュアの実行の権限」
run_reviewer() {
  local copy=$1 logf=$2
  local prompt="依頼文 $copy のとおりに作業し、結果を依頼文が指す出力先に書く。"
  local tools=() denied=()
  if [ ${#ALLOWED_TOOLS[@]} -gt 0 ]; then
    tools=("${ALLOWED_TOOLS[@]}")
  else
    tools=("${DEFAULT_ALLOWED_TOOLS[@]}")
  fi
  # 作業場所の結果ファイル 1 つへの書き込みの許可。// の後にルートからのパスを続ける (Claude Code の規則で絶対パスを表す書き方)
  tools+=("Edit(/$WS/review-$CURRENT_RID.yaml)")
  # 拒否の規則。ホーム・作業側・周回の置き場への書き込みと、複製の中の Claude Code と git が後で読んで実行するものの書き換えと、
  # git push を止める。WebFetch・WebSearch とネットワークのコマンドは拒否しない (接続できるかはサンドボックスの接続先の一覧で決まる)
  denied=(
    'AskUserQuestion'
    'Edit(~/**)'
    "Edit(/$CWD_REAL/**)"
    "Edit(/$LOOP_REAL/**)"
    "Edit(/$CLONE/.claude/**)"
    "Edit(/$CLONE/.git/**)"
    "Edit(/$CLONE/.mcp.json)"
    'Bash(git push:*)'
  )

  (
    cd "$CLONE" || exit 127
    exec python3 -c "$SETPGID_PY" \
      claude -p "$prompt" \
      --model "$MODEL" --effort "$EFFORT" --permission-mode "$PERMISSION_MODE" \
      --settings "$SETTINGS_JSON" --strict-mcp-config \
      --allowedTools "${tools[@]}" \
      --disallowedTools "${denied[@]}" \
      --output-format stream-json --verbose \
      ${EXTRA_PASS[@]+"${EXTRA_PASS[@]}"}
  ) </dev/null >"$logf" 2>&1 &
  REVIEWER_PID=$!
  PHASE=review
  until wait_once "$REVIEWER_PID"; do
    if timed_out; then
      # 上限を越えたときは、レビュアの実行のプロセスグループを止めるところから回の終わりの処理 (その間の割り込みは後で処理する)
      PHASE=finish
      log "上限 ($REVIEW_TIMEOUT_MINUTES 分) を越えたので、レビュアの実行を止める"
      stop_watchdog
      stop_group "$REVIEWER_PID"
      REVIEWER_RC=$WAITED_RC
      REVIEWER_PID=""
      run_finish timeout
      return
    fi
  done
  PHASE=finish
  REVIEWER_RC=$WAITED_RC
  REVIEWER_PID=""
  stop_watchdog
  run_finish done
}

process_request() {
  PHASE=prep
  CURRENT_RID=$1
  REQ_STARTED=$(now_iso)
  REQ_STARTED_EPOCH=$(date +%s)
  REQ_DEADLINE=$(( REQ_STARTED_EPOCH + REVIEW_TIMEOUT_SECONDS ))
  # ログから読む項目。レビュアの実行を起動しなかった回の印には、この unknown のまま書く
  EFFECTIVE="unknown"
  SKILL_CALLED="unknown"
  DENIAL_COUNT="unknown"
  DENIAL_TOOLS="[]"
  EFFECTIVE_MODE="unknown"
  SANDBOX_COUNT="unknown"
  SANDBOX_CALLS=""
  REVIEWER_RC=""
  PREP_TIMEOUT=0
  PREP_ERROR=""
  PENDING_CODE=""
  PREP_OUT="$WS/.prep-output"
  # 手順 2。上限の計測を始め、worker.yaml を reviewing にして識別子と作業場所のパスを書き、置き場のファイルの一覧と更新時刻を
  # 控える (回の終わりの処理で比べる。準備の途中に現れた end も検出するため、ここで控える)
  start_watchdog "$REQ_DEADLINE"
  write_worker_yaml reviewing "$CURRENT_RID"
  log "依頼文を見つけた: $CURRENT_RID"
  SNAPSHOT_BEFORE=$(snapshot)

  local req="$LOOP_DIR/review-request-$CURRENT_RID.md"
  local copy="$WS/review-request-$CURRENT_RID.md"
  local logf="$LOOP_DIR/$CURRENT_RID.log"
  HEAD_BEFORE=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null)

  # 手順 3。依頼文を確かめる
  if grep -q '{{' "$req"; then fail_without_run "request malformed (unfilled placeholder)"; return; fi
  if ! grep -q '^## 出力様式' "$req"; then fail_without_run "request malformed (no output format section)"; return; fi
  local req_head
  req_head=$(sed -n 's/^head:[[:space:]]*"\([0-9a-f][0-9a-f]*\)"[[:space:]]*$/\1/p' "$req" | head -n 1)
  if [ -z "$req_head" ]; then fail_without_run "request malformed (no head line)"; return; fi

  # 手順 4。作業側の HEAD と作業ツリーを確かめる
  if timed_out; then fail_timeout_in_preparation; return; fi
  local full_req full_head dirty
  full_req=$(git -C "$CWD_REAL" rev-parse --verify -q "$req_head^{commit}" 2>/dev/null)
  full_head=$(git -C "$CWD_REAL" rev-parse HEAD 2>/dev/null)
  if [ -z "$full_req" ] || [ "$full_req" != "$full_head" ]; then
    fail_without_run "head mismatch (expected $req_head, actual $HEAD_BEFORE)"; return
  fi
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -n "$dirty" ]; then fail_without_run "tree not clean ($dirty)"; return; fi

  # 手順 5〜8。準備のどれかが通らなければ、レビュアの実行を起動しない。上限を越えたかは、各段の前に確かめる
  # (手順 6 の各段と手順 8 では、関数 run_prep が起動する前と待つ間に確かめる)
  local problem
  if timed_out; then fail_timeout_in_preparation; return; fi
  if ! problem=$(prepare_workspace); then
    fail_without_run "${problem:-workspace failed (理由が分からない)}"; return
  fi
  if ! make_clone "$full_req"; then
    fail_preparation_stage "clone failed (理由が分からない)"; return
  fi
  if timed_out; then fail_timeout_in_preparation; return; fi
  if ! problem=$(clone_settings_problem "$CLONE"); then
    [ -n "$problem" ] || problem="clone settings (python3 が理由を出さずに終わった)"
    fail_prepared "$(join_lines "$problem")"; return
  fi
  if ! make_request_copy "$req" "$copy"; then
    fail_preparation_stage "request copy failed (理由が分からない)"; return
  fi
  rm -f "$PREP_OUT"

  # 手順 9。準備の段の合間に上限を越えていれば、レビュアの実行を起動しない
  if timed_out; then fail_timeout_in_preparation; return; fi
  log "レビュアの実行を起動する: claude -p --model $MODEL --effort $EFFORT --permission-mode $PERMISSION_MODE (cwd: ${CLONE}、上限 $REVIEW_TIMEOUT_MINUTES 分)"
  run_reviewer "$copy" "$logf"
  # 回の終わりの処理の途中に割り込みを受けていれば、印を書き終えたので、ここで終わる
  if [ -n "$PENDING_CODE" ]; then leave "$PENDING_CODE"; fi
  CURRENT_RID=""
  PHASE=""
  write_worker_yaml idle ""
}

# 印の無い依頼文のうち、識別子の順で最初の 1 つ
next_request() {
  find "$LOOP_DIR" -mindepth 1 -maxdepth 1 -type f -name 'review-request-*.md' 2>/dev/null \
    | sed -e 's|.*/review-request-||' -e 's|\.md$||' | LC_ALL=C sort | while IFS= read -r id; do
      [ -e "$LOOP_DIR/delivered-$id.yaml" ] && continue
      case "$IGNORED_REQUESTS" in *" $id "*) continue ;; esac
      echo "$id"
      break
    done
}

# ---- 本体 ----

write_worker_yaml idle ""
start_heartbeat
log "ワーカーを起動した: 版 $WORKER_VERSION / 置き場 $LOOP_DIR / モデル $MODEL / effort $EFFORT / 権限モード $PERMISSION_MODE"

idle_since=$(date +%s)
while :; do
  if [ -e "$LOOP_DIR/end" ]; then
    FINISHING=1
    trap '' INT TERM HUP
    # 周回の作業場所が残っていれば消す (消せなかった回の作業場所など)
    discard_workspace
    cleanup
    write_worker_yaml left ""
    log "end を見たので終わる"
    print_served
    exit 0
  fi
  rid=$(next_request)
  if [ -n "$rid" ]; then
    process_request "$rid"
    idle_since=$(date +%s)
    continue
  fi
  now=$(date +%s)
  if [ $(( now - idle_since )) -ge "$IDLE_SECONDS" ]; then
    FINISHING=1
    trap '' INT TERM HUP
    cleanup
    write_worker_yaml expired ""
    log "印の無い依頼文が無いまま $IDLE_MINUTES 分が過ぎたので終わる。周回は終わっていない — 同じコマンドで起動し直せる"
    print_served
    exit 124
  fi
  wait_for=$(( IDLE_SECONDS - (now - idle_since) ))
  [ "$wait_for" -gt "$POLL_SECONDS" ] && wait_for=$POLL_SECONDS
  idle_sleep "$wait_for"
done
