#!/usr/bin/env python3
"""wording-guard の CLI。スキル (SKILL.md) と人間が呼ぶ。

サブコマンド:
  terms   設定キー terms_paths が指す用語ファイルを読み、様式を検査して、まとめた内容を出力する

終了コード:
  0  成功
  2  設定ファイル・用語ファイルの誤り、または git リポジトリの外で --root を付けずに実行した
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wordingguard import config, terms  # noqa: E402

EXIT_OK = 0
EXIT_CONFIG = 2


def _root(args):
    root = args.root or config.find_root(os.getcwd())
    if root is None:
        raise config.ConfigError("git リポジトリの中で実行するか、--root でリポジトリのルートを指定する")
    return os.path.abspath(root)


def cmd_terms(args):
    root = _root(args)
    cfg = config.load(root)
    paths = config.terms_paths(root, cfg)
    if not paths:
        if args.format == "json":
            print(json.dumps({"configured": False, "terms_paths": [], "terms": []}, ensure_ascii=False))
        else:
            print("用語ファイルは設定されていない (設定キー terms_paths が無い)")
        return EXIT_OK
    loaded = terms.load_all(paths)
    if args.format == "json":
        print(json.dumps({"configured": True, "terms_paths": paths,
                          "terms": [t.to_dict() for t in loaded]}, ensure_ascii=False, indent=2))
        return EXIT_OK
    print("用語ファイル: " + ", ".join(os.path.relpath(p, root) if p.startswith(root) else p for p in paths))
    avoid = [t for t in loaded if t.verdict == "avoid"]
    allow = [t for t in loaded if t.verdict == "allow"]
    print(f"\n避ける語 ({len(avoid)} 件)")
    for t in avoid:
        how = "自動修正してよい" if t.autofix else "自動修正しない"
        print(f"- {t.pattern} → {' / '.join(t.replacements)} ({how})")
        print(f"  理由: {t.reason}")
        print(f"  決めた場所: {t.decided_in}")
        if t.exceptions:
            print(f"  例外: {' / '.join(t.exceptions)}")
    print(f"\n許容する語 ({len(allow)} 件)")
    for t in allow:
        print(f"- {t.pattern}")
        print(f"  理由: {t.reason}")
        print(f"  決めた場所: {t.decided_in}")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="wording_lint.py", description="wording-guard の CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("terms", help="用語ファイルを読み、様式を検査して、まとめた内容を出力する")
    p.add_argument("--root", help="リポジトリのルート (省略時はカレントディレクトリを含む git リポジトリのルート)")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_terms)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (config.ConfigError, terms.TermsError) as e:
        print(f"wording_lint.py: {e}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
