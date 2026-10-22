"""Issue のコメント。先頭行 (書いたセッションの種類と識別子とコメントの種類と値。R6) の生成と解析、コメントの一覧 (書き手が
トークンのログインと違うものを除く)、投稿 (同じ出来事への同じコメントが既にあれば投稿しない。KTD2)、小さな PR の報告と依頼の
対応づけ。様式の正本は issue-dispatch/skills/issue-dispatch/references/issue-format.md の「コメント」。

読むのは GraphQL (graphql/issue-comments.graphql。実行は project.graphql) と `gh api user`、書くのは `gh issue comment <URL>
--body-file -` (本文を標準入力で渡す。gh.run の mutation=True)。
"""

import re

from issue_dispatch import gh, ids
from issue_dispatch.project import graphql

PREFIX = "issue-dispatch"
SEP = " | "
ROLES = {"manager": "管理のセッション", "worker": "作業のセッション"}
_ROLE_OF = {v: k for k, v in ROLES.items()}
MANAGER_KINDS = ("割り当て", "開始可", "待機", "解放", "引き継ぎ", "停滞", "依存の待ち", "依存の解消", "依頼")
WORKER_KINDS = ("着手の宣言", "宣言の更新", "小さな PR の報告", "PR の報告")
# 宛先 (対象) と割り当ての番号を持つ種類
ADDRESSED_KINDS = ("割り当て", "開始可", "待機", "解放", "停滞", "依頼")
REQUEST_KINDS = ("宣言の書き直し", "本文の追記", "小さな PR")
RELEASE_REASONS = ("解除", "close", "ID の変更", "除去")
WAIT_KINDS = ("利用者の答え", "Issue", "小さな PR", "資源", "設定")
# 先頭行の値の見出し語 (値は `<見出し語> <値>` の 1 区切り)。解析は右からこの語で始まる区切りを値として取る
VALUE_WORDS = ("対象", "割り当て", "宣言", "種類", "待つ Issue", "待つ側の宣言", "前の PR", "PR", "理由", "値", "Issue")

# 種類ごとに持つ値 (キー) と並び。waits と blockers は配列で、1 要素 1 区切り
_SHAPE = {
    "割り当て": ("to", "assignment"),
    "開始可": ("to", "assignment", "declaration"),
    "待機": ("to", "assignment", "declaration", "waits"),
    "解放": ("to", "assignment", "release_reason"),
    "停滞": ("to", "assignment", "stuck_state"),
    "依頼": ("to", "assignment", "request_kind"),  # 種類ごとの値は _REQUEST_SHAPE
    "引き継ぎ": (),
    "依存の待ち": ("blockers",),
    "依存の解消": (),
    "着手の宣言": (),
    "宣言の更新": (),
    "小さな PR の報告": ("waiting_issue", "waiting_declaration", "previous_pr?"),
    "PR の報告": (),
}
_REQUEST_SHAPE = {"宣言の書き直し": ("declaration",), "本文の追記": ("pr",), "小さな PR": ("waiting_issue", "waiting_declaration", "previous_pr?")}
_WORD_OF = {"to": "対象", "assignment": "割り当て", "declaration": "宣言", "request_kind": "種類", "waiting_issue": "待つ Issue",
            "waiting_declaration": "待つ側の宣言", "previous_pr": "前の PR", "pr": "PR", "release_reason": "理由", "stuck_state": "値",
            "waits": "理由", "blockers": "Issue"}
_ID_RE = re.compile(r"^[1-9][0-9]*$")


def _shape(kind, request_kind=None):
    keys = list(_SHAPE[kind])
    if kind == "依頼" and request_kind in _REQUEST_SHAPE:
        keys += _REQUEST_SHAPE[request_kind]
    return keys


# --- 値の正規化と検査 ------------------------------------------------------------

def _issue_ref(value, what):
    key = ids.issue_key(value)
    if key is None:
        raise ValueError(f"{what} は Issue の参照 (owner/repo#番号 か URL) で書く: {value!r}")
    return key


def _pr_url(value, what):
    parsed = ids.parse_pr_url(value)
    if parsed is None:
        raise ValueError(f"{what} は PR の URL で書く: {value!r}")
    return parsed["url"]


