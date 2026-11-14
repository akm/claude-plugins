"""管理 Issue (か自己管理 Issue) の計画案の解析と、計画案を GitHub に書く「示す」(plan) と「実行する」(apply)
(計画の U3・KTD3・KTD5・KTD7・KTD8・R6・R7・R19・R26・R49)。

計画案の書式の SSOT は、文書 `issue-practice/skills/managing-issue-plan/references/merge-plan.md` の節「管理 Issue の計画案」と
このモジュールの定数。テスト (ファイル `issue-practice/tests/test_managing.py`) が、文書の節の表と定数が一致することを確認する。

「実行する」は、次の順に書く。途中で失敗しても、同じ計画案でやり直せる (作り済みの作業 Issue は作らず、書いた本文は書かない)。
1. 節「作る Issue」の作業 Issue を作る (モジュール issues の create。作業 Issue ごとに approval の記録も書く)
2. PR マージ計画の表のキーを、作った作業 Issue の番号に置き換え、表から図を作る
3. 計画する Issue の本文の節「クローズ条件」と「PR マージ計画」を書き換える (本文が計画案を作ったときから変わっていれば書かない)
4. 計画する Issue に、記録のコメント approval を書く

関数は、結果の辞書を返す。例外は送出しない (計画案のファイルを開けないときの OSError を除く)。
"""

import os
import re

from issue_practice import bodies, closecheck, draft, gh, issues, mergeplan, records, refs

SECTIONS = ("対象", "クローズ条件", "PR マージ計画", "作る Issue")
TARGET_FIELDS = ("Issue", "種類")
KINDS = ("管理 Issue", "自己管理 Issue")
MANAGING, SELF_MANAGING = KINDS
CLOSING_SECTION = "クローズ条件"
MERGE_PLAN_SECTION = "PR マージ計画"
CLOSING_REGION = "closing-conditions"
APPROVAL_TEXT = "計画案 {file_name} を利用者が承認し、この Issue の節「クローズ条件」と「PR マージ計画」に書いた。"

_FIELD_RE = re.compile(r"^- (?P<name>[^:]+): (?P<value>\S.*)$")
_MARK_RE = re.compile(r"^\s*<!-- /?issue-practice:")


def _section(text, title):
    found = bodies.find_section(text, title)
    if "error" in found:
        return None
    return found


def _parse_target(section, sources, errors):
    fields = {}
    for number, line in section["lines"]:
        if not line.strip():
            continue
        m = _FIELD_RE.match(line)
        if not m or m.group("name") not in TARGET_FIELDS or m.group("name") in fields:
            errors.append({"line": number, "message": f"節「対象」の行は「- {TARGET_FIELDS[0]}: <URL>」と「- {TARGET_FIELDS[1]}: <種類>」"})
            continue
        fields[m.group("name")] = (number, m.group("value").strip())
    if set(fields) != set(TARGET_FIELDS):
        errors.append({"line": section["heading_line"], "message": f"節「対象」に「{TARGET_FIELDS[0]}」と「{TARGET_FIELDS[1]}」の両方を書く"})
        return None
    line, value = fields["Issue"]
    ref = refs.parse_ref(value)
    if "error" in ref or ref["kind"] != "issue":
        errors.append({"line": line, "message": f"項目「Issue」が Issue の URL ではない: {value!r}"})
        return None
    source = next((s for s in sources if refs.same_issue(refs.parse_ref(s["url"]), ref)), None)
    if source is None:
        errors.append({"line": line, "message": "項目「Issue」の Issue が、節「元にした Issue」に無い (本文のハッシュ値で照合するため)"})
        return None
    kind_line, kind = fields["種類"]
    if kind not in KINDS:
        errors.append({"line": kind_line, "message": f"項目「種類」は {'・'.join(KINDS)} のどちらか: {kind!r}"})
        return None
    return {"ref": ref, "url": ref["url"], "kind": kind, "sha256": source["sha256"]}


