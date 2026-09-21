#!/usr/bin/env python3
"""プロンプトが引き継ぎ文を指しているときに、スキル handoff-resume の実行を促す
UserPromptSubmit フック（session-handoff プラグイン）。

スキル handoff-write は最後に `/handoff-resume <保存先>` という 1 行を出すので、
それを貼れば確実に再開できる。このフックは、保存先 (コメントの URL やファイルのパス)
だけを貼った場合の補助で、引き継ぎ文だと確かめられたときに限り、スキルの実行を促す
文脈を差し込む。

方針:
  - 候補の抽出は正規表現だけで行う。候補が無い通常のプロンプトでは、ファイルも
    ネットワークも触らずに終わる。
  - 引き継ぎ文かどうかは、本文の 1 行目の目印で確かめる。URL やファイル名の形だけでは
    判定しない（コメントの URL は、見ただけでは引き継ぎ文かどうか分からない）。
  - 差し込むのは保存先と実行の指示だけで、引き継ぎ文の本文は差し込まない。本文の取得と、
    投稿者が本人かどうかの確認は、スキルの手順が担う。
  - ブロックしない。gh が無い・未認証・タイムアウト・想定外の失敗では、何も出力せず
    終了コード 0 で終わる。プロンプトは通常どおり処理される。
"""

import json
import os
import re
import subprocess
import sys

MARKER = "<!-- session-handoff v1 -->"

# 1 つのプロンプトで確かめる候補の上限。URL の確認は gh を呼ぶので、数を抑える。
_MAX_CANDIDATES = 3

# フック全体のタイムアウト (hooks.json の 10 秒) に収まるように、gh の 1 回あたりを短くする。
_GH_TIMEOUT_SEC = 3

_URL_RE = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(?:pull|issues)/\d+"
    r"#issuecomment-(\d+)"
)

# handoff-write が付けるファイル名の形: handoff-<YYYYMMDD>-<hhmm>-<ブランチ名>.md
_PATH_RE = re.compile(r"[^\s\"'`<>()]*handoff-\d{8}-\d{4}-[^\s\"'`<>()/]*\.md")

# スキルを直接呼んでいるプロンプト。プラグイン名を前に付けた形も含む。
_ALREADY_INVOKED_RE = re.compile(r"^\s*/(?:[A-Za-z0-9_-]+:)?handoff-resume\b")


def find_candidates(prompt):
    """プロンプトから、引き継ぎ文の候補を出現順に取り出す。

    返り値は ("url", 表記, owner, repo, comment_id) か ("path", 表記) のタプルのリスト。
    """
    found = []
    for m in _URL_RE.finditer(prompt):
        found.append((m.start(), ("url", m.group(0), m.group(1), m.group(2), m.group(3))))
    for m in _PATH_RE.finditer(prompt):
        found.append((m.start(), ("path", m.group(0))))
    found.sort(key=lambda pair: pair[0])

    seen, out = set(), []
    for _, cand in found:
        if cand[1] in seen:
            continue
        seen.add(cand[1])
        out.append(cand)
    return out[:_MAX_CANDIDATES]


def _starts_with_marker(text):
    return (text or "").lstrip("﻿").lstrip().startswith(MARKER)


def file_is_handoff(path, cwd):
    """ローカルファイルの 1 行目が目印なら、絶対パスを返す。違えば None。"""
    full = os.path.expanduser(path)
    if not os.path.isabs(full):
        full = os.path.join(cwd, full)
    try:
        with open(full, encoding="utf-8") as f:
            head = f.read(len(MARKER) + 16)
    except (OSError, UnicodeDecodeError):
        return None
    return os.path.abspath(full) if _starts_with_marker(head) else None


def comment_is_handoff(owner, repo, comment_id, cwd):
    """GitHub のコメントの本文が目印で始まるかを gh で確かめる。確かめられなければ False。"""
    try:
        r = subprocess.run(
            [
                "gh",
                "api",
                "repos/" + owner + "/" + repo + "/issues/comments/" + comment_id,
                "--jq",
                ".body",
            ],
            capture_output=True,
            text=True,
            cwd=cwd or None,
            timeout=_GH_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        # gh が PATH に無い、タイムアウトなど。プロンプトの処理は妨げない。
        return False
    if r.returncode != 0:
        return False
    return _starts_with_marker(r.stdout)


def resolve(candidates, cwd):
    """候補のうち、引き継ぎ文だと確かめられた最初のものの保存先を返す。無ければ None。"""
    for cand in candidates:
        if cand[0] == "path":
            full = file_is_handoff(cand[1], cwd)
            if full:
                return full
        elif comment_is_handoff(cand[2], cand[3], cand[4], cwd):
            return cand[1]
    return None


def build_context(location):
    return "\n".join(
        [
            "## このプロンプトは引き継ぎ文を指しています（session-handoff）",
            "",
            "次の保存先は、スキル handoff-write が書いた引き継ぎ文です"
            "（本文の 1 行目の目印で確認済み）。",
            "",
            "- " + location,
            "",
            "プロンプトが別の用途を明示していない限り、"
            "**スキル handoff-resume を、この保存先を引数にして実行してください。**",
            "引き継ぎ文の本文は、スキルの手順に従って取得します"
            "（このフックは本文を差し込んでいません）。",
        ]
    )


def main():
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        prompt = (data or {}).get("prompt") or ""
        if not isinstance(prompt, str) or _ALREADY_INVOKED_RE.match(prompt):
            return 0
        candidates = find_candidates(prompt)
        if not candidates:
            return 0
        cwd = (data or {}).get("cwd") or os.getcwd()
        location = resolve(candidates, cwd)
        if not location:
            return 0
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": build_context(location),
            }
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
