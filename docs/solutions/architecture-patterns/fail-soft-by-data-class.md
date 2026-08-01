---
title: "データ種別ごとに失敗時の態度を変える"
date: 2026-08-01
module: pr-teeth
problem_type: architecture_pattern
category: architecture-patterns
component: tooling
severity: high
applies_when:
  - "利用者が書く設定と、実行を重ねて蓄積される状態を同じツールが扱う"
  - "LLM エージェントが構造化データを組み立てて渡す"
  - "呼び出し元が stderr を見る保証のない CLI"
tags:
  - fail-soft
  - data-integrity
  - error-handling
  - agent-input
---

## Context

`pr-teeth` の concept doc には、次の設計原則が明文化されている。

> 設定ファイルが無い場合はエラーにせず既定値で動く（初回実行を設定作業でブロックしない）

これは**設定ファイル**に関しては正しい判断だった。`config.toml` が存在しない、あるいは書きかけであっても、利用者が改めて数行書き直せば済むだけなので、初回実行をそこでブロックする理由がない。

問題は、この「fail-soft」という姿勢を、設定ファイル以外のあらゆるデータに対しても無差別に適用してしまったことにある。「ファイルが読めない／期待した形になっていないときは、空や既定値を返して処理を続ける」というコード上の型が、`glossary.json`（蓄積データ）にも、エージェントが組み立てる `--input` の JSON（実行時入力）にも、そのままコピーされた。その結果、性質の異なる3つの不具合が同じ根から生まれた。

1. **蓄積データが黙って上書きされた。** `store.load_json` は、ファイルが*存在しない*場合と*壊れている*場合の両方で `{}` を返していた。呼び出し側はこの2つを区別できず、破損した `glossary.json`（利用者が数ヶ月かけて蓄積した学習済み用語集）が、次の保存でシード分だけのデータに置き換わってしまった。再現手順は次の通り。14語登録された状態でファイルを破損させ、`promote` を実行すると13語になり、1語とその定義が完全に失われる。しかも `promote` は警告を一切出さなかった。
2. **エージェントが組み立てた入力が黙って無視された。** `for item in payload.get("terms") or []:` という書き方は、「キーが無ければ空扱い」という設定ファイル向けの慣用句である。LLM エージェントがトップレベルのキーを誤って `{"glossary": [...]}` のように組み立てた場合（正しくは `{"terms": [...]}`)、コマンドは登録件数0のまま警告も出さず終了コード0で終わった。件数の見た目はもっともらしく、エージェントは成功したと思い込んだ。
3. **1件の不正な要素がバッチ全体を破壊した。** `glossary.record()` は `term` の妥当性を検証しておらず、`None` がそのまま辞書のキーになっていた。保存時に `json.dump(..., sort_keys=True)` が `TypeError: '<' not supported between instances of 'NoneType' and 'str'` を送出する。保存はメモリ上に全項目を追加し終えた*後*に行われるため、`term` キーを欠いた要素が1つあるだけで、そのバッチに含まれる有効な用語すべてが失われた。再現手順は `[正常な項目, termキーが無い項目]` を入力すると終了コード1、`glossary.json` すら作成されない。

## Guidance

データは「間違っていたときに何が失われるか」で分類し、失敗時の振る舞いをその種類ごとに決める。

| 種別 | 例 | 失われるもの | 読めない/壊れているとき |
| --- | --- | --- | --- |
| 設定 | `config.toml` | 利用者が書いた数行 | 既定値で続行 + 警告 |
| 蓄積データ | `glossary.json` / `state.json` | 数ヶ月分の学習 | 保存を拒否して停止 |
| エージェント入力 | `--input` の JSON | その実行分 | 停止。項目単位の不備はスキップして件数を報告 |

この分類から、実装として以下の形が導かれた。

- `store.load_precious()` は、既定値を返す代わりに `Corrupt` 例外（パスと理由を持つ）を送出する。ただし「ファイルが存在しない」場合は正当な初回実行なので、引き続き既定値を返す。「存在しない」と「壊れている」を型レベルで区別する。
- 蓄積データを*書き込む*コマンド（`record`、`promote`）は、読み込みが `Corrupt` を送出した場合に保存を拒否し、利用者にバックアップまたは復旧を促す `hint` を返す。*読み込むだけ*のコマンド（`lookup`、`glossary-html`）は処理を継続してよいが、理由を必ず明示する。空の用語集を黙って表示すると「自分の学習が消えた」という体験になってしまうため。
- `agent_input` という単一モジュールを設け、エージェントが組み立てた JSON を検証する。全体の形が誤っていれば、期待する形をメッセージに明記して例外を送出する。個々の項目に問題がある場合はその項目だけをスキップし、理由を集約したうえで、受理件数とスキップ件数を返す。0件という結果自体が見える形にする。
- 採用したルール: **警告を計算したなら必ず返却に含める。集めて捨てるくらいなら集めない。** `cmd_promote` は `warnings` リストを計算していながら、それを出力に含めていなかった。

