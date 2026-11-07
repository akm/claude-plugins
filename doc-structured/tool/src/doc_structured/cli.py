"""コマンド doc-structured の入口。

  doc-structured --version         ツールのバージョンを表示する (設定ファイルは読まない)
  doc-structured version           ツールのバージョンを表示する
  doc-structured <知らない名前>     使い方を標準エラー出力に書き、終了コード 2 で終了する

サブコマンドは、起動時に設定ファイルを読み、形が違えばエラーの文を標準エラー出力に書いて終了コード 1 で終了する。
サブコマンドは sub-issue ごとに足す。
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, find_config, load_config

VERSION_TEXT = f"doc-structured {__version__}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-structured",
        description="アプリケーションの文書の構成の、生成と検査のツール",
    )
    parser.add_argument("--version", action="version", version=VERSION_TEXT)
    subparsers = parser.add_subparsers(dest="command", metavar="<サブコマンド>", required=True)
    subparsers.add_parser("version", help="ツールのバージョンを表示する")
    return parser


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
    # argparse が知らないサブコマンドを拒否するので、ここには来ない
    raise AssertionError(f"知らないサブコマンド: {args.command} (設定: {config.path})")
