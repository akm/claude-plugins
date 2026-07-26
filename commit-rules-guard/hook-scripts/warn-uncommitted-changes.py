#!/usr/bin/env python3
"""新しい作業への着手時に未コミットの変更を警告する UserPromptSubmit フック
（commit-rules-guard プラグイン）。

ユーザーのプロンプト送信は「新しい作業への着手」に最も近いシグナル。ここで未コミットの
変更が残っていると、次の作業の変更と動機が混ざり、先の変更が上書きされて失われる。
その損失が起きる直前に事実（未コミットの件数と内訳）だけを提示する。

方針:
  - worktree が clean なら何も注入しない。dirty のときだけ注入するので、
    通常のプロンプトにはコストがかからない。
  - ブロックしない（exit 2 はプロンプト自体を捨ててしまうため使わない）。
    「必ず先にコミットせよ」ではなく「動機が異なるなら先にコミットせよ」という
    判断材料の提示に留める。同じ動機の続きなら、そのまま作業を続けてよい。
  - git が無い・リポジトリ外・想定外の失敗では黙って何もしない（return 0）。
"""

import json
import os
import subprocess
import sys

# 一覧に出す最大件数。これを超えたら残りは件数だけ示す。
_MAX_LISTED = 10


def _git_status(cwd):
    """`git status --porcelain` の行を返す。リポジトリ外・git 無し・失敗なら None。"""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=cwd or None,
        )
    except OSError:
        # git が PATH に無い等。プロンプト処理は妨げない。
        return None
    if r.returncode != 0:
        return None
    return [line for line in r.stdout.splitlines() if line.strip()]


def build_context(lines):
    staged, unstaged, untracked = [], [], []
    for line in lines:
        # porcelain v1: XY<space>path。X=index側, Y=worktree側。
        status, path = line[:2], line[3:]
        if status == "??":
            untracked.append(path)
        else:
            if status[0].strip():
                staged.append(path)
            if status[1].strip():
                unstaged.append(path)

    out = []
    out.append("## 未コミットの変更があります（commit-rules-guard）")
    out.append("")
    out.append(
        "これから着手する作業が、以下の変更とは別の動機であれば、"
        "**先に現在の変更をコミットしてください。**"
    )
    out.append(
        "混ぜて作業を進めると動機が絡み合い、これらの変更が"
        "後続の変更に上書きされて失われます。同じ動機の続きであれば、そのまま進めて構いません。"
    )
    out.append("")
    for label, paths in (
        ("ステージ済み", staged),
        ("未ステージ", unstaged),
        ("未追跡", untracked),
    ):
        if not paths:
            continue
        shown = ", ".join(paths[:_MAX_LISTED])
        if len(paths) > _MAX_LISTED:
            shown += " …ほか " + str(len(paths) - _MAX_LISTED) + " 件"
        out.append("- " + label + " (" + str(len(paths)) + "): " + shown)
    return "\n".join(out)


def main():
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        cwd = (data or {}).get("cwd") or os.getcwd()
        lines = _git_status(cwd)
        if not lines:
            # リポジトリ外、または clean。何も注入しない。
            return 0
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": build_context(lines),
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
