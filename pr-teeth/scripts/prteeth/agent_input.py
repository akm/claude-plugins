"""エージェントが組み立てた JSON 入力の検証（pr-teeth プラグイン）。

docs/design/data-integrity.md「エージェント入力 — 信頼しない」の実装。

`--input` / `--state` の JSON はエージェントが毎回ゼロから組み立てる。人間が書く
設定ファイルより間違いが起きやすく、しかもエージェント側に間違いへ気づく手段がない。
そのため設定ファイル向けの「無ければ空」ではなく「無いなら間違っている」と扱う。

方針:
  - トップレベルの形が違う → InvalidInput で停止し、**期待する形を示す**。
    黙って0件処理して成功を返すと、エージェントは記録できたと信じてしまう。
  - 項目単位の不備 → その項目だけスキップし、受理件数とスキップ件数を返す。
    1件の不備で正常な項目まで巻き添えにするのは損失が大きすぎる。
"""


class InvalidInput(Exception):
    """入力全体の形が想定と違う。期待する形を message に含める。"""


def _describe(value):
    if isinstance(value, list):
        return "配列"
    if isinstance(value, dict):
        return "オブジェクト（キー: " + ", ".join(sorted(map(str, value))[:5]) + "）"
    return type(value).__name__


def terms(payload):
    """record --input を検証する。

    期待する形: {"terms": [{"term": ..., "language": ..., "definition": ...}, ...]}

    戻り値: (受理した項目のリスト, スキップの理由リスト)
    """
    expected = '{"terms": [{"term": "<語>", "language": "<言語タグ>", "definition": "<説明>"}]}'

    if not isinstance(payload, dict):
        raise InvalidInput(
            "入力の最上位はオブジェクトである必要があります（実際: "
            + _describe(payload) + "）。期待する形: " + expected
        )
    if "terms" not in payload:
        raise InvalidInput(
            "入力に terms キーがありません（実際のキー: "
            + (", ".join(sorted(map(str, payload))) or "なし")
            + "）。期待する形: " + expected
        )
    items = payload["terms"]
    if not isinstance(items, list):
        raise InvalidInput(
            "terms は配列である必要があります（実際: " + _describe(items) + "）。"
            "期待する形: " + expected
        )

    accepted, skipped = [], []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            skipped.append("terms[" + str(i) + "]: オブジェクトではありません（" + _describe(item) + "）")
            continue
        term = item.get("term")
        if not isinstance(term, str) or not term.strip():
            skipped.append(
                "terms[" + str(i) + "]: term が空か文字列ではありません"
                + ("（キー: " + ", ".join(sorted(map(str, item))) + "）" if item else "")
            )
            continue
        accepted.append(item)
    return accepted, skipped


def prs(payload):
    """select --input / record --state を検証する。

    期待する形: [{"repo": "<owner/repo>", "number": <番号>, "sha": ..., "updated_at": ...}, ...]
    （{"prs": [...]} でラップされていても受ける）

    戻り値: (受理した項目のリスト, スキップの理由リスト)
    """
    expected = '[{"repo": "<owner/repo>", "number": <番号>, "sha": "...", "updated_at": "..."}]'

    if isinstance(payload, dict):
        if "prs" not in payload:
            raise InvalidInput(
                "入力に prs キーがありません（実際のキー: "
                + (", ".join(sorted(map(str, payload))) or "なし")
                + "）。期待する形: " + expected
            )
        payload = payload["prs"]
    if not isinstance(payload, list):
        raise InvalidInput(
            "入力は配列である必要があります（実際: " + _describe(payload) + "）。"
            "期待する形: " + expected
        )

    accepted, skipped = [], []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            skipped.append("prs[" + str(i) + "]: オブジェクトではありません（" + _describe(item) + "）")
            continue
        repo, number = item.get("repo"), item.get("number")
        if not isinstance(repo, str) or not repo.strip():
            skipped.append("prs[" + str(i) + "]: repo が空か文字列ではありません")
            continue
        if number is None or isinstance(number, bool) or not isinstance(number, (int, str)):
            skipped.append("prs[" + str(i) + "]: number がありません")
            continue
        # sha も updated_at も無いと更新判定ができず、常に「変化なし」になってしまう。
        if not item.get("sha") and not item.get("updated_at"):
            skipped.append(
                "prs[" + str(i) + "] (" + repo + "#" + str(number) + "): "
                "sha と updated_at のどちらも無く、更新を判定できません"
            )
            continue
        accepted.append(item)
    return accepted, skipped
