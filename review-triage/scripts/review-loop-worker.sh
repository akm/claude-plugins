#!/usr/bin/env bash
# review-loop のワーカー。人間が端末で起動し、周回の置き場に現れた依頼文ごとに claude -p を走らせて、
# 結果を確かめてから完了の印を書く。
#
# 使い方:
#   review-loop-worker.sh <周回の置き場の絶対パス> --model <指定> --effort <値>
#       [--permission-mode <値>] [--allowed-tools <ツール>]... [--idle-minutes <分>]
#       [--review-timeout-minutes <分>] [-- <claude に渡す追加の引数>...]
#
# --model と --effort は必須で、既定を持たない (どのモデルと effort でレビューするかは人間が決める)。
# 作業側 (review-loop) と同じ作業ツリーで起動する。周回の間は作業ツリーを変えない。
#
# 終了コード: 0 = end を見て終わった / 124 = 依頼文が無いまま --idle-minutes が過ぎた /
#             2 = 引数の誤り・起動時の確認が通らない・他のワーカーが動いている /
#             128 + シグナル番号 = 割り込み (INT / TERM / HUP)
#
# 振る舞いの正本は review-triage/skills/review-loop/references/worker.md (起動時の確認・回の処理・
# 権限の既定・ログの読み方)、置き場のファイルの様式の正本は同じディレクトリの loop-files.md。
# 設定ファイルは読まない — 値はすべて引数で受け、作業側が案内のコマンドに埋める。
#
# macOS の /bin/bash (3.2) と Linux の bash、GNU と BSD の stat で動かす。python3 が要る
# (claude -p を専用のプロセスグループで起動するのと、ログ (stream-json) を読むのに使う)。

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
    [--permission-mode <値>] [--allowed-tools <ツール>]... [--idle-minutes <分>]
    [--review-timeout-minutes <分>] [-- <claude に渡す追加の引数>...]
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
PERMISSION_MODE="default"
ALLOWED_TOOLS=()
IDLE_MINUTES=180
REVIEW_TIMEOUT_MINUTES=60
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --model) [ $# -ge 2 ] || usage; MODEL=$2; shift 2 ;;
    --effort) [ $# -ge 2 ] || usage; EFFORT=$2; shift 2 ;;
    --permission-mode) [ $# -ge 2 ] || usage; PERMISSION_MODE=$2; shift 2 ;;
    --allowed-tools) [ $# -ge 2 ] || usage; ALLOWED_TOOLS+=("$2"); shift 2 ;;
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

# ---- 状態 ----

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
    echo "model: $(yaml_str "$MODEL")"
    echo "effort: $(yaml_str "$EFFORT")"
    echo "permission_mode: $(yaml_str "$PERMISSION_MODE")"
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

# ---- 起動時の確認 (正本は worker.md の「起動時の確認」の表) ----

STARTED=$(now_iso)

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

# 2. loop.yaml があり、repo_dir が読めるか
[ -f "$LOOP_DIR/loop.yaml" ] || unavailable "loop.yaml が無い"
REPO_DIR=$(read_key "$LOOP_DIR/loop.yaml" repo_dir)
[ -n "$REPO_DIR" ] || unavailable "loop.yaml の repo_dir が読めない"

# 3. 作業側と同じ作業ツリーで起動したか
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
START_HEAD=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null) || unavailable "HEAD が読めない"

# 4. 周回が終わっていないか
[ ! -e "$LOOP_DIR/end" ] || unavailable "end がある (周回は終わっている)"

# 5. 使うコマンドがあるか
command -v claude >/dev/null 2>&1 || unavailable "claude コマンドが見つからない"
command -v python3 >/dev/null 2>&1 || unavailable "python3 が見つからない"

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
log "ワーカーを起動した: 置き場 $LOOP_DIR / モデル $MODEL / effort $EFFORT / 権限モード $PERMISSION_MODE"

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
