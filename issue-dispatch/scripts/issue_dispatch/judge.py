"""宣言の判定 (計画の U15。正本は flow.md の「判定」)。

項目の状態 (itemstate) が導いた「判定の要る宣言」を、投稿の順 (同じなら Project の中の順) に 1 件ずつ判定し、`開始可`・`待機`・`依頼`
の書き込みの候補 (actions)・利用者に尋ねること (questions)・作業のセッションに送る合図 (signals) を返す。gh は実行せず、書き込みもしない。
競合の可能性は declaration.conflictability、資源は resources.judge_declare / judge_update、リポジトリの設定は repo.read_repo_config の結果で判断する。
"""

import re

from . import comments, declaration, filekinds, ids, itemstate, resources

RESULTS = ("go", "wait", "ask", "request")
SIGNAL_KINDS = ("go", "wait", "request")
# 判定の問い (種類 → 選択肢)。種類の名前と選択肢の正本は records.md の問いの表
QUESTION_OPTIONS = {"conflict": ["wait", "small-pr", "proceed"], "unknown-content": ["conflict", "none"], "resource-busy": ["wait", "proceed"],
                    "release-undeclared": ["release", "keep"], "small-pr-closed": ["wait-issue", "redo", "proceed"]}
QUESTION_KINDS = tuple(QUESTION_OPTIONS)
_USER_ANSWER = {"kind": "利用者の答え"}
_PR_URL_RE = re.compile(rf"https://github\.com/{ids.REPO_NAME_PATTERN}/pull/[1-9][0-9]*")


# --- 記録の問いの答え ------------------------------------------------------------------

def _questions(rec, item, kind, subject):
    """記録の問いのうち、項目 (owner/repo の大文字小文字を区別しない)・種類・対象 (subject。大文字小文字を区別しない) が同じもの。"""
    folded = subject.casefold() if isinstance(subject, str) else None
    return [q for q in ((rec or {}).get("questions") or {}).values()
            if ids.same_issue(q.get("item"), item) and q.get("kind") == kind
            and (q.get("subject").casefold() if isinstance(q.get("subject"), str) else None) == folded]


def answer_for(rec, item, kind, subject):
    """項目・種類・対象が同じ問いの最新の答え。答えが無い (未回答・取り下げ (answer が null)) なら None。"""
    answered = [q for q in _questions(rec, item, kind, subject) if q.get("answer") is not None]
    if not answered:
        return None
    return max(answered, key=lambda q: q.get("answered_at") or "")["answer"]


def asked(rec, item, kind, subject):
    """項目・種類・対象が同じ未回答の問い (答えも取り下げも無い) が記録にあるか。あれば尋ね直さない。"""
    return any(q.get("answered_at") is None for q in _questions(rec, item, kind, subject))


# --- 判定の順と比べる相手 ----------------------------------------------------------------

def _items_by_key(items):
    return {it["key"]: it for it in items if it.get("key")}


def pending(items, states):
    """未判定の宣言 (判定の要る最新の宣言で、`開始可`・`待機`・`依頼` のどれも無いもの) を、投稿の順 (同じなら Project の中の順) に。
    要素は {"item": 項目, "state": 状態, "judged": 判定の要る宣言}。"""
    by_key = _items_by_key(items)
    out = []
    for st in states:
        d = st.get("declaration") or {}
        if not st.get("assigned") or not d.get("judged") or d.get("stage") != "undecided" or st["key"] not in by_key:
            continue
        out.append({"item": by_key[st["key"]], "state": st, "judged": d["judged"]})
    return sorted(out, key=lambda e: (e["judged"]["at"] or "", e["item"].get("position") if e["item"].get("position") is not None else 0))


