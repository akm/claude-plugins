<!-- doc-structured:generated 生成元: docs/domains/01-catalog/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-catalog-models"></a>

# ドメイン `catalog` のモデル

<a name="d-catalog-m-book"></a>

## モデル「図書」 `book`

図書館が貸し出す 1 冊の本。

このモデルを参照するモデル: [ドメイン `loans` のモデル「貸出」][d-loans-m-loan]・[ドメイン `loans` のモデル「予約」][d-loans-m-reservation]

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

[d-loans-m-loan]: ../02-loans/models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-reservation]: ../02-loans/models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
