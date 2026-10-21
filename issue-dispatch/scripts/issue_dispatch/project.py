"""Project (GitHub Projects) の読み書き。項目の一覧 (`items`)・フィールドと選択肢とワークフローの検査 (`check`)・
不足の作成 (`add_fields`)・Status とフィールドの書き込み。様式の正本は
issue-dispatch/skills/issue-dispatch/references/project-schema.md。

GraphQL は同じディレクトリの graphql/*.graphql を `gh api graphql` で実行する (操作名で偽の gh が見分ける)。
書き込みは `gh project item-edit` と `gh project field-create` と mutation で、どれも gh.run の mutation=True で行う。
"""

import json
import os

from issue_dispatch import gh, ids

GRAPHQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphql")

# 独自フィールド (名前 → 型)。Agent stuck state の値は STUCK_STATES
CUSTOM_FIELDS = {"Agent session ID": "TEXT", "Agent session title": "TEXT", "Agent stuck state": "SINGLE_SELECT"}
STUCK_STATES = ("idle-no-progress", "deadline-passed", "session-missing", "manager-stopped", "waiting-for-user")
# Status の選択肢。Todo・In Progress・Done は Project が最初から持ち、ほかの 3 つはこの仕組みが足す (色と説明は足すときの値)
STATUS_OPTIONS = ("Todo", "Ready", "In Progress", "In review", "Blocked", "Done")
ADDED_STATUS_OPTIONS = {"Ready": ("GREEN", "着手してよい"), "In review": ("BLUE", "PR が ready for review"),
                        "Blocked": ("RED", "ほかの Issue か小さな PR を待つ")}
# 管理のセッションが書く Status (R2)。Done は書かない
MANAGER_STATUSES = ("Todo", "Ready", "Blocked", "In Progress", "In review")
REQUIRED_WORKFLOWS = ("Item closed",)
RECOMMENDED_WORKFLOWS = ("Item added to project", "Item reopened")
NOTICE_IF_ENABLED_WORKFLOWS = ("Auto-add to project",)         # 有効なら、Ready にする前に中身を確かめるよう案内する
DISCOURAGED_WORKFLOWS = ("Pull request linked to issue",)      # 有効なら無効を推奨する
EVENT_TYPES = ("ClosedEvent", "ReopenedEvent", "LabeledEvent", "UnlabeledEvent", "BlockedByAddedEvent",
               "BlockedByRemovedEvent", "ProjectV2ItemStatusChangedEvent", "AddedToProjectV2Event", "RemovedFromProjectV2Event")


def parse_project(text):
    """`owner/number` を {"owner", "number"} にする。読めなければ None。"""
    if not isinstance(text, str) or "/" not in text:
        return None
    owner, _, number = text.partition("/")
    if not owner or not number.isdigit() or int(number) < 1:
        return None
    return {"owner": owner, "number": int(number)}


def load_query(name):
    with open(os.path.join(GRAPHQL_DIR, f"{name}.graphql"), encoding="utf-8") as f:
        return "".join(line for line in f if not line.lstrip().startswith("#"))


def graphql(name, variables, mutation=False, timeout=gh.DEFAULT_TIMEOUT):
    """graphql/<name>.graphql を変数つきで実行する。

    返り値は (data, problem, errors)。data が読めれば problem は None で、errors には GraphQL が data と一緒に返した
    errors (一部の項目だけ読めないときなど) の配列が入る (無ければ空)。data が無ければ problem に失敗の説明が入る。
    """
    # 本文 (query と variables) を JSON で標準入力に渡す。-F は配列やオブジェクトを JSON として読まない (文字列のまま渡す) ので使わない
    body = {"query": load_query(name), "variables": {k: v for k, v in variables.items() if v is not None}}
    r = gh.run(["api", "graphql", "--input", "-"], timeout=timeout, mutation=mutation, expect_json=True,
               stdin=json.dumps(body, ensure_ascii=False))
    if r["failure"] and r["json"] is None:
        return None, {"failure": r["failure"], "message": r["stderr_tail"] or r["json_error"] or "", "exit_code": r["exit_code"]}, []
    body = r["json"] if isinstance(r["json"], dict) else {}
    data = body.get("data")
    errors = body.get("errors") or []
    if data is None:
        return None, {"failure": r["failure"] or "other", "message": json.dumps(errors, ensure_ascii=False) if errors else (r["stderr_tail"] or r["json_error"] or ""),
                      "exit_code": r["exit_code"]}, errors
    return data, None, errors