def go_declarations(items, states, pr_states, login):
    """比べる相手: 既に `開始可` になった宣言 (項目ごとに最新の `開始可` の宣言)。ready for review の後の PR が変えた、宣言に無いファイル (pr_paths) も相手に加える。
    要素は {"id", "item", "repo", "declaration", "pr_paths", "to", "assignment", "comments" (項目の解析済みのコメント)}。"""
    by_key = _items_by_key(items)
    out = []
    for st in states:
        d = st.get("declaration") or {}
        if not st.get("assigned") or d.get("go_declaration") is None or st["key"] not in by_key:
            continue
        it = by_key[st["key"]]
        pr_paths = []
        pr = st.get("pr")
        if pr and itemstate.pr_ready(pr):
            got = (pr_states or {}).get(pr["url"]) or {}
            if got.get("status") == "ok" and got.get("pr"):
                declared = {f["path"] for f in d["go_declaration"]["files"]}
                for f in got["pr"].get("files") or []:
                    path, problem = declaration.normalize_path(f.get("path"))
                    if not problem and path not in declared and path not in pr_paths:
                        pr_paths.append(path)
        out.append(_other(d["go_declaration_id"], it, st, d["go_declaration"], sorted(pr_paths), login))
    return out


def _other(decl_id, item, state, decl, pr_paths, login):
    return {"id": decl_id, "item": item["key"], "repo": item["repo"], "declaration": decl, "pr_paths": pr_paths, "to": state["assignment"]["to"],
            "assignment": state["assignment"]["number"], "comments": itemstate.parsed_comments(item, login)}


def _other_files(other, rules, table):
    """相手の宣言に、判定するリポジトリの規則で種類を付け、PR が変えた宣言に無いファイルを (節なしで) 足す。"""
    files = [{"path": f["path"], "units": f["units"], "kind": filekinds.classify(f["path"], rules, table)} for f in other["declaration"]["files"]]
    files += [{"path": p, "units": None, "kind": filekinds.classify(p, rules, table)} for p in other["pr_paths"]]
    return {"files": files, "resources": other["declaration"]["resources"], "split": other["declaration"]["split"]}


# --- 資源の使用 -----------------------------------------------------------------------

def _usage_key(usage, name):
    return next((k for k in usage if k.casefold() == name.casefold()), None)


def _add_usage(usage, name, item):
    key = _usage_key(usage, name) or name
    if item not in usage.setdefault(key, []):
        usage[key].append(item)


def _drop_usage(usage, name, item):
    key = _usage_key(usage, name)
    if key is None:
        return
    usage[key] = [i for i in usage[key] if not ids.same_issue(i, item)]
    if not usage[key]:
        del usage[key]


def _releasable(name, item_key, rec, attrs_table):
    return (resources.attributes_of(attrs_table or {}, name)["release_undeclared"] == "release"
            or answer_for(rec, item_key, "release-undeclared", name) == "release")


def released_reservations(st, rec, attrs_table, before=None):
    """割り当てで予約した資源 (reserved) のうち、宣言に無い予約として解放したもの (名前の順)。解放は GitHub への書き込みが無い導出なので、
    判定する側 (judge_one) と使用を導く側 (usage_for) がこの関数で同じに決める。読むのは項目の状態 (declared_resources・held) だけ。
    条件: `開始可` の後は持っている資源 (held) に無い予約、`開始可` の前は今の割り当ての読めた着手の宣言 (書き直しを含む。before を渡せばそのコメントの ID の
    宣言より前のものだけ) のどれかに無い予約で、属性 release_undeclared が release か、問い `release-undeclared` の答えが release のもの。"""
    d = st.get("declaration") or {}
    reserved = st.get("reserved") or []
    if not st.get("assigned") or not reserved or not d:
        return []
    if d.get("go_declaration_id") is not None and before is None:
        # `開始可` の後: 持っている資源 (held) が今の状態 (後の宣言で足し直して予約し直したものを含む)。`開始可` の前の宣言は見ない
        sets = [{h.casefold() for h in d.get("held") or []}]
    else:
        # `開始可` の前: 項目はまだ何も持たないので、読めた着手の宣言 (before より前) のどれかに無ければ解放した
        sets = []
        for x in d.get("declared_resources") or []:
            if x["comment_id"] == before:
                break
            sets.append({r.casefold() for r in x["resources"]})
    return sorted(name for name in reserved if any(name.casefold() not in s for s in sets) and _releasable(name, st["key"], rec, attrs_table))