def _comment_id(value, what):
    text = str(value).strip()
    if not _ID_RE.match(text):
        raise ValueError(f"{what} はコメントの ID (URL の末尾 #issuecomment-<数値> の数値) で書く: {value!r}")
    return int(text)


def _wait(item):
    if not isinstance(item, dict) or item.get("kind") not in WAIT_KINDS:
        raise ValueError(f"待つ理由は {', '.join(WAIT_KINDS)} のどれか: {item!r}")
    kind = item["kind"]
    out = {"kind": kind}
    if kind == "Issue":
        out["issue"] = _issue_ref(item.get("issue"), "待つ Issue")
    elif kind == "小さな PR":
        out["issue"] = _issue_ref(item.get("issue"), "小さな PR の依頼先の Issue")
        if item.get("pr") is not None:
            out["pr"] = _pr_url(item["pr"], "小さな PR")
    elif kind == "資源":
        name = item.get("resource")
        if not isinstance(name, str) or not name.strip() or SEP in name:
            raise ValueError(f"資源の名前が無いか、区切り文字を含む: {name!r}")
        out["resource"] = name.strip()
    return out


def normalize_values(kind, values):
    """種類に合わせて値をそろえ、検査する。返り値はそろえた値 (dict)。足りない・余分・形が違えば ValueError。"""
    values = dict(values or {})
    if kind not in _SHAPE:
        raise ValueError(f"コメントの種類ではない: {kind!r}")
    request_kind = values.get("request_kind")
    if kind == "依頼" and request_kind not in REQUEST_KINDS:
        raise ValueError(f"依頼の種類は {', '.join(REQUEST_KINDS)} のどれか: {request_kind!r}")
    keys = _shape(kind, request_kind)
    required = [k.rstrip("?") for k in keys if not k.endswith("?")]
    allowed = [k.rstrip("?") for k in keys]
    extra = [k for k, v in values.items() if k not in allowed and v not in (None, [], ())]
    if extra:
        raise ValueError(f"種類 {kind} は値 {', '.join(extra)} を持たない")
    missing = [k for k in required if values.get(k) in (None, [], ())]
    if missing:
        raise ValueError(f"種類 {kind} に値 {', '.join(missing)} が無い")
    out = {}
    for key in allowed:
        v = values.get(key)
        if v in (None, [], ()):
            continue
        if key == "to":
            if not isinstance(v, str) or not v.strip() or SEP in v:
                raise ValueError(f"対象 (作業のセッションの ID) が無いか、区切り文字を含む: {v!r}")
            out[key] = v.strip()
        elif key == "assignment":
            if not _ID_RE.match(str(v).strip()):
                raise ValueError(f"割り当ての番号は 1 以上の整数: {v!r}")
            out[key] = int(str(v).strip())
        elif key in ("declaration", "waiting_declaration"):
            out[key] = _comment_id(v, _WORD_OF[key])
        elif key == "request_kind":
            out[key] = v
        elif key == "waiting_issue":
            out[key] = _issue_ref(v, "待つ Issue")
        elif key in ("previous_pr", "pr"):
            out[key] = _pr_url(v, _WORD_OF[key])
        elif key == "release_reason":
            if v not in RELEASE_REASONS:
                raise ValueError(f"解放の理由は {', '.join(RELEASE_REASONS)} のどれか: {v!r}")
            out[key] = v
        elif key == "stuck_state":
            if not isinstance(v, str) or not v.strip() or SEP in v:
                raise ValueError(f"停滞の値が無いか、区切り文字を含む: {v!r}")
            out[key] = v.strip()
        elif key == "waits":
            out[key] = [_wait(w) for w in v]
        elif key == "blockers":
            out[key] = [_issue_ref(b, "待つ Issue") for b in v]
    return out


# --- 先頭行の生成 ----------------------------------------------------------------

def _wait_text(w):
    if w["kind"] == "Issue":
        return f"Issue {w['issue']}"
    if w["kind"] == "小さな PR":
        return f"小さな PR {w['issue']}" + (f" PR {w['pr']}" if w.get("pr") else "")
    if w["kind"] == "資源":
        return f"資源 {w['resource']}"
    return w["kind"]


