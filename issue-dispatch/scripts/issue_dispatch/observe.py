"""観測のうちスナップショットと差分。`snapshot.json` (ポーリングの基準になる Project の状態の写し) の読み書き、項目の読み取り
からの作成 (`build_snapshot`)、コメントに URL で書かれた PR の収集 (`pr_urls_in_comments`)、書いた値の反映 (`reflect`)、
スナップショットと今の内容の差分 (`diff`。何が変わったかだけを処理の順に返し、意味づけはしない)。
様式・差分の種類と処理の順の正本は issue-dispatch/skills/issue-dispatch/references/observation.md。保存先の正本は records.md。

このモジュールは gh を実行しない (項目の読み取りは project.items、PR の状態は issues.pr_state を呼び出し元が行う)。
"""

import copy
import json
import os
import re
import tempfile

from issue_dispatch import comments, ids

SNAPSHOT_FILE = "snapshot.json"
SNAPSHOT_VERSION = 1
SNAPSHOT_KEYS = ("version", "taken_at", "project_id", "items", "comment_prs")
ITEM_KEYS = ("item_id", "position", "state", "status", "fields", "assignees", "labels", "blocked_by", "body_edited_at", "comment_ids", "prs", "partial", "carried")
# 項目の一覧そのものの欠損 (読めなかった項目が除去と読まれる) と、1 項目の中の欠損 (その項目だけ比べない) を分ける
LIST_PROBLEMS = ("items-page", "graphql-errors")
# 差分の種類と処理の順 (observation.md の表): 人の変更 → close・reopen と項目の除去 → blockedBy → コメント → PR → 項目の追加・並び順・本文の編集
DIFF_KINDS = ("status", "field", "assignees", "labels", "closed", "reopened", "removed", "blocked_by", "comment", "pr", "added", "position", "body_edit")
# 1 項目の中の欠損の種類 (project items の problems の what) → その欠損の影響を受ける値の差分の種類 (比べない)。対応に無い種類は項目全体を比べない。
# 対応は GraphQL の connection ごとに導く値で決める (fieldValues からは fields と Status の 2 つを読む)
PARTIAL_SKIPS = {"labels-truncated": ("labels",), "blocked_by-truncated": ("blocked_by",), "body_edits-truncated": ("body_edit",),
                 "prs-truncated": ("pr",), "fields-truncated": ("field", "status"), "comments": ("comment",), "events": ()}
# 1 項目の中の欠損の種類 → その欠損の影響を受けるスナップショットの値 (前のスナップショットから引き継ぐ値)。PARTIAL_SKIPS と同じ種類を持つ
PARTIAL_VALUES = {"labels-truncated": ("labels",), "blocked_by-truncated": ("blocked_by",), "body_edits-truncated": ("body_edited_at",),
                  "prs-truncated": ("prs",), "fields-truncated": ("fields", "status"), "comments": ("comment_ids",), "events": ()}
# コメントの本文から PR を読む種類
PR_URL_COMMENT_KINDS = ("PR の報告",)
_PR_URL_RE = re.compile(rf"https://github\.com/{ids.REPO_NAME_PATTERN}/pull/[1-9][0-9]*")


# --- ファイル ---------------------------------------------------------------------

def load_snapshot(directory):
    """返り値: {"status": "ok", "snapshot"} / {"status": "missing"} / {"status": "corrupt", "message"}。"""
    path = os.path.join(directory, SNAPSHOT_FILE)
    if not os.path.exists(path):
        return {"status": "missing", "snapshot": None, "path": path}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return {"status": "corrupt", "snapshot": None, "path": path, "message": f"読めない: {e}"}
    if not isinstance(data, dict) or any(k not in data for k in SNAPSHOT_KEYS) or not isinstance(data["items"], dict) or not isinstance(data["comment_prs"], dict):
        return {"status": "corrupt", "snapshot": None, "path": path, "message": f"キー {', '.join(SNAPSHOT_KEYS)} を持つオブジェクトではない"}
    return {"status": "ok", "snapshot": data, "path": path}


def save_snapshot(directory, snapshot):
    """一時ファイル (records.md の一時名の規則: `.` で始まり `.tmp` で終わる名前。書き込み元ごとに別) に書き、fsync してから
    os.replace で置き換える (record.save と同じ形)。返り値はパス。"""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, SNAPSHOT_FILE)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


# --- 作成 -----------------------------------------------------------------------

