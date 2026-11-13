"""リリース計画 Issue の順番の表の読み取りと、「今のリリース」と「次のリリース」の判定 (計画の R36・U2)。

表の書式と判定の規則の SSOT は、文書 `issue-practice/references/release-plan-table.md` とこのモジュール。
テスト (ファイル `issue-practice/tests/test_releaseplan.py`) が、文書の見出しの行と定数が一致することを確認する。

関数は、解析できた値の辞書か、理由を持つ辞書を返す。例外は送出しない。gh が失敗したときは、失敗した gh の結果を返す。
"""

import re

from issue_practice import bodies, gh, records, refs

SECTION_TITLE = "リリースの順番"
HEADER = ("順", "リリース Issue", "主題")
CURRENT_LABEL = "current"
TARGET_LABEL_PREFIX = "release-target:"
DRAFT_MARK = "[DRAFT]"

_ROW_RE = re.compile(r"^\s*\|(?P<cells>.*)\|\s*$")
_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?\s*$")
_ORDER_RE = re.compile(r"^[1-9][0-9]*$")
_ISSUE_RE = re.compile(r"^#(?P<number>[1-9][0-9]*)$")


def _cells(line):
    m = _ROW_RE.match(line.rstrip("\r"))
    if not m:
        return None
    return [cell.strip() for cell in m.group("cells").split("|")]


def parse_table(body):
    """本文の節「リリースの順番」の表を読む。

    返り値は {"rows": [{"order", "number", "subject", "line"}]} か {"errors": [<理由>]}。行番号は本文の 1 行目を 1 とする。
    """
    section = bodies.find_section(body, SECTION_TITLE)
    if "error" in section:
        return {"errors": [section["error"]]}
    lines = section["lines"]
    visible = bodies.outside_fences([text for _, text in lines])
    table_lines = [(number, text) for i, (number, text) in enumerate(lines) if i in visible and _cells(text) is not None]
    if not table_lines:
        return {"errors": [f"節「{SECTION_TITLE}」に表が無い"]}
    # 表は、連続した表の行の 1 つのまとまり。まとまりが 2 つ以上あれば誤り
    groups, previous = [], None
    for number, text in table_lines:
        if previous is None or number != previous + 1:
            groups.append([])
        groups[-1].append((number, text))
        previous = number
    if len(groups) > 1:
        return {"errors": [f"節「{SECTION_TITLE}」に表が複数ある (行 {', '.join(str(g[0][0]) for g in groups)})"]}
    table = groups[0]
    header_line, header = table[0][0], _cells(table[0][1])
    if tuple(header) != HEADER:
        return {"errors": [f"行 {header_line}: 表の見出しの行が「| {' | '.join(HEADER)} |」ではない"]}
    if len(table) < 2 or not all(_DELIMITER_RE.match(c) for c in _cells(table[1][1])) or len(_cells(table[1][1])) != len(HEADER):
        return {"errors": [f"行 {header_line + 1}: 表の見出しの行の次が、区切りの行 (| --- | --- | --- |) ではない"]}
    rows, errors, seen = [], [], {}
    for number, text in table[2:]:
        cells = _cells(text)
        if len(cells) != len(HEADER):
            errors.append(f"行 {number}: 列の数が {len(HEADER)} ではない")
            continue
        order, issue, subject = cells
        if not _ORDER_RE.match(order):
            errors.append(f"行 {number}: 列「順」が 1 以上の整数ではない: {order!r}")
            continue
        m = _ISSUE_RE.match(issue)
        if not m:
            errors.append(f"行 {number}: 列「リリース Issue」が #<番号> の形ではない: {issue!r}")
            continue
        if not subject:
            errors.append(f"行 {number}: 列「主題」が空")
            continue
        issue_number = int(m.group("number"))
        if issue_number in seen:
            errors.append(f"行 {number}: リリース Issue #{issue_number} が 2 回ある (行 {seen[issue_number]})")
            continue
        seen[issue_number] = number
        rows.append({"order": int(order), "number": issue_number, "subject": subject, "line": number})
    if not errors and not rows:
        errors.append(f"節「{SECTION_TITLE}」の表に行が無い")
    if not errors:
        for expected, row in enumerate(rows, start=1):
            if row["order"] != expected:
                errors.append(f"行 {row['line']}: 列「順」が 1 から始まる連番になっていない ({expected} のところが {row['order']})")
                break
    if errors:
        return {"errors": errors}
    return {"rows": rows}


