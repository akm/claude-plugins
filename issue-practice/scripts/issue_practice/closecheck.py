"""閉じる前の検査・共通の条件のコピーの比較・依存先が片付いたことの書き込み (計画の U3・KTD9・KTD10・R19・R20・R22・R49・R50)。

検査することと見出しの SSOT は、文書 `issue-practice/references/closing-conditions.md` の節「管理 Issue の条件」と
「閉じ方」と、このモジュールの定数。

関数は、結果の辞書を返す。gh が失敗したら、結果の status を gh_failed にし、gh_error に失敗した gh の結果を入れる。
例外は送出しない。
"""

import re

from issue_practice import bodies, checkboxes, gh, mergeplan, records, refs, releaseplan

ROLES = ("working", "managing", "self-managing")
COMMON_HEADING = "すべての作業 Issue に共通するクローズ条件"
COPY_HEADING_RE = re.compile(r"^共通 \((?P<ref>\S+) の「" + COMMON_HEADING + r"」からコピー\)$")
DEPENDENCIES_SECTION = "依存先"
META_FIELDS = "number,url,state,milestone,blocking"
PR_FIELDS = "number,url,state,mergedAt,baseRefName,isDraft"

_LIST_ITEM_RE = re.compile(r"^[-*+] ")


class _GhFailed(Exception):
    """gh の失敗を、関数の中で呼び出し元まで戻すための例外。モジュールの外には出さない。"""

    def __init__(self, result):
        super().__init__("gh failed")
        self.result = result


def _need(pair):
    value, failure = pair
    if failure:
        raise _GhFailed(failure)
    return value


