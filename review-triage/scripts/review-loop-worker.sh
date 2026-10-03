#!/bin/bash
# review-loop のワーカー。人間が端末で起動し、周回の置き場に現れた依頼文ごとに、TMPDIR の下に新しく作ったディレクトリ
# (準備のディレクトリ) に複製 (作業側のリポジトリを複製して、依頼の head を取り出したもの) と依頼文の写しを作り、
# 回の作業場所のパスに改名してから、複製の中で claude -p を走らせる。
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
# Claude Code の利用者の設定 (環境変数 CLAUDE_CONFIG_DIR があればその下、無ければ ~/.claude の settings.json) は
# 読むが、使うのは起動時の確認と表示だけ。
#
# macOS でだけ動かす (起動時の確認の 3。サンドボックスの振る舞いを macOS でだけ確かめたため)。
# bash は macOS の /bin/bash (3.2) で動くように書き、1 行目でそれを指定する — PATH で先に見つかる bash (Homebrew の 5.2 など) を
# 使わないため。bash 5.2 は、保留中の trap を $(...) の中身の構文解析の途中で実行することがあり、そのとき trap の文字列は構文の誤りに
# なって実行されない (#105)。テストは CI (ubuntu) でも偽の uname で走らせるので、
# GNU の stat と Linux の /proc でも動くようにしておく。python3 が要る (claude -p と準備のコマンドを専用のプロセスグループで
# 起動する・ログ (stream-json) を読む・プラグインの版を読む・--settings の値と利用者の設定と複製の設定を JSON として検査する・
# --settings の JSON を組み立てる・依頼文の写しを作る・準備のディレクトリを作業場所のパスに改名する・結果を確かめて複写する・
# 作業場所の中を cwd にしているプロセスを見つける・作業場所の中のディレクトリに権限を足す・パスの実体を求めるのに使う)。
# python3 の処理はこのファイルに書かず、処理ごとのファイル (.py) にして、このスクリプトの実体と同じディレクトリの下の
# ディレクトリ review-triage/scripts/review-loop-worker/ に置く。ファイル名は、そのファイルを python3 で実行する関数の名前に
# 合わせる (setpgid_exec.py だけは、関数 run_prep と run_reviewer が共に使う)。各ファイルの説明の正本は、そのファイルの
# 先頭のコメント。ワーカーは起動時にすべてのファイルの中身を変数に読み込み、実行するときは読み込んだ中身を python3 -I -c に
# 渡す (実行中にプラグインが更新されて、ディレクトリの中身が消えても動き続けるため。関数 load_py_files)。
# 読み込めたかは、起動時の確認の 8 で確かめる。
#
# 構成: ワーカーは 2 つのプロセスで動く。人間が起動したプロセス (親。worker.yaml の pid) は、起動時の確認を済ませて、
# 回の処理を行うバックグラウンドのサブシェル (子) を起動したあとは、子が終わるのを待つだけで、コマンド置換を使わない。
# 割り込み (INT / TERM / HUP) は親が受け、割り込みを記録するファイルで子に伝える (関数 relay_interrupt と check_interrupt)。
# bash は、コマンド置換を処理している間に受けたシグナルの trap を実行しないことがあるため。振る舞いと理由の正本は worker.md の「終わり方」。
#
# 不変条件: 作業場所のパスの下では git を実行しない。複製に対する git は、準備のディレクトリの中で、作業場所のパスに
# 改名する前にだけ実行する (作業場所のパスは周回の間使い回すので、前の回のレビュアの実行が残したプロセスも書ける。
# 複製の .git の中身を書き換えられると、git が実行するコマンドがサンドボックスの外で動く)。作業場所は rm -rf だけで消す。

set -u

WORKER_PID=$$
POLL_SECONDS=5              # 依頼文を探す周期と、worker.yaml の更新時刻を進める周期
OTHER_WORKER_FRESH_SECONDS=30  # 起動時の確認で、他のワーカーが動いていると判定する更新時刻の新しさ
STOP_GRACE_SECONDS=5        # レビュアの実行や作業場所に残ったプロセスを TERM で止めてから KILL を送るまでの猶予
RESULT_MAX_BYTES=1048576    # 置き場に複写する結果の大きさの上限 (1 MiB)。正本は worker.md の「回の処理」の手順 10

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

# 改行区切りの列 (標準入力) を、", " で繋いだ 1 行にする (完了の印の error に並べる一覧)
comma_join() {
  tr '\n' ',' | sed -e 's/,$//' -e 's/,/, /g'
}

# そのプロセスグループに、終わっていない (ゾンビでない) プロセスが残っているか
group_alive() {
  ps -A -o pgid=,stat= 2>/dev/null | awk -v g="$1" '$1 == g && $2 !~ /^Z/ { found = 1 } END { exit !found }'
}

# ---- python3 のスクリプト ----

