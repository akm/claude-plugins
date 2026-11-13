"""記録のコメントの 1 行目の生成と解析、Issue のコメントの一覧から記録を集めること (計画の KTD4・KTD5)。

形の SSOT は、文書 `issue-practice/references/record-comments.md` とこのモジュールの定数 KINDS・KEYS。
テスト (ファイル `issue-practice/tests/test_docs.py`) が、文書の表と定数が一致することを確認する。

関数は、解析できた値の辞書か、理由の配列を持つ辞書 (`{"errors": [...]}`) を返す。例外は送出しない。
"""

import datetime
import re

from issue_practice import draft, gh, refs

PREFIX = "issue-practice:"

# 種類ごとの必須のキーと任意のキー。where は書く場所 (comment: 記録のコメントの 1 行目、body: 作る Issue の本文の末尾の行)。
# 順序は文書の表の順で、records format はこの順にキーを並べる
KINDS = {
    "session": {"required": ("role", "session"), "optional": ("branch", "previous"), "where": "comment"},
    "approval": {"required": ("draft",), "optional": (), "where": "comment"},
    "plan-change": {"required": (), "optional": ("draft",), "where": "comment"},
    "report": {"required": ("type",), "optional": ("pr",), "where": "comment"},
    "draft-removed": {"required": ("date",), "optional": ("draft",), "where": "comment"},
    "current-swap": {"required": ("date",), "optional": ("old",), "where": "comment"},
    "release-start": {"required": (), "optional": (), "where": "comment"},
    "dependency-resolved": {"required": ("issue",), "optional": (), "where": "comment"},
    "close-check": {"required": ("result",), "optional": (), "where": "comment"},
    "abandon": {"required": ("session",), "optional": (), "where": "comment"},
    "created-from": {"required": ("draft", "key"), "optional": (), "where": "body"},
}

ROLES = ("managing", "working", "self-managing")
REPORT_TYPES = ("pr", "check", "split", "condition-change", "carve-out", "suspend")
RESULTS = ("pass", "fail")

_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_KIND_RE = re.compile(r"^[a-z][a-z-]*$")
_PAIR_RE = re.compile(r"^(?P<key>[a-z][a-z-]*)=(?P<value>.*)$")


def _enum(values):
    def check(value):
        return None if value in values else f"{' / '.join(values)} のどれか"
    return check


def _pattern(regex, description):
    def check(value):
        return None if regex.match(value) else description
    return check


def _branch(value):
    if not _BRANCH_RE.match(value) or ".." in value:
        return "英数字で始まり、英数字・.・_・/・- が続くブランチの名前 (.. を含まない)"
    return None


def _draft(value):
    parsed = draft.parse_file_name(value)
    return parsed["error"] if "error" in parsed else None


def _date(value):
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return "YYYY-MM-DD の日付"
    return None if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", value) else "YYYY-MM-DD の日付"


def _issue(value):
    parsed = refs.parse_ref(value)
    if "error" in parsed or value.startswith("https://") or value.isdigit():
        return "#番号 か owner/repo#番号 の Issue の参照"
    return None


def _pr_url(value):
    parsed = refs.parse_ref(value)
    if "error" in parsed or parsed["kind"] != "pull":
        return "PR の URL (https://github.com/<owner>/<repo>/pull/<番号>)"
    return None


# キーごとの値の検査。値が形どおりなら None、違えば期待する形の説明を返す
KEYS = {
    "role": _enum(ROLES),
    "session": _pattern(_SESSION_RE, "英数字で始まり、英数字・_・.・- が続くセッションの ID"),
    "previous": _pattern(_SESSION_RE, "英数字で始まり、英数字・_・.・- が続くセッションの ID"),
    "branch": _branch,
    "draft": _draft,
    "type": _enum(REPORT_TYPES),
    "pr": _pr_url,
    "date": _date,
    "old": _issue,
    "issue": _issue,
    "result": _enum(RESULTS),
    "key": _pattern(_KEY_RE, "英数字で始まり、英数字・.・_・- が続くキー"),
}


def _check(kind, values, where):
    """種類と値を検査し、誤りの配列を返す。"""
    errors = []
    spec = KINDS.get(kind)
    if spec is None:
        return [f"知らない種類: {kind!r}"]
    if where is not None and spec["where"] != where:
        place = "Issue の本文の末尾の行" if spec["where"] == "body" else "記録のコメントの 1 行目"
        errors.append(f"種類 {kind} は{place}だけで使う")
    allowed = spec["required"] + spec["optional"]
    for key in values:
        if key not in allowed:
            errors.append(f"種類 {kind} に知らないキー: {key!r} (書けるキー: {', '.join(allowed) or 'なし'})")
    for key in spec["required"]:
        if key not in values:
            errors.append(f"種類 {kind} の必須のキーが無い: {key}")
    for key, value in values.items():
        if key not in allowed:
            continue
        if not value or any(c.isspace() for c in value):
            errors.append(f"キー {key} の値が空か、空白を含む")
            continue
        problem = KEYS[key](value)
        if problem:
            errors.append(f"キー {key} の値 {value!r} が {problem} ではない")
    return errors


