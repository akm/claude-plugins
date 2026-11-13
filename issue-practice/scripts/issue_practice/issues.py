"""計画案の節「作る Issue」から Issue を作る。「示す」(plan) と「実行する」(create) の 2 つに分ける (計画の KTD3・KTD5・U2)。

節の書式とスキルが作るラベルの SSOT は、文書 `issue-practice/references/issue-bodies.md` とこのモジュールの定数。
テスト (ファイル `issue-practice/tests/test_issues.py`) が、文書の項目の名前とラベルの表が定数と一致することを確認する。

やり直し (計画の R7・KTD5): 作る Issue の本文の最後の行に `issue-practice: created-from draft=<ファイル名> key=<キー>` を書き、
「実行する」は同じ行を持つ開いた Issue を作り済みとして扱う。作り済みの Issue も、マイルストーン・ラベル・親 Issue・
blocked by を GitHub の今の状態と比べ、足りないものだけを設定する。今の状態が計画案と違えば、上書きせずに誤りにする
(`gh` は、別の親 Issue がある Issue に親を設定すると、エラーにせずに置き換えるため。固定データの README)。

関数は、解析できた値の辞書か、理由を持つ辞書を返す。例外は送出しない (計画案のファイルを開けないときの OSError を除く)。
"""

import os
import re

from issue_practice import bodies, draft, gh, records, refs, releaseplan

SECTION_TITLE = "作る Issue"
FIELDS = ("親 Issue", "依存先の Issue", "マイルストーン", "ラベル")
NONE_VALUE = "なし"
BODY_OPEN = "~~~markdown"
BODY_CLOSE = "~~~"
NO_RELEASE_LABEL = "no-release"

# スキルが作るラベル (計画の R9)。名前・色・説明
LABELS = {
    releaseplan.CURRENT_LABEL: ("0e8a16", "有効なリリース計画 Issue (issue-practice)"),
    NO_RELEASE_LABEL: ("cfd3d7", "どのリリースにも入れない Issue (issue-practice)"),
}
TARGET_LABEL_COLOR = "1d76db"
TARGET_LABEL_DESCRIPTION = "リリース対象 {name} のリリース計画 Issue とリリース Issue (issue-practice)"

_ITEM_RE = re.compile(r"^### (?P<key>[A-Za-z0-9][A-Za-z0-9._-]*): (?P<title>\S.*)$")
_FIELD_RE = re.compile(r"^- (?P<name>[^:]+): (?P<value>\S.*)$")
_TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def managed_label(name):
    """スキルが作るラベルなら (色, 説明)、そうでなければ None。"""
    if name in LABELS:
        return LABELS[name]
    if name.startswith(releaseplan.TARGET_LABEL_PREFIX):
        target = name[len(releaseplan.TARGET_LABEL_PREFIX):]
        if _TARGET_NAME_RE.match(target):
            return TARGET_LABEL_COLOR, TARGET_LABEL_DESCRIPTION.format(name=target)
    return None


def _split(value):
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_issue_ref(text, repo):
    ref = refs.parse_ref(text, default_repo=repo)
    if "error" in ref:
        return None, ref["error"]
    if ref["kind"] == "pull":
        return None, f"PR は書かない (本文の節「依存先」だけに書く): {text}"
    return ref, None


