#!/usr/bin/env python3
"""disk-usage-triage のスクリプトの入口。サブコマンドごとにパッケージ disk_usage_triage のモジュールの関数を実行する。

出力は標準出力の JSON 1 つで、必ずキー `errors` を持つ (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の KTD14)。
サブコマンドごとの引数・出力の JSON のキー・終了コードは、`<サブコマンド> --help` が SSOT。スキルの SKILL.md は引数を書かずに
`--help` を参照する。保存先のディレクトリ (`~/.claude/disk-usage-triage/`) のファイルと入力のファイルの様式は、文書
references/files.md にある。

サブコマンドの一覧:
  config show                       設定を表示する。設定が無いときも、無いことを出力する
  config set --input-file <ファイル>  入力のファイルの内容で、設定の全体を置き換える

終了コード (計画の KTD14):
  0  続ける
  3  出力の `errors` を利用者に示して判断を求める (入力の誤り・壊れたファイル・Python の版が古いなど)
  4  外部のコマンドが失敗した
1 と 2 は Python 自身が使う (捕まえていない例外の 1・引数の誤りの 2)。スキルはこの 2 つをスクリプトの不具合として扱い、
中断する。例外を捕まえて 3 や 4 にすることはしない。

Python の版が 3.11 より古いときは、引数を解析する前に、版を `errors` に書いて終了コード 3 で終了する (計画の節「Assumptions」)。
macOS の /usr/bin/python3 は 3.9 のことがあるので、版を確認するまでの部分 (このファイル) は、古い版でも読める書き方にし、
パッケージは版を確認してから読み込む。
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
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
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


# --- 引数 ---------------------------------------------------------------------------------------------------------

def _add(sub, name, func, description, output, exit_help):
    parser = sub.add_parser(name, help=description.splitlines()[0], description=description,
                            epilog=f"出力 (標準出力の JSON):\n{output}\n\n{exit_help}",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.set_defaults(func=func)
    return parser


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
    return parser


def main(argv=None):
    errors = python_version_errors(sys.version_info)
    if errors:
        _emit({"errors": errors})
        return EXIT_UNSATISFIED
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
