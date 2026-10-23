"""項目の状態の導出。管理のセッションがターンのたびに、Project の項目 (project.items の結果) とコメントと Issue の出来事から、
割り当て中か・今の割り当ての PR・正常な終わり・reopen・宣言の段階・待っているもの・持っている資源を導く (計画の R24・KTD19)。
作業のセッションの確認 (`work check`・`work held`) も同じ導出の、自分の項目についての読み出し。
状態ごとの出どころと場面ごとの扱いの正本は issue-dispatch/skills/issue-dispatch/references/flow.md。

このモジュールは gh を実行しない (項目は project.items、`PR の報告` の PR の状態は issues.observe_pr を呼び出し元が読んで渡す)。
時刻は GraphQL の ISO 8601 (UTC、`Z`) の文字列のまま比べる。
"""

import json
import re

from issue_dispatch import comments, declaration, ids, resources

# 宣言の段階: 判定の要る最新の宣言への最新の判定の結果で決める
STAGES = ("undecided", "go", "returned", "waiting")
# 今の割り当ての PR の出どころ
PR_SOURCES = ("report", "reference")
# 割り当ての終わりの種類
END_KINDS = ("released", "normal")
# 問題の種類 (導出を続けられるが、知らせるもの)
PROBLEM_KINDS = ("pr-unreadable",)
LABEL_PREFIX = "resource:"
_PR_URL_RE = re.compile(rf"https://github\.com/{ids.REPO_NAME_PATTERN}/pull/[1-9][0-9]*")
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


# --- コメント -----------------------------------------------------------------------

def parsed_comments(item, login):
    """項目のコメントのうち、先頭行がこの仕組みの形で、書き手がトークンのログインのものを、時刻の順に返す。
    要素は project.items の comments の要素に header (parse_header の結果) と text (先頭行を除いた本文) を足したもの。"""
    out = []
    for c in sorted(item.get("comments") or [], key=lambda c: c.get("created_at") or ""):
        if c.get("author") != login:
            continue
        header, text = comments.split_body(c.get("body"))
        if header is None:
            continue
        out.append({**c, "header": header, "text": text})
    return out


def _after(items, at):
    return [c for c in items if (c.get("created_at") or "") > at]


def _by_kind(items, kind, role=None):
    return [c for c in items if c["header"]["kind"] == kind and (role is None or c["header"]["role"] == role)]


# --- 割り当て -----------------------------------------------------------------------

def assignment(cs):
    """今の割り当て: 最新のコメント `割り当て` (宛先と番号)。無ければ None。"""
    found = _by_kind(cs, "割り当て", "manager")
    if not found:
        return None
    c = found[-1]
    return {"to": c["header"]["values"]["to"], "number": c["header"]["values"]["assignment"], "comment_id": c["database_id"], "at": c["created_at"]}


def _for_assignment(cs, asg):
    """今の割り当てのコメント (`割り当て` より後) のうち、宛先と番号が今の割り当てのもの。宛先と番号を持たない種類はそのまま。"""
    out = []
    for c in _after(cs, asg["at"]):
        v = c["header"]["values"]
        if "to" in v and (v["to"] != asg["to"] or v.get("assignment") != asg["number"]):
            continue
        out.append(c)
    return out


def release(cs, asg):
    """今の番号の `解放`。無ければ None。"""
    found = _by_kind(_for_assignment(cs, asg), "解放", "manager")
    if not found:
        return None
    c = found[-1]
    return {"comment_id": c["database_id"], "at": c["created_at"], "reason": c["header"]["values"]["release_reason"]}


# --- PR -----------------------------------------------------------------------------

def _pr_view(url, source, state, draft, merged, closing, base_ref, created_at):
    return {"url": url, "source": source, "state": state, "draft": bool(draft), "merged": bool(merged), "closing": closing, "base_ref": base_ref,
            "created_at": created_at}


