"""消すコマンドに使ってよい実行ファイルとサブコマンドの組と、Claude が書いたコマンドの検査 (計画
docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R16・KTD6)。

判定表 (ファイル `disk-usage-triage/scripts/disk_usage_triage/judgment-table.json`) のツールのコマンドと、判定表に無い項目に
Claude が書いたコマンド (計画の R16) は、定数 ALLOWED の組のどれかで始める。実行ファイルだけで許可すると、`rustup run`・`uv run`・
`pnpm exec` のように別のコマンドを起動するサブコマンドを経由して、選んだ項目の外のものを消せるため (計画の KD17)。組を増やす
ときは、各ツールの文書で確認してから足し、プラグインを更新する。

Claude が書いたコマンドの検査 (関数 command_errors) は、このモジュールにだけ置き、記録するときと削除のシェルスクリプトを作るとき
の両方で使う (計画の KTD6)。検査の内容の SSOT は、文書 `disk-usage-triage/references/files.md` の節「Claude の判定の入力」。
"""

import json
import re

# 組 (引数の配列の先頭と順に比べる)・使ってよい環境変数の名前・Claude が書ける形・組を確認した文書。環境変数は、キャッシュの
# 場所を指定するものだけを許可する。名前を限らないと、PATH・NODE_OPTIONS・DYLD_INSERT_LIBRARIES などで別のプログラムを実行
# させられるため (計画の KTD6。U4 を実装するときに利用者が決めた。2026-11-27)。形 (forms) は、引数の配列と環境変数の組で、
# 判定表のツールのコマンドと同じく、項目を {path} か {name} で指す。Claude が書いたコマンドは、形のどれかと一致しなければ
# 誤りにする。組に続く引数で、選んだ項目の外を対象にさせないため (計画の R16。2026-11-28 に利用者が決めた)。
# 端末の UDID の形 (xcrun simctl list が示す形)。xcrun simctl delete は、端末の UDID のほかに、端末の名前と all・booted・
# unavailable も受け付けるので、{name} を置き換える値をこの形に限る。置き換えた後のコマンドが、項目のほかの端末を消す
# コマンド (xcrun simctl delete all など) にならないようにするため (計画の R16。2026-11-28 に利用者が決めた)
UDID_PATTERN = r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}"

ALLOWED = (
    {"args": ("brew", "cleanup"), "env": ("HOMEBREW_CACHE",),
     "forms": ({"args": ("brew", "cleanup"), "env": {"HOMEBREW_CACHE": "{path}"}},),
     "sources": ({"url": "https://docs.brew.sh/Manpage", "checked_on": "2026-11-27"},)},
    {"args": ("go", "clean"), "env": ("GOCACHE", "GOMODCACHE"),
     "forms": ({"args": ("go", "clean", "-cache"), "env": {"GOCACHE": "{path}"}},
               {"args": ("go", "clean", "-modcache"), "env": {"GOMODCACHE": "{path}"}}),
     "sources": ({"url": "https://pkg.go.dev/cmd/go#hdr-Remove_object_files_and_cached_files", "checked_on": "2026-11-27"},
                 {"url": "https://pkg.go.dev/cmd/go#hdr-Build_and_test_caching", "checked_on": "2026-11-25"},
                 {"url": "https://go.dev/ref/mod#module-cache", "checked_on": "2026-11-25"})},
    {"args": ("npm", "cache", "clean"), "env": (),
     "forms": ({"args": ("npm", "cache", "clean", "--force", "--cache", "{path}"), "env": {}},),
     "sources": ({"url": "https://docs.npmjs.com/cli/v11/commands/npm-cache", "checked_on": "2026-11-25"},)},
    {"args": ("pip", "cache", "purge"), "env": (),
     "forms": ({"args": ("pip", "cache", "purge", "--cache-dir", "{path}"), "env": {}},),
     "sources": ({"url": "https://pip.pypa.io/en/stable/cli/pip_cache/", "checked_on": "2026-11-25"},)},
    {"args": ("pnpm", "store", "prune"), "env": (),
     "forms": ({"args": ("pnpm", "store", "prune", "--store-dir", "{path}"), "env": {}},),
     "sources": ({"url": "https://pnpm.io/10.x/cli/store", "checked_on": "2026-11-25"},)},
    {"args": ("uv", "cache", "clean"), "env": (),
     "forms": ({"args": ("uv", "cache", "clean", "--cache-dir", "{path}"), "env": {}},),
     "sources": ({"url": "https://docs.astral.sh/uv/concepts/cache/#clearing-the-cache", "checked_on": "2026-11-27"},)},
    {"args": ("uv", "cache", "prune"), "env": (),
     "forms": ({"args": ("uv", "cache", "prune", "--cache-dir", "{path}"), "env": {}},),
     "sources": ({"url": "https://docs.astral.sh/uv/concepts/cache/#clearing-the-cache", "checked_on": "2026-11-27"},)},
    {"args": ("xcrun", "simctl", "delete"), "env": (),
     "forms": ({"args": ("xcrun", "simctl", "delete", "{name}"), "env": {},
                "name": {"pattern": UDID_PATTERN, "label": "端末の UDID"}},),
     "sources": ({"url": "https://developer.apple.com/forums/thread/812408", "checked_on": "2026-11-25"},)},
)