def usage_for(states, rec, attrs_table):
    """資源の使用 (resources.judge_* の usage)。itemstate.resource_usage から、宣言に無い予約として解放したもの (released_reservations) を除く
    (resource_usage は割り当てのときの予約を割り当て中ずっと数えるため)。"""
    usage = itemstate.resource_usage(states)
    for st in states:
        for name in released_reservations(st, rec, attrs_table):
            _drop_usage(usage, name, st["key"])
    return usage


# --- 1 件の判定 -----------------------------------------------------------------------

def rules_for(repo_config):
    """リポジトリの設定の読み取りの結果から、種類を決める規則と、本文に書く説明。読めなければ (None, 説明)。"""
    status = repo_config["status"]
    if status == "ok":
        return repo_config["config"]["files"], f"リポジトリの設定 ({repo_config['path']} の既定のブランチ) とデフォルトの表"
    if status == "missing":
        return [], "デフォルトの表 (既定のブランチに設定ファイルが無い)"
    return None, "無し (リポジトリの設定が読めない)"


def _comment(item_key, kind, values, body):
    return {"kind": "comment", "item": item_key, "comment_kind": kind, "values": values, "body": body}


def _signal(kind, to, item_key, decl_id, request_kind=None):
    out = {"kind": kind, "to": to, "item": item_key, "declaration": decl_id}
    if request_kind:
        out["request_kind"] = request_kind
    return out


def _question(kind, item_key, subject, decl_id, **extra):
    return {"kind": kind, "item": item_key, "options": list(QUESTION_OPTIONS[kind]), "subject": subject, "declaration": decl_id, **extra}


def _parse_mine(item, judged, rules, table):
    """判定する宣言の JSON をコメントから読み直し、リポジトリの規則で種類を付けて検査する。返り値は (declaration, []) か (None, 誤りの文の配列)。"""
    c = next((c for c in item.get("comments") or [] if c.get("database_id") == judged["comment_id"]), None)
    _, text = comments.split_body(c["body"]) if c else (None, None)
    obj, error = itemstate.declaration_object(text)
    if error:
        return None, [error]
    parsed = declaration.parse(obj, rules, table)
    if parsed["status"] != "ok":
        return None, [f"{e['key']}: {e['message']}" for e in parsed["errors"]]
    return parsed["declaration"], []


def _held_before(st, judged):
    """判定する更新の直前に持っていた資源: `開始可` の宣言の resources のうち、その後の (判定する更新より前の、差し戻されていない) どの更新にも残っているもの。
    項目の状態の `held` は判定する更新も数えるので、更新で外した資源 (解放するもの) を求めるにはこちらを使う。読むのは項目の状態の declared_resources。"""
    d = st["declaration"]
    later, after_go = [], False
    for x in d.get("declared_resources") or []:
        if x["comment_id"] == d["go_declaration_id"]:
            after_go = True
            continue
        if not after_go or x["comment_id"] == judged["comment_id"] or x["returned"]:
            continue
        later.append({"resources": x["resources"]})
    return sorted(declaration.held_resources(d["go_declaration"], later))


def _small_pr_report(other, item_key):
    """相手の項目の `小さな PR の報告` のうち、待つ Issue がこの項目のものの最新の PR の URL。無ければ None。"""
    for c in reversed(other["comments"]):
        h = c["header"]
        if h["role"] == "worker" and h["kind"] == "小さな PR の報告" and ids.same_issue(h["values"].get("waiting_issue"), item_key):
            m = _PR_URL_RE.search(c["text"] or "")
            if m:
                return ids.parse_pr_url(m.group(0))["url"]
    return None


def _small_pr_requested(other, item_key):
    """相手の今の割り当てのセッションに、待つ Issue がこの項目の `依頼` (小さな PR) を既に書いたか (宣言の書き直しで待つ側の宣言の ID が変わっても、同じ依頼とみなす)。"""
    for c in other["comments"]:
        h = c["header"]
        v = h["values"]
        if (h["role"] == "manager" and h["kind"] == "依頼" and v.get("request_kind") == "小さな PR" and v.get("to") == other["to"]
                and v.get("assignment") == other["assignment"] and ids.same_issue(v.get("waiting_issue"), item_key)):
            return True
    return False


