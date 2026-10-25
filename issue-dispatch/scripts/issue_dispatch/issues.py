"""Issue と PR の読み書き。`blockedBy` の追加 (`add_blocked_by`)・分割で作る Issue の作成 (`create_issue`)・ラベルの追加
(`add_label`。リポジトリに無ければ作る)・PR の観測 (`observe_pr`)。様式の正本は
issue-dispatch/skills/issue-dispatch/references/issue-format.md。

読むのは `gh issue list` / `gh issue view` / `gh label list` / `gh api user` と GraphQL (graphql/pr-observe.graphql。実行は
project.graphql と同じ仕組み)。書くのは `gh issue create` / `gh issue edit` / `gh label create` で、どれも gh.run の
mutation=True で行う。書き込みの失敗は理由付きで返し、このモジュールでは再試行しない (再試行するかは呼び出し元のスキルが決める)。
`blockedBy` の削除 (自分が足したものかの導出が要る) は U13 で足す。
"""

import re

from issue_dispatch import gh, ids
from issue_dispatch.project import graphql

# 分割で作る Issue の本文の先頭行。値は分割の元の宣言のコメントの URL (Issue とコメントの両方を指す)
SPLIT_FROM_PREFIX = "split-from: "
_DECLARATION_URL_RE = re.compile(rf"^https://github\.com/{ids.REPO_NAME_PATTERN}/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*$")
# PR の観測の結果の種類 (issue-format.md の表)
PR_KINDS = ("other_author", "draft", "needs_closing_reference", "in_review", "merged", "merged_issue_open", "merged_without_reference", "closed")
# `gh issue list` / `gh label list` の --limit (既定の 30 では足りない。開いた Issue とラベルがこれを超えるリポジトリは想定しない)
LIST_LIMIT = 1000


def _error(r, key=None):
    """gh.run の結果から失敗の説明を作る。"""
    message = r["stderr_tail"] or r.get("json_error") or r["stdout"].strip() or f"終了コード {r['exit_code']}"
    out = {"status": "error", "failure": r["failure"] or "other", "message": message, "exit_code": r["exit_code"]}
    if key:
        out["key"] = key
    return out


def token_login():
    """`gh api user` でトークンのログインを得る。返り値は {"status": "ok", "login"} か失敗の説明。"""
    r = gh.run(["api", "user"], expect_json=True)
    login = (r["json"] or {}).get("login") if isinstance(r["json"], dict) else None
    if r["failure"] or not login:
        return _error(r)
    return {"status": "ok", "login": login}


# --- PR の観測 -----------------------------------------------------------------

def _pr_kind(state, draft, issue_states):
    if state == "CLOSED":
        return "closed"
    if state == "MERGED":
        # 参照が 1 つも無いマージ済みは、「すべて閉じている」とは別にする (マージで Issue は閉じないため)
        if not issue_states:
            return "merged_without_reference"
        return "merged_issue_open" if "OPEN" in issue_states else "merged"
    if draft:
        return "draft"
    if not issue_states:
        return "needs_closing_reference"
    return "in_review"


def observe_pr(url, login=None):
    """PR の URL を受けて、状態と参照する Issue と変えたファイルを読み、種類を決める。書き込みは無い。

    login はトークンのログイン (None なら `gh api user` で得る)。作者がそれと違う PR は無いものとして扱い、種類
    `other_author` で中身 (`pr`) を返さない (AE28。公開リポジトリでは第三者も PR を作れるため)。
    返り値: {"status": "ok", "kind", "pr": {number, title, url, state, draft, created_at, merged_at, closed_at, author, base_ref, default_branch (リポジトリの既定のブランチ),
    head_ref, issues: [{key, number, url, state}], issues_truncated, files: [{path, additions, deletions, change_type}]},
    "author", "rate_limit", "warnings"} か、{"status": "error", "failure", "message", ...}。
    """
    parsed = ids.parse_pr_url(url)
    if parsed is None:
        return {"status": "error", "failure": "other", "message": f"PR の URL の形 (https://github.com/owner/repo/pull/番号) ではない: {url!r}", "exit_code": None}
    if login is None:
        got = token_login()
        if got["status"] != "ok":
            return got
        login = got["login"]
    owner, _, name = parsed["repo"].partition("/")
    variables = {"owner": owner, "name": name, "number": parsed["number"]}
    data, problem, errors = graphql("pr-observe", variables)
    if problem:
        return {"status": "error", **problem}
    pr = (data.get("repository") or {}).get("pullRequest")
    if not pr:
        return {"status": "error", "failure": "other", "exit_code": 0,
                "message": f"PR {parsed['url']} を読めない (無い・見えない: {errors!r})"}
    warnings = list(errors)
    author = (pr.get("author") or {}).get("login")
    rate_limit = data.get("rateLimit")
    if author != login:
        return {"status": "ok", "kind": "other_author", "pr": None, "author": author, "rate_limit": rate_limit, "warnings": warnings}
    files = [_file(n) for n in pr["files"]["nodes"] if n]
    info = pr["files"].get("pageInfo") or {}
    while info.get("hasNextPage"):
        page, problem, page_errors = graphql("pr-observe", {**variables, "filesCursor": info.get("endCursor")})
        if problem:
            return {"status": "error", **problem}
        page_pr = (page.get("repository") or {}).get("pullRequest")
        if not page_pr or page_errors:
            return {"status": "error", "failure": "other", "exit_code": 0,
                    "message": f"変えたファイルの続きのページを読めない: {page_errors!r}"}
        files += [_file(n) for n in page_pr["files"]["nodes"] if n]
        info = page_pr["files"].get("pageInfo") or {}
        rate_limit = page.get("rateLimit") or rate_limit
    refs = pr.get("closingIssuesReferences") or {}
    issues = [{"key": f"{n['repository']['nameWithOwner']}#{n['number']}", "number": n["number"], "url": n["url"], "state": n["state"]}
              for n in refs.get("nodes") or [] if n]
    out = {"number": pr["number"], "title": pr.get("title"), "url": pr["url"], "state": pr["state"], "draft": bool(pr.get("isDraft")),
           "created_at": pr.get("createdAt"), "merged_at": pr.get("mergedAt"), "closed_at": pr.get("closedAt"), "author": author,
           "base_ref": pr.get("baseRefName"), "head_ref": pr.get("headRefName"),
           "default_branch": ((data.get("repository") or {}).get("defaultBranchRef") or {}).get("name"), "issues": issues,
           "issues_truncated": (refs.get("totalCount") or 0) > len(issues), "files": files}
    return {"status": "ok", "kind": _pr_kind(pr["state"], out["draft"], [i["state"] for i in issues]), "pr": out, "author": author,
            "rate_limit": rate_limit, "warnings": warnings}