def current_pr(item, cs, asg, pr_states, login):
    """今の割り当ての PR (KTD19 の表の行「PR」)。今の割り当ての最新の `PR の報告` の本文の URL の PR (作者がログインと違えば無いものとする)。
    無ければ、Issue を閉じる参照の PR のうち、作者がログインで、作成が `割り当て` より後のもの (複数なら作成が最新)。
    返り値は (PR か None, problems)。`PR の報告` の PR が読めなければ (pr_states に無い・読めなかった) PR は None で、problems に残す
    (閉じる参照の PR には戻らない。読めるようになれば報告の PR を使うため)。"""
    reports = _by_kind(_for_assignment(cs, asg), "PR の報告", "worker")
    if reports:
        m = _PR_URL_RE.search(reports[-1]["text"] or "")
        if m:
            url = ids.parse_pr_url(m.group(0))["url"]
            got = pr_states.get(url)
            if not got or got.get("status") != "ok":
                return None, [{"what": "pr-unreadable", "url": url, "message": (got or {}).get("message") or "PR の状態を渡されていない"}]
            if got.get("author") == login and got.get("pr"):
                p = got["pr"]
                closing = any(ids.same_issue(i["key"], item["key"]) for i in p.get("issues") or [])
                return _pr_view(url, "report", p["state"], p.get("draft"), p.get("merged"), closing, p.get("base_ref"), p.get("created_at")), []
    candidates = [p for p in item.get("prs") or [] if p.get("author") == login and (p.get("created_at") or "") > asg["at"]]
    if not candidates:
        return None, []
    p = max(candidates, key=lambda p: p["created_at"])
    return _pr_view(p["url"], "reference", p["state"], p.get("draft"), p.get("merged"), True, p.get("base_ref"), p.get("created_at")), []


def report_pr_urls(items, login):
    """項目ごとに、今の割り当ての最新の `PR の報告` の本文の PR の URL を集める (重複なく、項目の順)。呼び出し元がこの URL の状態を読む。"""
    out = []
    for item in items:
        if not item.get("key"):
            continue
        cs = parsed_comments(item, login)
        asg = assignment(cs)
        if asg is None:
            continue
        reports = _by_kind(_for_assignment(cs, asg), "PR の報告", "worker")
        if not reports:
            continue
        m = _PR_URL_RE.search(reports[-1]["text"] or "")
        if m:
            url = ids.parse_pr_url(m.group(0))["url"]
            if url not in out:
                out.append(url)
    return out


def pr_ready(pr):
    """PR が ready for review かマージ済みか (読んだ時点の state・merged・draft で判定。KTD19)。マージされずに閉じた PR は、draft でなければ
    ready for review と読む (利用者が決めた)。"""
    return bool(pr) and (pr["merged"] or not pr["draft"])


# --- 終わりと reopen -----------------------------------------------------------------

def _events(item, kind):
    return [e for e in item.get("events") or [] if e.get("type") == kind]


def assignment_end(item, cs, asg, pr):
    """割り当ての終わり (KTD19 の表の行「割り当ての終わりと reopen」): 今の番号の `解放` か、正常な終わり。
    正常な終わりは、Issue が閉じていて進行中でない (今の割り当ての PR が、読んだ時点で ready for review かマージ済み) こと。
    Issue が開いている (reopen された) ときは、今の割り当ての最新の `ClosedEvent` があり、その close の時点で PR が ready for review か
    マージ済みだった (PR がマージ済み、または close より前に作られた PR が読んだ時点で draft でない) ことで正常な終わりと読む
    (PR の timeline は読まないので、close の時点で draft だった PR が reopen の後に ready になった場合は見分けられない。flow.md)。
    返り値は {"kind": "released", "at", "reason"} / {"kind": "normal", "at": 最新の ClosedEvent の時刻} / None。"""
    rel = release(cs, asg)
    if rel:
        return {"kind": "released", "at": rel["at"], "reason": rel["reason"]}
    closed = [e for e in _events(item, "ClosedEvent") if (e.get("at") or "") > asg["at"]]
    if not closed or not pr_ready(pr):
        return None
    last = closed[-1]
    if item.get("state") == "CLOSED":
        return {"kind": "normal", "at": last["at"]}
    if pr["merged"] or (pr.get("created_at") or "") < (last.get("at") or ""):
        return {"kind": "normal", "at": last["at"]}
    return None


def reopened_after(item, end):
    """終わった後の `ReopenedEvent`。無ければ None。"""
    if not end:
        return None
    later = [e for e in _events(item, "ReopenedEvent") if end.get("at") is None or (e.get("at") or "") > end["at"]]
    return {"at": later[-1]["at"]} if later else None