def choose_plan(plans):
    """ラベル current の付いた開いている計画の配列 ({"number", "created_at", ...}) から、表を読む計画を選ぶ。

    返り値は {"plan" (計画が無ければ None), "swapping" (付け替えの途中か)} か {"error"}。
    """
    if not plans:
        return {"plan": None, "swapping": False}
    if len(plans) == 1:
        return {"plan": plans[0], "swapping": False}
    if len(plans) == 2:
        return {"plan": max(plans, key=lambda p: (p["created_at"] or "", p["number"])), "swapping": True}
    numbers = ", ".join(f"#{p['number']}" for p in plans)
    return {"error": f"ラベル {CURRENT_LABEL} の付いたリリース計画 Issue が {len(plans)} つある ({numbers})。"
                     "付け替えの途中でも 2 つまでなので、決めた形が崩れている"}


def is_draft(title):
    return DRAFT_MARK in (title or "")


def decide(rows, lookup):
    """表の行から「今」と「次」を決める (計画の R36)。

    lookup はリリース Issue の番号を受け取り、({"number", "url", "state", "title", "body"}, None) か (None, 失敗した gh の結果) を
    返す関数。表のすべての行のリリース Issue を読む。
    返り値は {"current", "next", "gh_error", "errors"}。current と next は {"order", "number", "subject", "line", "issue"} か None。
    """
    open_entries = []
    for row in rows:
        issue, failure = lookup(row["number"])
        if failure:
            return {"current": None, "next": None, "gh_error": failure, "errors": []}
        if "/pull/" in (issue.get("url") or ""):
            return {"current": None, "next": None, "gh_error": None,
                    "errors": [f"表の行 {row['line']} の #{row['number']} は PR で、リリース Issue ではない"]}
        if issue["state"] == "OPEN":
            open_entries.append({**row, "issue": issue})
    current = next((e for e in open_entries if not is_draft(e["issue"]["title"])), None)
    if current is None:
        following = open_entries[0] if open_entries else None
    else:
        following = next((e for e in open_entries if e["order"] > current["order"]), None)
    return {"current": current, "next": following, "gh_error": None, "errors": []}


def find_milestone(milestones, number, target):
    """リリース Issue の番号とリリース対象から、リリースマイルストーンを探す。

    milestones は REST の milestone の配列。返り値は {"milestone"} か {"error"}。
    """
    found = []
    for milestone in milestones:
        parsed = refs.parse_milestone_name(milestone.get("title"))
        if "error" in parsed or parsed["number"] != number or parsed["target"] != target:
            continue
        found.append(milestone)
    if not found:
        return {"error": f"リリース Issue #{number} のリリースマイルストーン (R{number} "
                         f"{target + ' ' if target else ''}(主題)) が無いか、閉じている"}
    if len(found) > 1:
        return {"error": f"リリース Issue #{number} のリリースマイルストーンが複数ある "
                         f"({', '.join(repr(m.get('title')) for m in found)})"}
    return {"milestone": found[0]}


def check_links(issue, milestone):
    """リリース Issue とリリースマイルストーンが、お互いの URL を持つか。誤りの配列を返す。"""
    errors = []
    if issue["url"] not in (milestone.get("description") or ""):
        errors.append(f"マイルストーン {milestone.get('title')!r} の説明に、リリース Issue の URL ({issue['url']}) が無い")
    if (milestone.get("html_url") or "") not in (issue.get("body") or "") or not milestone.get("html_url"):
        errors.append(f"リリース Issue #{issue['number']} の本文に、マイルストーンの URL ({milestone.get('html_url')}) が無い")
    return errors


# --- GitHub から読む -------------------------------------------------------------------------------------------

def fetch_targets(repo):
    """リポジトリのラベル release-target:<名前> から、リリース対象の名前の配列を返す。返り値は (名前の配列, None) か (None, 失敗)。"""
    result = gh.run(["label", "list", "-R", repo, "--json", "name", "--limit", "1000"], expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, list):
        return None, {**result, "json_error": "応答がラベルの配列ではない"}
    names = [label.get("name") for label in data if isinstance(label, dict)]
    return sorted(n[len(TARGET_LABEL_PREFIX):] for n in names if isinstance(n, str) and n.startswith(TARGET_LABEL_PREFIX)), None


def fetch_plans(repo, target):
    """ラベル current (とリリース対象のラベル) の付いた開いている Issue を返す。返り値は (計画の配列, None) か (None, 失敗)。"""
    args = ["issue", "list", "-R", repo, "--state", "open", "--label", CURRENT_LABEL]
    if target:
        args += ["--label", TARGET_LABEL_PREFIX + target]
    args += ["--json", "number,url,title,body,createdAt", "--limit", "100"]
    result = gh.run(args, expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, list):
        return None, {**result, "json_error": "応答が Issue の配列ではない"}
    return [{"number": d.get("number"), "url": d.get("url"), "title": d.get("title"), "body": d.get("body") or "",
             "created_at": d.get("createdAt")} for d in data if isinstance(d, dict)], None