def _value_fields(kind, values):
    fields = []
    for key in _shape(kind, values.get("request_kind")):
        key = key.rstrip("?")
        v = values.get(key)
        if v is None:
            continue
        word = _WORD_OF[key]
        if key == "waits":
            fields += [f"{word} {_wait_text(w)}" for w in v]
        elif key == "blockers":
            fields += [f"{word} {b}" for b in v]
        else:
            fields.append(f"{word} {v}")
    return fields


def format_header(role, name, session_id, kind, values=None):
    """先頭行を作る。role は manager / worker。値の形は normalize_values。名前は区切り文字を含んでもよい (解析は右から読む) が、
    セッション ID は含めない。種類が役割のものでない・値が足りないなどは ValueError。"""
    if role not in ROLES:
        raise ValueError(f"役割は manager か worker: {role!r}")
    if kind not in (MANAGER_KINDS if role == "manager" else WORKER_KINDS):
        raise ValueError(f"種類 {kind!r} は {ROLES[role]}のコメントではない")
    if not isinstance(name, str) or not name.strip() or "\n" in name:
        raise ValueError(f"セッションの名前が無いか、改行を含む: {name!r}")
    if not isinstance(session_id, str) or not session_id.strip() or SEP in session_id or "\n" in session_id or session_id.strip() in _SHAPE:
        raise ValueError(f"セッション ID が無いか、区切り文字か改行を含むか、種類の語と同じ: {session_id!r}")
    normalized = normalize_values(kind, values)
    return SEP.join([PREFIX, ROLES[role], name.strip(), session_id.strip(), kind] + _value_fields(kind, normalized))


# --- 先頭行の解析 ----------------------------------------------------------------

def _split_value(field):
    """区切り 1 つを (見出し語, 値) にする。見出し語で始まらなければ None。長い語 (`待つ Issue`) を先に試す。"""
    for word in sorted(VALUE_WORDS, key=len, reverse=True):
        if field.startswith(word + " "):
            return word, field[len(word) + 1:]
    return None


def _parse_wait(text):
    for kind in ("利用者の答え", "設定"):
        if text == kind:
            return {"kind": kind}
    if text.startswith("Issue "):
        return {"kind": "Issue", "issue": text[len("Issue "):]}
    if text.startswith("小さな PR "):
        rest = text[len("小さな PR "):]
        issue, _, pr = rest.partition(" PR ")
        out = {"kind": "小さな PR", "issue": issue}
        if pr:
            out["pr"] = pr
        return out
    if text.startswith("資源 "):
        return {"kind": "資源", "resource": text[len("資源 "):]}
    raise ValueError(f"待つ理由の形ではない: {text!r}")


def parse_wait_reason(text):
    """`理由 ` の後の文字列 (`利用者の答え` / `Issue <参照>` / `小さな PR <参照> [PR <URL>]` / `資源 <名前>` / `設定`) を
    待つ理由の dict にする。CLI の --reason も同じ形。形が違えば ValueError。"""
    return _wait(_parse_wait(text.strip()))


def parse_header(line):
    """先頭行を読む。返り値は {"role", "name", "session_id", "kind", "values"} か、先頭行の形でなければ None。

    右から読む: 値の見出し語で始まる区切りを値として取り、次が種類、その前がセッション ID、残りがすべて名前。名前が
    区切り文字を含んでもよいのはこのため (セッション ID は含まない前提)。値の形が種類に合わなければ None。
    """
    if not isinstance(line, str) or "\n" in line:
        return None
    fields = line.rstrip().split(SEP)
    if len(fields) < 5 or fields[0] != PREFIX or fields[1] not in _ROLE_OF:
        return None
    role = _ROLE_OF[fields[1]]
    value_fields = []
    index = len(fields) - 1
    while index >= 4 and fields[index] not in _SHAPE and _split_value(fields[index]) is not None:
        value_fields.insert(0, _split_value(fields[index]))
        index -= 1
    if index < 4 or fields[index] not in _SHAPE:
        return None
    kind = fields[index]
    if kind not in (MANAGER_KINDS if role == "manager" else WORKER_KINDS):
        return None
    session_id = fields[index - 1]
    name = SEP.join(fields[2:index - 1])
    if not name or not session_id:
        return None
    raw = {}
    try:
        for word, text in value_fields:
            if word == "理由" and kind == "待機":
                raw.setdefault("waits", []).append(_parse_wait(text))
            elif word == "理由" and kind == "解放":
                raw["release_reason"] = text
            elif word == "Issue" and kind == "依存の待ち":
                raw.setdefault("blockers", []).append(text)
            else:
                key = next((k for k, w in _WORD_OF.items() if w == word and k not in ("waits", "blockers", "release_reason")), None)
                if key is None or key in raw:
                    return None
                raw[key] = text
        values = normalize_values(kind, raw)
    except ValueError:
        return None
    return {"role": role, "name": name, "session_id": session_id, "kind": kind, "values": values}


