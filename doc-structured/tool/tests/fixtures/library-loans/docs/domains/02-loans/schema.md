<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-schema"></a>

# ドメイン `loans` のスキーマ

```mermaid
erDiagram
  reservations {
    text id PK
    text book_id FK
    text previous_id FK
    text status
  }
  loans {
    text id PK
    text book_id FK
    text member_id FK
    text reservation_id FK, UK
    text status
    integer returned_at "未実装"
  }
  books {
    text id PK
  }
  members {
    text id PK
  }
  books ||--o{ reservations : book_id
  reservations |o--o{ reservations : previous_id
  books ||--o{ loans : book_id
  members ||--o{ loans : member_id
  reservations |o--o| loans : reservation_id
```

<a name="d-loans-t-reservations"></a>

## テーブル `reservations`

対応するモデル: [モデル「予約」][d-loans-m-reservation]

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 | 属性・定義 |
|---|---|---|---|---|---|
| <a name="d-loans-t-reservations-c-id"></a>`id` | `text` | | | | 予約を識別する値。 |
| <a name="d-loans-t-reservations-c-book_id"></a>`book_id` | `text` | | | [ドメイン `catalog` のテーブル `books` のカラム `id`][d-catalog-t-books-c-id] | [モデル「予約」の属性「予約図書」][d-loans-m-reservation-a-book] |
| <a name="d-loans-t-reservations-c-previous_id"></a>`previous_id` | `text` | 許可 | | [テーブル `reservations` のカラム `id`][d-loans-t-reservations-c-id] | [モデル「予約」の属性「前の予約」][d-loans-m-reservation-a-previous] |
| <a name="d-loans-t-reservations-c-status"></a>`status` | `text` | | `'waiting'` | | [モデル「予約」の属性「予約状態」][d-loans-m-reservation-a-status] |

<a name="d-loans-t-loans"></a>

## テーブル `loans`

対応するモデル: [モデル「貸出」][d-loans-m-loan]

主キー: `id`

| カラム | 型 | NULL | デフォルト値 | 参照先 | 属性・定義 |
|---|---|---|---|---|---|
| <a name="d-loans-t-loans-c-id"></a>`id` | `text` | | | | 貸出を識別する値。 |
| <a name="d-loans-t-loans-c-book_id"></a>`book_id` | `text` | | | [ドメイン `catalog` のテーブル `books` のカラム `id`][d-catalog-t-books-c-id] | [モデル「貸出」の属性「貸出図書」][d-loans-m-loan-a-book] |
| <a name="d-loans-t-loans-c-member_id"></a>`member_id` | `text` | | | [ドメイン `members` のテーブル `members` のカラム `id`][d-members-t-members-c-id] | [モデル「貸出」の属性「借りた利用者」][d-loans-m-loan-a-member] |
| <a name="d-loans-t-loans-c-reservation_id"></a>`reservation_id` | `text` | 許可 | | [テーブル `reservations` のカラム `id`][d-loans-t-reservations-c-id] | [モデル「貸出」の属性「元の予約」][d-loans-m-loan-a-reservation] |
| <a name="d-loans-t-loans-c-status"></a>`status` | `text` | | `'on_loan'` | | [モデル「貸出」の属性「貸出状態」][d-loans-m-loan-a-status] |
| <a name="d-loans-t-loans-c-returned_at"></a>`returned_at` (未実装) | `integer` | 許可 | | | 図書が返った時刻 (UNIX 時刻のミリ秒)。 |

インデックス:

- `member_id`
- `reservation_id` (一意)

[d-catalog-t-books-c-id]: ../01-catalog/schema.md#d-catalog-t-books-c-id "ドメイン `catalog` のテーブル `books` のカラム `id`"
[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-book]: models.md#d-loans-m-loan-a-book "ドメイン `loans` のモデル「貸出」の属性「貸出図書」"
[d-loans-m-loan-a-member]: models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"
[d-loans-m-loan-a-reservation]: models.md#d-loans-m-loan-a-reservation "ドメイン `loans` のモデル「貸出」の属性「元の予約」"
[d-loans-m-loan-a-status]: models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[d-loans-m-reservation]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-book]: models.md#d-loans-m-reservation-a-book "ドメイン `loans` のモデル「予約」の属性「予約図書」"
[d-loans-m-reservation-a-previous]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
[d-loans-m-reservation-a-status]: models.md#d-loans-m-reservation-a-status "ドメイン `loans` のモデル「予約」の属性「予約状態」"
[d-loans-t-reservations-c-id]: #d-loans-t-reservations-c-id "ドメイン `loans` のテーブル `reservations` のカラム `id`"
[d-members-t-members-c-id]: ../03-members/schema.md#d-members-t-members-c-id "ドメイン `members` のテーブル `members` のカラム `id`"
