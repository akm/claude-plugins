"""リリースの書き込み。リリース計画の計画案を GitHub に書く「示す」(plan) と「実行する」(apply) と、リリースの見直し
(review) とリリース Issue の状態 (show) (計画の U4・KTD3・KTD5・R8・R37〜R41)。

計画案の書式と名前の形の SSOT は、文書 `issue-practice/skills/release-plan/references/release-plan-issue.md` と
このモジュールの定数。テスト (ファイル `issue-practice/tests/test_releaseops.py`) が、文書の表と定数が一致することを確認する。

種類「新しい計画」の「実行する」は、計画の R38 の 6 つの手順の順に書き、続けて取りやめたリリースを閉じる (R39)。

1. 新しいリリース計画 Issue を作る (ラベル current は付けない) と、記録のコメント approval を書く
2. まだ無いリリース Issue (題名に [DRAFT]) とリリースマイルストーンを作ってお互いの URL を書き、Issue の入れ先の
   マイルストーンを設定して、新しい計画の本文に表を書く
3. 新しい計画にラベル current を付ける
4. 古い計画からラベル current を外す
5. 新しい計画に記録のコメント current-swap を書く
6. 古い計画を閉じる
7. 取りやめたリリースのメモをコピーし、記録のコメント plan-change を書いて、リリース Issue (not planned) と
   マイルストーンを閉じる

どの手順も、GitHub の今の状態を読んで、済んでいないものだけを行う。途中で失敗しても、同じ計画案でやり直せる
(作り済みの Issue は、本文の最後の行 created-from で見つける。計画の KTD5)。種類「急ぎのリリースの追加」(R40) は、
新しい計画を作らずに、今の計画に approval の記録を書き、手順 2 を行って今の計画の本文の表を書き換え、plan-change の
記録を書く。

関数は、結果の辞書を返す。例外は送出しない (計画案のファイルを開けないときの OSError を除く)。
"""

import datetime
import os
import re

from issue_practice import bodies, checkboxes, closecheck, draft, gh, issues, records, refs, releaseplan

PLAN_SECTIONS = ("対象", "リリースの順番", "Issue の入れ先", "取りやめるリリース")
TARGET_FIELDS = ("種類", "リリース対象", "今の計画")
KINDS = ("新しい計画", "急ぎのリリースの追加")
NEW_PLAN, URGENT = KINDS
DEST_HEADER = ("Issue", "入れるリリース")
CANCEL_HEADER = ("リリース Issue", "理由", "メモの移し先")
UNDECIDED = "未定"
EXCLUDED = "入れない"
NONE_VALUE = "なし"
PLAN_KEY = "plan"  # 新しいリリース計画 Issue の created-from の行のキー。リリース Issue のキーには使えない

MILESTONE_LINE = "- リリースマイルストーン: "
PENDING_MILESTONE = "まだ無い"
RELEASE_BODY = ("## 参照\n\n" + MILESTONE_LINE + "{milestone}\n\n"
                "この Issue の計画 (目的・範囲の判断・順序・メモの扱い・リリースの手順・完了の条件) は、"
                "スキル release-issue-plan で書く。メモは、この Issue のコメントに 1 件ずつ書く。\n\n{created_from}\n")
PLAN_PLACEHOLDER = "(リリース Issue を作った後に、表を書く。)"
PLAN_BODY = "## " + releaseplan.SECTION_TITLE + "\n\n{table}\n\n{created_from}\n"
MILESTONE_DESCRIPTION = "リリース Issue: {url}"

APPROVAL_NEW = "計画案 {file_name} を利用者が承認し、このリリース計画 Issue を作った。"
APPROVAL_URGENT = "計画案 {file_name} を利用者が承認し、このリリース計画 Issue の表に、急ぎのリリースの行を足す。"
SWAP_TEXT = "利用者が {date} に計画案 {file_name} を承認し、ラベル current を{old}この計画に付け替えた。"
URGENT_CHANGE_TEXT = "計画案 {file_name} (利用者が承認した) で、表に急ぎのリリースの行を足した。決めた人: 利用者。"
CANCEL_TEXT = ("新しいリリース計画 {plan} で、このリリースを取りやめた。決めた人: 利用者 (計画案 {file_name} を承認した)。\n\n"
               "- 理由: {reason}\n- メモの移し先: {memo}")
MEMO_TEXT = "取りやめたリリース Issue {issue} のメモ ({url}) を、新しいリリース計画 {plan} で、この Issue に移した。\n\n---\n\n{body}"

_FIELD_RE = re.compile(r"^- (?P<name>[^:]+): (?P<value>\S.*)$")
_ISSUE_CELL_RE = re.compile(r"^#(?P<number>[1-9][0-9]*)$")
_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?\s*$")


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


def _check(result):
    if gh.failed(result):
        raise _GhFailed(result)
    return result


def today():
    """今日の日付 (ローカル時刻)。テストで差し替える。"""
    return datetime.date.today()


def same_body(a, b):
    """2 つの本文が同じか。改行を \\n にそろえ、末尾の改行を除いて比べる (GitHub が本文の改行を \\r\\n で返すことがあるため)。"""
    def norm(text):
        return (text or "").replace("\r\n", "\n").rstrip("\n")
    return norm(a) == norm(b)