def split_body(body):
    """コメントの本文を (先頭行の解析結果か None, 先頭行と空行を除いた本文) にする。先頭行の形でなければ本文はそのまま。"""
    text = body or ""
    first, _, rest = text.partition("\n")
    parsed = parse_header(first)
    if parsed is None:
        return None, text
    return parsed, rest.lstrip("\n")


# --- 一覧 -----------------------------------------------------------------------

def token_login():
    r = gh.run(["api", "user"], expect_json=True)
    login = (r["json"] or {}).get("login") if isinstance(r["json"], dict) else None
    if r["failure"] or not login:
        return None, {"status": "error", "failure": r["failure"] or "other", "exit_code": r["exit_code"],
                      "message": r["stderr_tail"] or r.get("json_error") or "gh api user でログインを読めない"}
    return login, None


def list_comments(issue, login=None):
    """Issue のコメントを時刻の順に全部読む。書き手がトークンのログイン (login。None なら `gh api user`) と違うコメントは除く
    (R6。公開リポジトリでは第三者も書けるため)。返り値: {"status": "ok", "login", "comments": [{id, database_id, url,
    created_at, author, header (parse_header の結果か None), body (先頭行を除いた本文)}], "excluded" (除いた件数), "rate_limit"}
    か失敗の説明。"""
    ref = ids.parse_issue_ref(issue)
    if ref is None:
        return {"status": "error", "failure": "other", "exit_code": None, "message": f"Issue の参照ではない: {issue!r}"}
    if login is None:
        login, problem = token_login()
        if problem:
            return problem
    owner, _, name = ref["repo"].partition("/")
    nodes, after, rate_limit = [], None, None
    while True:
        data, problem, errors = graphql("issue-comments", {"owner": owner, "name": name, "number": ref["number"], "after": after})
        if problem:
            return {"status": "error", **problem}
        issue_node = (data.get("repository") or {}).get("issue")
        if not issue_node or errors:
            return {"status": "error", "failure": "other", "exit_code": 0,
                    "message": f"Issue {ref['key']} のコメントを読めない: {errors!r}"}
        page = issue_node["comments"]
        nodes += [n for n in page["nodes"] if n]
        rate_limit = data.get("rateLimit") or rate_limit
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    out, excluded = [], 0
    for n in sorted(nodes, key=lambda n: (n.get("createdAt") or "", n.get("databaseId") or 0)):
        if (n.get("author") or {}).get("login") != login:
            excluded += 1
            continue
        header, body = split_body(n.get("body"))
        out.append({"id": n["id"], "database_id": n.get("databaseId"), "url": n.get("url"), "created_at": n.get("createdAt"),
                    "author": login, "header": header, "body": body})
    return {"status": "ok", "login": login, "comments": out, "excluded": excluded, "rate_limit": rate_limit}


# --- 既投稿の見分けと投稿 ---------------------------------------------------------

