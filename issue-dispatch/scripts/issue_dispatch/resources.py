"""資源 (ラベル `resource:<名前>` と宣言の `resources` で表す、同時に使える数が限られるもの)。属性の読み込み (`attributes`。
設定に無い資源と属性はデフォルト値)、持っている資源の求め方 (`held_from_history`。R20 の (1))、契機ごとの判断
(`judge_assign`・`judge_declare`・`judge_update`・`judge_close`・`judge_release`。属性と、U13 が求めた資源の使用と、記録にある
利用者の回答を引数で受ける)。属性の表と契機の表の正本は issue-dispatch/skills/issue-dispatch/references/resources.md。gh は使わない。

資源の名前は大文字小文字を区別せずに比べる (ラベルの名前を GitHub が区別しないため)。返す名前は、呼び出し元が渡した綴り
(宣言・ラベル・設定) のまま。
"""

from issue_dispatch import declaration, ids

# 属性 (名前 → デフォルト値)。意味と値は resources.md の属性の表
DEFAULTS = {"capacity": 1, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"}
VALUES = {"reserve": ("on_assign", "on_declare"), "when_busy": ("wait", "ask"), "release_undeclared": ("release", "ask")}
TRIGGERS = ("assign", "declare", "update", "close", "release")
# 利用者の回答。when_busy が ask のとき: wait (待機する) / proceed (進める)。release_undeclared が ask のとき: release (解放してよい) / keep (解放してはいけない)
BUSY_ANSWERS = ("wait", "proceed")
UNDECLARED_ANSWERS = ("release", "keep")


def _key(name):
    return name.strip().casefold()


# --- 属性 ---------------------------------------------------------------------------

def attributes(config_resources):
    """設定の `resources` (資源の名前 → 属性のオブジェクト。config が形だけ検査したもの) に、書かれていない属性のデフォルト値を
    当てる。返り値は (表: 名前の casefold → {"name": 設定の綴り, 属性...}, warnings: [{"key", "message"}])。
    未知の属性と誤った値は警告してデフォルト値を使う。綴りだけ違う 2 つ目以降の資源は警告して使わない。"""
    table, warnings = {}, []
    for name, raw in (config_resources or {}).items():
        key = _key(name)
        if key in table:
            warnings.append({"key": f"resources.{name}", "message": f"資源 {name!r} は {table[key]['name']!r} と綴りだけが違う (名前は大文字小文字を区別しない)。使わない"})
            continue
        entry = {"name": name, **DEFAULTS}
        for attr, value in (raw or {}).items():
            if attr not in DEFAULTS:
                warnings.append({"key": f"resources.{name}.{attr}", "message": f"未知の属性 {attr!r} (属性は {', '.join(DEFAULTS)})。使わない"})
                continue
            if attr == "capacity":
                ok = isinstance(value, int) and not isinstance(value, bool) and value >= 1
            else:
                ok = value in VALUES[attr]
            if not ok:
                expected = "1 以上の整数" if attr == "capacity" else " / ".join(VALUES[attr])
                warnings.append({"key": f"resources.{name}.{attr}", "message": f"{attr} の値 {value!r} は誤り ({expected})。デフォルト値 {DEFAULTS[attr]!r} を使う"})
                continue
            entry[attr] = value
        table[key] = entry
    return table, warnings


def attributes_of(table, name):
    """資源の属性。設定に無ければデフォルト値 (name は渡された綴り)。"""
    return dict(table.get(_key(name)) or {"name": name, **DEFAULTS})


# --- 持っている資源 (R20 の (1)) ------------------------------------------------------

def held_from_history(history):
    """今の割り当ての宣言の並び (投稿の順) から持っている資源を求める。history の要素は {"declaration": parse の結果の declaration,
    "go": `開始可` を書いたか, "rejected": 差し戻されたか (省略は偽)}。
    最後に `開始可` を書いた宣言の resources のうち、その後の差し戻されていない更新のすべてに残っているもの (その宣言の綴り)。
    `開始可` の宣言が無ければ空。"""
    accepted = [h for h in history if not h.get("rejected")]
    go_index = max((i for i, h in enumerate(accepted) if h.get("go")), default=None)
    if go_index is None:
        return []
    go = accepted[go_index]["declaration"]
    later = [h["declaration"] for h in accepted[go_index + 1:]]
    return [r for r in go["resources"] if all(_key(r) in {_key(x) for x in d["resources"]} for d in later)]


# --- 判断 ---------------------------------------------------------------------------

def _same_item(a, b):
    # 項目のキー (owner/repo#番号) は owner/repo の大文字小文字を区別しない (GitHub が区別しないため)。参照として読めなければ文字列で比べる
    return ids.same_issue(a, b) or (ids.parse_issue_ref(a) is None and a == b)


def holders(usage, name, except_item=None):
    """資源を持つ項目 (使用 usage: 資源の名前 → 項目のキーの配列。資源の綴りも項目の綴りも問わない) のうち except_item 以外。"""
    out = []
    for key, items in (usage or {}).items():
        if _key(key) == _key(name):
            out += [i for i in items if except_item is None or not _same_item(i, except_item)]
    return out


def _busy(usage, name, item, attrs_table):
    return len(holders(usage, name, item)) >= attributes_of(attrs_table, name)["capacity"]


def _unique(names):
    """名前の重複 (大文字小文字を区別しない) を除き、最初の綴りを残す。"""
    seen, out = set(), []
    for n in names:
        if _key(n) not in seen:
            seen.add(_key(n))
            out.append(n)
    return out


def _answer(answers, name):
    return next((v for k, v in (answers or {}).items() if _key(k) == _key(name)), None)


def judge_assign(item, label_resources, usage, attrs_table, answers):
    """契機「割り当て」。label_resources は項目のラベルの資源。answers は when_busy が ask の資源への回答 (名前 → wait / proceed)。
    返り値: {"result": "assign" (割り当てて reserve を予約する) / "skip" (候補から外す) / "ask" (利用者に尋ねる),
    "reserve": 予約する資源, "busy": 空いていない資源, "ask": 尋ねる資源}。reserve が on_declare の資源は予約せず、空きも待機しない。"""
    reserve, busy, ask = [], [], []
    for name in label_resources:
        a = attributes_of(attrs_table, name)
        if a["reserve"] != "on_assign":
            continue
        if _busy(usage, name, item, attrs_table):
            answer = _answer(answers, name)
            if a["when_busy"] == "ask" and answer != "wait":
                if answer == "proceed":
                    reserve.append(name)
                else:
                    ask.append(name)
            else:
                busy.append(name)
            continue
        reserve.append(name)
    if busy:
        return {"result": "skip", "reserve": [], "busy": busy, "ask": []}
    if ask:
        return {"result": "ask", "reserve": [], "busy": [], "ask": ask}
    return {"result": "assign", "reserve": reserve, "busy": [], "ask": []}


def _check_new(item, names, usage, attrs_table, answers):
    """予約していない資源の空きを確かめる。返り値は (reserve, wait_for, ask)。"""
    reserve, wait_for, ask = [], [], []
    for name in names:
        if _busy(usage, name, item, attrs_table):
            answer = _answer(answers, name)
            if attributes_of(attrs_table, name)["when_busy"] == "ask" and answer != "wait":
                (reserve if answer == "proceed" else ask).append(name)
            else:
                wait_for.append(name)
        else:
            reserve.append(name)
    return reserve, wait_for, ask


def judge_declare(item, declared, reserved, usage, attrs_table, answers, undeclared_answers):
    """契機「着手の宣言」。declared は宣言の resources、reserved は割り当てで予約した資源。answers は when_busy が ask の資源への回答、
    undeclared_answers は release_undeclared が ask の資源への回答 (名前 → release / keep)。
    返り値: {"result": "go" (`開始可` を書くときに reserve を予約する) / "wait" (`待機`。どれも予約しない) / "ask",
    "reserve", "wait_for", "ask", "release" (解放する宣言に無い予約), "keep" (回答を待機する・残す予約), "ask_undeclared" (尋ねる),
    "request_rewrite" (解放してはいけないので書き直しを頼む)}。宣言に無い予約の扱いは go / wait / ask に依らない。"""
    declared, reserved = _unique(declared), _unique(reserved)
    reserved_keys = {_key(r) for r in reserved}
    new = [r for r in declared if _key(r) not in reserved_keys]
    reserve, wait_for, ask = _check_new(item, new, usage, attrs_table, answers)
    declared_keys = {_key(r) for r in declared}
    release, keep, ask_undeclared, request_rewrite = [], [], [], []
    for name in reserved:
        if _key(name) in declared_keys:
            continue
        if attributes_of(attrs_table, name)["release_undeclared"] == "release":
            release.append(name)
            continue
        answer = _answer(undeclared_answers, name)
        if answer == "release":
            release.append(name)
        elif answer == "keep":
            keep.append(name)
            request_rewrite.append(name)
        else:
            keep.append(name)
            ask_undeclared.append(name)
    result = "wait" if wait_for else ("ask" if ask else "go")
    return {"result": result, "reserve": reserve if result == "go" else [], "wait_for": wait_for, "ask": ask,
            "release": release, "keep": keep, "ask_undeclared": ask_undeclared, "request_rewrite": request_rewrite}


def judge_update(item, kind, held, declared, usage, attrs_table, answers):
    """契機「宣言の更新」。kind は更新の種類 (declaration.update_kind の結果。declaration.UPDATE_KINDS)、held は持っている資源、
    declared は更新の resources。外した資源は解放し、足した資源 (前に外して足し直したものも含む) は着手の宣言と同じに空きを
    確かめる。資源を外すだけの更新 (resources-removed-only) は判定せず `開始可` を書かないので result は "skip" (release は返す)。
    返り値: {"result": "go" / "wait" / "ask" / "skip", "reserve", "wait_for", "ask", "release"}。kind が種類でなければ ValueError。"""
    if kind not in declaration.UPDATE_KINDS:
        raise ValueError(f"更新の種類は {', '.join(declaration.UPDATE_KINDS)} のどれか: {kind!r}")
    held, declared = _unique(held), _unique(declared)
    held_keys = {_key(r) for r in held}
    declared_keys = {_key(r) for r in declared}
    added = [r for r in declared if _key(r) not in held_keys]
    release = [r for r in held if _key(r) not in declared_keys]
    if kind == "resources-removed-only":
        return {"result": "skip", "reserve": [], "wait_for": [], "ask": [], "release": release}
    reserve, wait_for, ask = _check_new(item, added, usage, attrs_table, answers)
    result = "wait" if wait_for else ("ask" if ask else "go")
    return {"result": result, "reserve": reserve if result == "go" else [], "wait_for": wait_for, "ask": ask, "release": release}


def judge_close(item, usage):
    """契機「Issue の close・割り当ての解除」。その項目が持つ資源をすべて解放する。返り値: {"release": [資源 (usage の綴り)]}。"""
    return {"release": [name for name, items in (usage or {}).items() if any(_same_item(i, item) for i in items)]}


def judge_release(resource, waiting):
    """契機「資源の解放」。waiting は `待機` になっている宣言の配列 ({"item", "declaration", "posted_at", "position", "wait_for": [資源]})。
    その資源で待機していた宣言を、投稿の順 (同じなら Project の中の順) に返す。返り値: {"rejudge": [...]}。"""
    hit = [w for w in waiting if any(_key(r) == _key(resource) for r in w.get("wait_for") or [])]
    return {"rejudge": sorted(hit, key=lambda w: (w.get("posted_at") or "", w.get("position") if w.get("position") is not None else 0))}
