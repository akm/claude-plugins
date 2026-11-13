"""PR マージ計画の表の解析と、表から mermaid の gitGraph の図を作ること (計画の KTD8・R31〜R34・U3)。

書式の SSOT は、文書 `issue-practice/skills/managing-issue-plan/references/merge-plan.md` とこのモジュールの定数。
テスト (ファイル `issue-practice/tests/test_mergeplan.py`) が、文書の設定の項目と表の見出しの行が定数と一致することを確認する。

表が SSOT で、図は表から作る。管理 Issue の本文では、マーク merge-plan で囲んだ範囲に、設定の箇条書き・表・図をこの順に書く。
計画案の表 (allow_keys=True) では、作業 Issue を計画案の節「作る Issue」のキーで書け、列「ブランチ」に `<番号>` を書ける。
作業 Issue を作った後に、関数 resolve でキーを番号に置き換える。

関数は、解析できた値の辞書か、理由を持つ辞書を返す。例外は送出しない。
"""

import copy
import re

from issue_practice import bodies, refs

REGION = "merge-plan"
SETTINGS = ("ブランチの構成", "PR をマージする人", "管理 Issue のブランチ", "管理 Issue のブランチのマージ先", "管理 Issue の PR")
HEADER = ("順", "作業 Issue", "ブランチ", "マージ先", "先にマージが要る作業 Issue", "PR")
CONFIGS = ("1", "2", "3")
MERGERS = ("利用者", "管理セッション")
NONE_VALUE = "なし"
NUMBER_PLACEHOLDER = "<番号>"
DRAFT_COMMIT_ID = "draft PR"
DRAFT_PR_NOTICE = ("> [!NOTE]\n> この PR は、作業 Issue の PR をまとめるための PR です。作業 Issue の PR がすべてマージされるまで、"
                   "draft のままにします。管理 Issue: {url}")

_SETTING_RE = re.compile(r"^- (?P<name>[^:]+): (?P<value>.*)$")
_CONFIG_RE = re.compile(r"^(?P<config>[0-9]+)(?: \(.*\))?$")
_ROW_RE = re.compile(r"^\s*\|(?P<cells>.*)\|\s*$")
_DELIMITER_RE = re.compile(r"^\s*:?-{3,}:?\s*$")
_ORDER_RE = re.compile(r"^[1-9][0-9]*$")
_WORK_RE = re.compile(r"^#(?P<number>[1-9][0-9]*)(?:\s+(?P<description>\S.*))?$")
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\s+(?P<description>\S.*))?$")
_REF_RE = re.compile(r"^#(?P<number>[1-9][0-9]*)$")
_DEP_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _cells(line):
    m = _ROW_RE.match(line.rstrip("\r"))
    if not m:
        return None
    return [cell.strip() for cell in m.group("cells").split("|")]


def _branch_name(cell, allow_placeholder=False):
    """バッククォートを外したブランチの名前か、None (名前の形ではない)。"""
    name = cell.strip()
    if len(name) >= 2 and name.startswith("`") and name.endswith("`"):
        name = name[1:-1].strip()
    checked = name.replace(NUMBER_PLACEHOLDER, "0") if allow_placeholder else name
    if not _BRANCH_RE.match(checked) or ".." in checked:
        return None
    return name


def _identity(item):
    return ("number", item["number"]) if item["number"] is not None else ("key", item["key"])


def _label(item):
    return f"#{item['number']}" if item["number"] is not None else item["key"]


