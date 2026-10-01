#!/usr/bin/env python3
"""wording-guard の CLI。スキル (SKILL.md) と人間が呼ぶ。

サブコマンド:
  terms   設定キー terms_paths が指す用語ファイルを読み、様式を検査して、まとめた内容を出力する
  setup   textlint と規則集を、同梱の版で利用者のキャッシュに入れる (npm でパッケージを取得する)
  check   Markdown のファイル (または標準入力の文章) を、用語ファイルと規則集で検査する
  fix     自動修正してよい避ける語 (autofix = true) だけを、ファイルに適用する

check と fix は、設定キー textlint があるリポジトリでだけ実行できる。振る舞いと終了コードの意味の
正本はファイル `wording-guard/skills/wording-guard/references/textlint.md` (終了コードは「コマンド」の表)。
ここでは言い直さない。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wordingguard import config, terms, textlint  # noqa: E402

EXIT_OK = 0
EXIT_FOUND = 1
EXIT_CONFIG = 2
EXIT_TEXTLINT = 3


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


def cmd_setup(args):
    textlint.setup()
    return EXIT_OK


def _textlint_context(args):
    root = _root(args)
    cfg = config.load(root)
    if config.textlint_settings(cfg) is None:
        raise config.ConfigError(f"textlint は設定されていない (設定ファイル {config.CONFIG_RELPATH} にキー textlint が無い)")
    return root, cfg, terms.load_all(config.terms_paths(root, cfg))


def _markdown_files(root, cfg, paths):
    """引数のパス (ファイルかディレクトリ) から、検査する Markdown のファイルを集める。

    (検査するファイル, 書き換えない過去の記録として除いたファイル) を返す。
    ディレクトリからは Markdown だけを集める。明示的に指定したファイルが Markdown でなければ、
    存在しないパスと同じく誤りにする — 知らせずに除くと「検査したもの 0 個」で成功に見えるため。
    """
    files, skipped = [], []
    for p in paths:
        if os.path.isdir(p):
            found = sorted(os.path.join(d, n) for d, _, names in os.walk(p) for n in names if n.endswith(".md"))
        elif os.path.isfile(p):
            if not p.endswith(".md"):
                raise config.ConfigError(f"{p} は Markdown (.md) でない。検査と自動修正の対象は Markdown だけ")
            found = [p]
        else:
            raise config.ConfigError(f"{p} が無い")
        for f in found:
            (skipped if config.is_frozen(root, cfg, f) else files).append(f)
    return files, skipped


def _print_findings(label, findings):
    for f in findings:
        head, _, detail = f["message"].partition("\n")
        matched = f"「{f['matched']}」 " if f["matched"] else ""
        detail = f" — {detail.strip()}" if detail.strip() else ""
        print(f"{label}:{f['line']}:{f['column']} {f['severity']} {matched}{head}{detail} [{f['rule']}]")


def cmd_check(args):
    root, cfg, term_list = _textlint_context(args)
    if args.stdin:
        if args.paths:
            raise config.ConfigError("--stdin とファイルの指定は同時に使えない")
        results = {args.filename: textlint.check_texts(root, cfg, term_list, [sys.stdin.read()],
                                                        filename=args.filename)[0]}
        skipped = []
    else:
        if not args.paths:
            raise config.ConfigError("検査するファイルかディレクトリを指定する (標準入力の文章なら --stdin)")
        files, skipped = _markdown_files(root, cfg, args.paths)
        results = textlint.check_files(root, cfg, term_list, files)
    counts = {"error": 0, "warning": 0, "info": 0}
    for findings in results.values():
        for f in findings:
            counts[f["severity"]] += 1
    if args.format == "json":
        print(json.dumps({"files": results, "skipped": skipped, "counts": counts}, ensure_ascii=False, indent=2))
    else:
        for path, findings in results.items():
            label = os.path.relpath(path, root) if os.path.isabs(path) else path
            _print_findings(label, findings)
        print(f"error {counts['error']} 件・warning {counts['warning']} 件 (検査したもの {len(results)} 個)")
        if skipped:
            print("書き換えない過去の記録 (設定キー frozen_paths) として除いたファイル: "
                  + ", ".join(os.path.relpath(p, root) for p in skipped))
    return EXIT_FOUND if counts["error"] else EXIT_OK


def cmd_fix(args):
    root, cfg, term_list = _textlint_context(args)
    files, skipped = _markdown_files(root, cfg, args.paths)
    applied = textlint.fix_files(root, cfg, term_list, files)
    total = 0
    for path, n in applied.items():
        if n:
            print(f"{os.path.relpath(path, root)}: {n} 件を直した")
        total += n
    print(f"自動修正してよい避ける語を {total} 件直した (検査したファイル {len(files)} 個)")
    if skipped:
        print("書き換えない過去の記録 (設定キー frozen_paths) として除いたファイル: "
              + ", ".join(os.path.relpath(p, root) for p in skipped))
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="wording_lint.py", description="wording-guard の CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("terms", help="用語ファイルを読み、様式を検査して、まとめた内容を出力する")
    p.add_argument("--root", help="リポジトリのルート (省略時はカレントディレクトリを含む git リポジトリのルート)")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_terms)

    p = sub.add_parser("setup", help="textlint と規則集を、同梱の版で利用者のキャッシュに入れる")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("check", help="Markdown を用語ファイルと規則集で検査する")
    p.add_argument("paths", nargs="*", help="検査するファイルかディレクトリ")
    p.add_argument("--root", help="リポジトリのルート (省略時はカレントディレクトリを含む git リポジトリのルート)")
    p.add_argument("--stdin", action="store_true", help="標準入力の文章を検査する")
    p.add_argument("--filename", default="stdin.md", help="--stdin のときの名前。拡張子で文章の形式が決まる")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("fix", help="自動修正してよい避ける語 (autofix = true) だけをファイルに適用する")
    p.add_argument("paths", nargs="+", help="直すファイルかディレクトリ")
    p.add_argument("--root", help="リポジトリのルート (省略時はカレントディレクトリを含む git リポジトリのルート)")
    p.set_defaults(func=cmd_fix)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (config.ConfigError, terms.TermsError) as e:
        print(f"wording_lint.py: {e}", file=sys.stderr)
        return EXIT_CONFIG
    except textlint.TextlintError as e:
        print(f"wording_lint.py: {e}", file=sys.stderr)
        return EXIT_TEXTLINT


if __name__ == "__main__":
    sys.exit(main())