def _wait_body(waits, usage, j=None):
    lines = []
    for w in waits:
        if w["kind"] == "利用者の答え":
            lines.append("利用者の答え: 管理のセッションが利用者に尋ねている (競合しうる相手の扱い・unknown-content のファイルの判定・資源の使用)")
        elif w["kind"] == "Issue":
            lines.append(f"Issue {w['issue']}: 競合しうる相手の作業が終わるまで待つ (利用者の答え: wait)")
        elif w["kind"] == "小さな PR":
            lines.append(f"小さな PR {w['issue']}: 相手に共通の変更を先に小さな PR にすることを依頼した" + (f" (PR {w['pr']})" if w.get("pr") else "") + " (利用者の答え: small-pr)")
        elif w["kind"] == "資源":
            holders = usage.get(_usage_key(usage, w["resource"]) or w["resource"]) or []
            lines.append(f"資源 {w['resource']}: 使用中 (持つ項目: {', '.join(holders) or '-'})")
    body = "待つもの:\n" + "\n".join(f"- {line}" for line in lines)
    return body + _undeclared_lines(j) if j else body


def _undeclared_lines(j):
    lines = []
    if j["release"]:
        lines.append(f"解放した資源 (宣言に無い予約・更新で外した資源): {', '.join(j['release'])}")
    if j["keep"]:
        lines.append(f"答えを待つ予約 (宣言に無い資源。解放してよいか利用者に尋ねている): {', '.join(j['keep'])}")
    return ("\n" + "\n".join(lines)) if lines else ""


def _blocking_actions(item, blockers):
    """`待機` の理由の Issue・小さな PR の相手を blockedBy に足し、Status を Blocked にする (既にあるものは書かない)。"""
    actions = []
    present = [b["key"] for b in item.get("blocked_by") or []]
    for blocker in blockers:
        if not any(ids.same_issue(blocker, k) for k in present):
            actions.append({"kind": "blocked-by-add", "item": item["key"], "blocker": blocker, "continuation": False})
    if blockers and item.get("state") == "OPEN" and (item.get("status") or {}).get("name") != "Blocked":
        actions.append({"kind": "set-status", "item": item["key"], "item_id": item["item_id"], "status": "Blocked", "continuation": False})
    return actions


def _restore_and_removals(item, d, blockers):
    """前の宣言の `待機` のために書いた Blocked と blockedBy の扱い。新しい判定で Issue・小さな PR を待たないなら Status を In Progress に戻し、
    自分が足した blockedBy のうち待たなくなった相手は外す候補 (承認を得て `blocked-by remove`)。"""
    actions = []
    own = d.get("own_blockers") or []
    if not blockers and own and item.get("state") == "OPEN" and (item.get("status") or {}).get("name") == "Blocked":
        actions.append({"kind": "set-status", "item": item["key"], "item_id": item["item_id"], "status": "In Progress", "continuation": False})
    present = [b["key"] for b in item.get("blocked_by") or []]
    for blocker in own:
        if any(ids.same_issue(blocker, k) for k in present) and not any(ids.same_issue(blocker, b) for b in blockers):
            actions.append({"kind": "blocked-by-remove", "item": item["key"], "blocker": blocker, "needs_approval": True})
    return actions


def _go_body(j, compared, proceeds, recompared, rule_text):
    lines = []
    if recompared:
        lines.append(f"競合の可能性: {'無し' if not proceeds else '利用者の答え proceed で進める'} (比べた `開始可` の宣言: {len(compared)} 件。規則: {rule_text})")
        for p in proceeds:
            lines.append(f"- 競合しうるまま進める相手: {p['item']} の宣言 {p['declaration']} ({', '.join(x['path'] for x in p['paths'])})")
    else:
        lines.append("ready for review の後の資源だけの更新なので、ファイルの競合の可能性は比べていない")
    if j["reserve"]:
        lines.append(f"予約した資源: {', '.join(j['reserve'])}")
    return "\n".join(lines) + _undeclared_lines(j)