def _parse_settings(lines, offset, errors):
    """設定の箇条書きを読む。返り値は {"config", "merger", "managing_branch", "managing_base", "managing_pr"}。"""
    values = {}
    for index, line in lines:
        m = _SETTING_RE.match(line.rstrip("\r"))
        if not m or m.group("name") not in SETTINGS:
            continue
        name = m.group("name")
        if name in values:
            errors.append({"line": index + offset, "message": f"設定「{name}」が 2 回ある"})
            continue
        values[name] = (index + offset, m.group("value").strip())
    settings = {"config": None, "merger": None, "managing_branch": None, "managing_base": None, "managing_pr": None}
    line_of = {name: line for name, (line, _) in values.items()}
    if "ブランチの構成" not in values:
        errors.append({"line": None, "message": "設定「ブランチの構成」が無い"})
    else:
        m = _CONFIG_RE.match(values["ブランチの構成"][1])
        if not m or m.group("config") not in CONFIGS:
            errors.append({"line": line_of["ブランチの構成"],
                           "message": f"ブランチの構成は {'・'.join(CONFIGS)} のどれか: {values['ブランチの構成'][1]!r}"})
        else:
            settings["config"] = m.group("config")
    if "PR をマージする人" not in values:
        errors.append({"line": None, "message": "設定「PR をマージする人」が無い"})
    elif values["PR をマージする人"][1] not in MERGERS:
        errors.append({"line": line_of["PR をマージする人"],
                       "message": f"PR をマージする人は {'・'.join(MERGERS)} のどちらか: {values['PR をマージする人'][1]!r}"})
    else:
        settings["merger"] = values["PR をマージする人"][1]
    managing = {key: values[name][1] for key, name in (("managing_branch", "管理 Issue のブランチ"),
                                                       ("managing_base", "管理 Issue のブランチのマージ先"),
                                                       ("managing_pr", "管理 Issue の PR"))
                if name in values and values[name][1] != NONE_VALUE}
    if settings["config"] == "1":
        for key, name in (("managing_branch", "管理 Issue のブランチ"), ("managing_base", "管理 Issue のブランチのマージ先"),
                          ("managing_pr", "管理 Issue の PR")):
            if key in managing:
                errors.append({"line": line_of[name], "message": f"ブランチの構成 1 では、設定「{name}」は {NONE_VALUE}"})
    elif settings["config"] in ("2", "3"):
        for key, name in (("managing_branch", "管理 Issue のブランチ"), ("managing_base", "管理 Issue のブランチのマージ先")):
            if key not in managing:
                errors.append({"line": line_of.get(name), "message": f"ブランチの構成 {settings['config']} では、設定「{name}」が要る"})
                continue
            branch = _branch_name(managing[key])
            if branch is None:
                errors.append({"line": line_of[name], "message": f"設定「{name}」がブランチの名前ではない: {managing[key]!r}"})
            else:
                settings[key] = branch
        if "managing_pr" in managing:
            ref = refs.parse_ref(managing["managing_pr"])
            if "error" in ref or ref["kind"] == "issue":
                errors.append({"line": line_of["管理 Issue の PR"],
                               "message": f"設定「管理 Issue の PR」が PR の URL ではない: {managing['managing_pr']!r}"})
            else:
                settings["managing_pr"] = managing["managing_pr"]
    return settings


def _parse_work(cell, allow_keys):
    m = _WORK_RE.match(cell)
    if m:
        return {"number": int(m.group("number")), "key": None, "description": m.group("description")}
    if allow_keys:
        m = _KEY_RE.match(cell)
        if m:
            return {"number": None, "key": m.group("key"), "description": m.group("description")}
    return None


def _parse_requires(cell, allow_keys):
    if cell == NONE_VALUE:
        return []
    items = []
    for text in [t.strip() for t in cell.split(",")]:
        m = _REF_RE.match(text)
        if m:
            items.append({"key": None, "number": int(m.group("number"))})
        elif allow_keys and _DEP_KEY_RE.match(text):
            items.append({"key": text, "number": None})
        else:
            return None
    return items