def _project_node(data):
    owner = data.get("repositoryOwner") or {}
    return owner.get("projectV2")


def read_meta(project):
    """フィールド・選択肢・ワークフローを読む。返り値: {"status": "ok", "project": {...}, "rate_limit"} か {"status": "error", ...}。"""
    data, problem, errors = graphql("project-meta", {"owner": project["owner"], "number": project["number"]})
    if problem:
        return {"status": "error", **problem}
    node = _project_node(data)
    if node is None:
        return {"status": "error", "failure": "other", "message": f"Project {project['owner']}/{project['number']} が無いか読めない" +
                (f" ({json.dumps(errors, ensure_ascii=False)})" if errors else ""), "exit_code": 0}
    fields = {}
    for f in node["fields"]["nodes"]:
        if not f:
            continue
        fields[f["name"]] = {"id": f["id"], "data_type": f["dataType"],
                             "options": [{"id": o["id"], "name": o["name"], "color": o.get("color"), "description": o.get("description", "")}
                                         for o in f.get("options", [])]}
    workflows = {w["name"]: {"id": w["id"], "number": w["number"], "enabled": w["enabled"]} for w in node["workflows"]["nodes"]}
    return {"status": "ok", "project": {"id": node["id"], "title": node["title"], "url": node["url"], "owner": project["owner"],
                                        "number": project["number"], "fields": fields, "workflows": workflows},
            "rate_limit": data.get("rateLimit"), "warnings": errors}


def check(meta_project):
    """フィールド・Status の選択肢・ワークフローの不足と案内を列挙する (gh は実行しない)。"""
    fields = meta_project["fields"]
    missing_fields = []
    for name, data_type in CUSTOM_FIELDS.items():
        f = fields.get(name)
        if f is None:
            missing_fields.append({"name": name, "data_type": data_type, "options": list(STUCK_STATES) if name == "Agent stuck state" else []})
        elif f["data_type"] != data_type:
            missing_fields.append({"name": name, "data_type": data_type, "problem": f"型が {f['data_type']} (期待は {data_type})"})
        elif name == "Agent stuck state":
            have = {o["name"] for o in f["options"]}
            lacking = [v for v in STUCK_STATES if v not in have]
            if lacking:
                missing_fields.append({"name": name, "data_type": data_type, "problem": f"値 {', '.join(lacking)} が無い", "options": lacking})
    status = fields.get("Status")
    missing_options = []
    update_options = []
    if status is None or status["data_type"] != "SINGLE_SELECT":
        missing_options = list(STATUS_OPTIONS)
    else:
        have = {o["name"] for o in status["options"]}
        missing_options = [name for name in STATUS_OPTIONS if name not in have]
        if missing_options:
            update_options.append(_options_proposal("Status", status, missing_options, ADDED_STATUS_OPTIONS))
    stuck = fields.get("Agent stuck state")
    if stuck is not None and stuck["data_type"] == "SINGLE_SELECT":
        lacking = [v for v in STUCK_STATES if v not in {o["name"] for o in stuck["options"]}]
        if lacking:
            update_options.append(_options_proposal("Agent stuck state", stuck, lacking, {}))
    workflows = meta_project["workflows"]
    enabled = {name for name, w in workflows.items() if w["enabled"]}
    wf = {
        "required_disabled": [n for n in REQUIRED_WORKFLOWS if n not in enabled],
        "recommended_disabled": [n for n in RECOMMENDED_WORKFLOWS if n not in enabled],  # 一覧に無いものも無効として数える
        "notice_enabled": [n for n in NOTICE_IF_ENABLED_WORKFLOWS if n in enabled],
        "discouraged_enabled": [n for n in DISCOURAGED_WORKFLOWS if n in enabled],
    }
    field_create = []
    for f in missing_fields:
        if "problem" in f:
            continue  # 型の違いは作り直しが要るので案を出さず報告だけ。既にあるフィールドの値の不足は update_options が案を持つ
        cmd = ["project", "field-create", str(meta_project["number"]), "--owner", meta_project["owner"], "--name", f["name"],
               "--data-type", f["data_type"]]
        if f["options"]:
            cmd += ["--single-select-options", ",".join(f["options"])]
        field_create.append(cmd)
    return {"ok": not missing_fields and not missing_options and not wf["required_disabled"],
            "missing_fields": missing_fields, "missing_status_options": missing_options, "workflows": wf,
            "proposals": {"field_create": field_create, "update_options": update_options}}


