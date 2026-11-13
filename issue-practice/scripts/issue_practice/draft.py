"""計画案のファイルの共通の部分。保存先の確認・ファイル名・先頭の書式の解析・本文の照合 (計画の KTD7・KTD13・KTD14)。

書式の SSOT は、文書 `issue-practice/references/draft-plan.md` とこのモジュール。計画案の中身 (スキルごとの節) は扱わない。
関数は、解析できた値の辞書か、理由を持つ辞書を返す。例外は送出しない (ファイルを開けないときの OSError を除く)。
"""

import os
import re
import subprocess

from issue_practice import bodies, refs

DRAFT_DIR = "tmp/issue-practice"

# プラグイン issue-practice のスキルの名前 (計画の KD3)。ファイル名の <スキル名> はこのどれか
SKILLS = (
    "new-issue",
    "managing-issue-plan",
    "managing-issue-run",
    "managing-issue-close",
    "working-issue",
    "release-plan",
    "release-issue-plan",
    "release-run",
    "release-close",
)

TARGET_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FILENAME_RE = re.compile(r"^(?P<date>[0-9]{8})-(?P<time>[0-9]{4})-(?P<rest>[a-z0-9][a-z0-9-]*)\.md$")
TITLE_RE = re.compile(r"^# 計画案: (?P<title>\S.*)$")
SOURCES_HEADING = "元にした Issue"
SOURCE_RE = re.compile(r"^- (?P<url>\S+) 本文の SHA-256: (?P<sha256>[0-9a-f]{64})$")
NONE_ITEM = "- なし"

# git を実行するときに消す環境変数。--root で渡したリポジトリだけを基準にするため (hook の中などで GIT_DIR が設定されていても)
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX")


def parse_file_name(name):
    """ファイル名を解析する。返り値は {"date", "time", "skill", "target"} か {"error"}。"""
    m = FILENAME_RE.match(name or "")
    if not m:
        return {"error": f"ファイル名が <YYYYMMDD>-<hhmm>-<スキル名>-<対象>.md の形ではない: {name!r}"}
    rest = m.group("rest")
    for skill in sorted(SKILLS, key=len, reverse=True):
        if rest.startswith(skill + "-") and TARGET_RE.match(rest[len(skill) + 1:]):
            return {"date": m.group("date"), "time": m.group("time"), "skill": skill, "target": rest[len(skill) + 1:]}
    return {"error": f"ファイル名の <スキル名>-<対象> が、スキルの名前と対象の組になっていない: {name!r}"}


def file_name(skill, target, stamp):
    """ファイル名を作る。stamp は `YYYYMMDD-hhmm`。返り値は {"file_name"} か {"error"}。"""
    if skill not in SKILLS:
        return {"error": f"知らないスキルの名前: {skill!r}"}
    if not TARGET_RE.match(target or ""):
        return {"error": f"対象は英小文字・数字・ハイフンで書く: {target!r}"}
    name = f"{stamp}-{skill}-{target}.md"
    parsed = parse_file_name(name)
    if "error" in parsed:
        return parsed
    return {"file_name": name}


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_KEYS}
    try:
        completed = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=env,
                                   stdin=subprocess.DEVNULL)
    except OSError as e:
        return {"args": ["git", "-C", root, *args], "exit_code": None, "stdout": "", "stderr": f"git を起動できない: {e}"}
    return {"args": ["git", "-C", root, *args], "exit_code": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr}


def check_dir(root):
    """計画案のディレクトリ (root の tmp/issue-practice/) が git に無視されているかを確認する。

    root は、リポジトリのルートの絶対パス。返り値は次のどれか。
      {"status": "ok", "dir": <絶対パス>}
      {"status": "unsatisfied", "errors": [<理由>]}   root がルートでない・無視されていない
      {"status": "git_failed", "git_error": {...}}     git が失敗した (リポジトリでないなど)
    """
    if not root or not os.path.isabs(root):
        return {"status": "unsatisfied", "errors": [f"--root はリポジトリのルートの絶対パスで渡す: {root!r}"]}
    top = _git(root, "rev-parse", "--show-toplevel")
    if top["exit_code"] != 0:
        return {"status": "git_failed", "git_error": top}
    if os.path.realpath(top["stdout"].strip()) != os.path.realpath(root):
        return {"status": "unsatisfied",
                "errors": [f"--root がリポジトリのルートではない (ルートは {top['stdout'].strip()})"]}
    ignored = _git(root, "check-ignore", "-q", "--", DRAFT_DIR + "/")
    if ignored["exit_code"] == 1:
        return {"status": "unsatisfied",
                "errors": [f"ディレクトリ {DRAFT_DIR}/ が git に無視されていない。.gitignore に tmp/ を足してコミットしてから、"
                           "もう一度実行する (スキルは .gitignore を変えない)"]}
    if ignored["exit_code"] != 0:
        return {"status": "git_failed", "git_error": ignored}
    return {"status": "ok", "dir": os.path.join(root, DRAFT_DIR)}