def parse(text, allow_keys=False, offset=0):
    """PR マージ計画 (設定の箇条書きと表) を読む。text はマークの中身か、計画案の節「PR マージ計画」の中身。

    allow_keys が真なら計画案の表として読み、作業 Issue をキーで書くことと、列「ブランチ」の `<番号>` を許す。
    offset は行番号に足す数 (本文の中の範囲を読むときに、本文の行番号で誤りを返すため)。
    返り値は {"settings", "prefix" (表の前の行の配列), "rows", "errors"}。rows の要素は {"order", "work" ({"number", "key",
    "description"}), "branch", "base", "requires" ([{"number", "key"}]), "pr" (列の文字列か None), "line"}。
    errors は {"line", "message"} の配列。
    """
    lines = bodies.split_lines(text)
    visible = bodies.outside_fences(lines)
    errors = []
    table_indices = [i for i in sorted(visible) if _cells(lines[i]) is not None]
    first_table = table_indices[0] if table_indices else len(lines)
    prefix_pairs = [(i + 1, lines[i].rstrip("\r")) for i in range(first_table) if i in visible]
    settings = _parse_settings(prefix_pairs, offset, errors)
    prefix = [line for _, line in prefix_pairs]
    while prefix and not prefix[0].strip():
        prefix.pop(0)
    while prefix and not prefix[-1].strip():
        prefix.pop()
    result = {"settings": settings, "prefix": prefix, "rows": [], "errors": errors}
    if not table_indices:
        errors.append({"line": None, "message": "PR マージ計画の表が無い"})
        return result
    groups, previous = [], None
    for i in table_indices:
        if previous is None or i != previous + 1:
            groups.append([])
        groups[-1].append(i)
        previous = i
    if len(groups) > 1:
        errors.append({"line": groups[1][0] + 1 + offset, "message": "PR マージ計画の表が複数ある"})
        return result
    table = groups[0]
    header_line = table[0] + 1 + offset
    if tuple(_cells(lines[table[0]])) != HEADER:
        errors.append({"line": header_line, "message": f"表の見出しの行が「| {' | '.join(HEADER)} |」ではない"})
        return result
    if len(table) < 2 or len(_cells(lines[table[1]])) != len(HEADER) \
            or not all(_DELIMITER_RE.match(c) for c in _cells(lines[table[1]])):
        errors.append({"line": header_line + 1, "message": "表の見出しの行の次が、区切りの行ではない"})
        return result
    rows, seen_work, seen_branch = [], {}, {}
    for i in table[2:]:
        number = i + 1 + offset

        def error(message, line=number):
            errors.append({"line": line, "message": message})

        cells = _cells(lines[i])
        if len(cells) != len(HEADER):
            error(f"列の数が {len(HEADER)} ではない")
            continue
        order, work_cell, branch_cell, base_cell, requires_cell, pr_cell = cells
        if not _ORDER_RE.match(order):
            error(f"列「順」が 1 以上の整数ではない: {order!r}")
            continue
        work = _parse_work(work_cell, allow_keys)
        if work is None:
            error(f"列「作業 Issue」が #<番号> の形ではない: {work_cell!r}" if not allow_keys else
                  f"列「作業 Issue」が #<番号> か、節「作る Issue」のキーではない: {work_cell!r}")
            continue
        branch = _branch_name(branch_cell, allow_placeholder=allow_keys)
        if branch is None:
            error(f"列「ブランチ」がブランチの名前ではない: {branch_cell!r}")
            continue
        base = _branch_name(base_cell)
        if base is None:
            error(f"列「マージ先」がブランチの名前ではない: {base_cell!r}")
            continue
        requires = _parse_requires(requires_cell, allow_keys)
        if requires is None:
            error(f"列「先にマージが要る作業 Issue」が {NONE_VALUE} か、#<番号> を , で区切ったものではない: {requires_cell!r}")
            continue
        if pr_cell:
            ref = refs.parse_ref(pr_cell)
            if "error" in ref or ref["kind"] == "issue" or not (pr_cell.startswith("#") or pr_cell.startswith("https://")):
                error(f"列「PR」が PR の URL か #<番号> ではない: {pr_cell!r}")
                continue
        ident = _identity(work)
        if ident in seen_work:
            error(f"作業 Issue {_label(work)} が 2 回ある (行 {seen_work[ident]})")
            continue
        if branch in seen_branch:
            error(f"ブランチ {branch} が 2 回ある (行 {seen_branch[branch]})")
            continue
        for req in requires:
            if _identity(req) not in seen_work:
                error(f"先にマージが要る作業 Issue {_label(req)} が、この行より前の行に無い")
        seen_work[ident] = number
        seen_branch[branch] = number
        rows.append({"order": int(order), "work": work, "branch": branch, "base": base, "requires": requires,
                     "pr": pr_cell or None, "line": number})
    result["rows"] = rows
    if not rows and not errors:
        errors.append({"line": header_line, "message": "表に行が無い"})
    for expected, row in enumerate(rows, start=1):
        if row["order"] != expected:
            errors.append({"line": row["line"], "message": f"列「順」が 1 から始まる連番になっていない ({expected} のところが {row['order']})"})
            break
    config = settings["config"]
    if rows and config == "1":
        bases = sorted({row["base"] for row in rows})
        if len(bases) > 1:
            errors.append({"line": header_line, "message": f"ブランチの構成 1 では、列「マージ先」をどの行も同じブランチにする ({', '.join(bases)})"})
    elif rows and config in ("2", "3") and settings["managing_branch"]:
        for row in rows:
            if row["base"] != settings["managing_branch"]:
                errors.append({"line": row["line"], "message": f"ブランチの構成 {config} では、列「マージ先」は管理 Issue のブランチ "
                                                               f"{settings['managing_branch']}"})
    errors.sort(key=lambda e: (e["line"] is not None, e["line"] or 0))
    return result


