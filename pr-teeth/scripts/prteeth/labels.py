"""HTML の見出し・ラベルの言語別文言（pr-teeth プラグイン）。

CONCEPTS.md 第5.3節「解説本文・レビュー範囲サマリ・用語解説…はすべて解決された
出力言語で書く」に対応する。本文だけ翻訳しても、見出しが日本語のままでは英語話者に
読めない画面になるため、テンプレート側の固定文言もここで切り替える。

同梱するのは日本語と英語だけ。**未知の言語は英語にフォールバックする**（日本語に
倒すと、日本語を読めない利用者に読めない画面を出すことになるため）。
本文はモデルが任意の言語で書くので、見出しだけ英語になる状態は許容する。
"""

_JA = {
    "page_title": "レビュー依頼の PR",
    "count_suffix": " 件",
    "no_prs": "対象の PR はありません。",
    "warning": "注意",
    "summary": "概要",
    "background": "背景",
    "changes": "主な変更点",
    "review_points": "見るべき点",
    "terms": "用語",
    "evidence": "根拠",
    "no_definition": "（定義未登録）",
    "must_review": "必須",
    "should_review": "推奨",
    "ignore": "対象外",
    "glossary_title": "用語ポートフォリオ",
    "known": "理解済み",
    "learning": "学習中",
    "new": "新出",
    "terms_count": "語",
}

_EN = {
    "page_title": "Pull requests awaiting your review",
    "count_suffix": " PRs",
    "no_prs": "No pull requests to show.",
    "warning": "Note",
    "summary": "Summary",
    "background": "Background",
    "changes": "Main changes",
    "review_points": "What to look at",
    "terms": "Terms",
    "evidence": "Evidence",
    "no_definition": "(no definition yet)",
    "must_review": "Must review",
    "should_review": "Should review",
    "ignore": "Out of scope",
    "glossary_title": "Glossary portfolio",
    "known": "Known",
    "learning": "Learning",
    "new": "New",
    "terms_count": " terms",
}

_TABLES = {"ja": _JA, "en": _EN}


def for_language(language):
    """言語タグに対応する文言表を返す。

    `ja-JP` のような地域付きタグも先頭で照合する。未知の言語は英語。
    """
    tag = (language or "").strip().lower()
    if tag in _TABLES:
        return _TABLES[tag]
    primary = tag.split("-")[0]
    return _TABLES.get(primary, _EN)