def parse(text, name, repo):
    """計画案の本文を解析する。name はファイル名、repo は #番号 の参照を解決するリポジトリ (owner/repo)。

    返り値は {"file_name", "target" ({"ref", "url", "kind", "sha256"} か None), "closing" (節「クローズ条件」の中身),
    "merge_plan" (mergeplan.parse の結果), "items" (節「作る Issue」の Issue。無ければ空), "errors"}。
    """
    head = draft.parse(text, name)
    errors = list(head["errors"])
    result = {"file_name": name, "target": None, "closing": None, "merge_plan": None, "items": [], "errors": errors}
    titles = tuple(s["title"] for s in head["sections"])
    if titles not in (SECTIONS[:3], SECTIONS):
        errors.append({"line": None, "message": "節「元にした Issue」の後に、節「" + "」「".join(SECTIONS[:3])
                       + "」(作業 Issue を作るときは、続けて「" + SECTIONS[3] + "」) をこの順に書く"})
        return result
    target = _parse_target(_section(text, "対象"), head["sources"], errors)
    result["target"] = target
    closing = _section(text, CLOSING_SECTION)
    result["closing"] = closing["content"]
    if not closing["content"].strip():
        errors.append({"line": closing["heading_line"], "message": "節「クローズ条件」が空"})
    for number, line in closing["lines"]:
        if _MARK_RE.match(line):
            errors.append({"line": number, "message": "節「クローズ条件」にマークを書かない (サブコマンドが書く)"})
    merge = _section(text, MERGE_PLAN_SECTION)
    plan = mergeplan.parse("\n".join(line for _, line in merge["lines"]), allow_keys=True, offset=merge["heading_line"])
    result["merge_plan"] = plan
    errors += plan["errors"]
    if SECTIONS[3] in titles:
        parsed = issues.parse_items(text, repo)
        result["items"] = parsed["items"]
        errors += parsed["errors"]
    if target is not None and not plan["errors"]:
        keys = {item["key"] for item in result["items"]}
        rows = plan["rows"]
        if target["kind"] == SELF_MANAGING:
            if result["items"]:
                errors.append({"line": None, "message": "自己管理 Issue の計画案には、節「作る Issue」を書かない"})
            if len(rows) != 1 or rows[0]["work"]["number"] != target["ref"]["number"] or plan["settings"]["config"] != "1":
                errors.append({"line": merge["heading_line"], "message": "自己管理 Issue の PR マージ計画は、ブランチの構成 1 で、"
                                                                      f"表の行はこの Issue (#{target['ref']['number']}) の 1 行だけ"})
        else:
            for row in rows:
                for item in [row["work"]] + row["requires"]:
                    if item["key"] is not None and item["key"] not in keys:
                        errors.append({"line": row["line"], "message": f"キー {item['key']} が、節「作る Issue」に無い"})
                if row["work"]["number"] == target["ref"]["number"]:
                    errors.append({"line": row["line"], "message": "管理 Issue 自身を、作業 Issue の行に書かない"})
    errors.sort(key=lambda e: (e["line"] is not None, e["line"] or 0))
    return result


def read(path, repo):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return parse(text, os.path.basename(path), repo)


# --- 本文の書き換え ---------------------------------------------------------------------------------------------

def _marked(name, content):
    return f"{bodies.start_mark(name)}\n\n{content.strip(chr(10))}\n\n{bodies.end_mark(name)}"


def _replace_section(body, title, content):
    found = bodies.find_section(body, title)
    if "error" in found:
        # 節が無ければ (None, None) で、呼び出し元が本文の最後に足す。同じ見出しの節が複数あるときは誤り
        return None, None if found["error"].endswith("が無い") else found["error"]
    lines = bodies.split_lines(body)
    start, end = found["heading_line"] - 1, found["end_line"]
    inner = content.strip("\n").split("\n")
    if end < len(lines):
        new_lines = lines[:start + 1] + [""] + inner + [""] + lines[end:]
    else:
        new_lines = lines[:start + 1] + [""] + inner + [""]
    return "\n".join(new_lines), None


def _append_section(body, title, content):
    return body.rstrip("\n") + f"\n\n## {title}\n\n{content.strip(chr(10))}\n"


def _write_part(body, title, region, content):
    """region (マークの名前) があればマークの中を、無ければ見出しの節の中を書き換え、節も無ければ本文の最後に足す。

    region が None なら、マークを付けずに見出しの節に書く。返り値は {"body"} か {"error"}。
    """
    if region is not None and bodies.has_region_mark(body, region):
        return bodies.replace_region(body, region, content)
    text = _marked(region, content) if region is not None else content
    replaced, error = _replace_section(body, title, text)
    if error:
        return {"error": error}
    if replaced is not None:
        return {"body": replaced}
    return {"body": _append_section(body, title, text)}


