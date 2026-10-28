"""宣言 (作業のセッションが変える予定のファイルと節と資源を書く JSON)。形の検査とパスの正規化 (`parse`)、更新の種類の判定
(`held_resources`・`update_kind`・`resource_changes`。R20)、競合の可能性の判定 (`conflictability`。R5)、PR が変えたファイルと
宣言の照合 (`pr_files_check`。R21)。様式と判定の規則の SSOT は issue-dispatch/skills/issue-dispatch/references/issue-format.md の
「宣言」。種類は filekinds がパスから決める (宣言に `kind` は書けない。KTD9)。gh は使わない。

形の検査は必須キーと未知のキーで行う (docs/solutions/design-patterns/typed-contract-for-agent-input.md)。パスはリポジトリの
ルート基準で、絶対パスとルートの外を指すパスは差し戻す (docs/solutions/tooling-decisions/require-explicit-basis-for-relative-paths.md)。
"""

import posixpath

from issue_dispatch import filekinds, ids

REQUIRED_KEYS = ("files", "resources", "split")
FILE_KEYS = ("path", "units")
SPLIT_KEYS = ("needed", "reason", "remaining", "blocked_by")
# 更新の種類 (R20)。initial: まだ `開始可` の宣言が無い (着手の宣言と同じに扱う)。full: ファイルか節が違う (または何も変わらない)。
# resources-only: ファイルと節が最後に `開始可` を書いた宣言と同じで、資源だけが持っている資源と違う。resources-removed-only: そのうち
# 持っている資源から 1 つ以上を外し、足した資源が無いもの (判定しない)
UPDATE_KINDS = ("initial", "full", "resources-only", "resources-removed-only")
# 競合の可能性 (R5)。conflict: 競合しうる。none: 競合しない。needs-user: 利用者の判定が要る (`unknown-content` を含む組)
CONFLICT_RESULTS = ("conflict", "none", "needs-user")
# 節の表記が無く、units を書けない種類 (規則に unit_notation が無い divisible なども書けない)
_NO_UNITS_KINDS = ("generated", "unknown-content", "unknown-structure")


def _resource_key(name):
    # 資源の名前は大文字小文字を区別しない (ラベルの名前を GitHub が区別しないため。SSOT は resources.md)
    return name.strip().casefold()


# --- 形の検査とパスの正規化 ---------------------------------------------------------

def normalize_path(path):
    """宣言のパス (リポジトリのルートからの相対パス) をそろえる。返り値は (そろえたパス, None) か (None, 問題)。
    posixpath.normpath で `./`・`//`・`a/../` を解き、絶対パス・ルートの外 (`..` で始まる)・ルートそのものを差し戻す。
    files classify (filekinds.normalize_path) と違い、`src/../src/app.ts` は `src/app.ts` として受け付ける。"""
    if not isinstance(path, str) or not path.strip():
        return None, f"パスは空でない文字列: {path!r}"
    if path.startswith("/"):
        return None, f"絶対パス {path!r} は使えない (リポジトリのルートからの相対パスを書く)"
    normalized = posixpath.normpath(path)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        return None, f"パス {path!r} はルートそのものかルートの外を指すので使えない"
    return normalized, None


def _check_units(units, key, errors):
    expected = "文字列の配列の配列 (1 つの節は、親にあたる名前から順に名前を並べた文字列の配列。例: [[\"dependencies\", \"zod\"]])"
    if not isinstance(units, list):
        errors.append({"key": key, "message": f"units は {expected}: {units!r}"})
        return None
    if not units:
        errors.append({"key": key, "message": "units の空の配列は書けない (ファイル全体を変える予定なら units を省く)"})
        return None
    out, own = [], []
    for i, unit in enumerate(units):
        if not isinstance(unit, list) or not unit or not all(isinstance(n, str) and n != "" for n in unit):
            own.append({"key": f"{key}[{i}]", "message": f"units の要素は {expected}: {unit!r}"})
            continue
        out.append(list(unit))
    errors.extend(own)
    return out if not own else None  # 自分が足した誤りだけで決める (ほかのファイルの誤りで後の検査を飛ばさない)