# 特殊文字 (計画の KTD6)。削除のシェルスクリプトでは引数ごとにクォートするが、クォートの誤りがあっても別のコマンドを実行させない
# ために、Claude が書いたコマンドには書かせない
SPECIAL_CHARACTERS = (";", "|", "&", "$", "`", "<", ">", "\n")
_CHARACTER_NAMES = {"`": "バッククォート", "\n": "改行"}

# Claude が書けない実行ファイル。これらのコマンドは、それぞれのドメイン (asdf・Docker・git の worktree) でスクリプトが組み立てる
DOMAIN_EXECUTABLES = ("docker", "asdf", "git")

PLACEHOLDERS = ("{path}", "{name}")  # 引数と環境変数の値に書け、記録の対象のディレクトリの絶対パスと名前に置き換える
COMMAND_TYPES = ("rm", "tool")


def allowed_entry(args):
    """引数の配列 args が始まる組の、ALLOWED の要素。どの組でも始まらなければ None。"""
    for entry in ALLOWED:
        if tuple(args[:len(entry["args"])]) == entry["args"]:
            return entry
    return None


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


# パスの形の値の先頭。これらで始まる値と、/ を含む値は、パスとして受け付けない。項目の場所は {path} で書かせ、Claude が書いた
# パスで、選んだ項目の外を消させないため (計画の R16。2026-11-28 に利用者が決めた)。
PATH_PREFIXES = ("/", "~", ".")


def value_errors(value, where):
    """引数か環境変数の値 value の誤りの配列。where は誤りの文に書く場所の名前。"""
    if not isinstance(value, str):
        return [f"{where} が文字列でない"]
    if value == "":
        return [f"{where} が空の文字列"]
    errors = []
    if "\0" in value:
        errors.append(f"{where} ({_dump(value)}) が NUL 文字を含む")
    found = [_CHARACTER_NAMES.get(c, c) for c in SPECIAL_CHARACTERS if c in value]
    if found:
        errors.append(f"{where} ({_dump(value)}) が、シェルの特殊文字 ({'・'.join(found)}) を含む")
    if ("{" in value or "}" in value) and value not in PLACEHOLDERS:
        errors.append(f"{where} ({_dump(value)}) の {{ }} が、{' か '.join(PLACEHOLDERS)} の要素全体でない")
    if value.startswith(PATH_PREFIXES) or "/" in value:
        errors.append(f"{where} ({_dump(value)}) がパスの形 ({'・'.join(PATH_PREFIXES)} で始まるか、/ を含む)。"
                      "項目の場所は {path} と書く")
    return errors