# --- 宣言の段階 ---------------------------------------------------------------------

def declaration_json(text):
    """宣言の本文の JSON のコードブロックを読む。返り値は (dict, None) か (None, 理由)。"""
    m = _JSON_BLOCK_RE.search(text or "")
    if not m:
        return None, "JSON のコードブロック (```json ... ```) が無い"
    try:
        obj = json.loads(m.group(1))
    except ValueError as e:
        return None, f"JSON として読めない: {e}"
    if not isinstance(obj, dict) or not isinstance(obj.get("files"), list) or not isinstance(obj.get("resources"), list) \
            or any(not isinstance(f, dict) or "path" not in f or "units" not in f for f in obj["files"]):
        return None, "宣言の形 (files の配列 (path と units) と resources の配列) ではない"
    return obj, None


def declarations(cs, asg):
    """今の割り当ての宣言 (`着手の宣言`・`宣言の更新`) を投稿の順に。要素は {"comment_id", "at", "kind", "declaration" (読めなければ None), "error"}。"""
    out = []
    for c in _for_assignment(cs, asg):
        if c["header"]["role"] != "worker" or c["header"]["kind"] not in ("着手の宣言", "宣言の更新"):
            continue
        obj, error = declaration_json(c["text"])
        out.append({"comment_id": c["database_id"], "at": c["created_at"], "kind": c["header"]["kind"], "declaration": obj, "error": error})
    return out


def results_for(cs, asg, decl_id):
    """宣言 (コメントの ID) への判定の結果: {"go": 最新の `開始可`, "waits": `待機` の配列 (投稿の順), "returned": 最新の `依頼` (宣言の書き直し)}。
    要素は {"comment_id", "at"} (`待機` は "reasons" も)。"""
    out = {"go": None, "waits": [], "returned": None}
    for c in _for_assignment(cs, asg):
        h = c["header"]
        if h["role"] != "manager" or h["values"].get("declaration") != decl_id:
            continue
        entry = {"comment_id": c["database_id"], "at": c["created_at"]}
        if h["kind"] == "開始可":
            out["go"] = entry
        elif h["kind"] == "待機":
            out["waits"].append({**entry, "reasons": h["values"]["waits"]})
        elif h["kind"] == "依頼" and h["values"].get("request_kind") == "宣言の書き直し":
            out["returned"] = entry
    return out


def _blocking_reasons(reasons):
    return [r for r in reasons if r.get("kind") in ("Issue", "小さな PR")]


def declaration_stage(item, cs, asg, project_number):
    """今の割り当ての判定の要る最新の宣言 (R20) と、その段階・判定の結果・管理のセッションが書いた `Blocked` か・戻り先・自分が足した blockedBy・
    持っている資源。判定の要る宣言は、着手の宣言と宣言の更新のうち、`開始可` の後の資源を外すだけの更新 (resources-removed-only) を除いたもの。
    差し戻された宣言を書き直した更新は、資源を外しただけでも判定の要る宣言。段階は、その宣言への最新の判定の結果 (`開始可` → go、
    `待機` → waiting、`依頼` (宣言の書き直し) → returned、無ければ undecided)。"""
    go_declaration, later, judged, prev_returned = None, [], None, False
    for d in declarations(cs, asg):
        res = results_for(cs, asg, d["comment_id"])
        if d["declaration"] is None:
            kind, needs = None, True
        else:
            kind = declaration.update_kind(go_declaration, d["declaration"], declaration.held_resources(go_declaration, later))
            needs = kind != "resources-removed-only" or prev_returned
        if needs:
            judged = {**d, "update_kind": kind}
        prev_returned = res["returned"] is not None
        if prev_returned or d["declaration"] is None:
            continue
        if res["go"]:
            go_declaration, later = d["declaration"], []
        else:
            later.append(d["declaration"])
    held = sorted(declaration.held_resources(go_declaration, later))
    out = {"judged": judged, "stage": None, "go": None, "wait": None, "returned": None, "manager_blocked": False, "blocked_wait": None,
           "return_status": None, "own_blockers": [], "go_declaration": go_declaration, "held": held}
    if judged is None:
        return out
    res = results_for(cs, asg, judged["comment_id"])
    out["go"], out["returned"] = res["go"], res["returned"]
    out["wait"] = res["waits"][-1] if res["waits"] else None
    latest = max([x for x in (("go", res["go"]), ("waiting", out["wait"]), ("returned", res["returned"])) if x[1]], key=lambda x: x[1]["at"], default=None)
    out["stage"] = latest[0] if latest else "undecided"
    # 管理のセッションが書いた `Blocked`: 理由に Issue か 小さな PR を含む `待機` の後に `開始可` が無く、Status が Blocked で、Blocked への変化がその `待機` より後
    go_at = res["go"]["at"] if res["go"] else None
    blocking_waits = [w for w in res["waits"] if _blocking_reasons(w["reasons"]) and (go_at is None or w["at"] > go_at)]
    if blocking_waits:
        out["own_blockers"] = sorted({ids.issue_key(r["issue"]) for w in blocking_waits for r in _blocking_reasons(w["reasons"])})
        first = blocking_waits[0]
        status_events = [e for e in _events(item, "ProjectV2ItemStatusChangedEvent")
                         if e.get("project_number") == project_number and e.get("status") == "Blocked" and (e.get("at") or "") >= first["at"]]
        if (item.get("status") or {}).get("name") == "Blocked" and status_events:
            out["manager_blocked"], out["blocked_wait"], out["return_status"] = True, first["comment_id"], "In Progress"
    return out