def _check_file(entry, index, rules, table, errors, seen):
    key = f"files[{index}]"
    if not isinstance(entry, dict):
        errors.append({"key": key, "message": f"files の要素はオブジェクト (path と、省略できる units): {entry!r}"})
        return None
    for k in entry:
        if k not in FILE_KEYS:
            errors.append({"key": f"{key}.{k}", "message": f"未知のキー {k!r} (files の要素のキーは path と units。種類はスクリプトがパスから決めるので kind は書かない)"})
    if "path" not in entry:
        errors.append({"key": f"{key}.path", "message": "path は必須 (リポジトリのルートからの相対パス)"})
        return None
    path, problem = normalize_path(entry["path"])
    if problem:
        errors.append({"key": f"{key}.path", "message": problem})
        return None
    if path in seen:
        errors.append({"key": f"{key}.path", "message": f"同じパス {path!r} が files[{seen[path]}] にもある (1 つにまとめる)"})
        return None
    seen[path] = index
    kind = filekinds.classify(path, rules, table) if rules is not None else None
    units = None
    if "units" in entry and entry["units"] is not None:
        units = _check_units(entry["units"], f"{key}.units", errors)
        if units is not None and kind is not None and (kind["kind"] in _NO_UNITS_KINDS or not kind.get("unit_notation")):
            matched = kind["matched"]
            how = (f"一致した規則: {matched['source']} の {matched['pattern']!r}" if matched else "どの規則にも一致しない")
            errors.append({"key": f"{key}.units", "message": f"パス {path!r} の種類は {kind['kind']} で節の表記 (unit_notation) が無いので、units は書けない ({how})"})
            return None
    return {"path": path, "units": units, "kind": kind}


def _check_split(split, errors):
    if not isinstance(split, dict):
        errors.append({"key": "split", "message": f"split はオブジェクト (needed と reason。必要なら remaining と blocked_by): {split!r}"})
        return None
    for k in split:
        if k not in SPLIT_KEYS:
            errors.append({"key": f"split.{k}", "message": f"未知のキー {k!r} (split のキーは {', '.join(SPLIT_KEYS)})"})
    needed = split.get("needed")
    if not isinstance(needed, bool):
        errors.append({"key": "split.needed", "message": f"needed は真偽値: {needed!r}"})
        return None
    out = {"needed": needed, "reason": split.get("reason"), "remaining": None, "blocked_by": None}
    if needed:
        for k in ("reason", "remaining"):
            if not isinstance(split.get(k), str) or not split[k].strip():
                errors.append({"key": f"split.{k}", "message": f"needed が真なら {k} は必須 (空でない文字列)"})
        if "blocked_by" not in split:
            errors.append({"key": "split.blocked_by", "message": "needed が真なら blocked_by は必須 (Issue の参照の配列。大きさのために分けるなら空の配列)"})
        elif not isinstance(split["blocked_by"], list):
            errors.append({"key": "split.blocked_by", "message": f"blocked_by は Issue の参照の配列: {split['blocked_by']!r}"})
        else:
            refs = []
            for i, ref in enumerate(split["blocked_by"]):
                k = ids.issue_key(ref)
                if k is None:
                    errors.append({"key": f"split.blocked_by[{i}]", "message": f"blocked_by の要素は Issue の参照 (owner/repo#番号 か URL): {ref!r}"})
                else:
                    refs.append(k)
            out["blocked_by"] = refs
        out["remaining"] = split.get("remaining")
    else:
        if not isinstance(out["reason"], str):
            errors.append({"key": "split.reason", "message": f"reason は文字列: {out['reason']!r}"})
        for k in ("remaining", "blocked_by"):
            if k in split:
                errors.append({"key": f"split.{k}", "message": f"needed が偽なら {k} は書かない"})
    return out