def _pr_state(p):
    return {"state": p["state"], "draft": bool(p.get("draft")), "merged": bool(p.get("merged"))}


def snapshot_item(item, partial=(), previous=None, previous_taken_at=None):
    """project.items の項目 (Issue) を、スナップショットが持つ値だけにする。partial はその項目の欠損の種類 (problems の what)。
    previous (前のスナップショットの同じ項目) があれば、その種類の欠損の影響を受ける値 (PARTIAL_VALUES) は前の値を引き継ぎ、`carried` (種類 →
    引き継いだ値の元の taken_at) に残して `partial` には入れない。前の項目でも同じ種類が partial なら引き継ぐ元が無いので、今読んだ値のまま
    `partial` に入れる。"""
    fields = {name: {"value": v.get("text") if "text" in v else v.get("name"), "updated_at": v.get("updated_at")} for name, v in (item.get("fields") or {}).items()}
    edits = [e.get("edited_at") for e in item.get("body_edits") or [] if e.get("edited_at")]
    out = {"item_id": item["item_id"], "position": item["position"], "state": item.get("state"),
           "status": (item.get("status") or {}).get("name"), "fields": fields,
           "assignees": sorted(item.get("assignees") or []), "labels": sorted(item.get("labels") or []),
           "blocked_by": {b["key"]: b["state"] for b in item.get("blocked_by") or []},
           "body_edited_at": max(edits) if edits else None,
           "comment_ids": sorted(c["database_id"] for c in item.get("comments") or [] if c.get("database_id") is not None),
           "prs": {p["url"]: _pr_state(p) for p in item.get("prs") or []},
           "partial": [], "carried": {}}
    for what in sorted(set(partial)):
        keys = PARTIAL_VALUES.get(what)
        if keys and previous is not None and what not in (previous.get("partial") or []):
            for k in keys:
                out[k] = copy.deepcopy(previous[k])
            out["carried"][what] = (previous.get("carried") or {}).get(what) or previous_taken_at
        else:
            out["partial"].append(what)
    return out


def build_snapshot(items_result, comment_prs, taken_at, previous=None):
    """project.items の結果と、コメントの URL の PR の状態 (URL → {state, draft, merged}。読めなかった PR は {"partial": 理由}) から
    スナップショットを作る。Issue 以外の項目 (draft issue・PR) は持たない。items_result の problems のうち項目 1 つの中の欠損
    (item を持つもの) は、previous (前のスナップショット) に引き継ぐ元があれば前の値を引き継ぎ (snapshot_item)、無ければその項目の
    `partial` に種類を残す。読めなかった PR も、previous に状態があれば引き継いで `carried` (元の taken_at) を持たせる。項目の一覧
    そのものの欠損 (LIST_PROBLEMS) は呼び出し元が先に処理を中断する。"""
    partial = {}
    for p in items_result.get("problems") or []:
        if p.get("item") and p.get("what") not in LIST_PROBLEMS:
            partial.setdefault(p["item"], []).append(p["what"])
    prev_items = (previous or {}).get("items") or {}
    prev_taken_at = (previous or {}).get("taken_at")
    items = {it["key"]: snapshot_item(it, partial.get(it["key"], ()), prev_items.get(it["key"]), prev_taken_at)
             for it in items_result.get("items") or [] if it.get("key")}
    prev_prs = (previous or {}).get("comment_prs") or {}
    prs = {}
    for url, v in (comment_prs or {}).items():
        prev = prev_prs.get(url)
        if "partial" in v and prev is not None and "partial" not in prev:
            prs[url] = {**_pr_state(prev), "carried": prev.get("carried") or prev_taken_at}
        else:
            prs[url] = dict(v) if "partial" in v else _pr_state(v)
    return {"version": SNAPSHOT_VERSION, "taken_at": taken_at, "project_id": items_result.get("project_id"), "items": items, "comment_prs": prs}


def carried(snapshot):
    """スナップショットで前の値を引き継いだ項目の種類と PR。返り値は {"items": {キー: {種類: 元の taken_at}}, "prs": {URL: 元の taken_at}}。"""
    items = {key: it["carried"] for key, it in snapshot["items"].items() if it.get("carried")}
    prs = {url: v["carried"] for url, v in snapshot["comment_prs"].items() if isinstance(v, dict) and "carried" in v}
    return {"items": items, "prs": prs}


