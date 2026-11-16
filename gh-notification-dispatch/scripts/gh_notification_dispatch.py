#!/usr/bin/env python3
"""gh-notification-dispatch のスクリプトの入口。サブコマンドごとにパッケージ gh_notification_dispatch のモジュールの関数を実行する。

出力は標準出力の JSON 1 つ。サブコマンドごとの引数・出力の JSON のキー・終了コードは、`<サブコマンド> --help` が SSOT。
スキルの SKILL.md は引数を書かずに `--help` を参照する。記録のファイルの様式は文書 references/records.md、メッセージの様式は
文書 references/messages.md にある (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の KTD3・KTD8)。

サブコマンドの一覧:
  dispatcher set --name <名前> --permission-mode <モード> [--switch]   配信のセッションを記録する
  subscriptions request --name <名前> --permission-mode <モード> [--repo <owner/repo>] [--kind <種類>]   受信のセッションが、登録の申し込みの本文を作る
  subscriptions add --message-file <ファイル> --sender <ID>   配信のセッションが、登録の申し込みを記録する
  subscriptions list --viewer <ID> [--mine]      登録の一覧を、番号を振って表示する
  subscriptions remove --viewer <ID> <番号>...   配信のセッションが、一覧の番号の登録を削除する
  subscriptions resolve --viewer <ID> --name <名前> <番号>...   受信のセッションが、一覧の番号から削除の申し込みの本文を作る
  subscriptions unsubscribe --message-file <ファイル> --sender <ID>   配信のセッションが、削除の申し込みの登録を削除する
  subscriptions rename --session-id <ID> --name <名前>   配信のセッションが、受信のセッションの名前を引き直した値に変える
  tick                                           通知を取得して出来事を判定し、この回に送るメッセージを出力する
  ack <メッセージの ID>                          tick が出力したメッセージが届いたことを記録する
  fail <メッセージの ID> --reason <理由>         tick が出力したメッセージが届かなかったことを記録する
  settle                                         この回のメッセージの結果を集計し、続けて届かなかった回数を更新する

終了コード (計画の KTD11):
  0  続ける
  3  出力の `errors` を利用者に示して判断を求める (申し込みの形が違う・リポジトリを読めない・配信のセッションでないなど)
  4  gh が失敗した。出力の `gh_error` に、失敗した呼び出しを示して中断する
1 と 2 は Python 自身が使う (捕まえていない例外の 1・引数の誤りの 2)。スキルはこの 2 つをスクリプトの不具合として扱い、
中断する。例外を捕まえて 3 や 4 にすることはしない。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gh_notification_dispatch import gh, messages, outbox, poll, subscriptions  # noqa: E402

EXIT_OK = 0
EXIT_UNSATISFIED = 3
EXIT_EXTERNAL_FAILED = 4

_EXIT_CODES_HELP = """終了コード:
  0  {ok}
  3  {unsatisfied}
  4  {failed}
  1 と 2 は Python 自身の失敗 (例外と引数の誤り)。スクリプトの不具合として扱う"""

_NO_GH = "使わない (gh を実行しない)"
_NOT_DISPATCHER = "このセッションが記録の配信のセッションでない (配信のセッションが記録されていないときも)"


def _exit_help(ok, unsatisfied, failed=_NO_GH):
    return _EXIT_CODES_HELP.format(ok=ok, unsatisfied=unsatisfied, failed=failed)


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _emit_status(result):
    status = result.pop("status")
    if status == "gh_failed":
        result["gh_error"] = gh.describe_failure(result["gh_error"])
        _emit(result)
        return EXIT_EXTERNAL_FAILED
    _emit(result)
    return EXIT_OK if status == "ok" else EXIT_UNSATISFIED


def _read_message(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_dispatcher_set(args):
    return _emit_status(subscriptions.set_dispatcher(args.name, args.permission_mode, switch=args.switch))


def cmd_subscriptions_request(args):
    return _emit_status(subscriptions.request(args.name, args.permission_mode, repo=args.repo, kinds=args.kind))


def cmd_subscriptions_add(args):
    return _emit_status(subscriptions.add(_read_message(args.message_file), args.sender))


def cmd_subscriptions_list(args):
    return _emit_status(subscriptions.list_subscriptions(args.viewer, mine=args.mine))


def cmd_subscriptions_remove(args):
    return _emit_status(subscriptions.remove(args.viewer, args.numbers))


def cmd_subscriptions_resolve(args):
    return _emit_status(subscriptions.resolve(args.viewer, args.numbers, args.name))


def cmd_subscriptions_unsubscribe(args):
    return _emit_status(subscriptions.unsubscribe(_read_message(args.message_file), args.sender))


def cmd_subscriptions_rename(args):
    return _emit_status(subscriptions.rename(args.session_id, args.name))


def cmd_tick(args):
    return _emit_status(poll.tick())


def cmd_ack(args):
    return _emit_status(outbox.record(args.message_id, "ack"))


def cmd_fail(args):
    return _emit_status(outbox.record(args.message_id, "fail", args.reason))


def cmd_settle(args):
    return _emit_status(outbox.settle())


# --- 引数 ---------------------------------------------------------------------------------------------------------

def _add(sub, name, func, description, output, exit_help):
    parser = sub.add_parser(name, help=description.splitlines()[0], description=description,
                            epilog=f"出力 (標準出力の JSON):\n{output}\n\n{exit_help}",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.set_defaults(func=func)
    return parser


def _positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("番号は 1 以上")
    return value


_MESSAGE_ARGS_HELP = {
    "message_file": "受け取ったメッセージの本文 (要素 cross-session-message の中身) を書いたファイル",
    "sender": "受け取ったメッセージの送り手の ID (要素 cross-session-message の属性 from-session。無ければ from)",
}
_SUBSCRIPTION_ROW = "{id, repo, kind, session_id, session_name, permission_mode, created_at}"


def build_parser():
    parser = argparse.ArgumentParser(prog="gh_notification_dispatch.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    groups = parser.add_subparsers(dest="group", required=True)

    g = groups.add_parser("dispatcher", help="配信のセッションを記録する").add_subparsers(dest="command", required=True)
    p = _add(g, "set", cmd_dispatcher_set,
             "配信のセッションを、記録のディレクトリの state.json に記録する。gh は実行しない。\n"
             "セッションの ID は、引数で受けずに環境変数 CLAUDE_CODE_HOST_SESSION_ID から読む。\n"
             "記録と同じ ID なら、名前と権限モードを書き換える。記録と違う ID なら、--switch を付けたときだけ書き換える",
             "  dispatcher  記録した配信のセッション {session_id, name, permission_mode, recorded_at}。\n"
             "              記録と違う ID で --switch が無いときは、記録の配信のセッション (書き換えない)\n"
             "  previous    切り替えたときの、前の配信のセッション。切り替えていなければ null\n"
             "  switched    切り替えたか\n"
             "  errors      記録しなかった理由の配列",
             _exit_help("記録した", "記録と違うセッションで --switch が無い・環境変数が無い・名前か権限モードの形が違う"))
    p.add_argument("--name", required=True, help="このセッションの名前 (サイドバーのタイトル)")
    p.add_argument("--permission-mode", required=True, help="このセッションの権限モード (" + "・".join(messages.PERMISSION_MODES) + ")")
    p.add_argument("--switch", action="store_true", help="記録の配信のセッションを、このセッションに切り替える")

    g = groups.add_parser("subscriptions", help="登録を申し込む・記録する・一覧にする・削除する").add_subparsers(
        dest="command", required=True)
    p = _add(g, "request", cmd_subscriptions_request,
             "受信のセッションが、登録の申し込み (type: subscribe) の本文を作る。記録のディレクトリには書かない。\n"
             "セッションの ID は、環境変数 CLAUDE_CODE_HOST_SESSION_ID から読む。\n"
             "--repo を省くと、作業ディレクトリのリポジトリ (gh repo view) にする。--kind を省くと、2 つの種類にする",
             "  repo          申し込むリポジトリ (owner/repo)\n"
             "  kinds         申し込む種類の配列\n"
             "  session_id    このセッションの ID\n"
             "  dispatcher    記録の配信のセッション {session_id, name, permission_mode, recorded_at}。記録が無ければ null\n"
             "  message_body  配信のセッションへ送る本文\n"
             "  errors        本文を作らなかった理由の配列\n"
             "  gh_error      gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("本文を作った", "環境変数が無い・引数の形が違う",
                        "--repo を省いて、gh repo view が失敗した (作業ディレクトリが git のリポジトリでないなど)"))
    p.add_argument("--name", required=True, help="このセッションの名前 (サイドバーのタイトル)")
    p.add_argument("--permission-mode", required=True, help="このセッションの権限モード (" + "・".join(messages.PERMISSION_MODES) + ")")
    p.add_argument("--repo", help="リポジトリ (owner/repo)")
    p.add_argument("--kind", help="種類のカンマ区切り (" + "・".join(messages.KINDS) + ")")

    p = _add(g, "add", cmd_subscriptions_add,
             "配信のセッションが、登録の申し込み (type: subscribe) を記録し、返事 (type: subscribed) の本文を返す。\n"
             "本文の session-id が --sender と違う申し込みは受け付けない。リポジトリを gh api repos/<owner>/<repo> で読み、\n"
             "API が返した正式な名前で記録する。(リポジトリ, 種類, セッション) が同じ登録は増やさず、登録済みとして返す。\n"
             "受け付けなかったときも、返事の本文を返す",
             "  result      accepted (受け付けた)・rejected (受け付けなかった)\n"
             "  repo        リポジトリ (受け付けたときは API が返した正式な名前)。分からなければ null\n"
             f"  added       新しく記録した登録 {_SUBSCRIPTION_ROW} の配列\n"
             "  existing    既に記録してあった登録の配列 (名前と権限モードを申し込みの値に変えた)\n"
             "  warning     権限モードの分類が違うときの説明。同じなら null\n"
             "  reply_body  送り手へ送る返事の本文\n"
             "  errors      受け付けなかった理由の配列\n"
             "  gh_error    gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("受け付けた", "申し込みの形が違う・送り手が本文と違う・リポジトリを読めない (404)・" + _NOT_DISPATCHER,
                        "gh が失敗した (認証切れ・ネットワークなど)"))
    p.add_argument("--message-file", required=True, help=_MESSAGE_ARGS_HELP["message_file"])
    p.add_argument("--sender", required=True, help=_MESSAGE_ARGS_HELP["sender"])

    p = _add(g, "list", cmd_subscriptions_list,
             "登録の一覧を、登録日時の順に 1 から番号を振って返し、番号と登録の ID の対応を記録する。gh は実行しない。\n"
             "--viewer が記録の配信のセッションなら、対応を記録のディレクトリの snapshots/<ID>.json に書く。\n"
             "それ以外 (受信のセッション) なら、${TMPDIR:-/tmp}/gh-notification-dispatch/<ID>/snapshot.json に書き、\n"
             "記録のディレクトリは変えない",
             "  viewer         --viewer の値\n"
             "  mine           --mine を付けたか\n"
             "  listed_at      一覧を表示した時刻\n"
             "  snapshot       番号の対応を書いたファイルのパス\n"
             f"  subscriptions  {{number, {_SUBSCRIPTION_ROW[1:]} の配列 (番号の順)\n"
             "  table          利用者に示す Markdown の表 (番号・リポジトリ・種類・登録日時・届け先のセッション)\n"
             "  errors         一覧にしなかった理由の配列",
             _exit_help("一覧にした", "--viewer の形が違う・--viewer が記録の配信のセッションの ID なのに、"
                        "このセッションが記録の配信のセッションでない"))
    p.add_argument("--viewer", required=True, help="一覧を表示するセッションの ID")
    p.add_argument("--mine", action="store_true", help="--viewer のセッションの登録だけを一覧にする")

    p = _add(g, "remove", cmd_subscriptions_remove,
             "配信のセッションが、snapshots/<ID>.json に記録した対応で、一覧の番号の登録を削除する。gh は実行しない。\n"
             "1 つでも指定できない番号 (一覧に無い・登録が既に無い) があれば、何も削除しない。\n"
             "別のセッションの登録を削除したら、そのセッションへ送る通知 (type: removed) の本文を返す",
             "  removed   削除した登録 {number, ...} の配列\n"
             "  messages  送る通知 {to (宛先の名前), to_session_id, body} の配列。受信のセッションごとに 1 つ\n"
             "  errors    削除しなかった理由の配列",
             _exit_help("削除した", "一覧を表示していない・番号が一覧に無い・登録が既に無い・" + _NOT_DISPATCHER))
    p.add_argument("--viewer", required=True, help="一覧を表示したセッション (配信のセッション) の ID")
    p.add_argument("numbers", nargs="+", type=_positive, metavar="番号", help="一覧の番号")

    p = _add(g, "resolve", cmd_subscriptions_resolve,
             "受信のセッションが、一時ディレクトリに記録した自分の一覧の番号を登録の ID に変え、\n"
             "削除の申し込み (type: unsubscribe) の本文を作る。記録のディレクトリには書かない。gh は実行しない",
             "  subscription_ids  登録の ID の配列\n"
             "  subscriptions     登録 {number, ...} の配列\n"
             "  dispatcher        記録の配信のセッション。記録が無ければ null\n"
             "  message_body      配信のセッションへ送る本文\n"
             "  errors            本文を作らなかった理由の配列",
             _exit_help("本文を作った", "一覧を表示していない・番号が一覧に無い・登録が既に無い・自分の登録でない"))
    p.add_argument("--viewer", required=True, help="このセッション (受信のセッション) の ID")
    p.add_argument("--name", required=True, help="このセッションの名前 (サイドバーのタイトル)")
    p.add_argument("numbers", nargs="+", type=_positive, metavar="番号", help="一覧の番号")

    p = _add(g, "unsubscribe", cmd_subscriptions_unsubscribe,
             "配信のセッションが、削除の申し込み (type: unsubscribe) の登録を削除し、返事 (type: unsubscribed) の本文を返す。\n"
             "本文の session-id が --sender と違う申し込みと、送り手の登録でない ID を含む申し込みは、何も削除しない。\n"
             "受け付けなかったときも、返事の本文を返す。gh は実行しない",
             "  result      accepted・rejected\n"
             "  removed     削除した登録の配列\n"
             "  reply_body  送り手へ送る返事の本文\n"
             "  errors      受け付けなかった理由の配列",
             _exit_help("削除した", "申し込みの形が違う・送り手が本文と違う・登録が既に無い・送り手の登録でない・" + _NOT_DISPATCHER))
    p.add_argument("--message-file", required=True, help=_MESSAGE_ARGS_HELP["message_file"])
    p.add_argument("--sender", required=True, help=_MESSAGE_ARGS_HELP["sender"])

    p = _add(g, "rename", cmd_subscriptions_rename,
             "配信のセッションが、受信のセッションの ID の登録の名前を変える。gh は実行しない。\n"
             "名前を宛先にしたメッセージが届かないときに、ツール list_sessions で ID から今の名前を引き直して使う",
             "  session_id  --session-id の値\n"
             "  name        --name の値\n"
             "  renamed     名前を変えた登録の数\n"
             "  errors      変えなかった理由の配列",
             _exit_help("変えた", "その ID の登録が無い・引数の形が違う・" + _NOT_DISPATCHER))
    p.add_argument("--session-id", required=True, help="受信のセッションの ID")
    p.add_argument("--name", required=True, help="受信のセッションの今の名前")

    p = _add(groups, "tick", cmd_tick,
             "通知を取得してレビューの依頼を判定し、送信待ちに入れ、この回に送るメッセージを出力する (定期の予定が実行する)。\n"
             "前の回のメッセージの結果が集計されていなければ (settle が呼ばれていなければ)、始めに集計する。\n"
             "取得の範囲の起点は、取得の位置の 5 分前と、最初に開始した時刻の遅いほう。記録が無い最初の回は、今の時刻を\n"
             "開始した時刻と取得の位置にする。gh が失敗したら、取得の位置を変えずに終了コード 4 で返す",
             "  tick_at             この回を始めた時刻\n"
             "  window_start        取得の範囲の起点\n"
             "  position            更新した取得の位置。gh が失敗した回は null\n"
             "  not_modified        通知の一覧が前の回から変わっていない (304) か\n"
             "  found               この回に送信待ちに入れた (出来事, 登録) の数\n"
             "  messages            送るメッセージ {message_id, subscription_id, repo, kind, session_id, session_name,\n"
             "                      to (宛先の名前), to_session_id, count, resend, body} の配列\n"
             "  waiting             この回に出力しなかった送信待ちの数 (次の回に出力する)\n"
             "  expired             30 日を過ぎて消した送信待ち {subscription_id, repo, kind, session_name, count, ...} の配列\n"
             "  previous_round      始めに集計した前の回 (settle と同じ形)。無ければ null\n"
             "  became_unreachable  前の回の集計で、届かない登録になった登録の配列\n"
             "  failed_call         gh が失敗した呼び出し {api, repo, number}。失敗しなければ null\n"
             "  summary             利用者に示す 1 行の要約\n"
             "  errors              取得しなかった理由の配列\n"
             "  gh_error            gh が失敗したときだけ {args, exit_code, failure, stderr_tail, json_error}",
             _exit_help("取得した (送るメッセージが無い回も)", _NOT_DISPATCHER,
                        "gh が失敗した (認証切れ・読めないリポジトリ・rate limit など)。failed_call の呼び出しを示す"))

    p = _add(groups, "ack", cmd_ack,
             "tick が出力したメッセージが届いたことを記録し、そのメッセージの出来事を送信待ちから消す。gh は実行しない。\n"
             "この回 (最後の tick) に出力したメッセージの ID だけを受け付ける",
             "  message_id       メッセージの ID\n"
             "  result           記録した結果 (ack)\n"
             "  subscription_id  メッセージの登録\n"
             "  removed_events   送信待ちから消した出来事の数\n"
             "  errors           記録しなかった理由の配列",
             _exit_help("記録した", "この回のメッセージでない (前の回のメッセージ・settle の後)・既に記録した・" + _NOT_DISPATCHER))
    p.add_argument("message_id", help="tick の出力の messages[].message_id")

    p = _add(groups, "fail", cmd_fail,
             "tick が出力したメッセージが届かなかったことを、理由と一緒に記録する。出来事は送信待ちに残り、次の tick が\n"
             "送り直す。gh は実行しない。この回 (最後の tick) に出力したメッセージの ID だけを受け付ける",
             "  message_id       メッセージの ID\n"
             "  result           記録した結果 (fail)\n"
             "  subscription_id  メッセージの登録\n"
             "  removed_events   0\n"
             "  errors           記録しなかった理由の配列",
             _exit_help("記録した", "この回のメッセージでない (前の回のメッセージ・settle の後)・既に記録した・" + _NOT_DISPATCHER))
    p.add_argument("message_id", help="tick の出力の messages[].message_id")
    p.add_argument("--reason", required=True, help="届かなかった理由 (SendMessage の結果の文)")

    p = _add(groups, "settle", cmd_settle,
             "この回のメッセージの結果を登録ごとに集計し、対応を消す。fail が 1 通でもあれば、続けて届かなかった回数に\n"
             "1 を足す。fail が無く ack が 1 通でもあれば 0 に戻す。どちらも記録されなかったメッセージだけなら変えない。\n"
             "3 回続けて届かなかった登録は、届かない登録になる。gh は実行しない",
             "  settled  集計した回 {round_id, tick_at, results (登録ごとの {subscription_id, repo, kind, session_id,\n"
             "           session_name, result (delivered・failed・unrecorded), consecutive_failures}), became_unreachable,\n"
             "           already_counted}。集計する対応が無ければ null\n"
             "  errors   集計しなかった理由の配列",
             _exit_help("集計した (集計する対応が無い回も)", _NOT_DISPATCHER))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
