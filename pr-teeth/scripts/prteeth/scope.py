"""レビュー範囲の判定（pr-teeth プラグイン）。

CONCEPTS.md 第7節の実装。

変更ファイルを must_review / should_review / ignore に分類する。分類は PR の並び順と
深掘りの重点を決めるため、モデルの裁量ではなくここで機械的に確定させる。

glob について:
  fnmatch は `*` がディレクトリ区切りを越えてしまい、`src/*.py` が `src/a/b.py` に
  誤って一致する。設定の意図（`src/payments/**` は配下すべて、`**/*.md` は任意階層の
  .md）を正しく表すため、`**` と `*` を区別する独自の変換を使う。
"""

import re

MUST = "must_review"
SHOULD = "should_review"
IGNORE = "ignore"

# 優先度（高い順）。1ファイルが複数範囲に一致したら最上位を採る。
# 重要な範囲を ignore で誤って隠さないため（第7節）。
PRIORITY = (MUST, SHOULD, IGNORE)

_RANK = {name: i for i, name in enumerate(PRIORITY)}


def _bracket(pattern, start):
    """`[...]` を正規表現の文字クラスに変換する。

    戻り値: (変換後の文字列, 次に読む位置)。閉じ括弧が無ければ (None, start)。

    glob と正規表現で**否定の記号が違う**のが要点。glob は `[!abc]`、正規表現は
    `[^abc]` で否定する。そのままコピーすると `!` がリテラルの感嘆符として解釈され、
    「abc 以外」が「! か a か b か c」になって**判定が正反対**になる。
    """
    i = start + 1
    negate = False
    if i < len(pattern) and pattern[i] in ("!", "^"):
        negate = True
        i += 1

    # 否定記号の直後の `]` はリテラル（`[!]abc]` は「] a b c 以外」）。
    body_start = i
    if i < len(pattern) and pattern[i] == "]":
        i += 1

    j = pattern.find("]", i)
    if j < 0:
        return None, start  # 閉じていない。呼び出し側がリテラル `[` として扱う。

    body = pattern[body_start:j]
    if not body:
        return None, start  # `[]` は文字クラスとして意味を成さない。

    # `*` と同じく、文字クラスも階層を越えさせない。`[a/b]` が `/` に一致すると
    # `src/[a/b]*.go` のようなパターンがディレクトリ境界を跨いでしまう。
    body = body.replace("/", "")
    if not body:
        return None, start

    return ("[" + ("^" if negate else "") + body + "]"), j + 1


def _translate(pattern):
    """glob を正規表現に変換する。`**` は階層を越え、`*` と `?` は越えない。"""
    # 実装は _bracket と合わせて読む（文字クラスの否定記号が glob と正規表現で違う）。
    i = 0
    out = ["^"]
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                # `**/` は0階層以上に一致させる（`**/*.md` が先頭の a.md にも当たるように）。
                if pattern.startswith("/", i):
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            body, j = _bracket(pattern, i)
            if body is not None:
                out.append(body)
                i = j
                continue
        out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def _matches(path, patterns):
    # 設定は利用者が手で書くので、リストでない値（スカラー等）が来ても落とさない。
    if isinstance(patterns, str) or not isinstance(patterns, (list, tuple)):
        patterns = [patterns] if isinstance(patterns, str) else []
    for p in patterns:
        if not isinstance(p, str) or not p.strip():
            continue
        pat = p.strip()
        if _translate(pat).match(path):
            return True
        # ディレクトリ指定 (`docs/`, `docs`) は配下すべてに一致させる。
        if not pat.endswith("*"):
            if _translate(pat.rstrip("/") + "/**").match(path):
                return True
    return False


def classify_file(path, repo_entry, unmatched_default=SHOULD):
    """ファイル1件の範囲を返す（第7節の判定ルール）。"""
    entry = repo_entry or {}
    hits = [name for name in PRIORITY if _matches(path, entry.get(name))]
    if hits:
        return min(hits, key=lambda n: _RANK[n])
    return unmatched_default


def classify_files(paths, repo, config):
    """PR の変更ファイル一覧を分類する。

    戻り値: {"by_file": {path: 範囲}, "counts": {範囲: 件数}, "priority": 範囲}
    priority はその PR 全体の優先度で、PR の並び順に使う（第7節）。

    リポジトリ自体が未設定なら全ファイルを should_review 扱いにする（安全側）。
    ignore に倒すと、設定し忘れたリポジトリの重要な変更を黙って隠してしまう。
    """
    cfg = config or {}
    repos = cfg.get("repos")
    entry = repos.get(repo) if isinstance(repos, dict) else None
    if not isinstance(entry, dict):
        entry = None

    # [repo_defaults] はリポジトリ別設定の既定値。名前で役割が分かるようにしている
    # （[repos.defaults] だと "defaults" という名前のリポジトリと区別できない）。
    defaults = cfg.get("repo_defaults")
    if not isinstance(defaults, dict):
        defaults = {}
    unmatched = defaults.get("unmatched")
    if unmatched not in _RANK:
        unmatched = SHOULD

    if entry is None:
        by_file = {p: SHOULD for p in paths}
    else:
        by_file = {p: classify_file(p, entry, unmatched) for p in paths}

    counts = {name: 0 for name in PRIORITY}
    for name in by_file.values():
        counts[name] = counts.get(name, 0) + 1

    if counts[MUST]:
        priority = MUST
    elif counts[SHOULD]:
        priority = SHOULD
    else:
        priority = IGNORE

    return {"by_file": by_file, "counts": counts, "priority": priority}


def sort_key(result):
    """PR の並び順キー。must → should → ignore（第7節）。"""
    return _RANK[result["priority"]]
