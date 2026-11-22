<!-- doc-structured:generated 生成元: docs/domains/03-members/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-members-schema"></a>

# ドメイン `members` のスキーマ

```mermaid
erDiagram
  "members" {
    text id PK
    text name
  }
  "member_cards" {
    text id PK "未実装"
    text member_id FK "未実装"
  }
  "members" ||--o{ "member_cards" : "member_id"
```

<a name="d-members-t-members"></a>

## テーブル `members`

対応するモデル: [モデル「利用者」][d-members-m-member]

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 | 属性・定義 |
|---|---|---|---|---|---|
| <a name="d-members-t-members-c-id"></a>`id` | `text` | | | | 利用者を識別する値。 |
| <a name="d-members-t-members-c-name"></a>`name` | `text` | | | | [モデル「利用者」の属性「氏名」][d-members-m-member-a-name] |

<a name="d-members-t-member_cards"></a>

## テーブル `member_cards`

利用者に発行する利用者カード 1 枚の行。

未実装

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 | 属性・定義 |
|---|---|---|---|---|---|
| <a name="d-members-t-member_cards-c-id"></a>`id` | `text` | | | | 利用者カードを識別する値。 |
| <a name="d-members-t-member_cards-c-member_id"></a>`member_id` | `text` | | | [テーブル `members` のカラム `id`][d-members-t-members-c-id] | カードを持つ利用者。 |

インデックス:

- `member_id`

[d-members-m-member]: models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
[d-members-m-member-a-name]: models.md#d-members-m-member-a-name "ドメイン `members` のモデル「利用者」の属性「氏名」"
[d-members-t-members-c-id]: #d-members-t-members-c-id "ドメイン `members` のテーブル `members` のカラム `id`"
