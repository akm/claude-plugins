"""HTML の見出し・ラベルの言語別文言（pr-teeth プラグイン）。

CONCEPTS.md 第5.3節「解説本文・レビュー範囲サマリ・用語解説…はすべて解決された
出力言語で書く」に対応する。本文だけ翻訳しても、見出しが日本語のままでは英語話者に
読めない画面になるため、テンプレート側の固定文言もここで切り替える。

同梱するのは日本語と英語だけ。**未知の言語は英語にフォールバックする**（日本語に
倒すと、日本語を読めない利用者に読めない画面を出すことになるため）。
本文はモデルが任意の言語で書くので、見出しだけ英語になる状態は許容する。

文脈（CONTEXT_PATROL / CONTEXT_PICK）について:
  レビュー範囲の内部の値（must_review 等）は**どちらの文脈でも同じ**で、分類ロジックも
  共通。変えるのは表示だけにする。番号指定でマージ済み PR を読むときに「レビュー必須」と
  出るのは意味がずれる（レビューはもう終わっている）が、分類そのものは大きい PR で
  どこを読むべきかの手がかりとして有用なので、**読み方の指標として見せる**。
  内部の値まで分けると分類・並び替え・保存のすべてに文脈が波及するため、そうしない。
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

# 文脈。巡回（レビュー待ちの消化）と番号指定（読んで理解する）で、
# レビュー範囲の見せ方だけが変わる。
CONTEXT_PATROL = "patrol"
CONTEXT_PICK = "pick"

# 番号指定時に差し替える文言。**キーは _JA / _EN と同じ**で、値だけが違う。
# ここに無いキーは巡回時のものがそのまま使われる。
_PICK_JA = {
    "page_title": "指定した PR",
    "count_suffix": " 件",
    "no_prs": "対象の PR はありません。",
    "must_review": "重点",
    "should_review": "参考",
    "ignore": "周辺",
    "review_points": "読むときの手がかり",
}

_PICK_EN = {
    "page_title": "Selected pull requests",
    "count_suffix": " PRs",
    "no_prs": "No pull requests to show.",
    "must_review": "Focus",
    "should_review": "Context",
    "ignore": "Periphery",
    "review_points": "What to look at while reading",
}

_PICK_OVERRIDES = {"ja": _PICK_JA, "en": _PICK_EN}


def for_language(language, context=CONTEXT_PATROL):
    """言語タグに対応する文言表を返す。

    `ja-JP` のような地域付きタグも先頭で照合する。未知の言語は英語。

    context が CONTEXT_PICK なら、レビュー範囲まわりの文言を番号指定向けに
    差し替えた表を返す（内部の値は変えない。冒頭の説明を参照）。
    """
    tag = (language or "").strip().lower()
    primary = tag if tag in _TABLES else tag.split("-")[0]
    base = _TABLES.get(primary, _EN)
    if context != CONTEXT_PICK:
        return base
    # フォールバックした言語の上書き表を使う。base が _EN なら英語の上書き。
    key = primary if primary in _TABLES else "en"
    merged = dict(base)
    merged.update(_PICK_OVERRIDES[key])
    return merged