# このスクリプトの実体があるディレクトリ (シンボリックリンクを解決した絶対パス) を標準出力に出す。$1 はこのスクリプトのパス ($0)。
# スクリプト自身がシンボリックリンクなら、リンクを辿った先のディレクトリにする。求められなければ何も出さずに 1 を返す
script_real_dir() {
  local p=$1 link
  while [ -L "$p" ]; do
    link=$(readlink "$p") || return 1
    case "$link" in
      /*) p=$link ;;
      *) p="$(dirname "$p")/$link" ;;
    esac
  done
  real_dir "$(dirname "$p")"
}

# python3 のスクリプトのディレクトリ。プラグインのバージョンを読むとき (review-loop-worker/read_worker_version.py) と同じく、
# このスクリプトの実体パスから決める。環境変数 CLAUDE_PLUGIN_ROOT は、人間が端末で起動するワーカーには設定されないので使わない
PY_DIR=""
if script_dir=$(script_real_dir "$0"); then
  PY_DIR="$script_dir/review-loop-worker"
fi
# ワーカーが python3 で実行するファイルの名前 (.py を除いたもの)。ファイルを足したら、ここにも足す。
# deny_tmp_hook は run_py では実行せず、中身をレビュアの実行のフックのコマンドに埋め込み (build_settings_json)、
# ログを読むとき (read_log_facts) にも渡す
PY_FILES=(
  read_worker_version allow_write_problem settings_arg_problem user_settings_problem webfetch_domains workspace_hash
  build_settings_json stop_cwd_procs make_removable read_log_facts rename_dir clone_settings_problem make_request_copy
  result_file_problem copy_result setpgid_exec deny_tmp_hook
)

# python3 のスクリプトのディレクトリから、PY_FILES のファイルの中身を、名前ごとの変数 PY_SRC_<名前> に読み込む。
# ディレクトリが無いか、ファイルが足りないか読めなければ、理由を PY_PROBLEM に入れる (読み込めれば PY_PROBLEM は空)。
# 読み込んだ中身は関数 run_py で実行する。ファイルを呼ぶたびに開かないのは、周回の間 (何時間も動く) に別のセッションが
# プラグインを更新すると、古いバージョンのディレクトリの中身が消えることがあるため
load_py_files() {
  local n src missing="" unreadable=""
  PY_PROBLEM=""
  if [ -z "$PY_DIR" ]; then
    PY_PROBLEM="このスクリプト ($0) の実体パスを求められないので、python3 のスクリプトのディレクトリが分からない"
    return
  fi
  if [ ! -d "$PY_DIR" ]; then
    PY_PROBLEM="python3 のスクリプトのディレクトリ $PY_DIR が無い"
    return
  fi
  for n in "${PY_FILES[@]}"; do
    if [ ! -f "$PY_DIR/$n.py" ]; then
      missing="${missing:+$missing, }$n.py"
    elif src=$(cat "$PY_DIR/$n.py" 2>/dev/null); then
      printf -v "PY_SRC_$n" '%s' "$src"
    else
      unreadable="${unreadable:+$unreadable, }$n.py"
    fi
  done
  [ -z "$missing" ] || PY_PROBLEM="python3 のスクリプトのディレクトリ $PY_DIR に、ファイル $missing が無い"
  [ -z "$unreadable" ] || PY_PROBLEM="${PY_PROBLEM:+$PY_PROBLEM。}python3 のスクリプトのディレクトリ $PY_DIR の、ファイル $unreadable を読めない"
}

# 読み込んだ python3 のスクリプト ($1 は名前) を、$2 以降を引数にして実行する。python3 は isolated mode (-I) で起動する —
# -c では、Python の import の探索先の先頭がカレントディレクトリになり、ワーカーのカレントディレクトリ (作業側) に json.py のような
# 標準ライブラリと同名のファイルがあると、そちらが読まれるため。標準入力は /dev/null にする (どのスクリプトも標準入力を読まない)
run_py() {
  local var="PY_SRC_$1"
  shift
  python3 -I -c "${!var}" "$@" </dev/null
}

# 起動時の確認より前のバージョンの読み取りと、起動時の確認の 2 の掃除にも読み込んだ中身を使うので、ここで読み込む。
# 読み込めなければ、それらを行わずに、起動時の確認の 8 で止まる
load_py_files

# ---- 起動時の確認に使う道具 (python3 を使う。read_worker_version のほかは、起動時の確認の 8 で python3 とそのスクリプトを確かめた後に呼ぶ) ----

# ワーカーのバージョンを標準出力に出す。$1 はこのスクリプトのパス。説明の正本は review-loop-worker/read_worker_version.py
read_worker_version() {
  run_py read_worker_version "$1"
}

# 起動時の確認の 12 (書き込みを許す場所の検査)。説明の正本は review-loop-worker/allow_write_problem.py
allow_write_problem() {
  run_py allow_write_problem "$@"
}

# 起動時の確認の 13 (追加の引数の --settings の値の検査)。説明の正本は review-loop-worker/settings_arg_problem.py
settings_arg_problem() {
  run_py settings_arg_problem "$1"
}

# 起動時の確認の 14 (利用者の設定の検査)。説明の正本は review-loop-worker/user_settings_problem.py
user_settings_problem() {
  run_py user_settings_problem "$1"
}

# 起動時の確認の 15 (接続を許すホストに加わるドメインの表示)。説明の正本は review-loop-worker/webfetch_domains.py
webfetch_domains() {
  run_py webfetch_domains "$1"
}

# 作業場所の名前に付けるハッシュ。説明の正本は review-loop-worker/workspace_hash.py
workspace_hash() {
  run_py workspace_hash "$1"
}

# レビュアの実行に渡す --settings の JSON を組み立てて標準出力に出す。説明の正本は review-loop-worker/build_settings_json.py
build_settings_json() {
  run_py build_settings_json "$@"
}

# ---- 作業場所と準備のディレクトリの片付けに使う道具 (起動時の確認の 2 と、回の処理の手順 5・10 で使う。python3 を使う) ----

# 作業場所 ($1。実体パス) の中を cwd にしているプロセスを止める。準備のディレクトリにも使う ($2 は出力に書くディレクトリの呼び名。
# 省略すると「作業場所」)。TERM を送ってから KILL を送るまでの猶予は STOP_GRACE_SECONDS 秒。
# 説明の正本は review-loop-worker/stop_cwd_procs.py
stop_cwd_procs() {
  run_py stop_cwd_procs "$1" "$STOP_GRACE_SECONDS" "${2:-作業場所}"
}

# 作業場所 ($1) を rm -rf で消せるように、その中のディレクトリに所有者の権限を足す。説明の正本は review-loop-worker/make_removable.py
make_removable() {
  run_py make_removable "$1"
}

# 作業場所 ($1。実体パス) を消す (回の終わりの処理の 5)。準備のディレクトリにも使う ($2 は出力に書くディレクトリの呼び名。
# 省略すると「作業場所」)。パスがシンボリックリンクでなく、実体が作ったときと同じであることを確かめてから、
# 中のディレクトリに権限を足して rm -rf で消す。git は使わない。消さなかったか消せなければ、パスと理由を標準エラーに出して 1 を返す
remove_workspace() {
  local ws=$1 label=${2:-作業場所} why
  if [ -L "$ws" ]; then
    log "$label $ws がシンボリックリンクに置き換えられているので、消さない (リンクの先も消さない)。次の回の作業場所を作るときに、リンクだけを消す"
    return 1
  fi
  [ -e "$ws" ] || return 0
  if ! why=$(make_removable "$ws"); then
    log "$label $ws を消さない: ${why:-確かめられない}。次の回の作業場所を作るときか、次の起動で消す"
    return 1
  fi
  rm -rf "$ws" 2>/dev/null
  if [ -e "$ws" ] || [ -L "$ws" ]; then
    log "$label $ws を消せない。次の回の作業場所を作るときか、次の起動で消す"
    return 1
  fi
  return 0
}

# ディレクトリ $1 の下に残っている準備のディレクトリ (名前が review-loop-prep-<$2>.<6 文字>。$2 は、周回 id と、周回の置き場の
# 実体パスのハッシュを - で繋いだもの) を片付ける (起動時の確認の 2 と、回の処理の手順 5・割り込み)。準備のディレクトリは
# worker.yaml に記録しないので、名前の形で見つける。シンボリックリンクでないディレクトリだけを、中を cwd にしているプロセスを
# 止めてから消す (作業場所と同じ手順)。それ以外のものは、パスを標準エラーに出して残す
discard_prep_dirs() {
  local d
  for d in "$1/review-loop-prep-$2".??????; do
    if [ -d "$d" ] && [ ! -L "$d" ]; then
      log "準備のディレクトリ $d が残っているので、片付ける"
      stop_cwd_procs "$d" 準備のディレクトリ
      remove_workspace "$d" 準備のディレクトリ
    elif [ -e "$d" ] || [ -L "$d" ]; then
      log "$d は準備のディレクトリの名前の形だが、シンボリックリンクか、ディレクトリでないので、片付けない"
    fi
  done
}

# 起動時の確認の 2 (掃除)。前の起動が残した作業場所と準備のディレクトリの中を cwd にしているプロセスを止め、それらを消す。
# 作業場所として片付けるのは、前の worker.yaml のキー workspace に記録されたパス (無いか空なら、TMPDIR の実体の下の決まったパス)
# だけで、パスの名前が作業場所の名前の形 (review-loop-<周回 id>-<周回の置き場の実体パスのハッシュ>) に合い、シンボリックリンクでない
# ディレクトリのときだけ、止めて消す — worker.yaml に書かれた値だけを根拠に、ワーカーが作ったのではないディレクトリの中の
# プロセスを止めたり、ディレクトリを消したりしないため。準備のディレクトリは worker.yaml に記録しないので、作業場所と同じディレクトリの
# 下から名前の形で見つける (関数 discard_prep_dirs)。プロセスは cwd で見つける (プロセスグループでは見つけられず、名前 (claude) は
# 利用者の対話セッションと同じなので照合しない)。確認ではないので、片付けられなくても止めない (理由とパスを標準エラーに出す)
startup_cleanup() {
  local loop_real key name recorded="" tmp_real target
  if ! command -v python3 >/dev/null 2>&1; then
    log "python3 が見つからないので、前の起動の作業場所を片付けられない"
    return 0
  fi
  if [ -n "$PY_PROBLEM" ]; then
    log "python3 のスクリプトを読み込めていないので、前の起動の作業場所を片付けられない"
    return 0
  fi
  loop_real=$(real_dir "$LOOP_DIR") || return 0
  key="${loop_real##*/}-$(workspace_hash "$loop_real")"
  name="review-loop-$key"
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
  # 準備の途中に消えた起動が残した準備のディレクトリ (その中で準備のコマンドが動き続けていることもある)
  discard_prep_dirs "${target%/*}" "$key"
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
BODY_PID=""            # 子 (回の処理を行うバックグラウンドのサブシェル) の PID。親は起動したときに、子は自分で求める (関数 body_main)
INTERRUPT_FILE=""      # 割り込みを記録するファイル (起動時の確認の 16 で決める)。親が書き、子が確かめる
INTERRUPT_TMP=""       # 割り込みを記録するファイルを書くときの一時名
RELAY_SIG=""           # 親が最初に受けた割り込みのシグナルの名前 (関数 relay_interrupt)
RELAY_CODE=""          # 親が最初に受けた割り込みの終了コード
RELAY_WARNED=""        # 割り込みを記録するファイルを書けなかったことを、標準エラーに知らせたか (関数 write_interrupt_file)
SELF_SIG=""            # 子が自分で最初に受けた TERM・HUP の名前 (プロセスグループに届いたもの。関数 body_main の trap が書く)
WS=""                  # 回の作業場所のパス (起動時の確認が通った後に決める)
WS_KEY=""              # 作業場所と準備のディレクトリの名前に共通する部分 (<周回 id>-<周回の置き場の実体パスのハッシュ>)
# 回のどの部分を行っているか。割り込みを受けたときの扱いを決める (関数 on_signal)。
#   "" = 依頼文を探している / prep = 準備 (手順 2〜8 と、準備のディレクトリの改名) / review = レビュアの実行 (手順 9) /
#   finish = 回の終わりの処理 (手順 10)
PHASE=""