def header_key(parsed):
    """同じ出来事かを比べるための鍵。名前は比べない (変わりうる)。書き手の ID・種類・値を比べる。"""
    return (parsed["role"], parsed["session_id"], parsed["kind"], _freeze(parsed["values"]))


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def already_posted(parsed, own_comments):
    """同じ出来事への同じコメントが既にあればそのコメント (list_comments の要素) を、無ければ None を返す (KTD2)。

    own_comments は list_comments が返した、書き手が自分のコメントの配列 (時刻の順)。種類ごとの規則:
    `待機` は同じ宣言への最新の `待機` とだけ比べる。`依存の待ち` は最新の `依存の待ち` と比べ、間に `依存の解消` があれば
    投稿する。`依存の解消` は最新の `依存の待ち` より後のコメントとだけ比べる。`停滞` は同じ対象・割り当て・値なら、間に
    別のコメントがあっても既投稿。ほかの種類は、先頭行の鍵 (header_key) が同じコメントがあれば既投稿。
    """
    kind = parsed["kind"]
    key = header_key(parsed)
    headed = [c for c in own_comments if c.get("header")]
    if kind == "待機":
        same_declaration = [c for c in headed if c["header"]["kind"] == "待機"
                            and c["header"]["values"].get("declaration") == parsed["values"].get("declaration")]
        latest = same_declaration[-1] if same_declaration else None
        return latest if latest and header_key(latest["header"]) == key else None
    if kind == "依存の待ち":
        latest_wait, resolved_after = None, False
        for c in headed:
            if c["header"]["kind"] == "依存の待ち":
                latest_wait, resolved_after = c, False
            elif c["header"]["kind"] == "依存の解消" and latest_wait is not None:
                resolved_after = True
        if latest_wait is None or resolved_after:
            return None
        return latest_wait if header_key(latest_wait["header"]) == key else None
    if kind == "依存の解消":
        after_latest_wait = []
        for c in headed:
            if c["header"]["kind"] == "依存の待ち":
                after_latest_wait = []
            else:
                after_latest_wait.append(c)
        return next((c for c in after_latest_wait if header_key(c["header"]) == key), None)
    if kind == "停滞":
        v = parsed["values"]
        return next((c for c in headed if c["header"]["kind"] == "停滞" and c["header"]["role"] == parsed["role"]
                     and c["header"]["session_id"] == parsed["session_id"]
                     and (c["header"]["values"]["to"], c["header"]["values"]["assignment"], c["header"]["values"]["stuck_state"])
                     == (v["to"], v["assignment"], v["stuck_state"])), None)
    return next((c for c in headed if header_key(c["header"]) == key), None)


def post(issue, role, name, session_id, kind, values, body, login=None):
    """コメントを投稿する。先頭行は format_header で作り、同じ出来事への同じコメントが既にあれば投稿しない (already_posted)。
    返り値: {"status": "ok", "posted": bool, "database_id", "url", "header"} か失敗の説明。一覧が読めなければ投稿しない
    (既投稿かを確かめられないまま投稿すると二重になりうるため)。"""
    try:
        line = format_header(role, name, session_id, kind, values)
    except ValueError as e:
        return {"status": "error", "failure": "other", "exit_code": None, "message": str(e), "key": "header"}
    listed = list_comments(issue, login)
    if listed["status"] != "ok":
        return listed
    existing = already_posted(parse_header(line), listed["comments"])
    if existing is not None:
        return {"status": "ok", "posted": False, "database_id": existing["database_id"], "url": existing["url"], "header": line}
    url = ids.issue_url(issue)
    r = gh.run(["issue", "comment", url, "--body-file", "-"], mutation=True, stdin=f"{line}\n\n{body or ''}")
    m = re.search(r"#issuecomment-([0-9]+)\s*$", r["stdout"].strip()) if r["stdout"] else None
    if r["failure"] or r["exit_code"] != 0 or m is None:
        return {"status": "error", "failure": r["failure"] or "other", "exit_code": r["exit_code"],
                "message": r["stderr_tail"] or r["stdout"].strip() or f"終了コード {r['exit_code']}"}
    return {"status": "ok", "posted": True, "database_id": int(m.group(1)), "url": r["stdout"].strip().split("\n")[-1], "header": line}


# --- 報告と依頼の対応づけ ---------------------------------------------------------

def match_report(request, report):
    """`小さな PR の報告` (report) が、種類 `小さな PR` の `依頼` (request) に答えたものか。先頭行の待つ Issue・待つ側の宣言・
    前の PR (あれば) が同じなら対応する。書いたセッションの名前と ID は比べない (名前は変わりうるため)。"""
    if not request or not report or request["kind"] != "依頼" or request["values"].get("request_kind") != "小さな PR":
        return False
    if report["kind"] != "小さな PR の報告":
        return False
    a, b = request["values"], report["values"]
    return (ids.same_issue(a["waiting_issue"], b["waiting_issue"]) and a["waiting_declaration"] == b["waiting_declaration"]
            and a.get("previous_pr") == b.get("previous_pr"))