## Why This Matters

無差別な fail-soft は、本来*回復可能*な問題を*回復不能*な問題に変換してしまう。ディスク上のバイト列が壊れていること自体や、エージェントが JSON のキー名をタイプミスしたこと自体は、検知さえできれば簡単に直せる。しかし「読めなければ空/既定値を返す」という一律の振る舞いは、その検知の機会そのものを握りつぶす。破損ファイルは検知される前に上書きされ、キーの誤りは検知される前に「0件成功」という体裁を取って処理が完了してしまう。

さらに悪いのは、利用者に見える症状が原因を特定しにくい形で現れることだ。用語集から1語が消えても、利用者はそれが「破損ファイルを促進コマンドが上書きしたから」だとは気づかない。ただ「学習が消えた」としか感じられない。エージェント側から見ても、`promote` が終了コード0で件数を返している以上、失敗したとは認識できない。エラーメッセージが無いことが、原因追跡を不可能にしている。fail-soft は「エラーを出さない」ことと「エラーを隠す」ことを取り違えると、静かにデータを壊す仕組みに変わる。

## When to Apply

この教訓は `pr-teeth` に限らず、次の性質を持つツール一般に当てはまる。

- 利用者が書く**設定**と、実行を重ねて**蓄積**される状態（学習データ、キャッシュ、履歴など）を同じファイル群、あるいは同じロード関数で扱っているツール。両者は「間違っていたときに失われるものの重さ」が全く違うため、同じ関数・同じ既定値フォールバックで扱ってはいけない。
- LLM エージェントが構造化データ（JSON、YAML など）を**組み立てて渡す**箇所。エージェントは人間の利用者と違ってキー名の誤りに気づいて自己修正する保証がなく、「キーが無ければ空扱い」という寛容な読み取りは、エージェントの誤りをそのまま黙って握りつぶす。
- 呼び出し元（人間、CI、別のエージェント）が **stderr を見る保証のない CLI**。終了コードと標準出力の件数だけで成否を判断する呼び出し元に対しては、警告をログに出すだけでは不十分で、コマンドの返り値そのものに反映しなければ伝わらない。

## Examples

**エージェント入力: 検証なしの寛容な読み取り → 妥当性検証と件数報告**

Before（設定ファイル向けの慣用句をエージェント入力にも流用してしまっていた）:

```python
for item in payload.get("terms") or []:
    glossary.record(item["term"], item["definition"])
```

`payload` のトップレベルキーが `terms` でなく `glossary` だった場合、`payload.get("terms")` は `None` になり `or []` で空リストに落ち、ループは1度も実行されない。呼び出し元には登録0件という結果だけが残り、警告は出ない。

After:

```python
def terms(payload):
    """戻り値: (受理した項目のリスト, スキップの理由リスト)"""
    expected = '{"terms": [{"term": "<語>", "language": "...", "definition": "..."}]}'
    if "terms" not in payload:
        raise InvalidInput(
            "入力に terms キーがありません（実際のキー: "
            + (", ".join(sorted(map(str, payload))) or "なし")
            + "）。期待する形: " + expected
        )
    accepted, skipped = [], []
    for i, item in enumerate(payload["terms"]):
        term = item.get("term") if isinstance(item, dict) else None
        if not isinstance(term, str) or not term.strip():
            skipped.append("terms[" + str(i) + "]: term が空か文字列ではありません")
            continue
        accepted.append(item)
    return accepted, skipped
```

呼び出し元は `accepted` と `skipped` の件数を必ず受け取るため、0件成功が黙って通ることがなくなる。

**蓄積データ: 破損と未存在を区別しないロード → `Corrupt` を送出するロード**

Before:

```python
def load_json(path, default, warnings=None):
    text = _read_text(path)          # 読めなければ None
    if text is None or not text.strip():
        return default
    try:
        return json.loads(text)
    except ValueError as e:
        if warnings is not None:
            warnings.append(path + " を読めませんでした。既定値で続行します。")
        return default               # ← 壊れていても既定値が返る
```

ファイルが無い場合と壊れている場合の両方で `{}` が返るため、`promote` はどちらのケースでもシード分だけの新しい `glossary.json` を保存してしまい、既存の14語のうち13語が消えても検知できない。

After:

```python
class Corrupt(Exception):
    """蓄積データが壊れていて読めない。「無い」と区別するための型。"""

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__(path + " を読めません（" + reason + "）")


def load_precious(path, default):
    text = _read_text(path)
    if text is None or not text.strip():
        return default               # 無い/空は正当な初回実行
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Corrupt(path, "JSON として不正: " + str(e))
    if not isinstance(data, dict):
        raise Corrupt(path, "最上位がオブジェクトではありません")
    return data
```

書き込み系コマンドは `Corrupt` を捕捉して保存を拒否し、`hint` で復旧手順を案内する。読み取り専用コマンドは処理を続けてよいが、理由を必ず出力に含める。
