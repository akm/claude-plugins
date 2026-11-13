"""Issue の本文の読み書き。マークで囲んだ範囲と見出しの節の取り出し・範囲の書き換え・本文のハッシュ値 (計画の KTD7・KTD8)。

マークは HTML のコメントで、範囲の名前ごとに開始と終了の 2 行を書く。

    <!-- issue-practice:<名前> -->
    ...
    <!-- /issue-practice:<名前> -->

範囲の名前は定数 REGIONS にあるものだけ (文書 `issue-practice/references/closing-conditions.md` の節「節の場所」と一致させる)。
マークは、その行にマークだけがある行として書く。コードブロック (``` か ~~~ で囲んだ部分) の中のマークと見出しは数えない。
本文に書式の例を書いたときに、例を範囲や節と取り違えないため。

関数は、解析できた値の辞書か、理由の文字列を持つ辞書 (`{"error": <理由>}`) を返す。例外は送出しない。
"""

import hashlib
import re

from issue_practice import gh

REGIONS = ("closing-conditions", "merge-plan")

_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6}) +(.*?)\s*#*\s*$")


def start_mark(name):
    return f"<!-- issue-practice:{name} -->"


def end_mark(name):
    return f"<!-- /issue-practice:{name} -->"


def body_sha256(body):
    """本文のハッシュ値 (UTF-8 の SHA-256 の 16 進数)。本文は gh が返したまま使い、改行や空白をそろえない。"""
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def split_lines(body):
    """本文を行に分ける。改行は `\\n` で分け、行末の `\\r` は残す (書き戻したときに元の本文に戻るように)。"""
    return (body or "").split("\n")


def outside_fences(lines):
    """コードブロックの外にある行の番号 (0 から数える) の集合。"""
    result = set()
    fence = None
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
                continue
            if marker == fence:
                fence = None
                continue
        if fence is None:
            result.add(i)
    return result


def heading(line):
    """見出しの行なら (レベル, 文字列)、そうでなければ None。"""
    m = _HEADING_RE.match(line.rstrip("\r"))
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def _strip_blank(lines):
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def find_region(body, name):
    """マークで囲んだ範囲を探す。

    返り値は {"name", "start_line", "end_line", "content", "lines"} か {"error"}。行番号は本文の 1 行目を 1 とし、
    start_line と end_line はマークの行。content は範囲の中の行 (前後の空行を除く) をつないだ文字列、lines は範囲の中の行の
    配列 (行番号と行の組。前後の空行も含む)。
    """
    if name not in REGIONS:
        return {"error": f"知らない範囲の名前: {name!r} (使える名前: {', '.join(REGIONS)})"}
    lines = split_lines(body)
    visible = outside_fences(lines)
    starts = [i for i in sorted(visible) if lines[i].strip() == start_mark(name)]
    ends = [i for i in sorted(visible) if lines[i].strip() == end_mark(name)]
    if not starts and not ends:
        return {"error": f"範囲 {name} のマークが無い"}
    if len(starts) > 1:
        return {"error": f"範囲 {name} の開始のマークが複数ある (行 {', '.join(str(i + 1) for i in starts)})"}
    if len(ends) > 1:
        return {"error": f"範囲 {name} の終了のマークが複数ある (行 {', '.join(str(i + 1) for i in ends)})"}
    if not starts:
        return {"error": f"範囲 {name} の開始のマークが無い (終了のマークは行 {ends[0] + 1})"}
    if not ends:
        return {"error": f"範囲 {name} が閉じていない (開始のマークは行 {starts[0] + 1})"}
    start, end = starts[0], ends[0]
    if end < start:
        return {"error": f"範囲 {name} の終了のマーク (行 {end + 1}) が開始のマーク (行 {start + 1}) より前にある"}
    inner = [(i + 1, lines[i].rstrip("\r")) for i in range(start + 1, end)]
    content = "\n".join(_strip_blank([text for _, text in inner]))
    return {"name": name, "start_line": start + 1, "end_line": end + 1, "content": content, "lines": inner}


def has_region_mark(body, name):
    """範囲の開始か終了のマークが、コードブロックの外に 1 つでもあるか。"""
    lines = split_lines(body)
    marks = (start_mark(name), end_mark(name))
    return any(lines[i].strip() in marks for i in outside_fences(lines))


def replace_region(body, name, content):
    """マークで囲んだ範囲の中を content に書き換えた本文を返す。範囲の外は 1 文字も変えない。

    範囲の中は「開始のマーク・空行・content・空行・終了のマーク」の形にする。返り値は {"body"} か {"error"}。
    """
    found = find_region(body, name)
    if "error" in found:
        return found
    lines = split_lines(body)
    start, end = found["start_line"] - 1, found["end_line"] - 1
    inner = (content or "").strip("\n").split("\n")
    new_lines = lines[:start + 1] + [""] + inner + [""] + lines[end:]
    return {"body": "\n".join(new_lines)}


def find_section(body, title, level=2):
    """見出し (レベル level、文字列 title) の節を探す。節は、次の同じレベル以上の見出しの手前まで。

    返り値は {"title", "heading_line", "end_line", "content", "lines"} か {"error"}。end_line は節の最後の行。
    """
    lines = split_lines(body)
    visible = outside_fences(lines)
    found = [i for i in sorted(visible) if heading(lines[i]) == (level, title)]
    if not found:
        return {"error": f"節「{title}」(見出しのレベル {level}) が無い"}
    if len(found) > 1:
        return {"error": f"節「{title}」が複数ある (行 {', '.join(str(i + 1) for i in found)})"}
    start = found[0]
    end = len(lines)
    for i in sorted(visible):
        if i <= start:
            continue
        h = heading(lines[i])
        if h and h[0] <= level:
            end = i
            break
    inner = [(i + 1, lines[i].rstrip("\r")) for i in range(start + 1, end)]
    content = "\n".join(_strip_blank([text for _, text in inner]))
    return {"title": title, "heading_line": start + 1, "end_line": end, "content": content, "lines": inner}


def write_body(url, body):
    """Issue の本文を body に書き換える (`gh issue edit <URL> --body-file -`)。返り値は gh.run の結果。

    書く前に本文が読んだときから変わっていないかを確認するのは、呼び出し元 (計画の KTD7)。
    """
    return gh.run(["issue", "edit", url, "--body-file", "-"], mutation=True, stdin=body)


ISSUE_FIELDS = "number,url,state,title,body,updatedAt"


def fetch_issue(ref):
    """Issue を gh で読む。ref は refs.parse_ref の結果で、key が決まっているもの。

    返り値は ({"number", "url", "state", "title", "body", "updated_at", "sha256"}, None) か、(None, 失敗した gh の結果)。
    """
    result = gh.run(["issue", "view", str(ref["number"]), "-R", f"{ref['owner']}/{ref['repo']}", "--json", ISSUE_FIELDS],
                    expect_json=True)
    if gh.failed(result):
        return None, result
    data = result["json"]
    if not isinstance(data, dict) or not isinstance(data.get("body"), str):
        return None, {**result, "json_error": "応答に本文 (body) が無い"}
    issue = {"number": data.get("number"), "url": data.get("url"), "state": data.get("state"), "title": data.get("title"),
             "body": data["body"], "updated_at": data.get("updatedAt"), "sha256": body_sha256(data["body"])}
    return issue, None