def _executable_errors(args):
    executable = args[0]
    if not isinstance(executable, str) or executable == "":
        return []  # value_errors が示す
    if executable in PLACEHOLDERS:
        return [f"実行ファイル (args[0]) が、置き換える文字列 {executable}"]
    if "/" in executable:
        return [f"実行ファイル ({_dump(executable)}) をパスで書いている (名前だけを書く)"]
    if executable in DOMAIN_EXECUTABLES:
        return [f"{executable} のコマンドは書けない ({'・'.join(DOMAIN_EXECUTABLES)} のコマンドは、それぞれの一覧で"
                "スクリプトが組み立てる)"]
    if allowed_entry(args) is not None:
        return []
    pairs = [" ".join(entry["args"]) for entry in ALLOWED if entry["args"][0] == executable]
    if not pairs:
        return [f"許可していない実行ファイル ({_dump(executable)})。許可している組: "
                + "・".join(" ".join(entry["args"]) for entry in ALLOWED)]
    return [f"許可していない組 ({_dump(' '.join(str(a) for a in args[:3]))})。{executable} で許可している組: "
            + "・".join(pairs)]


def _env_errors(env, entry):
    if not isinstance(env, dict):
        return ["env が JSON のオブジェクトでない"]
    errors = []
    allowed = entry["env"] if entry is not None else ()
    for name, value in env.items():
        if entry is not None and name not in allowed:
            names = "・".join(allowed) if allowed else "無し"
            errors.append(f"環境変数 {name} は、組 {' '.join(entry['args'])} に許可していない (許可している名前: {names})")
        errors += value_errors(value, f"環境変数 {name} の値")
    return errors


def _form_text(form):
    env = "".join(f"{name}={value} " for name, value in form["env"].items())
    return env + " ".join(form["args"])


def _form_errors(args, env, entry):
    """コマンド (引数の配列 args と環境変数 env) が、組 entry の形のどれとも一致しないときの誤りの配列。"""
    if any(list(form["args"]) == args and form["env"] == env for form in entry["forms"]):
        return []
    forms = "・".join(_form_text(form) for form in entry["forms"])
    return [f"コマンドが、組 {' '.join(entry['args'])} の形のどれとも一致しない (書ける形: {forms})"]


def name_errors(command, name):
    """消すコマンド command の {name} を、項目の名前 name に置き換えてよいかの誤りの配列 (計画の R16)。

    組の形が {name} に置き換える値を限るとき (定数 ALLOWED の forms の name) に、名前がその形でなければ誤りにする。判定表の
    ツールのコマンドと Claude が書いたコマンドの両方に使う。
    """
    if not isinstance(command, dict) or command.get("type") != "tool":
        return []
    args = command.get("args")
    if not isinstance(args, list) or "{name}" not in args or not all(isinstance(a, str) for a in args):
        return []
    entry = allowed_entry(args)
    if entry is None:
        return []
    for form in entry["forms"]:
        limit = form.get("name")
        if limit is not None and list(form["args"]) == args and not re.fullmatch(limit["pattern"], name):
            return [f"項目の名前 ({_dump(name)}) が、{_form_text(form)} の {{name}} に置き換えられる形 ({limit['label']}) でない"]
    return []


def command_errors(command):
    """消すコマンド command の誤りの配列 (計画の R16)。

    command は {"type": "rm"} か {"type": "tool", "args": [...], "env": {...}}。tool は、引数と環境変数を検査する。
    """
    if not isinstance(command, dict):
        return ["command が JSON のオブジェクトでない"]
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
        return errors
    for index, arg in enumerate(args):
        errors += value_errors(arg, f"args[{index}]")
    errors += _executable_errors(args)
    entry = allowed_entry(args) if all(isinstance(a, str) for a in args) else None
    if "env" in command:
        errors += _env_errors(command["env"], entry)
    env = command.get("env", {})
    if entry is not None and isinstance(env, dict):
        errors += _form_errors(args, env, entry)
    return errors