def parse(obj, rules, default_table):
    """宣言の JSON (dict) を検査し、パスをそろえ、種類を付ける。

    返り値: {"status": "ok", "declaration": {"files": [{"path", "units" (None なら全体), "kind" (filekinds.classify の結果)}],
    "resources": [...], "split": {"needed", "reason", "remaining", "blocked_by" (正規形の配列か None)}}, "count": ファイルの数, "errors": []}
    か、{"status": "error", "declaration": None, "count": None, "errors": [{"key", "message"}]} (誤りはできるだけ全部集める)。
    rules が None なら種類を付けず (kind は None)、種類に依る検査 (節の表記の無いファイルの units) だけを飛ばす。形の検査とパスの正規化は同じ
    (コメントの宣言を読む導出 (itemstate) が、リポジトリの設定を読まずに同じ検査を使うため)。
    """
    errors = []
    if not isinstance(obj, dict):
        return {"status": "error", "declaration": None, "count": None,
                "errors": [{"key": "(root)", "message": f"宣言は files・resources・split を持つオブジェクト: {type(obj).__name__}"}]}
    for k in obj:
        if k not in REQUIRED_KEYS:
            errors.append({"key": k, "message": f"未知のキー {k!r} (宣言のキーは {', '.join(REQUIRED_KEYS)})"})
    for k in REQUIRED_KEYS:
        if k not in obj:
            errors.append({"key": k, "message": f"{k} は必須"})
    if errors:
        return {"status": "error", "declaration": None, "count": None, "errors": errors}
    files = []
    if not isinstance(obj["files"], list):
        errors.append({"key": "files", "message": f"files は配列: {obj['files']!r}"})
    else:
        seen = {}
        for i, entry in enumerate(obj["files"]):
            f = _check_file(entry, i, rules, default_table, errors, seen)
            if f:
                files.append(f)
    resources = []
    if not isinstance(obj["resources"], list):
        errors.append({"key": "resources", "message": f"resources は資源の名前 (文字列) の配列: {obj['resources']!r}"})
    else:
        seen_resources = {}
        for i, r in enumerate(obj["resources"]):
            if not isinstance(r, str) or not r.strip() or any(c.isspace() for c in r):
                errors.append({"key": f"resources[{i}]", "message": f"資源の名前は空白を含まない文字列: {r!r}"})
            elif _resource_key(r) in seen_resources:
                # 資源の名前は大文字小文字を区別しない (SSOT は resources.md) ので、表記だけ違う重複も差し戻す
                errors.append({"key": f"resources[{i}]", "message": f"同じ資源 {r!r} が resources[{seen_resources[_resource_key(r)]}] にもある (名前は大文字小文字を区別しない。1 つにまとめる)"})
            else:
                seen_resources[_resource_key(r)] = i
                resources.append(r)
    split = _check_split(obj["split"], errors)
    if errors:
        return {"status": "error", "declaration": None, "count": None, "errors": errors}
    return {"status": "ok", "declaration": {"files": files, "resources": resources, "split": split}, "count": len(files), "errors": []}


# --- 更新の種類 (R20) -------------------------------------------------------------

def _file_key(f):
    return (f["path"], None if f["units"] is None else frozenset(tuple(u) for u in f["units"]))


def same_files(a, b):
    """2 つの宣言のファイルと節が同じか (順序は問わない)。"""
    return {_file_key(f) for f in a["files"]} == {_file_key(f) for f in b["files"]}


def held_resources(go_declaration, later_updates):
    """持っている資源: 最後に `開始可` を書いた宣言の resources のうち、その後のどの宣言の更新にも残っているもの (集合。
    `開始可` の宣言の表記)。`開始可` の宣言がまだ無ければ空。差し戻された宣言は later_updates に入れない。"""
    if go_declaration is None:
        return set()
    held = list(go_declaration["resources"])
    for update in later_updates:
        keys = {_resource_key(r) for r in update["resources"]}
        held = [r for r in held if _resource_key(r) in keys]
    return set(held)


def resource_changes(new_declaration, held):
    """新しい宣言の資源と持っている資源の差: {"added": 足した資源 (新しい宣言の表記), "removed": 外した資源 (held の表記)}
    (名前の順。大文字小文字は区別しない)。"""
    held_keys = {_resource_key(r) for r in held}
    new_keys = {_resource_key(r) for r in new_declaration["resources"]}
    return {"added": sorted(r for r in new_declaration["resources"] if _resource_key(r) not in held_keys),
            "removed": sorted(r for r in held if _resource_key(r) not in new_keys)}


def update_kind(go_declaration, new_declaration, held):
    """更新の種類 (UPDATE_KINDS)。go_declaration は最後に `開始可` を書いた宣言 (無ければ None)、held は held_resources の結果。"""
    if go_declaration is None:
        return "initial"
    if not same_files(go_declaration, new_declaration):
        return "full"
    changes = resource_changes(new_declaration, held)
    if not changes["added"] and not changes["removed"]:
        return "full"
    if not changes["added"]:
        return "resources-removed-only"
    return "resources-only"


# --- 競合の可能性 (R5) -------------------------------------------------------------

