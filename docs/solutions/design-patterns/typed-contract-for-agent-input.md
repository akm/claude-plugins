---
title: "LLM が組み立てる入力は型で縛る"
date: 2026-08-01
module: pr-teeth
problem_type: design_pattern
category: design-patterns
component: tooling
severity: high
applies_when:
  - "CLI や API のペイロードを LLM がプロンプトから組み立てる"
  - "dict.get() と None 許容のフォーマッタが同居している"
  - "他のフィールドから導出できる値を入力として受け取っている"
tags:
  - typed-contract
  - dataclass
  - validation
  - agent-input
  - silent-failure
---

## Context

`pr-teeth` は Claude Code のプラグインで、CLI サブコマンド `render` が JSON ペイロードを受け取り、GitHub の PR に関する HTML レポートを生成する。このペイロードは人間が書くのではなく、LLM エージェントが `SKILL.md` のプロース（自然文の指示）だけを頼りにゼロから組み立てる。

実装は受け取った JSON をただの `dict` として `.get()` で読んでいた。

```python
out.append('<div class="meta">' + _e(pr.get("repo")) + " #" + _e(pr.get("number")))
```

`_e()` は HTML エスケープ用のヘルパーで、`None` を `""` に変換する。つまりキー名を一つ間違えるだけで、**エラーにならず空文字列が出力される**。PR オブジェクトには読み取り可能なキーが 17 個あったが、`SKILL.md` に明記されていたのはそのごく一部だった。

**実際に再現した失敗。** エージェントがもっともらしいが誤ったキー名を渡すケース（`repo` のつもりで `repository`、`number` のつもりで `pr_number`、`summary` のつもりで `body`、`changes` のつもりで `main_changes`）を再現すると、

- 出力された本文: `認証のリファクタ推奨 #` — タイトルだけが生き残り、他はすべて静かに消えた
- CLI の結果: `exit=0`、`warnings: []` — 成功時と見分けがつかない
- エージェントはこの後、生成されたファイルパスを「うまくいった」ものとしてユーザーに報告する

ここで重要だったのはフレーミングだった。最初に出た案は「必須キーが欠けていたら警告する」だった。ユーザーはこれを退けた。「**必須キーが欠ける、ということがデータ構造上起きないようにした方が良い**」——検出ではなく構造的に不可能にすべきだ、と。正しい診断は「欠落キーが検出されていない」ではなく、**「実装に *必須* という概念がそもそも存在しない」**ことだった。

## Guidance

必須性を「チェック」ではなく「構造」にする。具体的なルールは次の通り。

- **必須フィールドは dataclass の位置引数にする。** `repo`、`number`、`title`、`priority` のような必須項目は、オブジェクトを構築する時点で渡さなければ構築自体が失敗するようにする。欠けている場合は、欠けているフィールド名・実際に渡されたキー・期待する形の 3 点セットを含めて例外を送出する。
- **未知のキーはエラーにする。** これがタイポ検出器になる。`main_changes` というキーは、それを黙って無視することが「セクションが消える」原因そのものだったので、無視ではなく例外にすることで検出可能になる。
- **enum 的なフィールドは値も検証する。**（例: `priority` は決められた3値のいずれかでなければならない）
- **導出可能な値は受け取らず `@property` にする。** 呼び出し元が入力できない値は、間違えようがない。
- **falsy だが有効な値に注意する。** `number=0` は Python の真偽値評価では偽になるが、有効な値である。必須チェックのロジックが `if not value` のような書き方をしていると、`0` を「欠落」と誤判定してしまう。`is None` や「キーが存在するか」で判定する必要がある。
- **ドキュメントの参照先が実在するか確認する。** `SKILL.md` が「入力 JSON の形は `render --help` を参照」と書いていたのに、`--help` 側は「解説データ JSON」としか説明していなかった。17個のキーを持つスキーマに対してこれは行き止まりのドキュメントだった。プロースが `--help` を指し、`--help` が何も指していない、という組み合わせ自体を防ぐ。

## Why This Matters

読み手が寛容（permissive）であることと、呼び出し元が人間ではないことが組み合わさると、間違った出力が成功として報告され、誰にも気づかれない。人間なら空欄だらけのレポートを見て違和感に気づくかもしれないが、エージェントはそのまま「できました」とファイルパスを報告して終わる。