def parse_items(text, repo):
    """計画案の本文から節「作る Issue」を読む。repo は #番号 の参照を解決するリポジトリ (owner/repo)。

    返り値は {"items", "errors"}。items の要素は {"key", "title", "line", "parent", "blocked_by", "milestone", "labels",
    "body"} (parent と blocked_by の要素は refs.parse_ref の結果)。errors は {"line", "message"} の配列。
    """
    lines = [line.rstrip("\r") for line in bodies.split_lines(text)]
    visible = bodies.outside_fences(lines)
    level2 = [i for i in sorted(visible) if bodies.heading(lines[i]) and bodies.heading(lines[i])[0] == 2]
    starts = [i for i in level2 if bodies.heading(lines[i])[1] == SECTION_TITLE]
    errors, items = [], []
    if not starts:
        return {"items": [], "errors": [{"line": None, "message": f"節「{SECTION_TITLE}」(## {SECTION_TITLE}) が無い"}]}
    if len(starts) > 1:
        return {"items": [], "errors": [{"line": starts[1] + 1, "message": f"節「{SECTION_TITLE}」が複数ある"}]}
    start = starts[0]
    end = next((i for i in level2 if i > start), len(lines))
    item, i, seen = None, start + 1, {}

    def error(index, message):
        errors.append({"line": index + 1, "message": message})

    while i < end:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _ITEM_RE.match(line)
        if m:
            if item is not None and item["body"] is None:
                error(item["line"] - 1, f"Issue {item['key']} の本文 ({BODY_OPEN} で囲んだ部分) が無い")
            key = m.group("key")
            if key in seen:
                error(i, f"キー {key} が 2 回ある (行 {seen[key]})")
            seen.setdefault(key, i + 1)
            item = {"key": key, "title": m.group("title").strip(), "line": i + 1, "fields": {}, "body": None}
            items.append(item)
            i += 1
            continue
        if item is None:
            error(i, "「### <キー>: <題名>」の見出しの前に、行がある")
            i += 1
            continue
        if line == BODY_OPEN:
            if item["body"] is not None:
                error(i, f"Issue {item['key']} の本文が 2 つある")
            close = next((j for j in range(i + 1, end) if lines[j].startswith(BODY_CLOSE)), None)
            if close is None or lines[close] != BODY_CLOSE:
                error(i, f"Issue {item['key']} の本文の囲みが閉じていない ({BODY_CLOSE} の行が無いか、"
                         f"本文の中に {BODY_CLOSE} で始まる行がある)")
                return {"items": [], "errors": errors}
            item["body"] = "\n".join(lines[i + 1:close])
            i = close + 1
            continue
        fm = _FIELD_RE.match(line)
        if fm and item["body"] is None:
            name = fm.group("name")
            if name not in FIELDS:
                error(i, f"知らない項目: {name!r} (項目: {'・'.join(FIELDS)})")
            elif name in item["fields"]:
                error(i, f"項目「{name}」が 2 回ある")
            else:
                expected = FIELDS[len(item["fields"])]
                if name != expected:
                    error(i, f"項目の順序が違う (ここは「{expected}」)")
                item["fields"][name] = (i, fm.group("value").strip())
            i += 1
            continue
        error(i, "項目 (- <項目>: <値>) か本文の囲み (~~~markdown) ではない行")
        i += 1
    if item is not None and item["body"] is None:
        error(item["line"] - 1, f"Issue {item['key']} の本文 ({BODY_OPEN} で囲んだ部分) が無い")
    if not items:
        error(start, f"節「{SECTION_TITLE}」に Issue が無い")

    parsed = []
    for item in items:
        missing = [name for name in FIELDS if name not in item["fields"]]
        if missing:
            error(item["line"] - 1, f"Issue {item['key']} に項目が無い: {'・'.join(missing)} (値が無ければ「なし」と書く)")
            continue
        out = {"key": item["key"], "title": item["title"], "line": item["line"], "parent": None, "blocked_by": [],
               "milestone": None, "labels": [], "body": item["body"]}
        index, value = item["fields"]["親 Issue"]
        if value != NONE_VALUE:
            ref, problem = _parse_issue_ref(value, repo)
            if problem:
                error(index, f"親 Issue: {problem}")
            else:
                out["parent"] = ref
        index, value = item["fields"]["依存先の Issue"]
        if value != NONE_VALUE:
            keys = set()
            for text_ref in _split(value):
                ref, problem = _parse_issue_ref(text_ref, repo)
                if problem:
                    error(index, f"依存先の Issue: {problem}")
                elif ref["key"].lower() in keys:
                    error(index, f"依存先の Issue に {ref['key']} が 2 回ある")
                else:
                    keys.add(ref["key"].lower())
                    out["blocked_by"].append(ref)
        index, value = item["fields"]["マイルストーン"]
        if value != NONE_VALUE:
            out["milestone"] = value
        index, value = item["fields"]["ラベル"]
        if value != NONE_VALUE:
            out["labels"] = _split(value)
            if len({label.lower() for label in out["labels"]}) != len(out["labels"]):
                error(index, "同じラベルが 2 回ある")
        if out["milestone"] and NO_RELEASE_LABEL in out["labels"]:
            error(index, f"マイルストーンとラベル {NO_RELEASE_LABEL} の両方がある")
        parsed.append(out)
    errors.sort(key=lambda e: (e["line"] is not None, e["line"] or 0))
    return {"items": parsed, "errors": errors}