# 回ごとの状態
CURRENT_RID=""
REQ_STARTED=""
REQ_STARTED_EPOCH=0
REQ_DEADLINE=0         # 上限の時刻 (エポック秒)。依頼文を受け取った時刻に --review-timeout-minutes を足したもの
HEAD_BEFORE=""
REQ_BASE=""            # 依頼文の base の値 (無ければ空)。リポジトリの行を表示しただけの結果を見分けるのに使う
REQ_HEAD_FULL=""       # 依頼文の head を作業側で解決した完全な SHA
EFFECTIVE="unknown"
SKILL_CALLED="unknown"
DENIAL_COUNT="unknown"
DENIAL_TOOLS="[]"
EFFECTIVE_MODE="unknown"  # ログから読んだ実効の権限モード
HOOK_DENIAL_COUNT="unknown"  # ログから数えた、ワーカーのフックが拒否した呼び出しの件数 (DENIAL_COUNT には含めない)
SANDBOX_COUNT="unknown"   # ログから数えた、サンドボックスが止めた確認の件数 (リポジトリの行を表示しただけのものを除く)
SANDBOX_CALLS=""          # 完了の印の sandbox_blocked.calls の要素 (YAML の行)。空なら calls は []
SHOWN_COUNT="unknown"     # ログから数えた、リポジトリの行を表示しただけと確かめた呼び出しの件数
SHOWN_CALLS=""            # 完了の印の repo_text_displayed.calls の要素 (YAML の行)。空なら calls は []
MARKER_LINE=""         # 最後に書いた完了の印の、この起動で応じた回の一覧に出す行
PREP_DIR=""            # 回の準備のディレクトリのパス (手順 5 で作り、手順 8 の後に作業場所のパスに改名する)
PREP_OUT=""            # 準備のコマンドの標準出力と標準エラーを書くファイル (準備のディレクトリの中。改名の前に消す)
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
# python3 が無いか、python3 のスクリプトを読み込めていなければ unknown のまま進み、起動時の確認の 8 で止まる
if command -v python3 >/dev/null 2>&1 && [ -z "$PY_PROBLEM" ]; then
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

# 8. 使うコマンドがあり、python3 のスクリプトを読み込めたか (読み込んだのは関数 load_py_files)
command -v claude >/dev/null 2>&1 || unavailable "claude コマンドが見つからない"
PYTHON3=$(command -v python3 2>/dev/null) || unavailable "python3 が見つからない"
[ -z "$PY_PROBLEM" ] || unavailable "$PY_PROBLEM"

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

# 12. 書き込みを許す場所 (--sandbox-allow-write) が、守る場所 (ホーム・作業側・周回の置き場・TMPDIR の実体) と同じでも、
# その祖先でもなく、作業側と周回の置き場の下の場所でもないか。TMPDIR の実体を守るのは、準備のディレクトリ (回の処理の手順 5) を、
# 前の回のレビュアの実行が残したプロセスが書けない場所に作るため。先頭の ~ は引数を読んだときにホームに展開してある
for v in ${SANDBOX_ALLOW_WRITE[@]+"${SANDBOX_ALLOW_WRITE[@]}"}; do
  case "$v" in
    /*) ;;
    *) unavailable "--sandbox-allow-write の値は絶対パスで指定する (先頭の ~ と ~/ はホームに展開する。~ユーザー名 の形は展開しない): $v" ;;
  esac
done
if [ ${#SANDBOX_ALLOW_WRITE[@]} -gt 0 ]; then
  if ! problem=$(allow_write_problem "$HOME_REAL" "$CWD_REAL" "$LOOP_REAL" "$TMP_REAL" "${SANDBOX_ALLOW_WRITE[@]}"); then
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

# 14. 利用者の設定が、コマンドをサンドボックスの外で実行させず、Unix ソケットへの接続を許さないか
# (sandbox.excludedCommands と sandbox.network.allowUnixSockets)。レビュー対象のブランチの設定は、回ごとに複製で確かめる。
# 利用者の設定の置き場は、Claude Code 本体と同じ決め方にする: 環境変数 CLAUDE_CONFIG_DIR があればその下、
# 無ければ $HOME/.claude。CLAUDE_CONFIG_DIR が相対パスだと、レビュアの実行 (複製の中の cwd) からの解決先が
# ワーカーの cwd (作業側) からの解決先と食い違い、ワーカーが実際に使われる設定を確かめられない
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
  case "$CLAUDE_CONFIG_DIR" in
    /*) CONFIG_DIR="$CLAUDE_CONFIG_DIR" ;;
    *) unavailable "環境変数 CLAUDE_CONFIG_DIR が相対パス ($CLAUDE_CONFIG_DIR)。レビュアの実行はこれを自分の cwd (複製) から解決するので、ワーカーが同じファイルを確かめられない。絶対パスにしてから起動し直す" ;;
  esac
else
  CONFIG_DIR="$HOME/.claude"
fi
USER_SETTINGS="$CONFIG_DIR/settings.json"
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
# 作業場所のパスもそのまま実体パスになる (シンボリックリンクに置き換えられていないかを、このパスと比べて確かめる)。
# 準備のディレクトリの名前は review-loop-prep-<WS_KEY>.<mktemp が決める 6 文字> で、作業場所のパスの文字列で始まらない
# (サンドボックスが書き込みの許可をパスの接頭辞で判定しても、作業場所への許可が準備のディレクトリに及ばないように)
ws_hash=$(workspace_hash "$LOOP_REAL") && [ -n "$ws_hash" ] || unavailable "作業場所の名前に付けるハッシュを求められない"
WS_KEY="${LOOP_REAL##*/}-$ws_hash"
WS="$TMP_REAL/review-loop-$WS_KEY"
CLONE="$WS/tree"

