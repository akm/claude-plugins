<!-- doc-structured:generated 生成元: docs/domains/01-catalog/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-catalog-models"></a>

# ドメイン `catalog` のモデル

<a name="d-catalog-m-book"></a>

## モデル「図書」 `book`

図書館が貸し出す 1 冊の本。

このモデルを参照するモデル: [ドメイン `loans` のモデル「貸出」][d-loans-m-loan]・[ドメイン `loans` のモデル「予約」][d-loans-m-reservation]

このモデルを参照するテーブル: [テーブル `books`][d-catalog-t-books]・[テーブル `book_categories`][d-catalog-t-book_categories] (属性「分類」を参照)

<a name="d-catalog-m-book-a-title"></a>

### 属性「書名」 `title`

図書の題名。

<a name="d-catalog-m-book-a-shelf_status"></a>

### 属性「配架状態」 `shelf_status`

図書が書架にあるか、除いたか。

<a name="d-catalog-m-book-a-shelf_status-v-shelved"></a>

#### 値「配架中」 `shelved`

書架にあり、貸し出せる。

<a name="d-catalog-m-book-a-shelf_status-v-withdrawn"></a>

#### 値「除籍」 `withdrawn`

蔵書から除き、貸し出さない。

<a name="d-catalog-m-book-a-categories"></a>

### 属性「分類」 `categories`

図書に付けた分類。1 冊に複数の分類を付けられる。参照先: [モデル「分類」][d-catalog-m-category]

<a name="d-catalog-m-category"></a>

## モデル「分類」 `category`

図書を主題で分ける区分。

このモデルを参照するモデル: [モデル「図書」][d-catalog-m-book]

このモデルを参照するテーブル: [テーブル `categories`][d-catalog-t-categories]

<a name="d-catalog-m-category-a-name"></a>

### 属性「分類名」 `name`

分類の名前。

[d-catalog-m-book]: #d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-catalog-m-category]: #d-catalog-m-category "ドメイン `catalog` のモデル「分類」"
[d-catalog-t-book_categories]: schema.md#d-catalog-t-book_categories "ドメイン `catalog` のテーブル `book_categories`"
[d-catalog-t-books]: schema.md#d-catalog-t-books "ドメイン `catalog` のテーブル `books`"
[d-catalog-t-categories]: schema.md#d-catalog-t-categories "ドメイン `catalog` のテーブル `categories`"
[d-loans-m-loan]: ../02-loans/models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-reservation]: ../02-loans/models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
