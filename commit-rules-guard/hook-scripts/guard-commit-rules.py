#!/usr/bin/env python3
"""`git commit` の直前にコミットルールを思い出させる PreToolUse フック（commit-rules-guard プラグイン）。

長い作業の後だとコミットの動機（何のために変更したか）が忘れられ、複数の動機を 1 つの
コミットに混ぜてしまいやすい。そこで `git commit`（新規コミット）の直前に一度だけ止め、
コミットルールの要点とステージ内容のサマリ、動機の混在の疑いを提示して自己確認させる。

方針（弱・リマインダ注入 + マーカー方式）:
  - `git commit`（新規コミット。--amend / --dry-run 等は対象外）を検知したら一度だけブロックし、
    stderr で要点・ステージ内容・混在ヒント（あれば）を提示する。
  - 内容を確認して分離不要と判断したら、合図として `--trailer 'Rules-Checked: yes'` を付けて
    再実行すると通過する。混在の推定はブロック理由ではなく「気づきのヒント」で、誤検知でも
    合図を付ければ必ず通る。

リポジトリ固有ルール（config.json。任意）:
  commit 対象リポジトリのトップに置く
  `.claude/akm-claude-plugins/commit-rules-guard/config.json` を読み、次を適用する。
  - generated_globs: 生成物とみなす追加パターンの配列。例: ["*.pb.go", "db/schema.sql"]
  - custom_rules: [{ id, when_all_present: [pattern...], message }]。when_all_present の
    全パターンがステージ内のいずれかのパスにマッチしたとき message をヒントに加える。
    lappds の「db/schema.sql と migrations/ の混在」のような固有ケースをここで宣言する。

汎用化のための設定（環境変数。未設定でも動く）:
  - COMMIT_GUARD_GENERATED_GLOBS: 生成物とみなす追加パターンを「:」区切りで指定できる。
    config.json の generated_globs と併用可。
  - COMMIT_GUARD_RULES_FILE: 表示するルールファイルのパス。既定は
    ~/.claude/rules/commit-rules.md → プラグイン同梱の rules/commit-rules.md の順に探す。

想定外で落ちたら全 Bash を止めないよう許可側に倒す（return 0）。
"""

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

ALLOW = 0
BLOCK = 2

_CHECKED = re.compile(r"Rules-Checked:\s*yes", re.IGNORECASE)
_HEREDOC = re.compile(r"<<-?\s*([\"']?)(\w+)\1")
_SEG = re.compile(r"&&|\|\||[;&|\n]")
_NON_COMMIT_FLAGS = {"--amend", "--dry-run", "-h", "--help", "--interactive", "--patch", "-p"}

# 言語横断で「ツールが生成/管理する」と広く言えるファイル。手書きと動機を分けたい対象。
_GENERATED_DEFAULT = [
    "*.pb.go", "*_grpc.pb.go", "*.pb.gw.go",   # protobuf 系
    "go.sum",                                   # go mod
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock",  # JS
    "Cargo.lock",                               # Rust
    "poetry.lock", "Pipfile.lock", "uv.lock",   # Python
    "composer.lock", "Gemfile.lock",            # PHP / Ruby
]


def _generated_globs(config=None):
    """生成物パターン。既定 + 環境変数 + リポジトリ固有 config の generated_globs を合成する。"""
    globs = list(_GENERATED_DEFAULT)
    extra = os.environ.get("COMMIT_GUARD_GENERATED_GLOBS", "")
    for g in extra.split(":"):
        g = g.strip()
        if g:
            globs.append(g)
    if config:
        for g in config.get("generated_globs", []):
            if isinstance(g, str) and g.strip():
                globs.append(g.strip())
    return globs


def strip_heredocs(s):
    out, delim = [], None
    for line in s.split("\n"):
        if delim is None:
            m = _HEREDOC.search(line)
            if m:
                out.append(line[: m.start()])
                delim = m.group(2)
            else:
                out.append(line)
        elif line.strip() == delim:
            delim = None
    return "\n".join(out)