def skipped(before, after):
    """2 つのスナップショットで欠損がある項目と PR (どちらかで欠損があるもの)。項目はその種類の欠損の影響を受ける値だけを比べず (diff)、
    PR は比べない。返り値は {"items": {キー: 欠損の種類}, "prs": {URL: 理由}}。"""
    items = {}
    for snap in (before, after):
        for key, it in snap["items"].items():
            if it.get("partial"):
                items.setdefault(key, [])
                items[key] = sorted(set(items[key]) | set(it["partial"]))
    prs = {}
    for snap in (before, after):
        for url, v in snap["comment_prs"].items():
            if isinstance(v, dict) and "partial" in v:
                prs[url] = v["partial"]
    return {"items": items, "prs": prs}


def pr_urls_in_comments(items, login):
    """開いている項目のコメントのうち、投稿者が login で、`PR の報告` の本文に書かれた PR の URL と、`待機` の理由 `小さな PR` の PR を、
    見つけた順に (重複なく) 返す。閉じた項目は読まない。"""
    out = []
    for item in items:
        if not item.get("key") or item.get("state") != "OPEN":
            continue
        for c in item.get("comments") or []:
            if c.get("author") != login:
                continue
            header, body = comments.split_body(c.get("body"))
            if header is None:
                continue
            urls = []
            if header["kind"] in PR_URL_COMMENT_KINDS:
                urls = [m.group(0) for m in _PR_URL_RE.finditer(body)]
            elif header["kind"] == "待機":
                urls = [w["pr"] for w in header["values"].get("waits") or [] if w.get("pr")]
            for url in urls:
                normalized = ids.parse_pr_url(url)["url"]
                if normalized not in out:
                    out.append(normalized)
    return out


# --- 反映 -----------------------------------------------------------------------

def reflect(snapshot, op):
    """書いた値をスナップショットに反映する。op は {"kind": status | field | comment | blocked_by | labels | assignees, "item": キー, ...}
    (値のキーは observation.md の「書いた値の反映」)。返り値は (snapshot, None) か (snapshot, 問題の文)。反映できない op では変えない。"""
    kind = op.get("kind")
    key = op.get("item")
    item = next((v for k, v in snapshot["items"].items() if ids.same_issue(k, key)), None) if key else None
    if item is None:
        return snapshot, f"スナップショットに項目 {key!r} が無い"
    if kind == "status":
        item["status"] = op.get("value")
    elif kind == "field":
        entry = item["fields"].setdefault(op["field"], {"value": None, "updated_at": None})
        entry["value"] = op.get("value")
        entry["updated_at"] = op.get("updated_at") or entry.get("updated_at")
    elif kind == "comment":
        if op.get("id") is not None and op["id"] not in item["comment_ids"]:
            item["comment_ids"] = sorted(item["comment_ids"] + [op["id"]])
    elif kind == "blocked_by":
        blocker = ids.issue_key(op.get("blocker"))
        if blocker is None:
            return snapshot, f"blocker {op.get('blocker')!r} は Issue の参照ではない"
        if op.get("action") == "add":
            item["blocked_by"][blocker] = op.get("state") or "OPEN"
        elif op.get("action") == "remove":
            item["blocked_by"].pop(blocker, None)
        else:
            return snapshot, f"blocked_by の action は add か remove: {op.get('action')!r}"
    elif kind in ("labels", "assignees"):
        current = set(item[kind]) - set(op.get("remove") or []) | set(op.get("add") or [])
        item[kind] = sorted(current)
    else:
        return snapshot, f"反映の種類ではない: {kind!r}"
    return snapshot, None


# --- 差分 -----------------------------------------------------------------------

def _kind_index(kind):
    return DIFF_KINDS.index(kind)


def _pr_view(v):
    """comment_prs の値のうち比べる部分 (state・draft・merged。引き継ぎのフラグ carried は比べない)。"""
    return None if v is None else _pr_state(v)


def _omitted_kinds(partial):
    """項目の欠損の種類 (前後の partial の和) から、比べない差分の種類の集合を返す。対応 (PARTIAL_SKIPS) に無い種類があれば、
    どの値が影響を受けるか分からないので None (項目のすべての値を比べない)。"""
    if any(what not in PARTIAL_SKIPS for what in partial):
        return None
    return {kind for what in partial for kind in PARTIAL_SKIPS[what]}