# 16. 割り込みを記録するファイル (worker.md の「終わり方」) のパスと、それを書くときの一時名が空いているか。前の起動が残した
# 通常のファイルかシンボリックリンクは消す (シンボリックリンクはリンクだけを消す)。親は割り込みを受けたときにここへ書いて子に伝えるので、
# 消せないもの (ディレクトリなど) があれば止める
INTERRUPT_FILE="$TMP_REAL/review-loop-interrupt-$WS_KEY"
INTERRUPT_TMP="$TMP_REAL/.review-loop-interrupt-$WS_KEY.tmp"
for v in "$INTERRUPT_FILE" "$INTERRUPT_TMP"; do
  if [ -L "$v" ] || [ -f "$v" ]; then rm -f "$v" 2>/dev/null; fi
  if [ -e "$v" ] || [ -L "$v" ]; then
    unavailable "割り込みを記録するファイルのパスに、消せないものがある: $v"
  fi
done

# レビュアの実行に渡す --settings の JSON。値は起動の間変わらないので、ここで 1 度だけ組み立てる。
# フックのコマンドには、起動時の確認の 8 で見つけた python3 のパスと、起動時に読み込んだフックの中身を埋め込む
settings_args=("$WS" "$PYTHON3" "$PY_SRC_deny_tmp_hook")
for v in ${SANDBOX_ALLOW_WRITE[@]+"${SANDBOX_ALLOW_WRITE[@]}"}; do settings_args+=(-w "$v"); done
for v in ${SANDBOX_ALLOWED_DOMAINS[@]+"${SANDBOX_ALLOWED_DOMAINS[@]}"}; do settings_args+=(-d "$v"); done
for v in ${EXTRA_SETTINGS[@]+"${EXTRA_SETTINGS[@]}"}; do settings_args+=(-s "$v"); done
SETTINGS_JSON=$(build_settings_json "${settings_args[@]}") && [ -n "$SETTINGS_JSON" ] \
  || unavailable "レビュアの実行に渡す --settings の JSON を組み立てられない"

# ---- バックグラウンドの処理 ----

# プロセス $1 が動いているか。終わったのに、起動したプロセスが回収していない (ゾンビの) プロセスは動いていないとみなす。
# コマンド ps がシグナルで止まったとき (終了コードが 128 を越える。プロセスグループに届いた TERM・HUP など) は、分からないので
# 動いているとみなす — 動いていないとみなすと、親が動いているのに、子が kill -9 のときの経路 (関数 check_interrupt) で後始末を
# せずに終わる。本当に動いていなければ、次に確かめたときに分かる
pid_alive() {
  local st rc
  st=$(ps -o stat= -p "$1" 2>/dev/null)
  rc=$?
  [ "$rc" -le 128 ] || return 0
  case "$st" in
    ""|Z*) return 1 ;;
  esac
  return 0
}

# 親 (人間が起動したプロセス。worker.yaml の pid) が動いているか
worker_alive() {
  pid_alive "$WORKER_PID"
}

# worker.yaml の更新時刻を 5 秒おきに進める。親が無くなったら (kill -9 で trap が動かなかった場合も) 自分も終わる
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
# 残っていなければ wait しない (正本は worker.md の「終わり方」)。これらの処理は親と子と同じプロセスグループで動くので、
# プロセスグループに届いた HUP ではすぐに (trap が無い)、TERM では自分の trap で、子と同時に終わる (INT は、バックグラウンドの
# コマンドなので無視する)。bash 5 (Linux の 5.2 で確かめた) は、trap を設定したシグナルで wait を途中で抜けるとき、その wait の中で
# 回収した子プロセスの終わりを記録しないことがあるので、準備のコマンドやレビュアの実行を待つ wait が、同時に終わったこれらの処理を
# 回収したまま抜けることがある。終わりを記録しなかった子プロセスを wait すると、ほかの子プロセスがすべて終わるまで戻らない — まだ止めていない
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