def compose_checked(body, kind, closing, merge_content):
    """計画する Issue の本文に、クローズ条件と PR マージ計画 (マークの中身) を書いた本文を作る。

    管理 Issue はクローズ条件をマーク closing-conditions で囲み、自己管理 Issue はマークを付けずに節「クローズ条件」に書く。
    PR マージ計画は、どちらもマーク merge-plan で囲む。ほかの場所は変えない。返り値は {"body"} か {"error"}。
    """
    if kind == SELF_MANAGING and bodies.has_region_mark(body, CLOSING_REGION):
        return {"error": "自己管理 Issue の本文にマーク closing-conditions がある (自己管理 Issue の節「クローズ条件」にはマークを書かない)"}
    written = _write_part(body, CLOSING_SECTION, CLOSING_REGION if kind == MANAGING else None, closing)
    if "error" in written:
        return written
    return _write_part(written["body"], MERGE_PLAN_SECTION, mergeplan.REGION, merge_content)


def compose(body, kind, closing, merge_content):
    """compose_checked の本文。誤りのときは None。"""
    return compose_checked(body, kind, closing, merge_content).get("body")


# --- 示す・実行する ---------------------------------------------------------------------------------------------

def _empty_result(name, repo, errors):
    return {"status": "unsatisfied" if errors else "ok", "draft": name, "repo": repo, "target": None, "body_state": None,
            "issues": None, "merge_plan": None, "closing_conditions": None, "approval_recorded": None, "errors": errors}


def _plan(path, repo):
    """「示す」の本体。返り値は (結果の辞書, parse の結果, 作業 Issue の番号の辞書)。"""
    parsed = read(path, repo)
    name = parsed["file_name"]
    result = _empty_result(name, repo, list(parsed["errors"]))
    if parsed["errors"]:
        return result, parsed, {}
    target = parsed["target"]
    ref = target["ref"]
    result["target"] = {"issue": ref["key"], "url": target["url"], "kind": target["kind"]}
    result["closing_conditions"] = parsed["closing"]
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        return {**result, "status": "gh_failed", "gh_error": failure}, parsed, {}
    meta, failure = closecheck.fetch_meta(ref)
    if failure:
        return {**result, "status": "gh_failed", "gh_error": failure}, parsed, {}
    milestone = (meta.get("milestone") or {}).get("title")
    for item in parsed["items"]:
        if item["milestone"] != milestone:
            result["errors"].append({"line": item["line"], "message": f"Issue {item['key']}: マイルストーン {item['milestone']!r} が、"
                                                                       f"計画する Issue のマイルストーン {milestone!r} と違う (R49)"})
    numbers = {}
    if parsed["items"]:
        shown, _ = issues.plan(path, repo)
        if shown["status"] == "gh_failed":
            return {**result, "status": "gh_failed", "gh_error": shown["gh_error"]}, parsed, {}
        result["issues"] = {k: shown[k] for k in ("labels_to_create", "items")}
        result["errors"] += shown["errors"]
        numbers = {i["key"]: i["issue"]["number"] for i in shown["items"] if i["issue"]}
    resolved = mergeplan.resolve(parsed["merge_plan"], numbers)
    unresolved = bool(resolved["errors"])
    preview = {**resolved, "errors": []}
    content = mergeplan.render(preview)
    result["merge_plan"] = {"settings": preview["settings"], "rows": mergeplan.rows_output(preview, ref["owner"], ref["repo"]),
                            "content": content}
    if issue["sha256"] == target["sha256"]:
        result["body_state"] = "pending"
        # 「実行する」は作業 Issue を作った後に本文を組み立てる。組み立てで見つかる誤り (同じ見出しの節が複数あるなど) は
        # 本文と計画案のクローズ条件だけで決まり、表の中身 (キーのままか番号か) によらないので、ここで見つけて作業 Issue を
        # 作る前に誤りとして返す (#278)
        composed = compose_checked(issue["body"], target["kind"], parsed["closing"], content)
        if "error" in composed:
            result["errors"].append({"line": None, "message": f"{ref['key']} の本文に書き込めない: {composed['error']}"})
    else:
        composed = None if unresolved else compose(issue["body"], target["kind"], parsed["closing"], content)
        result["body_state"] = "applied" if composed == issue["body"] else "changed"
    if result["body_state"] == "changed":
        result["errors"].append({"line": None, "message": f"{ref['key']} の本文が、計画案を作ったときから変わった (計画案を直す)"})
    listed, failure = records.list_records(ref)
    if failure:
        return {**result, "status": "gh_failed", "gh_error": failure}, parsed, numbers
    result["approval_recorded"] = any(r["kind"] == "approval" and r["values"].get("draft") == name for r in listed["records"])
    result["status"] = "unsatisfied" if result["errors"] else "ok"
    return result, parsed, numbers