def resolve(plan, numbers):
    """計画案の表のキーを、作った Issue の番号に置き換える。numbers はキーから番号への辞書。

    列「ブランチ」の `<番号>` も、その行の作業 Issue の番号に置き換える。返り値は plan と同じ形の辞書 (errors に、番号の
    分からないキーを足す)。
    """
    resolved = copy.deepcopy(plan)
    errors = resolved["errors"]

    def number_of(item, line):
        if item["number"] is not None:
            return item["number"]
        if item["key"] in numbers:
            return numbers[item["key"]]
        errors.append({"line": line, "message": f"キー {item['key']} の Issue が無い (計画案から作った Issue が見つからない)"})
        return None

    def resolved_item(item, line):
        number = number_of(item, line)
        if number is None:
            return item
        return {**item, "number": number, "key": None}

    for row in resolved["rows"]:
        row["work"] = resolved_item(row["work"], row["line"])
        if row["work"]["number"] is not None:
            row["branch"] = row["branch"].replace(NUMBER_PLACEHOLDER, str(row["work"]["number"]))
        row["requires"] = [resolved_item(req, row["line"]) for req in row["requires"]]
    return resolved


def graph(plan):
    """表から mermaid の gitGraph を作る。plan は誤りの無いもの。返り値は図の文字列 (最後に改行を付ける)。"""
    settings, rows = plan["settings"], plan["rows"]
    out = ["gitGraph"]

    def emit(line):
        out.append("  " + line)

    if settings["config"] in ("2", "3"):
        default, target = settings["managing_base"], settings["managing_branch"]
        emit(f'commit id: "{default}"')
        emit(f"branch {target}")
        if settings["config"] == "2":
            emit(f'commit id: "{DRAFT_COMMIT_ID}"')
    else:
        default = target = rows[0]["base"]
        emit(f'commit id: "{default}"')
    created, merged = set(), set()

    def create(row):
        emit(f"branch {row['branch']}")
        emit(f'commit id: "{_label(row["work"]).lstrip("#")}"')
        emit(f"checkout {target}")
        created.add(_identity(row["work"]))

    for row in rows:
        if not row["requires"]:
            create(row)
    for row in rows:
        if _identity(row["work"]) not in created:
            create(row)
        emit(f"merge {row['branch']}")
        merged.add(_identity(row["work"]))
        for other in rows:
            if _identity(other["work"]) not in created and all(_identity(r) in merged for r in other["requires"]):
                create(other)
    if settings["config"] in ("2", "3"):
        emit(f"checkout {default}")
        emit(f"merge {target}")
    return "\n".join(out) + "\n"


def _row_line(row):
    work = _label(row["work"]) + (f" {row['work']['description']}" if row["work"]["description"] else "")
    requires = ", ".join(_label(r) for r in row["requires"]) or NONE_VALUE
    cells = [str(row["order"]), work, f"`{row['branch']}`", row["base"], requires, row["pr"] or ""]
    return "|" + "|".join(f" {c} " if c else " " for c in cells) + "|"