def read(path, repo):
    """計画案のファイルを読み、先頭の書式 (draft.parse) と節「作る Issue」を解析する。

    返り値は {"file_name", "items", "errors"}。ファイルを開けなければ OSError を送出する。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    name = os.path.basename(path)
    head = draft.parse(text, name)
    parsed = parse_items(text, repo)
    return {"file_name": name, "items": parsed["items"], "errors": head["errors"] + parsed["errors"]}


def created_from_line(file_name, key):
    return records.format_line("created-from", {"draft": file_name, "key": key}, where="body")["line"]


def created_from(body):
    """本文の最後の空でない行が created-from の行なら、その値 {"draft", "key"}。そうでなければ None。"""
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    if not lines:
        return None
    parsed = records.parse_line(lines[-1], where="body")
    if "errors" in parsed or parsed["kind"] != "created-from":
        return None
    return parsed["values"]


def issue_body(item, file_name):
    return item["body"].rstrip("\n") + "\n\n" + created_from_line(file_name, item["key"]) + "\n"


# --- GitHub から読む -------------------------------------------------------------------------------------------

def _json(result, check, message):
    if gh.failed(result):
        return None, result
    if not check(result["json"]):
        return None, {**result, "json_error": message}
    return result["json"], None


def fetch_labels(repo):
    data, failure = _json(gh.run(["label", "list", "-R", repo, "--json", "name", "--limit", "1000"], expect_json=True),
                          lambda d: isinstance(d, list), "応答がラベルの配列ではない")
    if failure:
        return None, failure
    return {label["name"].lower() for label in data if isinstance(label, dict) and isinstance(label.get("name"), str)}, None


def fetch_open_issues(repo):
    """開いている Issue (PR を除く) を全部読む。REST の issue の配列を返す。"""
    data, failure = _json(gh.run(["api", f"repos/{repo}/issues?state=open&per_page=100", "--paginate", "--slurp"],
                                 expect_json=True),
                          lambda d: isinstance(d, list) and all(isinstance(p, list) for p in d),
                          "応答がページの配列 (--slurp の形) ではない")
    if failure:
        return None, failure
    return [i for page in data for i in page if isinstance(i, dict) and "pull_request" not in i], None


def fetch_ref(ref):
    """参照先の Issue (か PR) の番号・URL・状態を読む。"""
    data, failure = _json(gh.run(["issue", "view", str(ref["number"]), "-R", f"{ref['owner']}/{ref['repo']}",
                                  "--json", "number,url,state,title"], expect_json=True),
                          lambda d: isinstance(d, dict) and isinstance(d.get("url"), str), "応答に url が無い")
    return data, failure


RELATION_FIELDS = "number,url,state,milestone,labels,parent,blockedBy"


def fetch_relations(url):
    """作り済みの Issue のマイルストーン・ラベル・親 Issue・blocked by を読む。"""
    data, failure = _json(gh.run(["issue", "view", url, "--json", RELATION_FIELDS], expect_json=True),
                          lambda d: isinstance(d, dict) and isinstance(d.get("url"), str), "応答に url が無い")
    if failure:
        return None, failure
    blocked = ((data.get("blockedBy") or {}).get("nodes")) or []
    return {"number": data.get("number"), "url": data["url"],
            "milestone": (data.get("milestone") or {}).get("title"),
            "labels": [label.get("name") for label in data.get("labels") or [] if isinstance(label, dict)],
            "parent": (data.get("parent") or {}).get("url"),
            "blocked_by": [node.get("url") for node in blocked if isinstance(node, dict)]}, None


def observe(repo, items):
    """計画案の Issue に関わる GitHub の今の状態を読む。返り値は (状態の辞書, None) か (None, 失敗した gh の結果)。"""
    labels, failure = fetch_labels(repo)
    if failure:
        return None, failure
    milestones, failure = releaseplan.fetch_open_milestones(repo)
    if failure:
        return None, failure
    referenced = {}
    for item in items:
        for ref in ([item["parent"]] if item["parent"] else []) + item["blocked_by"]:
            if ref["key"].lower() in referenced:
                continue
            data, failure = fetch_ref(ref)
            if failure:
                return None, failure
            referenced[ref["key"].lower()] = data
    open_issues, failure = fetch_open_issues(repo)
    if failure:
        return None, failure
    return {"labels": labels, "milestones": {m.get("title") for m in milestones}, "referenced": referenced,
            "open_issues": open_issues}, None


def _same_url(a, b):
    return (a or "").rstrip("/").lower() == (b or "").rstrip("/").lower()


def build(items, state, file_name):
    """「示す」の一覧を作る。返り値は ({"labels_to_create", "items", "errors"}, None) か (None, 失敗した gh の結果)。

    items の要素は {"key", "title", "line", "issue" (作り済みなら {"number", "url"}、無ければ None), "actions"}。
    作り済みの Issue があれば、その関係 (マイルストーン・ラベル・親 Issue・blocked by) を gh で読む。
    """
    errors, labels_to_create, out = [], [], []

    def error(item, message):
        errors.append({"line": item["line"], "message": f"Issue {item['key']}: {message}"})

    for item in items:
        if item["milestone"] and item["milestone"] not in state["milestones"]:
            error(item, f"マイルストーン {item['milestone']!r} が無いか、閉じている")
        for label in item["labels"]:
            if label.lower() in state["labels"] or any(label == l["name"] for l in labels_to_create):
                continue
            managed = managed_label(label)
            if managed is None:
                error(item, f"ラベル {label!r} がリポジトリに無い (スキルが作るラベルではないので、作らない)")
            else:
                labels_to_create.append({"name": label, "color": managed[0], "description": managed[1]})
        for role, ref in [("親 Issue", item["parent"])] + [("依存先の Issue", r) for r in item["blocked_by"]]:
            if ref is None:
                continue
            data = state["referenced"][ref["key"].lower()]
            if "/pull/" in data["url"]:
                error(item, f"{role} {ref['key']} は PR (blocked by と sub-issue は Issue どうしの関係)")
            elif data.get("state") != "OPEN":
                error(item, f"{role} {ref['key']} が閉じている")
            ref["url"] = data["url"]
        existing = [i for i in state["open_issues"]
                    if created_from(i.get("body")) == {"draft": file_name, "key": item["key"]}]
        entry = {"key": item["key"], "title": item["title"], "line": item["line"], "issue": None, "actions": []}
        out.append(entry)
        if len(existing) > 1:
            error(item, "同じ created-from の行を持つ開いた Issue が複数ある ("
                        + ", ".join(i.get("html_url") or "" for i in existing) + ")")
            continue
        parent_url = item["parent"]["url"] if item["parent"] else None
        blocker_urls = [ref["url"] for ref in item["blocked_by"]]
        if not existing:
            entry["actions"].append({"action": "create", "title": item["title"], "milestone": item["milestone"],
                                     "labels": item["labels"]})
            if parent_url:
                entry["actions"].append({"action": "set-parent", "parent": parent_url})
            if blocker_urls:
                entry["actions"].append({"action": "add-blocked-by", "issues": blocker_urls})
            continue
        found = existing[0]
        entry["issue"] = {"number": found.get("number"), "url": found.get("html_url")}
        now, failure = fetch_relations(found.get("html_url"))
        if failure:
            return None, failure
        if item["milestone"] and now["milestone"] != item["milestone"]:
            if now["milestone"]:
                error(item, f"作り済みの Issue に別のマイルストーン {now['milestone']!r} が設定されている (上書きしない)")
            else:
                entry["actions"].append({"action": "set-milestone", "milestone": item["milestone"]})
        missing_labels = [l for l in item["labels"] if l.lower() not in {n.lower() for n in now["labels"]}]
        if missing_labels:
            entry["actions"].append({"action": "add-labels", "labels": missing_labels})
        if parent_url and not _same_url(now["parent"], parent_url):
            if now["parent"]:
                error(item, f"作り済みの Issue に別の親 Issue {now['parent']} が設定されている (上書きしない)")
            else:
                entry["actions"].append({"action": "set-parent", "parent": parent_url})
        missing_blockers = [u for u in blocker_urls if not any(_same_url(u, b) for b in now["blocked_by"])]
        if missing_blockers:
            entry["actions"].append({"action": "add-blocked-by", "issues": missing_blockers})
    return {"labels_to_create": labels_to_create, "items": out, "errors": errors}, None


def plan(path, repo):
    """「示す」。返り値は {"status": "ok" | "unsatisfied" | "gh_failed", "draft", "repo", "labels_to_create", "items",
    "errors"} (gh_failed では "gh_error" も持つ)。"""
    parsed = read(path, repo)
    out = {"draft": parsed["file_name"], "repo": repo, "labels_to_create": [], "items": [], "errors": parsed["errors"]}
    if parsed["errors"]:
        return {**out, "status": "unsatisfied"}, parsed
    state, failure = observe(repo, parsed["items"])
    if failure:
        return {**out, "status": "gh_failed", "gh_error": failure}, parsed
    built, failure = build(parsed["items"], state, parsed["file_name"])
    if failure:
        return {**out, "status": "gh_failed", "gh_error": failure}, parsed
    out.update(built)
    return {**out, "status": "unsatisfied" if out["errors"] else "ok"}, parsed


# --- 書き込み -------------------------------------------------------------------------------------------------

APPROVAL_TEXT = "計画案 {file_name} を利用者が承認し、この Issue を作った。"


def _edit(url, *flags):
    return gh.run(["issue", "edit", url, *flags], mutation=True)


def _record_approval(url, file_name):
    """作った Issue に記録のコメント approval が無ければ書く。返り値は (書いたか, 失敗した gh の結果か None)。"""
    listed, failure = records.list_records(refs.parse_ref(url))
    if failure:
        return False, failure
    if any(r["kind"] == "approval" and r["values"].get("draft") == file_name for r in listed["records"]):
        return False, None
    line = records.format_line("approval", {"draft": file_name}, where="comment")["line"]
    result = gh.run(["issue", "comment", url, "--body-file", "-"], mutation=True,
                    stdin=f"{line}\n\n{APPROVAL_TEXT.format(file_name=file_name)}\n")
    if gh.failed(result):
        return False, result
    return True, None


def create(path, repo, record_approval=False):
    """「実行する」。「示す」と同じ一覧を作り、誤りが無ければ書き込む。

    返り値は「示す」の辞書に {"done" (行った書き込み {"key", "action", "url"} の配列), "issues" ({"key", "url"} の配列)}
    を足したもの。gh が失敗したら、そこで止めて status を gh_failed にし、それまでに行った書き込みを done に入れる。
    """
    result, parsed = plan(path, repo)
    result.update(done=[], issues=[])
    if result["status"] != "ok":
        return result
    done = result["done"]

    def failed(failure):
        return {**result, "status": "gh_failed", "gh_error": failure}

    for label in result["labels_to_create"]:
        r = gh.run(["label", "create", label["name"], "-R", repo, "--color", label["color"],
                    "--description", label["description"]], mutation=True)
        if gh.failed(r):
            return failed(r)
        done.append({"key": None, "action": "create-label", "url": None, "label": label["name"]})
    by_key = {item["key"]: item for item in parsed["items"]}
    for entry in result["items"]:
        item = by_key[entry["key"]]
        url = entry["issue"]["url"] if entry["issue"] else None
        for action in entry["actions"]:
            kind = action["action"]
            if kind == "create":
                args = ["issue", "create", "-R", repo, "--title", item["title"], "--body-file", "-"]
                if item["milestone"]:
                    args += ["--milestone", item["milestone"]]
                for label in item["labels"]:
                    args += ["--label", label]
                r = gh.run(args, mutation=True, stdin=issue_body(item, parsed["file_name"]))
                if gh.failed(r):
                    return failed(r)
                made = refs.parse_ref((r["stdout"].strip().splitlines() or [""])[-1])
                if "error" in made or made["kind"] != "issue":
                    return failed({**r, "json_error": "gh issue create の出力が Issue の URL ではない"})
                url = made["url"]
            elif kind == "set-milestone":
                r = _edit(url, "--milestone", action["milestone"])
            elif kind == "add-labels":
                r = _edit(url, *[flag for label in action["labels"] for flag in ("--add-label", label)])
            elif kind == "set-parent":
                r = _edit(url, "--parent", action["parent"])
            elif kind == "add-blocked-by":
                for blocker in action["issues"]:
                    r = _edit(url, "--add-blocked-by", blocker)
                    if gh.failed(r):
                        return failed(r)
            if gh.failed(r):
                return failed(r)
            done.append({"key": entry["key"], "action": kind, "url": url})
        if record_approval:
            wrote, failure = _record_approval(url, parsed["file_name"])
            if failure:
                return failed(failure)
            if wrote:
                done.append({"key": entry["key"], "action": "record-approval", "url": url})
        result["issues"].append({"key": entry["key"], "url": url})
    return result
