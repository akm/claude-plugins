# akm-claude-plugins

akm のチーム共有 Claude Code プラグイン集 (マーケットプレイス) です。

## 収録プラグイン

| プラグイン | 説明 |
| --- | --- |
| [commit-rules-guard](commit-rules-guard/README.md) | `git commit` の直前にコミットルールを想起させ、動機の混在を気づかせる |

## 使い方

```bash
claude plugin marketplace add https://github.com/akm/claude-plugins/blob/main/.claude-plugin/marketplace.json
claude plugin install commit-rules-guard
```

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