対比するとわかりやすい。**クラッシュは回復可能** である——目に見えるので、その場で入力を直せる。**静かな劣化は回復不可能** である——exit=0 で警告もなければ、何かがおかしいと気づく手がかりが存在しない。今回のケースでは、失敗の証拠は「タイトルの後に半角スペースと `#` だけが残る」という非常に地味な見た目の差でしかなかった。

セキュリティの観点も同じ根から生えている。`url` キーをそのまま `href="..."` に埋め込んでいた設計は、`html.escape` が属性からの脱出（クォート）は防ぐが、**スキームまでは検証しない** ことを見落としていた。`javascript:fetch(...)` のような値はそのまま生き残り、クリック時に実行される。ここでの教訓は「スキームをバリデートせよ」ではなく、**受け付けない入力は攻撃されようがない**、ということ。`url` は `repo` と `number` から機械的に導出できる（`https://github.com/{repo}/pull/{number}`）ので、入力として受け取ること自体をやめれば、注入経路そのものが消える。バリデーションより導出の方が強い。

## When to Apply

- ペイロードが LLM によって、プロースの指示だけを頼りに一から組み立てられる CLI・API 全般。
- `.get()`（または同等の欠損許容アクセサ）と、`None` を許容するフォーマッタ・エスケープ関数が同じコードパスで出会っている場所。
- ある値が他のフィールドから機械的に導出できるにもかかわらず、外部からの入力として受け取っている箇所（例: URL、合計値、ステータスの表示ラベルなど）。

なお、ここで守れるのは**ペイロードの形**までである。フィールドの中身が正しい対象を指しているかは型検証では分からない。ペイロードのフィールド自体を非構造テキスト（貼り付けた URL など）から取り出している場合は、その抽出段に別の手当てが要る → [extract-identifiers-in-code-not-llm.md](extract-identifiers-in-code-not-llm.md)

## Examples

**Before: `.get()` で読む dict — 誤字が静かに握りつぶされる**

```python
def render_pr(pr: dict) -> str:
    out = []
    out.append('<div class="meta">' + _e(pr.get("repo")) + " #" + _e(pr.get("number")))
    out.append('<a href="' + _e(pr.get("url")) + '">link</a>')
    out.append(_e(pr.get("summary")))
    return "".join(out)

# 呼び出し側が repository / pr_number / body という誤ったキーを渡しても
# 例外は起きず、"認証のリファクタ推奨 #" のような欠損だらけの HTML が
# exit=0, warnings=[] で返る。
```

**After: dataclass + `from_payload` — 必須性と未知キーを構造で縛る**

```python
from dataclasses import dataclass, field

GITHUB_HOST = "https://github.com"

_PR_REQUIRED = ("repo", "number", "title", "priority")
_PR_OPTIONAL = ("language", "author", "counts", "summary", "changes", ...)


@dataclass
class PullRequest:
    repo: str
    number: int
    title: str
    priority: str            # must_review / should_review / ignore
    language: str = "ja"
    summary: str = ""
    changes: list = field(default_factory=list)

    @property
    def url(self):
        """GitHub 上の PR ページ。repo と number から導出する。"""
        return GITHUB_HOST + "/" + self.repo + "/pull/" + str(self.number)


def _pr_from(raw, index):
    where = "prs[" + str(index) + "]"

    # 0 は falsy だが有効な番号。required 判定で誤って弾かない。
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

    if raw["priority"] not in (MUST, SHOULD, IGNORE):
        raise InvalidDocument(where + ": priority が不正です")

    return PullRequest(repo=str(raw["repo"]), number=raw["number"], ...)
```

同じ誤ったペイロード（`body` / `main_changes` / `pr_number` / `repository`）を渡すと、今度は次のように失敗し、原因がその場でわかる。

```
prs[0]: 必須のキーがありません: repo, number, priority（渡されたキー: body,
main_changes, pr_number, repository, title）。期待する形: {"prs": [{"repo":
"<owner/repo>", "number": <番号>, "title": "<タイトル>", "priority":
"must_review|should_review|ignore", ...}]}
```

`url` を渡そうとした場合も、未知キーとして弾かれる。

```
prs[0]: 未知のキー url（使えるキー: repo, number, title, priority, language, ...）
```

`url` についても、受け取っていたキーを削除し `@property` に置き換えたことで、`javascript:` のような値を持つ `url` フィールドをそもそも渡せなくなり、`href` に不正なスキームが混入する経路自体がなくなった。
