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
"""

import re

# https://github.com/owner/repo/pull/123 とその派生（/files, ?w=1, #discussion_r... 等）。
# ホストは github.com とその Enterprise 相当を想定し、ホスト名自体は縛らない
# （縛ると GHE の利用者が使えなくなる。owner/repo/pull/number の並びで十分特定できる）。
_URL = re.compile(
    r"^(?:https?://)?[^/\s]+/"
    r"(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull(?:s)?/(?P<number>\d+)"
    r"(?:[/?#].*)?$"
)

# owner/repo#123 と owner/repo/123。`#` は shell で消えやすいので後者も受ける。
_SHORT = re.compile(r"^(?P<owner>[^/\s#]+)/(?P<repo>[^/\s#]+)(?:#|/)(?P<number>\d+)$")

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
        return {"repo": owner + "/" + repo, "number": int(m.group("number"))}

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