def fetch_release_issue(repo, number):
    result = gh.run(["issue", "view", str(number), "-R", repo, "--json", "number,url,state,title,body"], expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, dict):
        return None, {**result, "json_error": "応答が Issue のオブジェクトではない"}
    return {"number": data.get("number"), "url": data.get("url"), "state": data.get("state"), "title": data.get("title"),
            "body": data.get("body") or ""}, None


def fetch_open_milestones(repo):
    result = gh.run(["api", f"repos/{repo}/milestones?state=open&per_page=100", "--paginate", "--slurp"], expect_json=True)
    if gh.failed(result):
        return None, result
    pages = result["json"]
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        return None, {**result, "json_error": "応答がページの配列 (--slurp の形) ではない"}
    return [m for page in pages for m in page if isinstance(m, dict)], None


def _release_output(entry, milestone, running):
    issue = entry["issue"]
    return {"order": entry["order"], "number": issue["number"], "url": issue["url"], "title": issue["title"],
            "subject": entry["subject"], "draft": is_draft(issue["title"]), "running": running,
            "milestone": {"number": milestone.get("number"), "title": milestone.get("title"), "url": milestone.get("html_url")},
            "selectable": True, "reason": None}


def current_and_next(repo, target=None, carve_out=False):
    """リポジトリ repo (owner/repo) の「今」と「次」を決める。

    返り値は {"status": "ok" | "unsatisfied" | "gh_failed", ...}。ok と unsatisfied では {"target", "targets", "plan",
    "swapping", "current", "next", "errors"}、gh_failed では {"gh_error"} を持つ。
    """
    out = {"repo": repo, "target": target, "targets": [], "plan": None, "swapping": False, "current": None, "next": None,
           "errors": []}

    def failed(failure):
        return {**out, "status": "gh_failed", "gh_error": failure}

    def unsatisfied(*errors):
        out["errors"] += list(errors)
        return {**out, "status": "unsatisfied"}

    targets, failure = fetch_targets(repo)
    if failure:
        return failed(failure)
    out["targets"] = targets
    if targets and not target:
        return unsatisfied(f"リリース対象が複数ある ({', '.join(targets)})。--target でどのリリース対象かを指定する")
    if target and target not in targets:
        return unsatisfied(f"リリース対象 {target!r} のラベル {TARGET_LABEL_PREFIX}{target} が無い")
    plans, failure = fetch_plans(repo, target)
    if failure:
        return failed(failure)
    chosen = choose_plan(plans)
    if "error" in chosen:
        return unsatisfied(chosen["error"])
    out["swapping"] = chosen["swapping"]
    plan = chosen["plan"]
    if plan is None:
        return {**out, "status": "ok"}
    out["plan"] = {"number": plan["number"], "url": plan["url"], "title": plan["title"], "created_at": plan["created_at"]}
    table = parse_table(plan["body"])
    if "errors" in table:
        return unsatisfied(*(f"リリース計画 Issue #{plan['number']} の{e}" if not e.startswith("行 ")
                             else f"リリース計画 Issue #{plan['number']} の本文の{e}" for e in table["errors"]))
    decided = decide(table["rows"], lambda number: fetch_release_issue(repo, number))
    if decided["gh_error"]:
        return failed(decided["gh_error"])
    if decided["errors"]:
        return unsatisfied(*decided["errors"])
    if decided["current"] is None and decided["next"] is None:
        return {**out, "status": "ok"}
    milestones, failure = fetch_open_milestones(repo)
    if failure:
        return failed(failure)
    errors = []
    for name in ("current", "next"):
        entry = decided[name]
        if entry is None:
            continue
        found = find_milestone(milestones, entry["number"], target)
        if "error" in found:
            errors.append(found["error"])
            continue
        errors += check_links(entry["issue"], found["milestone"])
        running = False
        if name == "current":
            ref = refs.parse_ref(entry["issue"]["url"])
            listed, failure = records.list_records(ref)
            if failure:
                return failed(failure)
            if listed["invalid"]:
                errors.append(f"リリース Issue #{entry['number']} に、1 行目の形が違う記録のコメントがある "
                              f"({', '.join(i['url'] or '' for i in listed['invalid'])})")
            kinds = {r["kind"] for r in listed["records"]}
            if "draft-removed" not in kinds:
                errors.append(f"リリース Issue #{entry['number']} は題名に {DRAFT_MARK} が無いのに、"
                              "記録のコメント draft-removed が無い")
            running = "release-start" in kinds
        out[name] = _release_output(entry, found["milestone"], running)
    if errors:
        out["current"], out["next"] = None, None
        return unsatisfied(*errors)
    if carve_out and out["current"] and out["current"]["running"]:
        out["current"]["selectable"] = False
        out["current"]["reason"] = "リリースの実行中に切り出すときは、今のリリースを選べない (計画の R13)"
    return {**out, "status": "ok"}
