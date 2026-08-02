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
  - **1 セッションにつき 1 回だけ**注入する。何度も出すとノイズになり、
    「慣れ（無視）」を招く。それは注入そのものを無力化する。
  - 判定に**計画の内容を使わない。** 当初は「計画の内容が変わったら再度促す」
    設計にしていたが、これは実環境で破綻していた。TaskCreate は
    **1 呼び出しで 1 タスク**を作るため、6 タスクの計画では 6 回発火する
    （実測で確認）。タスクを 1 件足す・削る・並べ替えるだけでも再発火していた。
    内容ベースの判定は「同じ計画かどうか」を表現できない。
  - リポジトリ外では何もしない。コミットの話が無関係なため。
  - **状態を保存できない環境では、間引きを諦めて通知する側に倒す。** 黙ると
    フックが永久に無言になり、しかもそれを利用者が知る手段が無い（正常な間引きと
    区別できない）。静かに死んだガードより、数回多く鳴るほうが良い。
  - 想定外で落ちても本体を止めない（return 0）。

再度促さないことの割り切り:
  計画を作り直したときも 2 回目は出ない。促す機会は減るが、鳴りすぎて無視される
  ほうが失敗として重い。セッションの入口では SessionStart フックが、コミットの
  瞬間には PreToolUse ガードが別途効く。

  **コンテキスト圧縮 (compact) でも再武装しない**（既知の割り切り）。圧縮すると
  Claude の記憶は要約に置き換わるが、session_id は変わらないためマーカーが残り、
  以後このフックは黙り続ける。長い自律セッションほど圧縮が起きやすく、つまり
  本フックが最も要る場面で効かないという構造になっている。

  同梱の SessionStart フックは matcher に compact を含めており、「圧縮はルールの
  存在感が薄れる瞬間」と判断している。本フックをそこに合わせて再武装させることも
  できるが、フック間に依存が生まれるため今回は採らない。圧縮直後は SessionStart
  フックがルール全文を再注入するので、コミットルール自体は想起される。

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
# TaskCreate/TaskUpdate は subject・description を平らな dict で送る。
_PLAN_KEYS = ("todos", "plan", "tasks", "subject", "prompt", "description")

# タスク 1 件の中で「何をするか」を表すキー。状態（status / activeForm）は見ない。
_TASK_KEYS = ("content", "subject", "title", "task", "description")

# git の判定を打ち切るまでの秒数。hooks.json の全体上限より短くする。
_GIT_TIMEOUT = 5



def _state_dir():
    base = os.environ.get("COMMIT_GUARD_STATE_DIR") or tempfile.gettempdir()
    return os.path.join(base, "commit-rules-guard")


def _marker_path(session_id):
    """このセッションの注入済みマーカー。

    **計画の内容は名前に含めない。** 内容ごとに分けると、TaskCreate のように
    1 呼び出しで 1 タスクを作るツールでタスク数だけ発火する。

    セッション ID は**読みやすい部分＋ハッシュ**にする。記号を落とすだけだと
    `abc/def` と `abcdef` が同じ名前になり、別セッションの通知を打ち消しうる
    （64 文字で切る処理でも同じことが起きる）。一意性はハッシュが担う。
    """
    raw = str(session_id) if session_id else ""
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    readable = "".join(c for c in raw if c.isalnum() or c in "-_")[:32]
    stem = (readable + "-" + fingerprint) if readable else ("nosession-" + fingerprint)
    return os.path.join(_state_dir(), stem + ".seen")


def claim(path):
    """このマーカーを自分のものにできたら True。既に在れば False。

    存在確認と作成を **1 つの原子的な操作**にする。`os.path.exists` で見てから
    `open` すると、その隙間に別プロセスが入り、同じセッションで複数回通知が出る
    （並列に 4 回呼ぶと 3〜4 回発火することを確認済み）。

    **「既に在る」と「置けない」を区別する。**

    - 既に在る（FileExistsError）… 正常な間引き。黙る。
    - 置けない（他の OSError。読み取り専用・容量不足・権限等）… 状態を保存
      できない環境。**通知する側に倒す。**

    後者で黙ると、環境が壊れている間フックは永久に無言になる。しかも利用者にも
    Claude にも signal が無く、「正しく間引かれている」と区別できない。静かに
    死んだガードより、セッションに数回多く鳴るほうが良い。
    """
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        # O_EXCL: 既に在れば FileExistsError。作成できた側だけが通知する。
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        # 保存できない。間引けないが、黙って死ぬよりは鳴らす。
        return True
    os.close(fd)
    return True


def has_plan_content(tool_input):
    """促す対象になる中身があるか。

    状態だけを更新する呼び出し（TaskUpdate の {task_id, status} 等）では False。
    促す対象が無いのに鳴らさないため。

    **内容の同一性は判定しない。** 以前は内容のハッシュで「同じ計画か」を判定して
    いたが、TaskCreate が 1 呼び出しで 1 タスクを作るため、タスクごとに別の計画と
    見なされて発火していた。いまはセッション単位で数えるので、ここは「中身がある
    か」だけを見ればよい。

    ただし**平らな dict に status が付いていれば状態更新**とみなす。TaskUpdate は
    {subject, status} のように、どのタスクかを示すために subject を添えて状態だけを
    変える。これを「中身あり」と数えると、セッションに 1 回しかない通知を状態更新で
    使い切り、**その後に来る本当の計画で促せなくなる**（促す機会を最も要らない
    タイミングで消費する）。
    """
    if not isinstance(tool_input, dict):
        return False

    # 状態遷移のための呼び出し。subject 等は「どのタスクか」の指示でしかない。
    # todos/plan/tasks のような計画そのものを持つ場合は、下のループで拾う。
    if isinstance(tool_input.get("status"), str) and tool_input["status"].strip():
        if not any(k in tool_input for k in ("todos", "plan", "tasks")):
            return False

    for key in _PLAN_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return True
                if isinstance(item, dict):
                    for k in _TASK_KEYS:
                        v = item.get(k)
                        if isinstance(v, str) and v.strip():
                            return True
    return False


def _in_git_repo(cwd):
    # timeout はプロセス側でも持つ。hooks.json の 10 秒はフック全体の上限で、
    # そこで殺されると git の子プロセスが取り残されうる。ネットワーク上の
    # リポジトリや index のロック待ちで固まる経路があるため、自分で打ち切る。
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=cwd or None,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        # 判定できないならリポジトリ外と同じ扱い（黙る）。
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
    lines.append("この確認は 1 セッションにつき一度だけ出ます。")
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

        if not has_plan_content(data.get("tool_input")):
            # 中身の無い呼び出し（状態更新のみ等）。促す対象が無い。
            return 0

        # 通知済みかどうかを先に見る。git の起動はここを通った場合だけにする
        # （状態更新は最も頻度が高く、そのたびにプロセスを起こす必要は無い）。
        marker = _marker_path(data.get("session_id"))
        if os.path.exists(marker):
            return 0

        cwd = data.get("cwd") or os.getcwd()
        if not _in_git_repo(cwd):
            return 0

        # 取得できた側だけが通知する（存在確認と作成は原子的）。
        if not claim(marker):
            return 0

        # PostToolUse ではツールは既に実行済み。exit 2 は「取り消し」ではなく
        # 「実行後のフィードバック」として Claude に届く。
        sys.stderr.write(build_message() + "\n")
        return 2
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