def plan(path, repo):
    """「示す」。計画案と GitHub の今の状態から、書き込みの一覧を返す。GitHub には書き込まない。

    返り値は {"status", "draft", "repo", "target" ({"issue", "url", "kind"}), "body_state" (pending: これから書く・
    applied: 書き込み済み・changed: 計画案を作ったときから本文が変わった), "issues" (作業 Issue の「示す」の
    {"labels_to_create", "items"}。作らなければ null), "merge_plan" ({"settings", "rows", "content"}。content は本文に書く
    マークの中身で、作業 Issue を作る前はキーのまま), "closing_conditions", "approval_recorded", "errors"}。
    """
    return _plan(path, repo)[0]


def apply(path, repo):
    """「実行する」。plan と同じ確認をし、誤りが無ければ書き込む。返り値は plan の辞書に {"done"} を足したもの。

    done は行った書き込み {"key", "action", "url"} の配列 (action は issues create の action と、write-body・record-approval)。
    gh が失敗したら、そこで止めて status を gh_failed にし、それまでの書き込みを done に入れる。
    plan で誤りが見つかれば、何も書き込まずに status を unsatisfied にする。作業 Issue を作った後に、plan で読んだ後から
    計画する Issue の本文が変わったと分かったときも unsatisfied にし、それまでの書き込みを done に入れる。
    """
    result, parsed, numbers = _plan(path, repo)
    result["done"] = []
    if result["status"] != "ok":
        return result
    target = parsed["target"]
    ref = target["ref"]

    def failed(failure):
        return {**result, "status": "gh_failed", "gh_error": failure}

    if parsed["items"]:
        created = issues.create(path, repo, record_approval=True)
        result["done"] += created["done"]
        if created["status"] == "gh_failed":
            return failed(created["gh_error"])
        if created["status"] != "ok":
            result["errors"] += created["errors"]
            return {**result, "status": "unsatisfied"}
        numbers = {i["key"]: refs.parse_ref(i["url"])["number"] for i in created["issues"]}
    resolved = mergeplan.resolve(parsed["merge_plan"], numbers)
    if resolved["errors"]:
        result["errors"] += resolved["errors"]
        return {**result, "status": "unsatisfied"}
    content = mergeplan.render(resolved)
    result["merge_plan"]["content"] = content
    result["merge_plan"]["rows"] = mergeplan.rows_output(resolved, ref["owner"], ref["repo"])
    issue, failure = bodies.fetch_issue(ref)
    if failure:
        return failed(failure)
    composed = compose_checked(issue["body"], target["kind"], parsed["closing"], content)
    if issue["sha256"] != target["sha256"]:
        # 本文が計画案を作ったときと違うのは、書き込み済みのときか、_plan で本文を読んだ後に本文が変わったとき
        if "error" in composed or composed["body"] != issue["body"]:
            result["errors"].append({"line": None, "message": f"{ref['key']} の本文が、計画案を作ったときから変わった (計画案を直す)"})
            return {**result, "status": "unsatisfied"}
    elif "error" in composed:
        # _plan が同じ本文で組み立てられることを確認しているので、この分岐は実行されない
        result["errors"].append({"line": None, "message": f"{ref['key']} の本文に書き込めない: {composed['error']}"})
        return {**result, "status": "unsatisfied"}
    else:
        written = bodies.write_body(issue["url"], composed["body"])
        if gh.failed(written):
            return failed(written)
        result["done"].append({"key": None, "action": "write-body", "url": issue["url"]})
    result["body_state"] = "applied"
    if not result["approval_recorded"]:
        line = records.format_line("approval", {"draft": parsed["file_name"]}, where="comment")["line"]
        r = gh.run(["issue", "comment", issue["url"], "--body-file", "-"], mutation=True,
                   stdin=f"{line}\n\n{APPROVAL_TEXT.format(file_name=parsed['file_name'])}\n")
        if gh.failed(r):
            return failed(r)
        result["done"].append({"key": None, "action": "record-approval", "url": issue["url"]})
        result["approval_recorded"] = True
    return result
