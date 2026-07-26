# akm-claude-plugins

akm のチーム共有 Claude Code プラグイン集 (マーケットプレイス) です。

## 収録プラグイン

| プラグイン | 説明 |
| --- | --- |
| [commit-rules-guard](commit-rules-guard/README.md) | `git commit` の直前にコミットルールを想起させ、動機の混在を気づかせる |

## 使い方

### user レベルでインストールする

自分の環境全体で使う場合は、以下のコマンドでインストールします。

```bash
claude plugin marketplace add https://github.com/akm/claude-plugins/blob/main/.claude-plugin/marketplace.json
claude plugin install commit-rules-guard
```

### リポジトリに明示的に設定する

特定のリポジトリで利用するプラグインを設定として明示し、チームで共有したい場合は、プロジェクトの `.claude/settings.json` にマーケットプレイスの登録とプラグインの有効化を記述します。

```json
{
  "extraKnownMarketplaces": {
    "akm-claude-plugins": {
      "source": {
        "source": "github",
        "repo": "akm/claude-plugins"
      }
    }
  },
  "enabledPlugins": ["commit-rules-guard@akm-claude-plugins"]
}
```

- `extraKnownMarketplaces` はマーケットプレイス名をキーとするオブジェクトで、値の `source` にマーケットプレイスの取得元を指定します。
- `enabledPlugins` は有効化するプラグインの配列で、`プラグイン名@マーケットプレイス名` の形式で指定します。

`.claude/settings.json` は git 管理下に置くとチーム全体で共有されます。一方、自分だけで有効化したい場合や個人的にオーバーライドしたい場合は、同じ内容を `.claude/settings.local.json` に記述することもできます。`.claude/settings.local.json` は通常 gitignore され、`.claude/settings.json` よりも優先されます。

### 最新版に更新する

このリポジトリの `main` に PR がマージされてプラグインが更新された場合、手元には自動では反映されません。以下の手順で最新を取り込みます。

```bash
claude plugin marketplace update akm-claude-plugins
claude plugin update commit-rules-guard
```

- 1 行目でマーケットプレイス定義 (収録プラグインの一覧) を取得元から取り直します。マーケットプレイス名を省略すると、登録済みのすべてのマーケットプレイスが更新されます。
- 2 行目で個々のプラグイン本体を最新に更新します。

`marketplace update` だけではプラグイン本体は更新されないため、両方を実行してください。

**更新後は Claude Code の再起動が必要です。** 再起動するまで、実行中のセッションには更新内容が反映されません。

`.claude/settings.json` の `enabledPlugins` で有効化している場合も、プラグイン本体の取得は同じ仕組みのため、更新手順は同様です。設定ファイルに書いてあるだけでは最新版が自動で使われるわけではない点に注意してください。

なお、収録プラグインは `main` ブランチを参照する設定 (`marketplace.json` の `ref`) のため、更新するとマージ済みの最新の内容が取り込まれます。

各プラグインの詳細は上表のリンク先 README を参照してください。

## 構成

```
.
├── .claude-plugin/
│   └── marketplace.json          # マーケットプレイス定義 (収録プラグインの一覧)
└── commit-rules-guard/           # プラグイン本体
    ├── .claude-plugin/plugin.json
    ├── hooks/hooks.json
    ├── hook-scripts/guard-commit-rules.py
    ├── rules/commit-rules.md      # 同梱の既定ルール
    └── README.md
```
