#!/usr/bin/env bash
# review-loop のワーカー。人間が端末で起動し、周回の置き場に現れた依頼文ごとに claude -p を走らせて、
# 結果を確かめてから完了の印を書く。
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
# GNU の stat でも動くようにしておく。python3 が要る (claude -p を専用のプロセスグループで起動する・
# ログ (stream-json) を読む・プラグインの版を読む・--settings の値と利用者の設定を JSON として検査する・
# パスの実体を求めるのに使う)。

set -u

WORKER_PID=$$
POLL_SECONDS=5              # 依頼文を探す周期と、worker.yaml の更新時刻を進める周期
OTHER_WORKER_FRESH_SECONDS=30  # 起動時の確認で、他のワーカーが動いていると判定する更新時刻の新しさ
STOP_GRACE_SECONDS=5        # レビュアの実行を TERM で止めてから KILL を送るまでの猶予

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
TIMED_OUT=0
FINISHING=0

# 回ごとの状態
CURRENT_RID=""
REQ_STARTED=""
REQ_STARTED_EPOCH=0
HEAD_BEFORE=""
EFFECTIVE="unknown"
SKILL_CALLED="unknown"
DENIAL_COUNT="unknown"
DENIAL_TOOLS="[]"

write_worker_yaml() {
  local state=$1 current=$2 error=${3:-}
  {
    echo "state: $state"
    echo "current_request: $(yaml_str "$current")"
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

# 2. 前の起動の作業場所を片付ける (掃除)。作業場所を作る処理がまだ無いので、今は片付けるものが無い

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

# 13. 追加の引数 (-- の後) が、受け付ける一覧に収まるか。制限を弱めるフラグは列挙しきれないので、受け付けるものの一覧で検査する
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

stop_heartbeat() {
  if [ -n "$HEARTBEAT_PID" ]; then
    kill -TERM "$HEARTBEAT_PID" 2>/dev/null
    wait "$HEARTBEAT_PID" 2>/dev/null
    HEARTBEAT_PID=""
  fi
}

# 上限の秒数が過ぎたらワーカーに USR1 を送る。更新時刻を進める処理と同じく、周期ごとにワーカーが動いているかを確かめ、
# 動いていなければ (kill -9 で trap が動かなかった場合も) 自分も終わる — 消えたワーカーの PID が別のプロセスに再利用されていると、
# USR1 (既定の動作は終了) がそのプロセスを止めてしまうため
start_watchdog() {
  (
    wd_sleep=""
    trap 'kill "$wd_sleep" 2>/dev/null; exit 0' TERM
    wd_deadline=$(( $(date +%s) + $1 ))
    while worker_alive; do
      wd_left=$(( wd_deadline - $(date +%s) ))
      if [ "$wd_left" -le 0 ]; then
        kill -USR1 "$WORKER_PID" 2>/dev/null
        exit 0
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
    kill -TERM "$WATCHDOG_PID" 2>/dev/null
    wait "$WATCHDOG_PID" 2>/dev/null
    WATCHDOG_PID=""
  fi
}

# 割り込みに応じられるように、sleep をバックグラウンドで起動して wait で待つ
idle_sleep() {
  sleep "$1" &
  SLEEP_PID=$!
  wait "$SLEEP_PID" 2>/dev/null
  SLEEP_PID=""
}

# レビュアの実行のプロセスグループ全体を止める (TERM、猶予の後に残っていれば KILL)。終了コードを REVIEWER_RC に入れる
wait_group_gone() {
  local pgid=$1 limit=$2 i=0
  while [ "$i" -lt $(( limit * 5 )) ]; do
    group_alive "$pgid" || return 0
    sleep 0.2
    i=$(( i + 1 ))
  done
  ! group_alive "$pgid"
}

stop_reviewer() {
  local pid=$REVIEWER_PID
  [ -n "$pid" ] || return 0
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  if ! wait_group_gone "$pid" "$STOP_GRACE_SECONDS"; then
    kill -KILL -- "-$pid" 2>/dev/null
    kill -KILL "$pid" 2>/dev/null
    wait_group_gone "$pid" "$STOP_GRACE_SECONDS" || log "レビュアの実行のプロセスグループ $pid が止まらない"
  fi
  wait "$pid" 2>/dev/null
  REVIEWER_RC=$?
}

# ---- 終わり方 ----

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

on_signal() {
  local sig=$1 code=$2
  [ "$FINISHING" = 0 ] || exit "$code"
  FINISHING=1
  trap '' INT TERM HUP USR1
  log "割り込み ($sig) を受けた"
  if [ -n "$REVIEWER_PID" ]; then
    stop_reviewer
    REVIEWER_PID=""
    finish_round interrupted
  fi
  cleanup
  write_worker_yaml left ""
  print_served
  exit "$code"
}

trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP
trap 'TIMED_OUT=1' USR1
trap 'cleanup' EXIT

# ---- 回の処理 (正本は worker.md の「回の処理」) ----

# 置き場のファイルの一覧と更新時刻。ワーカーとレビュアの実行が書いてよいもの (worker.yaml・結果・ログ) と、
# 作業側が再開や停止のときにレビュー中でも書き換える loop.yaml は除く
snapshot() {
  find "$LOOP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | LC_ALL=C sort | while IFS= read -r p; do
    n=${p##*/}
    case "$n" in
      worker.yaml|.worker.yaml.tmp|loop.yaml|.loop.yaml.tmp|"review-$CURRENT_RID.yaml"|"$CURRENT_RID.log") continue ;;
    esac
    echo "$n $(mtime "$p")"
  done
}

# ログ (stream-json) から、実効モデル・skill の呼び出し・拒否された呼び出しを読む (読み方の正本は worker.md の「ログの読み方」)
read_log_facts() {
  python3 - "$1" <<'PY'
import json, sys

model = None
saw_assistant = False
skill = False
result = None
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
    if not isinstance(o, dict) or o.get("parent_tool_use_id"):
        continue
    t = o.get("type")
    if t == "system" and o.get("subtype") == "init":
        if model is None and isinstance(o.get("model"), str) and o["model"]:
            model = o["model"]
    elif t == "assistant":
        saw_assistant = True
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                skill = True
    elif t == "result":
        result = o

name = "unknown"
if model:
    name = model[len("claude-"):] if model.startswith("claude-") else model
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
PY
}

# 完了の印を書く。ran=1 はレビュアの実行を起動した回
write_marker() {
  local status=$1 error=$2 ran=$3 head_after=${4:-} clean_after=${5:-} exit_code=${6:-}
  {
    echo "id: $(yaml_str "$CURRENT_RID")"
    echo "status: $status"
    echo "model:"
    echo "  specified: $(yaml_str "$MODEL")"
    echo "  effective: $(yaml_str "$EFFECTIVE")"
    echo "effort: $(yaml_str "$EFFORT")"
    echo "skill_called: $SKILL_CALLED"
    echo "permission_denials:"
    echo "  count: $DENIAL_COUNT"
    echo "  tools: $DENIAL_TOOLS"
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
  SERVED_LINES+=("$line")
  ROUNDS_SERVED=$(( ROUNDS_SERVED + 1 ))
  log "完了の印を書いた: $CURRENT_RID ($status${error:+: $error})"
}

# レビュアの実行を起動しなかった回の印 (依頼文・HEAD・作業ツリーの確認が通らない)
fail_without_run() {
  write_marker failed "$1" 0
  CURRENT_RID=""
  write_worker_yaml idle ""
}

# レビュアの実行が終わった (または止めた) 後の確認と印。how は done / timeout / interrupted
REVIEWER_RC=""
SNAPSHOT_BEFORE=""
RESULT_SIG_BEFORE=""
finish_round() {
  local how=$1
  local result="$LOOP_DIR/review-$CURRENT_RID.yaml"
  local errors=()
  local facts head_after full_after full_before dirty clean_after after changed

  facts=$(read_log_facts "$LOOP_DIR/$CURRENT_RID.log")
  EFFECTIVE=$(echo "$facts" | sed -n 1p)
  SKILL_CALLED=$(echo "$facts" | sed -n 2p)
  DENIAL_COUNT=$(echo "$facts" | sed -n 3p)
  DENIAL_TOOLS=$(echo "$facts" | sed -n 4p)
  # python3 がログを読めずに何も出さなかったときは、読めなかったものとして扱う
  [ -n "$EFFECTIVE" ] || EFFECTIVE=unknown
  [ -n "$SKILL_CALLED" ] || SKILL_CALLED=unknown
  [ -n "$DENIAL_COUNT" ] || DENIAL_COUNT=unknown
  [ -n "$DENIAL_TOOLS" ] || DENIAL_TOOLS="[]"

  case "$how" in
    timeout) errors+=("timeout") ;;
    interrupted) errors+=("interrupted") ;;
    done)
      if [ ! -f "$result" ]; then
        errors+=("no result")
      elif [ -n "$RESULT_SIG_BEFORE" ] && [ "$(mtime "$result") $(wc -c <"$result")" = "$RESULT_SIG_BEFORE" ]; then
        errors+=("no result (the file is from an earlier run)")
      else
        grep -q '^findings:' "$result" || errors+=("no findings key")
        local got
        got=$(read_key "$result" run_id)
        [ "$got" = "$CURRENT_RID" ] || errors+=("run_id mismatch (expected $CURRENT_RID, actual \"$got\")")
      fi ;;
  esac

  head_after=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null)
  full_after=$(git -C "$CWD_REAL" rev-parse HEAD 2>/dev/null)
  full_before=$(git -C "$CWD_REAL" rev-parse --verify -q "$HEAD_BEFORE^{commit}" 2>/dev/null)
  [ "$full_after" = "$full_before" ] || errors+=("head changed (before $HEAD_BEFORE, after $head_after)")
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -z "$dirty" ]; then clean_after=true; else clean_after=false; errors+=("tree not clean ($dirty)"); fi

  after=$(snapshot)
  changed=$( { echo "$SNAPSHOT_BEFORE"; echo "$after"; } | sed '/^$/d' | LC_ALL=C sort | uniq -u | sed 's/ [^ ]*$//' | LC_ALL=C sort -u | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -n "$changed" ]; then
    errors+=("loop dir modified ($changed)")
    # レビュアの実行が置いた依頼文は、この起動の間は処理しない
    local n
    for n in $(echo "$changed" | tr -d ','); do
      case "$n" in
        review-request-*.md) n=${n#review-request-}; IGNORED_REQUESTS="$IGNORED_REQUESTS${n%.md} " ;;
      esac
    done
  fi

  if [ ${#errors[@]} -eq 0 ]; then
    write_marker ok "" 1 "$head_after" "$clean_after" "$REVIEWER_RC"
  else
    local joined="" e
    for e in "${errors[@]}"; do joined="${joined:+$joined; }$e"; done
    write_marker failed "$joined" 1 "$head_after" "$clean_after" "$REVIEWER_RC"
  fi
}

run_reviewer() {
  local req=$1 result=$2 logf=$3
  local prompt="依頼文 $req のとおりに作業し、結果を依頼文が指す出力先に書く。"
  local tools=()
  if [ ${#ALLOWED_TOOLS[@]} -gt 0 ]; then
    tools=("${ALLOWED_TOOLS[@]}")
  else
    tools=("${DEFAULT_ALLOWED_TOOLS[@]}")
  fi
  # 結果ファイル 1 つへの書き込みの許可。// の後にルートからのパスを続ける
  tools+=("Edit(/$result)")

  TIMED_OUT=0
  (
    cd "$CWD_REAL" || exit 127
    exec python3 -c 'import os, sys; os.setpgid(0, 0); os.execvp(sys.argv[1], sys.argv[1:])' \
      claude -p "$prompt" \
      --model "$MODEL" --effort "$EFFORT" --permission-mode "$PERMISSION_MODE" \
      --allowedTools "${tools[@]}" \
      --disallowedTools AskUserQuestion \
      --output-format stream-json --verbose \
      ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
  ) </dev/null >"$logf" 2>&1 &
  REVIEWER_PID=$!
  start_watchdog "$REVIEW_TIMEOUT_SECONDS"
  wait "$REVIEWER_PID"
  REVIEWER_RC=$?
  if [ "$TIMED_OUT" = 1 ] && [ "$REVIEWER_RC" -gt 128 ]; then
    log "上限 ($REVIEW_TIMEOUT_MINUTES 分) を越えたので、レビュアの実行を止める"
    stop_reviewer
    REVIEWER_PID=""
    stop_watchdog
    finish_round timeout
  else
    REVIEWER_PID=""
    stop_watchdog
    finish_round done
  fi
}

process_request() {
  CURRENT_RID=$1
  REQ_STARTED=$(now_iso)
  REQ_STARTED_EPOCH=$(date +%s)
  EFFECTIVE="unknown"
  SKILL_CALLED="unknown"
  DENIAL_COUNT="unknown"
  DENIAL_TOOLS="[]"
  REVIEWER_RC=""
  write_worker_yaml reviewing "$CURRENT_RID"
  log "依頼文を見つけた: $CURRENT_RID"

  local req="$LOOP_DIR/review-request-$CURRENT_RID.md"
  local result="$LOOP_DIR/review-$CURRENT_RID.yaml"
  local logf="$LOOP_DIR/$CURRENT_RID.log"
  HEAD_BEFORE=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null)

  # 依頼文の検査
  if grep -q '{{' "$req"; then fail_without_run "request malformed (unfilled placeholder)"; return; fi
  if ! grep -q '^## 出力様式' "$req"; then fail_without_run "request malformed (no output format section)"; return; fi
  local req_head
  req_head=$(sed -n 's/^head:[[:space:]]*"\([0-9a-f][0-9a-f]*\)"[[:space:]]*$/\1/p' "$req" | head -n 1)
  if [ -z "$req_head" ]; then fail_without_run "request malformed (no head line)"; return; fi

  # HEAD と作業ツリーの確認
  local full_req full_head dirty
  full_req=$(git -C "$CWD_REAL" rev-parse --verify -q "$req_head^{commit}" 2>/dev/null)
  full_head=$(git -C "$CWD_REAL" rev-parse HEAD 2>/dev/null)
  if [ -z "$full_req" ] || [ "$full_req" != "$full_head" ]; then
    fail_without_run "head mismatch (expected $req_head, actual $HEAD_BEFORE)"; return
  fi
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g')
  if [ -n "$dirty" ]; then fail_without_run "tree not clean ($dirty)"; return; fi

  SNAPSHOT_BEFORE=$(snapshot)
  RESULT_SIG_BEFORE=""
  if [ -f "$result" ]; then RESULT_SIG_BEFORE="$(mtime "$result") $(wc -c <"$result")"; fi

  log "レビュアの実行を起動する: claude -p --model $MODEL --effort $EFFORT (上限 $REVIEW_TIMEOUT_MINUTES 分)"
  run_reviewer "$req" "$result" "$logf"
  CURRENT_RID=""
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
