#!/usr/bin/env python3
"""計画・タスク作成の直後にコミット境界を意識させる PostToolUse フック（commit-rules-guard プラグイン）。

同梱の 3 フックはいずれも**ターンの境界か、コミットの瞬間**でしか介入できない。

  - SessionStart / UserPromptSubmit … ターンの境界。長い自律ターンの中では発火しない
  - PreToolUse (guard-commit-rules) … `git commit` の瞬間。**遅すぎる**

最後の点が本フックの動機である。`git commit` で止めたときには、既に全部の変更を
書き終えている。そこから動機ごとに分けるには `git reset` で作業をやり直す必要があり、
モデルから見ると「合図（Rules-Checked）を付けて通す」ほうが自然に見えてしまう。
実運用でも、5 回連続で合図だけ付けて通した記録がある（Issue #7 のコメント）。

そこで本フックは**実行に入る前**、計画やタスクリストを作った直後に一度だけ、
「コミット境界を計画に織り込む」よう促す。分割が容易なうちに意識づけするのが狙い。

方針:
  - **同じセッションでは一度だけ**注入する。TodoWrite はステータス更新のたびに
    呼ばれるため、素朴に実装すると数分おきに同じ文言が出てノイズになり、
    「慣れ（無視）」を招く。それは注入そのものを無力化する。
  - 内容が**実質的に変わったとき**は再度注入してよい。計画が作り直された場合は
    境界の再検討が要るため。タスクの状態遷移（in_progress → completed）だけの
    変化は「実質的な変化」に含めない。
  - リポジトリ外では何もしない。コミットの話が無関係なため。
  - 想定外で落ちても本体を止めない（return 0）。

状態の持ち方:
  セッションごとに一時ディレクトリへマーカーを置く。プロセスが分かれるフックでは
  メモリに持てないため。`session_id` が取れない環境では注入を 1 回に留める
  （毎回注入するよりノイズが少ない側に倒す）。

環境変数:
  - COMMIT_GUARD_STATE_DIR: マーカーの置き場所。既定は tempfile.gettempdir()。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

# 対象ツール。環境によって計画・タスク系のツール名が違うため複数を並べる。
# hooks.json の matcher でも絞るが、matcher の書式差に依存しないようここでも確認する。
_PLANNING_TOOLS = {
    "ExitPlanMode",
    "TodoWrite",
    "TaskCreate",
    "TaskUpdate",
}

# 計画の内容を表すとみなすキー。ツールごとに名前が違う。
_PLAN_KEYS = ("todos", "plan", "tasks", "prompt", "description")


def _state_dir():
    base = os.environ.get("COMMIT_GUARD_STATE_DIR") or tempfile.gettempdir()
    return os.path.join(base, "commit-rules-guard")


def _marker_path(session_id, digest):
    """このセッション・この計画内容に対する注入済みマーカー。

    内容のダイジェストを名前に含めるため、計画が作り直されれば別のマーカーになり、
    再度注入される。状態遷移だけの更新では digest が変わらず、注入されない。
    """
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:64]
    return os.path.join(_state_dir(), (safe or "nosession") + "-" + digest + ".seen")


def _already_notified(path):
    return os.path.exists(path)


def _mark(path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
    except OSError:
        # マーカーを置けなくても注入自体は成立する（次回また出るだけ）。
        pass


def plan_digest(tool_input):
    """計画の「実質的な内容」のダイジェストを返す。

    タスクの状態（status / activeForm 等）は除く。in_progress → completed の
    遷移のたびに注入すると、同じ文言が数分おきに出てノイズになるため。
    内容が空なら None（注入しない）。
    """
    if not isinstance(tool_input, dict):
        return None

    parts = []
    for key in _PLAN_KEYS:
        value = tool_input.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    # タスク1件。状態ではなく「何をするか」だけを見る。
                    for k in ("content", "title", "task", "description"):
                        v = item.get(k)
                        if isinstance(v, str) and v.strip():
                            parts.append(v.strip())
                            break
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _in_git_repo(cwd):
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=cwd or None,
        )
    except OSError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def build_message():
    lines = []
    lines.append("コミット境界の計画（commit-rules-guard）")
    lines.append("")
    lines.append("これから実行する計画に、**コミットするタイミングを織り込んでください。**")
    lines.append("")
    lines.append("- 動機（機能の追加/変更/削除・問題の修正・linter の指摘対応・")
    lines.append("  リファクタリング・ツールによる自動生成）が切り替わる箇所が"
                 "コミット境界です。")
    lines.append("- 各タスクの完了条件に「コミット済みであること」を含めてください。")
    lines.append("- **分割は後からできません。** 全部書き終えてから分けようとすると、")
    lines.append("  作業のやり直しになります。")
    lines.append("")
    lines.append("この確認は同じ計画に対して一度だけ出ます。")
    return "\n".join(lines)


def main():
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        data = data or {}

        if data.get("tool_name") not in _PLANNING_TOOLS:
            return 0

        digest = plan_digest(data.get("tool_input"))
        if digest is None:
            # 中身の無い呼び出し（状態更新のみ等）。促す対象が無い。
            return 0

        cwd = data.get("cwd") or os.getcwd()
        if not _in_git_repo(cwd):
            return 0

        marker = _marker_path(data.get("session_id"), digest)
        if _already_notified(marker):
            return 0
        _mark(marker)

        # PostToolUse ではツールは既に実行済み。exit 2 は「取り消し」ではなく
        # 「実行後のフィードバック」として Claude に届く。
        sys.stderr.write(build_message() + "\n")
        return 2
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
