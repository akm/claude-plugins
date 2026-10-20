#!/usr/bin/env python3
"""issue-dispatch の CLI の入口。サブコマンドごとにパッケージ issue_dispatch のモジュールの関数を実行する。入出力は JSON。

サブコマンドの一覧の正本は、計画 docs/plans/2026-10-06-2025-feat-issue-dispatch-plan.md の KTD14。
この版にあるサブコマンド:
  config read --dir <ルート> --role manager|repo   設定を読み、デフォルト値を当てた後の設定と警告・エラーを返す
  config add-edit-check --dir <ルート> --repo <owner/repo>   管理ディレクトリの設定の third_party_edit_check に足す
  files classify --dir <リポジトリのルート> <パス>...   パスごとの種類と属性 (リポジトリの設定の files とデフォルトの表で決める)

終了コード: JSON を出せたときは、エラーの有無によらず 0 (エラーは JSON の `errors` で伝える)。0 以外は Python 自身の失敗
(捕まえていない例外の 1・引数の誤りの 2) で、呼び出す側はそれを停止の条件として扱う (正本は同じ計画の R25。
1 と 2 は Python 自身が使うので、サブコマンドの専用の終了コードには使わない)。
"""

import argparse
import json
import sys

from issue_dispatch import config, filekinds


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def cmd_config_read(args):
    _emit(config.load(args.dir, args.role))
    return 0


def cmd_config_add_edit_check(args):
    _emit(config.add_edit_check(args.dir, args.repo))
    return 0


def cmd_files_classify(args):
    loaded = config.load(args.dir, "repo")
    table = filekinds.load_default_table()
    results = [{"path": path, **filekinds.classify(path, loaded["config"]["files"], table)} for path in args.paths]
    _emit({"paths": results, "config_status": loaded["status"], "warnings": loaded["warnings"], "errors": loaded["errors"]})
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="issue_dispatch.py", description="issue-dispatch の同梱 CLI (入出力は JSON)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("config", help="設定の読み込みと書き換え")
    config_sub = p_config.add_subparsers(dest="subcommand", required=True)

    p_read = config_sub.add_parser("read", help="設定を読む")
    p_read.add_argument("--dir", required=True, help="管理ディレクトリかリポジトリのルート")
    p_read.add_argument("--role", required=True, choices=config.ROLES, help="manager (管理ディレクトリ) / repo (リポジトリ)")
    p_read.set_defaults(func=cmd_config_read)

    p_add = config_sub.add_parser("add-edit-check", help="third_party_edit_check にリポジトリを足す (承認を得た後)")
    p_add.add_argument("--dir", required=True, help="管理ディレクトリ")
    p_add.add_argument("--repo", required=True, help="owner/repo")
    p_add.set_defaults(func=cmd_config_add_edit_check)

    p_files = sub.add_parser("files", help="ファイルの種類")
    files_sub = p_files.add_subparsers(dest="subcommand", required=True)
    p_classify = files_sub.add_parser("classify", help="パスごとの種類と属性を返す (gh は実行しない)")
    p_classify.add_argument("--dir", required=True, help="リポジトリのルート (設定の files を読む)")
    p_classify.add_argument("paths", nargs="+", help="ルートからの相対パス")
    p_classify.set_defaults(func=cmd_files_classify)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