# 上限の時刻 ($1。エポック秒) を過ぎたら、子に USR1 を送る。USR1 は、子が待っている wait を途中で戻すための知らせで、
# 上限を越えたかどうかは子が時計で確かめる (関数 timed_out)。過ぎた後は、止められるまで 1 秒おきに送る — 1 度だけだと、
# 子が wait を始める直前に届いた USR1 は wait を戻さず、その wait に上限が掛からない。
# 周期ごとに子が動いているかを確かめ、動いていなければ (kill -9 で trap が動かなかった場合も) 自分も終わる —
# 消えた子の PID が別のプロセスに再利用されていると、USR1 (既定の動作は終了) がそのプロセスを止めてしまうため。
# 親が動いていなければ (kill -9)、子に USR1 を送ってから終わる。子は wait から戻ったときに親が消えたことに気づき、後始末をせずに終わる
# (関数 check_interrupt)
start_watchdog() {
  (
    wd_sleep=""
    trap 'kill "$wd_sleep" 2>/dev/null; exit 0' TERM
    while pid_alive "$BODY_PID"; do
      if ! worker_alive; then
        kill -USR1 "$BODY_PID" 2>/dev/null
        exit 0
      fi
      wd_left=$(( $1 - $(date +%s) ))
      if [ "$wd_left" -le 0 ]; then
        kill -USR1 "$BODY_PID" 2>/dev/null
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

# 割り込みに応じられるように (親が送る USR1 で wait が途中で戻る)、sleep をバックグラウンドで起動して wait で待つ。
# wait が途中で戻ったら sleep を止める — 残すと、割り込みで終わったワーカーの後に、標準出力と標準エラーを開いたまま最大
# POLL_SECONDS 秒残る (端末やテストは、それが閉じるまで待つ)
idle_sleep() {
  sleep "$1" &
  SLEEP_PID=$!
  if ! wait "$SLEEP_PID" 2>/dev/null; then
    kill "$SLEEP_PID" 2>/dev/null
  fi
  SLEEP_PID=""
}

# 子プロセス $1 の終わりを 1 度待つ。終わっていれば終了コードを WAITED_RC に入れて 0 を返す。trap (割り込みや USR1) を実行したために
# wait が途中で戻り、子がまだ在れば 1 を返す (呼び出し元が上限を確かめてから待ち直す)。wait が途中で戻った直後に子が終わった場合も、
# 子の終了コードを受け取り直す (受け取り済みの子を待つと 127 が返るので、そのときは最初の値のままにする)。
# wait から戻るたびに、割り込みの記録と親が動いているかを確かめる (関数 check_interrupt)。割り込みなら、ここから終わることがある
wait_once() {
  local rc
  wait "$1"
  WAITED_RC=$?
  check_interrupt
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

# この周回の準備のディレクトリと作業場所が残っていれば、どちらも片付ける (準備が通らなかった回と、準備の途中の割り込み)
discard_round_dirs() {
  discard_prep_dirs "$TMP_REAL" "$WS_KEY"
  discard_workspace
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

# 割り込み (INT / TERM / HUP) を受けたときの子の処理。$1 はシグナルの名前、$2 は終了コード。子が割り込みを記録するファイルか、
# 自分で受けたシグナルの名前 (変数 SELF_SIG) を見つけたときに呼ぶ (関数 check_interrupt)。受けた時点 (PHASE) で扱いが違う。
#   prep   (準備の途中): 準備のコマンドのプロセスグループを止め、準備のディレクトリと作業場所を消す。印は書かない —
#          レビュアの実行を起動していないので、起動し直したワーカーが同じ依頼文を初めから処理する
#   review (レビュアの実行中): レビュアの実行を止め、回の終わりの処理を行って、failed・interrupted の印を書く
#   finish (回の終わりの処理の途中。上限を越えてレビュアの実行を止めている間に見つけたとき): 何もせずに戻る。割り込みを記録する
#          ファイルも SELF_SIG も残るので、その回の印を書き終えてから、もう一度見つけて終わる (関数 process_request)。
#          印の無い回と、消し残した作業場所を作らないため
# finish のほかは、そのあと worker.yaml を left にして終わる
INTERRUPT_NOTED=0
on_signal() {
  local sig=$1 code=$2
  if [ "$PHASE" = finish ]; then
    if [ "$INTERRUPT_NOTED" = 0 ]; then
      INTERRUPT_NOTED=1
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
      discard_round_dirs
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

# 親が割り込みを記録したか (worker.md の「終わり方」) と、親が動いているかを確かめる。どの時点で呼ぶかの正本は worker.md の
# 「終わり方」の子の箇条。割り込みを記録するファイルか、子が自分で受けた TERM・HUP の名前 (SELF_SIG) があれば、関数 on_signal で扱う。
# 親が動いていなければ (kill -9)、ファイルや SELF_SIG があっても、後始末をせずに終わる (worker.yaml も印も書かない。起動し直した
# ワーカーが片付ける)。親の確認に使う ps がプロセスグループに届いた TERM・HUP で止まったときは、親が動いていないとは判定しない
# (関数 pid_alive)。割り込みかどうかを主にファイルで確かめるのは、bash がコマンド置換を処理している間に受けたシグナルの trap を
# 実行しないことがあるため。親は子が終わるまで 1 秒おきに USR1 を送るので、子が USR1 を受け損ねても、次の USR1 で wait から戻る
check_interrupt() {
  local sig="" code=""
  [ "$FINISHING" = 0 ] || return 0
  if ! worker_alive; then
    FINISHING=1
    log "親 (PID $WORKER_PID) が無いので、後始末をせずに終わる"
    exit 1
  fi
  if [ -f "$INTERRUPT_FILE" ]; then
    read -r sig code <"$INTERRUPT_FILE"
    # 終了コードの形は case で確かめる — grep のような外部コマンドは、プロセスグループに届いた TERM・HUP で止まりうるため
    case "$sig:$code" in
      :*|*:|*:*[!0-9]*) sig="" ;;
    esac
    if [ -z "$sig" ]; then
      log "割り込みを記録するファイル $INTERRUPT_FILE の中身を読めない。割り込みとして扱う"
      sig="名前を読めないシグナル"
      code=1
    fi
  elif [ -n "$SELF_SIG" ]; then
    # プロセスグループに届いた TERM・HUP を子が自分で受け、親がまだファイルを書いていない。親も同じシグナルを受けているが、
    # 子がフォアグラウンドで実行していたコマンドは同じシグナルで止まり、その失敗を準備の失敗として扱う前にここで割り込みにする
    sig=$SELF_SIG
    case "$sig" in
      TERM) code=143 ;;
      HUP) code=129 ;;
    esac
  else
    return 0
  fi
  on_signal "$sig" "$code"
}

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

# ログ (stream-json) から、実効モデル・skill の呼び出し・拒否された呼び出し・実効の権限モード・ワーカーのフックが拒否した呼び出し・
# サンドボックスが止めた確認・リポジトリの行を表示しただけの呼び出しを読んで、1 行に 1 つずつ標準出力に出す。
# 行の並びと説明の正本は review-loop-worker/read_log_facts.py。ワーカーのフックが拒否した呼び出しを見分けるのに、
# 起動時に読み込んだフックの中身を渡す。リポジトリの行を表示しただけの呼び出しを見分けるのに、作業側のパスと依頼文の範囲を渡す
read_log_facts() {
  run_py read_log_facts "$1" "$PY_SRC_deny_tmp_hook" "$CWD_REAL" "$REQ_BASE" "$REQ_HEAD_FULL"
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
    echo "worker_hook_denials: $HOOK_DENIAL_COUNT"
    echo "sandbox_blocked:"
    echo "  count: $SANDBOX_COUNT"
    if [ -n "$SANDBOX_CALLS" ]; then
      echo "  calls:"
      printf '%s' "$SANDBOX_CALLS"
    else
      echo "  calls: []"
    fi
    echo "repo_text_displayed:"
    echo "  count: $SHOWN_COUNT"
    if [ -n "$SHOWN_CALLS" ]; then
      echo "  calls:"
      printf '%s' "$SHOWN_CALLS"
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

# 手順 5。前の回の作業場所と準備のディレクトリが残っていれば、残ったプロセスを止めて消してから、準備のディレクトリを新しく作り、
# そのパスを PREP_DIR に、準備のコマンドの出力を書くファイルのパスを PREP_OUT に入れる。作業場所のパスにシンボリックリンクが
# 残っていれば、リンクだけを消す (リンクの先は消さない)。準備のディレクトリは mktemp -d で作る — 前の回のサンドボックスが
# 書き込みを許したのは作業場所のパスで、新しい名前のディレクトリには書けない。
# 作業場所は、手順 8 の後に準備のディレクトリを作業場所のパスに改名して作る (関数 rename_prep_dir)。
# 作れなければ、完了の印の error に書く文字列を PREP_ERROR に入れて 1 を返す
prepare_workspace() {
  local out
  if [ -e "$WS" ] && [ ! -L "$WS" ]; then
    log "前の回の作業場所 $WS が残っているので、消してから作る"
  fi
  discard_round_dirs
  if [ -e "$WS" ] || [ -L "$WS" ]; then
    PREP_ERROR="workspace failed (the previous workspace remains: $WS)"
    return 1
  fi
  if ! out=$(mktemp -d "$TMP_REAL/review-loop-prep-$WS_KEY.XXXXXX" 2>&1); then
    PREP_ERROR="workspace failed (mktemp: $(last_line "$out"))"
    return 1
  fi
  PREP_DIR=$out
  PREP_OUT="$PREP_DIR/.prep-output"
  if [ -L "$PREP_DIR" ] || [ ! -d "$PREP_DIR" ] || [ ! -O "$PREP_DIR" ] || [ "$(real_dir "$PREP_DIR")" != "$PREP_DIR" ]; then
    PREP_ERROR="workspace failed (not a directory owned by the worker: $PREP_DIR)"
    return 1
  fi
  return 0
}

# ディレクトリ $1 を $2 に改名する (rename(2) をそのまま呼ぶ)。説明の正本は review-loop-worker/rename_dir.py
rename_dir() {
  run_py rename_dir "$1" "$2"
}

# 手順 8 の後。準備のディレクトリ (PREP_DIR) を作業場所のパス (WS) に改名する。作業場所のパスに何かあれば (前の回の
# レビュアの実行が残したプロセスが、手順 5 で消した後に作り直したもの)、シンボリックリンクを辿らずに失敗する —
# rename(2) は、移す先が空でないディレクトリなら ENOTEMPTY で、ディレクトリでないもの (シンボリックリンクを含む) なら
# ENOTDIR で失敗し、空のディレクトリなら置き換える。mv は移す先がディレクトリへのシンボリックリンクなら、その先の中に移すので使わない。
# 改名できなければ、完了の印の error に書く文字列を PREP_ERROR に入れて 1 を返す
rename_prep_dir() {
  local out
  if out=$(rename_dir "$PREP_DIR" "$WS"); then
    PREP_DIR=""
    return 0
  fi
  PREP_ERROR="workspace failed (rename to $WS: ${out:-理由が分からない})"
  return 1
}

# 手順 6 の段の失敗を、完了の印の error に書く文字列にする。$1 は段の名前、$2 は git の出力
clone_failed() {
  local detail
  detail=$(last_line "$2")
  echo "clone failed ($1${detail:+: $detail})"
}

# 準備のコマンド ($2 以降) を、準備のディレクトリを cwd にして、専用のプロセスグループでバックグラウンドに起動して待つ ($1 は出力に書く段の名前)。
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
  # 読み込んだ setpgid_exec.py の中身を、関数 run_py と同じく python3 -I -c で実行する (-I の理由は関数 run_py)
  (
    cd "$PREP_DIR" || exit 127
    exec python3 -I -c "$PY_SRC_setpgid_exec" "$@"
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

# 手順 6。作業側のリポジトリを準備のディレクトリの tree/ (改名の後は作業場所の tree/) に複製し、依頼の head ($1。作業側で解決した
# 完全な SHA) を detached HEAD で取り出す。
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
  subs=$(grep '^160000 ' "$PREP_OUT" | cut -f2 | comma_join)
  if [ -n "$subs" ]; then
    PREP_ERROR="clone failed (submodule: $subs)"
    return 1
  fi
  return 0
}

# 手順 7。複製 ($1) の設定を確かめる。説明の正本は review-loop-worker/clone_settings_problem.py
clone_settings_problem() {
  run_py clone_settings_problem "$1"
}

# 手順 8。作業側の依頼文 ($1) の写しを、準備のディレクトリの $2 に作る。写しの作り方 (置き換える文字列と、失敗とする条件) の
# 正本は review-loop-worker/make_request_copy.py。写しを作る python3 は準備のコマンドとして起動する (関数 run_prep)。
# 読み込んだ中身を、関数 run_py と同じく python3 -I -c で実行する。
# 通らなければ 1 を返し、上限を越えたためでなければ、完了の印の error に書く文字列を PREP_ERROR に入れる
make_request_copy() {
  local out
  run_prep "request copy" python3 -I -c "$PY_SRC_make_request_copy" "$1" "$2" "$CURRENT_RID" "$LOOP_REAL" "$CWD_REAL" "$WS" "$CLONE" \
    && return 0
  [ "$PREP_TIMEOUT" = 1 ] && return 1
  out=$(last_line "$(cat "$PREP_OUT" 2>/dev/null)")
  case "$out" in
    "request copy failed ("*) PREP_ERROR=$out ;;
    *) PREP_ERROR="request copy failed (${out:-理由が分からない})" ;;
  esac
  return 1
}

# 作業場所の結果 ($1) を確かめる (「回の処理」の表の「結果のファイル」)。大きさの上限は RESULT_MAX_BYTES。
# 説明の正本は review-loop-worker/result_file_problem.py
result_file_problem() {
  run_py result_file_problem "$1" "$WS" "$RESULT_MAX_BYTES"
}

# 手順 10 の 4。作業場所の結果 ($1) を、置き場の出力先 ($2) に複写する。大きさの上限は RESULT_MAX_BYTES。
# 説明の正本は review-loop-worker/copy_result.py
copy_result() {
  run_py copy_result "$1" "$2" "$RESULT_MAX_BYTES"
}

# ---- 回の処理の流れ (手順 2〜10) ----

# レビュアの実行を起動しなかった回の印 (依頼文・HEAD・作業ツリーの確認か、作業場所を作れない)。上限の計測を止めてから書く。
# ログから読む項目 (実効モデル・実効の権限モード・サンドボックスが止めた件数など) は、関数 process_request が回の初めに入れた
# unknown のまま書く。書く前に割り込みを確かめる — 準備の途中に受けた割り込みなら、印を書かずに終わる (関数 on_signal)
fail_without_run() {
  check_interrupt
  stop_watchdog
  write_marker failed "$1" 0
  note_served "$MARKER_LINE"
  CURRENT_RID=""
  PHASE=""
  write_worker_yaml idle ""
}

# 準備 (手順 5〜8 と、その後の改名) が通らなかった回。準備のディレクトリと作業場所があれば、回の終わりの処理の 1 と 5 の手順で
# 片付けてから、レビュアの実行を起動せずに failed の印を書く
fail_prepared() {
  discard_round_dirs
  PREP_DIR=""
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
  local fact fact_no=0 call_command="" call_yaml

  # 1. 作業場所の中を cwd にしているプロセスが残っていれば止める (後始末の途中で作業場所に書かれないように)。
  # レビュアの実行の終了コード (REVIEWER_RC) は変えない
  stop_cwd_procs "$WS"

  # 2. ログを読む。行の並びは review-loop-worker/read_log_facts.py の先頭のコメントのとおり。9 行目からは、
  # 呼び出しごとのコマンドと文面の 2 行で、先頭から SANDBOX_COUNT 件を完了の印の sandbox_blocked.calls の要素の YAML に、
  # 残りを repo_text_displayed.calls の要素の YAML にする (値は yaml_str で二重引用符の文字列にする)
  facts=$(read_log_facts "$LOOP_DIR/$CURRENT_RID.log")
  SANDBOX_CALLS=""
  SHOWN_CALLS=""
  while IFS= read -r fact; do
    fact_no=$(( fact_no + 1 ))
    case $fact_no in
      1) EFFECTIVE=$fact ;;
      2) SKILL_CALLED=$fact ;;
      3) DENIAL_COUNT=$fact ;;
      4) DENIAL_TOOLS=$fact ;;
      5) EFFECTIVE_MODE=$fact ;;
      6) HOOK_DENIAL_COUNT=$fact ;;
      7) SANDBOX_COUNT=$fact ;;
      8) SHOWN_COUNT=$fact ;;
      *)
        if [ $(( fact_no % 2 )) -eq 1 ]; then
          call_command=$fact
        else
          call_yaml="    - command: $(yaml_str "$call_command")
      message: $(yaml_str "$fact")