def pr_state(url):
    """PR の状態 (state・draft・merged) だけを読む (スナップショットが GitHub 上の状態を写すため、作者で除かず、変えたファイルも読まない)。
    返り値: {"status": "ok", "url", "state", "draft", "merged"} か失敗の説明。"""
    parsed = ids.parse_pr_url(url)
    if parsed is None:
        return {"status": "error", "failure": "other", "message": f"PR の URL の形ではない: {url!r}", "exit_code": None}
    owner, _, name = parsed["repo"].partition("/")
    data, problem, errors = graphql("pr-observe", {"owner": owner, "name": name, "number": parsed["number"]})
    if problem:
        return {"status": "error", **problem}
    pr = (data.get("repository") or {}).get("pullRequest")
    if not pr:
        return {"status": "error", "failure": "other", "exit_code": 0, "message": f"PR {parsed['url']} を読めない (無い・見えない: {errors!r})"}
    return {"status": "ok", "url": parsed["url"], "state": pr["state"], "draft": bool(pr.get("isDraft")), "merged": pr["state"] == "MERGED"}


def _file(node):
    return {"path": node["path"], "additions": node.get("additions"), "deletions": node.get("deletions"), "change_type": node.get("changeType")}


# --- 分割で作る Issue ----------------------------------------------------------

def split_from_line(declaration_url):
    """分割で作る Issue の本文の先頭行。declaration_url は分割の元の宣言のコメントの URL
    (`https://github.com/owner/repo/issues/番号#issuecomment-<id>`)。その形でなければ None。"""
    if not isinstance(declaration_url, str) or not _DECLARATION_URL_RE.match(declaration_url.strip()):
        return None
    return SPLIT_FROM_PREFIX + declaration_url.strip()


def _first_line(body):
    return (body or "").split("\n", 1)[0].strip()


def create_issue(repo, title, body, declaration_url, labels=(), assignees=()):
    """分割で Issue を作る。本文の先頭行に分割の元 (宣言のコメントの URL) を書き、同じ先頭行を持つ開いた Issue が
    既にあれば作らずにその番号を返す (再開のときに 2 つ作らない。AE44)。Status と sub-issue の関係は書かない。

    返り値: {"status": "ok", "created": bool, "number", "url"} か失敗の説明。開いた Issue の一覧が読めなければ作らない
    (既にあるかを確認できないまま作ると 2 つになりうるため)。
    """
    first = split_from_line(declaration_url)
    if first is None:
        return {"status": "error", "failure": "other", "exit_code": None,
                "message": f"分割の元は宣言のコメントの URL (https://github.com/owner/repo/issues/番号#issuecomment-<id>) で指す: {declaration_url!r}"}
    if not isinstance(repo, str) or not re.fullmatch(ids.REPO_NAME_PATTERN, repo):
        return {"status": "error", "failure": "other", "exit_code": None, "message": f"リポジトリは owner/name の形: {repo!r}"}
    r = gh.run(["issue", "list", "-R", repo, "--state", "open", "--json", "number,url,body", "--limit", str(LIST_LIMIT)], expect_json=True)
    if r["failure"] or not isinstance(r["json"], list):
        return _error(r)
    for issue in r["json"]:
        if _first_line(issue.get("body")) == first:
            return {"status": "ok", "created": False, "number": issue["number"], "url": issue["url"]}
    args = ["issue", "create", "-R", repo, "--title", title, "--body", f"{first}\n\n{body}"]
    for label in labels:
        args += ["--label", label]
    for assignee in assignees:
        args += ["--assignee", assignee]
    r = gh.run(args, mutation=True)
    created = ids.parse_issue_ref(r["stdout"].strip().split("\n")[-1] if r["stdout"].strip() else "")
    if r["failure"] or r["exit_code"] != 0 or created is None:
        return _error(r)
    return {"status": "ok", "created": True, "number": created["number"], "url": created["url"]}


