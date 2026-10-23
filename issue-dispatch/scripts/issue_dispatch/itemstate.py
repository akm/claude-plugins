"""項目の状態の導出。管理のセッションがターンのたびに、Project の項目 (project.items の結果) とコメントと Issue の出来事から、
割り当て中か・今の割り当ての PR・正常な終わり・reopen・宣言の段階・待っているもの・持っている資源を導く (計画の R24・KTD19)。
作業のセッションの確認 (`work check`・`work held`) も同じ導出の、自分の項目についての読み出し。
状態ごとの出どころと場面ごとの扱いの正本は issue-dispatch/skills/issue-dispatch/references/flow.md。

このモジュールは gh を実行しない (項目は project.items、`PR の報告` の PR の状態は issues.observe_pr を呼び出し元が読んで渡す)。
時刻は GraphQL の ISO 8601 (UTC、`Z`) の文字列のまま比べる。
"""

import json
import re

from issue_dispatch import comments, declaration, ids, resources, sessions

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
    """宣言の本文の JSON のコードブロックを読み、declaration.parse (種類は付けない) で形を検査してパスをそろえる。
    返り値は (parse の declaration, None) か (None, 理由)。"""
    m = _JSON_BLOCK_RE.search(text or "")
    if not m:
        return None, "JSON のコードブロック (```json ... ```) が無い"
    try:
        obj = json.loads(m.group(1))
    except ValueError as e:
        return None, f"JSON として読めない: {e}"
    parsed = declaration.parse(obj, None, None)
    if parsed["status"] != "ok":
        return None, "宣言の形の誤り: " + "; ".join(f"{e['key']}: {e['message']}" for e in parsed["errors"])
    return parsed["declaration"], None


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
    # 自分が足した blocker: 今の割り当てのすべての `待機` (判定の要る宣言が更新で変わった後の、前の宣言への `待機` も含む) の理由の Issue・小さな PR の依頼先
    all_waits = [c for c in _for_assignment(cs, asg) if c["header"]["role"] == "manager" and c["header"]["kind"] == "待機"]
    own = sorted({ids.issue_key(r["issue"]) for c in all_waits for r in _blocking_reasons(c["header"]["values"]["waits"])})
    out = {"judged": judged, "stage": None, "go": None, "wait": None, "returned": None, "manager_blocked": False, "blocked_wait": None,
           "return_status": None, "own_blockers": own, "waiting_blockers": [], "go_declaration": go_declaration, "held": held}
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
        out["waiting_blockers"] = sorted({ids.issue_key(r["issue"]) for w in blocking_waits for r in _blocking_reasons(w["reasons"])})
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


def resource_labels(labels):
    """ラベルの名前の並びから資源の名前 (`resource:<名前>` の名前。ラベルの綴りのまま、名前の順) を取る。接頭辞は大文字小文字を区別しない
    (GitHub のラベルの名前は区別しないため。issues.add_label と同じ)。"""
    n = len(LABEL_PREFIX)
    return sorted(l[n:] for l in labels if isinstance(l, str) and l[:n].casefold() == LABEL_PREFIX and len(l) > n)


def reserved_resources(item, asg, attrs_table):
    """割り当てのときに予約した資源: コメント `割り当て` の時点で付いていたラベル `resource:<名前>` のうち、属性 reserve が on_assign のもの (名前の順)。"""
    return [n for n in resource_labels(labels_at(item, asg["at"])) if resources.attributes_of(attrs_table or {}, n)["reserve"] == "on_assign"]


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


# --- 行うこと・報告 -----------------------------------------------------------------

# 行うこと (書き込みの候補。item state は書かず、管理のセッションが既存のサブコマンドで実行する)
ACTION_KINDS = ("comment", "set-status", "blocked-by-add", "set-field", "clear-field", "withdraw-question")
# 1 回だけ報告するもの (記録の reported で重複を除く)
REPORT_KINDS = ("status-changed", "field-changed", "blocked-by-added", "blocked-by-removed", "reopened", "reopened-while-pending",
                "pr-base-not-default", "pr-left-open")
# 利用者に尋ねること (種類 → 選択肢。空なら自由回答)。種類の名前の正本は records.md の問いの表
QUESTION_OPTIONS = {"close-in-progress": ["stop", "reopen"], "assignee-changed": ["release", "continue"], "field-cleared": ["release", "restore"],
                    "field-changed": ["release", "restore"], "removed": ["release", "keep"], "status-changed": ["release", "restore"],
                    "third-party-edit": ["stop", "continue"], "merged-issue-open": ["close", "keep"], "pr-closed-unmerged": ["release", "keep"],
                    "user-answer-lost": []}
