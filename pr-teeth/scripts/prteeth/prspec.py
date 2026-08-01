"""PR の指定を解釈する（pr-teeth プラグイン）。

CONCEPTS.md 第16節（番号指定の解説）の実装。

利用者は PR を次のどちらの形でも渡せる。

  owner/repo#123
  https://github.com/owner/repo/pull/123

**解釈をモデルに任せない理由:** URL から owner/repo/number を取り出す作業は、
見た目には簡単でも取り違えが起きる（`/pull/123/files` の末尾、`#issuecomment-...`
のフラグメント、末尾スラッシュ、`www.` の有無）。取り違えると**別の PR の解説を
正しい体裁で出してしまい、読み手には誤りだと分からない**。範囲判定と同じく、
機械的に決まるものはここで確定させる。

見分けが付かない入力は**捨てずに理由付きで返す**。黙って落とすと、渡したはずの
PR が出力に無いことに気づけない。

ホストの扱い:
  URL のホスト部分は**照合するだけで捨てる**。取り出すのは owner / repo / number
  だけで、リンクは `document.GITHUB_HOST` から組み立てられる。つまり GitHub
  Enterprise の URL を貼っても、公開 github.com の同名リポジトリを指す。
  GHE は `document.GITHUB_HOST` 側が未対応（設定で持つ想定のまま固定値）なので、
  **ここだけホストを受け入れても対応したことにならない。** 対応する場合は
  ホストを設定に持たせ、この関数の戻り値にも載せて `gh --hostname` まで通す
  必要がある。今はその手前で loud に失敗する（`gh` が引けずエラーになる）。
"""

import re

# owner / repo に許す文字。GitHub のアカウント名は英数字とハイフンだけで、
# **ドットを含まない**。この制約が「ホストらしい文字列を owner と誤認しない」
# 保証になっている（下の _SHORT の項を参照）。
_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_REPO = r"[A-Za-z0-9._-]+"

# https://github.com/owner/repo/pull/123 とその派生（/files, ?w=1, #discussion_r... 等）。
# **ホストは必ずドットを含むか、スキームが付いていること**を要求する。
# ここを `[^/\s]+` と緩くすると、`foo/bar/baz/pull/9` のような素のパスの先頭が
# ホストとして食われ、`bar/baz` という**打っていないリポジトリ**に解決される。
_URL = re.compile(
    r"^(?:https?://[^/\s]+|[^/\s]*\.[^/\s]+)/"
    r"(?P<owner>" + _OWNER + r")/(?P<repo>" + _REPO + r")/pull(?:s)?/(?P<number>\d+)"
    r"(?:[/?#].*)?$"
)

# owner/repo#123 と owner/repo/123。`#` は引用符を付け忘れると渡らないことがあるので
# 後者も受ける。owner にドットを許さないので、`github.com/akm/123` のような
# スキーム無しの URL 断片がここに落ちてきて `github.com/akm` に化けることはない。
_SHORT = re.compile(
    r"^(?P<owner>" + _OWNER + r")/(?P<repo>" + _REPO + r")(?:#|/)(?P<number>\d+)$"
)

_EXPECTED = "owner/repo#123 または https://github.com/owner/repo/pull/123"


class InvalidSpec(Exception):
    """PR の指定として解釈できない。"""


def parse_one(text):
    """指定1件を {"repo", "number"} にする。解釈できなければ InvalidSpec。"""
    raw = (text or "").strip()
    if not raw:
        raise InvalidSpec("空の指定です。期待する形: " + _EXPECTED)

    for pattern in (_URL, _SHORT):
        m = pattern.match(raw)
        if not m:
            continue
        owner = m.group("owner")
        repo = m.group("repo")
        # URL の `.git` 付き（clone URL からの貼り付け）を吸収する。
        if repo.endswith(".git"):
            repo = repo[: -len(".git")]
        if not owner or not repo:
            continue
        # **大文字小文字を畳む。** GitHub は owner/repo を区別しないが、この先の
        # 設定引き当て（config.toml の [repos."owner/repo"]）と範囲判定は素の辞書
        # 引きなので、`Akm/Claude-Plugins` と打つと設定を取りこぼし、出力言語と
        # レビュー範囲が黙って既定値に落ちる。巡回は `gh search prs` が返す正規の
        # 表記を使うためこの問題が無く、番号指定だけが利用者の打った文字列を
        # そのまま流す。ここが識別子を確定させる唯一の場所なので、ここで揃える。
        return {"repo": (owner + "/" + repo).lower(), "number": int(m.group("number"))}

    raise InvalidSpec("「" + raw + "」を PR の指定として解釈できません。期待する形: " + _EXPECTED)


def parse(specs):
    """複数の指定をまとめて解釈する。

    戻り値: (targets, errors)
      targets: [{"repo","number"}]。**入力順を保ち、重複は先勝ちで1件に畳む。**
      errors:  解釈できなかった指定の理由（文字列）。

    重複を畳むのは、同じ PR を2回解説しても情報が増えないため。ただし**畳んだ事実は
    errors には入れない**（利用者の誤りではなく、実害も無い）。
    """
    targets = []
    errors = []
    seen = set()
    for spec in specs or []:
        try:
            item = parse_one(spec)
        except InvalidSpec as e:
            errors.append(str(e))
            continue
        key = (item["repo"], item["number"])
        if key in seen:
            continue
        seen.add(key)
        targets.append(item)
    return targets, errors
