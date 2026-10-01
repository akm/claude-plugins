"""textlint を取得・実行して、用語ファイルと規則集で文章を検査する。

textlint と規則集は、プラグインに同梱した `wording-guard/textlint/package.json` と
`package-lock.json` で版を固定し、コマンド `wording_lint.py setup` が利用者のキャッシュに
`npm ci` で入れる。置き場はロックファイルの内容のハッシュで分けるので、プラグインを更新して
版が変わると、新しい置き場に入れ直すことになる。

実行するたびに、次の 3 つを合わせた textlint の設定を一時ディレクトリに作る。
  1. リポジトリの textlint の設定 (設定キー textlint.config。候補を出す規則集の選び方)
  2. 用語ファイルから生成した prh の辞書と許容の一覧 (wordingguard.terms)
  3. 引用ブロックを検出から除くフィルタ (wording-guard が引用を書き換えないため)

振る舞いの正本はファイル `wording-guard/skills/wording-guard/references/textlint.md`。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import config, terms

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_DIR = os.path.join(PLUGIN_ROOT, "textlint")
CACHE_ENV = "WORDING_GUARD_CACHE_DIR"
SEVERITIES = {0: "info", 1: "warning", 2: "error"}


class TextlintError(Exception):
    """textlint が入っていない・実行に失敗したときのエラー。"""


def setup_command():
    return f"python3 {os.path.join(PLUGIN_ROOT, 'scripts', 'wording_lint.py')} setup"


def cache_root():
    """textlint を入れる場所の親ディレクトリ。環境変数 WORDING_GUARD_CACHE_DIR で変えられる。"""
    if os.environ.get(CACHE_ENV):
        return os.environ[CACHE_ENV]
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "akm-claude-plugins", "wording-guard")


def install_dir():
    """同梱のロックファイルに対応する、textlint の置き場。"""
    with open(os.path.join(PACKAGE_DIR, "package-lock.json"), "rb") as f:
        key = hashlib.sha256(f.read()).hexdigest()[:16]
    return os.path.join(cache_root(), f"textlint-{key}")


def textlint_bin(directory):
    return os.path.join(directory, "node_modules", ".bin", "textlint")


def ensure_installed():
    """textlint の置き場を返す。入っていなければ TextlintError を送出する。"""
    d = install_dir()
    if not os.path.exists(textlint_bin(d)):
        raise TextlintError(
            f"textlint が入っていない (探した場所: {d})。コマンド `{setup_command()}` で入れる"
            " (npm で約 380 個のパッケージを取得する。Node と npm が必要)")
    return d


def setup(out=sys.stdout):
    """同梱の package.json と package-lock.json の版で、textlint をキャッシュに入れる。

    npm ci は一時的な名前のディレクトリで行い、終わってから置き場の名前に変える。置き場の状態ごとの扱い:
      - textlint が入っている: 何もしない。
      - 置き場があるのに textlint が無い (中身が消えた・壊れた): 取得を始める前に TextlintError で止め、
        置き場を消すよう案内する。置き場はこの関数では消さない (中身を利用者が確かめられるように)。
      - 置き場が無い: 取得して名前を変える。名前を変える前に、同時に実行した別の setup が置き場を
        作り終えていたら (改名が失敗し、置き場に textlint がある)、入ったものとして扱う。
    一時的な名前のディレクトリは、成否に関わらず最後に消す。置き場の名前に変わらなかった木を残しても、
    次の setup は使わないため。ファイル操作の失敗 (OSError) は TextlintError にして呼び出し側に返す。
    """
    try:
        return _setup(out)
    except OSError as e:
        raise TextlintError(f"textlint のセットアップに失敗した: {e}") from e


def _setup(out):
    d = install_dir()
    if os.path.exists(textlint_bin(d)):
        print(f"textlint は入っている: {d}", file=out)
        return d
    if os.path.exists(d):
        raise TextlintError(
            f"textlint の置き場 {d} があるのに、textlint が入っていない (置き場が壊れている)。"
            f"置き場を消してから (rm -rf \"{d}\")、もう一度実行する")
    npm = shutil.which("npm")
    if npm is None:
        raise TextlintError("npm が見つからない。Node (npm を含む) を入れてから実行する")
    os.makedirs(cache_root(), exist_ok=True)
    work = tempfile.mkdtemp(prefix=os.path.basename(d) + ".", dir=cache_root())
    try:
        for name in ("package.json", "package-lock.json"):
            shutil.copy(os.path.join(PACKAGE_DIR, name), work)
        print(f"npm ci を実行する: {work}", file=out)
        r = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=work, capture_output=True, text=True)
        if r.returncode != 0:
            raise TextlintError(f"npm ci が失敗した (終了コード {r.returncode}):\n{r.stderr.strip()}")
        try:
            os.rename(work, d)
        except OSError as e:
            if os.path.exists(textlint_bin(d)):
                print(f"textlint は、同時に実行した別の setup が先に入れた: {d}", file=out)
                return d
            raise TextlintError(f"取得した textlint を置き場 {d} に移せない: {e}") from e
    finally:
        if os.path.exists(work):
            shutil.rmtree(work, ignore_errors=True)
    print(f"textlint を入れた: {d}", file=out)
    return d


def _load_base(path):
    """リポジトリの textlint の設定 (JSON) を読む。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise config.ConfigError(f"textlint の設定 {path} を読めない (JSON で書く): {e}") from e
    if not isinstance(data, dict):
        raise config.ConfigError(f"textlint の設定 {path} の最上位が JSON のオブジェクトでない")
    return data