def _options_proposal(field_name, field, lacking, colors):
    """単一選択のフィールドに選択肢を足す updateProjectV2Field の入力。既存の選択肢を id 付きで含める (含めないと消える。U1)。"""
    options = [{"id": o["id"], "name": o["name"], "color": o["color"] or "GRAY", "description": o["description"] or ""}
               for o in field["options"]]
    for name in lacking:
        color, description = colors.get(name, ("GRAY", ""))
        options.append({"name": name, "color": color, "description": description})
    return {"field": field_name, "fieldId": field["id"], "options": options}


def add_fields(meta_project, checked):
    """check の案を実行する (承認を得た後に呼ぶ)。不足のフィールドを gh project field-create で作り、単一選択のフィールド
    (Status・Agent stuck state) の選択肢を既存の id を保って足す。返り値は実行ごとの結果の配列。"""
    results = []
    for cmd in checked["proposals"]["field_create"]:
        r = gh.run(cmd, mutation=True, expect_json=False)
        results.append({"action": "field-create", "args": cmd, "ok": r["failure"] is None, "failure": r["failure"], "stderr": r["stderr_tail"]})
    for proposal in checked["proposals"]["update_options"]:
        data, problem, errors = graphql("update-status-options", {"fieldId": proposal["fieldId"], "options": proposal["options"]}, mutation=True)
        results.append({"action": "update-options", "field": proposal["field"], "ok": problem is None and not errors,
                        "failure": (problem or {}).get("failure"), "stderr": (problem or {}).get("message", ""), "errors": errors or None})
    return results


# ----- 項目の一覧 -----

def _ref(issue_node):
    return f"{issue_node['repository']['nameWithOwner']}#{issue_node['number']}"


def _event(node):
    kind = node.get("__typename")
    e = {"type": kind, "at": node.get("createdAt")}
    if kind == "ClosedEvent":
        closer = node.get("closer") or {}
        e.update({"state_reason": node.get("stateReason"), "closer_pr": closer.get("number") if closer.get("__typename") == "PullRequest" else None})
    elif kind in ("LabeledEvent", "UnlabeledEvent"):
        e["label"] = (node.get("label") or {}).get("name")
    elif kind in ("BlockedByAddedEvent", "BlockedByRemovedEvent"):
        b = node.get("blockingIssue") or {}
        e["blocking"] = _ref(b) if b.get("repository") else None
    elif kind == "ProjectV2ItemStatusChangedEvent":
        e.update({"status": node.get("status"), "previous_status": node.get("previousStatus"), "was_automated": node.get("wasAutomated"),
                  "project_number": (node.get("project") or {}).get("number")})
    elif kind in ("AddedToProjectV2Event", "RemovedFromProjectV2Event"):
        e["project_number"] = (node.get("project") or {}).get("number")
    return e


def _comment(node):
    return {"id": node["id"], "database_id": node.get("databaseId"), "url": node.get("url"), "created_at": node.get("createdAt"),
            "author": (node.get("author") or {}).get("login"), "body": node.get("body", "")}


def _more_pages(name, repo, number, first_page, key, convert):
    """コメントか出来事の続きのページを読んで、変換した要素の配列を返す。読めなければ問題を返す。"""
    nodes = [convert(n) for n in first_page["nodes"] if n]
    info = first_page.get("pageInfo") or {}
    owner, _, repo_name = repo.partition("/")
    while info.get("hasNextPage"):
        data, problem, errors = graphql(name, {"owner": owner, "name": repo_name, "number": number, "after": info.get("endCursor")})
        if problem:
            return nodes, problem
        issue = (data.get("repository") or {}).get("issue")
        if not issue or not isinstance(issue.get(key), dict):
            return nodes, {"failure": "other", "message": "続きのページで Issue を読めない (移された・消された、または " +
                           json.dumps(errors, ensure_ascii=False) + ")", "exit_code": 0}
        page = issue[key]
        nodes += [convert(n) for n in page["nodes"] if n]
        info = page.get("pageInfo") or {}
    return nodes, None