def render(plan):
    """マークの中身 (設定の箇条書き・表・図) を作る。設定の箇条書きは、読んだときの表の前の行をそのまま使う。"""
    table = ["| " + " | ".join(HEADER) + " |", "|" + "|".join([" --- "] * len(HEADER)) + "|"]
    table += [_row_line(row) for row in plan["rows"]]
    parts = []
    if plan["prefix"]:
        parts.append("\n".join(plan["prefix"]))
    parts.append("\n".join(table))
    parts.append("```mermaid\n" + graph(plan) + "```")
    return "\n\n".join(parts)


def extract_graph(text):
    """中身の最初の mermaid のコードブロックの中身 (最後に改行を付ける) か、None。"""
    lines = bodies.split_lines(text)
    for i, line in enumerate(lines):
        if line.rstrip("\r").strip() == "```mermaid":
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip("\r").strip() == "```":
                    return "\n".join(line.rstrip("\r") for line in lines[i + 1:j]) + "\n"
            return None
    return None


def set_pr(plan, number, pr):
    """作業 Issue (番号) の行で、列「PR」を pr にした plan を返す。返り値は {"plan", "previous"} か {"error"}。"""
    ref = refs.parse_ref(pr)
    if "error" in ref or ref["kind"] != "pull":
        return {"error": f"PR の URL ではない: {pr!r}"}
    changed = copy.deepcopy(plan)
    for row in changed["rows"]:
        if row["work"]["number"] == number:
            previous = row["pr"]
            row["pr"] = pr
            return {"plan": changed, "previous": previous}
    return {"error": f"作業 Issue #{number} の行が、PR マージ計画の表に無い"}


def set_managing_pr(plan, pr):
    """設定「管理 Issue の PR」を pr にした plan を返す (構成 2・3 だけ)。設定の行が無ければ、表の前の行の最後に足す。

    返り値は {"plan", "previous"} か {"error"}。
    """
    ref = refs.parse_ref(pr)
    if "error" in ref or ref["kind"] != "pull":
        return {"error": f"PR の URL ではない: {pr!r}"}
    if plan["settings"]["config"] not in ("2", "3"):
        return {"error": "ブランチの構成 1 には、管理 Issue の PR が無い"}
    changed = copy.deepcopy(plan)
    line = f"- {SETTINGS[4]}: {pr}"
    for i, text in enumerate(changed["prefix"]):
        m = _SETTING_RE.match(text)
        if m and m.group("name") == SETTINGS[4]:
            changed["prefix"][i] = line
            break
    else:
        changed["prefix"].append(line)
    changed["settings"] = {**changed["settings"], "managing_pr": pr}
    return {"plan": changed, "previous": plan["settings"]["managing_pr"]}


def read_region(body):
    """本文のマーク merge-plan の範囲を読んで parse する。返り値は parse の結果に {"content"} を足したものか、{"error"}。"""
    region = bodies.find_region(body, REGION)
    if "error" in region:
        return region
    text = "\n".join(line for _, line in region["lines"])
    plan = parse(text, offset=region["start_line"])
    return {**plan, "content": region["content"]}


def pr_url(cell, owner, repo):
    """列「PR」の文字列を URL にする。#<番号> はリポジトリの PR の URL にする。"""
    if not cell:
        return None
    if cell.startswith("#"):
        return f"https://github.com/{owner}/{repo}/pull/{int(cell[1:])}"
    return refs.parse_ref(cell)["url"]


def rows_output(plan, owner, repo):
    """JSON に出す行の配列。作業 Issue と PR の URL を足す。"""
    out = []
    for row in plan["rows"]:
        work = row["work"]
        out.append({"order": row["order"],
                    "work": {"number": work["number"], "key": work["key"], "description": work["description"],
                             "url": f"https://github.com/{owner}/{repo}/issues/{work['number']}" if work["number"] else None},
                    "branch": row["branch"], "base": row["base"],
                    "requires": [r["number"] if r["number"] is not None else r["key"] for r in row["requires"]],
                    "pr": row["pr"], "pr_url": pr_url(row["pr"], owner, repo), "line": row["line"]})
    return out