# --- blockedBy -----------------------------------------------------------------

def add_blocked_by(issue, blocker):
    """issue の `blockedBy` に blocker を足す (`gh issue edit <URL> --add-blocked-by <URL>`。URL の形だけを受け付ける。U1)。
    返り値: {"status": "ok", "issue", "blocker"} (キーは `owner/repo#番号`) か失敗の説明。失敗しても再試行しない。"""
    issue_ref, blocker_ref = ids.parse_issue_ref(issue), ids.parse_issue_ref(blocker)
    if issue_ref is None or blocker_ref is None:
        return {"status": "error", "failure": "other", "exit_code": None,
                "message": f"Issue の参照 (owner/repo#番号 か URL) ではない: {issue!r} / {blocker!r}"}
    r = gh.run(["issue", "edit", issue_ref["url"], "--add-blocked-by", blocker_ref["url"]], mutation=True)
    if r["failure"] or r["exit_code"] != 0:
        return _error(r)
    return {"status": "ok", "issue": issue_ref["key"], "blocker": blocker_ref["key"]}


def remove_blocked_by(issue, blocker):
    """issue の `blockedBy` から blocker を外す (`gh issue edit <URL> --remove-blocked-by <URL>`)。自分が足したものだけを外す確認は
    呼び出し元 (CLI の `blocked-by remove`。項目の状態から導く) が行う。返り値は add_blocked_by と同じ形。"""
    issue_ref, blocker_ref = ids.parse_issue_ref(issue), ids.parse_issue_ref(blocker)
    if issue_ref is None or blocker_ref is None:
        return {"status": "error", "failure": "other", "exit_code": None,
                "message": f"Issue の参照 (owner/repo#番号 か URL) ではない: {issue!r} / {blocker!r}"}
    r = gh.run(["issue", "edit", issue_ref["url"], "--remove-blocked-by", blocker_ref["url"]], mutation=True)
    if r["failure"] or r["exit_code"] != 0:
        return _error(r)
    return {"status": "ok", "issue": issue_ref["key"], "blocker": blocker_ref["key"]}


# --- ラベル ----------------------------------------------------------------------

def _same_label(names, label):
    """names の中で label と同じ名前 (GitHub はラベルの名前を大文字小文字を区別せずに一意にするので casefold で比べる) を返す。無ければ None。"""
    wanted = label.casefold()
    return next((n for n in names if isinstance(n, str) and n.casefold() == wanted), None)


def add_label(issue, label, description=None):
    """Issue にラベルを足す。既に付いていれば何もしない。リポジトリにラベルが無ければ先に作る (色は gh のデフォルト、
    説明は description)。名前は大文字小文字を区別せずに比べ、リポジトリに綴りだけ違うラベルがあればその綴りで足す。
    返り値: {"status": "ok", "issue", "label" (足した綴り), "label_created", "added"} か失敗の説明。"""
    ref = ids.parse_issue_ref(issue)
    if ref is None:
        return {"status": "error", "failure": "other", "exit_code": None, "message": f"Issue の参照ではない: {issue!r}"}
    r = gh.run(["issue", "view", ref["url"], "--json", "labels"], expect_json=True)
    if r["failure"] or not isinstance(r["json"], dict):
        return _error(r, "issue")
    attached = _same_label([l.get("name") for l in r["json"].get("labels") or []], label)
    result = {"status": "ok", "issue": ref["key"], "label": attached or label, "label_created": False, "added": False}
    if attached is not None:
        return result
    r = gh.run(["label", "list", "-R", ref["repo"], "--json", "name", "--limit", str(LIST_LIMIT)], expect_json=True)
    if r["failure"] or not isinstance(r["json"], list):
        return _error(r, "labels")
    existing = _same_label([l.get("name") for l in r["json"]], label)
    if existing is not None:
        label = existing  # 既にある綴りで足す (綴りだけ違う名前で作ろうとすると GitHub は「既にある」で拒む)
        result["label"] = existing
    else:
        args = ["label", "create", label, "-R", ref["repo"]]
        if description:
            args += ["--description", description]
        r = gh.run(args, mutation=True)
        if r["failure"] or r["exit_code"] != 0:
            return _error(r, "label-create")
        result["label_created"] = True
    r = gh.run(["issue", "edit", ref["url"], "--add-label", label], mutation=True)
    if r["failure"] or r["exit_code"] != 0:
        return {**_error(r, "add-label"), "label_created": result["label_created"]}
    result["added"] = True
    return result
