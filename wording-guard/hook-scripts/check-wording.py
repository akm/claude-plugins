#!/usr/bin/env python3
"""Markdown に書き足した文章を textlint で検査する PostToolUse の hook (wording-guard プラグイン)。

本体はモジュール wordingguard.hook。ここは標準入力の JSON を渡し、結果を標準出力に書くだけ。
想定外の例外で終わったときは、標準エラー出力に書いて終了コード 1 で終わる
(Claude Code は終了コード 0・2 以外を、ツールの実行を止めない誤りとして利用者に見せる)。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))


def main():
    from wordingguard import hook

    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"wording-guard: hook の入力を JSON として読めない: {e}", file=sys.stderr)
        return 1
    output = hook.handle(event)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — 想定外の例外も、利用者に見える形で知らせる
        print(f"wording-guard: hook が想定外の誤りで終わった: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