def format_line(kind, values, where=None):
    """1 行目を作る。values はキーと値の辞書。返り値は {"line"} か {"errors"}。キーは KINDS の順に並べる。"""
    errors = _check(kind, values, where)
    if errors:
        return {"errors": errors}
    spec = KINDS[kind]
    parts = [PREFIX, kind] + [f"{key}={values[key]}" for key in spec["required"] + spec["optional"] if key in values]
    return {"line": " ".join(parts)}


def is_record_line(line):
    return (line or "").startswith(PREFIX)


def parse_line(line, where=None):
    """1 行目を解析する。返り値は {"kind", "values"} か {"errors"}。where を渡すと、その場所で使える種類かも検査する。"""
    line = (line or "").rstrip("\r")
    if not is_record_line(line):
        return {"errors": [f"{PREFIX} で始まらない"]}
    tokens = line[len(PREFIX):].split()
    if not tokens:
        return {"errors": ["種類が無い"]}
    kind, errors, values = tokens[0], [], {}
    if not _KIND_RE.match(kind):
        return {"errors": [f"種類の形ではない: {kind!r}"]}
    for token in tokens[1:]:
        m = _PAIR_RE.match(token)
        if not m:
            errors.append(f"<キー>=<値> の形ではない: {token!r}")
            continue
        if m.group("key") in values:
            errors.append(f"同じキーが 2 回ある: {m.group('key')}")
            continue
        values[m.group("key")] = m.group("value")
    errors += _check(kind, values, where)
    if errors:
        return {"errors": errors}
    return {"kind": kind, "values": values}


def parse_assignments(items):
    """`<キー>=<値>` の文字列の配列を辞書にする。返り値は ({キー: 値}, 誤りの配列)。"""
    values, errors = {}, []
    for item in items:
        m = _PAIR_RE.match(item)
        if not m:
            errors.append(f"<キー>=<値> の形ではない: {item!r}")
        elif m.group("key") in values:
            errors.append(f"同じキーが 2 回ある: {m.group('key')}")
        else:
            values[m.group("key")] = m.group("value")
    return values, errors


def _split_body(body):
    first, _, rest = (body or "").partition("\n")
    return first.rstrip("\r"), rest.lstrip("\r\n")


def collect(comments, login):
    """コメントの配列 (REST の issue comment の形) から記録を集める。

    投稿者 (user.login) が login と違うコメントと、1 行目が PREFIX で始まらないコメントは除く。ログインは大文字と小文字を
    区別しない。返り値は {"records", "invalid", "skipped_other_authors"}。records の要素は
    {"kind", "values", "id", "url", "created_at", "updated_at", "body"} (body は 1 行目と続く空行を除いた本文)、
    invalid の要素は {"id", "url", "line", "errors"}。
    """
    records, invalid, skipped = [], [], 0
    for comment in comments:
        author = ((comment.get("user") or {}).get("login") or "")
        if author.lower() != (login or "").lower():
            if is_record_line(_split_body(comment.get("body"))[0]):
                skipped += 1
            continue
        first, rest = _split_body(comment.get("body"))
        if not is_record_line(first):
            continue
        parsed = parse_line(first, where="comment")
        base = {"id": comment.get("id"), "url": comment.get("html_url")}
        if "errors" in parsed:
            invalid.append({**base, "line": first, "errors": parsed["errors"]})
            continue
        records.append({"kind": parsed["kind"], "values": parsed["values"], **base,
                        "created_at": comment.get("created_at"), "updated_at": comment.get("updated_at"), "body": rest})
    return {"records": records, "invalid": invalid, "skipped_other_authors": skipped}


def fetch_comments(ref):
    """Issue (か PR) のコメントを、投稿の順に全部読む。返り値は (コメントの配列, None) か (None, 失敗した gh の結果)。"""
    result = gh.run(["api", f"repos/{ref['owner']}/{ref['repo']}/issues/{ref['number']}/comments", "--paginate", "--slurp"],
                    expect_json=True)
    if gh.failed(result):
        return None, result
    pages = result["json"]
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        return None, {**result, "json_error": "応答がページの配列 (--slurp の形) ではない"}
    return [c for page in pages for c in page if isinstance(c, dict)], None


def list_records(ref):
    """Issue の記録を集める。返り値は ({"login", "records", "invalid", "skipped_other_authors"}, None) か
    (None, 失敗した gh の結果)。"""
    login, failure = gh.viewer_login()
    if failure:
        return None, failure
    comments, failure = fetch_comments(ref)
    if failure:
        return None, failure
    return {"login": login, **collect(comments, login)}, None
