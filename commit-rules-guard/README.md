# commit-rules-guard

`git commit` の直前にコミットルールを想起させる Claude Code プラグインです。長い作業の後に
「複数の動機を一つのコミットに混ぜてしまう」問題を、コミットの瞬間のリマインダで防ぎます。

## 何をするか

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
    "akm-claude-plugins:commit-rules-guard@0.1.0"
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

### プロジェクト固有パターンの注入

このプラグインは言語横断で普遍的な生成物パターンだけを扱います。プロジェクト固有の生成物
(例: `db/schema.sql` は生成物だが `migrations/` は手書き、といった細かい区別) は、
プラグインでは再現しきれません。そうした固有の検知が要るプロジェクトでは、リポジトリ内の
PreToolUse フック (`.claude/hooks/`) を併用してください。

## 前提

- `python3` が PATH にあること。
- Claude Code のプラグイン機構が使えるバージョンであること。

## 仕組みの注意

このフックは Claude Code が Bash を実行する経路にのみ効きます。`CLAUDE.md` やフックを読まない
実行経路 (headless・cron・別ツール) では効きません。最終的な保証が要るコミット規約は、
CI など実行経路に依存しない仕組みで担保してください。