# --- 資源の使用 ---------------------------------------------------------------------

def labels_at(item, at):
    """ある時点 (at) に付いていたラベル: その時点までの LabeledEvent・UnlabeledEvent を時刻の順に全部読んで求める (R24 の決まり (6))。"""
    labels = set()
    for e in item.get("events") or []:
        if (e.get("at") or "") > at or not e.get("label"):
            continue
        if e.get("type") == "LabeledEvent":
            labels.add(e["label"])
        elif e.get("type") == "UnlabeledEvent":
            labels.discard(e["label"])
    return labels


def reserved_resources(item, asg, attrs_table):
    """割り当てのときに予約した資源: コメント `割り当て` の時点で付いていたラベル `resource:<名前>` のうち、属性 reserve が on_assign のもの (名前の順)。"""
    names = sorted(l[len(LABEL_PREFIX):] for l in labels_at(item, asg["at"]) if l.startswith(LABEL_PREFIX) and len(l) > len(LABEL_PREFIX))
    return [n for n in names if resources.attributes_of(attrs_table or {}, n)["reserve"] == "on_assign"]


def resource_usage(states):
    """資源の使用 (資源の名前 → 持つ項目のキーの配列。resources.judge_* の usage): 割り当て中の項目の予約した資源と持っている資源。
    待っている宣言が新しく要る資源は `開始可` まで持たない (held は `開始可` の宣言から導くため)。"""
    usage = {}
    for s in states:
        if not s.get("assigned"):
            continue
        for name in list(s.get("reserved") or []) + list((s.get("declaration") or {}).get("held") or []):
            key = next((k for k in usage if k.casefold() == name.casefold()), name)
            if s["key"] not in usage.setdefault(key, []):
                usage[key].append(s["key"])
    return usage


# --- 作業のセッションの確認 -----------------------------------------------------------

def _request_done(req, cs, asg, pr_states):
    """`依頼` を行ったか (GitHub から判断できるものだけ。R28)。"""
    v = req["header"]["values"]
    kind = v["request_kind"]
    later = _after(cs, req["created_at"])
    if kind == "宣言の書き直し":
        return any(c["header"]["role"] == "worker" and c["header"]["kind"] == "宣言の更新" for c in later)
    if kind == "本文の追記":
        got = pr_states.get(ids.parse_pr_url(v["pr"])["url"]) or {}
        return got.get("status") == "ok" and bool(got.get("pr")) and any(ids.same_issue(i["key"], asg["item_key"]) for i in got["pr"].get("issues") or [])
    if kind == "小さな PR":
        return any(comments.match_report(req["header"], c["header"]) for c in later)
    return False


