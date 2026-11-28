#!/usr/bin/env python3
"""disk-usage-triage のスクリプトの入口。サブコマンドごとにパッケージ disk_usage_triage のモジュールの関数を実行する。

出力は標準出力の JSON 1 つで、必ずキー `errors` を持つ (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD14)。
サブコマンドごとの引数・出力の JSON のキー・終了コードは、`<サブコマンド> --help` が SSOT。スキルの SKILL.md は引数を書かずに
`--help` を参照する。保存先のディレクトリ (`~/.claude/disk-usage-triage/`) のファイルと入力のファイルの様式は、文書
references/files.md にある。

サブコマンドの一覧:
  config show                       設定を表示する。設定が無いときも、無いことを出力する
  config set --input-file <ファイル>  入力のファイルの内容で、設定の全体を置き換える
  records list                      記録を、番号を付けて表示する
  records add --input-file <ファイル>  利用者が「残す」と言った対象を記録する (--run と --item で一覧の項目を指定できる)
  records remove --listing <ID> <番号>...  records list の番号の記録を消す
  run start                         トリアージを始め、トリアージの ID を出力する
  scan --run <ID> [--item <番号>]    調べるディレクトリか一覧の項目の下の階層を du で調べ、一覧を作る
  list show --run <ID> <英字>        一覧を、その時の判定と一緒に表示する
  select add --run <ID> <番号>...    一覧の項目を、消す項目として選ぶ
  select remove --run <ID> <番号>... 選んだ項目から外す
  select show --run <ID>            選んだ項目を表示する
  judge set --run <ID> <番号> --input-file <ファイル>  一覧の項目に、Claude の判定を記録する
  hook pre-tool-use                 hook PreToolUse が実行する。削除のシェルスクリプトの実行と書き換えを拒否する

終了コード (計画の KTD14):
  0  続ける
  3  出力の `errors` を利用者に示して判断を求める (入力の誤り・壊れたファイル・Python の版が古いなど)
  4  外部のコマンドが失敗した
1 と 2 は Python 自身が使う (捕まえていない例外の 1・引数の誤りの 2)。スキルはこの 2 つをスクリプトの不具合として扱い、
中断する。例外を捕まえて 3 や 4 にすることはしない。

Python の版が 3.11 より古いときは、引数を解析する前に、版を `errors` に書いて終了コード 3 で終了する (計画の節「Assumptions」)。
macOS の /usr/bin/python3 は 3.9 のことがあるので、版を確認するまでの部分 (このファイル) は、古い版でも読める書き方にし、
パッケージは版を確認してから読み込む。

サブコマンド hook は、Claude Code の hook が実行するので、出力は Claude Code の hook の出力の様式にし、キー `errors` を持たない。
Python の版が古いときも、版を標準出力ではなく標準エラー出力に書く。標準出力の JSON は Claude Code に hook の出力として読まれ、
hook の誤りとして示されないことがあるため (計画の U8 を実装するときに利用者が決めた。2026-11-24)。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REQUIRED_PYTHON = (3, 11)

EXIT_OK = 0
EXIT_UNSATISFIED = 3
EXIT_EXTERNAL_FAILED = 4

_EXIT_CODES_HELP = """終了コード:
  0  {ok}
  3  {unsatisfied}
  4  {failed}
  1 と 2 は Python 自身の失敗 (例外と引数の誤り)。スクリプトの不具合として扱う"""

_NO_EXTERNAL = "使わない (外部のコマンドを実行しない)"


def _exit_help(ok, unsatisfied, failed=_NO_EXTERNAL):
    return _EXIT_CODES_HELP.format(ok=ok, unsatisfied=unsatisfied, failed=failed)


def _emit(payload):
    """標準出力に JSON を書く。UTF-8 として読めない名前のパスも書けるように、モジュール store の関数 dumps で書く (計画の KTD2)。"""
    from disk_usage_triage import store  # Python の版を確認した後に呼ぶ (関数 main)
    sys.stdout.write(store.dumps(payload))
    sys.stdout.write("\n")


def _emit_status(result):
    status = result.pop("status")
    _emit(result)
    return EXIT_OK if status == "ok" else EXIT_UNSATISFIED


def python_version_errors(version_info):
    """version_info が REQUIRED_PYTHON より古ければ、版を示す誤りの配列。新しければ空の配列。"""
    if tuple(version_info[:2]) >= REQUIRED_PYTHON:
        return []
    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    actual = ".".join(str(part) for part in version_info[:3])
    return [f"Python {required} 以上が必要 (実行した python3 は {actual}、パスは {sys.executable})"]


def cmd_config_show(args):
    from disk_usage_triage import config
    return _emit_status(config.show())


def cmd_config_set(args):
    from disk_usage_triage import config
    return _emit_status(config.set_from_file(args.input_file))


def cmd_records_list(args):
    from disk_usage_triage import records
    return _emit_status(records.list_records())


def cmd_records_add(args):
    from disk_usage_triage import lists, records
    if (args.run is None) != (args.item is None):
        args.parser.error("--run と --item は、両方を指定する")
    if args.item is not None:
        return _emit_status(lists.add_keep(args.run, args.item, args.input_file))
    return _emit_status(records.add_from_file(args.input_file))


def cmd_records_remove(args):
    from disk_usage_triage import records
    return _emit_status(records.remove(args.listing, args.numbers))


def cmd_run_start(args):
    from disk_usage_triage import lists
    return _emit_status(lists.run_start())


def cmd_scan(args):
    from disk_usage_triage import lists
    return _emit_status(lists.scan(args.run, args.item))


def cmd_list_show(args):
    from disk_usage_triage import lists
    return _emit_status(lists.show(args.run, args.letter, all_items=args.all, unreadable=args.unreadable))


def cmd_select_add(args):
    from disk_usage_triage import lists
    if bool(args.numbers) == (args.all_deletable is not None):
        args.parser.error("番号か --all-deletable の、どちらか一方を指定する")
    if args.all and args.all_deletable is None:
        args.parser.error("--all は、--all-deletable と一緒に指定する")
    return _emit_status(lists.select_add(args.run, args.numbers, all_deletable=args.all_deletable,
                                         include_others=args.all))


def cmd_select_remove(args):
    from disk_usage_triage import lists
    return _emit_status(lists.select_remove(args.run, args.numbers))


def cmd_select_show(args):
    from disk_usage_triage import lists
    return _emit_status(lists.select_show(args.run))


def cmd_judge_set(args):
    from disk_usage_triage import lists
    return _emit_status(lists.judge_set(args.run, args.number, args.input_file))


def cmd_hook_pre_tool_use(args):
    from disk_usage_triage import hook
    try:
        output = hook.pre_tool_use(sys.stdin.read())
    except hook.InvalidInput as e:
        # 標準出力には何も書かない。Claude Code は、終了コードが 0 と 2 以外の hook を誤りとして示し、ツールを実行する
        sys.stderr.write(f"disk-usage-triage: {e}。拒否も許可もしない\n")
        return EXIT_UNSATISFIED
    if output is not None:
        _emit(output)
    return EXIT_OK


# --- 引数 ---------------------------------------------------------------------------------------------------------

def _add(sub, name, func, description, output, exit_help):
    parser = sub.add_parser(name, help=description.splitlines()[0], description=description,
                            epilog=f"出力 (標準出力の JSON):\n{output}\n\n{exit_help}",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.set_defaults(func=func, parser=parser)
    return parser


_BACKGROUND = ("Bash ツールの時間の上限より長くかかることがある。そのため、Bash ツールのバックグラウンド\n"
               "(引数 run_in_background) で実行し、完了の通知を受けてから出力を読む (計画の KTD15)")

_RUN_HELP = "run start が出力したトリアージの ID (YYYYMMDD-HHMMSS)"

_ITEM_FIELDS = ("number, path, display, bytes, size, judgment, judgment_label, reason,\n"
                "                   record, impact, command, command_text, process_names, dedicated_list, unreadable_count")

_LIST_OUTPUT = (
    "  letter           一覧の英字。一覧が無いときは null\n"
    "  created_at       一覧を作った時刻\n"
    "  source           何を調べた一覧か。{kind: scan_dirs} か {kind: item, number, path, display}\n"
    "  table            一覧の表 (Markdown)。スキルはそのまま示す\n"
    "  notes            表の下に示す注記の配列 (調べたディレクトリごとの使用量・読めなかったディレクトリなど)。スキルはそのまま示す\n"
    f"  items            表に示した項目の配列。要素は {{{_ITEM_FIELDS}}}。\n"
    "                   judgment は deletable・review・keep か null (判定なし)。impact と command_text は表に出さない\n"
    "  others           その他の行 {count, bytes, size, deletable_count, deletable_bytes, unreadable_count}。無ければ null\n")

_LISTS_UNSATISFIED = ("トリアージ・一覧・番号が無いか形が違う・設定か記録 (records.json) が無いか壊れている・\n"
                      "     一覧のファイルが壊れている (新しいトリアージで調べ直す)")


_CONFIG_SHAPE = "{scan_dirs, project_dirs, timeout_seconds}"


def build_parser():
    from disk_usage_triage import config  # Python の版を確認した後に呼ぶ (関数 main)

    parser = argparse.ArgumentParser(prog="disk_usage_triage.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    groups = parser.add_subparsers(dest="group", required=True)

    g = groups.add_parser("config", help="設定を表示する・置き換える").add_subparsers(dest="command", required=True)
    _add(g, "show", cmd_config_show,
         "設定 (保存先のディレクトリのファイル config.json) を表示する。設定が無いときも誤りにせず、exists を false にする。\n"
         "保存した値の形だけを確認し、ディレクトリがあるかは確認しない。保存先のディレクトリは作らない",
         "  exists      config.json があるか (壊れているときも true)\n"
         f"  config      設定 {_CONFIG_SHAPE}。config set の入力と同じ形。無いときと壊れているときは null\n"
         "  path        config.json の絶対パス\n"
         "  inputs_dir  config set などに渡す入力のファイルを、Claude が書くディレクトリの絶対パス\n"
         "  errors      設定を読めなかった理由の配列",
         _exit_help("表示した (設定が無いときも)", "config.json が壊れている (理由と、ファイルのパスを errors に書く)"))

    p = _add(g, "set", cmd_config_set,
             "引数 --input-file の JSON のファイルの内容で、設定 (config.json) の全体を置き換える。書いたキーだけを変えることは\n"
             f"しない。timeout_seconds を省くと {config.DEFAULT_TIMEOUT_SECONDS} を書き、前の設定の値は残らない。"
             "入力の様式と検査の内容は、文書\n"
             "references/files.md の節「config set の入力」にある。誤りはすべて errors に書き、1 つでもあれば何も保存しない\n"
             "(保存先のディレクトリも作らない)",
             f"  config    保存した設定 {_CONFIG_SHAPE}。保存しなかったときは null\n"
             "  previous  置き換える前の設定 (同じ形)。設定が無かったときと、保存しなかったときは null\n"
             "  path      config.json の絶対パス\n"
             "  errors    保存しなかった理由の配列",
             _exit_help("保存した",
                        "入力のファイルを読めない・入力に誤りがある (知らないキー・型の違う値・相対パス・存在しないディレクトリ・\n"
                        "     調べるディレクトリの重複と入れ子など)・config.json が壊れている"))
    p.add_argument("--input-file", required=True,
                   help="Claude が Write ツールで書いた入力の JSON のファイル (config show の inputs_dir の下に置く)")

    g = groups.add_parser("records", help="記録を表示する・足す・消す").add_subparsers(dest="command", required=True)
    _add(g, "list", cmd_records_list,
         "記録 (保存先のディレクトリのファイル records.json) を、対象の種類の順 (ディレクトリ・Docker・asdf)、同じ種類の中では\n"
         "パスか名前の順に並べ、1 から番号を付けて表示する。記録が無いときも誤りにしない。様式は文書 references/files.md の\n"
         "節「records.json」にある",
         "  records  記録の配列。要素は records.json の記録に、number (番号) と display (対象を示す文字列。ディレクトリは\n"
         "           ~ で始まる形、Docker は名前、asdf は「ツール 版」) を足したもの。壊れているときは空の配列\n"
         "  listing  一覧の ID (記録の中身から求めた値)。records remove に渡す。壊れているときは null\n"
         "  path     records.json の絶対パス\n"
         "  errors   記録を読めなかった理由の配列",
         _exit_help("表示した (記録が無いときも)", "records.json が壊れている (理由と、ファイルのパスを errors に書く)"))

    p = _add(g, "add", cmd_records_add,
             "引数 --input-file の JSON のファイルの対象を、利用者の「残す」として記録する。引数 --run と --item で一覧の項目を\n"
             "指定すると、入力に target を書かず、その項目のディレクトリを対象にする。同じ対象の記録があれば置き換え、\n"
             "判定・だれが決めたか・日付 (と、入力に書いたときは理由) だけを変える。入力の様式と検査の内容は、文書\n"
             "references/files.md の節「records add の入力」にある。ディレクトリの記録には設定 (config.json) が要る。\n"
             "誤りはすべて errors に書き、1 つでもあれば何も記録しない",
             "  record    記録したもの (records.json の記録の形)。記録しなかったときは null\n"
             "  display   記録した対象を示す文字列 (records list と同じ形)。記録しなかったときは null\n"
             "  previous  置き換えた記録。無かったときと、記録しなかったときは null\n"
             "  path      records.json の絶対パス\n"
             "  errors    記録しなかった理由の配列",
             _exit_help("記録した",
                        "入力のファイルを読めない・入力に誤りがある (知らないキー・keep でない判定・存在しないディレクトリ・\n"
                        "     保護の一覧の場所・名前の形の誤りなど)・設定が無いか壊れている (ディレクトリのとき)・\n"
                        "     records.json が壊れている・--item のトリアージ・一覧・番号が無いか、一覧のファイルが壊れている"))
    p.add_argument("--input-file", required=True,
                   help="Claude が Write ツールで書いた入力の JSON のファイル (config show の inputs_dir の下に置く)")
    p.add_argument("--run", help=f"{_RUN_HELP}。--item と一緒に指定する")
    p.add_argument("--item", metavar="番号",
                   help="記録する一覧の項目の番号 (例: A3)。指定すると、入力に target を書かず、この項目のディレクトリを記録する")

    p = _add(g, "remove", cmd_records_remove,
             "records list で表示した一覧の番号の記録を消す。一覧を表示した後に記録が変わっていれば (一覧の ID が違えば)、\n"
             "何も消さない。範囲の外の番号が 1 つでもあれば、何も消さない。同じ番号は 1 つにする",
             "  removed  消した記録の配列 (records list の要素と同じ形)。消さなかったときは空の配列\n"
             "  path     records.json の絶対パス\n"
             "  errors   消さなかった理由の配列",
             _exit_help("消した",
                        "一覧を表示した後に記録が変わった・範囲の外の番号がある・records.json が壊れている"))
    p.add_argument("--listing", required=True, help="records list の出力の listing (一覧の ID)")
    p.add_argument("numbers", nargs="+", type=int, metavar="番号", help="records list の出力の number")

    g = groups.add_parser("run", help="トリアージを始める").add_subparsers(dest="command", required=True)
    _add(g, "start", cmd_run_start,
         "トリアージ (調べ始めてから、削除の後の比較までの 1 回分の作業) を始める。保存先のディレクトリの下にトリアージの\n"
         "ディレクトリを作り、トリアージの ID (始めた手元の時刻 YYYYMMDD-HHMMSS) を出力する。ほかのサブコマンドの --run に渡す。\n"
         "設定 (config.json) が要る",
         "  run         トリアージの ID。作らなかったときは null\n"
         "  created_at  始めた時刻。作らなかったときは null\n"
         "  errors      作らなかった理由の配列",
         _exit_help("始めた", "設定が無いか壊れている・同じ秒に始めたトリアージがある"))

    p = _add(groups, "scan", cmd_scan,
             "調べるディレクトリ (設定の scan_dirs) を du で調べ、1 つ下の階層の項目を使用量の多い順に並べた、最初の一覧 (英字 A) を\n"
             "作る。引数 --item で一覧の項目を指定すると、その 1 つ下の階層を調べて、次の英字の一覧を作る。同じものをもう一度\n"
             "調べると、そのたびに新しい一覧を作る。一覧は 1 つのトリアージで 26 個 (A〜Z) まで。専用の一覧の項目 (~/.asdf/installs\n"
             "など) を指定すると、一覧を作らずに dedicated_list を返す。結果を出せた調べるディレクトリが無いときと、--item の項目の\n"
             "下の階層を調べられなかったときは、一覧を作らない。\n"
             f"調べるディレクトリごとに時間の上限 (設定の timeout_seconds 秒) があり、全体では\n{_BACKGROUND}",
             "  run              トリアージの ID\n"
             "  dedicated_list   --item の項目が専用の一覧の項目なら、その種類 (asdf・docker・worktree)。ほかは null\n"
             "  item             --item の項目 (items の要素と同じ形)。--item が無いときと、番号が無いときは null\n"
             + _LIST_OUTPUT +
             "  unreadable       null (読めなかったパスは list show の --unreadable で出力する)\n"
             "  errors           一覧を作らなかった理由の配列",
             _exit_help("一覧を作った・専用の一覧の項目だった",
                        _LISTS_UNSATISFIED + "・一覧を 26 個作り終えた・\n"
                        "     du の結果を出せなかった (どの調べるディレクトリも、または --item の項目の下の階層を)",
                        "使わない (du が失敗したときと、時間の上限を超えたときも、3 で示す)"))
    p.add_argument("--run", required=True, help=_RUN_HELP)
    p.add_argument("--item", metavar="番号", help="下の階層を調べる一覧の項目の番号 (例: A3)")

    g = groups.add_parser("list", help="一覧を表示する").add_subparsers(dest="command", required=True)
    p = _add(g, "show", cmd_list_show,
             "一覧を、その時の設定・記録・判定表から求めた判定と一緒に表示する (判定は一覧のファイルに保存しない)。表には、使用量の\n"
             "多い順に 30 項目を示し、残りをその他の行にまとめる。--all を付けると、すべての項目を示す",
             "  run              トリアージの ID\n"
             + _LIST_OUTPUT +
             "  unreadable       --unreadable のときだけ、{items: [{number, display, paths}], unmapped}。表に示した項目 (--all なら\n"
             "                   すべての項目) の読めなかったパスと、どの項目にも入らない読めなかったパス。ほかは null\n"
             "  errors           表示しなかった理由の配列",
             _exit_help("表示した", _LISTS_UNSATISFIED))
    p.add_argument("--run", required=True, help=_RUN_HELP)
    p.add_argument("letter", metavar="英字", help="一覧の英字 (例: A)")
    p.add_argument("--all", action="store_true", help="その他の行にまとめず、すべての項目を示す")
    p.add_argument("--unreadable", action="store_true", help="読めなかったパスも出力する (利用者が依頼したときだけ使う)")

    g = groups.add_parser("select", help="消す項目を選ぶ・外す・表示する").add_subparsers(dest="command", required=True)
    p = _add(g, "add", cmd_select_add,
             "一覧の項目を、消す項目として選ぶ。選んだ項目は、トリアージの中で、複数の一覧にまたがって 1 つにまとめる。\n"
             "引数 --all-deletable <英字> を付けると、その一覧の番号が 1〜30 の項目 (--all を付けない list show の表の項目) のうちの\n"
             "「消してよい」の項目を選び、--all も付けると、31 番目以降の項目 (その他の行の項目) からも選ぶ。\n"
             "保護の一覧の項目・判定が「残す」か判定の無い項目・保護の一覧の場所か「残す」の項目を含む項目・下にアプリの\n"
             "worktree があるか、探しきれない項目は選ばず、理由を rejected に書く。\n"
             "親を選んでいる項目は選ばず、子を選んでいる項目の親を選ぶと、子を外す。形の誤りか存在しない番号が 1 つでもあれば、\n"
             "何も選ばない。\n"
             "項目の下にアプリの worktree があるかを、項目ごとに時間の上限 (設定の timeout_seconds 秒) の中で探すので、全体では\n"
             f"{_BACKGROUND}",
             "  run               トリアージの ID\n"
             "  added             選んだ項目の配列。要素は list show の items の要素と同じ形 (影響と消すコマンドを含む)\n"
             "  already           既に選んでいた項目の配列。要素は {number, display}\n"
             "  replaced          親を選んだので外した子の配列。要素は {number, display, parent (選んだ親の番号)}\n"
             "  rejected          選ばなかった項目の配列。要素は {number, display, reasons (理由の配列)}\n"
             "  others_deletable  --all-deletable で --all が無いときの、31 番目以降 (その他の行) の「消してよい」の項目\n"
             "                    {count, bytes, size}。\n"
             "                    ほかは null\n"
             "  selection         選んだ項目の全体 {count, bytes, size}。何も選ばなかったとき (終了コード 3) は null\n"
             "  errors            何も選ばなかった理由の配列",
             _exit_help("選んだ (選ばなかった項目があっても、rejected に理由を書いて 0 で終了する)",
                        _LISTS_UNSATISFIED + "・選んだ項目のファイルが壊れている"))
    p.add_argument("--run", required=True, help=_RUN_HELP)
    p.add_argument("numbers", nargs="*", metavar="番号", help="選ぶ項目の番号 (例: A3 B12)")
    p.add_argument("--all-deletable", metavar="英字", help="この一覧の番号が 1〜30 の「消してよい」の項目を、まとめて選ぶ")
    p.add_argument("--all", action="store_true", help="--all-deletable で、31 番目以降 (その他の行) の項目からも選ぶ")

    p = _add(g, "remove", cmd_select_remove,
             "番号の項目を、選んだ項目から外す。選んでいない項目は、何もせずに not_selected に書く。形の誤りか存在しない番号が\n"
             "1 つでもあれば、何も外さない",
             "  run           トリアージの ID\n"
             "  removed       外した項目の配列。要素は {number (選んだときの番号), display, size}\n"
             "  not_selected  選んでいなかった項目の配列。要素は {number, display, reason}\n"
             "  selection     選んだ項目の全体 {count, bytes, size}。何も外さなかったとき (終了コード 3) は null\n"
             "  errors        何も外さなかった理由の配列",
             _exit_help("外した (選んでいない項目があっても 0)",
                        "トリアージ・一覧・番号が無いか形が違う・一覧か選んだ項目のファイルが壊れている"))
    p.add_argument("--run", required=True, help=_RUN_HELP)
    p.add_argument("numbers", nargs="+", metavar="番号", help="外す項目の番号")

    p = _add(g, "show", cmd_select_show,
             "選んだ項目を、その時の判定と一緒に表示する",
             "  run        トリアージの ID\n"
             "  items      選んだ項目の配列。要素は list show の items の要素から unreadable_count を除いた形\n"
             "  table      選んだ項目の表 (Markdown)。選んだ項目が無ければ null\n"
             "  selection  選んだ項目の全体 {count, bytes, size}。表示しなかったときは null\n"
             "  errors     表示しなかった理由の配列",
             _exit_help("表示した (選んだ項目が無いときも)",
                        "トリアージが無い・設定か記録が無いか壊れている・選んだ項目のファイルが壊れている"))
    p.add_argument("--run", required=True, help=_RUN_HELP)

    g = groups.add_parser("judge", help="Claude の判定を記録する").add_subparsers(dest="command", required=True)
    p = _add(g, "set", cmd_judge_set,
             "一覧の項目に、引数 --input-file の JSON のファイルの Claude の判定を記録する。受け付けるのは、判定の無い項目と、\n"
             "項目そのものの Claude の記録で判定が決まった項目 (調べ直し) だけ。入力の様式と検査の内容は、文書\n"
             "references/files.md の節「Claude の判定の入力」にある。一覧のファイルは変えない (次の list show から判定が変わる)",
             "  run       トリアージの ID\n"
             "  item      記録した後の項目 (list show の items の要素と同じ形)。記録しなかったときは null\n"
             "  record    記録したもの (records.json の記録の形)。記録しなかったときは null\n"
             "  previous  置き換えた Claude の記録。無かったときと、記録しなかったときは null\n"
             "  errors    記録しなかった理由の配列",
             _exit_help("記録した",
                        _LISTS_UNSATISFIED + "・保護の一覧・判定表・親の\n"
                        "     ディレクトリの記録・利用者の記録で判定が決まった項目・入力のファイルを読めないか、入力に誤りがある"))
    p.add_argument("--run", required=True, help=_RUN_HELP)
    p.add_argument("number", metavar="番号", help="判定を記録する一覧の項目の番号 (例: A3)")
    p.add_argument("--input-file", required=True,
                   help="Claude が Write ツールで書いた入力の JSON のファイル (config show の inputs_dir の下に置く)")

    g = groups.add_parser("hook", help="hook が実行する").add_subparsers(dest="command", required=True)
    _add(g, "pre-tool-use", cmd_hook_pre_tool_use,
         "hook PreToolUse (ファイル hooks/hooks.json) が実行する。標準入力の hook の入力のツールが、Bash ツールか\n"
         "mcp__terminal__run_in_terminal なら入力 tool_input のすべての文字列 (コマンドのキー command・タブを開くディレクトリの\n"
         "キー cwd など) を、Write・Edit・MultiEdit・NotebookEdit なら書き込むファイルのパス (キー file_path・notebook_path) を\n"
         "検査し、文字列 disk-usage-triage/runs・保存先のディレクトリの下の runs の絶対パス・削除のシェルスクリプトのファイル名\n"
         "disk-usage-triage-delete.sh のどれかを含めば拒否する。ほかのツールは検査しない。保存先のディレクトリは読みも書きもしない",
         "  Claude Code の hook の出力の様式 {hookSpecificOutput: {hookEventName (PreToolUse), permissionDecision (deny),\n"
         "  permissionDecisionReason}}。拒否しないときと、入力が読めないときは、何も出力しない (errors のキーは持たない)",
         _exit_help("拒否した・拒否しなかった",
                    "hook の入力が読めない (JSON として読めない・キーの値の型が違う)・Python の版が古い。理由を標準エラー出力\n"
                    "     に書き、拒否も許可もしない (Claude Code は hook の誤りとして示し、ツールを実行する)"))
    return parser


def main(argv=None):
    errors = python_version_errors(sys.version_info)
    if errors:
        if (sys.argv[1:] if argv is None else argv)[:1] == ["hook"]:
            for error in errors:
                sys.stderr.write(f"disk-usage-triage: {error}\n")
        else:  # 古い版ではパッケージを読み込まないので、関数 _emit を使わない
            json.dump({"errors": errors}, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        return EXIT_UNSATISFIED
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