"
          # 呼び出しの番号 (0 から) が SANDBOX_COUNT より小さければ、サンドボックスが止めた確認
          if [ $(( (fact_no - 10) / 2 )) -lt "$SANDBOX_COUNT" ]; then
            SANDBOX_CALLS="$SANDBOX_CALLS$call_yaml"
          else
            SHOWN_CALLS="$SHOWN_CALLS$call_yaml"
          fi
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
  [ -n "$HOOK_DENIAL_COUNT" ] || HOOK_DENIAL_COUNT=unknown
  [ -n "$SANDBOX_COUNT" ] || SANDBOX_COUNT=unknown
  [ -n "$SHOWN_COUNT" ] || SHOWN_COUNT=unknown

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
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | comma_join)
  if [ -z "$dirty" ]; then clean_after=true; else clean_after=false; errors+=("tree not clean ($dirty)"); fi

  # 置き場。依頼文を受け取ったときに控えた一覧と比べる (結果の複写より前に比べる)
  after=$(snapshot)
  changed=$( { echo "$SNAPSHOT_BEFORE"; echo "$after"; } | sed '/^$/d' | LC_ALL=C sort | uniq -u | sed 's/ [^ ]*$//' | LC_ALL=C sort -u | comma_join)
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
# 子は、サブシェルを待つ間は割り込みを記録するファイルを確かめず、印を書き終えてから確かめる (関数 process_request)。
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

  # --setting-sources user,project: 複製の .claude/settings.local.json (ローカルの設定) を読ませない。複製はコミットから作るので
  # ふつうは無いが、前の回のレビュアの実行が残したプロセスは、改名の後に作れる (フックはサンドボックスの外で動く)。
  # setpgid_exec.py は、関数 run_prep と同じく、読み込んだ中身を python3 -I -c で実行する
  (
    cd "$CLONE" || exit 127
    exec python3 -I -c "$PY_SRC_setpgid_exec" \
      claude -p "$prompt" \
      --model "$MODEL" --effort "$EFFORT" --permission-mode "$PERMISSION_MODE" \
      --settings "$SETTINGS_JSON" --setting-sources user,project --strict-mcp-config \
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
  REQ_BASE=""
  REQ_HEAD_FULL=""
  # ログから読む項目。レビュアの実行を起動しなかった回の印には、この unknown のまま書く
  EFFECTIVE="unknown"
  SKILL_CALLED="unknown"
  DENIAL_COUNT="unknown"
  DENIAL_TOOLS="[]"
  EFFECTIVE_MODE="unknown"
  HOOK_DENIAL_COUNT="unknown"
  SANDBOX_COUNT="unknown"
  SANDBOX_CALLS=""
  SHOWN_COUNT="unknown"
  SHOWN_CALLS=""
  REVIEWER_RC=""
  PREP_TIMEOUT=0
  PREP_ERROR=""
  PREP_DIR=""
  PREP_OUT=""
  # 手順 2。上限の計測を始め、worker.yaml を reviewing にして識別子と作業場所のパスを書き、置き場のファイルの一覧と更新時刻を
  # 控える (回の終わりの処理で比べる。準備の途中に現れた end も検出するため、ここで控える)
  start_watchdog "$REQ_DEADLINE"
  write_worker_yaml reviewing "$CURRENT_RID"
  log "依頼文を見つけた: $CURRENT_RID"
  SNAPSHOT_BEFORE=$(snapshot)

  local req="$LOOP_DIR/review-request-$CURRENT_RID.md"
  local copy_name="review-request-$CURRENT_RID.md"
  local logf="$LOOP_DIR/$CURRENT_RID.log"
  HEAD_BEFORE=$(git -C "$CWD_REAL" rev-parse --short HEAD 2>/dev/null)

  # 手順 3。依頼文を確かめる
  if grep -q '{{' "$req"; then fail_without_run "request malformed (unfilled placeholder)"; return; fi
  if ! grep -q '^## 出力様式' "$req"; then fail_without_run "request malformed (no output format section)"; return; fi
  local req_head
  req_head=$(sed -n 's/^head:[[:space:]]*"\([0-9a-f][0-9a-f]*\)"[[:space:]]*$/\1/p' "$req" | head -n 1)
  if [ -z "$req_head" ]; then fail_without_run "request malformed (no head line)"; return; fi
  # base は形を確かめずに控える (ログを読むときに確かめる。無くても、形に合わなくても、回は止めない)
  REQ_BASE=$(sed -n 's/^base:[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$req" | head -n 1)

  # 手順 4。作業側の HEAD と作業ツリーを確かめる
  if timed_out; then fail_timeout_in_preparation; return; fi
  local full_req full_head dirty
  full_req=$(git -C "$CWD_REAL" rev-parse --verify -q "$req_head^{commit}" 2>/dev/null)
  full_head=$(git -C "$CWD_REAL" rev-parse HEAD 2>/dev/null)
  if [ -z "$full_req" ] || [ "$full_req" != "$full_head" ]; then
    fail_without_run "head mismatch (expected $req_head, actual $HEAD_BEFORE)"; return
  fi
  REQ_HEAD_FULL=$full_req
  dirty=$(git -C "$CWD_REAL" status --porcelain 2>/dev/null | cut -c4- | comma_join)
  if [ -n "$dirty" ]; then fail_without_run "tree not clean ($dirty)"; return; fi

  # 手順 5〜8。準備のどれかが通らなければ、レビュアの実行を起動しない。上限を越えたかは、各段の前に確かめる
  # (手順 6 の各段と手順 8 では、関数 run_prep が起動する前と待つ間に確かめる)。手順 6〜8 は準備のディレクトリの中で行う
  local problem
  if timed_out; then fail_timeout_in_preparation; return; fi
  if ! prepare_workspace; then
    # 準備のディレクトリを作る前に通らなければ、片付けるものは無い (作業場所は prepare_workspace が片付けようとした)
    if [ -n "$PREP_DIR" ]; then fail_prepared "$PREP_ERROR"; else fail_without_run "$PREP_ERROR"; fi
    return
  fi
  if ! make_clone "$full_req"; then
    fail_preparation_stage "clone failed (理由が分からない)"; return
  fi
  if timed_out; then fail_timeout_in_preparation; return; fi
  if ! problem=$(clone_settings_problem "$PREP_DIR/tree"); then
    [ -n "$problem" ] || problem="clone settings (python3 が理由を出さずに終わった)"
    fail_prepared "$(join_lines "$problem")"; return
  fi
  if ! make_request_copy "$req" "$PREP_DIR/$copy_name"; then
    fail_preparation_stage "request copy failed (理由が分からない)"; return
  fi
  rm -f "$PREP_OUT"
  PREP_OUT=""

  # 準備のディレクトリを作業場所のパスに改名する。改名の後は、作業場所のパスの下で git を実行せず、準備の出力も読まない
  if ! rename_prep_dir; then fail_prepared "$PREP_ERROR"; return; fi

  # 手順 9。準備の途中に割り込みを受けていれば、レビュアの実行を起動せずに終わる (関数 on_signal)。
  # 準備の段の合間に上限を越えていれば、レビュアの実行を起動しない
  check_interrupt
  if timed_out; then fail_timeout_in_preparation; return; fi
  log "レビュアの実行を起動する: claude -p --model $MODEL --effort $EFFORT --permission-mode $PERMISSION_MODE (cwd: ${CLONE}、上限 $REVIEW_TIMEOUT_MINUTES 分)"
  run_reviewer "$WS/$copy_name" "$logf"
  # 印を書き終えた。回の終わりの処理の途中に受けた割り込みは、ここで見つけて終わる
  CURRENT_RID=""
  PHASE=""
  check_interrupt
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

# ---- 子 (回の処理を行うプロセス。正本は worker.md の「終わり方」) ----

# 子の本体。worker.yaml を idle で書き、更新時刻を進める処理を始め、依頼文を探して回の処理を行う。親 (関数 supervise_body) が
# バックグラウンドのサブシェルとして起動する
body_main() {
  # trap は子が最初に設定する。設定する前に USR1 (親が割り込みを伝えるときに送る) や、プロセスグループに届いた TERM・HUP を受けると、
  # デフォルトの動作で子が終わり、worker.yaml を left にしないまま終わるため。
  # SIGINT は無視する (端末の Ctrl-C は親だけが受ける)。子は ( ) & で起動したバックグラウンドのサブシェルなので、無視した状態で
  # 始まるが、bash の版や起動の仕方によっては無視にならない (bash 5.2 は、INT の trap を設定した親が関数を & で起動すると、
  # 子の SIGINT をデフォルトの動作にする) ので、ここで明示する。
  # 親が送る USR1 は、待っている wait を途中で戻すためだけに使い、割り込みかどうかは割り込みを記録するファイルで確かめる
  # (関数 check_interrupt)。プロセスグループに届いた TERM・HUP は、wait を戻すほかに、受けたシグナルの名前を SELF_SIG に書く —
  # 子がフォアグラウンドで実行しているコマンドも同じシグナルで止まり、親がファイルを書くより先に、子がその失敗を準備の失敗として
  # 扱うことがあるため (SELF_SIG に名前があれば、関数 check_interrupt が割り込みにする)。TERM と HUP は無視にしない — 無視は子が起動する
  # コマンドに引き継がれ、準備のコマンドやレビュアの実行が TERM で止まらなくなる
  trap '' INT
  trap '[ -n "$SELF_SIG" ] || SELF_SIG=TERM' TERM
  trap '[ -n "$SELF_SIG" ] || SELF_SIG=HUP' HUP
  trap ':' USR1
  trap 'cleanup' EXIT
  local idle_since now wait_for rid
  # 子の PID (上限を測る処理が USR1 を送る先)。サブシェルの中の $$ は親の PID のままで、bash 3.2 には変数 BASHPID が無いので、
  # sh を exec したコマンド置換の、親のプロセス (この子) の PID として求める
  BODY_PID=$(exec sh -c 'echo $PPID')

  write_worker_yaml idle ""
  start_heartbeat
  log "ワーカーを起動した: 版 $WORKER_VERSION / 置き場 $LOOP_DIR / モデル $MODEL / effort $EFFORT / 権限モード $PERMISSION_MODE"

  idle_since=$(date +%s)
  while :; do
    check_interrupt
    if [ -e "$LOOP_DIR/end" ]; then
      FINISHING=1
      trap '' INT TERM HUP
      # 周回の作業場所と準備のディレクトリが残っていれば消す (消せなかった回の作業場所など)
      discard_round_dirs
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
}

# ---- 親 (シグナルを受け取るプロセス。正本は worker.md の「終わり方」) ----
#
# 親は、下で trap を設定した後、コマンド置換を使わない (関数 relay_interrupt・write_interrupt_file・supervise_body)。bash は、
# コマンド置換を処理している間に受けたシグナルの trap を実行しないことがあるため (経緯は https://github.com/akm/claude-plugins/issues/105)。
# テスト review-triage/tests/test_review_loop_worker.py が、親の trap を設定した後の行から呼ぶ関数をたどり、その本文にコマンド置換が
# 無いことを確かめる

# 割り込みを受けたときの親の処理。最初に受けた 1 回だけ、シグナルの名前と終了コードを覚えて、割り込みを記録するファイルに書く。
# 子への USR1 と、書けなかったときの書き直しは、関数 supervise_body が行う
relay_interrupt() {
  [ -z "$RELAY_SIG" ] || return 0
  RELAY_SIG=$1
  RELAY_CODE=$2
  write_interrupt_file
}

# 親が最初に受けた割り込みのシグナルの名前と終了コードを、割り込みを記録するファイルに書く (一時名に書いてから改名する。子が
# 書きかけを読まないため)。INT・TERM・HUP を無視するサブシェル (コマンド置換ではない) の中で書く — 親の trap は外部コマンド mv に
# 引き継がれないので、親が続けて受けたシグナル (Ctrl-C を続けて押したときなど) のデフォルトの動作で mv が止まり、書けなくなるため
# (無視は mv に引き継がれる)。書けなかったとき (サブシェルが無視を設定する前にシグナルが届いた場合を含む) は 1 を返し、最初の
# 1 回だけ標準エラーに知らせる
write_interrupt_file() {
  ( trap '' INT TERM HUP; printf '%s %s\n' "$RELAY_SIG" "$RELAY_CODE" >"$INTERRUPT_TMP" && mv -f "$INTERRUPT_TMP" "$INTERRUPT_FILE" ) \
    && return 0
  if [ -z "$RELAY_WARNED" ]; then
    RELAY_WARNED=1
    echo "review-loop-worker: 割り込みを記録するファイル $INTERRUPT_FILE を書けない。子 (PID $BODY_PID) が終わるまで、1 秒おきに書き直す。" >&2
    echo "  止まらなければ kill -KILL $WORKER_PID を送る (子は親が無いことに気づいて、後始末をせずに終わる)" >&2
  fi
  return 1
}

# 子を起動し、終わるまで待つ。割り込みを受けていれば、子が終わるまで 1 秒おきに子へ USR1 を送る (子が USR1 を受け損ねても、
# 次の USR1 で wait から戻るように)。送る前に、割り込みを記録するファイルが無ければ (書けなかったとき) 書き直す。子が終わったら
# 割り込みを記録するファイルを消し、割り込みを受けていればそのシグナルの終了コードで、受けていなければ子の終了コードで終わる
supervise_body() {
  local rc=""
  ( body_main ) &
  BODY_PID=$!
  while kill -0 "$BODY_PID" 2>/dev/null; do
    if [ -z "$RELAY_SIG" ]; then
      wait "$BODY_PID"
      rc=$?
    else
      [ -f "$INTERRUPT_FILE" ] || write_interrupt_file
      kill -USR1 "$BODY_PID" 2>/dev/null
      sleep 1 </dev/null >/dev/null 2>&1 &
      wait "$!"
    fi
  done
  # 子が、上の wait を始める前に終わっていれば、ここで終了コードを受け取る
  if [ -z "$rc" ]; then
    wait "$BODY_PID"
    rc=$?
  fi
  rm -f "$INTERRUPT_FILE" "$INTERRUPT_TMP"
  [ -z "$RELAY_SIG" ] || rc=$RELAY_CODE
  exit "$rc"
}

trap 'relay_interrupt INT 130' INT
trap 'relay_interrupt TERM 143' TERM
trap 'relay_interrupt HUP 129' HUP
supervise_body
