<!-- doc-structured:generated 生成元: migrations/*.sql コマンド: bin/doc-structured generate --all (このファイルを直接編集せず、生成元を直して生成し直す) -->

# 実際のスキーマ

マイグレーション `migrations/*.sql` を SQLite に適用したスキーマ。

```mermaid
erDiagram
  "book_categories" {
    TEXT book_id PK, FK
    TEXT category_id PK, FK
  }
  "books" {
    TEXT id PK
    TEXT title
    TEXT shelf_status
    TEXT call_number
    INTEGER created_at
  }
  "categories" {
    TEXT id PK
    TEXT name UK
  }
  "loans" {
    TEXT id PK
    TEXT book_id FK
    TEXT member_id FK
    TEXT reservation_id FK, UK
    TEXT status
  }
  "members" {
    TEXT id PK
    TEXT name
  }
  "reservations" {
    TEXT id PK
    TEXT book_id FK
    TEXT previous_id FK
    TEXT status
  }
  "books" ||--o{ "book_categories" : "book_id"
  "categories" ||--o{ "book_categories" : "category_id"
  "books" ||--o{ "loans" : "book_id"
  "members" ||--o{ "loans" : "member_id"
  "reservations" |o--o| "loans" : "reservation_id"
  "books" ||--o{ "reservations" : "book_id"
  "reservations" |o--o{ "reservations" : "previous_id"
```

## テーブル `book_categories`

主キー: `book_id`・`category_id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `book_id` | `TEXT` | | | `books`.`id` |
| `category_id` | `TEXT` | | | `categories`.`id` |

インデックス:

- `category_id`

## テーブル `books`

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `id` | `TEXT` | | | |
| `title` | `TEXT` | | | |
| `shelf_status` | `TEXT` | | `'shelved'` | |
| `call_number` | `TEXT` | | | |
| `created_at` | `INTEGER` | | | |

CHECK 制約:

- `shelf_status IN ('shelved', 'on_loan')`

## テーブル `categories`

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `id` | `TEXT` | | | |
| `name` | `TEXT` | | | |

インデックス:

- `name` (一意)

## テーブル `loans`

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `id` | `TEXT` | | | |
| `book_id` | `TEXT` | | | `books`.`id` |
| `member_id` | `TEXT` | | | `members`.`id` |
| `reservation_id` | `TEXT` | 許可 | | `reservations`.`id` |
| `status` | `TEXT` | | `'on_loan'` | |

インデックス:

- `member_id`
- `reservation_id` (一意。条件: `reservation_id IS NOT NULL`)

CHECK 制約:

- `status IN ('on_loan', 'returned')`

## テーブル `members`

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `id` | `TEXT` | | | |
| `name` | `TEXT` | | | |

## テーブル `reservations`

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 |
|---|---|---|---|---|
| `id` | `TEXT` | | | |
| `book_id` | `TEXT` | | | `books`.`id` |
| `previous_id` | `TEXT` | 許可 | | `reservations`.`id` |
| `status` | `TEXT` | | `'waiting'` | |