def simplify_item(node, position):
    """GraphQL の項目を、後の単位が読む形にする。Issue 以外の項目 (draft issue・PR) は content を None にして返す。"""
    content = node.get("content") or {}
    fields = {}
    status = None
    for fv in node["fieldValues"]["nodes"]:
        if not fv or not fv.get("field"):
            continue
        name = fv["field"]["name"]
        if name == "Status":
            status = {"name": fv.get("name"), "option_id": fv.get("optionId"), "updated_at": fv.get("updatedAt")}
        elif "text" in fv:
            fields[name] = {"text": fv.get("text"), "updated_at": fv.get("updatedAt")}
        else:
            fields[name] = {"name": fv.get("name"), "option_id": fv.get("optionId"), "updated_at": fv.get("updatedAt")}
    item = {"item_id": node["id"], "position": position, "item_updated_at": node.get("updatedAt"), "status": status, "fields": fields,
            "content_type": content.get("__typename"), "key": None}
    if content.get("__typename") != "Issue":
        return item, []
    repo = content["repository"]["nameWithOwner"]
    sub = content.get("subIssuesSummary") or {}
    parent = content.get("parent")
    item.update({
        "key": _ref(content), "repo": repo, "number": content["number"], "url": content["url"], "title": content["title"],
        "state": content["state"], "created_at": content.get("createdAt"), "author": (content.get("author") or {}).get("login"),
        "visibility": content["repository"].get("visibility"), "in_organization": content["repository"].get("isInOrganization"),
        "assignees": [a["login"] for a in content["assignees"]["nodes"]],
        "labels": [l["name"] for l in content["labels"]["nodes"]],
        "parent": _ref(parent) if parent and parent.get("repository") else None,
        "sub_issues": {"total": sub.get("total", 0), "completed": sub.get("completed", 0)},
        "is_parent": bool(sub.get("total")),
        "blocked_by": [{"key": _ref(b), "url": b["url"], "state": b["state"]} for b in content["blockedBy"]["nodes"]],
        "body_edits": [{"editor": (e.get("editor") or {}).get("login"), "edited_at": e.get("editedAt"), "deleted_at": e.get("deletedAt")}
                       for e in content["userContentEdits"]["nodes"]],
        "prs": [{"number": p["number"], "url": p["url"], "state": p["state"], "draft": p["isDraft"], "merged": p["merged"],
                 "created_at": p.get("createdAt"), "merged_at": p.get("mergedAt"), "closed_at": p.get("closedAt"),
                 "author": (p.get("author") or {}).get("login"), "base_ref": p.get("baseRefName")}
                for p in content["closedByPullRequestsReferences"]["nodes"]],
    })
    problems = []
    # 入れ子の connection は続きのページを読まない (件数の上限は上げてある)。超えていれば、欠けを知らせる
    for key, what in (("labels", "labels"), ("blockedBy", "blocked_by"), ("userContentEdits", "body_edits"),
                      ("closedByPullRequestsReferences", "prs")):
        if (content.get(key, {}).get("pageInfo") or {}).get("hasNextPage"):
            problems.append({"item": item["key"], "what": f"{what}-truncated", "failure": "other",
                             "message": f"{what} が 1 ページ (最初の {len(content[key]['nodes'])} 件) に収まらず、残りを読んでいない", "exit_code": 0})
    if (node["fieldValues"].get("pageInfo") or {}).get("hasNextPage"):
        problems.append({"item": item["key"], "what": "fields-truncated", "failure": "other",
                         "message": "フィールドの値が 1 ページに収まらず、残りを読んでいない", "exit_code": 0})
    comments, problem = _more_pages("issue-comments", repo, content["number"], content["comments"], "comments", _comment)
    if problem:
        problems.append({"item": item["key"], "what": "comments", **problem})
    events, problem = _more_pages("issue-timeline", repo, content["number"], content["timelineItems"], "timelineItems", _event)
    if problem:
        problems.append({"item": item["key"], "what": "events", **problem})
    item["comments"] = comments
    item["events"] = sorted(events, key=lambda e: (e.get("at") or "", EVENT_TYPES.index(e["type"]) if e["type"] in EVENT_TYPES else 99))
    return item, problems