def _item_diffs(key, b, a):
    """両方にある 1 項目の値の違い (欠損は見ない)。"""
    out = []
    if b["status"] != a["status"]:
        out.append({"kind": "status", "item": key, "before": b["status"], "after": a["status"]})
    for name in sorted(set(b["fields"]) | set(a["fields"])):
        bv, av = (b["fields"].get(name) or {}).get("value"), (a["fields"].get(name) or {}).get("value")
        if bv != av:
            out.append({"kind": "field", "item": key, "field": name, "before": bv, "after": av})
    for kind in ("assignees", "labels"):
        added, removed = sorted(set(a[kind]) - set(b[kind])), sorted(set(b[kind]) - set(a[kind]))
        if added or removed:
            out.append({"kind": kind, "item": key, "added": added, "removed": removed})
    if b["state"] != a["state"]:
        out.append({"kind": "closed" if a["state"] == "CLOSED" else "reopened", "item": key, "before": b["state"], "after": a["state"]})
    added = sorted(set(a["blocked_by"]) - set(b["blocked_by"]))
    removed = sorted(set(b["blocked_by"]) - set(a["blocked_by"]))
    changed = [{"key": k, "before": b["blocked_by"][k], "after": a["blocked_by"][k]} for k in sorted(set(a["blocked_by"]) & set(b["blocked_by"])) if a["blocked_by"][k] != b["blocked_by"][k]]
    if added or removed or changed:
        out.append({"kind": "blocked_by", "item": key, "added": added, "removed": removed, "state_changed": changed})
    new_comments = sorted(set(a["comment_ids"]) - set(b["comment_ids"]))
    if new_comments:
        out.append({"kind": "comment", "item": key, "ids": new_comments})
    for url in sorted(set(a["prs"]) | set(b["prs"])):
        if b["prs"].get(url) != a["prs"].get(url):
            out.append({"kind": "pr", "item": key, "url": url, "source": "reference", "before": b["prs"].get(url), "after": a["prs"].get(url)})
    if b["body_edited_at"] != a["body_edited_at"]:
        out.append({"kind": "body_edit", "item": key, "before": b["body_edited_at"], "after": a["body_edited_at"]})
    return out


def diff(before, after):
    """2 つのスナップショットの違いを、処理の順 (DIFF_KINDS の順、同じ種類は今の位置の順) に並べて返す。意味づけはしない。
    要素は {"kind", "item" (コメントの URL の PR は None), ...} で、種類ごとの値は observation.md の表。
    前後どちらかに欠損 (partial) がある項目は、その種類の欠損の影響を受ける値 (PARTIAL_SKIPS) だけを比べない (欠損を変化と読まないため)。
    欠損と関係のない値と、項目の追加・除去・並び順は比べる。"""
    out = []
    skip = skipped(before, after)
    b_items, a_items = before["items"], after["items"]
    for key, a in a_items.items():
        b = b_items.get(key)
        if b is None:
            out.append({"kind": "added", "item": key, "position": a["position"]})
            continue
        omitted = _omitted_kinds(skip["items"].get(key, ()))
        if omitted is None:
            continue
        out += [d for d in _item_diffs(key, b, a) if d["kind"] not in omitted]
    for key, b in b_items.items():
        if key not in a_items:
            out.append({"kind": "removed", "item": key, "position": b["position"]})
    # 並び順: 両方にある項目の相対の順が変わったときだけ 1 件 (位置の数値は追加・除去でずれるので比べない)
    common = [k for k in a_items if k in b_items]
    before_order = sorted(common, key=lambda k: b_items[k]["position"])
    after_order = sorted(common, key=lambda k: a_items[k]["position"])
    if before_order != after_order:
        out.append({"kind": "position", "item": None, "before": before_order, "after": after_order})
    for url in sorted(set(before["comment_prs"]) | set(after["comment_prs"])):
        if url in skip["prs"]:
            continue
        b, a = _pr_view(before["comment_prs"].get(url)), _pr_view(after["comment_prs"].get(url))
        if b != a:
            out.append({"kind": "pr", "item": None, "url": url, "source": "comment", "before": b, "after": a})
    positions = {k: v["position"] for k, v in a_items.items()}
    positions.update({k: v["position"] for k, v in b_items.items() if k not in positions})
    return sorted(out, key=lambda d: (_kind_index(d["kind"]), positions.get(d["item"], 0) if d["item"] else 0, d.get("url") or ""))