def tokenize(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def git(repo, *args):
    base = ["git"]
    if repo and repo != "__special__":
        base += ["-C", repo]
    return subprocess.run(base + list(args), capture_output=True, text=True)


# リポジトリ固有ルールの設定ファイル。commit 対象リポジトリのトップからの相対パス。
_PROJECT_CONFIG_REL = ".claude/akm-claude-plugins/commit-rules-guard/config.json"


def _repo_toplevel(repo):
    """commit 対象リポジトリの git トップレベルの絶対パスを返す。取れなければ None。"""
    if repo == "__special__":
        return None
    r = git(repo if repo else None, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return None
    top = r.stdout.strip()
    return top or None


def _load_project_config(repo):
    """commit 対象リポジトリの config.json を読む。無ければ空 dict。壊れていても空 dict。"""
    top = _repo_toplevel(repo)
    if not top:
        return {}
    path = os.path.join(top, _PROJECT_CONFIG_REL)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # 設定が壊れていても本体を止めない（汎用パターンのみで続行）。
        return {}


def find_git(tokens):
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "git" or t.endswith("/git"):
            i += 1
            repo = None
            while i < len(tokens) and tokens[i].startswith("-"):
                g = tokens[i]
                if g == "-C" and i + 1 < len(tokens):
                    repo = tokens[i + 1]
                    i += 2
                    continue
                if g == "-c" and i + 1 < len(tokens):
                    i += 2
                    continue
                if g.startswith("--git-dir") or g.startswith("--work-tree"):
                    repo = "__special__"
                i += 1
            if i < len(tokens):
                return i, repo
            return None, None
        i += 1
    return None, None


def is_new_commit(args):
    for a in args:
        if a in _NON_COMMIT_FLAGS:
            return False
    return True


def staged_entries(repo):
    r = git(repo if repo != "__special__" else None, "diff", "--cached", "--name-status")
    if r.returncode != 0:
        return None
    entries = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        entries.append((parts[0], parts[-1]))
    return entries


def _matches_any(path, globs):
    base = path.rsplit("/", 1)[-1]
    for g in globs:
        if fnmatch.fnmatch(path, g) or fnmatch.fnmatch(base, g):
            return True
        # "migrations/*" のようなディレクトリ prefix パターンにも当てる。
        if g.endswith("/*") and (path == g[:-2] or path.startswith(g[:-1])):
            return True
    return False


def _custom_rule_hints(entries, config):
    """config の custom_rules を評価する。when_all_present の全パターンがステージ内の
    いずれかのパスにマッチしたら、その message をヒントに加える。"""
    hints = []
    paths = [p for _, p in entries]
    for rule in config.get("custom_rules", []):
        if not isinstance(rule, dict):
            continue
        patterns = rule.get("when_all_present", [])
        message = rule.get("message", "")
        if not patterns or not message:
            continue
        if all(any(_matches_any(p, [pat]) for p in paths) for pat in patterns):
            hints.append(message)
    return hints


def classify(entries, config=None):
    config = config or {}
    hints = []
    paths = [p for _, p in entries]
    globs = _generated_globs(config)

    generated = [p for p in paths if _matches_any(p, globs)]
    handwritten = [p for p in paths if not _matches_any(p, globs)]

    if generated and handwritten:
        hints.append(
            "生成物（" + ", ".join(generated[:3])
            + ("…" if len(generated) > 3 else "")
            + "）と手書きの変更が同時にステージされています。"
            "『手書きと自動生成は別の動機』— 分けてコミットするか確認してください。"
        )

    has_docs = any(re.search(r"(^|/)docs?/", p) or p.lower().endswith((".md", ".rst")) for p in paths)
    has_code = any(re.search(r"\.(go|py|rs|ts|tsx|js|jsx|rb|java|kt|php|c|cc|cpp|h)$", p) for p in paths)
    if has_docs and has_code:
        hints.append(
            "ドキュメントの変更とコードの変更が同時にステージされています。"
            "その変更に直接関連する更新なら同一コミットで良いですが、無関係なら分けてください。"
        )

    has_rename = any(s.startswith("R") for s, _ in entries)
    has_add = any(s.startswith("A") for s, _ in entries)
    if has_rename and has_add:
        hints.append(
            "改名・移動（R）と新規追加（A）が同時にステージされています。"
            "リファクタリングと機能追加は別の動機です。混在していないか確認してください。"
        )

    # リポジトリ固有ルール（config.json の custom_rules）を最後に足す。
    hints.extend(_custom_rule_hints(entries, config))

    return hints


def _rules_file():
    """表示するルールファイルを探す。環境変数 → ユーザーのグローバル → プラグイン同梱の順。"""
    env = os.environ.get("COMMIT_GUARD_RULES_FILE")
    if env and os.path.isfile(os.path.expanduser(env)):
        return os.path.expanduser(env)
    user = os.path.expanduser("~/.claude/rules/commit-rules.md")
    if os.path.isfile(user):
        return user
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        bundled = os.path.join(root, "rules", "commit-rules.md")
        if os.path.isfile(bundled):
            return bundled
    return None


def build_message(entries, hints):
    lines = []
    rf = _rules_file()
    src = rf if rf else "（コミットルールファイル未設定。内蔵の要点を表示）"
    lines.append("コミットルールの確認: " + src)
    lines.append("")
    lines.append("コミットは『変更した動機』でグルーピングし、複数の動機を 1 つに混ぜないでください。")
    lines.append("特に次は忘れやすいので確認してください:")
    lines.append("  - レビューや linter の複数の指摘は、指摘ごとに別コミットにする（まとめない）。")
    lines.append("  - 手書きのコードと、ツールによる自動生成物は別コミットにする。")
    lines.append("  - リファクタリングと、機能の追加/変更/削除・問題の修正は別コミットにする。")
    lines.append("")
    lines.append("今回ステージされている変更:")
    if entries:
        for status, path in entries[:30]:
            lines.append("  " + status + "\t" + path)
        if len(entries) > 30:
            lines.append("  …ほか " + str(len(entries) - 30) + " 件")
    else:
        lines.append("  （ステージされた変更を取得できませんでした）")
    if hints:
        lines.append("")
        lines.append("混在の疑い（気づきのヒント。誤りなら無視してよい）:")
        for h in hints:
            lines.append("  - " + h)
    lines.append("")
    lines.append("上を確認し、動機が混在していれば分割してからコミットし直してください。")
    lines.append("分離不要と判断したら、確認済みの合図として次を付けて再実行してください:")
    lines.append("  git commit ... --trailer 'Rules-Checked: yes'")
    return "\n".join(lines)


def evaluate_segment(seg):
    tokens = tokenize(seg)
    idx, repo = find_git(tokens)
    if idx is None:
        return ALLOW
    if tokens[idx] != "commit":
        return ALLOW
    args = tokens[idx + 1:]
    if not is_new_commit(args):
        return ALLOW
    entries = staged_entries(repo)
    if entries is not None and len(entries) == 0:
        return ALLOW
    config = _load_project_config(repo)
    hints = classify(entries, config) if entries else []
    sys.stderr.write(build_message(entries or [], hints) + "\n")
    return BLOCK


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            return 0
        cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
        if _CHECKED.search(cmd):
            return 0
        code = strip_heredocs(cmd)
        for seg in _SEG.split(code):
            seg = seg.strip()
            if not seg:
                continue
            if evaluate_segment(seg) == BLOCK:
                return BLOCK
        return ALLOW
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