QUESTION_KINDS = tuple(QUESTION_OPTIONS)
STATUS_OPTIONS_FOR_DEPENDENCY = ("Ready", "Blocked")
FIELD_ID, FIELD_TITLE = "Agent session ID", "Agent session title"
# 割り当て中の項目で、管理のセッションが書く Status (これ以外は利用者が変えたもの)
ASSIGNED_STATUSES = ("In Progress", "In review", "Blocked")


def _in_scope(item, login):
    """範囲 (KD25): 担当者が自分 (トークンのログイン) 1 人の項目。"""
    return [a.casefold() for a in item.get("assignees") or []] == [login.casefold()]


def _status_events_after(item, at, project_number):
    return [e for e in _events(item, "ProjectV2ItemStatusChangedEvent") if e.get("project_number") == project_number and (e.get("at") or "") > at]


def _action_comment(item, kind, values, body):
    return {"kind": "comment", "item": item["key"], "comment_kind": kind, "values": values, "body": body}


def _action_status(item, status, continuation=False):
    return {"kind": "set-status", "item": item["key"], "item_id": item["item_id"], "status": status, "continuation": continuation}


def _report(item, kind, **values):
    return {"kind": kind, "item": item["key"], **values}


def dependency_actions(item, state, login, project_number):
    """割り当ての無い項目の `Ready` ⇄ `Blocked` の再導出 (KTD7)。範囲は担当者が自分 1 人で、割り当て中でなく、Status が Ready か Blocked の項目。
    開いている blocker があれば `依存の待ち` → `Blocked`、すべて閉じたら `依存の解消` → `Ready` (コメントが先)。`依存の待ち` の無い `Blocked` は
    利用者が手で付けたものなので書き換えない。コメントの後に止まった書き込み (Status の変化がコメントより後に無い) は続きを書き (continuation)、
    コメントより後に Status の変化があれば利用者の変更として報告する。返り値は (actions, reports)。"""
    status = (item.get("status") or {}).get("name")
    if state.get("assigned") or not _in_scope(item, login) or status not in STATUS_OPTIONS_FOR_DEPENDENCY:
        return [], []
    open_blockers = sorted(b["key"] for b in item.get("blocked_by") or [] if b.get("state") == "OPEN")
    deps = [c for c in parsed_comments(item, login) if c["header"]["role"] == "manager" and c["header"]["kind"] in ("依存の待ち", "依存の解消")]
    latest = deps[-1] if deps else None
    waiting = latest is not None and latest["header"]["kind"] == "依存の待ち"
    changed_after = bool(latest) and bool(_status_events_after(item, latest["created_at"], project_number))
    if status == "Ready":
        if not open_blockers:
            return [], []
        if waiting:
            if changed_after:
                return [], [_report(item, "status-changed", status=status, after_comment=latest["database_id"])]
            return [_action_status(item, "Blocked", continuation=True)], []
        body = "開いている blocker: " + "、".join(open_blockers)
        return [_action_comment(item, "依存の待ち", {"blockers": open_blockers}, body), _action_status(item, "Blocked")], []
    # Blocked
    if waiting:
        if open_blockers:
            return [], []
        return [_action_comment(item, "依存の解消", {}, "blocker がすべて閉じた"), _action_status(item, "Ready")], []
    if latest is not None and not open_blockers and not changed_after:
        return [_action_status(item, "Ready", continuation=True)], []
    return [], []


def human_blocked_by(item, state):
    """割り当て中の項目の `blockedBy` のうち、自分が足したもの (own_blockers) でないもの (人が足した。導出せず報告する。KTD7)。"""
    own = set((state.get("declaration") or {}).get("own_blockers") or [])
    return sorted(b["key"] for b in item.get("blocked_by") or [] if not any(ids.same_issue(b["key"], o) for o in own))


# --- 記録の読み出し ---------------------------------------------------------------------

def record_lost(rec):
    """記録を失ったか (記録が無い・管理のセッションが無い・前の記録が ended)。R24。"""
    return rec is None or not rec.get("manager") or rec["manager"].get("state") == "ended"


def _rec_item(rec, key):
    for k, v in ((rec or {}).get("items") or {}).items():
        if ids.same_issue(k, key):
            return v
    return None


