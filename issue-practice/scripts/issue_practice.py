#!/usr/bin/env python3
"""issue-practice の検査のスクリプトの入口。サブコマンドごとにパッケージ issue_practice のモジュールの関数を実行する。

出力は標準出力の JSON 1 つ。サブコマンドごとの引数・出力の JSON のキー・終了コードは、`<サブコマンド> --help` が SSOT
(計画 docs/plans/2026-11-13-2156-feat-issue-practice-plugin-plan.md の KTD2)。スキルの SKILL.md は引数を書かずに `--help` を参照する。

サブコマンドの一覧:
  refs parse <参照> [--repo <owner/repo>]       Issue か PR の参照を解析する
  refs milestone <名前>                          リリースマイルストーンの名前を解析する

終了コード (計画の KTD10):
  0  検査して満たす (解析できた・決めた形になっている)
  3  検査して満たさない (入力や GitHub の状態が決めた形になっていない)。満たさない項目を JSON の `errors` などで返す
  4  外部のコマンド (gh・git) が失敗して検査できなかった。JSON の `gh_error` か `git_error` に理由を返す
1 と 2 は Python 自身が使う (捕まえていない例外の 1・引数の誤りの 2)。スキルはこの 2 つをスクリプトの不具合として扱い、
中断する。例外を捕まえて 3 や 4 にすることはしない (「検査できなかった」を「満たさない」と取り違えないため)。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from issue_practice import refs  # noqa: E402

EXIT_OK = 0
EXIT_UNSATISFIED = 3
EXIT_EXTERNAL_FAILED = 4

_EXIT_CODES_HELP = """終了コード:
  0  {ok}
  3  {unsatisfied}
  4  {failed}
  1 と 2 は Python 自身の失敗 (例外と引数の誤り)。スクリプトの不具合として扱う"""


def _exit_help(ok, unsatisfied, failed="使わない (gh も git も実行しない)"):
    return _EXIT_CODES_HELP.format(ok=ok, unsatisfied=unsatisfied, failed=failed)


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# --- refs ---------------------------------------------------------------------------------------------------------

def cmd_refs_parse(args):
    ref = refs.parse_ref(args.ref, default_repo=args.repo)
    if "error" in ref:
        _emit({"ref": None, "errors": [ref["error"]]})
        return EXIT_UNSATISFIED
    _emit({"ref": ref, "errors": []})
    return EXIT_OK


def cmd_refs_milestone(args):
    parsed = refs.parse_milestone_name(args.name)
    if "error" in parsed:
        _emit({"milestone": None, "errors": [parsed["error"]]})
        return EXIT_UNSATISFIED
    _emit({"milestone": parsed, "errors": []})
    return EXIT_OK


# --- 引数 ---------------------------------------------------------------------------------------------------------

def _add(sub, name, func, description, output, exit_help):
    parser = sub.add_parser(name, help=description.splitlines()[0], description=description,
                            epilog=f"出力 (標準出力の JSON):\n{output}\n\n{exit_help}",
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.set_defaults(func=func)
    return parser


def build_parser():
    parser = argparse.ArgumentParser(prog="issue_practice.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    groups = parser.add_subparsers(dest="group", required=True)

    g = groups.add_parser("refs", help="識別子 (Issue と PR の参照・マイルストーンの名前) を解析する").add_subparsers(
        dest="command", required=True)
    p = _add(g, "parse", cmd_refs_parse,
             "Issue か PR の参照を解析する。gh は実行しない。\n"
             "受け付ける形: 12・#12 (リポジトリは --repo)・owner/repo#12・https://github.com/owner/repo/issues/12・…/pull/12",
             "  ref     解析した参照 {owner, repo, number, kind (issue・pull・null), key (owner/repo#番号), url}。\n"
             "          12 と #12 で --repo が無いときは、owner・repo・key・url が null。解析できなければ null\n"
             "  errors  解析できなかった理由の配列",
             _exit_help("解析できた", "解析できなかった"))
    p.add_argument("ref", help="参照")
    p.add_argument("--repo", help="12 と #12 の形のときのリポジトリ (owner/repo)")
    p = _add(g, "milestone", cmd_refs_milestone,
             "リリースマイルストーンの名前 (R<番号> (主題) か R<番号> <リリース対象> (主題)) を解析する。gh は実行しない。",
             "  milestone  {number (リリース Issue の番号), target (リリース対象。名前に無ければ null), subject (主題)}。\n"
             "             解析できなければ null\n"
             "  errors     解析できなかった理由の配列",
             _exit_help("解析できた", "名前の形ではない"))
    p.add_argument("name", help="マイルストーンの名前")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