def _unit_overlaps(a, b):
    """節が同じか、一方が他方の先頭部分か (名前は正規化せず、配列の要素ごとに比べる)。"""
    n = min(len(a), len(b))
    return list(a[:n]) == list(b[:n])


def judge_path(mine, other):
    """同じパスの 2 つのファイルの宣言 (parse の files の要素) を比べる。返り値は (結果, 理由)。"""
    kind = mine["kind"]["kind"]
    if kind == "generated":
        return "none", "種類が generated (生成物は作り直せる)"
    if kind == "unknown-content" or other["kind"]["kind"] == "unknown-content":
        return "needs-user", "種類が unknown-content (どの規則にも一致しない) なので、利用者の判定が要る"
    if kind == "unknown-structure":
        return "conflict", "種類が unknown-structure (構造を知らない) なので、同じパスで競合しうる"
    if mine["units"] is None or other["units"] is None:
        return "conflict", "どちらかが units を省いている (ファイル全体を変える予定) ので、同じパスで競合しうる"
    for a in mine["units"]:
        for b in other["units"]:
            if _unit_overlaps(a, b):
                return "conflict", f"節 {a!r} と {b!r} が同じか、一方が他方の先頭部分"
    return "none", "両方が units を書き、同じ節も先頭部分の一致も無い"


def _worst(results):
    for r in ("conflict", "needs-user"):
        if r in results:
            return r
    return "none"


def conflictability(mine, others):
    """競合の可能性の判定。mine は {"repo": "owner/name", "declaration": parse の結果の declaration}、others はその配列
    (要素に "id" を付けられる。比べる相手は既に `開始可` になった宣言)。

    相手の "declaration" が None なら解析できなかった相手 ("problems" に理由) で、自動では判定できないので needs-user にする
    (過去に受理された宣言が、今のリポジトリの設定の規則では読めないときなど。相手 1 つのためにほかの判定を中断しない)。

    返り値: {"result": 全体の結論 (CONFLICT_RESULTS。conflict > needs-user > none), "others": [{"id", "repo", "result",
    "paths": [{"path", "result", "reason"}] (同じリポジトリの同じパスだけ), "problems" (解析できない相手の理由。無ければ空)}]}。
    別のリポジトリの相手は paths が空で none。
    """
    my_files = {f["path"]: f for f in mine["declaration"]["files"]}
    out = []
    for other in others:
        paths = []
        if other.get("declaration") is None:
            out.append({"id": other.get("id"), "repo": other["repo"], "result": "needs-user", "paths": [],
                        "problems": list(other.get("problems") or [{"key": "declaration", "message": "宣言を解析できない"}])})
            continue
        if other["repo"].lower() == mine["repo"].lower():
            for f in other["declaration"]["files"]:
                if f["path"] in my_files:
                    result, reason = judge_path(my_files[f["path"]], f)
                    paths.append({"path": f["path"], "result": result, "reason": reason})
        out.append({"id": other.get("id"), "repo": other["repo"], "result": _worst([p["result"] for p in paths]), "paths": paths, "problems": []})
    return {"result": _worst([o["result"] for o in out]), "others": out}


# --- PR が変えたファイルと宣言の照合 (R21) ------------------------------------------

def pr_files_check(changed_paths, repo, latest_declaration, others, rules, default_table):
    """PR が変えたファイル (`pr observe` の files の path) を最新の宣言と比べる。

    返り値: {"undeclared": [{"path", "kind", "declared_by": [同じリポジトリでそのファイルを宣言しているほかの `開始可` の宣言の id]}]
    (種類が generated のものは除く), "skipped_generated": [パス], "problems": [{"path", "message"}] (そろえられないパス)}。
    """
    declared = {f["path"] for f in latest_declaration["files"]}
    undeclared, skipped, problems = [], [], []
    for raw in changed_paths:
        path, problem = normalize_path(raw)
        if problem:
            problems.append({"path": raw, "message": problem})
            continue
        if path in declared:
            continue
        kind = filekinds.classify(path, rules, default_table)
        if kind["kind"] == "generated":
            skipped.append(path)
            continue
        declared_by = [o.get("id") for o in others if o["repo"].lower() == repo.lower() and any(f["path"] == path for f in o["declaration"]["files"])]
        undeclared.append({"path": path, "kind": kind["kind"], "declared_by": declared_by})
    return {"undeclared": undeclared, "skipped_generated": skipped, "problems": problems}