def _unanswered(rec, key):
    """項目への未回答の問い (question_id 付き)。"""
    return [dict(q, question_id=qid) for qid, q in sorted(((rec or {}).get("questions") or {}).items())
            if ids.same_issue(q.get("item"), key) and q.get("answered_at") is None]


def _is_reported(rec, key, kind):
    ri = _rec_item(rec, key)
    return bool(ri) and kind in (ri.get("reported") or {})


def _question(item, kind, **extra):
    return {"kind": kind, "item": item["key"], "options": list(QUESTION_OPTIONS[kind]), **extra}


# --- 割り当て中の項目の場面 -------------------------------------------------------------

def expected_statuses(state):
    """割り当て中の開いている項目で、管理のセッションの書き込みとして説明できる Status。理由に Issue か 小さな PR を含む `待機` の後なら Blocked、
    それ以外は In Progress か In review。"""
    d = state.get("declaration") or {}
    if d.get("waiting_blockers"):
        return {"Blocked"}
    return {"In Progress", "In review"}


def _handover_action(item, cs, rec, own_id, lost):
    """初めて扱う項目 (記録にその項目の情報が無い) で、最後に書いた管理のセッションの ID が自分と違えば `引き継ぎ` を書く (自分の `引き継ぎ` が既にあれば書かない)。"""
    if _rec_item(rec, item["key"]) is not None:
        return None
    managers = [c for c in cs if c["header"]["role"] == "manager"]
    if not managers or sessions.same_session_id(managers[-1]["header"]["session_id"], own_id):
        return None
    if any(c["header"]["kind"] == "引き継ぎ" and sessions.same_session_id(c["header"]["session_id"], own_id) for c in managers):
        return None
    prev = managers[-1]["header"]
    reason = "記録が無い" if rec is None or not rec.get("manager") else ("前の記録が ended" if lost else "記録にこの項目の情報が無い")
    body = f"前の管理のセッション: {prev['name']} ({prev['session_id']})。理由: {reason}"
    return _action_comment(item, "引き継ぎ", {}, body)


