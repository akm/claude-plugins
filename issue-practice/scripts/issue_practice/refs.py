"""識別子の解析と正規化 (計画の KTD12)。Issue の番号・`owner/repo#N`・Issue と PR とコメントの URL・マイルストーンの名前を、
このモジュールの 1 か所で解析する。ほかのモジュールとスキルは、識別子を文から解釈せず、ここの関数を使う。

解析の関数は、解釈できた値の辞書か、理由の文字列を持つ辞書 (`{"error": <理由>}`) を返す。例外は送出しない。
"""

import re

_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_REPO = r"[A-Za-z0-9._-]+"
_NUMBER = r"[1-9][0-9]*"

_REPO_RE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repo>{_REPO})$")
_SHORT_RE = re.compile(rf"^#?(?P<number>{_NUMBER})$")
_KEY_RE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repo>{_REPO})#(?P<number>{_NUMBER})$")
_URL_RE = re.compile(
    rf"^https://github\.com/(?P<owner>{_OWNER})/(?P<repo>{_REPO})/(?P<path>issues|pull)/(?P<number>{_NUMBER})/?$")
_COMMENT_URL_RE = re.compile(
    rf"^https://github\.com/(?P<owner>{_OWNER})/(?P<repo>{_REPO})/(?P<path>issues|pull)/(?P<number>{_NUMBER})"
    r"#issuecomment-(?P<comment_id>[1-9][0-9]*)$")
_ZERO_RE = re.compile(r"(?:^|[#/])0+$")

# リリースマイルストーンの名前。`R<リリース Issue の番号> (主題)` か、リリース対象があるとき `R<番号> <リリース対象> (主題)`
# (計画の R41)。主題は最後の括弧の中で、括弧を含んでもよい
_MILESTONE_RE = re.compile(rf"^R(?P<number>{_NUMBER})(?: (?P<target>[^\s()]+))? \((?P<subject>.+)\)$")


def parse_repo(text):
    """`owner/repo` を解析する。返り値は {"owner", "repo", "repo_key"} か {"error"}。"""
    text = (text or "").strip()
    m = _REPO_RE.match(text)
    if not m or m.group("repo") in (".", ".."):
        return {"error": f"owner/repo の形ではない: {text!r}"}
    return {"owner": m.group("owner"), "repo": m.group("repo"), "repo_key": f"{m.group('owner')}/{m.group('repo')}"}


def _ref(owner, repo, number, kind, url=None):
    key = f"{owner}/{repo}#{number}" if owner else None
    return {"owner": owner, "repo": repo, "number": number, "kind": kind, "key": key,
            "url": url or (f"https://github.com/{owner}/{repo}/{'pull' if kind == 'pull' else 'issues'}/{number}"
                           if owner else None)}


def parse_ref(text, default_repo=None):
    """Issue か PR の参照を解析する。

    受け付ける形: `12`・`#12` (リポジトリは default_repo)・`owner/repo#12`・`https://github.com/owner/repo/issues/12`・
    `https://github.com/owner/repo/pull/12`。返り値は {"owner", "repo", "number", "kind", "key", "url"} か {"error"}。
    kind は URL から分かるときだけ `issue` か `pull` で、番号だけの形では None (Issue か PR かは GitHub に聞くまで分からない)。
    `12` と `#12` で default_repo が無いときは、owner・repo・key・url を None にして返す (形の検査だけをしたい呼び出し元のため)。
    """
    raw = text
    text = (text or "").strip()
    if not text:
        return {"error": "空の参照"}
    if _ZERO_RE.search(text) or re.search(r"[#/]0[0-9]", text):
        return {"error": f"番号は 1 以上で、先頭に 0 を付けない: {raw!r}"}
    m = _URL_RE.match(text)
    if m:
        if m.group("repo") in (".", ".."):
            return {"error": f"リポジトリの名前ではない: {raw!r}"}
        kind = "pull" if m.group("path") == "pull" else "issue"
        return _ref(m.group("owner"), m.group("repo"), int(m.group("number")), kind)
    m = _KEY_RE.match(text)
    if m:
        if m.group("repo") in (".", ".."):
            return {"error": f"リポジトリの名前ではない: {raw!r}"}
        return _ref(m.group("owner"), m.group("repo"), int(m.group("number")), None)
    m = _SHORT_RE.match(text)
    if m:
        number = int(m.group("number"))
        if default_repo is None:
            return _ref(None, None, number, None)
        repo = parse_repo(default_repo)
        if "error" in repo:
            return {"error": f"リポジトリの指定が {repo['error']}"}
        return _ref(repo["owner"], repo["repo"], number, None)
    if text.startswith("https://"):
        return {"error": f"Issue か PR の URL ではない: {raw!r}"}
    return {"error": f"Issue の参照として解釈できない: {raw!r}"}


def parse_comment_url(text):
    """Issue か PR のコメントの URL (`…/issues/12#issuecomment-345`) を解析する。

    返り値は {"owner", "repo", "number", "kind", "key", "url", "comment_id"} か {"error"}。
    """
    text = (text or "").strip()
    m = _COMMENT_URL_RE.match(text)
    if not m or m.group("repo") in (".", ".."):
        return {"error": f"コメントの URL ではない: {text!r}"}
    kind = "pull" if m.group("path") == "pull" else "issue"
    return {**_ref(m.group("owner"), m.group("repo"), int(m.group("number")), kind, url=text),
            "comment_id": int(m.group("comment_id"))}


def parse_milestone_name(name):
    """リリースマイルストーンの名前を解析する。返り値は {"number", "target", "subject"} か {"error"}。

    target はリリース対象の名前で、名前に無ければ None。
    """
    m = _MILESTONE_RE.match(name or "")
    if not m:
        return {"error": f"リリースマイルストーンの名前 (R<番号> (主題) か R<番号> <リリース対象> (主題)) ではない: {name!r}"}
    subject = m.group("subject").strip()
    if not subject:
        return {"error": f"主題が空: {name!r}"}
    return {"number": int(m.group("number")), "target": m.group("target"), "subject": subject}


def same_issue(a, b):
    """2 つの参照 (parse_ref の結果) が同じ Issue か。owner と repo の大文字と小文字は区別しない (GitHub が区別しないため)。"""
    if not a.get("key") or not b.get("key"):
        return False
    return a["key"].lower() == b["key"].lower()