def local_date(timestamp):
    """GitHub の日時 (ISO 8601。末尾 Z) を、ローカル時刻の日付 (YYYY-MM-DD) にする。読めなければ None。"""
    try:
        moment = datetime.datetime.fromisoformat((timestamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone().date().isoformat()


# --- 計画案の解析 -----------------------------------------------------------------------------------------------

def _table(section, header, errors):
    """節の中の表 (見出しの行が header) を読む。返り値は [(行番号, セルの配列)] か、「なし」なら []。誤りなら None。"""
    lines = [(number, text) for number, text in section["lines"] if text.strip()]
    if len(lines) == 1 and lines[0][1].strip() == NONE_VALUE:
        return []
    if not lines:
        errors.append({"line": section["heading_line"], "message": f"節「{section['title']}」が空 (無ければ「{NONE_VALUE}」と書く)"})
        return None
    cells = [(number, releaseplan._cells(text)) for number, text in lines]
    bad = [number for number, c in cells if c is None]
    if bad:
        errors.append({"line": bad[0], "message": f"節「{section['title']}」は、表か「{NONE_VALUE}」の 1 行だけにする"})
        return None
    if tuple(cells[0][1]) != header:
        errors.append({"line": cells[0][0], "message": f"表の見出しの行が「| {' | '.join(header)} |」ではない"})
        return None
    if len(cells) < 2 or len(cells[1][1]) != len(header) or not all(_DELIMITER_RE.match(c) for c in cells[1][1]):
        errors.append({"line": cells[0][0] + 1, "message": "表の見出しの行の次が、区切りの行ではない"})
        return None
    rows = []
    for number, c in cells[2:]:
        if len(c) != len(header):
            errors.append({"line": number, "message": f"列の数が {len(header)} ではない"})
            continue
        rows.append((number, c))
    if not rows:
        errors.append({"line": cells[0][0], "message": f"節「{section['title']}」の表に行が無い (無ければ「{NONE_VALUE}」と書く)"})
    return rows


def _fields(section, names, errors):
    fields = {}
    for number, line in section["lines"]:
        if not line.strip():
            continue
        m = _FIELD_RE.match(line)
        if not m or m.group("name") not in names or m.group("name") in fields:
            errors.append({"line": number, "message": f"節「{section['title']}」の行は「- <項目>: <値>」(項目: {'・'.join(names)})"})
            continue
        fields[m.group("name")] = (number, m.group("value").strip())
    missing = [n for n in names if n not in fields]
    if missing:
        errors.append({"line": section["heading_line"], "message": f"節「{section['title']}」に項目が無い: {'・'.join(missing)}"})
        return None
    return fields


def _release_ref(cell, rows_by_number, rows_by_key):
    """列の値 (#番号 かキー) を、表の行に結び付ける。返り値は表の行か None。"""
    m = _ISSUE_CELL_RE.match(cell)
    if m:
        return rows_by_number.get(int(m.group("number")))
    return rows_by_key.get(cell)


def parse_plan(text, name, repo):
    """リリース計画の計画案を解析する。name はファイル名、repo は #番号 の参照を解決するリポジトリ (owner/repo)。

    返り値は {"file_name", "kind", "target", "current" ({"ref", "url", "sha256"} か None), "rows" (表の行),
    "dests" ({"line", "number", "release" (表の行か None), "value" (#番号・キー・未定・入れない)} の配列),
    "cancels" ({"line", "number", "reason", "memo" (表の行か None)} の配列), "errors"}。
    """
    head = draft.parse(text, name)
    errors = list(head["errors"])
    result = {"file_name": name, "kind": None, "target": None, "current": None, "rows": [], "dests": [], "cancels": [],
              "errors": errors}
    titles = tuple(s["title"] for s in head["sections"])
    if titles != PLAN_SECTIONS:
        errors.append({"line": None, "message": "節「元にした Issue」の後に、節「" + "」「".join(PLAN_SECTIONS) + "」をこの順に書く"})
        return result
    sections = {title: bodies.find_section(text, title) for title in PLAN_SECTIONS}
    fields = _fields(sections["対象"], TARGET_FIELDS, errors)
    if fields:
        line, kind = fields["種類"]
        if kind not in KINDS:
            errors.append({"line": line, "message": f"項目「種類」は {'・'.join(KINDS)} のどちらか: {kind!r}"})
        else:
            result["kind"] = kind
        line, target = fields["リリース対象"]
        if target != NONE_VALUE:
            if not releaseplan.TARGET_NAME_RE.match(target):
                errors.append({"line": line, "message": f"項目「リリース対象」の名前の形ではない: {target!r}"})
            else:
                result["target"] = target
        line, current = fields["今の計画"]
        if current != NONE_VALUE:
            ref = refs.parse_ref(current)
            source = next((s for s in head["sources"] if "error" not in ref and refs.same_issue(refs.parse_ref(s["url"]), ref)), None)
            if "error" in ref or ref["kind"] != "issue":
                errors.append({"line": line, "message": f"項目「今の計画」が Issue の URL ではない: {current!r}"})
            elif source is None:
                errors.append({"line": line, "message": "項目「今の計画」の Issue が、節「元にした Issue」に無い (本文のハッシュ値で照合するため)"})
            else:
                result["current"] = {"ref": ref, "url": ref["url"], "sha256": source["sha256"]}
        elif head["sources"]:
            errors.append({"line": line, "message": "項目「今の計画」が「なし」なのに、節「元にした Issue」に Issue がある"})
        if result["kind"] == URGENT and result["current"] is None and current == NONE_VALUE:
            errors.append({"line": line, "message": "急ぎのリリースの追加では、項目「今の計画」に、行を足すリリース計画 Issue を書く"})
    table = releaseplan.parse_table(text, allow_keys=True)
    if "errors" in table:
        errors += [{"line": int(e.split(":")[0][2:]) if e.startswith("行 ") else None, "message": e} for e in table["errors"]]
        return result
    rows = table["rows"]
    result["rows"] = rows
    by_number = {r["number"]: r for r in rows if r["number"]}
    by_key = {r["key"]: r for r in rows if r["key"]}
    if PLAN_KEY in by_key:
        errors.append({"line": by_key[PLAN_KEY]["line"], "message": f"キー {PLAN_KEY} は使えない (リリース計画 Issue に使う)"})
    dest_rows = _table(sections["Issue の入れ先"], DEST_HEADER, errors) or []
    seen = {}
    for line, (issue_cell, value) in dest_rows:
        m = _ISSUE_CELL_RE.match(issue_cell)
        if not m:
            errors.append({"line": line, "message": f"列「Issue」が #<番号> の形ではない: {issue_cell!r}"})
            continue
        number = int(m.group("number"))
        if number in seen:
            errors.append({"line": line, "message": f"#{number} が 2 回ある (行 {seen[number]})"})
            continue
        seen[number] = line
        if number in by_number:
            errors.append({"line": line, "message": f"#{number} は表のリリース Issue (リリース Issue にマイルストーンは設定しない。R42)"})
            continue
        release = None
        if value not in (UNDECIDED, EXCLUDED):
            release = _release_ref(value, by_number, by_key)
            if release is None:
                errors.append({"line": line, "message": f"列「入れるリリース」が、表のリリース Issue (#番号 かキー)・{UNDECIDED}・"
                                                        f"{EXCLUDED} のどれでもない: {value!r}"})
                continue
        result["dests"].append({"line": line, "number": number, "release": release, "value": value})
    cancel_rows = _table(sections["取りやめるリリース"], CANCEL_HEADER, errors) or []
    seen = {}
    for line, (issue_cell, reason, memo) in cancel_rows:
        m = _ISSUE_CELL_RE.match(issue_cell)
        if not m:
            errors.append({"line": line, "message": f"列「リリース Issue」が #<番号> の形ではない: {issue_cell!r}"})
            continue
        number = int(m.group("number"))
        if number in seen or number in by_number:
            errors.append({"line": line, "message": f"#{number} が 2 回ある・表にもある"})
            continue
        seen[number] = line
        if not reason:
            errors.append({"line": line, "message": "列「理由」が空"})
            continue
        memo_row = None
        if memo != NONE_VALUE:
            memo_row = _release_ref(memo, by_number, by_key)
            if memo_row is None:
                errors.append({"line": line, "message": f"列「メモの移し先」が、表のリリース Issue (#番号 かキー) か {NONE_VALUE} ではない: {memo!r}"})
                continue
        result["cancels"].append({"line": line, "number": number, "reason": reason, "memo": memo_row})
    if result["kind"] == URGENT:
        if result["cancels"]:
            errors.append({"line": sections["取りやめるリリース"]["heading_line"],
                           "message": f"急ぎのリリースの追加では、リリースを取りやめない (節「取りやめるリリース」は「{NONE_VALUE}」)"})
        if not by_key:
            errors.append({"line": sections["リリースの順番"]["heading_line"], "message": "急ぎのリリースの追加なのに、表にキーの行 (足すリリース) が無い"})
    errors.sort(key=lambda e: (e["line"] is not None, e["line"] or 0))
    return result


def read_plan(path, repo):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return parse_plan(text, os.path.basename(path), repo)


# --- GitHub から読む -------------------------------------------------------------------------------------------

DEST_FIELDS = "number,url,state,title,milestone,labels"


def _fetch_dest(repo, number):
    result = gh.run(["issue", "view", str(number), "-R", repo, "--json", DEST_FIELDS], expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return None, {**result, "json_error": "応答に url が無い"}
    return {"number": data.get("number"), "url": data["url"], "state": data.get("state"), "title": data.get("title"),
            "milestone": (data.get("milestone") or {}).get("title"),
            "labels": [label.get("name") for label in data.get("labels") or [] if isinstance(label, dict)]}, None


def _comments_and_records(ref, login):
    comments = _need(records.fetch_comments(ref))
    return comments, records.collect(comments, login)


def _memos(comments):
    """コメントのうち、記録のコメントではないもの (メモ)。"""
    out = []
    for comment in comments:
        first = (comment.get("body") or "").partition("\n")[0].rstrip("\r")
        if records.is_record_line(first):
            continue
        out.append({"id": comment.get("id"), "url": comment.get("html_url"), "author": (comment.get("user") or {}).get("login"),
                    "created_at": comment.get("created_at"), "first_line": first, "body": comment.get("body") or ""})
    return out


def _milestones_of(milestones, number, target):
    found = []
    for milestone in milestones:
        parsed = refs.parse_milestone_name(milestone.get("title"))
        if "error" not in parsed and parsed["number"] == number and parsed["target"] == target:
            found.append(milestone)
    return found


def _created(open_issues, file_name, key):
    return [i for i in open_issues if issues.created_from(i.get("body")) == {"draft": file_name, "key": key}]


# --- 示す・実行する (リリース計画) ---------------------------------------------------------------------------------

class _Writer:
    """書き込みの一覧を作り、dry でなければ書き込む。示すと実行するが、同じ手順を通るようにするため。"""

    def __init__(self, dry):
        self.dry = dry
        self.actions = []
        self.done = []

    def act(self, step, action, run, **detail):
        entry = {"step": step, "action": action, **detail}
        self.actions.append(entry)
        if self.dry:
            return None
        result = _check(run())
        self.done.append(entry)
        return result


def _edit(url, *flags):
    return gh.run(["issue", "edit", url, *flags], mutation=True)


def _comment(url, text):
    return gh.run(["issue", "comment", url, "--body-file", "-"], mutation=True, stdin=text)


def _issue_url_from(result):
    made = refs.parse_ref((result["stdout"].strip().splitlines() or [""])[-1])
    if "error" in made or made["kind"] != "issue":
        raise _GhFailed({**result, "json_error": "gh issue create の出力が Issue の URL ではない"})
    return made


def _observe(parsed, repo):
    """計画案に関わる GitHub の今の状態を読む。返り値は状態の辞書。gh が失敗したら _GhFailed を送出する。"""
    file_name, target = parsed["file_name"], parsed["target"]
    errors = []
    state = {"errors": errors, "login": _need(gh.viewer_login())}
    state["labels"] = _need(issues.fetch_labels(repo))
    targets = _need(releaseplan.fetch_targets(repo))
    if targets and target is None:
        errors.append({"line": None, "message": f"リリース対象が複数ある ({', '.join(targets)})。項目「リリース対象」に書く"})
    state["milestones"] = _need(releaseplan.fetch_open_milestones(repo, state="all"))
    state["open_issues"] = _need(issues.fetch_open_issues(repo))
    state["current_plans"] = {p["number"]: p for p in _need(releaseplan.fetch_plans(repo, target))}
    # 今の計画
    current = None
    if parsed["current"]:
        ref = parsed["current"]["ref"]
        issue = _need(bodies.fetch_issue(ref))
        if "/pull/" in (issue["url"] or ""):
            errors.append({"line": None, "message": f"今の計画 {ref['key']} は PR"})
        title = releaseplan.parse_plan_title(issue["title"])
        if title is None or title["target"] != target:
            errors.append({"line": None, "message": f"今の計画 {ref['key']} の題名が、リリース対象 {target or NONE_VALUE} のリリース計画 "
                                                    f"Issue の形 ({releaseplan.plan_title('YYYYMMDD', target)}) ではない: {issue['title']!r}"})
        table = releaseplan.parse_table(issue["body"])
        current = {**issue, "ref": ref, "table": table.get("rows"), "changed": issue["sha256"] != parsed["current"]["sha256"]}
        if "errors" in table:
            errors.append({"line": None, "message": f"今の計画 {ref['key']} の表: " + "・".join(table["errors"])})
        _, current["records"] = _comments_and_records(ref, state["login"])
    state["current"] = current
    # 新しい計画 (種類「新しい計画」のときだけ。created-from の行で探す)
    state["plan"] = None
    if parsed["kind"] == NEW_PLAN:
        found = _created(state["open_issues"], file_name, PLAN_KEY)
        if len(found) > 1:
            errors.append({"line": None, "message": "同じ計画案から作ったリリース計画 Issue が複数ある"})
        elif found:
            ref = refs.parse_ref(found[0]["html_url"])
            issue = _need(bodies.fetch_issue(ref))
            _, listed = _comments_and_records(ref, state["login"])
            state["plan"] = {**issue, "ref": ref, "records": listed}
    # 表のリリース Issue
    releases = {}
    for row in parsed["rows"]:
        if row["number"]:
            issue = _need(releaseplan.fetch_release_issue(repo, row["number"]))
            releases[row["number"]] = _known_release(issue, row, state, target, errors)
        else:
            releases[row["key"]] = _new_release(row, state, file_name, target, errors)
    state["releases"] = releases
    # Issue の入れ先
    dests = {}
    for dest in parsed["dests"]:
        issue = _need(_fetch_dest(repo, dest["number"]))
        dests[dest["number"]] = issue
        where = f"Issue の入れ先の #{dest['number']}"
        if "/pull/" in issue["url"]:
            errors.append({"line": dest["line"], "message": f"{where} は PR"})
        elif issue["state"] != "OPEN":
            errors.append({"line": dest["line"], "message": f"{where} が閉じている"})
        elif releaseplan.parse_plan_title(issue["title"]) or releaseplan.parse_release_title(issue["title"]):
            errors.append({"line": dest["line"], "message": f"{where} は、リリース計画 Issue かリリース Issue"})
        elif dest["release"] is not None and issues.NO_RELEASE_LABEL in issue["labels"]:
            errors.append({"line": dest["line"], "message": f"{where} にラベル {issues.NO_RELEASE_LABEL} が付いている (先に外すかを利用者が決める)"})
        if dest["release"] is not None:
            release = releases[dest["release"]["number"] or dest["release"]["key"]]
            if release.get("closed"):
                errors.append({"line": dest["line"], "message": f"{where} の入れ先のリリース Issue が閉じている"})
    state["dests"] = dests
    # 取りやめるリリース
    cancels = {}
    dest_numbers = {d["number"]: d for d in parsed["dests"]}
    old_numbers = {r["number"] for r in (current or {}).get("table") or []}
    for cancel in parsed["cancels"]:
        number = cancel["number"]
        issue = _need(releaseplan.fetch_release_issue(repo, number))
        entry = {**issue, "milestone": None, "memos": [], "recorded": False}
        cancels[number] = entry
        where = f"取りやめるリリース #{number}"
        if number not in old_numbers:
            errors.append({"line": cancel["line"], "message": f"{where} が、今の計画の表に無い"})
        parsed_title = releaseplan.parse_release_title(issue["title"])
        if "/pull/" in (issue["url"] or "") or parsed_title is None or parsed_title["number"] != number:
            errors.append({"line": cancel["line"], "message": f"{where} の題名が、リリース Issue の形ではない: {issue['title']!r}"})
            continue
        found = _milestones_of(state["milestones"], number, target)
        if len(found) != 1:
            errors.append({"line": cancel["line"], "message": f"{where} のリリースマイルストーンが {len(found)} つある"})
            continue
        entry["milestone"] = found[0]
        remaining = [i for i in state["open_issues"] if (i.get("milestone") or {}).get("number") == found[0].get("number")]
        for item in remaining:
            dest = dest_numbers.get(item.get("number"))
            if dest is None or (dest["release"] is not None and dest["release"]["number"] == number):
                errors.append({"line": cancel["line"], "message": f"{where} のマイルストーンの開いた Issue #{item.get('number')} の移し先が、"
                                                                  "節「Issue の入れ先」に無い"})
        comments, listed = _comments_and_records(refs.parse_ref(issue["url"]), state["login"])
        entry["memos"] = _memos(comments)
        entry["recorded"] = any(r["kind"] == "plan-change" and r["values"].get("draft") == file_name for r in listed["records"])
    state["cancels"] = cancels
    # メモの移し先の、今あるコメント (コピー済みかを、元のコメントの URL を含むかで判定する)
    state["memo_dest_comments"] = {}
    for cancel in parsed["cancels"]:
        memo = cancel["memo"]
        if memo is None:
            continue
        release = releases[memo["number"] or memo["key"]]
        url = (release.get("issue") or {}).get("url")
        if url and url not in state["memo_dest_comments"]:
            state["memo_dest_comments"][url] = [c.get("body") or "" for c in _need(records.fetch_comments(refs.parse_ref(url)))]
    _check_plans(parsed, state, errors, repo)
    return state


def _known_release(issue, row, state, target, errors):
    """表の #番号 の行のリリース Issue を確かめる。返り値は {"issue", "milestone", "closed"}。"""
    where = f"表の行 {row['line']} の #{row['number']}"
    out = {"issue": issue, "milestone": None, "closed": issue["state"] != "OPEN"}
    title = releaseplan.parse_release_title(issue["title"])
    if "/pull/" in (issue["url"] or ""):
        errors.append({"line": row["line"], "message": f"{where} は PR"})
        return out
    if title is None or title["number"] != row["number"] or title["target"] != target:
        errors.append({"line": row["line"], "message": f"{where} の題名が、リリース Issue の形 "
                                                       f"({releaseplan.release_title(row['number'], '主題', target, draft=False)}) ではない: "
                                                       f"{issue['title']!r}"})
        return out
    found = _milestones_of(state["milestones"], row["number"], target)
    if len(found) != 1:
        errors.append({"line": row["line"], "message": f"{where} のリリースマイルストーンが {len(found)} つある"})
        return out
    out["milestone"] = found[0]
    if not out["closed"] and found[0].get("state") != "open":
        errors.append({"line": row["line"], "message": f"{where} は開いているのに、リリースマイルストーンが閉じている"})
    return out


def _new_release(row, state, file_name, target, errors):
    """表のキーの行のリリース Issue を、created-from の行で探す。返り値は {"issue" (無ければ None), "milestone", "closed"}。"""
    out = {"issue": None, "milestone": None, "closed": False}
    found = _created(state["open_issues"], file_name, row["key"])
    if len(found) > 1:
        errors.append({"line": row["line"], "message": f"キー {row['key']} の created-from の行を持つ開いた Issue が複数ある"})
        return out
    if not found:
        return out
    issue = {"number": found[0].get("number"), "url": found[0].get("html_url"), "title": found[0].get("title"),
             "body": found[0].get("body") or "", "state": "OPEN"}
    out["issue"] = issue
    title = releaseplan.parse_release_title(issue["title"])
    pending = releaseplan.release_title(None, row["subject"], target)
    if issue["title"] != pending and (title is None or title["number"] != issue["number"] or title["target"] != target):
        errors.append({"line": row["line"], "message": f"作り済みのリリース Issue {issue['url']} の題名が、計画案から作る形ではない: "
                                                       f"{issue['title']!r}"})
    found = _milestones_of(state["milestones"], issue["number"], target)
    if len(found) > 1:
        errors.append({"line": row["line"], "message": f"作り済みのリリース Issue {issue['url']} のリリースマイルストーンが複数ある"})
    elif found:
        out["milestone"] = found[0]
    return out


def _check_plans(parsed, state, errors, repo):
    """ラベル current の付いた計画と、今の計画・新しい計画の状態が、手順のどこかで止まった状態として説明できるか。"""
    numbers = set(state["current_plans"])
    current, plan = state["current"], state["plan"]
    old = current["number"] if current else None
    if parsed["kind"] == URGENT:
        # 本文が変わったか (書き込み済みか) は、表を書くときに判定する (_write_current_table)
        if numbers != {old}:
            errors.append({"line": None, "message": f"ラベル current の付いた計画が、今の計画 #{old} だけではない: "
                                                    f"{sorted(numbers) or NONE_VALUE}"})
        elif current["state"] != "OPEN":
            errors.append({"line": None, "message": f"今の計画 #{old} が閉じている"})
        if current and current["table"] is not None:
            new_numbers = [r["number"] for r in parsed["rows"] if r["number"]]
            old_numbers = [r["number"] for r in current["table"]]
            if new_numbers != old_numbers and not current["changed"]:
                errors.append({"line": None, "message": "急ぎのリリースの追加では、今の計画の表の行を変えずに、キーの行だけを足す"})
        return
    if current and current["changed"]:
        errors.append({"line": None, "message": f"今の計画 {current['ref']['key']} の本文が、計画案を作ったときから変わった (計画案を直す)"})
    new = plan["number"] if plan else None
    if plan is None:
        expected = {old} if old else set()
        if numbers != expected:
            errors.append({"line": None, "message": f"ラベル current の付いた計画が、計画案の項目「今の計画」と違う: "
                                                    f"{sorted(numbers) or NONE_VALUE}"})
        elif current and current["state"] != "OPEN":
            errors.append({"line": None, "message": f"今の計画 #{old} が閉じている"})
    else:
        allowed = {n for n in (old, new) if n}
        if not numbers <= allowed:
            errors.append({"line": None, "message": f"ラベル current の付いた計画に、今の計画と新しい計画のほかの計画がある: {sorted(numbers)}"})
        elif new not in numbers and old is not None and old not in numbers:
            errors.append({"line": None, "message": f"新しい計画 #{new} にも今の計画 #{old} にもラベル current が無い (決めた形が崩れている)"})
        elif current and current["state"] != "OPEN" and new not in numbers:
            errors.append({"line": None, "message": f"今の計画 #{old} が閉じているのに、新しい計画 #{new} にラベル current が無い"})
    if current and current["table"] is not None:
        in_new = {r["number"] for r in parsed["rows"] if r["number"]}
        cancelled = {c["number"] for c in parsed["cancels"]}
        for row in current["table"]:
            if row["number"] in in_new or row["number"] in cancelled:
                continue
            release = state["releases"].get(row["number"])
            issue = release["issue"] if release else None
            if issue is None:
                issue = _need(releaseplan.fetch_release_issue(repo, row["number"]))
            if issue["state"] == "OPEN":
                errors.append({"line": None, "message": f"今の計画の表の開いたリリース #{row['number']} が、新しい表にも、"
                                                        "節「取りやめるリリース」にも無い"})


def _labels_to_create(parsed, state):
    names = [releaseplan.CURRENT_LABEL] if parsed["kind"] == NEW_PLAN else []
    if parsed["target"]:
        names.append(releaseplan.TARGET_LABEL_PREFIX + parsed["target"])
    if any(d["value"] == EXCLUDED for d in parsed["dests"]):
        names.append(issues.NO_RELEASE_LABEL)
    out = []
    for name in names:
        if name.lower() in state["labels"]:
            continue
        color, description = issues.managed_label(name)
        out.append({"name": name, "color": color, "description": description})
    return out


def _approval_date(listed, file_name):
    for record in listed["records"] if listed else []:
        if record["kind"] == "approval" and record["values"].get("draft") == file_name:
            return local_date(record["created_at"])
    return None


def _write(parsed, state, repo, writer):
    """手順を順に行う (writer.dry なら一覧を作るだけ)。返り値は {"plan", "releases"} (作った・見つけた Issue)。"""
    file_name, target, kind = parsed["file_name"], parsed["target"], parsed["kind"]
    labels = [releaseplan.TARGET_LABEL_PREFIX + target] if target else []
    for label in _labels_to_create(parsed, state):
        writer.act(0, "create-label", lambda label=label: gh.run(
            ["label", "create", label["name"], "-R", repo, "--color", label["color"], "--description", label["description"]],
            mutation=True), label=label["name"])
    # 手順 1: 新しい計画を作る (急ぎの追加では、今の計画に approval の記録を書く)
    if kind == NEW_PLAN:
        plan = state["plan"]
        if plan is None:
            title = releaseplan.plan_title(today().strftime("%Y%m%d"), target)
            body = PLAN_BODY.format(table=PLAN_PLACEHOLDER, created_from=issues.created_from_line(file_name, PLAN_KEY))
            args = ["issue", "create", "-R", repo, "--title", title, "--body-file", "-"]
            for label in labels:
                args += ["--label", label]
            result = writer.act(1, "create-plan", lambda: gh.run(args, mutation=True, stdin=body), title=title, labels=labels)
            if result is not None:
                made = _issue_url_from(result)
                plan = {"number": made["number"], "url": made["url"], "ref": made, "body": body, "records": None}
                writer.done[-1]["url"] = made["url"]
        holder = plan
        approval_text = APPROVAL_NEW
    else:
        holder = state["current"]
        approval_text = APPROVAL_URGENT
    holder_url = holder["url"] if holder else None
    if _approval_date(holder.get("records") if holder else None, file_name) is None:
        line = records.format_line("approval", {"draft": file_name}, where="comment")["line"]
        writer.act(1, "record-approval", lambda: _comment(holder_url, f"{line}\n\n{approval_text.format(file_name=file_name)}\n"),
                   url=holder_url)
    # 手順 2: リリース Issue とマイルストーン
    # made は、表の行 (#番号 かキー) ごとの {"key", "number", "url", "milestone", "milestone_url"}。キーの行は、この実行で
    # 作ったもの (示すときは、番号と URL が None)
    made = {}
    for row in parsed["rows"]:
        if row["key"] is None:
            release = state["releases"][row["number"]]
            made[row["number"]] = {"key": None, "number": row["number"], "url": release["issue"]["url"],
                                   "milestone": (release["milestone"] or {}).get("title"),
                                   "milestone_url": (release["milestone"] or {}).get("html_url")}
        else:
            made[row["key"]] = _write_release(row, state["releases"][row["key"]], parsed, repo, writer, labels)
    made_releases = [made[row["key"]] for row in parsed["rows"] if row["key"]]
    for dest in parsed["dests"]:
        issue = state["dests"][dest["number"]]
        if dest["release"] is not None:
            title = made[dest["release"]["number"] or dest["release"]["key"]]["milestone"]
            if issue["milestone"] != title:
                writer.act(2, "set-milestone", lambda url=issue["url"], title=title: _edit(url, "--milestone", title),
                           url=issue["url"], milestone=title, previous=issue["milestone"])
            continue
        if issue["milestone"]:
            writer.act(2, "remove-milestone", lambda url=issue["url"]: _edit(url, "--remove-milestone"),
                       url=issue["url"], previous=issue["milestone"])
        if dest["value"] == EXCLUDED and issues.NO_RELEASE_LABEL not in issue["labels"]:
            writer.act(2, "add-label", lambda url=issue["url"]: _edit(url, "--add-label", issues.NO_RELEASE_LABEL),
                       url=issue["url"], label=issues.NO_RELEASE_LABEL)
    final_rows = []
    for row in parsed["rows"]:
        number = made[row["number"] or row["key"]]["number"]
        final_rows.append({"number": number if number else f"<{row['key']} の番号>", "subject": row["subject"]})
    table = releaseplan.render_table(final_rows)
    if kind == NEW_PLAN:
        _write_new_plan_table(holder, table, file_name, writer)
    else:
        _write_current_table(state["current"], table, writer)
        listed = state["current"]["records"]
        if not any(r["kind"] == "plan-change" and r["values"].get("draft") == file_name for r in listed["records"]):
            line = records.format_line("plan-change", {"draft": file_name}, where="comment")["line"]
            text = URGENT_CHANGE_TEXT.format(file_name=file_name) + "\n\n" + "\n".join(
                f"- {r['url'] or r['key']}" for r in made_releases)
            writer.act(4, "record-plan-change", lambda: _comment(holder_url, f"{line}\n\n{text}\n"), url=holder_url)
        return {"plan": None, "releases": made_releases}
    # 手順 3〜6: ラベル current の付け替えと、古い計画を閉じる
    current = state["current"]
    numbers = set(state["current_plans"])
    new_number = holder["number"] if holder else None
    if new_number not in numbers:
        writer.act(3, "add-current", lambda: _edit(holder_url, "--add-label", releaseplan.CURRENT_LABEL), url=holder_url)
    if current and current["number"] in numbers:
        writer.act(4, "remove-current", lambda: _edit(current["url"], "--remove-label", releaseplan.CURRENT_LABEL),
                   url=current["url"])
    listed = holder.get("records") if holder else None
    if not listed or not any(r["kind"] == "current-swap" for r in listed["records"]):
        date = _approval_date(listed, file_name) or today().isoformat()
        values = {"date": date}
        if current:
            values["old"] = f"#{current['number']}"
        line = records.format_line("current-swap", values, where="comment")["line"]
        text = SWAP_TEXT.format(date=date, file_name=file_name, old=f" #{current['number']} から" if current else "") + "\n\n"
        text += f"- 置き換えた計画: {'#' + str(current['number']) if current else NONE_VALUE}\n"
        text += "- 新しく作ったリリース Issue とマイルストーン:" + ("".join(
            f"\n  - {r['url'] or r['key']} (マイルストーン {r['milestone_url'] or r['milestone']})" for r in made_releases)
            if made_releases else f" {NONE_VALUE}")
        writer.act(5, "record-current-swap", lambda: _comment(holder_url, f"{line}\n\n{text}\n"), url=holder_url, date=date)
    if current and current["state"] == "OPEN":
        writer.act(6, "close-old-plan", lambda: gh.run(["issue", "close", current["url"]], mutation=True), url=current["url"])
    # 取りやめたリリース (R39)
    for cancel in parsed["cancels"]:
        _write_cancel(cancel, state, parsed, holder_url, writer, made)
    return {"plan": {"number": new_number, "url": holder_url}, "releases": made_releases}


def _write_release(row, release, parsed, repo, writer, labels):
    """キーの行のリリース Issue を作り、番号を題名に書き足し、マイルストーンを作り、本文にマイルストーンの URL を書く。"""
    file_name, target = parsed["file_name"], parsed["target"]
    created_from = issues.created_from_line(file_name, row["key"])
    initial_body = RELEASE_BODY.format(milestone=PENDING_MILESTONE, created_from=created_from)
    issue = release["issue"]
    if issue is None:
        title = releaseplan.release_title(None, row["subject"], target)
        args = ["issue", "create", "-R", repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        result = writer.act(2, "create-release", lambda: gh.run(args, mutation=True, stdin=initial_body), key=row["key"], title=title)
        if result is not None:
            made = _issue_url_from(result)
            issue = {"number": made["number"], "url": made["url"], "title": title, "body": initial_body}
            writer.done[-1]["url"] = made["url"]
    number = issue["number"] if issue else None
    url = issue["url"] if issue else None
    final_title = releaseplan.release_title(number or f"<{row['key']} の番号>", row["subject"], target)
    if issue is None or issue["title"] != final_title:
        writer.act(2, "set-release-number", lambda: _edit(url, "--title", final_title), key=row["key"], url=url, title=final_title)
    milestone = release["milestone"]
    milestone_name = releaseplan.milestone_title(number or f"<{row['key']} の番号>", row["subject"], target)
    if milestone is None:
        result = writer.act(2, "create-milestone", lambda: gh.run(
            ["api", f"repos/{repo}/milestones", "-X", "POST", "-f", f"title={milestone_name}",
             "-f", f"description={MILESTONE_DESCRIPTION.format(url=url)}"], mutation=True, expect_json=True),
            key=row["key"], title=milestone_name)
        if result is not None:
            data = result["json"]
            if not isinstance(data, dict) or not isinstance(data.get("html_url"), str):
                raise _GhFailed({**result, "json_error": "応答に html_url が無い"})
            milestone = data
            writer.done[-1]["url"] = data["html_url"]
    elif url not in (milestone.get("description") or ""):
        writer.act(2, "set-milestone-description", lambda: gh.run(
            ["api", f"repos/{repo}/milestones/{milestone['number']}", "-X", "PATCH",
             "-f", f"description={MILESTONE_DESCRIPTION.format(url=url)}"], mutation=True, expect_json=True),
            key=row["key"], title=milestone.get("title"))
    milestone_url = (milestone or {}).get("html_url")
    body = issue["body"] if issue else initial_body
    if not milestone_url or milestone_url not in body:
        if not same_body(body, initial_body):
            raise _Unsatisfied(f"作り済みのリリース Issue {url} の本文が、作ったときから変わった (マイルストーンの URL を書けない)")
        new_body = RELEASE_BODY.format(milestone=milestone_url or f"<{row['key']} のマイルストーンの URL>", created_from=created_from)
        writer.act(2, "write-release-body", lambda: bodies.write_body(url, new_body), key=row["key"], url=url)
    return {"key": row["key"], "number": number, "url": url, "milestone": milestone_name, "milestone_url": milestone_url}


class _Unsatisfied(Exception):
    """書き込みの途中で、計画案と GitHub の状態が合わないと分かったとき。モジュールの外には出さない。"""


def _write_new_plan_table(plan, table, file_name, writer):
    created_from = issues.created_from_line(file_name, PLAN_KEY)
    placeholder = PLAN_BODY.format(table=PLAN_PLACEHOLDER, created_from=created_from)
    final = PLAN_BODY.format(table=table, created_from=created_from)
    body = plan["body"] if plan else placeholder
    if same_body(body, final):
        return
    if not same_body(body, placeholder):
        raise _Unsatisfied(f"新しいリリース計画 Issue {plan['url']} の本文が、作ったときから変わった")
    url = plan["url"] if plan else None
    writer.act(2, "write-plan-table", lambda: bodies.write_body(url, final), url=url)


def _write_current_table(current, table, writer):
    body = current["body"]
    section = bodies.find_section(body, releaseplan.SECTION_TITLE)
    if "error" in section:
        raise _Unsatisfied(f"今の計画の本文: {section['error']}")
    lines = bodies.split_lines(body)
    start, end = section["heading_line"] - 1, section["end_line"]
    new_lines = lines[:start + 1] + [""] + table.split("\n") + [""] + lines[end:]
    new_body = "\n".join(new_lines)
    if same_body(new_body, body):
        return
    if current["changed"]:
        raise _Unsatisfied(f"今の計画 {current['ref']['key']} の本文が、計画案を作ったときから変わった")
    writer.act(3, "write-plan-table", lambda: bodies.write_body(current["url"], new_body), url=current["url"])


def _write_cancel(cancel, state, parsed, plan_url, writer, made):
    entry = state["cancels"][cancel["number"]]
    file_name = parsed["file_name"]
    plan_ref = f"#{refs.parse_ref(plan_url)['number']}" if plan_url else "<新しい計画>"
    memo_url = None
    if cancel["memo"] is not None:
        memo_url = made[cancel["memo"]["number"] or cancel["memo"]["key"]]["url"]
        # 示すときに足した文で、実行するときにコピー済みと判定しないよう、状態の配列はコピーして使う
        existing = list(state["memo_dest_comments"].get(memo_url, []))
        for memo in entry["memos"]:
            if any(memo["url"] in body for body in existing):
                continue
            text = MEMO_TEXT.format(issue=f"#{cancel['number']}", url=memo["url"], plan=plan_ref, body=memo["body"].rstrip("\n"))
            writer.act(7, "copy-memo", lambda text=text: _comment(memo_url, text + "\n"), url=memo_url, memo=memo["url"])
            existing.append(text)
    if not entry["recorded"]:
        line = records.format_line("plan-change", {"draft": file_name}, where="comment")["line"]
        memo_text = memo_url or (f"<{cancel['memo']['key']}>" if cancel["memo"] else NONE_VALUE)
        text = CANCEL_TEXT.format(plan=plan_ref, file_name=file_name, reason=cancel["reason"], memo=memo_text)
        writer.act(7, "record-cancel", lambda: _comment(entry["url"], f"{line}\n\n{text}\n"), url=entry["url"])
    if entry["state"] == "OPEN":
        writer.act(7, "close-cancelled-release", lambda: gh.run(["issue", "close", entry["url"], "--reason", "not planned"],
                                                               mutation=True), url=entry["url"])
    milestone = entry["milestone"]
    if milestone and milestone.get("state") == "open":
        repo = f"{refs.parse_ref(entry['url'])['owner']}/{refs.parse_ref(entry['url'])['repo']}"
        writer.act(7, "close-cancelled-milestone", lambda: gh.run(
            ["api", f"repos/{repo}/milestones/{milestone['number']}", "-X", "PATCH", "-f", "state=closed"],
            mutation=True, expect_json=True), url=milestone.get("html_url"), title=milestone.get("title"))


def _plan_result(parsed, repo):
    return {"status": "ok", "draft": parsed["file_name"], "repo": repo, "kind": parsed["kind"], "target": parsed["target"],
            "current": None, "plan": None, "current_plans": [], "labels_to_create": [], "actions": [],
            "errors": list(parsed["errors"])}


def _run(path, repo, dry):
    parsed = read_plan(path, repo)
    result = _plan_result(parsed, repo)
    if not dry:
        result["done"] = []
    if result["errors"]:
        return {**result, "status": "unsatisfied"}
    writer = _Writer(dry=True)
    try:
        state = _observe(parsed, repo)
        result["current"] = {"number": state["current"]["number"], "url": state["current"]["url"]} if state["current"] else None
        result["plan"] = {"number": state["plan"]["number"], "url": state["plan"]["url"]} if state["plan"] else None
        result["current_plans"] = sorted(state["current_plans"])
        result["labels_to_create"] = _labels_to_create(parsed, state)
        result["errors"] += state["errors"]
        if result["errors"]:
            return {**result, "status": "unsatisfied"}
        _write(parsed, state, repo, writer)
        result["actions"] = writer.actions
        if dry:
            return result
        writer = _Writer(dry=False)
        written = _write(parsed, state, repo, writer)
        result["done"] = writer.done
        result["plan"] = written["plan"] if written["plan"] else result["plan"]
        result["releases"] = written["releases"]
    except _GhFailed as e:
        if not dry:
            result["done"] = writer.done
        return {**result, "status": "gh_failed", "gh_error": e.result}
    except _Unsatisfied as e:
        if not dry:
            result["done"] = writer.done
        result["errors"].append({"line": None, "message": str(e)})
        return {**result, "status": "unsatisfied"}
    return result


def plan(path, repo):
    """「示す」。計画案と GitHub の今の状態から、行う書き込みの一覧を返す。GitHub には書き込まない。

    返り値は {"status", "draft", "repo", "kind", "target", "current" (今の計画 {number, url} か None), "plan" (作り済みの
    新しい計画 {number, url} か None), "current_plans" (ラベル current の付いた計画の番号の配列), "labels_to_create",
    "actions" ({"step", "action", ...} の配列), "errors"}。
    """
    return _run(path, repo, dry=True)


def apply(path, repo):
    """「実行する」。plan と同じ確認をし、誤りが無ければ書き込む。返り値は plan の辞書に {"done", "releases"} を足したもの。

    gh が失敗したら、そこで止めて status を gh_failed にし、それまでの書き込みを done に入れる。
    """
    return _run(path, repo, dry=False)


# --- 見直し (R8・R37・R50) とリリース Issue の状態 -------------------------------------------------------------

REFERENCE_SECTION = releaseplan.REFERENCE_SECTION
references = releaseplan.references


def is_release_or_plan(title):
    """題名が、リリース計画 Issue かリリース Issue の形か (計画の R37 の見直しから除くもの)。"""
    return bool(releaseplan.parse_plan_title(title) or releaseplan.parse_release_title(title))


def unassigned(open_issues):
    """マイルストーンの無い開いた Issue (リリース計画 Issue・リリース Issue・ラベル no-release の付いた Issue を除く)。"""
    out = []
    for issue in open_issues:
        labels = [label.get("name") for label in issue.get("labels") or [] if isinstance(label, dict)]
        if issue.get("milestone") or is_release_or_plan(issue.get("title")) or issues.NO_RELEASE_LABEL in labels:
            continue
        out.append({"number": issue.get("number"), "url": issue.get("html_url"), "title": issue.get("title")})
    return out


def _resolved_dependencies(repo, open_issues):
    """本文の節「依存先」に、閉じた blocked by の Issue が残っている開いた Issue (片付いた記録を書き損ねたもの。R50)。"""
    out = []
    for issue in open_issues:
        body = issue.get("body") or ""
        if "error" in bodies.find_section(body, closecheck.DEPENDENCIES_SECTION):
            continue
        result = _check(gh.run(["issue", "view", issue.get("html_url"), "--json", "number,url,blockedBy"], expect_json=True))
        nodes = ((result["json"] or {}).get("blockedBy") or {}).get("nodes") or []
        closed = [n for n in nodes if isinstance(n, dict) and n.get("state") == "CLOSED"]
        remaining = [n for n in closed
                     if closecheck.remove_dependency(body, refs.parse_ref(n.get("url")), repo)["removed"]]
        if remaining:
            out.append({"number": issue.get("number"), "url": issue.get("html_url"), "title": issue.get("title"),
                        "resolved": [{"number": n.get("number"), "url": n.get("url")} for n in remaining]})
    return out


def _release_state(issue, target, milestones, listed, errors, where):
    """リリース Issue の題名・マイルストーン・お互いの URL・記録を確かめる。返り値は {"draft", "running", "milestone", ...}。"""
    out = {"number": issue["number"], "url": issue["url"], "title": issue["title"], "state": issue["state"], "draft": None,
           "running": False, "draft_removed": None, "release_start": None, "milestone": None, "errors": []}

    def error(message):
        out["errors"].append(message)
        errors.append(f"{where}: {message}")

    if "/pull/" in (issue["url"] or ""):
        error("PR で、リリース Issue ではない")
        return out
    title = releaseplan.parse_release_title(issue["title"])
    if title is None or title["number"] != issue["number"] or title["target"] != target:
        error(f"題名が、リリース Issue の形 ({releaseplan.release_title(issue['number'], '主題', target, draft=False)}) ではない: "
              f"{issue['title']!r}")
        return out
    out["draft"] = title["draft"]
    found = _milestones_of(milestones, issue["number"], target)
    if len(found) != 1:
        error(f"リリースマイルストーン ({releaseplan.milestone_title(issue['number'], '主題', target)}) が {len(found)} つある")
    else:
        milestone = found[0]
        out["milestone"] = {"number": milestone.get("number"), "title": milestone.get("title"),
                            "url": milestone.get("html_url"), "state": milestone.get("state")}
        if issue["state"] == "OPEN" and milestone.get("state") != "open":
            error("開いているのに、リリースマイルストーンが閉じている")
        for problem in releaseplan.check_links(issue, milestone):
            error(problem)
    if listed["invalid"]:
        error("1 行目の形が違う記録のコメントがある (" + ", ".join(i["url"] or "" for i in listed["invalid"]) + ")")
    removed = [r for r in listed["records"] if r["kind"] == "draft-removed"]
    started = [r for r in listed["records"] if r["kind"] == "release-start"]
    out["draft_removed"] = removed[-1]["url"] if removed else None
    out["release_start"] = started[0]["url"] if started else None
    out["running"] = bool(started)
    if not title["draft"] and not removed:
        error(f"題名に {releaseplan.DRAFT_MARK} が無いのに、記録のコメント draft-removed が無い")
    if title["draft"] and removed:
        error(f"記録のコメント draft-removed があるのに、題名に {releaseplan.DRAFT_MARK} がある")
    return out


def review(repo, target=None):
    """リリースの見直し。決めた形の崩れ (R8)・マイルストーンの無い開いた Issue (R37)・依存先の片付いた記録を書き損ねた
    Issue (R50) を返す。読むだけ。

    返り値は {"status", "repo", "target", "targets", "plans" (ラベル current の付いた計画の配列), "plan" (表を読んだ計画),
    "swapping", "releases" (表のリリース Issue の状態の配列), "unassigned", "dependencies", "errors"}。
    """
    out = {"status": "ok", "repo": repo, "target": target, "targets": [], "plans": [], "plan": None, "swapping": False,
           "releases": [], "unassigned": [], "dependencies": [], "errors": []}
    errors = out["errors"]
    try:
        login = _need(gh.viewer_login())
        targets = _need(releaseplan.fetch_targets(repo))
        out["targets"] = targets
        if targets and not target:
            errors.append(f"リリース対象が複数ある ({', '.join(targets)})。--target でどのリリース対象かを指定する")
            return {**out, "status": "unsatisfied"}
        if target and target not in targets:
            errors.append(f"リリース対象 {target!r} のラベル {releaseplan.TARGET_LABEL_PREFIX}{target} が無い")
            return {**out, "status": "unsatisfied"}
        plans = _need(releaseplan.fetch_plans(repo, target))
        out["plans"] = [{"number": p["number"], "url": p["url"], "title": p["title"], "created_at": p["created_at"]} for p in plans]
        for p in plans:
            title = releaseplan.parse_plan_title(p["title"])
            if title is None or title["target"] != target:
                errors.append(f"ラベル current の付いた #{p['number']} の題名が、リリース計画 Issue の形 "
                              f"({releaseplan.plan_title('YYYYMMDD', target)}) ではない: {p['title']!r}")
        chosen = releaseplan.choose_plan(plans)
        if "error" in chosen:
            errors.append(chosen["error"])
        elif chosen["plan"]:
            plan = chosen["plan"]
            out["plan"] = {"number": plan["number"], "url": plan["url"], "title": plan["title"]}
            out["swapping"] = chosen["swapping"]
            table = releaseplan.parse_table(plan["body"])
            if "errors" in table:
                errors += [f"リリース計画 Issue #{plan['number']} の表: {e}" for e in table["errors"]]
            else:
                milestones = _need(releaseplan.fetch_open_milestones(repo, state="all"))
                for row in table["rows"]:
                    issue = _need(releaseplan.fetch_release_issue(repo, row["number"]))
                    _, listed = _comments_and_records(refs.parse_ref(issue["url"]), login)
                    state = _release_state(issue, target, milestones, listed, errors, f"表の行 {row['line']} の #{row['number']}")
                    out["releases"].append({"order": row["order"], **state})
        open_issues = _need(issues.fetch_open_issues(repo))
        out["unassigned"] = unassigned(open_issues)
        out["dependencies"] = _resolved_dependencies(repo, open_issues)
    except _GhFailed as e:
        return {**out, "status": "gh_failed", "gh_error": e.result}
    out["status"] = "unsatisfied" if errors else "ok"
    return out


def show(ref):
    """リリース Issue 1 つの状態を返す。読むだけ。

    返り値は {"status", "issue", "url", "title", "state", "sha256", "target", "subject", "draft", "running", "draft_removed",
    "release_start", "milestone", "prs", "memos", "errors"}。
    """
    out = {"status": "ok", "issue": ref["key"], "url": None, "title": None, "state": None, "sha256": None, "target": None,
           "subject": None, "draft": None, "running": False, "draft_removed": None, "release_start": None,
           "milestone": None, "prs": [], "memos": [], "errors": []}
    try:
        login = _need(gh.viewer_login())
        issue = _need(bodies.fetch_issue(ref))
        out.update(url=issue["url"], title=issue["title"], state=issue["state"], sha256=issue["sha256"])
        title = releaseplan.parse_release_title(issue["title"])
        target = title["target"] if title else None
        out.update(target=target, subject=title["subject"] if title else None)
        milestones = _need(releaseplan.fetch_open_milestones(f"{ref['owner']}/{ref['repo']}", state="all"))
        comments, listed = _comments_and_records(ref, login)
        errors = []
        state = _release_state(issue, target, milestones, listed, errors, f"#{issue['number']}")
        out.update({k: state[k] for k in ("draft", "running", "draft_removed", "release_start", "milestone")})
        out["errors"] = state["errors"]
        out["prs"] = references(issue["body"])["prs"]
        out["memos"] = [{k: m[k] for k in ("url", "author", "created_at", "first_line")} for m in _memos(comments)]
    except _GhFailed as e:
        return {**out, "status": "gh_failed", "gh_error": e.result}
    out["status"] = "unsatisfied" if out["errors"] else "ok"
    return out


# --- リリース Issue の計画 (R44〜R46) ------------------------------------------------------------------------------

ISSUE_SECTIONS = ("対象", "参照", "目的", "範囲の判断", "順序", "メモの扱い", "リリースの手順", "完了の条件")
CHANGE_SECTION = "変えたこと"
ISSUE_TARGET_FIELD = "リリース Issue"
STEPS_SECTION = "リリースの手順"
DONE_SECTION = "完了の条件"
STEPS_HEADER = ("手順", "行う / 省く", "理由")
STEP_VALUES = ("行う", "省く")
STEPS_DOC_LINE_RE = re.compile(r"^- 手順の文書: (?P<value>\S+)$")
COMMIT_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/blob/[0-9a-f]{40}/\S+$")
DRAFT_REMOVED_TEXT = "利用者が {date} に計画案 {file_name} を承認した。本文に計画を書き、題名の [DRAFT] を外した。"
CHANGE_TEXT = "計画案 {file_name} を利用者が承認し、本文の計画を書き換えた。\n\n{change}"


def _check_steps(section, errors):
    lines = [(n, t) for n, t in section["lines"] if t.strip()]
    first = STEPS_DOC_LINE_RE.match(lines[0][1].strip()) if lines else None
    if not first:
        errors.append({"line": section["heading_line"], "message": f"節「{STEPS_SECTION}」の最初の行が「- 手順の文書: <URL か なし>」ではない"})
        return
    value = first.group("value")
    rest = lines[1:]
    if value == NONE_VALUE:
        if not rest:
            errors.append({"line": section["heading_line"], "message": f"手順の文書が無いときは、節「{STEPS_SECTION}」に手順を直接書く"})
        return
    if not COMMIT_URL_RE.match(value):
        errors.append({"line": lines[0][0], "message": "手順の文書の URL が、コミットを指定した URL "
                                                       "(https://github.com/<owner>/<repo>/blob/<40 桁のコミット>/<パス>) ではない"})
    table = [(n, releaseplan._cells(t)) for n, t in rest if releaseplan._cells(t) is not None]
    if not table or tuple(table[0][1]) != STEPS_HEADER:
        errors.append({"line": section["heading_line"], "message": f"手順ごとの表 (見出しの行は「| {' | '.join(STEPS_HEADER)} |」) が無い"})
        return
    rows = table[2:]
    if not rows:
        errors.append({"line": table[0][0], "message": "手順ごとの表に行が無い"})
    for number, cells in rows:
        if len(cells) != len(STEPS_HEADER) or not cells[0] or cells[1] not in STEP_VALUES or not cells[2]:
            errors.append({"line": number, "message": f"手順ごとの表の行は、手順・{'か'.join(STEP_VALUES)}・理由を書く"})


def _check_done(section, errors):
    lines = [(n, t) for n, t in section["lines"] if t.strip()]
    if len(lines) == 1 and lines[0][1].strip() == "- " + NONE_VALUE:
        return
    if not checkboxes.parse_lines(section["lines"]):
        errors.append({"line": section["heading_line"], "message": f"節「{DONE_SECTION}」は、チェックボックスか「- {NONE_VALUE}」で書く"})


def parse_issue_plan(text, name):
    """リリース Issue の計画案を解析する。返り値は {"file_name", "ref", "sha256", "change" (節「変えたこと」の中身か None),
    "body" (本文に書く部分。節「参照」から最後まで), "milestone" (節「参照」のマイルストーンの URL), "prs", "errors"}。"""
    head = draft.parse(text, name)
    errors = list(head["errors"])
    result = {"file_name": name, "ref": None, "sha256": None, "change": None, "body": None, "milestone": None, "prs": [],
              "errors": errors}
    titles = tuple(s["title"] for s in head["sections"])
    if titles not in (ISSUE_SECTIONS, ISSUE_SECTIONS[:1] + (CHANGE_SECTION,) + ISSUE_SECTIONS[1:]):
        errors.append({"line": None, "message": "節「元にした Issue」の後に、節「" + "」「".join(ISSUE_SECTIONS)
                       + f"」をこの順に書く (承認の後に変えるときは、節「対象」の後に節「{CHANGE_SECTION}」)"})
        return result
    fields = _fields(bodies.find_section(text, "対象"), (ISSUE_TARGET_FIELD,), errors)
    if fields:
        line, value = fields[ISSUE_TARGET_FIELD]
        ref = refs.parse_ref(value)
        source = next((s for s in head["sources"] if "error" not in ref and refs.same_issue(refs.parse_ref(s["url"]), ref)), None)
        if "error" in ref or ref["kind"] != "issue":
            errors.append({"line": line, "message": f"項目「{ISSUE_TARGET_FIELD}」が Issue の URL ではない: {value!r}"})
        elif source is None:
            errors.append({"line": line, "message": f"項目「{ISSUE_TARGET_FIELD}」の Issue が、節「元にした Issue」に無い"})
        else:
            result.update(ref=ref, sha256=source["sha256"])
    if CHANGE_SECTION in titles:
        change = bodies.find_section(text, CHANGE_SECTION)
        if not change["content"].strip():
            errors.append({"line": change["heading_line"], "message": f"節「{CHANGE_SECTION}」が空 (何を変えたか・理由・決めた人を書く)"})
        result["change"] = change["content"]
    sections = {title: bodies.find_section(text, title) for title in ISSUE_SECTIONS[1:]}
    for title, section in sections.items():
        if not section["content"].strip():
            errors.append({"line": section["heading_line"], "message": f"節「{title}」が空"})
    found = references(text)
    if not found["milestone"]:
        errors.append({"line": sections[REFERENCE_SECTION]["heading_line"], "message": f"節「{REFERENCE_SECTION}」に「{MILESTONE_LINE}<URL>」が無い"})
    for url in found["prs"]:
        parsed = refs.parse_ref(url)
        if "error" in parsed or parsed["kind"] != "pull":
            errors.append({"line": sections[REFERENCE_SECTION]["heading_line"], "message": f"「- PR: 」の URL が PR の URL ではない: {url!r}"})
    result.update(milestone=found["milestone"], prs=found["prs"])
    if sections[STEPS_SECTION]["content"].strip():
        _check_steps(sections[STEPS_SECTION], errors)
    if sections[DONE_SECTION]["content"].strip():
        _check_done(sections[DONE_SECTION], errors)
    lines = bodies.split_lines(text)
    result["body"] = "\n".join(lines[sections[REFERENCE_SECTION]["heading_line"] - 1:]).strip("\n")
    errors.sort(key=lambda e: (e["line"] is not None, e["line"] or 0))
    return result


def _issue_plan_run(path, dry):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parsed = parse_issue_plan(text, os.path.basename(path))
    result = {"status": "ok", "draft": parsed["file_name"], "issue": None, "mode": None, "body_state": None, "actions": [],
              "errors": list(parsed["errors"])}
    if not dry:
        result["done"] = []
    if result["errors"]:
        return {**result, "status": "unsatisfied"}
    ref = parsed["ref"]
    repo = f"{ref['owner']}/{ref['repo']}"
    writer = _Writer(dry=True)
    errors = result["errors"]
    try:
        login = _need(gh.viewer_login())
        issue = _need(bodies.fetch_issue(ref))
        result["issue"] = {"number": issue["number"], "url": issue["url"], "title": issue["title"]}
        title = releaseplan.parse_release_title(issue["title"])
        if "/pull/" in (issue["url"] or "") or title is None or title["number"] != issue["number"]:
            errors.append({"line": None, "message": f"{ref['key']} の題名が、リリース Issue の形ではない: {issue['title']!r}"})
            return {**result, "status": "unsatisfied"}
        if issue["state"] != "OPEN":
            errors.append({"line": None, "message": f"{ref['key']} が閉じている"})
        milestones = _need(releaseplan.fetch_open_milestones(repo, state="all"))
        found = _milestones_of(milestones, issue["number"], title["target"])
        if len(found) != 1:
            errors.append({"line": None, "message": f"{ref['key']} のリリースマイルストーンが {len(found)} つある"})
        elif found[0].get("html_url") != parsed["milestone"]:
            errors.append({"line": None, "message": f"節「{REFERENCE_SECTION}」のマイルストーンの URL が、{ref['key']} のリリースマイルストーン "
                                                    f"({found[0].get('html_url')}) と違う"})
        elif issue["url"] not in (found[0].get("description") or ""):
            errors.append({"line": None, "message": f"マイルストーン {found[0].get('title')!r} の説明に、リリース Issue の URL が無い"})
        for url in parsed["prs"]:
            pr = refs.parse_ref(url)
            _need(closecheck.fetch_pr(pr["url"]))
        _, listed = _comments_and_records(ref, login)
        removed = [r for r in listed["records"] if r["kind"] == "draft-removed"]
        mine = [r for r in removed if r["values"].get("draft") == parsed["file_name"]]
        # この計画案の draft-removed の記録があれば、承認を書いている途中か書き終えたところ (やり直し)
        approve = title["draft"] or bool(mine)
        result["mode"] = "approve" if approve else "change"
        if approve:
            if parsed["change"] is not None:
                errors.append({"line": None, "message": f"計画の承認の前 (題名に {releaseplan.DRAFT_MARK} がある) は、節「{CHANGE_SECTION}」を書かない"})
            if removed and not mine:
                errors.append({"line": None, "message": f"別の計画案の draft-removed の記録があるのに、題名に {releaseplan.DRAFT_MARK} がある (R8)"})
        else:
            if parsed["change"] is None:
                errors.append({"line": None, "message": f"計画を承認した後 (題名に {releaseplan.DRAFT_MARK} が無い) に変えるときは、"
                                                        f"節「{CHANGE_SECTION}」に何を変えたか・理由・決めた人を書く (R46)"})
            if not removed:
                errors.append({"line": None, "message": f"題名に {releaseplan.DRAFT_MARK} が無いのに、記録のコメント draft-removed が無い (R8)"})
        created_from = next((line for line in reversed((issue["body"] or "").splitlines())
                             if line.strip() and issues.created_from(line)), None)
        new_body = parsed["body"] + (f"\n\n{created_from.strip()}" if created_from else "") + "\n"
        if same_body(issue["body"], new_body):
            result["body_state"] = "applied"
        elif issue["sha256"] == parsed["sha256"]:
            result["body_state"] = "pending"
        else:
            result["body_state"] = "changed"
            errors.append({"line": None, "message": f"{ref['key']} の本文が、計画案を作ったときから変わった (計画案を直す)"})
        if approve and not title["draft"] and result["body_state"] == "pending":
            errors.append({"line": None, "message": f"この計画案で承認を書き終えた後に、本文が計画案と違う。承認の後に変えるときは、"
                                                    f"新しい計画案に節「{CHANGE_SECTION}」を書く (R46)"})
        if errors:
            return {**result, "status": "unsatisfied"}
        file_name = parsed["file_name"]

        def write(writer):
            if result["body_state"] == "pending":
                writer.act(1, "write-body", lambda: bodies.write_body(issue["url"], new_body), url=issue["url"])
            if approve:
                if not mine:
                    date = today().isoformat()
                    line = records.format_line("draft-removed", {"date": date, "draft": file_name}, where="comment")["line"]
                    text = DRAFT_REMOVED_TEXT.format(date=date, file_name=file_name)
                    writer.act(2, "record-draft-removed", lambda: _comment(issue["url"], f"{line}\n\n{text}\n"),
                               url=issue["url"], date=date)
                new_title = releaseplan.release_title(issue["number"], title["subject"], title["target"], draft=False)
                if title["draft"]:
                    writer.act(3, "remove-draft-title", lambda: _edit(issue["url"], "--title", new_title), url=issue["url"],
                               title=new_title)
            elif not any(r["kind"] == "plan-change" and r["values"].get("draft") == file_name for r in listed["records"]):
                line = records.format_line("plan-change", {"draft": file_name}, where="comment")["line"]
                text = CHANGE_TEXT.format(file_name=file_name, change=parsed["change"].strip())
                writer.act(2, "record-plan-change", lambda: _comment(issue["url"], f"{line}\n\n{text}\n"), url=issue["url"])

        write(writer)
        result["actions"] = writer.actions
        if dry:
            return result
        writer = _Writer(dry=False)
        write(writer)
        result["done"] = writer.done
        if writer.done:
            result["body_state"] = "applied"
    except _GhFailed as e:
        if not dry:
            result["done"] = writer.done
        return {**result, "status": "gh_failed", "gh_error": e.result}
    return result


def issue_plan(path):
    """「示す」。リリース Issue の計画案と GitHub の今の状態から、行う書き込みの一覧を返す。GitHub には書き込まない。

    返り値は {"status", "draft", "issue" ({number, url, title}), "mode" (approve: 計画の承認・change: 承認の後の変更),
    "body_state" (pending・applied・changed), "actions", "errors"}。
    """
    return _issue_plan_run(path, dry=True)


def issue_apply(path):
    """「実行する」。issue_plan と同じ確認をし、誤りが無ければ書き込む。返り値は issue_plan の辞書に {"done"} を足したもの。"""
    return _issue_plan_run(path, dry=False)


# --- リリース Issue とリリースマイルストーンを閉じる (R48) ---------------------------------------------------------

CLOSE_TEXT = "閉じる前の確認の結果。すべての条件を満たした。"


def _close_body(check, notes):
    prs = ", ".join(p["url"] for p in check["prs"]) or "PR は無い"
    total = check["issues_total"]
    issues_text = f"{total} 件。すべて閉じている" if total else "0 件 (このリリースに含める Issue は無かった)"
    done = check["checkboxes"]
    done_text = ("、".join(u for u in check["evidence"] if u not in {p["url"] for p in check["prs"]}) or "なし") if done else "なし"
    lines = [CLOSE_TEXT, "",
             f"- 共通の条件 1 ({closecheck.RELEASE_COMMON[0]}): 下の「会話で確認したこと」",
             f"- 共通の条件 2 ({closecheck.RELEASE_COMMON[1]}): {prs}",
             f"- 共通の条件 3 ({closecheck.RELEASE_COMMON[2]}): {issues_text}",
             f"- 共通の条件 4 ({closecheck.RELEASE_COMMON[3]}): 下の「会話で確認したこと」",
             f"- 項目「完了の条件」の根拠: {done_text}", "", "## 会話で確認したこと", "", notes.strip()]
    return "\n".join(lines)


def _close_run(ref, notes, dry):
    check = closecheck.release_check(ref)
    result = {**check, "actions": []}
    if not dry:
        result["done"] = []
    if check["status"] != "ok":
        return result
    repo = f"{ref['owner']}/{ref['repo']}"
    milestone = check["milestone"]

    def write(writer):
        if check["close_check"] is None:
            line = records.format_line("close-check", {"result": "pass"}, where="comment")["line"]
            body = _close_body(check, notes or "")
            writer.act(1, "record-close-check", lambda: _comment(check["url"], f"{line}\n\n{body}\n"), url=check["url"])
        if check["state"] == "OPEN":
            writer.act(2, "close-release", lambda: gh.run(["issue", "close", check["url"], "--reason", "completed"], mutation=True),
                       url=check["url"])
        if milestone["state"] == "open":
            writer.act(2, "close-milestone", lambda: gh.run(
                ["api", f"repos/{repo}/milestones/{milestone['number']}", "-X", "PATCH", "-f", "state=closed"],
                mutation=True, expect_json=True), url=milestone["url"])

    writer = _Writer(dry=True)
    write(writer)
    result["actions"] = writer.actions
    if dry:
        return result
    if check["close_check"] is None and not (notes or "").strip():
        result["errors"].append("記録のコメント close-check に書く、会話で確認したこと (--notes-file) が空")
        return {**result, "status": "unsatisfied"}
    writer = _Writer(dry=False)
    try:
        write(writer)
    except _GhFailed as e:
        result["done"] = writer.done
        return {**result, "status": "gh_failed", "gh_error": e.result}
    result["done"] = writer.done
    return result


def close_plan(ref):
    """「示す」。リリース Issue を閉じる前の検査 (closecheck.release_check) と、行う書き込みの一覧を返す。書き込まない。"""
    return _close_run(ref, None, dry=True)


def close_apply(ref, notes):
    """「実行する」。検査を満たせば、記録のコメント close-check を書き、リリース Issue とリリースマイルストーンを閉じる。

    notes は、利用者に確認した共通の条件 1・4 の結果 (記録のコメントの節「会話で確認したこと」に書く)。済んだ書き込みは
    行わないので、片方だけ閉じた状態からやり直すと、残りだけを閉じる。
    """
    return _close_run(ref, notes, dry=False)