def judge_one(entry, others, rec, usage, attrs_table, repo_config, table, login):
    """宣言 1 件の判定 (flow.md の「1 件の判定」)。others は比べる相手 (go_declarations の要素)、usage は資源の使用 (usage_for の結果)。
    返り値: {"item", "declaration", "to", "assignment", "update_kind", "repo_config", "result" (RESULTS), "waits" (`待機` の理由), "compared" (比べた相手の宣言の ID),
    "recompared" (ファイルの競合の可能性を比べたか), "reserve", "release", "keep", "parsed" (検査した宣言), "actions", "questions", "signals"}。"""
    item, st, judged = entry["item"], entry["state"], entry["judged"]
    key, asg, d = item["key"], st["assignment"], st["declaration"]
    decl_id = judged["comment_id"]
    base = {"to": asg["to"], "assignment": asg["number"], "declaration": decl_id}
    j = {"item": key, "declaration": decl_id, "to": asg["to"], "assignment": asg["number"], "update_kind": judged.get("update_kind"),
         "repo_config": repo_config["status"], "result": None, "waits": [], "compared": [], "recompared": False, "reserve": [], "release": [], "keep": [],
         "parsed": None, "actions": [], "questions": [], "signals": []}
    # 1. 宣言に無い予約 (着手の宣言だけ)。資源はリポジトリの規則に依らず itemstate が読んだ宣言から分かるので、設定の読み取りと形の検査の前に
    #    行い、結果に依らず分ける (resources.md の契機 declare の行): 解放は結果に載せ、問いは待つ経路でも出し、解放してはいけないと答えた資源が
    #    あれば書き直しを頼んで終わる (予約は残す)。解放した資源と答えを待つ予約は、どの経路の本文にも書く (_undeclared_lines)
    r = None
    if judged.get("update_kind") in (None, "initial") and judged.get("declaration") is not None:
        declared = judged["declaration"]["resources"]
        answers = {n: answer_for(rec, key, "resource-busy", n) for n in declared}
        # 前の宣言で解放した予約は、もう予約していない (足し直せば新しい資源として空きを確かめる)
        released = released_reservations(st, rec, attrs_table, before=decl_id)
        reserved = [n for n in st.get("reserved") or [] if n not in released]
        undeclared_answers = {n: answer_for(rec, key, "release-undeclared", n) for n in reserved}
        r = resources.judge_declare(key, declared, reserved, usage, attrs_table or {}, answers, undeclared_answers)
        j["release"], j["keep"] = r["release"], r["keep"]
        for n in r["ask_undeclared"]:
            if not asked(rec, key, "release-undeclared", n):
                j["questions"].append(_question("release-undeclared", key, n, decl_id, resource=n))
        if r["request_rewrite"]:
            j["result"] = "request"
            body = (f"資源 {', '.join(r['request_rewrite'])} は、割り当てで予約したのに宣言に無く、解放してはいけないと利用者が答えたので予約を残している。"
                    f"この資源を resources に加えた宣言を `宣言の更新` で投稿する。" + _undeclared_lines(j))
            j["actions"].append(_comment(key, "依頼", {**base, "request_kind": "宣言の書き直し"}, body))
            j["signals"].append(_signal("request", asg["to"], key, decl_id, "宣言の書き直し"))
            return j
    # 2. リポジトリの設定
    rules, rule_text = rules_for(repo_config)
    if rules is None:
        j["result"], j["waits"] = "wait", [{"kind": "設定"}]
        body = (f"リポジトリ {item['repo']} の設定を読めないので、この宣言の判定を止めている。理由: {repo_config.get('message')}。"
                f"直し方: {repo_config.get('fix') or '-'}。直したら管理のセッションに知らせる (設定を直したことは GitHub に現れないため)。" + _undeclared_lines(j))
        j["actions"].append(_comment(key, "待機", {**base, "waits": j["waits"]}, body))
        j["signals"].append(_signal("wait", asg["to"], key, decl_id))
        return j
    # 3. 宣言の形
    parsed, errors = _parse_mine(item, judged, rules, table)
    if parsed is None:
        j["result"] = "request"
        body = "宣言の形の誤り:\n" + "\n".join(f"- {e}" for e in errors) + f"\n\n使った規則: {rule_text}。直した宣言を `宣言の更新` で投稿する。" + _undeclared_lines(j)
        j["actions"].append(_comment(key, "依頼", {**base, "request_kind": "宣言の書き直し"}, body))
        j["signals"].append(_signal("request", asg["to"], key, decl_id, "宣言の書き直し"))
        return j
    j["parsed"] = parsed
    if r is None:
        # 更新 (`開始可` の後): 外した資源を解放し、足した資源は空きを確かめる。宣言に無い予約の概念は無い
        declared = parsed["resources"]
        answers = {n: answer_for(rec, key, "resource-busy", n) for n in declared}
        r = {**resources.judge_update(key, judged["update_kind"], _held_before(st, judged), declared, usage, attrs_table or {}, answers),
             "keep": [], "ask_undeclared": [], "request_rewrite": []}
        j["release"] = r["release"]
    # 4. 競合の可能性 (ready for review の後の資源だけの更新は比べない)
    recompare = not (st.get("pr") and itemstate.pr_ready(st["pr"]) and judged.get("update_kind") == "resources-only")
    j["recompared"] = recompare
    waits, blockers, requests, request_signals, proceeds = [], [], [], [], []
    unanswered = False
    if recompare:
        same = [o for o in others if o["repo"].casefold() == item["repo"].casefold() and not ids.same_issue(o["item"], key)]
        result = declaration.conflictability({"repo": item["repo"], "declaration": parsed},
                                             [{"id": o["id"], "repo": o["repo"], "declaration": _other_files(o, rules, table)} for o in same])
        j["compared"] = [o["id"] for o in same]
        for o, res in zip(same, result["others"]):
            other_ref = {"item": o["item"], "declaration": o["id"], "to": o["to"]}
            conflict_paths = [p for p in res["paths"] if p["result"] == "conflict"]
            if not conflict_paths:
                # unknown-content の同じパス: 競合しうるかを利用者に尋ねる (相手の宣言とパスが対象)
                for p in [p for p in res["paths"] if p["result"] == "needs-user"]:
                    subject = f"{o['item']}:{o['id']}:{p['path']}"
                    answer = answer_for(rec, key, "unknown-content", subject)
                    if answer == "conflict":
                        conflict_paths.append(p)
                    elif answer is None:
                        unanswered = True
                        if not asked(rec, key, "unknown-content", subject):
                            j["questions"].append(_question("unknown-content", key, subject, decl_id, other=other_ref, path=p["path"]))
            if not conflict_paths:
                continue
            subject = f"{o['item']}:{o['id']}"
            answer = answer_for(rec, key, "conflict", subject)
            if answer is None:
                unanswered = True
                if not asked(rec, key, "conflict", subject):
                    j["questions"].append(_question("conflict", key, subject, decl_id, other=other_ref, paths=conflict_paths))
            elif answer == "wait":
                waits.append({"kind": "Issue", "issue": o["item"]})
                blockers.append(o["item"])
            elif answer == "small-pr":
                w = {"kind": "小さな PR", "issue": o["item"]}
                pr = _small_pr_report(o, key)
                if pr:
                    w["pr"] = pr
                waits.append(w)
                blockers.append(o["item"])
                if not _small_pr_requested(o, key):
                    paths = "、".join(p["path"] for p in conflict_paths)
                    body = (f"{key} の宣言 {decl_id} と競合しうるファイル ({paths}) の共通の変更を、先に小さな PR にしてマージする (利用者の答え: small-pr)。"
                            f"作ったら `小さな PR の報告` で PR の URL を書く。")
                    requests.append(_comment(o["item"], "依頼", {"to": o["to"], "assignment": o["assignment"], "request_kind": "小さな PR",
                                                                 "waiting_issue": key, "waiting_declaration": decl_id}, body))
                    request_signals.append(_signal("request", o["to"], o["item"], decl_id, "小さな PR"))
            else:
                proceeds.append({"item": o["item"], "declaration": o["id"], "paths": conflict_paths})
    if unanswered:
        waits.insert(0, dict(_USER_ANSWER))
    if waits:
        j["result"], j["waits"] = ("ask" if unanswered else "wait"), waits
        j["actions"].append(_comment(key, "待機", {**base, "waits": waits}, _wait_body(waits, usage, j)))
        j["actions"] += requests
        j["actions"] += _blocking_actions(item, blockers)
        j["actions"] += _restore_and_removals(item, d, blockers)
        j["signals"].append(_signal("wait", asg["to"], key, decl_id))
        j["signals"] += request_signals
        return j
    # 5. 資源の空き (競合の可能性で待つ・尋ねる宣言は、新しい資源の空きを確かめない。1 か 3 で求めた r を使う)
    res_waits = [{"kind": "資源", "resource": n} for n in r["wait_for"]]
    if r["ask"]:
        res_waits.insert(0, dict(_USER_ANSWER))
        for n in r["ask"]:
            if not asked(rec, key, "resource-busy", n):
                j["questions"].append(_question("resource-busy", key, n, decl_id, resource=n, holders=resources.holders(usage, n, key)))
    if res_waits:
        j["result"], j["waits"] = ("ask" if r["ask"] else "wait"), res_waits
        j["actions"].append(_comment(key, "待機", {**base, "waits": res_waits}, _wait_body(res_waits, usage, j)))
        j["actions"] += _restore_and_removals(item, d, [])
        j["signals"].append(_signal("wait", asg["to"], key, decl_id))
        return j
    # 6. 開始可 (宣言に無い予約の問いは 1 で出してある。`開始可` を書いてから答えを待つ)
    j["result"], j["reserve"] = "go", r["reserve"]
    j["actions"].append(_comment(key, "開始可", base, _go_body(j, j["compared"], proceeds, recompare, rule_text)))
    j["actions"] += _restore_and_removals(item, d, [])
    j["signals"].append(_signal("go", asg["to"], key, decl_id))
    return j


