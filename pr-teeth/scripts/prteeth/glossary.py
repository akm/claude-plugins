"""ユーザー用語集（pr-teeth プラグイン）。

CONCEPTS.md 第8節の実装。

要点は「理解しているかどうかは出力言語に依存しない」こと。term / status / occurrences は
言語非依存でエントリごとに1つ持ち、definitions だけを言語ごとに持つ。これにより日本語で
積み上げた known が、英語で出力しても同じように効く。

昇格は new → learning のみ自動。learning → known は人の確認を経る（第8節）。
推定だけで自動確定すると、偽陽性で説明が勝手に消える事故になるため。
"""

NEW = "new"
LEARNING = "learning"
KNOWN = "known"

# new → learning に自動昇格する通算出現回数（第8節の例に合わせる）。
LEARNING_THRESHOLD = 3

# 初期 seed。「流通した英語」として説明を省く語（第1節・第8節）。
# 出力言語が何であっても原語のまま使い、説明しない。
SEED_TERMS = (
    "SSoT",
    "PoC",
    "CI",
    "CD",
    "PR",
    "diff",
    "API",
    "OSS",
    "URL",
    "HTML",
    "JSON",
    "YAML",
)


def empty():
    return {"version": 1, "terms": {}}


def load_or_seed(data):
    """用語集を正規化する。空なら seed 済みの初期状態を返す。"""
    if not isinstance(data, dict) or not data.get("terms"):
        g = empty()
        for t in SEED_TERMS:
            g["terms"][t] = {
                "term": t,
                "status": KNOWN,
                "definitions": {},
                "occurrences": 0,
                "seed": True,
            }
        return g
    data.setdefault("version", 1)
    data.setdefault("terms", {})
    return data


def get(glossary, term):
    return (glossary.get("terms") or {}).get(term)


def status_of(glossary, term):
    """未登録は new 扱い（初出はフル説明する）。"""
    entry = get(glossary, term)
    if not entry:
        return NEW
    return entry.get("status") or NEW


def definition_for(glossary, term, language):
    """その言語の説明文。無ければ None（呼び出し側が生成して record する）。"""
    entry = get(glossary, term)
    if not entry:
        return None
    defs = entry.get("definitions") or {}
    value = defs.get(language)
    if isinstance(value, str) and value.strip():
        return value
    return None

def other_language_definitions(glossary, term, language):
    """他言語の説明文。既存の定義を隠さず示すために使う（第8節・/pr-glossary）。"""
    entry = get(glossary, term)
    if not entry:
        return {}
    defs = entry.get("definitions") or {}
    return {k: v for k, v in defs.items() if k != language and isinstance(v, str) and v.strip()}


def record(glossary, term, language=None, definition=None, provenance=None, now=None):
    """語の出現を記録し、更新後のエントリを返す。

    - 未登録なら new として登録する。
    - occurrences を加算し、閾値を超えたら new → learning に自動昇格する。
    - definition が渡され、その言語の定義がまだ無ければ書き込む（次回から再利用）。
    - known は自動では触らない（降格は行わない。第8節）。
    """
    terms = glossary.setdefault("terms", {})
    entry = terms.get(term)
    if entry is None:
        entry = {
            "term": term,
            "status": NEW,
            "definitions": {},
            "occurrences": 0,
        }
        if provenance:
            entry["provenance"] = provenance
        if now:
            entry["first_seen"] = now
        terms[term] = entry

    entry["occurrences"] = int(entry.get("occurrences") or 0) + 1
    if now:
        entry["last_seen"] = now

    defs = entry.setdefault("definitions", {})
    if language and definition and not (defs.get(language) or "").strip():
        defs[language] = definition

    # 自動昇格は new → learning だけ。learning → known は人の確認が要る。
    if entry.get("status") == NEW and entry["occurrences"] >= LEARNING_THRESHOLD:
        entry["status"] = LEARNING

    return entry


def set_status(glossary, term, status, now=None):
    """ステータスを明示的に変更する（/pr-glossary からの確定操作）。

    これがユーザーの意思による最終的な真実。会話からの推定はここを呼ばない。
    """
    if status not in (NEW, LEARNING, KNOWN):
        raise ValueError("不正なステータスです: " + str(status))
    terms = glossary.setdefault("terms", {})
    entry = terms.get(term)
    if entry is None:
        entry = {"term": term, "definitions": {}, "occurrences": 0}
        terms[term] = entry
    entry["status"] = status
    if status == KNOWN and now:
        entry["known_since"] = now
    elif status != KNOWN:
        entry.pop("known_since", None)
    return entry


def needs_explanation(glossary, term):
    """説明が要るか。known なら不要（第8節: 説明挙動はステータス駆動）。"""
    return status_of(glossary, term) != KNOWN


def counts(glossary):
    out = {NEW: 0, LEARNING: 0, KNOWN: 0}
    for entry in (glossary.get("terms") or {}).values():
        s = entry.get("status") or NEW
        out[s] = out.get(s, 0) + 1
    return out
