#!/usr/bin/env python3
"""セッション開始時にコミットルールを想起させる SessionStart フック（commit-rules-guard プラグイン）。

同梱の PreToolUse ガード（guard-commit-rules.py）は `git commit` の直前にしか介入できない。
しかし実際に問題になるのは「そもそもコミットしようとしない」ことで、細かくコミットすべき
段階でコミットせずに作業を続けた結果、最終的に複数の動機が絡み合い、コミットされるべき
変更が後続の変更に上書きされて失われる。これは事後（コミット時）には取り返せない。

そこで本フックはセッションの入口でルールの要点を注入し、事前に意識づけする。
PreToolUse ガードが「最後の防衛線」、本フックは「事前の意識づけ」という役割分担。

方針:
  - ルールの全文ではなく「行動指針に翻訳したダイジェスト」を注入する。
    「動機ごとに分ける」だけでは『いつコミットするか』が導けないため、
    「次の動機に着手する前にコミットする。後から分割はできない」という因果まで書く。
  - startup / resume / clear / compact で発火する。特に compact は、圧縮でルールの
    存在感が薄れる瞬間であり、CLAUDE.md 等の静的な設定では再注入できないタイミング。
  - ブロックはしない（注入のみ）。想定外で落ちても本体を止めない（return 0）。

環境変数:
  - COMMIT_GUARD_RULES_FILE: ルールファイルのパス。既定は
    ~/.claude/rules/commit-rules.md → プラグイン同梱の rules/commit-rules.md の順に探す。
    （guard-commit-rules.py と同じ探索順）
"""

import json
import os
import sys


def _rules_file():
    """表示するルールファイルを探す。環境変数 → ユーザーのグローバル → プラグイン同梱の順。

    guard-commit-rules.py の同名関数と同じ優先順位。片方だけ変えると
    「ガードが参照するルール」と「想起させるルール」がずれるため、変更時は両方を合わせる。
    """
    env = os.environ.get("COMMIT_GUARD_RULES_FILE")
    if env and os.path.isfile(os.path.expanduser(env)):
        return os.path.expanduser(env)
    user = os.path.expanduser("~/.claude/rules/commit-rules.md")
    if os.path.isfile(user):
        return user
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        bundled = os.path.join(root, "rules", "commit-rules.md")
        if os.path.isfile(bundled):
            return bundled
    return None


def build_context():
    lines = []
    lines.append("## コミットルール（commit-rules-guard による想起）")
    lines.append("")
    lines.append("コミットは『変更した動機』でグルーピングし、複数の動機を 1 つに混ぜないこと。")
    lines.append("動機の例: 機能の追加/変更/削除・問題の修正・linter の指摘対応・"
                 "リファクタリング・ツールによる自動生成。")
    lines.append("")
    lines.append("**コミットするタイミング:**")
    lines.append("")
    lines.append("- **一つの動機の作業が終わったら、次の動機に着手する前にコミットする。**")
    lines.append("  後からまとめて分割することはできない。作業を続けると、コミットされるべき")
    lines.append("  変更が後続の変更に上書きされて失われる。")
    lines.append("- 指示された作業が複数の動機にまたがるときは、着手前にコミットの単位を計画し、")
    lines.append("  動機の切り替わりごとにコミットする。")
    lines.append("- 動機ごとの分割は、各コミットでテスト・検査がパスすることより優先する。")
    lines.append("  検査は最終的に（push・レビュー時点で）パスすればよい。")
    lines.append("")
    rf = _rules_file()
    if rf:
        lines.append("ルール全文: " + rf)
    return "\n".join(lines)


def main():
    try:
        # stdin は読むが、matcher 側で発火条件を絞っているため source では分岐しない。
        # 不正な JSON でもセッション開始を妨げないよう握りつぶす。
        try:
            json.load(sys.stdin)
        except Exception:
            pass
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": build_context(),
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
