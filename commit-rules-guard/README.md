# commit-rules-guard

コミットルールを Claude Code に想起させるプラグインです。「複数の動機を一つのコミットに混ぜて
しまう」問題を、**事前の意識づけ**と**コミット直前のリマインダ**の two-stage で防ぎます。

| タイミング | フック | 役割 |
| --- | --- | --- |
| セッション開始・再開・`/clear`・コンテキスト圧縮後 | SessionStart | ルールの要点と「いつコミットするか」を注入 |
| ユーザーのプロンプト送信時 (未コミットの変更があるときのみ) | UserPromptSubmit | 着手前に未コミットの変更を提示 |
| `git commit` の直前 | PreToolUse | 一度だけ止め、ステージ内容と混在の疑いを提示 |

PreToolUse だけでは「コミットしようとした瞬間」にしか介入できません。しかし実際に問題になるのは
**そもそもコミットしようとしない**ことで、細かくコミットすべき段階で作業を続けた結果、最終的に
複数の動機が絡み合い、コミットされるべき変更が後続の変更に上書きされて失われます。これは事後には
取り返せないため、前 2 つのフックで事前に意識づけします。

## 事前の意識づけ (SessionStart / UserPromptSubmit)

どちらも **ブロックせず、コンテキストに情報を注入するだけ**です。

- **SessionStart**: ルールの要点を「行動指針」に翻訳して注入します。「動機ごとに分ける」だけでなく
  「一つの動機の作業が終わったら、次の動機に着手する前にコミットする。後からまとめて分割はできない」
  という因果まで示します。コンテキスト圧縮 (`compact`) 後にも再注入されるため、`CLAUDE.md` のような
  静的な設定では薄れてしまうタイミングを補えます。
- **UserPromptSubmit**: worktree に未コミットの変更があるときだけ、その一覧 (ステージ済み / 未ステージ /
  未追跡) を提示します。clean なときやリポジトリ外では何も注入しないため、通常のプロンプトには
  影響しません。「必ずコミットせよ」ではなく「着手する作業が別の動機なら先にコミットせよ」という
  判断材料の提示に留めています。

## コミット直前のリマインダ (PreToolUse)

Claude Code が `git commit` (新規コミット) を実行しようとすると、PreToolUse フックが一度だけ止め、
標準エラーに次を提示します。

- コミットルールの要点 (特に忘れやすい 3 点)。
- 今ステージされている変更の一覧 (`git diff --cached --name-status`)。
- 動機の混在の疑い (下記) を「気づきのヒント」として。

Claude は内容を確認し、動機が混在していれば分割してコミットし直します。分離不要と判断したら、
確認済みの合図として `--trailer 'Rules-Checked: yes'` を付けて再実行すると通過します
(マーカー方式)。

```bash
# 一度止められた後、確認して問題なければ:
git commit -m "..." --trailer 'Rules-Checked: yes'
```

混在の推定はブロック理由ではなく、あくまでヒントです。誤検知でも合図を付ければ必ず通るため、
正しいコミットを妨げません。

### 検知する混在パターン (汎用)

- 生成物 (`*.pb.go` / `go.sum` / `package-lock.json` / `Cargo.lock` / `poetry.lock` など各種
  ロックファイル・生成コード) と手書きの変更が同時にステージされている。
- ドキュメント (`docs/` 配下・`*.md` / `*.rst`) とコードが同時にステージされている。
- 改名・移動 (git status の `R`) と新規追加 (`A`) が同時にステージされている
  (リファクタと機能追加の混在の疑い)。

「レビューや linter の複数の指摘を一つにまとめてしまう」問題は機械検出が難しいため、ヒューリスティックでは
判定せず、リマインダ文言で必ず気づかせます。

## 導入

1. マーケットプレイスを登録する。

   ```bash
   claude plugin marketplace add https://github.com/akm/claude-plugins/blob/main/.claude-plugin/marketplace.json
   ```