def assigned_scenes(item, state, rec, login, own_id, project_number, config, pr_states, lost):
    """割り当てのある項目の場面ごとの扱い (flow.md の「場面ごとの扱い」)。返り値は (actions, questions, reports)。
    未回答の問いがある項目には手を付けない (答えを待つ間の reopen による問いの取り下げを除く)。"""
    actions, questions, reports = [], [], []
    cs = parsed_comments(item, login)
    asg = state["assignment"]
    key = item["key"]
    status = (item.get("status") or {}).get("name")
    handover = _handover_action(item, cs, rec, own_id, lost)
    if handover:
        actions.append(handover)
    pending = _unanswered(rec, key)
    if pending and item.get("state") == "OPEN":
        close_q = [q for q in pending if q["kind"] == "close-in-progress"]
        if close_q and any((e.get("at") or "") > close_q[0]["asked_at"] for e in _events(item, "ReopenedEvent")):
            # 答えを待つ間に reopen された: 問いを取り下げ、フィールドは空にせず、Status を導いた状態に戻す (R21)
            actions.append({"kind": "withdraw-question", "item": key, "question_id": close_q[0]["question_id"]})
            restore = "Blocked" if "Blocked" in expected_statuses(state) else "In Progress"
            if status != restore:
                actions.append(_action_status(item, restore))
            reports.append(_report(item, "reopened-while-pending", question_id=close_q[0]["question_id"]))
            return actions, questions, reports
    if pending:
        return actions, questions, reports
    if not state["assigned"]:
        if state["reopened"]:
            value = ((item.get("fields") or {}).get(FIELD_ID) or {}).get("text")
            if value == asg["to"]:
                actions.append({"kind": "clear-field", "item": key, "item_id": item["item_id"], "fields": [FIELD_ID, FIELD_TITLE]})
            reports.append(_report(item, "reopened", at=state["reopened"]["at"], fields_cleared=value == asg["to"]))
        if state["end"] and state["end"]["kind"] == "normal" and state["pr"] and state["pr"]["state"] == "OPEN":
            reports.append(_report(item, "pr-left-open", url=state["pr"]["url"]))
        return actions, questions, reports
    if item.get("state") == "CLOSED" and state["in_progress"]:
        questions.append(_question(item, "close-in-progress", record_lost=lost))
        return actions, questions, reports
    if not _in_scope(item, login):
        questions.append(_question(item, "assignee-changed", assignees=list(item.get("assignees") or [])))
    ri = _rec_item(rec, key) or {}
    intent = ri.get("intent") or {}
    field = (item.get("fields") or {}).get(FIELD_ID) or {}
    value, updated = field.get("text"), field.get("updated_at")
    if value != asg["to"]:
        if updated and updated > asg["at"]:
            questions.append(_question(item, "field-cleared" if not value else "field-changed", value=value))
        else:
            actions.append({"kind": "set-field", "item": key, "item_id": item["item_id"], "field": FIELD_ID, "value": asg["to"], "continuation": True})
            if intent.get("session_title"):
                actions.append({"kind": "set-field", "item": key, "item_id": item["item_id"], "field": FIELD_TITLE, "value": intent["session_title"], "continuation": True})
    expected = expected_statuses(state)
    d = state.get("declaration") or {}
    if item.get("state") == "OPEN" and status not in expected and not (status == "Blocked" and d.get("manager_blocked")):
        if status not in ASSIGNED_STATUSES:
            if _status_events_after(item, asg["at"], project_number):
                questions.append(_question(item, "status-changed", status=status))
            else:
                actions.append(_action_status(item, "In Progress", continuation=True))
    # `待機` (Issue か 小さな PR) の続き: blockedBy と Blocked
    if d.get("waiting_blockers") and d.get("wait") and not d.get("manager_blocked"):
        wait_at = d["wait"]["at"]
        present = {b["key"] for b in item.get("blocked_by") or []}
        for blocker in d["waiting_blockers"]:
            if any(ids.same_issue(blocker, k) for k in present):
                continue
            removed = [e for e in _events(item, "BlockedByRemovedEvent") if e.get("blocking") and ids.same_issue(e["blocking"], blocker) and (e.get("at") or "") > wait_at]
            if removed:
                reports.append(_report(item, "blocked-by-removed", blockers=[blocker]))
            else:
                actions.append({"kind": "blocked-by-add", "item": key, "blocker": blocker, "continuation": True})
        if status != "Blocked" and item.get("state") == "OPEN":
            if _status_events_after(item, wait_at, project_number):
                if not any(q["kind"] == "status-changed" for q in questions):
                    reports.append(_report(item, "status-changed", status=status, after_comment=d["wait"]["comment_id"]))
            else:
                actions.append(_action_status(item, "Blocked", continuation=True))
    # 第三者の本文の編集 (確認の対象のリポジトリだけ。確かめた時刻より後のもの)
    if any(item["repo"].casefold() == r.casefold() for r in (config or {}).get("third_party_edit_check") or []):
        confirmed = ri.get("body_edit_confirmed_at") or ""
        edits = [e for e in third_party_edits(item, asg, login) if (e["edited_at"] or "") > confirmed]
        if edits:
            questions.append(_question(item, "third-party-edit", edits=edits))
    # PR
    pr = state.get("pr")
    if pr:
        if pr["source"] == "report" and not pr["closing"]:
            default = (((pr_states or {}).get(pr["url"]) or {}).get("pr") or {}).get("default_branch")
            if default and pr.get("base_ref") and pr["base_ref"] != default:
                reports.append(_report(item, "pr-base-not-default", url=pr["url"], base_ref=pr["base_ref"], default_branch=default))
            else:
                asked = any(r["kind"] == "本文の追記" and ids.parse_pr_url(r["values"]["pr"])["url"] == pr["url"] for r in pending_requests(item, cs, asg, asg["to"], pr_states))
                if not asked:
                    actions.append(_action_comment(item, "依頼", {"to": asg["to"], "assignment": asg["number"], "request_kind": "本文の追記", "pr": pr["url"]},
                                                   f"PR {pr['url']} の本文に `Closes #{item['number']}` を足す"))
        if item.get("state") == "OPEN":
            if pr["merged"]:
                questions.append(_question(item, "merged-issue-open", url=pr["url"]))
            elif pr["state"] == "CLOSED":
                questions.append(_question(item, "pr-closed-unmerged", url=pr["url"]))
    if lost and d.get("wait") and any(r.get("kind") == "利用者の答え" for r in d["wait"]["reasons"]):
        questions.append(_question(item, "user-answer-lost", declaration=d["judged"]["comment_id"] if d.get("judged") else None, record_lost=True))
    return actions, questions, reports


# --- 人の変更 (R22) ---------------------------------------------------------------------