def fetch_meta(ref):
    """Issue の番号・URL・状態・マイルストーン・blocking (この Issue を依存先とする Issue) を読む。"""
    result = gh.run(["issue", "view", str(ref["number"]), "-R", f"{ref['owner']}/{ref['repo']}", "--json", META_FIELDS],
                    expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return None, {**result, "json_error": "応答に url が無い"}
    return data, None


def fetch_pr(url):
    result = gh.run(["pr", "view", url, "--json", PR_FIELDS], expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return None, {**result, "json_error": "応答に url が無い"}
    return data, None


def pr_merged(data):
    return data.get("state") == "MERGED" and bool(data.get("mergedAt"))


def open_blocking(meta):
    """meta (fetch_meta の結果) の blocking のうち、開いている Issue の配列。"""
    nodes = ((meta.get("blocking") or {}).get("nodes")) or []
    return [{"number": n.get("number"), "url": n.get("url"), "title": n.get("title"), "state": n.get("state")}
            for n in nodes if isinstance(n, dict) and n.get("state") == "OPEN"]


def _milestone(meta):
    return (meta.get("milestone") or {}).get("title")


def _items_text(items):
    return [{"group": item["group"], "text": item["text"]} for item in items]


def common_items(items):
    """管理 Issue のチェックボックスのうち、節「すべての作業 Issue に共通するクローズ条件」の項目。"""
    return [item for item in items if item["heading"] == COMMON_HEADING]


def copy_items(items):
    """作業 Issue のチェックボックスのうち、共通の条件のコピーの見出しの下の項目。"""
    return [item for item in items if item["heading"] and COPY_HEADING_RE.match(item["heading"])]


def _new_result(ref, role, managing_ref):
    return {"status": "ok", "issue": ref["key"], "url": None, "role": role,
            "managing": managing_ref["key"] if managing_ref else None, "satisfied": False, "unsatisfied": [],
            "evidence": [], "pr": None, "checkboxes": None, "work_issues": [], "blocking": [], "errors": []}


def _unsatisfied(result, kind, message, line=None, url=None):
    result["unsatisfied"].append({"kind": kind, "message": message, "line": line, "url": url})


def _check_pr(result, cell, base, kind, owner, repo):
    if not cell:
        _unsatisfied(result, kind, "PR マージ計画の表に PR が無い" if kind == "pr" else "設定「管理 Issue の PR」に PR が無い")
        return
    url = mergeplan.pr_url(cell, owner, repo)
    data = _need(fetch_pr(url))
    merged = pr_merged(data)
    info = {"url": data["url"], "state": data.get("state"), "merged": merged, "base": data.get("baseRefName")}
    if kind == "pr":
        result["pr"] = info
    else:
        result["managing_pr"] = info
    if not merged:
        _unsatisfied(result, kind, f"PR がマージされていない (状態: {data.get('state')})", url=data["url"])
    elif data.get("baseRefName") != base:
        _unsatisfied(result, kind, f"PR のマージ先 {data.get('baseRefName')} が、PR マージ計画のマージ先 {base} と違う",
                     url=data["url"])
    else:
        result["evidence"].append(data["url"])


def _check_checkboxes(result, body, exclude_common=False):
    parsed = checkboxes.parse(body)
    if "error" in parsed:
        result["errors"].append(parsed["error"])
        return None
    items = [i for i in parsed["items"] if not (exclude_common and i["heading"] == COMMON_HEADING)]
    if not items:
        result["errors"].append("節「クローズ条件」にチェックボックスが無い")
    for item in items:
        if item["state"] in checkboxes.SATISFIED:
            result["evidence"].append(item["evidence"] or item["carved_out"])
        else:
            _unsatisfied(result, "checkbox", f"{item['state']}: {item['text']}", line=item["line"])
    result["checkboxes"] = checkboxes.summarize(items)
    return parsed["items"]


def _read_plan(result, body, name):
    plan = mergeplan.read_region(body)
    if "error" in plan:
        result["errors"].append(f"{name}の PR マージ計画: {plan['error']}")
        return None
    if plan["errors"]:
        result["errors"] += [f"{name}の PR マージ計画: 行 {e['line']}: {e['message']}" if e["line"] else
                             f"{name}の PR マージ計画: {e['message']}" for e in plan["errors"]]
        return None
    return plan


def _row_of(plan, number):
    return next((row for row in plan["rows"] if row["work"]["number"] == number), None)


def _check_working(result, ref, issue, meta, items, managing_ref):
    managing = _need(bodies.fetch_issue(managing_ref))
    managing_meta = _need(fetch_meta(managing_ref))
    plan = _read_plan(result, managing["body"], "管理 Issue ")
    if plan is not None:
        if f"{ref['owner']}/{ref['repo']}".lower() != f"{managing_ref['owner']}/{managing_ref['repo']}".lower():
            result["errors"].append("作業 Issue が管理 Issue と別のリポジトリにある (PR マージ計画の表は #番号 で書くため)")
        else:
            row = _row_of(plan, ref["number"])
            if row is None:
                result["errors"].append(f"管理 Issue の PR マージ計画の表に、作業 Issue #{ref['number']} の行が無い")
            else:
                _check_pr(result, row["pr"], row["base"], "pr", managing_ref["owner"], managing_ref["repo"])
    managing_parsed = checkboxes.parse(managing["body"])
    if "error" in managing_parsed:
        result["errors"].append(f"管理 Issue のクローズ条件: {managing_parsed['error']}")
    elif items is not None:
        expected = _items_text(common_items(managing_parsed["items"]))
        actual = _items_text(copy_items(items))
        if expected != actual:
            _unsatisfied(result, "common", "共通の条件のコピーが、管理 Issue の節「" + COMMON_HEADING + "」と違う",
                         url=managing["url"])
    if _milestone(meta) != _milestone(managing_meta):
        _unsatisfied(result, "milestone", f"マイルストーン {_milestone(meta)!r} が、管理 Issue のマイルストーン "
                                          f"{_milestone(managing_meta)!r} と違う", url=issue["url"])


def _check_managing(result, ref, issue):
    plan = _read_plan(result, issue["body"], "")
    if plan is None:
        return
    for row in plan["rows"]:
        work_ref = refs.parse_ref(f"#{row['work']['number']}", default_repo=f"{ref['owner']}/{ref['repo']}")
        work = _need(fetch_meta(work_ref))
        result["work_issues"].append({"number": work.get("number"), "url": work["url"], "state": work.get("state")})
        if work.get("state") != "CLOSED":
            _unsatisfied(result, "work-issue", f"作業 Issue #{row['work']['number']} が閉じていない", url=work["url"])
    settings = plan["settings"]
    if settings["config"] in ("2", "3"):
        result["managing_pr"] = None
        _check_pr(result, settings["managing_pr"], settings["managing_base"], "managing-pr", ref["owner"], ref["repo"])


def _check_self(result, ref, issue):
    plan = _read_plan(result, issue["body"], "")
    if plan is None:
        return
    if len(plan["rows"]) != 1 or plan["rows"][0]["work"]["number"] != ref["number"]:
        result["errors"].append(f"自己管理 Issue の PR マージ計画の表は、この Issue (#{ref['number']}) の 1 行だけにする")
        return
    row = plan["rows"][0]
    _check_pr(result, row["pr"], row["base"], "pr", ref["owner"], ref["repo"])


def check(ref, role, managing_ref=None):
    """閉じる前の検査。role は ROLES のどれか。role が working なら managing_ref (管理 Issue の参照) が要る。

    返り値は {"status" (ok・unsatisfied・gh_failed), "issue", "url", "role", "managing", "satisfied", "unsatisfied"
    ({"kind", "message", "line", "url"} の配列), "evidence" (根拠の URL の配列。同じ URL は現れた順に 1 回だけ), "pr", "checkboxes", "work_issues",
    "blocking", "errors"} (gh_failed では "gh_error" も持つ)。
    """
    result = _new_result(ref, role, managing_ref)
    try:
        issue = _need(bodies.fetch_issue(ref))
        result["url"] = issue["url"]
        meta = _need(fetch_meta(ref))
        result["blocking"] = open_blocking(meta)
        items = _check_checkboxes(result, issue["body"], exclude_common=(role == "managing"))
        if role == "working":
            _check_working(result, ref, issue, meta, items, managing_ref)
        elif role == "managing":
            _check_managing(result, ref, issue)
        else:
            _check_self(result, ref, issue)
    except _GhFailed as e:
        return {**result, "status": "gh_failed", "gh_error": e.result}
    result["evidence"] = list(dict.fromkeys(result["evidence"]))
    result["satisfied"] = not result["unsatisfied"] and not result["errors"]
    result["status"] = "ok" if result["satisfied"] else "unsatisfied"
    return result


def common_copies(managing_ref):
    """管理 Issue の共通の条件と、開いている作業 Issue (PR マージ計画の表の行) のコピーを比べる。

    返り値は {"status", "issue", "url", "common" (管理 Issue の共通の項目), "outdated" ({"number", "url", "expected",
    "actual"} の配列), "up_to_date", "skipped" (閉じた作業 Issue), "errors"}。
    """
    result = {"status": "ok", "issue": managing_ref["key"], "url": None, "common": [], "outdated": [], "up_to_date": [],
              "skipped": [], "errors": []}
    try:
        managing = _need(bodies.fetch_issue(managing_ref))
        result["url"] = managing["url"]
        plan = _read_plan(result, managing["body"], "")
        parsed = checkboxes.parse(managing["body"])
        if "error" in parsed:
            result["errors"].append(parsed["error"])
        if plan is None or "error" in parsed:
            result["status"] = "unsatisfied"
            return result
        expected = _items_text(common_items(parsed["items"]))
        result["common"] = expected
        for row in plan["rows"]:
            work_ref = refs.parse_ref(f"#{row['work']['number']}", default_repo=f"{managing_ref['owner']}/{managing_ref['repo']}")
            work = _need(bodies.fetch_issue(work_ref))
            entry = {"number": work["number"], "url": work["url"]}
            if work["state"] != "OPEN":
                result["skipped"].append(entry)
                continue
            work_parsed = checkboxes.parse(work["body"])
            actual = [] if "error" in work_parsed else _items_text(copy_items(work_parsed["items"]))
            if actual != expected:
                result["outdated"].append({**entry, "expected": expected, "actual": actual})
            else:
                result["up_to_date"].append(entry)
    except _GhFailed as e:
        return {**result, "status": "gh_failed", "gh_error": e.result}
    result["status"] = "unsatisfied" if result["outdated"] or result["errors"] else "ok"
    return result


# --- 依存先が片付いたこと (R50) ----------------------------------------------------------------------------------

def _reference_patterns(closed_ref, base_repo):
    owner_repo = f"{closed_ref['owner']}/{closed_ref['repo']}"
    patterns = [re.escape(f"https://github.com/{owner_repo}/issues/{closed_ref['number']}") + r"(?![0-9])",
                r"(?<![\w/.-])" + re.escape(f"{owner_repo}#{closed_ref['number']}") + r"(?![0-9])"]
    if base_repo.lower() == owner_repo.lower():
        patterns.append(r"(?<![\w/])#" + str(closed_ref["number"]) + r"(?![0-9])")
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def remove_dependency(body, closed_ref, base_repo):
    """本文の節「依存先」から、閉じた Issue (closed_ref) を指す箇条書きの項目を消す。base_repo は本文の Issue のリポジトリ。

    項目は、行頭の箇条書きの行と、その下の字下げした行。閉じた Issue の URL か `owner/repo#番号` を含む項目と、
    base_repo が閉じた Issue と同じリポジトリなら `#番号` を含む項目を消す。項目が無くなったら、節ごと消す。
    返り値は {"body", "removed" (消した行の配列), "section_removed"}。節が無ければ本文を変えずに返す。
    """
    section = bodies.find_section(body, DEPENDENCIES_SECTION)
    if "error" in section:
        return {"body": body, "removed": [], "section_removed": False}
    lines = bodies.split_lines(body)
    start, end = section["heading_line"] - 1, section["end_line"]
    patterns = _reference_patterns(closed_ref, base_repo)
    blocks, i = [], start + 1
    while i < end:
        if _LIST_ITEM_RE.match(lines[i]):
            j = i + 1
            while j < end and lines[j].strip() and lines[j][:1] in (" ", "\t"):
                j += 1
            blocks.append((i, j))
            i = j
            continue
        i += 1
    remove = [(a, b) for a, b in blocks if any(p.search(lines[a]) for p in patterns)]
    if not remove:
        return {"body": body, "removed": [], "section_removed": False}
    removed = [lines[k].rstrip("\r") for a, b in remove for k in range(a, b)]
    if len(remove) == len(blocks):
        new_lines = lines[:start] + lines[end:]
        return {"body": "\n".join(new_lines), "removed": removed, "section_removed": True}
    drop = {k for a, b in remove for k in range(a, b)}
    new_lines = [line for k, line in enumerate(lines) if k not in drop]
    return {"body": "\n".join(new_lines), "removed": removed, "section_removed": False}


def _issue_value(closed_ref, dependent_ref):
    if f"{closed_ref['owner']}/{closed_ref['repo']}".lower() == f"{dependent_ref['owner']}/{dependent_ref['repo']}".lower():
        return f"#{closed_ref['number']}"
    return closed_ref["key"]


RESOLVED_TEXT = "依存先の Issue {url} が閉じた。"
REMOVED_TEXT = "この Issue の節「依存先」から、その項目を消した。"


def dependents_plan(ref):
    """閉じる Issue (ref) を依存先とする開いた Issue への書き込みを示す (示す)。GitHub には書き込まない。

    返り値は {"status", "issue", "url", "state", "dependents" ({"number", "url", "sha256", "actions", "new_body"} の配列),
    "errors"}。actions は {"action": "comment", "line"} と {"action": "edit-dependencies", "removed", "section_removed"}。
    """
    result = {"status": "ok", "issue": ref["key"], "url": None, "state": None, "dependents": [], "errors": []}
    try:
        meta = _need(fetch_meta(ref))
        result.update(url=meta["url"], state=meta.get("state"))
        for node in open_blocking(meta):
            dependent_ref = refs.parse_ref(node["url"])
            dependent = _need(bodies.fetch_issue(dependent_ref))
            listed = _need(records.list_records(dependent_ref))
            value = _issue_value(ref, dependent_ref)
            base_repo = f"{dependent_ref['owner']}/{dependent_ref['repo']}"
            recorded = any(r["kind"] == "dependency-resolved"
                           and refs.same_issue(refs.parse_ref(r["values"]["issue"], default_repo=base_repo), ref)
                           for r in listed["records"])
            actions = []
            if not recorded:
                actions.append({"action": "comment",
                                "line": records.format_line("dependency-resolved", {"issue": value}, where="comment")["line"]})
            removed = remove_dependency(dependent["body"], ref, base_repo)
            if removed["removed"]:
                actions.append({"action": "edit-dependencies", "removed": removed["removed"],
                                "section_removed": removed["section_removed"]})
            result["dependents"].append({"number": dependent["number"], "url": dependent["url"],
                                         "sha256": dependent["sha256"], "actions": actions, "new_body": removed["body"]})
    except _GhFailed as e:
        return {**result, "status": "gh_failed", "gh_error": e.result}
    return result


def dependents_resolve(ref):
    """dependents_plan の書き込みを行う (実行する)。ref が閉じていなければ書かない。

    返り値は dependents_plan の辞書に {"done" ({"number", "action", "url"} の配列)} を足したもの。gh が失敗したら、そこで
    止めて status を gh_failed にし、それまでの書き込みを done に入れる。もう一度実行すると、書いた記録と消した項目は
    書かない。
    """
    result = dependents_plan(ref)
    result["done"] = []
    if result["status"] != "ok":
        return result
    if result["state"] != "CLOSED":
        result["errors"].append(f"{ref['key']} が閉じていない (閉じてから実行する)")
        result["status"] = "unsatisfied"
        return result
    for dependent in result["dependents"]:
        edited = any(a["action"] == "edit-dependencies" for a in dependent["actions"])
        for action in dependent["actions"]:
            if action["action"] == "comment":
                text = RESOLVED_TEXT.format(url=result["url"]) + (REMOVED_TEXT if edited else "")
                r = gh.run(["issue", "comment", dependent["url"], "--body-file", "-"], mutation=True,
                           stdin=f"{action['line']}\n\n{text}\n")
            else:
                r = bodies.write_body(dependent["url"], dependent["new_body"])
            if gh.failed(r):
                return {**result, "status": "gh_failed", "gh_error": r}
            result["done"].append({"number": dependent["number"], "action": action["action"], "url": dependent["url"]})
    return result


# --- リリース Issue の閉じる前の検査 (R48) -------------------------------------------------------------------------

# どのリリースにも共通する条件 (文書 skills/release-issue-plan/references/release-issue.md の節「項目「完了の条件」」)。
# 1 と 4 は GitHub の状態から判定できないので、スキル release-close が利用者に確認し、記録のコメント close-check に書く
RELEASE_COMMON = (
    "行うと決めたリリースの手順を、最後まで行った",
    "リリースに PR が要るなら、その PR がマージされた",
    "リリースマイルストーンを設定した Issue が、すべて閉じている",
    "実行の中で見つかった、このリリースでは直さない問題を、Issue に切り出した",
)
RELEASE_MANUAL = (RELEASE_COMMON[0], RELEASE_COMMON[3])
DONE_SECTION = "完了の条件"
RELEASE_PR_FIELDS = PR_FIELDS + ",body"


def fetch_milestone_issues(repo, number):
    """マイルストーンを設定した Issue (PR を除く。開いたものも閉じたものも) を読む。REST の issue の配列を返す。"""
    result = gh.run(["api", f"repos/{repo}/issues?milestone={number}&state=all&per_page=100", "--paginate", "--slurp"],
                    expect_json=True)
    if gh.failed(result):
        return None, result
    pages = result["json"]
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        return None, {**result, "json_error": "応答がページの配列 (--slurp の形) ではない"}
    return [i for page in pages for i in page if isinstance(i, dict) and "pull_request" not in i], None


def release_check(ref):
    """リリース Issue を閉じる前の検査 (R48)。読むだけ。

    返り値は {"status", "issue", "url", "state", "satisfied", "unsatisfied" ({"kind", "message", "line", "url"} の配列。kind は
    draft・release-start・pr・pr-link・milestone-issue・checkbox のどれか), "evidence", "manual" (利用者に確認する共通の条件),
    "milestone" ({number, title, url, state}), "prs" ({url, state, merged, base} の配列), "issues_total", "issues_open",
    "checkboxes", "close_check" (記録のコメント close-check result=pass の URL か None), "blocking", "errors"}。
    """
    result = {"status": "ok", "issue": ref["key"], "url": None, "state": None, "satisfied": False, "unsatisfied": [],
              "evidence": [], "manual": list(RELEASE_MANUAL), "milestone": None, "prs": [], "issues_total": None,
              "issues_open": [], "checkboxes": None, "close_check": None, "blocking": [], "errors": []}
    repo = f"{ref['owner']}/{ref['repo']}"
    try:
        issue = _need(bodies.fetch_issue(ref))
        result.update(url=issue["url"], state=issue["state"])
        meta = _need(fetch_meta(ref))
        result["blocking"] = open_blocking(meta)
        title = releaseplan.parse_release_title(issue["title"])
        if "/pull/" in (issue["url"] or "") or title is None or title["number"] != issue["number"]:
            result["errors"].append(f"題名が、リリース Issue の形ではない: {issue['title']!r}")
            result["status"] = "unsatisfied"
            return result
        listed = _need(records.list_records(ref))
        kinds = {r["kind"] for r in listed["records"]}
        if listed["invalid"]:
            result["errors"].append("1 行目の形が違う記録のコメントがある")
        if title["draft"]:
            _unsatisfied(result, "draft", f"題名に {releaseplan.DRAFT_MARK} がある (計画が承認されていない)")
        elif "draft-removed" not in kinds:
            result["errors"].append(f"題名に {releaseplan.DRAFT_MARK} が無いのに、記録のコメント draft-removed が無い (R8)")
        if "release-start" not in kinds:
            _unsatisfied(result, "release-start", "記録のコメント release-start が無い (実行を始めていない)")
        passed = [r for r in listed["records"] if r["kind"] == "close-check" and r["values"].get("result") == "pass"]
        result["close_check"] = passed[-1]["url"] if passed else None
        milestones = _need(releaseplan.fetch_open_milestones(repo, state="all"))
        found = [m for m in milestones if refs.parse_milestone_name(m.get("title")).get("number") == issue["number"]
                 and refs.parse_milestone_name(m.get("title")).get("target") == title["target"]]
        if len(found) != 1:
            result["errors"].append(f"リリースマイルストーンが {len(found)} つある")
        else:
            milestone = found[0]
            result["milestone"] = {"number": milestone.get("number"), "title": milestone.get("title"),
                                   "url": milestone.get("html_url"), "state": milestone.get("state")}
            result["errors"] += releaseplan.check_links(issue, milestone)
            items = _need(fetch_milestone_issues(repo, milestone.get("number")))
            result["issues_total"] = len(items)
            for item in items:
                if item.get("state") != "closed":
                    result["issues_open"].append({"number": item.get("number"), "url": item.get("html_url"),
                                                  "title": item.get("title")})
                    _unsatisfied(result, "milestone-issue", f"マイルストーンの Issue #{item.get('number')} が閉じていない",
                                 url=item.get("html_url"))
        for url in releaseplan.references(issue["body"])["prs"]:
            pr = refs.parse_ref(url)
            if "error" in pr or pr["kind"] != "pull":
                result["errors"].append(f"節「参照」の PR の URL が PR の URL ではない: {url!r}")
                continue
            data = gh.run(["pr", "view", pr["url"], "--json", RELEASE_PR_FIELDS], expect_json=True)
            if gh.failed(data):
                raise _GhFailed(data)
            data = data["json"] or {}
            merged = pr_merged(data)
            result["prs"].append({"url": data.get("url"), "state": data.get("state"), "merged": merged,
                                  "base": data.get("baseRefName")})
            if not merged:
                _unsatisfied(result, "pr", f"PR がマージされていない (状態: {data.get('state')})", url=data.get("url"))
            else:
                result["evidence"].append(data.get("url"))
            if issue["url"] not in (data.get("body") or ""):
                _unsatisfied(result, "pr-link", "PR の本文に、リリース Issue の URL が無い (R47)", url=data.get("url"))
        section = bodies.find_section(issue["body"], DONE_SECTION)
        if "error" in section:
            result["errors"].append(f"本文の{section['error']}")
        else:
            items = checkboxes.parse_lines(section["lines"])
            for item in items:
                if item["state"] in checkboxes.SATISFIED:
                    result["evidence"].append(item["evidence"] or item["carved_out"])
                else:
                    _unsatisfied(result, "checkbox", f"{item['state']}: {item['text']}", line=item["line"])
            result["checkboxes"] = checkboxes.summarize(items)
    except _GhFailed as e:
        return {**result, "status": "gh_failed", "gh_error": e.result}
    result["evidence"] = list(dict.fromkeys(result["evidence"]))
    result["satisfied"] = not result["unsatisfied"] and not result["errors"]
    result["status"] = "ok" if result["satisfied"] else "unsatisfied"
    return result
