# akm-claude-plugins

akm のチーム共有 Claude Code プラグイン集 (マーケットプレイス) です。

## 収録プラグイン

| プラグイン | 説明 |
| --- | --- |
| [commit-rules-guard](commit-rules-guard/README.md) | コミットルールを想起させ、動機の混在を気づかせる (セッション開始時・作業着手時・計画作成時・`git commit` 直前) |
| [pr-teeth](pr-teeth/README.md) | レビュー依頼が来ている GitHub の PR を巡回し、レビュー範囲に照らして噛み砕いた解説を HTML で作る (出力言語は設定可能) |

## 使い方

### user レベルでインストールする

自分の環境全体で使う場合は、以下のコマンドでインストールします。

```bash
claude plugin marketplace add akm/claude-plugins
claude plugin install commit-rules-guard
```

`marketplace add` はリポジトリを clone するため、`owner/repo` 形式か clone 可能な URL (`https://….git` / `git@…`) を指定します。GitHub のブラウザ用の閲覧 URL (`https://github.com/…/blob/…/marketplace.json`) は clone できないため使えません。

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
  "enabledPlugins": {
    "commit-rules-guard@akm-claude-plugins": true
  }
}
```

- `extraKnownMarketplaces` はマーケットプレイス名をキーとするオブジェクトで、値の `source` にマーケットプレイスの取得元を指定します。
- `enabledPlugins` は `プラグイン名@マーケットプレイス名` をキー、有効/無効を表す真偽値を値とするオブジェクトです。

`settings.json` の詳しい説明については [公式ドキュメント](https://code.claude.com/docs/en/settings#plugin-settings) を参照してください。

`.claude/settings.json` は git 管理下に置くとチーム全体で共有されます。一方、自分だけで有効化したい場合や個人的にオーバーライドしたい場合は、同じ内容を `.claude/settings.local.json` に記述することもできます。`.claude/settings.local.json` は通常 gitignore され、`.claude/settings.json` よりも優先されます。

### 最新版に更新する

このリポジトリの `main` に PR がマージされてプラグインが更新された場合、手元には自動では反映されません。以下の手順で最新を取り込みます。

**1. インストール先のスコープを確認する**

更新コマンドはスコープを取り違えると失敗するため、先に現状を確認します。

```bash
claude plugin list
```

```
❯ commit-rules-guard@akm-claude-plugins
  Version: 0.1.0
  Scope: project        ← このスコープを次の手順で使う
```

**2. マーケットプレイス定義を更新する**

```bash
claude plugin marketplace update akm-claude-plugins
```

マーケットプレイス定義 (収録プラグインの一覧) を取得元から取り直します。マーケットプレイス名を省略すると、登録済みのすべてのマーケットプレイスが更新されます。

**3. プラグイン本体を更新する**

`marketplace update` だけではプラグイン本体は更新されないため、続けて実行します。**プラグイン名は `プラグイン名@マーケットプレイス名` の形式で指定してください。** 短い名前 (`commit-rules-guard`) だけでは解決できず `Plugin "..." not found` になります。

user スコープ (既定) の場合:

```bash
claude plugin update commit-rules-guard@akm-claude-plugins
```

project / local スコープの場合は、**`--scope` の指定と、そのプロジェクトのディレクトリでの実行**が必要です。`plugin update` の既定は user スコープのため、指定しないと `not installed at scope user` になります。

```bash
claude plugin update commit-rules-guard@akm-claude-plugins --scope project
```

**更新後は Claude Code の再起動が必要です。** 再起動するまで、実行中のセッションには更新内容が反映されません。

`.claude/settings.json` の `enabledPlugins` で有効化している場合も、プラグイン本体の取得は同じ仕組みのため、更新手順は同様です。設定ファイルに書いてあるだけでは最新版が自動で使われるわけではない点に注意してください。

なお、収録プラグインは `main` ブランチを参照する設定 (`marketplace.json` の `ref`) のため、更新するとマージ済みの最新の内容が取り込まれます。

各プラグインの詳細は上表のリンク先 README を参照してください。

## 構成

```
.
├── .claude-plugin/
│   └── marketplace.json          # マーケットプレイス定義 (収録プラグインの一覧)
├── commit-rules-guard/           # プラグイン本体 (フック)
│   ├── .claude-plugin/plugin.json
│   ├── hooks/hooks.json
│   ├── hook-scripts/              # 各フックの本体 (4 本)
│   ├── rules/commit-rules.md      # 同梱の既定ルール
│   ├── tests/                     # python3 -m unittest discover -s commit-rules-guard/tests
│   └── README.md
└── pr-teeth/                     # プラグイン本体 (skill)
    ├── .claude-plugin/plugin.json
    ├── skills/pr-teeth/SKILL.md
    ├── skills/pr-glossary/SKILL.md
    ├── scripts/                   # 判定・保存・HTML 生成
    ├── tests/                     # python3 -m unittest discover -s pr-teeth/tests
    ├── CONCEPTS.md                # 設計
    └── README.md
```
