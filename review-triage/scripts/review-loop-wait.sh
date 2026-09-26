#!/usr/bin/env bash
# review-loop の作業側が背景で走らせる待機スクリプト。
#
# 使い方:
#   review-loop-wait.sh [--await-worker] <周回の置き場> <識別子> <分> [<停滞の秒数>]
#
# 周回の置き場を 5 秒おきに見て、次のどれかが現れたら標準出力に 1 行を出して終了コード 0 で終わる。
# 同じ周期に複数が当たれば、上にあるものを返す。
#
#   delivered <識別子>   完了の印 delivered-<識別子>.yaml が現れた。status が ok なら依頼文と結果、
#                        failed なら依頼文も揃ったときに返す (揃うまでは次の周期まで待つ)。
#                        status が読めない印は揃うのを待たずに返す (読めないことは作業側の検査が扱う)
#   end                  ファイル end が現れた
#   worker <state>       新しいワーカーの worker.yaml が現れた (起動時には無かった、または pid が起動時と違う)
#   worker <state>       worker.yaml の state が unavailable / expired / left
#   worker invalid       worker.yaml の state が読めない (5 つの状態のどれでもない)
#   worker stale         worker.yaml の更新時刻が <停滞の秒数> (既定 30) より古い。
#                        ワーカーは動いている間は状態に関わらず 5 秒おきに更新時刻を進めるので、
#                        古いことをワーカーのプロセスが居なくなった印と読む。worker.yaml が無い間は判定しない
#
# --await-worker を付けると、起動時の worker.yaml のワーカーは居ないものとして扱い、その状態と停滞を事象にしない
# (新しいワーカーの出現・完了の印・end だけを返す)。作業側が、居なくなったワーカーの起動し直しを待つときに使う。
#
# 終了コード: 0 = 現れた / 124 = 期限切れ / それ以外 = 中断 (引数の誤りを含む。理由は標準エラー)。
# 期限は起動時の date +%s に <分> を足した締切で測り、期限切れを宣言する前にもう 1 度確かめる。
# 一時名 (. で始まる名前) のファイルは見ない — 書く側は一時名に書いてから改名する。
# 置き場の各ファイルの様式の正本は review-triage/skills/review-loop/references/loop-files.md。
#
# macOS の /bin/bash (3.2) と Linux の bash、GNU と BSD の stat で動かす。

set -u

usage() {
  echo "使い方: review-loop-wait.sh [--await-worker] <周回の置き場> <識別子> <分> [<停滞の秒数>]" >&2
  exit 2
}

await_worker=0
if [ "${1:-}" = "--await-worker" ]; then
  await_worker=1
  shift
fi
[ $# -ge 3 ] && [ $# -le 4 ] || usage
dir=$1
rid=$2
minutes=$3
stale_seconds=${4:-30}

[ -d "$dir" ] || { echo "周回の置き場がディレクトリとして存在しない: $dir" >&2; exit 2; }
[ -n "$rid" ] || { echo "識別子が空" >&2; exit 2; }
echo "$minutes" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || { echo "分は 0 以上の数で指定する: $minutes" >&2; exit 2; }
echo "$stale_seconds" | grep -Eq '^[0-9]+$' || { echo "停滞の秒数は 0 以上の整数で指定する: $stale_seconds" >&2; exit 2; }

POLL_SECONDS=5

# ファイルの更新時刻 (エポック秒)。GNU の stat -c が使えなければ BSD の stat -f に切り替える
mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null
}

# YAML のトップレベルの単純なキーの値を読む (前後の空白と引用符を除く)
read_key() {
  sed -n "s/^$2:[[:space:]]*//p" "$1" 2>/dev/null | head -n 1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

marker="$dir/delivered-$rid.yaml"
request="$dir/review-request-$rid.md"
result="$dir/review-$rid.yaml"
worker="$dir/worker.yaml"

worker_existed=0
start_pid=""
if [ -f "$worker" ]; then
  worker_existed=1
  start_pid=$(read_key "$worker" pid)
fi

# 1 回分の確認。現れたものがあれば標準出力に 1 行を出して 0 を返す
check_once() {
  if [ -f "$marker" ]; then
    status=$(read_key "$marker" status)
    case "$status" in
      ok)
        if [ -f "$request" ] && [ -f "$result" ]; then echo "delivered $rid"; return 0; fi ;;
      failed)
        if [ -f "$request" ]; then echo "delivered $rid"; return 0; fi ;;
      *)
        echo "delivered $rid"; return 0 ;;
    esac
  fi
  if [ -e "$dir/end" ]; then
    echo "end"; return 0
  fi
  if [ -f "$worker" ]; then
    state=$(read_key "$worker" state)
    case "$state" in
      idle|reviewing|expired|unavailable|left) ;;
      *) echo "worker invalid"; return 0 ;;
    esac
    if [ "$worker_existed" = 0 ] || [ "$(read_key "$worker" pid)" != "$start_pid" ]; then
      echo "worker $state"; return 0
    fi
    # 起動時のワーカーは居ないものとして待っているので、その状態と停滞は見ない
    [ "$await_worker" = 1 ] && return 1
    case "$state" in
      unavailable|expired|left) echo "worker $state"; return 0 ;;
    esac
    m=$(mtime "$worker")
    if [ -n "$m" ] && [ $(( $(date +%s) - m )) -gt "$stale_seconds" ]; then
      echo "worker stale"; return 0
    fi
  fi
  return 1
}

deadline=$(( $(date +%s) + $(awk -v m="$minutes" 'BEGIN { printf "%d", m * 60 }') ))

while :; do
  check_once && exit 0
  now=$(date +%s)
  if [ "$now" -ge "$deadline" ]; then
    # 期限切れを宣言する前にもう 1 度確かめる
    check_once && exit 0
    exit 124
  fi
  wait_for=$(( deadline - now ))
  [ "$wait_for" -gt "$POLL_SECONDS" ] && wait_for=$POLL_SECONDS
  sleep "$wait_for"
done
