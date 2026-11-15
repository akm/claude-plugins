<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-functions"></a>

# ドメイン `loans` の操作・前提・イベント

<a name="d-loans-pre-book_shelved"></a>

## 前提「図書が配架中」 `book_shelved`

貸し出す図書が書架にある。

- 対象: [ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」][d-catalog-m-book-a-shelf_status-v-shelved]

<a name="d-loans-pre-loan_on_loan"></a>

## 前提「貸出が貸出中」 `loan_on_loan`

返す図書の貸出が、まだ返却されていない。

- 対象: [モデル「貸出」の属性「貸出状態」の値「貸出中」][d-loans-m-loan-a-status-v-on_loan]

<a name="d-loans-pre-no_previous_reservation"></a>

## 前提「先の予約が無い」 `no_previous_reservation`

同じ図書に、ほかの利用者の予約が無い。

- 対象: [モデル「予約」][d-loans-m-reservation]・[モデル「予約」の属性「前の予約」][d-loans-m-reservation-a-previous]

<a name="d-loans-ev-book_lent"></a>

## イベント「図書を貸し出した」 `book_lent`

図書が利用者の手元に移った。

<a name="d-loans-ev-book_returned"></a>

## イベント「図書が返却された」 `book_returned`

図書が図書館に戻った。

[d-catalog-m-book-a-shelf_status-v-shelved]: ../01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-shelved "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」"
[d-loans-m-loan-a-status-v-on_loan]: models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-reservation]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-previous]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