# --- まとめて判定 -------------------------------------------------------------------------

_SLIM_KEYS = ("item", "declaration", "to", "assignment", "update_kind", "repo_config", "result", "waits", "compared", "recompared", "reserve", "release", "keep")


def judge(items, states, rec, attrs_table, pr_states, read_config, table=None, login=None, only=None):
    """未判定の宣言を順に判定する。read_config はリポジトリ (owner/repo) → repo.read_repo_config の結果を返す関数 (リポジトリごとに 1 回呼ぶ)。
    only を渡せばその項目の宣言だけ判定する (相手はすべての項目から集める)。同じ実行で `開始可` にした宣言は、後の宣言の相手になり、予約した資源は
    後の宣言には空いていない。返り値: {"judgments": [judge_one の結果から actions・questions・signals・parsed を除いたもの], "actions", "questions", "signals"}。"""
    table = table if table is not None else filekinds.load_default_table()
    others = go_declarations(items, states, pr_states, login)
    usage = usage_for(states, rec, attrs_table)
    configs = {}
    out = {"judgments": [], "actions": [], "questions": [], "signals": []}
    for entry in pending(items, states):
        key, repo_name = entry["item"]["key"], entry["item"]["repo"]
        if only is not None and not ids.same_issue(key, only):
            continue
        if repo_name.casefold() not in configs:
            configs[repo_name.casefold()] = read_config(repo_name)
        j = judge_one(entry, others, rec, usage, attrs_table, configs[repo_name.casefold()], table, login)
        out["judgments"].append({k: j[k] for k in _SLIM_KEYS})
        out["actions"] += j["actions"]
        out["questions"] += j["questions"]
        out["signals"] += j["signals"]
        for n in j["release"]:  # 解放は結果に依らない (待つ宣言の、宣言に無い予約の解放も含む)
            _drop_usage(usage, n, key)
        if j["result"] == "go":
            others = [o for o in others if not ids.same_issue(o["item"], key)]
            others.append(_other(entry["judged"]["comment_id"], entry["item"], entry["state"], j["parsed"], [], login))
            for n in j["reserve"]:
                _add_usage(usage, n, key)
    return out