def new_path(root, skill, target, stamp):
    """新しい計画案のパスを決め、ディレクトリを作る。既にあるファイルの名前は返さない。

    返り値は check_dir と同じ形で、ok のときは {"status": "ok", "path", "relative", "file_name"}。
    """
    name = file_name(skill, target, stamp)
    if "error" in name:
        return {"status": "unsatisfied", "errors": [name["error"]]}
    checked = check_dir(root)
    if checked["status"] != "ok":
        return checked
    path = os.path.join(checked["dir"], name["file_name"])
    if os.path.lexists(path):
        return {"status": "unsatisfied",
                "errors": [f"計画案のファイルが既にある (上書きしない): {path}。時刻か対象を変えて作り直す"]}
    os.makedirs(checked["dir"], exist_ok=True)
    return {"status": "ok", "path": path, "relative": f"{DRAFT_DIR}/{name['file_name']}", "file_name": name["file_name"]}


def parse(text, name):
    """計画案の先頭の書式を解析する。name はファイル名 (ディレクトリを含まない)。

    返り値は {"file_name", "title", "skill", "target", "created", "sources", "sections", "errors"}。errors は
    {"line" (1 から数える行番号。行に結び付かない誤りは null), "message"} の配列で、空なら形どおり。
    sources は {"issue" (owner/repo#番号), "url", "sha256", "line"} の配列、sections は節「元にした Issue」の後の
    レベル 2 の節 {"title", "line"} の配列。
    """
    errors = []
    result = {"file_name": name, "title": None, "skill": None, "target": None, "created": None, "sources": [],
              "sections": [], "errors": errors}
    parsed_name = parse_file_name(name)
    if "error" in parsed_name:
        errors.append({"line": None, "message": parsed_name["error"]})
    else:
        result.update(skill=parsed_name["skill"], target=parsed_name["target"],
                      created=f"{parsed_name['date'][:4]}-{parsed_name['date'][4:6]}-{parsed_name['date'][6:]} "
                              f"{parsed_name['time'][:2]}:{parsed_name['time'][2:]}")
    lines = bodies.split_lines(text)
    visible = bodies.outside_fences(lines)
    m = TITLE_RE.match(lines[0].rstrip("\r")) if lines else None
    if not m:
        errors.append({"line": 1, "message": "1 行目が「# 計画案: <題>」ではない"})
    else:
        result["title"] = m.group("title").strip()
    level2 = [(i, bodies.heading(lines[i])[1]) for i in sorted(visible)
              if bodies.heading(lines[i]) and bodies.heading(lines[i])[0] == 2]
    source_headings = [i for i, title in level2 if title == SOURCES_HEADING]
    if not source_headings:
        errors.append({"line": None, "message": f"節「{SOURCES_HEADING}」(## {SOURCES_HEADING}) が無い"})
        return result
    if len(source_headings) > 1:
        errors.append({"line": source_headings[1] + 1, "message": f"節「{SOURCES_HEADING}」が複数ある"})
    start = source_headings[0]
    if level2[0][0] != start:
        errors.append({"line": start + 1, "message": f"節「{SOURCES_HEADING}」が最初のレベル 2 の見出しではない"})
    following = [i for i, _ in level2 if i > start]
    end = following[0] if following else len(lines)
    result["sections"] = [{"title": title, "line": i + 1} for i, title in level2 if i > start]
    items, has_none, seen = [], False, {}
    for i in range(start + 1, end):
        line = lines[i].rstrip("\r")
        if not line.strip():
            continue
        if line == NONE_ITEM:
            has_none = True
            items.append(i)
            continue
        sm = SOURCE_RE.match(line)
        if not sm:
            errors.append({"line": i + 1, "message": "「- <Issue の URL> 本文の SHA-256: <64 桁の 16 進数>」か「- なし」ではない"})
            continue
        ref = refs.parse_ref(sm.group("url"))
        if "error" in ref or not sm.group("url").startswith("https://"):
            errors.append({"line": i + 1, "message": f"Issue か PR の URL ではない: {sm.group('url')}"})
            continue
        key = ref["key"].lower()
        if key in seen:
            errors.append({"line": i + 1, "message": f"同じ Issue が 2 回ある (行 {seen[key]})"})
            continue
        seen[key] = i + 1
        items.append(i)
        result["sources"].append({"issue": ref["key"], "url": ref["url"], "sha256": sm.group("sha256"), "line": i + 1})
    if not items:
        errors.append({"line": start + 1, "message": f"節「{SOURCES_HEADING}」に項目が無い (無ければ「- なし」と書く)"})
    elif has_none and result["sources"]:
        errors.append({"line": start + 1, "message": "「- なし」と Issue の項目が両方ある"})
    return result


def read(path):
    """計画案のファイルを読んで parse する。ファイルを開けなければ OSError を送出する。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return parse(text, os.path.basename(path))


def compare(sources):
    """節「元にした Issue」の Issue の本文を再度読み込み、ハッシュ値を比べる。

    返り値は {"results": [{"issue", "url", "sha256_draft", "sha256_now", "changed", "updated_at"}], "gh_error"}。
    gh が失敗したら、そこで止めて gh_error に失敗した gh の結果を入れる (残りは読まない)。
    """
    results = []
    for source in sources:
        ref = refs.parse_ref(source["url"])
        issue, failure = bodies.fetch_issue(ref)
        if failure:
            return {"results": results, "gh_error": failure}
        results.append({"issue": source["issue"], "url": source["url"], "sha256_draft": source["sha256"],
                        "sha256_now": issue["sha256"], "changed": issue["sha256"] != source["sha256"],
                        "updated_at": issue["updated_at"]})
    return {"results": results, "gh_error": None}
