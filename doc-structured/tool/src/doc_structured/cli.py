"""コマンド doc-structured の入口。

  doc-structured --version         ツールのバージョンを表示する (設定ファイルは読まない)
  doc-structured version           ツールのバージョンを表示する
  doc-structured generate          ドメインの YAML から、人が読む Markdown を生成する
  doc-structured check [--light|--heavy|--all|--only <検査>]
                                   検査を実行する。指定が無ければ軽い群 (--light)
  doc-structured links-fix [<ファイル>...] [--choose <ファイル> <ラベル> <ID か URL>]...
                                   手書きの Markdown の定義の行・ファイルのアンカー・リンクの表示の文を直す。
                                   判断の要るものが残れば終了コード 1
  doc-structured refs <ID>         その ID と子孫の ID を参照している、手書きの Markdown の箇所を出力する。
                                   見つからなくても終了コード 0。ID の形が違えば終了コード 1
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
from .documents import load_documents
from .domains import load_project
from .generate import HANDWRITTEN_MESSAGE, HandwrittenFilesError, handwritten_fix, render_project, write_outputs
from .links_fix import Choice, ChoiceError, fix_files
from .names import IdError
from .refs import find_refs

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
    fix_parser = subparsers.add_parser(
        "links-fix",
        help="手書きの Markdown の定義の行・ファイルのアンカー・リンクの表示の文を直す。判断の要るものが残れば終了コード 1",
    )
    fix_parser.add_argument(
        "paths", nargs="*", metavar="<ファイル>", help="直す手書きの Markdown。指定が無ければ、すべての手書きの Markdown"
    )
    fix_parser.add_argument(
        "--choose", nargs=3, action="append", default=[], metavar=("<ファイル>", "<ラベル>", "<ID か URL>"),
        help="ファイルのラベルの参照先を、参照先の ID か外部の URL で指定する (何度でも指定できる)",
    )
    refs_parser = subparsers.add_parser(
        "refs", help="その ID と子孫の ID を参照している、手書きの Markdown の箇所を出力する"
    )
    refs_parser.add_argument("id", metavar="<ID>", help="参照している箇所を探す ID (例 d-loans-m-loan)")
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
    try:
        written, deleted = write_outputs(config.root, render_project(project))
    except HandwrittenFilesError as e:
        for relative in e.paths:
            print(f"{relative}: {HANDWRITTEN_MESSAGE}。{handwritten_fix(relative)}", file=sys.stderr)
        print(
            f"doc-structured: 生成するファイルの場所に手で書いたファイルが {len(e.paths)} 件あるので、何も生成しなかった",
            file=sys.stderr,
        )
        return 1
    for path in written:
        print(f"書いた: {path}")
    for path in deleted:
        print(f"消した: {path}")
    if not written and not deleted:
        print("生成したファイルは、すべて最新だった")
    return 0


def _relative(config: Config, path: str) -> str | None:
    """コマンドに渡したパス (今のディレクトリからの相対か絶対) を、リポジトリのルートからの相対パスにする。"""
    resolved = (Path.cwd() / path).resolve()
    try:
        return resolved.relative_to(config.root.resolve()).as_posix()
    except ValueError:
        return None


def run_links_fix(config: Config, args: argparse.Namespace) -> int:
    project, problems = load_project(config.root)
    if problems:
        for problem in problems:
            print(problem.format(), file=sys.stderr)
        print(f"doc-structured: YAML に {len(problems)} 件の誤りがあるので、何も直さなかった", file=sys.stderr)
        return 1
    index, _ = load_documents(config.root, project)
    paths: list[str] | None = None
    if args.paths:
        paths = []
        for given in args.paths:
            relative = _relative(config, given)
            if relative is None or index.file(relative) is None:
                print(
                    f"doc-structured: {given} は、ドメインのディレクトリの下の手書きの Markdown でない", file=sys.stderr
                )
                return 1
            paths.append(relative)
    choices: list[Choice] = []
    for given, label, value in args.choose:
        relative = _relative(config, given)
        if relative is None:
            print(f"doc-structured: --choose のファイル {given} は、リポジトリの外にある", file=sys.stderr)
            return 1
        choices.append(Choice(relative, label, value))
    try:
        result = fix_files(config.root, index, paths, choices)
    except ChoiceError as e:
        print(f"doc-structured: {e}", file=sys.stderr)
        return 1
    for path in result.changed:
        print(f"書き換えた: {path}")
    for report in result.reports:
        print(report.format())
    if result.reports:
        print(f"判断の要るものが {len(result.reports)} 件ある (参照先を --choose で渡すか、本文を直して、もう一度実行する)")
        return 1
    if not result.changed:
        print("直すものは無かった")
    return 0


def run_refs(config: Config, args: argparse.Namespace) -> int:
    # YAML に誤りがあっても実行する (手書きのファイルの見つけ方と行が属する ID は、YAML の内容を使わないため。
    # 決めた経緯は Issue #198 のコメントの 6)
    project, _ = load_project(config.root)
    index, _ = load_documents(config.root, project)
    try:
        result = find_refs(index, args.id)
    except IdError as e:
        print(f"doc-structured: ID {args.id} の形が違う: {e}", file=sys.stderr)
        return 1
    for line in result.lines():
        print(line)
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
    if args.command == "links-fix":
        return run_links_fix(config, args)
    if args.command == "refs":
        return run_refs(config, args)
    # argparse が知らないサブコマンドを拒否するので、ここには来ない
    raise AssertionError(f"知らないサブコマンド: {args.command} (設定: {config.path})")
