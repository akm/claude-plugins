"""コマンド doc-structured の入口。

  doc-structured --version         ツールのバージョンを表示する (設定ファイルは読まない)
  doc-structured version           ツールのバージョンを表示する
  doc-structured generate          ドメインの YAML から、人が読む Markdown を生成する
  doc-structured check [--light|--heavy|--all|--only <検査>]
                                   検査を実行する。指定が無ければ軽い群 (--light)
  doc-structured <知らない名前>     使い方を標準エラー出力に書き、終了コード 2 で終了する

サブコマンドは、起動時に設定ファイルを読み、形が違えばエラーの文を標準エラー出力に書いて終了コード 1 で終了する。
サブコマンドは sub-issue ごとに足す。
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from . import check
from .config import Config, ConfigError, find_config, load_config
from .domains import load_project
from .generate import render_project, write_outputs

VERSION_TEXT = f"doc-structured {__version__}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-structured",
        description="アプリケーションの文書の構成の、生成と検査のツール",
    )
    parser.add_argument("--version", action="version", version=VERSION_TEXT)
    subparsers = parser.add_subparsers(dest="command", metavar="<サブコマンド>", required=True)
    subparsers.add_parser("version", help="ツールのバージョンを表示する")
    subparsers.add_parser("generate", help="ドメインの YAML から、人が読む Markdown を生成する")
    check_parser = subparsers.add_parser("check", help="検査を実行する。指定が無ければ軽い群 (--light)")
    group = check_parser.add_mutually_exclusive_group()
    group.add_argument("--light", action="store_true", help=f"軽い群の検査 ({'・'.join(check.LIGHT)}) を実行する")
    group.add_argument("--heavy", action="store_true", help="重い群の検査を実行する")
    group.add_argument("--all", action="store_true", help="すべての検査を実行する")
    group.add_argument("--only", metavar="<検査>", help="1 つの検査だけを実行する (例 --only a)")
    return parser


def run_check(config: Config, args: argparse.Namespace) -> int:
    if args.only is not None:
        if args.only not in check.ALL:
            print(
                f"doc-structured: このバージョンのツールに検査 {args.only} は無い (ある検査: {'・'.join(check.ALL)})",
                file=sys.stderr,
            )
            return 2
        checks: tuple[str, ...] = (args.only,)
    elif args.heavy:
        checks = check.HEAVY
    elif args.all:
        checks = check.ALL
    else:
        checks = check.LIGHT
    if not checks:
        print("重い群の検査は、このバージョンのツールには無い")
        return 0
    result = check.run_checks(config.root, checks)
    for problem in result.problems:
        print(problem.format())
    names = "・".join(checks)
    if result.skipped:
        print(f"YAML に誤りがあるので、検査 {'・'.join(result.skipped)} を実行しなかった (誤りは検査 h で確認する)")
    if result.ok:
        print(f"検査 {names}: 問題は無かった")
        return 0
    if result.problems:
        print(f"検査 {names}: 問題が {len(result.problems)} 件あった")
    else:
        print(f"検査 {names}: 実行できなかった検査がある")
    return 1


def run_generate(config: Config) -> int:
    project, problems = load_project(config.root)
    if problems:
        for problem in problems:
            print(problem.format(), file=sys.stderr)
        print(f"doc-structured: YAML に {len(problems)} 件の誤りがあるので、何も生成しなかった", file=sys.stderr)
        return 1
    written, deleted = write_outputs(config.root, render_project(project))
    for path in written:
        print(f"書いた: {path}")
    for path in deleted:
        print(f"消した: {path}")
    if not written and not deleted:
        print("生成したファイルは、すべて最新だった")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(find_config(Path.cwd()))
    except ConfigError as e:
        print(f"doc-structured: {e}", file=sys.stderr)
        return 1

    if args.command == "version":
        print(VERSION_TEXT)
        return 0
    if args.command == "generate":
        return run_generate(config)
    if args.command == "check":
        return run_check(config, args)
    # argparse が知らないサブコマンドを拒否するので、ここには来ない
    raise AssertionError(f"知らないサブコマンド: {args.command} (設定: {config.path})")