def items(project):
    """項目の一覧を位置の順に全部読む。返り値: {"status": "ok", "project_id", "items": [...], "problems": [...], "rate_limit"} か
    {"status": "error", ...} (最初のページが読めないとき)。続きのページやコメントの続きが読めなかったときは problems に入れて止める。"""
    result_items = []
    problems = []
    after = None
    project_id = None
    rate = None
    position = 0
    while True:
        data, problem, errors = graphql("items", {"owner": project["owner"], "number": project["number"], "after": after})
        if problem:
            if not result_items:
                return {"status": "error", **problem}
            problems.append({"what": "items-page", "after": after, **problem})
            break
        node = _project_node(data)
        if node is None:
            message = f"Project {project['owner']}/{project['number']} が無いか読めない" + (f" ({json.dumps(errors, ensure_ascii=False)})" if errors else "")
            if not result_items:
                return {"status": "error", "failure": "other", "message": message, "exit_code": 0}
            problems.append({"what": "items-page", "after": after, "failure": "other", "message": message, "exit_code": 0})
            break
        if errors:
            # data と一緒に返った errors (一部の項目だけ読めない、など)。読めた項目は返し、読めなかったことを知らせる
            problems.append({"what": "graphql-errors", "after": after, "errors": errors})
        project_id = node["id"]
        rate = data.get("rateLimit")
        for n in node["items"]["nodes"]:
            if not n:
                continue
            position += 1
            item, item_problems = simplify_item(n, position)
            result_items.append(item)
            problems += item_problems
        info = node["items"].get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    return {"status": "ok" if not problems else "partial", "project_id": project_id, "items": result_items, "problems": problems, "rate_limit": rate}


# ----- 書き込み -----

def set_status(meta_project, item_id, status):
    """Status を書く。管理のセッションが書く 5 つ以外 (Done を含む) は gh を実行せずに拒否する (R2)。"""
    if status not in MANAGER_STATUSES:
        return {"status": "rejected", "message": f"Status {status!r} は書かない (書けるのは {', '.join(MANAGER_STATUSES)}。Done は組み込みワークフローが書く)"}
    field = meta_project["fields"].get("Status")
    option = next((o for o in (field or {}).get("options", []) if o["name"] == status), None)
    if field is None or option is None:
        return {"status": "rejected", "message": f"Project の Status に選択肢 {status!r} が無い (project check で足す)"}
    r = gh.run(["project", "item-edit", "--project-id", meta_project["id"], "--id", item_id, "--field-id", field["id"],
                "--single-select-option-id", option["id"]], mutation=True)
    if r["failure"]:
        return {"status": "error", "failure": r["failure"], "message": r["stderr_tail"]}
    return {"status": "ok", "item_id": item_id, "field": "Status", "value": status}


def set_text_field(meta_project, item_id, field_name, text):
    """テキストのフィールド (Agent session ID・Agent session title) を書く。text が None なら空にする。1 回に 1 フィールド。"""
    field = meta_project["fields"].get(field_name)
    if field is None or field["data_type"] != "TEXT":
        return {"status": "rejected", "message": f"Project にテキストのフィールド {field_name!r} が無い (project check で足す)"}
    args = ["project", "item-edit", "--project-id", meta_project["id"], "--id", item_id, "--field-id", field["id"]]
    args += ["--clear"] if text is None else ["--text", text]
    r = gh.run(args, mutation=True)
    if r["failure"]:
        return {"status": "error", "failure": r["failure"], "message": r["stderr_tail"]}
    return {"status": "ok", "item_id": item_id, "field": field_name, "value": text}


def set_single_select_field(meta_project, item_id, field_name, value):
    """単一選択のフィールド (Agent stuck state) を書く。value が None なら空にする。選択肢に無い値は gh を実行せずに拒否する。"""
    field = meta_project["fields"].get(field_name)
    if field is None or field["data_type"] != "SINGLE_SELECT":
        return {"status": "rejected", "message": f"Project に単一選択のフィールド {field_name!r} が無い (project check で足す)"}
    args = ["project", "item-edit", "--project-id", meta_project["id"], "--id", item_id, "--field-id", field["id"]]
    if value is None:
        args.append("--clear")
    else:
        option = next((o for o in field["options"] if o["name"] == value), None)
        if option is None:
            return {"status": "rejected", "message": f"{field_name} に選択肢 {value!r} が無い (選択肢は {', '.join(o['name'] for o in field['options'])})"}
        args += ["--single-select-option-id", option["id"]]
    r = gh.run(args, mutation=True)
    if r["failure"]:
        return {"status": "error", "failure": r["failure"], "message": r["stderr_tail"]}
    return {"status": "ok", "item_id": item_id, "field": field_name, "value": value}