2. プラグインをインストールする。

   ```bash
   claude plugin install commit-rules-guard
   ```

または `settings.json` に直接書く。

```json
{
  "extraKnownMarketplaces": [
    "https://github.com/akm/claude-plugins/blob/main/.claude-plugin/marketplace.json"
  ],
  "enabledPlugins": [
    "akm-claude-plugins:commit-rules-guard@0.2.0"
  ]
}
```

## 設定 (任意の環境変数)

いずれも未設定で動きます。

| 環境変数 | 既定 | 説明 |
| --- | --- | --- |
| `COMMIT_GUARD_GENERATED_GLOBS` | (なし) | 生成物とみなす追加パターンを `:` 区切りで指定。例: `*.pb.go:db/schema.sql:migrations/*` |
| `COMMIT_GUARD_RULES_FILE` | (下記の探索順) | 表示するルールファイルのパスを固定 |

ルールファイルの探索順: `COMMIT_GUARD_RULES_FILE` → `~/.claude/rules/commit-rules.md` →
プラグイン同梱の `rules/commit-rules.md`。

## プロジェクト固有ルール (config.json / 任意)

このプラグインは言語横断で普遍的な生成物パターンだけを本体で扱います。プロジェクト固有の生成物
(例: `db/schema.sql` は生成物だが `migrations/` は手書き、といった細かい区別) は、コミット対象
リポジトリのトップに置く設定ファイルで宣言できます。プラグイン本体 (ロジック) を一元管理したまま、
コードを足さずにプロジェクトごとの固有ルールを扱えます。

設定ファイルのパス (コミット対象リポジトリの git トップレベルからの相対):

```
.claude/akm-claude-plugins/commit-rules-guard/config.json
```

`<marketplace>/<plugin>/` の階層にすることで名前空間が衝突しません。リポジトリ内に PreToolUse
フックを別途置く必要はありません (フックの二重発火を避けられます)。

### スキーマ

```json
{
  "generated_globs": ["*.pb.go", "*_grpc.pb.go", "db/schema.sql"],
  "custom_rules": [
    {
      "id": "schema-migration-mix",
      "when_all_present": ["db/schema.sql", "migrations/*"],
      "message": "db/schema.sql (schema-dump の生成物) と migrations/ (手書き) が同時にステージされています。手書きのマイグレーションと生成物はコミットの動機を分けてください。"
    }
  ]
}
```

| キー | 説明 |
| --- | --- |
| `generated_globs` | 生成物とみなす追加パターンの配列。既定パターン + 環境変数 `COMMIT_GUARD_GENERATED_GLOBS` と合成される。 |
| `custom_rules[].id` | ルールの識別子 (任意。可読性のためのラベル)。 |
| `custom_rules[].when_all_present` | パターンの配列。列挙した各パターンが、ステージ内のいずれかのパスにマッチする。すべて満たされたら `message` をヒントに加える。 |
| `custom_rules[].message` | 上の条件が満たされたときにヒントとして表示する文言。 |

`when_all_present` の各パターンは、汎用の生成物パターンと同じマッチ規則で評価されます
(フルパス / ベース名 / `migrations/*` のようなディレクトリ prefix)。

設定ファイルが無い・JSON が壊れているときは、汎用パターンのみで動作します (本体は止まりません)。

## 前提

- `python3` が PATH にあること。
- Claude Code のプラグイン機構が使えるバージョンであること。

## 仕組みの注意

これらのフックは Claude Code の実行経路にのみ効きます。フックを読まない実行経路
(別ツール・手動の `git commit` など) では効きません。最終的な保証が要るコミット規約は、
CI など実行経路に依存しない仕組みで担保してください。

また、SessionStart / UserPromptSubmit の 2 つは**注入するだけで強制はしません**。
リマインドの有無にかかわらず判断するのは Claude であり、確実にコミットさせる仕組みではありません。
PreToolUse による最後の防衛線と組み合わせて使ってください。
