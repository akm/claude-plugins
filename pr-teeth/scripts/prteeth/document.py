"""解説データの型（pr-teeth プラグイン）。

`render` に渡すデータを dataclass で定義する。docs/design/data-integrity.md
「エージェント入力 — 信頼しない」の適用。

型を置く理由:
  素の dict を `.get()` で読むと、キー名を間違えても `None` が返り、`_e(None)` が
  空文字になって**何事もなかったように欠落したセクションが消える**。エージェントは
  成功したと判断してユーザーにパスを伝えるため、誰も気づけない。
  「必須キーが欠けたら警告する」ではなく、**必須という概念を型で持つ**ことで、
  組み立てた時点で不正を検出する。

url を持たない理由:
  PR の URL は repo と number から一意に決まるため、エージェントに渡させる必要がない。
  渡させると「何を入れてもよい」余地が生まれ、PR 本文由来の文字列が href に入りうる
  （javascript: が生存する）。導出にすれば、その経路自体が存在しなくなる。
"""

from dataclasses import dataclass, field

from . import scope

# PR の URL はこのホストから導出する。GitHub Enterprise が必要になったら
# config.toml に設定を足す（今は使わないので固定）。
GITHUB_HOST = "https://github.com"


class InvalidDocument(Exception):
    """解説データの形が想定と違う。期待する形を message に含める。"""


@dataclass
class Term:
    """用語解説1件。"""

    term: str
    definition: str
    status: str = "new"
    evidence: str = ""
    occurrences: int = 0


@dataclass
class PullRequest:
    """PR 1件の解説。

    必須は repo / number / title / priority の4つ。これらが欠けると
    「どの PR の話か」が読者に伝わらず、解説として成立しない。
    """

    repo: str
    number: int
    title: str
    priority: str
    language: str = "ja"
    author: str = ""
    counts: dict = field(default_factory=dict)
    summary: str = ""
    background: str = ""
    recommendation: str = ""
    changes: list = field(default_factory=list)
    review_points: list = field(default_factory=list)
    terms: list = field(default_factory=list)
    diagram: str = ""
    note: str = ""
    collapsed: bool = None  # None なら priority から決める

    @property
    def url(self):
        """GitHub 上の PR ページ。repo と number から導出する。"""
        return GITHUB_HOST + "/" + self.repo + "/pull/" + str(self.number)


@dataclass
class Document:
    """1回の実行で出す解説全体。"""

    prs: list = field(default_factory=list)
    language: str = "ja"
    title: str = ""
    generated_at: str = ""
    warnings: list = field(default_factory=list)


_PR_REQUIRED = ("repo", "number", "title", "priority")
_PR_OPTIONAL = (
    "language", "author", "counts", "summary", "background", "recommendation",
    "changes", "review_points", "terms", "diagram", "note", "collapsed",
)
_TERM_KEYS = ("term", "definition", "status", "evidence", "occurrences")

_EXPECTED = (
    '{"prs": [{"repo": "<owner/repo>", "number": <番号>, "title": "<タイトル>", '
    '"priority": "must_review|should_review|ignore", ...}]}'
)


def _term_from(raw, where):
    if not isinstance(raw, dict):
        raise InvalidDocument(where + ": 用語はオブジェクトである必要があります")
    term = raw.get("term")
    if not isinstance(term, str) or not term.strip():
        raise InvalidDocument(where + ": term が空か文字列ではありません")
    unknown = sorted(set(raw) - set(_TERM_KEYS))
    if unknown:
        raise InvalidDocument(
            where + ": 未知のキー " + ", ".join(unknown)
            + "（使えるキー: " + ", ".join(_TERM_KEYS) + "）"
        )
    return Term(
        term=term,
        definition=raw.get("definition") or "",
        status=raw.get("status") or "new",
        evidence=raw.get("evidence") or "",
        occurrences=raw.get("occurrences") or 0,
    )


def _pr_from(raw, index):
    where = "prs[" + str(index) + "]"
    if not isinstance(raw, dict):
        raise InvalidDocument(where + ": PR はオブジェクトである必要があります")

    missing = [k for k in _PR_REQUIRED if not raw.get(k) and raw.get(k) != 0]
    if missing:
        raise InvalidDocument(
            where + ": 必須のキーがありません: " + ", ".join(missing)
            + "（渡されたキー: " + (", ".join(sorted(map(str, raw))) or "なし") + "）。"
            "期待する形: " + _EXPECTED
        )

    # 未知のキーはタイポの可能性が高い。黙って捨てるとセクションが消える。
    unknown = sorted(set(raw) - set(_PR_REQUIRED) - set(_PR_OPTIONAL))
    if unknown:
        raise InvalidDocument(
            where + ": 未知のキー " + ", ".join(unknown)
            + "（使えるキー: " + ", ".join(_PR_REQUIRED + _PR_OPTIONAL) + "）"
        )

    priority = raw["priority"]
    if priority not in (scope.MUST, scope.SHOULD, scope.IGNORE):
        raise InvalidDocument(
            where + ": priority は " + " / ".join((scope.MUST, scope.SHOULD, scope.IGNORE))
            + " のいずれかです（実際: " + str(priority) + "）"
        )

    terms = [
        _term_from(t, where + ".terms[" + str(i) + "]")
        for i, t in enumerate(raw.get("terms") or [])
    ]

    return PullRequest(
        repo=str(raw["repo"]),
        number=raw["number"],
        title=str(raw["title"]),
        priority=priority,
        language=raw.get("language") or "ja",
        author=raw.get("author") or "",
        counts=raw.get("counts") or {},
        summary=raw.get("summary") or "",
        background=raw.get("background") or "",
        recommendation=raw.get("recommendation") or "",
        changes=list(raw.get("changes") or []),
        review_points=list(raw.get("review_points") or []),
        terms=terms,
        diagram=raw.get("diagram") or "",
        note=raw.get("note") or "",
        collapsed=raw.get("collapsed"),
    )


def from_payload(payload):
    """エージェントが組み立てた JSON を Document にする。

    不正なら InvalidDocument を投げる。黙って欠落させない。
    """
    if not isinstance(payload, dict):
        raise InvalidDocument(
            "入力の最上位はオブジェクトである必要があります。期待する形: " + _EXPECTED
        )
    if "prs" not in payload:
        raise InvalidDocument(
            "入力に prs キーがありません（実際のキー: "
            + (", ".join(sorted(map(str, payload))) or "なし")
            + "）。期待する形: " + _EXPECTED
        )
    raw_prs = payload["prs"]
    if not isinstance(raw_prs, list):
        raise InvalidDocument("prs は配列である必要があります。期待する形: " + _EXPECTED)

    prs = [_pr_from(raw, i) for i, raw in enumerate(raw_prs)]

    # ignore のみの PR は1行に畳む（第7節）。指定があればそれを尊重する。
    for pr in prs:
        if pr.collapsed is None:
            pr.collapsed = pr.priority == scope.IGNORE

    prs.sort(key=lambda p: scope.sort_key({"priority": p.priority}))

    return Document(
        prs=prs,
        language=payload.get("language") or "ja",
        title=payload.get("title") or "",
        generated_at=payload.get("generated_at") or "",
        warnings=list(payload.get("warnings") or []),
    )