def _absolutize(paths, base_dir):
    return [p if os.path.isabs(p) else os.path.join(base_dir, p) for p in paths]


def _option(value, name, where):
    """規則やフィルタの設定値 (true・オブジェクト) を、書き足せるオブジェクトにする。"""
    if value is None or value is True:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise config.ConfigError(f"{where} が {name} を無効にしている。用語ファイルの検査に {name} を使うので、無効にしない")


def compose(root, cfg, term_list, workdir, fix_only=False):
    """textlint の設定を workdir に作り、(設定のパス, 規則が 1 つ以上あるか) を返す。

    規則が 1 つも無いときに textlint を実行すると、JSON ではなく案内の文を出すので、
    呼び出し側は規則が無ければ textlint を実行しない。

    fix_only が True のときは、自動修正してよい避ける語だけを入れる (リポジトリの規則集と、
    検出だけする避ける語は入れない)。自動修正で文脈によって言い換えが変わる語を書き換えないため。
    """
    base, base_dir, where = {}, root, "設定"
    base_path = config.textlint_config_path(root, cfg)
    if base_path and not fix_only:
        base, base_dir, where = _load_base(base_path), os.path.dirname(base_path), f"textlint の設定 {base_path}"
    composed = {k: v for k, v in base.items() if k not in ("rules", "filters")}
    rules = dict(base.get("rules", {}))
    filters = dict(base.get("filters", {}))

    fix, detect = terms.to_prh(term_list)
    dictionaries = []
    for name, items in (("prh-fix.yml", fix), ("prh-detect.yml", [] if fix_only else detect)):
        if items:
            path = os.path.join(workdir, name)
            # prh は辞書を YAML として読む。JSON は YAML として読めるので、JSON で書く
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "rules": items}, f, ensure_ascii=False, indent=2)
            dictionaries.append(path)
    if dictionaries or "prh" in rules:
        prh = _option(rules.get("prh"), "規則 prh", where)
        prh["rulePaths"] = _absolutize(prh.get("rulePaths", []), base_dir) + dictionaries
        if prh["rulePaths"]:
            rules["prh"] = prh
        else:
            # 辞書が 1 つも無い prh では、textlint が例外で終わり、検査できるものも無いので外す
            rules.pop("prh", None)

    allow = terms.to_allowlist(term_list)
    if allow or "allowlist" in filters:
        allowlist = _option(filters.get("allowlist"), "フィルタ allowlist", where)
        allowlist["allow"] = list(allowlist.get("allow", [])) + allow
        if "allowlistConfigPaths" in allowlist:
            allowlist["allowlistConfigPaths"] = _absolutize(allowlist["allowlistConfigPaths"], base_dir)
        filters["allowlist"] = allowlist

    node_types = _option(filters.get("node-types"), "フィルタ node-types", where)
    node_types["nodeTypes"] = list(dict.fromkeys(list(node_types.get("nodeTypes", [])) + ["BlockQuote"]))
    filters["node-types"] = node_types

    composed["rules"] = rules
    composed["filters"] = filters
    path = os.path.join(workdir, "textlintrc.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(composed, f, ensure_ascii=False, indent=2)
    return path, bool(rules)


def _run_textlint(directory, conf, paths, cwd, fix=False):
    cmd = [textlint_bin(directory), "--config", conf, "--rules-base-directory",
           os.path.join(directory, "node_modules"), "--format", "json"]
    if fix:
        cmd.append("--fix")
    try:
        r = subprocess.run(cmd + paths, cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        raise TextlintError(f"textlint を実行できない ({cmd[0]}): {e}") from e
    # textlint は、検出が無いか warning だけなら 0、error があれば 1 で終わる。それ以外は実行の失敗。
    # 規則の読み込みや実行が例外で終わったときも 1 で終わるが、そのときは標準出力に何も出さない
    # (textlint 15.8.0 で確かめた)。検出が無いときもファイルごとの結果を JSON で出すので、空の出力は失敗として扱う
    if r.returncode not in (0, 1) or not r.stdout.strip():
        raise TextlintError(f"textlint が失敗した (終了コード {r.returncode}):\n{r.stderr.strip() or r.stdout.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise TextlintError(f"textlint の出力を JSON として読めない: {e}\n{r.stdout[:500]}") from e


def _finding(message, source):
    """textlint の 1 件の検出を、wording-guard が扱う形に変換する。"""
    # prh は検出の範囲 (range) に先頭の 1 文字だけを入れ、置き換える範囲を fix.range に入れる。
    # 他の規則にも range が 1 文字だけのもの (ja-no-redundant-expression など) があり、
    # 1 文字では何を指すか読み取れないので、その場合は検出した文字列を空にする
    span = (message.get("fix") or {}).get("range") or message.get("range")
    matched = source[span[0]:span[1]] if span and source is not None else ""
    if len(matched) <= 1:
        matched = ""
    return {
        "rule": message.get("ruleId", ""),
        "severity": SEVERITIES.get(message.get("severity"), "error"),
        "message": message.get("message", ""),
        "line": message.get("line"),
        "column": message.get("column"),
        "matched": matched,
    }


def check_files(root, cfg, term_list, paths):
    """ファイルを検査し、{パス: 検出のリスト} を返す。"""
    if not paths:
        return {}
    directory = ensure_installed()
    with tempfile.TemporaryDirectory() as work:
        conf, has_rules = compose(root, cfg, term_list, work)
        if not has_rules:
            return {os.path.abspath(p): [] for p in paths}
        results = _run_textlint(directory, conf, [os.path.abspath(p) for p in paths], cwd=root)
    found = {}
    for r in results:
        with open(r["filePath"], encoding="utf-8") as f:
            source = f.read()
        found[r["filePath"]] = [_finding(m, source) for m in r["messages"]]
    return found


def check_texts(root, cfg, term_list, texts, filename="text.md"):
    """文字列のリストを検査し、文字列ごとの検出のリストを、同じ順で返す。

    1 回の textlint の実行でまとめて検査する (hook が書き足す前と後の文字列を比べるのに使う)。
    filename の拡張子で、textlint が文章の形式 (Markdown など) を決める。
    """
    if not texts:
        return []
    directory = ensure_installed()
    with tempfile.TemporaryDirectory() as work:
        conf, has_rules = compose(root, cfg, term_list, work)
        if not has_rules:
            return [[] for _ in texts]
        paths = []
        for i, text in enumerate(texts):
            d = os.path.join(work, "input", str(i))
            os.makedirs(d)
            path = os.path.join(d, os.path.basename(filename))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            paths.append(path)
        results = _run_textlint(directory, conf, paths, cwd=root)
        by_path = {os.path.realpath(r["filePath"]): r["messages"] for r in results}
    return [[_finding(m, text) for m in by_path.get(os.path.realpath(p), [])] for p, text in zip(paths, texts)]


def fix_files(root, cfg, term_list, paths):
    """自動修正してよい避ける語 (autofix = true) だけを、ファイルに適用する。{パス: 適用した件数} を返す。"""
    if not paths:
        return {}
    directory = ensure_installed()
    with tempfile.TemporaryDirectory() as work:
        conf, has_rules = compose(root, cfg, term_list, work, fix_only=True)
        if not has_rules:
            return {os.path.abspath(p): 0 for p in paths}
        results = _run_textlint(directory, conf, [os.path.abspath(p) for p in paths], cwd=root, fix=True)
    return {r["filePath"]: len(r.get("applyingMessages", [])) for r in results}
