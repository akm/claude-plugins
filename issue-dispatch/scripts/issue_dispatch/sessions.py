"""セッションの識別。セッション ID の正規化、環境変数からの自分のセッション ID の決定、管理のセッションの規約の名前の生成と
解析、作業のセッションの一時ディレクトリのパス。gh も ListAgents も使わず、環境変数は引数の辞書で受ける (テストのため)。
宛先の決め方と、公式文書に無い振る舞いへの依存の正本は issue-dispatch/skills/issue-dispatch/references/messaging.md。
"""

import os
import re

from issue_dispatch import ids

NAME_PREFIX = "issue-dispatch "
# 環境変数。CLAUDE_CODE_HOST_SESSION_ID (Desktop のセッション ID。`local_` で始まる) があればそれ、無ければ
# CLAUDE_CODE_SESSION_ID (会話の記録の UUID)。公式文書に無い振る舞いに頼るので、読むのは own_session_id の 1 か所 (KTD10)
ENV_HOST_SESSION_ID = "CLAUDE_CODE_HOST_SESSION_ID"
ENV_SESSION_ID = "CLAUDE_CODE_SESSION_ID"
# `local_` の有無は区別して保持する。中身の形 (UUID など) には決め打ちせず、パスの 1 区切りとして使える値 (空白と `/` を
# 含まず、`.` で始まらない。`.`・`..` は通さない) だけを通す
_ID_RE = re.compile(r"^(?:local_)?[^\s/.][^\s/]*$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9._-]+$")    # ids.REPO_NAME_PATTERN の owner の部分と同じ文字
_LOGIN_RE = _OWNER_RE


def normalize_session_id(text):
    """セッション ID をそろえる (前後の空白を除く)。`local_<ID>` と `<ID>` は別物として保持する。
    空・空白や `/` を含む・`.` で始まる (`.`・`..` を含む)・`local_` だけ、は読めないので None (ID はパスの 1 区切りにも使う)。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or not _ID_RE.match(text) or text == "local_":
        return None
    return text


def same_session_id(a, b):
    """2 つのセッション ID が同じか (`local_` の有無が違えば別)。どちらかが読めなければ偽。"""
    na, nb = normalize_session_id(a), normalize_session_id(b)
    return na is not None and na == nb


def own_session_id(environ):
    """環境変数から自分のセッション ID を決める。返り値は (ID, 読んだ環境変数の名前) か (None, None)。
    CLAUDE_CODE_HOST_SESSION_ID があればそれ (Desktop のセッション。`local_` 付き)、無ければ CLAUDE_CODE_SESSION_ID。
    空の値と形が読めない値は無いものとして扱う。"""
    for name in (ENV_HOST_SESSION_ID, ENV_SESSION_ID):
        value = normalize_session_id(environ.get(name))
        if value is not None:
            return value, name
    return None, None


def manager_name(owner, number=None, login=None):
    """管理のセッションの規約の名前 `issue-dispatch <owner>/<number>/<login>` を作る (KD23)。owner に設定の project
    (dict。owner と number) を渡してもよい。owner と login は小文字にそろえる (GitHub は大文字小文字を区別しないが、名前は
    Claude Code が文字列として照合する宛先なので、設定に書かれた表記が違っても同じ組から同じ名前を導くため)。
    形が違えば ValueError。"""
    if isinstance(owner, dict):
        owner, number = owner.get("owner"), owner.get("number")
    if not isinstance(owner, str) or not _OWNER_RE.match(owner):
        raise ValueError(f"owner は名前に使える文字だけの文字列: {owner!r}")
    if isinstance(number, bool) or not re.fullmatch(r"[1-9][0-9]*", str(number).strip() if number is not None else ""):
        raise ValueError(f"Project の番号は 1 以上の整数: {number!r}")
    if not isinstance(login, str) or not _LOGIN_RE.match(login):
        raise ValueError(f"login は名前に使える文字だけの文字列: {login!r}")
    return f"{NAME_PREFIX}{owner.lower()}/{int(str(number).strip())}/{login.lower()}"


def parse_manager_name(text):
    """規約の名前を読む。返り値は {"owner", "number", "login"} (owner と login は小文字) か、形が違えば None。
    ListAgents の行に付く短い識別子 (`[2c2f42]`) は含まない形で渡す (呼び出し元が外す)。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text.startswith(NAME_PREFIX):
        return None
    parts = text[len(NAME_PREFIX):].split("/")
    if len(parts) != 3:
        return None
    owner, number, login = parts
    try:
        manager_name(owner, number, login)
    except ValueError:
        return None
    return {"owner": owner.lower(), "number": int(number), "login": login.lower()}


def session_temp_dir(session_id, environ):
    """作業のセッションの一時ディレクトリ `${TMPDIR:-/tmp}/issue-dispatch/<セッション ID>/` のパス (末尾の `/` は付けない)。
    作業ツリーの外に置く (待機の wait.pid と、伝えた版を記録するファイルの置き場。KTD6・R26)。TMPDIR は絶対パスのときだけ使う
    (相対パスは作業ツリーの中を指しうる)。セッション ID が読めなければ ValueError。"""
    normalized = normalize_session_id(session_id)
    if normalized is None:
        raise ValueError(f"セッション ID が読めない: {session_id!r}")
    tmpdir = (environ.get("TMPDIR") or "").strip()
    base = tmpdir if tmpdir.startswith("/") else "/tmp"
    return os.path.normpath(os.path.join(base, "issue-dispatch", normalized))