def human_changes(diffs, items_by_key, states_by_key, rec, workflows):
    """スナップショットの差分のうち、記録の意図 (自分の部分書き込み) と組み込みワークフローの遷移と利用者が着手を決める遷移で説明できないものを
    報告する (KTD7)。割り当て中の項目の Status とフィールドの変化は assigned_scenes が問いにするのでここでは扱わない。"""
    reports = []
    for diff in diffs or []:
        key = diff.get("item")
        if not key:
            continue
        item, st = items_by_key.get(key), states_by_key.get(key)
        assigned = bool(st and st.get("assigned"))
        intent = (_rec_item(rec, key) or {}).get("intent") or {}
        reopened = bool(item and _events(item, "ReopenedEvent"))
        kind = diff.get("kind")
        if kind == "status":
            before, after = diff.get("before"), diff.get("after")
            if assigned or intent.get("status") == after:
                continue
            if after == "Done" and item and item.get("state") == "CLOSED":
                continue
            if after == "Todo" and reopened and (workflows or {}).get("Item reopened"):
                continue
            if after == "Ready" and (before in (None, "Todo") or (before == "Done" and reopened)):
                continue
            reports.append({"kind": "status-changed", "item": key, "before": before, "after": after})
        elif kind == "field":
            if assigned or diff.get("field") not in (FIELD_ID, FIELD_TITLE):
                continue
            if (diff["field"] == FIELD_ID and intent.get("session_id") == diff.get("after")) or (diff["field"] == FIELD_TITLE and intent.get("session_title") == diff.get("after")):
                continue
            reports.append({"kind": "field-changed", "item": key, "field": diff["field"], "before": diff.get("before"), "after": diff.get("after")})
        elif kind == "blocked_by" and assigned:
            own = (st.get("declaration") or {}).get("own_blockers") or []
            added = [b for b in diff.get("added") or [] if not any(ids.same_issue(b, o) for o in own)]
            removed = [b for b in diff.get("removed") or [] if any(ids.same_issue(b, o) for o in own)]
            if added:
                reports.append({"kind": "blocked-by-added", "item": key, "blockers": added})
            if removed:
                reports.append({"kind": "blocked-by-removed", "item": key, "blockers": removed})
    return reports


# --- ターン ---------------------------------------------------------------------------

def derive_turn(items, rec, login, own_id, project_number, attrs_table, pr_states, diffs, workflows, config):
    """管理のセッションのターンで、項目の状態と、行うこと (actions)・尋ねること (questions)・1 回だけ報告するもの (reports)・答えを待つ項目 (pending) を導く。
    書き込みはしない。rec は記録 (無ければ None)。diffs は observe diff の差分 (無ければ空)。workflows は Project のワークフローの名前 → 有効か。"""
    lost = record_lost(rec)
    states, actions, questions, reports, pending = [], [], [], [], []
    items_by_key, states_by_key = {}, {}
    for item in items:
        if not item.get("key"):
            continue
        st = derive(item, login, pr_states, project_number, attrs_table)
        states.append(st)
        items_by_key[item["key"]], states_by_key[item["key"]] = item, st
        if st["assignment"]:
            a, q, r = assigned_scenes(item, st, rec, login, own_id, project_number, config, pr_states, lost)
            actions += a
            questions += q
            reports += r
        a, r = dependency_actions(item, st, login, project_number)
        actions += a
        reports += r
        pending += [{"question_id": q["question_id"], "item": item["key"], "kind": q["kind"], "asked_at": q["asked_at"]} for q in _unanswered(rec, item["key"])]
    reports += human_changes(diffs, items_by_key, states_by_key, rec, workflows)
    # 記録の意図にある項目が一覧に無い: Project から除かれた (割り当ての解除を尋ねる)
    for key, ri in sorted(((rec or {}).get("items") or {}).items()):
        if ri.get("intent") and not any(ids.same_issue(key, k) for k in items_by_key) and not any(q["kind"] == "removed" for q in _unanswered(rec, key)):
            questions.append({"kind": "removed", "item": key, "options": list(QUESTION_OPTIONS["removed"])})
    seen = set()
    unique = []
    for r in reports:
        mark = (r["item"], r["kind"])
        if mark in seen or _is_reported(rec, r["item"], r["kind"]):
            continue
        seen.add(mark)
        unique.append(r)
    return {"items": states, "usage": resource_usage(states), "actions": actions, "questions": questions, "reports": unique, "pending": pending,
            "record_lost": lost}


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
