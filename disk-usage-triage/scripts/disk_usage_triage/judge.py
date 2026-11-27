"""保護の一覧・判定表と判定の順 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R12〜R15・R17・R19・KD8・
KTD5・KTD6・KTD16)。

項目のパスから、判定 (消してよい `deletable`・確認が要る `review`・残す `keep`) を決める。判定の順は計画の R13 で、保護の一覧・
記録の「残す」・使われているかどうかによる判定・記録のほかの判定・判定表の順に決める。記録の読み書きはモジュール records に
あり、このモジュールはディレクトリの記録を判定に使う。使われているかどうかによる判定 (asdf・Docker・git の worktree) は、
U10〜U12 で関数 judge の引数 usage に渡す。

- 保護の一覧 (R14) は、消す対象に選べない場所の一覧。プラグインを実行している Python の版・作業ディレクトリ・調べるディレクトリ
  のように実行の環境で決まる場所を含むので、判定表とは別にこのモジュールのコードに持つ (KTD5)。記録では除けない。
- 判定表は、ファイル `disk-usage-triage/scripts/disk_usage_triage/judgment-table.json`。様式の SSOT は、文書
  `disk-usage-triage/references/judgment-table.md`。行は、パターンに一致したディレクトリと、その下の項目に使い、項目とその親の
  ディレクトリに一致する行が複数あれば、階層の多いパターンの行を使う (KTD5)。
- 保護の一覧の項目を含む親のディレクトリは、まとめて消す対象に選べない (R12)。アプリの worktree を含むかは、項目を選ぶときに
  下の階層を探して決める (KTD5)。

パスは、シンボリックリンクを解決してから比べる。保護の一覧の場所と同じか・その下か・それを含むかは、パスの文字列に加えて、
ディレクトリの識別子 (デバイス番号と inode 番号) でも比べる。macOS の標準のファイルシステムは大文字と小文字を区別しないので、
大文字と小文字だけが違う書き方の場所も、保護の一覧の場所として扱うため。
"""

import datetime
import json
import os
import re
import sys
import time

JUDGMENTS = ("deletable", "review", "keep")  # 消してよい・確認が要る・残す
JUDGMENT_LABELS = {"deletable": "消してよい", "review": "確認が要る", "keep": "残す"}
DECIDER_LABELS = {"user": "利用者", "claude": "Claude"}
DEDICATED_LISTS = ("asdf", "docker", "worktree")  # 専用の一覧の種類 (KTD5)
TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "judgment-table.json")

_PRUNED = (".git", "node_modules")  # 選ぶときの探索で、下を探さないディレクトリの名前 (KTD5)

# 決まった場所の保護 (R14)。(種類, 範囲, ホームディレクトリからの相対パス, 説明)。範囲 subtree はその場所と下の階層を、self は
# その場所だけを保護する。1 つのパスが複数の場所に当たるときは、先に書いた場所の種類を示す (Docker.raw を Docker Desktop の
# ディレクトリより先に書く)。
_FIXED = (
    ("docker-raw", "self", ("Library", "Containers", "com.docker.docker", "Data", "vms", "0", "data", "Docker.raw"),
     "Docker Desktop のディスクイメージのファイル Docker.raw"),
    ("docker", "subtree", ("Library", "Containers", "com.docker.docker"), "Docker Desktop のディレクトリ"),
    ("claude-desktop", "subtree", ("Library", "Application Support", "Claude"), "Claude Desktop のディレクトリ"),
    ("claude", "subtree", (".claude",), "Claude Code のディレクトリ ~/.claude"),
    ("icloud", "subtree", ("Library", "Mobile Documents"), "iCloud Drive のディレクトリ"),
    ("cloud-storage", "subtree", ("Library", "CloudStorage"), "クラウドストレージのディレクトリ"),
)


