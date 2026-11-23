"""コマンド doc-structured の入口。

  doc-structured --version         ツールのバージョンを表示する (設定ファイルは読まない)
  doc-structured version           ツールのバージョンを表示する
  doc-structured generate [--all]  ドメインの YAML から、人が読む Markdown を生成する。--all は、設定に
                                   database.schema_actual: true があれば、実際のスキーマの docs/system/schema-actual.md も
                                   生成し直す (データベースが無ければ終了コード 3)
  doc-structured check [--light|--heavy|--all|--only <検査>]
                                   検査を実行する。指定が無ければ軽い群 (--light)。データベースが無くて検査 j を
                                   実行できなければ終了コード 3
  doc-structured impl-diff         検査 j だけを実行し、設計と実装の正規化した形どうしの unified diff と指示の行を
                                   出力する。何も変えない。差分があれば終了コード 1、データベースが無ければ終了コード 3
  doc-structured impl-diff-resolve --list
                                   検査 j の差分の件を、1 行に 1 件「<ID> | 使えるフラグ | メッセージ」の形で、解消する順に出力する
  doc-structured impl-diff-resolve <ID> --planned|--unplanned|--match-impl [--file <パス>]
                                   [--definition <ID> <文>]... [--model <テーブルの ID> <モデルの ID>]...
                                   [--attribute <テーブルかカラムの ID> <属性の ID>]...
                                   差分の 1 件を、YAML を書き換えて解消する。解消できなければ何も書き換えずに終了コード 1、
                                   データベースが無ければ終了コード 3
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
from .config import CONFIG_RELATIVE_PATH, Config, ConfigError, find_config, load_config
from .documents import load_documents
from .domains import load_project
from .impl_diff import UNAVAILABLE_EXIT_CODE, ImplementationUnavailable
from . import impl_resolve
from .generate import (
    HANDWRITTEN_MESSAGE,
    SCHEMA_ACTUAL_PATH,
    HandwrittenFilesError,
    handwritten_fix,
    kept_paths,
    render_project,
    write_outputs,
)
from .links_fix import Choice, ChoiceError, fix_files
from .names import IdError
from .refs import find_refs
from .schema_actual import MigrationError, read_schema
from .schema_diff import render_schema_actual

VERSION_TEXT = f"doc-structured {__version__}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-structured",
        description="アプリケーションの文書の構成の、生成と検査のツール",
    )
    parser.add_argument("--version", action="version", version=VERSION_TEXT)
    subparsers = parser.add_subparsers(dest="command", metavar="<サブコマンド>", required=True)
    subparsers.add_parser("version", help="ツールのバージョンを表示する")
    generate_parser = subparsers.add_parser("generate", help="ドメインの YAML から、人が読む Markdown を生成する")
    generate_parser.add_argument(
        "--all", action="store_true",
        help="設定に database.schema_actual: true があれば、実際のスキーマの docs/system/schema-actual.md も生成し直す",
    )
    check_parser = subparsers.add_parser("check", help="検査を実行する。指定が無ければ軽い群 (--light)")
    group = check_parser.add_mutually_exclusive_group()
    group.add_argument("--light", action="store_true", help=f"軽い群の検査 ({'・'.join(check.LIGHT)}) を実行する")
    group.add_argument("--heavy", action="store_true", help=f"重い群の検査 ({'・'.join(check.HEAVY)}) を実行する")
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
    subparsers.add_parser(
        "impl-diff",
        help="検査 j だけを実行し、設計と実装の差分 (unified diff) と指示の行を出力する。何も変えない",
    )
    resolve_parser = subparsers.add_parser(
        "impl-diff-resolve", help="検査 j の差分の 1 件を、YAML を書き換えて解消する。--list で件の一覧を出力する"
    )
    resolve_parser.set_defaults(subparser=resolve_parser)
    resolve_parser.add_argument("id", nargs="?", metavar="<ID>", help="解消する件の ID (--list が出力する ID)")
    flags = resolve_parser.add_mutually_exclusive_group()
    flags.add_argument("--list", action="store_true", help="件の一覧を、解消する順に出力する")
    flags.add_argument("--planned", dest="flag", action="store_const", const=impl_resolve.PLANNED, help="planned: true を付ける")
    flags.add_argument("--unplanned", dest="flag", action="store_const", const=impl_resolve.UNPLANNED, help="planned を外す")
    flags.add_argument(
        "--match-impl", dest="flag", action="store_const", const=impl_resolve.MATCH_IMPL, help="YAML を実装に合わせる"
    )
    resolve_parser.add_argument(
        "--file", metavar="<パス>", help="実装にだけあるテーブルを足す YAML (省けばドメインのディレクトリの直下の schema.yaml)"
    )
    resolve_parser.add_argument(
        "--definition", nargs=2, action="append", default=[], metavar=("<ID>", "<文>"), help="足すテーブルかカラムの定義の文"
    )
    resolve_parser.add_argument(
        "--model", nargs=2, action="append", default=[], metavar=("<テーブルの ID>", "<モデルの ID>"),
        help="足すテーブルに対応するモデル",
    )
    resolve_parser.add_argument(
        "--attribute", nargs=2, action="append", default=[], metavar=("<テーブルかカラムの ID>", "<属性の ID>"),
        help="足すテーブル (中間テーブル) かカラムに対応する属性",
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
    result = check.run_checks(config.root, checks, config)
    for problem in result.problems:
        print(problem.format())
    for note in result.notes:
        print(note)
    names = "・".join(checks)
    if result.skipped:
        print(f"YAML に誤りがあるので、検査 {'・'.join(result.skipped)} を実行しなかった (誤りは検査 h で確認する)")
    if result.unavailable is not None:
        print(f"doc-structured: 検査 j を実行できない: {result.unavailable}", file=sys.stderr)
        if result.problems:
            print(f"検査 {names}: 問題が {len(result.problems)} 件あった")
        print(f"検査 {names}: 検査 j を実行できなかった")
        return UNAVAILABLE_EXIT_CODE
    if result.ok:
        print(f"検査 {names}: 問題は無かった")
        return 0
    if result.problems:
        print(f"検査 {names}: 問題が {len(result.problems)} 件あった")
    else:
        print(f"検査 {names}: 実行できなかった検査がある")
    return 1


def run_generate(config: Config, args: argparse.Namespace) -> int:
    project, problems = load_project(config.root)
    if problems:
        for problem in problems:
            print(problem.format(), file=sys.stderr)
        print(f"doc-structured: YAML に {len(problems)} 件の誤りがあるので、何も生成しなかった", file=sys.stderr)
        return 1
    kept = kept_paths(config.database)
    outputs = render_project(project, kept)
    if args.all and kept:
        # docs/system/schema-actual.md も生成し直す (決めた経緯は Issue #207 のコメントの 10)
        database = config.database
        try:
            outputs[SCHEMA_ACTUAL_PATH] = render_schema_actual(read_schema(config.root, database), database)
        except ImplementationUnavailable as e:
            print(f"doc-structured: 実際のスキーマを読めないので、何も生成しなかった: {e}", file=sys.stderr)
            return UNAVAILABLE_EXIT_CODE
        except MigrationError as e:
            where = e.path or CONFIG_RELATIVE_PATH.as_posix()
            print(f"{where}: {e}", file=sys.stderr)
            print("doc-structured: マイグレーションを適用できないので、何も生成しなかった", file=sys.stderr)
            return 1
        kept = ()
    try:
        written, deleted = write_outputs(config.root, outputs, kept)
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


def run_impl_diff(config: Config) -> int:
    project, problems = load_project(config.root)
    if problems:
        for problem in problems:
            print(problem.format(), file=sys.stderr)
        print(f"doc-structured: YAML に {len(problems)} 件の誤りがあるので、設計と実装を比べなかった", file=sys.stderr)
        return 1
    try:
        result = check.implementation_diff(config, project)
    except ImplementationUnavailable as e:
        print(f"doc-structured: 設計と実装を比べられない: {e}", file=sys.stderr)
        return UNAVAILABLE_EXIT_CODE
    if result.diff:
        print(result.diff, end="")
    for problem in result.problems:
        print(problem.format())
    if result.problems:
        print(f"検査 j: 問題が {len(result.problems)} 件あった")
        return 1
    if result.diff:
        return 1
    print("設計と実装に差分は無かった")
    return 0


def run_impl_diff_resolve(config: Config, args: argparse.Namespace) -> int:
    parser = args.subparser
    if args.list:
        if args.id is not None or args.file or args.definition or args.model or args.attribute:
            parser.error("--list には、ID とほかのオプションを付けられない")
    elif args.id is None or args.flag is None:
        parser.error("解消する件の ID と、--planned・--unplanned・--match-impl のどれか 1 つを指定する (件の一覧は --list)")
    project, problems = load_project(config.root)
    if problems:
        for problem in problems:
            print(problem.format(), file=sys.stderr)
        print(f"doc-structured: YAML に {len(problems)} 件の誤りがあるので、設計と実装を比べなかった", file=sys.stderr)
        return 1
    database = config.database
    if database is None:
        print(
            f"{CONFIG_RELATIVE_PATH.as_posix()}: 設定に paths.migrations と database が無いので、設計と実装を比べられない。"
            "設定に paths.migrations と database を書く",
            file=sys.stderr,
        )
        return 1
    try:
        actual = read_schema(config.root, database)
    except ImplementationUnavailable as e:
        print(f"doc-structured: 設計と実装を比べられない: {e}", file=sys.stderr)
        return UNAVAILABLE_EXIT_CODE
    except MigrationError as e:
        where = e.path or CONFIG_RELATIVE_PATH.as_posix()
        print(f"{where}: {e}", file=sys.stderr)
        print("doc-structured: マイグレーションを適用できないので、設計と実装を比べなかった", file=sys.stderr)
        return 1
    if args.list:
        cases = impl_resolve.list_cases(project, actual)
        for case in cases:
            print(case.line())
        if not cases:
            print("解消する差分は無かった")
        return 0
    request = impl_resolve.Request(
        args.id, args.flag, args.file,
        [tuple(pair) for pair in args.definition], [tuple(pair) for pair in args.model],
        [tuple(pair) for pair in args.attribute],
    )
    try:
        result = impl_resolve.resolve(config.root, project, actual, request)
    except impl_resolve.ResolveError as e:
        for line in e.lines:
            print(line, file=sys.stderr)
        print("doc-structured: 何も書き換えなかった", file=sys.stderr)
        return 1
    for line in result.lines():
        print(line)
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
        return run_generate(config, args)
    if args.command == "check":
        return run_check(config, args)
    if args.command == "links-fix":
        return run_links_fix(config, args)
    if args.command == "refs":
        return run_refs(config, args)
    if args.command == "impl-diff":
        return run_impl_diff(config)
    if args.command == "impl-diff-resolve":
        return run_impl_diff_resolve(config, args)
    # argparse が知らないサブコマンドを拒否するので、ここには来ない
    raise AssertionError(f"知らないサブコマンド: {args.command} (設定: {config.path})")
