"""Issue の参照の正規化。`owner/repo#番号` と URL (`https://github.com/owner/repo/issues/番号`) を同じ正規形
(キー `owner/repo#番号`) にする。宣言の `blocked_by`・記録の項目のキー・`gh issue edit --add-blocked-by` に渡す URL の
変換に使う。リポジトリの名前の形は config.REPO_NAME_PATTERN と同じ (名前に使える文字だけで決める)。
"""

import re

REPO_NAME_PATTERN = r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
_KEY_RE = re.compile(rf"^(?P<repo>{REPO_NAME_PATTERN})#(?P<number>[1-9][0-9]*)$")
_URL_RE = re.compile(rf"^https://github\.com/(?P<repo>{REPO_NAME_PATTERN})/(?P<kind>issues|pull)/(?P<number>[1-9][0-9]*)/?$")


def parse_issue_ref(text):
    """Issue の参照を読む。返り値は {"repo": "owner/name", "number": int, "key", "url"} か、読めなければ None。
    URL は `/issues/<番号>` の形だけ (PR の URL `/pull/<番号>` は Issue の参照ではないので None)。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    m = _KEY_RE.match(text)
    kind = "issues"
    if not m:
        m = _URL_RE.match(text)
        if not m:
            return None
        kind = m.group("kind")
    if kind != "issues":
        return None
    repo, number = m.group("repo"), int(m.group("number"))
    return {"repo": repo, "number": number, "key": f"{repo}#{number}", "url": f"https://github.com/{repo}/issues/{number}"}


def issue_key(text):
    """参照を正規形 `owner/repo#番号` にする。読めなければ None。"""
    parsed = parse_issue_ref(text)
    return parsed["key"] if parsed else None


def issue_url(text):
    """参照を URL にする (`gh issue edit --add-blocked-by` は URL の形だけを受け付ける。U1)。読めなければ None。"""
    parsed = parse_issue_ref(text)
    return parsed["url"] if parsed else None


def same_issue(a, b):
    """2 つの参照が同じ Issue を指すか (リポジトリの名前は大文字小文字を区別しない)。どちらかが読めなければ偽。"""
    pa, pb = parse_issue_ref(a), parse_issue_ref(b)
    return bool(pa and pb and pa["repo"].lower() == pb["repo"].lower() and pa["number"] == pb["number"])