def _identity(path):
    """デバイス番号と inode 番号の組。シンボリックリンクはたどる。無いか読めなければ None。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _chain(real):
    """実パス real と、その親のディレクトリをルートまでたどった配列。要素は (実パス, 識別子)。"""
    result = []
    current = real
    while True:
        result.append((current, _identity(current)))
        parent = os.path.dirname(current)
        if parent == current:
            return result
        current = parent


class _Location:
    """保護の一覧の場所 1 つ。path は示すためのパス (シンボリックリンクを解決しない)。"""

    def __init__(self, kind, scope, path, label):
        self.kind = kind
        self.scope = scope
        self.path = path
        self.label = label
        self.real = os.path.realpath(path)
        chain = _chain(self.real)
        self.identity = chain[0][1]
        self.ancestors = chain[1:]
        self.missing = not os.path.lexists(self.real)  # 無いと確認できた場所。読めずに確認できないときは False

    def same(self, entry):
        """entry ((実パス, 識別子)) が、この場所と同じディレクトリかファイルか。"""
        real, identity = entry
        return real == self.real or (identity is not None and identity == self.identity)

    def under(self, entry):
        """この場所が entry の下にあるか (entry がこの場所の親か)。"""
        real, identity = entry
        return any(real == r or (identity is not None and identity == i) for r, i in self.ancestors)

    def matches(self, chain):
        """chain (関数 _chain の返り値) のパスが、この場所の範囲 (scope) に入るか。"""
        if self.scope == "subtree":
            return any(self.same(entry) for entry in chain)
        return self.same(chain[0])

    def public(self):
        return {"kind": self.kind, "path": self.path, "label": self.label}


class Environment:
    """判定に使う実行の環境。関数 environment が作る。

    fixed は決まった場所と Python の版、runtime は調べるディレクトリ・ホームディレクトリ・作業ディレクトリとその親。
    """

    def __init__(self, home, cwd, fixed, runtime):
        self.home = home
        self.cwd = cwd
        self.fixed = tuple(fixed)
        self.runtime = tuple(runtime)
        self.locations = self.fixed + self.runtime


def _python_version_dir(executable, home):
    """プラグインを実行している Python が asdf の版なら、その版のディレクトリ。そうでなければ None (KTD10)。

    asdf のデータの場所は、環境変数 ASDF_DATA_DIR、無ければ ~/.asdf。Python の実行ファイルの実パスが
    `<データの場所>/installs/python/<版>/` の下にあるときの、その版。`installs/python` のディレクトリは、パスの文字列ではなく
    識別子で探す。ASDF_DATA_DIR の書き方が、大文字と小文字だけ実行ファイルのパスと違っても、同じ版を求めるため。
    """
    data_dir = os.environ.get("ASDF_DATA_DIR") or os.path.join(home, ".asdf")
    python_installs = _identity(os.path.join(data_dir, "installs", "python"))
    if python_installs is None:
        return None
    chain = _chain(os.path.realpath(executable))
    for (path, _), (_, parent_identity) in zip(chain, chain[1:]):
        if parent_identity == python_installs:
            return path
    return None


def environment(config):
    """実行の環境から、保護の一覧の場所を求める。config は設定 (モジュール config の load の返り値) で、scan_dirs を使う。

    ホームディレクトリは環境変数 HOME、作業ディレクトリは os.getcwd、Python の実行ファイルは sys.executable から求める。
    """
    home = os.path.abspath(os.path.expanduser("~"))
    cwd = os.getcwd()
    fixed = [_Location(kind, scope, os.path.join(home, *parts), label) for kind, scope, parts, label in _FIXED]
    python_dir = _python_version_dir(sys.executable, home)
    if python_dir is not None:
        fixed.append(_Location("python", "subtree", python_dir, "プラグインを実行している Python の asdf の版"))
    runtime = [_Location("scan-dir", "self", os.path.abspath(os.path.expanduser(value)), "調べるディレクトリ")
               for value in config["scan_dirs"]]
    runtime.append(_Location("home", "self", home, "ホームディレクトリ"))
    runtime.append(_Location("cwd", "self", cwd, "セッションの作業ディレクトリ"))
    current = cwd
    while os.path.dirname(current) != current:
        current = os.path.dirname(current)
        runtime.append(_Location("cwd-parent", "self", current, f"セッションの作業ディレクトリ ({cwd}) の親"))
    return Environment(home, cwd, fixed, runtime)


def locations(env):
    """保護の一覧の、決まった場所と実行の環境で決まる場所 (アプリの worktree を除く)。要素は {kind, path, label}。"""
    return [location.public() for location in env.locations]


def _is_worktrees_pair(claude, worktrees):
    """2 つの名前が `.claude` と `worktrees` か。大文字と小文字は区別しない。

    macOS の標準のファイルシステムでは、大文字と小文字だけが違う書き方 (`.Claude/worktrees`) も同じディレクトリを指すため。
    大文字と小文字を区別するファイルシステムでは、名前だけが違う別のディレクトリも保護するが、保護する項目が増えるだけで、
    消す対象に選べる項目は増えない。
    """
    return claude.casefold() == ".claude" and worktrees.casefold() == "worktrees"


def _app_worktree(real):
    """パスがアプリの worktree (`.claude/worktrees/` の下) か、その親の `.claude/worktrees` なら、保護の一覧の項目。"""
    parts = real.split(os.sep)
    for index in range(len(parts) - 1):
        if _is_worktrees_pair(parts[index], parts[index + 1]):
            if len(parts) == index + 2:
                return {"kind": "app-worktree-parent", "path": real, "label": "アプリの worktree の親のディレクトリ"}
            return {"kind": "app-worktree", "path": os.sep.join(parts[:index + 3]), "label": "アプリの worktree"}
    return None


def _check_absolute(path):
    if not os.path.isabs(path):
        raise ValueError(f"絶対パスでない: {path}")


def protection(path, env):
    """path が保護の一覧の項目なら {kind, path (保護の一覧の場所), label}。そうでなければ None。"""
    _check_absolute(path)
    real = os.path.realpath(path)
    chain = _chain(real)
    for location in env.fixed:
        if location.matches(chain):
            return location.public()
    worktree = _app_worktree(real)
    if worktree is not None:
        return worktree
    for location in env.runtime:
        if location.matches(chain):
            return location.public()
    return None


def _contained(path, env):
    """path の下にある保護の一覧の場所のうち、ほかの場所の下にないもの。無い場所 (~/Library/CloudStorage が無いマシンなど) は除く。"""
    entry = _chain(os.path.realpath(path))[0]
    inside = [location for location in env.locations if not location.missing and location.under(entry)]
    return [location for location in inside
            if not any(other is not location and location.under((other.real, other.identity)) for other in inside)]


def _search_below(path, timeout, clock):
    """path の下を探し、アプリの worktree のディレクトリ (`.claude/worktrees`)・読めなかったディレクトリ・時間の上限を超えたかを返す。

    `.git` と `node_modules` の下と、見つけた `.claude/worktrees` の下は探さない。シンボリックリンクはたどらない (KTD5)。
    """
    deadline = clock() + timeout
    found, unreadable = [], []
    for directory, names, _ in os.walk(path, onerror=lambda e: unreadable.append(e.filename)):
        if clock() > deadline:
            return found, unreadable, True
        names[:] = [name for name in names if name not in _PRUNED]
        for name in [name for name in names if _is_worktrees_pair(os.path.basename(directory), name)]:
            found.append(os.path.join(directory, name))
            names.remove(name)
    return found, unreadable, False


def selection_blockers(path, env, *, timeout, clock=time.monotonic):
    """path をまとめて消す対象に選べない理由の配列 (R12・KTD5)。選べるときは空の配列。

    要素は {kind, path, reason}。kind は、protected (path が保護の一覧の項目)・contains-protected (下に保護の一覧の場所がある)・
    app-worktree-below (下にアプリの worktree のディレクトリがある)・unreadable (下に読めないディレクトリがある)・timeout
    (下を探すのが時間の上限 timeout 秒を超えた) のどれか。前の種類の理由があれば、後の種類は調べない (下を探すのは時間がかかるため)。
    判定が「残す」の項目と、それを含む親は、記録を使う判定 (U4) の後に呼び出し元が扱う。
    """
    protected = protection(path, env)
    if protected is not None:
        return [{"kind": "protected", "path": path,
                 "reason": f"保護の一覧にある ({protected['label']}: {protected['path']})"}]
    contained = _contained(path, env)
    if contained:
        return [{"kind": "contains-protected", "path": location.path,
                 "reason": f"下に、保護の一覧の {location.label} ({location.path}) がある"} for location in contained]
    found, unreadable, timed_out = _search_below(path, timeout, clock)
    blockers = [{"kind": "app-worktree-below", "path": worktrees,
                 "reason": f"下に、アプリの worktree のディレクトリ ({worktrees}) がある"} for worktrees in found]
    blockers += [{"kind": "unreadable", "path": directory,
                  "reason": f"下に、読めないディレクトリ ({directory}) があり、アプリの worktree が無いことを確認できない"}
                 for directory in unreadable]
    if timed_out:
        blockers.append({"kind": "timeout", "path": path,
                         "reason": f"時間の上限 ({timeout} 秒) までに、下にアプリの worktree が無いことを確認し終えなかった"})
    return blockers


# --- 判定表 ---------------------------------------------------------------------------------------------------------

# 行のキー。文書 references/judgment-table.md の表と同じ順序
ROW_KEYS = ("pattern", "judgment", "reason", "impact", "command", "process_names", "dedicated_list", "sources")
REQUIRED_KEYS = ("pattern", "judgment", "reason", "impact", "command", "sources")
TABLE_DEDICATED_LISTS = ("asdf", "docker")  # 判定表に書ける専用の一覧の種類。worktree はコードで決める
COMMAND_TYPES = ("rm", "tool")
PLACEHOLDERS = ("{path}", "{name}")  # ツールのコマンドの引数と環境変数の値に書け、削除のシェルスクリプトを作るときに置き換える

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


def _pattern_parts(pattern):
    return pattern[2:].split("/")  # 先頭の "~/" を除く。様式は row_errors が検査する


def _text_error(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        return f"{key} が空でない文字列でない"
    return None


def _pattern_errors(pattern):
    if not isinstance(pattern, str) or not pattern.startswith("~/"):
        return ["pattern が ~/ で始まる文字列でない"]
    errors = []
    for part in _pattern_parts(pattern):
        if part in ("", ".", ".."):
            errors.append(f"pattern に空の名前・.・.. がある ({pattern})")
        elif "*" in part and part != "*":
            errors.append(f"pattern の * が名前の一部にある ({pattern}。* は 1 つの階層の名前全体にだけ書ける)")
    return errors


def _template_error(value, where):
    """ツールのコマンドの引数か環境変数の値 value の誤り。{ と } は、PLACEHOLDERS の文字列そのものにだけ書ける。"""
    if not isinstance(value, str) or value == "":
        return f"{where} が空でない文字列でない"
    if ("{" in value or "}" in value) and value not in PLACEHOLDERS:
        return f"{where} ({value}) の {{ }} が、{' か '.join(PLACEHOLDERS)} の要素全体でない"
    return None


def _command_errors(row):
    command = row.get("command")
    if row.get("judgment") == "keep":
        return [] if command is None else ["judgment が keep の行の command が null でない"]
    if not isinstance(command, dict):
        return ["command が JSON のオブジェクトでない (keep 以外の行は必須)"]
    kind = command.get("type")
    if kind == "rm":
        extra = [key for key in command if key != "type"]
        return [f"type が rm の command に、知らないキーがある: {'・'.join(extra)}"] if extra else []
    if kind != "tool":
        return [f"command の type が {' か '.join(COMMAND_TYPES)} でない"]
    errors = []
    extra = [key for key in command if key not in ("type", "args", "env")]
    if extra:
        errors.append(f"type が tool の command に、知らないキーがある: {'・'.join(extra)}")
    args = command.get("args")
    if not isinstance(args, list) or not args:
        errors.append("command の args が、1 つ以上の要素を持つ配列でない")
    else:
        errors += [e for e in (_template_error(arg, f"args[{i}]") for i, arg in enumerate(args)) if e]
        if args[0] in PLACEHOLDERS:
            errors.append("command の args[0] (実行ファイル) が、置き換える文字列")
    env = command.get("env", {})
    if not isinstance(env, dict):
        errors.append("command の env が JSON のオブジェクトでない")
    else:
        for name, value in env.items():
            if not _ENV_NAME.match(name):
                errors.append(f"command の env の名前 ({name}) が、大文字・数字・_ だけの名前でない")
            error = _template_error(value, f"env の {name}")
            if error:
                errors.append(error)
    return errors


def _sources_errors(sources):
    if not isinstance(sources, list) or not sources:
        return ["sources が、1 つ以上の要素を持つ配列でない"]
    errors = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or set(source) != {"url", "checked_on"}:
            errors.append(f"sources[{index}] が、キー url と checked_on だけを持つオブジェクトでない")
            continue
        if not isinstance(source["url"], str) or not source["url"].startswith("https://"):
            errors.append(f"sources[{index}] の url が https:// で始まる文字列でない")
        checked_on = source["checked_on"]
        if not isinstance(checked_on, str) or not _DATE.match(checked_on):
            errors.append(f"sources[{index}] の checked_on が YYYY-MM-DD の形でない")
        else:
            try:
                datetime.date.fromisoformat(checked_on)
            except ValueError:
                errors.append(f"sources[{index}] の checked_on ({checked_on}) が日付でない")
    return errors


def row_errors(row):
    """判定表の行 1 つの様式の誤りの配列 (文書 references/judgment-table.md の節「行」)。"""
    if not isinstance(row, dict):
        return ["JSON のオブジェクトでない"]
    errors = []
    unknown = [key for key in row if key not in ROW_KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown))
    errors += [f"キー {key} が無い" for key in REQUIRED_KEYS if key not in row]
    errors += _pattern_errors(row.get("pattern"))
    if row.get("judgment") not in JUDGMENTS:
        errors.append(f"judgment が {'・'.join(JUDGMENTS)} のどれでもない")
    errors += [e for e in (_text_error(row, "reason"), _text_error(row, "impact")) if e]
    errors += _command_errors(row)
    names = row.get("process_names", [])
    if not isinstance(names, list) or not all(isinstance(n, str) and n and "/" not in n for n in names):
        errors.append("process_names が、/ を含まない空でない文字列の配列でない")
    if "dedicated_list" in row:
        if row["dedicated_list"] not in TABLE_DEDICATED_LISTS:
            errors.append(f"dedicated_list が {'・'.join(TABLE_DEDICATED_LISTS)} のどれでもない")
        if row.get("judgment") != "keep":
            errors.append("dedicated_list を持つ行の judgment が keep でない (専用の一覧の行は、まとめて消す対象に選べない)")
    errors += _sources_errors(row.get("sources"))
    return errors


def _overlap(left, right):
    """同じ深さの 2 つのパターンが、同じパスに一致しうるか。"""
    a, b = _pattern_parts(left), _pattern_parts(right)
    return len(a) == len(b) and all(x == y or "*" in (x, y) for x, y in zip(a, b))


def table_errors(rows):
    """判定表全体の誤りの配列。行ごとの様式と、同じ深さで同じパスに一致しうる 2 つの行。"""
    if not isinstance(rows, list):
        return ["判定表が JSON の配列でない"]
    errors = []
    for index, row in enumerate(rows):
        errors += [f"行 {index} ({row.get('pattern') if isinstance(row, dict) else row!r}): {e}" for e in row_errors(row)]
    patterns = [row["pattern"] for row in rows if isinstance(row, dict) and not _pattern_errors(row.get("pattern"))]
    for i in range(len(patterns)):
        for j in range(i + 1, len(patterns)):
            if _overlap(patterns[i], patterns[j]):
                errors.append(f"{patterns[i]} と {patterns[j]} が、同じ深さで同じパスに一致しうる (どちらの行を使うかが決まらない)")
    return errors


def load_table(path=TABLE_PATH):
    """判定表を読み、様式を検査して、行の配列を返す。誤りがあれば ValueError を送出する (プラグインの不具合として扱う)。"""
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    errors = table_errors(rows)
    if errors:
        raise ValueError(f"判定表 {path} の様式の誤り: " + "。".join(errors))
    return rows


def match_table(path, rows, env):
    """path に使う判定表の行。{row, path (行のパターンに一致したディレクトリ)}。無ければ None。

    行は、パターンに一致したディレクトリと、その下の項目に使う。項目とその親のディレクトリに一致する行が複数あれば、階層の多い
    パターンの行を使う。`*` は 1 つの階層の名前全体に一致する (KTD5)。
    """
    _check_absolute(path)
    parts = os.path.realpath(path).split(os.sep)
    home_parts = os.path.realpath(env.home).split(os.sep)
    best = None
    for row in rows:
        pattern = home_parts + _pattern_parts(row["pattern"])
        if len(pattern) > len(parts):
            continue
        if all(p == "*" or p == q for p, q in zip(pattern, parts)):
            if best is None or len(pattern) > len(best[1]):
                best = (row, pattern)
    if best is None:
        return None
    row, pattern = best
    return {"row": row, "path": os.sep.join(parts[:len(pattern)])}


def _resolve(value, matched_path):
    return {"{path}": matched_path, "{name}": os.path.basename(matched_path)}.get(value, value)


def _command(row, path, matched_path):
    """行の command を、項目 path に使う形にする。rm は {type, path}、tool は置き換えた {type, args, env}。"""
    command = row["command"]
    if command is None:
        return None
    if command["type"] == "rm":
        return {"type": "rm", "path": path}
    return {"type": "tool", "args": [_resolve(arg, matched_path) for arg in command["args"]],
            "env": {name: _resolve(value, matched_path) for name, value in command.get("env", {}).items()}}


def _is_app_worktrees(real):
    parts = real.split(os.sep)
    return len(parts) >= 2 and _is_worktrees_pair(parts[-2], parts[-1])


# --- 記録 -----------------------------------------------------------------------------------------------------------

class DirectoryRecords:
    """ディレクトリの記録 (モジュール records の load の返り値のうち、対象の種類が directory のもの) の索引 (計画の KTD16)。

    記録のパスと項目のパスは、シンボリックリンクを解決したパスの文字列と、ディレクトリの識別子 (デバイス番号と inode 番号) の
    両方で比べ、どちらかが同じなら同じディレクトリとする。保護の一覧と同じく、利用者が大文字と小文字だけが違う書き方で記録
    しても、その記録を使うため。記録の識別子は、この索引を作るときに求める (記録には保存しない。ディレクトリを消して作り直すと
    識別子が変わるため)。
    """

    def __init__(self, records):
        self._entries = [(record, record["target"]["path"], _identity(record["target"]["path"]))
                         for record in records if record["target"]["kind"] == "directory"]

    def find(self, entry):
        """entry ((実パス, 識別子)) と同じディレクトリの記録。無ければ None。"""
        real, identity = entry
        for record, path, record_identity in self._entries:
            if path == real or (identity is not None and identity == record_identity):
                return record
        return None

    def nearest(self, real):
        """実パス real か、その親のディレクトリの記録のうち、最も近いもの。(何階層上か (real そのものは 0), 記録)。無ければ None。"""
        for depth, entry in enumerate(_chain(real)):
            record = self.find(entry)
            if record is not None:
                return depth, record
        return None


def _resolved(command, path, real):
    """記録のコマンドを、記録の対象の項目に使う形にする。rm は {type, path}、tool は {path}・{name} を real で置き換える。"""
    if command["type"] == "rm":
        return {"type": "rm", "path": path}
    return {"type": "tool", "args": [_resolve(arg, real) for arg in command["args"]],
            "env": {name: _resolve(value, real) for name, value in command.get("env", {}).items()}}


def _record_command(record, depth, path, real, matched):
    """記録で判定が決まった項目の消すコマンド (計画の KTD16)。記録のもの、項目に使う判定表の行のもの、rm の順に選ぶ。"""
    if record["judgment"] == "keep":
        return None
    if record["command"] is not None:
        return _resolved(record["command"], path, real)
    if depth == 0 and matched is not None:
        row_command = matched["row"]["command"]
        if matched["path"] == real or (row_command is not None and row_command["type"] == "rm"):
            command = _command(matched["row"], path, matched["path"])
            if command is not None:
                return command
    return {"type": "rm", "path": path}


def _from_record(result, path, real, nearest, matched):
    """記録で決まる判定を result に書いて返す (計画の R13・R19・KTD16)。"""
    depth, record = nearest
    record_path = record["target"]["path"]
    row = matched["row"] if matched is not None else None
    impact = record["impact"] if record["impact"] is not None else (row["impact"] if row is not None else None)
    process_names = list(record["process_names"]) or (list(row.get("process_names", [])) if row is not None else [])
    result.update(source="record", impact=impact, process_names=process_names,
                  record={"path": record_path, "decided_by": record["decided_by"],
                          "decided_on": record["decided_on"], "judgment": record["judgment"]})
    command = record["command"]
    if depth > 0 and record["judgment"] != "keep" and command is not None and command["type"] == "tool":
        tool = " ".join(_resolve(arg, record_path) for arg in command["args"])
        result.update(judgment="keep", reason=f"{record_path} の下の項目。{record_path} は、記録のツールのコマンド ({tool})"
                                               " でまとめて消し、下の項目だけを消すコマンドは無い")
        return result
    who = DECIDER_LABELS[record["decided_by"]]
    reason = record["reason"] or f"{who}が {record['decided_on']} に「{JUDGMENT_LABELS[record['judgment']]}」と記録した"
    if depth > 0:
        reason = f"{record_path} の下の項目。{record_path} の記録: {reason}"
    result.update(judgment=record["judgment"], reason=reason,
                  command=_record_command(record, depth, path, real, matched))
    return result


def judge(path, env, rows, records=None, usage=None):
    """path の判定。保護の一覧・記録の「残す」・使われているかどうかによる判定・記録のほかの判定・判定表の順に決める (R13)。

    records は、ディレクトリの記録の索引 (DirectoryRecords)。None なら記録を使わない。usage は、項目のパスを受け取り、
    使われているかどうかで決まる判定 ({judgment, reason, impact, command, process_names}) か、決まらなければ None を返す関数
    (asdf の参照・コンテナの使用・git の worktree。U10〜U12 で渡す)。None なら使わない。

    返り値: {judgment (JUDGMENTS のどれか。判定なしは None), source ("protected"・"record"・"usage"・"table"・None), pattern
    (一致した判定表の行のパターン), matched_path (そのパターンに一致したディレクトリ), reason, impact, command (消すコマンド。rm は
    {type, path}、tool は {type, args, env}), process_names, dedicated_list (DEDICATED_LISTS のどれか。項目そのものが専用の一覧を
    持つ行に一致したときと、項目が .claude/worktrees のとき), protection (保護の一覧の項目なら {kind, path, label}), record
    (判定を決めた記録。{path (記録のディレクトリ), decided_by, decided_on, judgment}。記録で決めなかったときは None)}。

    記録は、項目そのものか、最も近い親のディレクトリのものを使う (R19)。親の「残す」以外の記録は、判定表に、記録のディレクトリ
    より下で項目まで (項目そのものを含む) のディレクトリに一致する行があれば使わず、その行を使う (R13)。Claude が書いたツールの
    コマンドがある記録の下の項目は「残す」にする (R19)。

    判定なしの項目は、Claude が調べて判定する。ツールのコマンドの行の下の項目は「残す」にする。ツールのコマンドは一致した
    ディレクトリをまとめて消すので、下の項目だけを消すコマンドが無いため (文書 references/judgment-table.md の節「行を使う項目」)。
    """
    real = os.path.realpath(path)
    protected = protection(path, env)
    matched = match_table(path, rows, env)
    result = {"judgment": None, "source": None, "pattern": None, "matched_path": None, "reason": None, "impact": None,
              "command": None, "process_names": [], "dedicated_list": None, "protection": protected, "record": None}
    exact = matched is not None and matched["path"] == real
    if exact:
        result["dedicated_list"] = matched["row"].get("dedicated_list")
    if _is_app_worktrees(real):
        result["dedicated_list"] = "worktree"
    if matched is not None:
        result.update(pattern=matched["row"]["pattern"], matched_path=matched["path"])
    if protected is not None:
        result.update(judgment="keep", source="protected",
                      reason=f"保護の一覧にある ({protected['label']}: {protected['path']})")
        return result
    nearest = records.nearest(real) if records is not None else None
    if nearest is not None and nearest[1]["judgment"] == "keep":
        return _from_record(result, path, real, nearest, matched)
    if usage is not None:
        used = usage(path)
        if used is not None:
            result.update(used, source="usage")
            return result
    if nearest is not None:
        depth = nearest[0]
        table_depth = None if matched is None else len(real.split(os.sep)) - len(matched["path"].split(os.sep))
        if depth == 0 or table_depth is None or table_depth >= depth:
            return _from_record(result, path, real, nearest, matched)
    if matched is None:
        return result
    row = matched["row"]
    result.update(source="table", impact=row["impact"], process_names=list(row.get("process_names", [])))
    command = row["command"]
    if exact or command is None or command["type"] == "rm":
        result.update(judgment=row["judgment"], reason=row["reason"], command=_command(row, path, matched["path"]))
    else:
        tool = " ".join(_resolve(arg, matched["path"]) for arg in command["args"])
        result.update(judgment="keep", reason=f"{matched['path']} の下の項目。{matched['path']} は、ツールのコマンド ({tool}) で"
                                               "まとめて消し、下の項目だけを消すコマンドは無い")
    return result