def pending_requests(item, cs, asg, session_id, pr_states):
    """自分宛てで今の割り当ての番号の `依頼` のうち、まだ行っていないもの (投稿の順)。要素は {"comment_id", "at", "kind", "values"}。"""
    out = []
    for c in _for_assignment(cs, asg):
        h = c["header"]
        if h["role"] != "manager" or h["kind"] != "依頼" or h["values"]["to"] != session_id:
            continue
        if not _request_done(c, cs, {**asg, "item_key": item["key"]}, pr_states or {}):
            out.append({"comment_id": c["database_id"], "at": c["created_at"], "kind": h["values"]["request_kind"], "values": h["values"]})
    return out


def third_party_edits(item, asg, login):
    """コメント `割り当て` より後の、トークンのログイン以外による本文の編集 (時刻の順)。"""
    return [{"editor": e.get("editor"), "edited_at": e.get("edited_at")} for e in sorted(item.get("body_edits") or [], key=lambda e: e.get("edited_at") or "")
            if (e.get("edited_at") or "") > asg["at"] and e.get("editor") != login]


def work_check(item, session_id, login, pr_states):
    """作業のセッションの確認 (`work check`。R27): フィールドが自分の ID か・自分宛ての今の割り当ての `割り当て` があるか・今の番号の `解放`・
    まだ行っていない `依頼`・`割り当て` より後の第三者の本文の編集 (確認の対象かは呼び出し元が決める)。"""
    cs = parsed_comments(item, login)
    asg = assignment(cs)
    field = ((item.get("fields") or {}).get("Agent session ID") or {}).get("text")
    out = {"key": item["key"], "field_is_mine": field == session_id, "assignment": asg, "assigned_to_me": bool(asg) and asg["to"] == session_id,
           "released": None, "pending_requests": [], "third_party_edits": []}
    if not out["assigned_to_me"]:
        return out
    out["released"] = release(cs, asg)
    out["pending_requests"] = pending_requests(item, cs, asg, session_id, pr_states)
    out["third_party_edits"] = third_party_edits(item, asg, login)
    return out


def work_held(items, session_id, login, pr_states, project_number):
    """作業のセッションが持っている Issue (`work held`。R26): 自分宛ての今の割り当てで割り当て中 (閉じて利用者の答えを待つ Issue を含む) のものを
    Project の順に。要素は key・state・status・判定の要る宣言の ID (judged) と更新の種類・それへの `開始可`・`待機` の有無・
    `Blocked` が管理のセッションのものか・まだ行っていない `依頼`。"""
    out = []
    for item in items:
        if not item.get("key"):
            continue
        s = derive(item, login, pr_states, project_number)
        if not s["assigned"] or s["assignment"]["to"] != session_id:
            continue
        d = s["declaration"]
        out.append({"key": item["key"], "state": item.get("state"), "status": (item.get("status") or {}).get("name"), "assignment": s["assignment"]["number"],
                    "judged": d["judged"]["comment_id"] if d["judged"] else None, "update_kind": d["judged"]["update_kind"] if d["judged"] else None,
                    "stage": d["stage"], "has_go": d["go"] is not None, "has_wait": d["wait"] is not None, "manager_blocked": d["manager_blocked"],
                    "pending_requests": pending_requests(item, parsed_comments(item, login), s["assignment"], session_id, pr_states)})
    return out


# --- 導出 ---------------------------------------------------------------------------

def derive(item, login, pr_states, project_number, attrs_table=None):
    """1 項目の状態を導く。item は project.items の項目 (Issue)、pr_states は `PR の報告` の URL → issues.observe_pr の結果、
    project_number は出来事を絞る Project の番号。返り値のキーは flow.md の「項目の状態」の表。"""
    cs = parsed_comments(item, login)
    asg = assignment(cs)
    out = {"key": item["key"], "assignment": asg, "release": None, "pr": None, "in_progress": False, "end": None, "assigned": False,
           "reopened": None, "declaration": declaration_stage(item, cs, asg, project_number) if asg else None, "reserved": [], "problems": []}
    if asg is None:
        return out
    pr, problems = current_pr(item, cs, asg, pr_states or {}, login)
    out["problems"] = problems
    out["release"] = release(cs, asg)
    out["pr"] = pr
    out["end"] = assignment_end(item, cs, asg, pr)
    out["in_progress"] = out["release"] is None and not pr_ready(pr)
    out["assigned"] = out["end"] is None
    out["reopened"] = reopened_after(item, out["end"])
    out["reserved"] = reserved_resources(item, asg, attrs_table)
    return out
