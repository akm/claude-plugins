<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-dependencies"></a>

# ドメイン `loans` の依存

| 依存先のドメイン | 参照する定義 | キー | 参照先 |
|---|---|---|---|
| [`catalog`][d-catalog] | [モデル「貸出」の属性「貸出図書」][d-loans-m-loan-a-book] | `refers_to` | [ドメイン `catalog` のモデル「図書」][d-catalog-m-book] |
| [`catalog`][d-catalog] | [モデル「予約」の属性「予約図書」][d-loans-m-reservation-a-book] | `refers_to` | [ドメイン `catalog` のモデル「図書」][d-catalog-m-book] |
| [`catalog`][d-catalog] | [操作「貸し出す」][d-loans-op-lend] | `targets` | [ドメイン `catalog` のモデル「図書」の属性「配架状態」][d-catalog-m-book-a-shelf_status] |
| [`catalog`][d-catalog] | [前提「図書が配架中」][d-loans-pre-book_shelved] | `targets` | [ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」][d-catalog-m-book-a-shelf_status-v-shelved] |
| [`catalog`][d-catalog] | [テーブル `reservations` のカラム `book_id`][d-loans-t-reservations-c-book_id] | `references` | [ドメイン `catalog` のテーブル `books` のカラム `id`][d-catalog-t-books-c-id] |
| [`catalog`][d-catalog] | [テーブル `loans` のカラム `book_id`][d-loans-t-loans-c-book_id] | `references` | [ドメイン `catalog` のテーブル `books` のカラム `id`][d-catalog-t-books-c-id] |
| [`members`][d-members] | [モデル「貸出」の属性「借りた利用者」][d-loans-m-loan-a-member] | `refers_to` | [ドメイン `members` のモデル「利用者」][d-members-m-member] |
| [`members`][d-members] | [テーブル `loans` のカラム `member_id`][d-loans-t-loans-c-member_id] | `references` | [ドメイン `members` のテーブル `members` のカラム `id`][d-members-t-members-c-id] |

[d-catalog]: ../01-catalog/README.md#d-catalog "ドメイン `catalog`"
[d-catalog-m-book]: ../01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-catalog-m-book-a-shelf_status]: ../01-catalog/models.md#d-catalog-m-book-a-shelf_status "ドメイン `catalog` のモデル「図書」の属性「配架状態」"
[d-catalog-m-book-a-shelf_status-v-shelved]: ../01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-shelved "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」"
[d-catalog-t-books-c-id]: ../01-catalog/schema.md#d-catalog-t-books-c-id "ドメイン `catalog` のテーブル `books` のカラム `id`"
[d-loans-m-loan-a-book]: models.md#d-loans-m-loan-a-book "ドメイン `loans` のモデル「貸出」の属性「貸出図書」"
[d-loans-m-loan-a-member]: models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"
[d-loans-m-reservation-a-book]: models.md#d-loans-m-reservation-a-book "ドメイン `loans` のモデル「予約」の属性「予約図書」"
[d-loans-op-lend]: functions.md#d-loans-op-lend "ドメイン `loans` の操作「貸し出す」"
[d-loans-pre-book_shelved]: functions.md#d-loans-pre-book_shelved "ドメイン `loans` の前提「図書が配架中」"
[d-loans-t-loans-c-book_id]: schema.md#d-loans-t-loans-c-book_id "ドメイン `loans` のテーブル `loans` のカラム `book_id`"
[d-loans-t-loans-c-member_id]: schema.md#d-loans-t-loans-c-member_id "ドメイン `loans` のテーブル `loans` のカラム `member_id`"
[d-loans-t-reservations-c-book_id]: schema.md#d-loans-t-reservations-c-book_id "ドメイン `loans` のテーブル `reservations` のカラム `book_id`"
[d-members]: ../03-members/README.md#d-members "ドメイン `members`"
[d-members-m-member]: ../03-members/models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
[d-members-t-members-c-id]: ../03-members/schema.md#d-members-t-members-c-id "ドメイン `members` のテーブル `members` のカラム `id`"
