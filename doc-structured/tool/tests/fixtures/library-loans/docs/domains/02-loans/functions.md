<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-functions"></a>

# ドメイン `loans` の操作・前提・イベント

<a name="d-loans-op-lend"></a>

## 操作「貸し出す」 `lend`

利用者に図書を貸し出し、貸出を作る。

- 対象: [モデル「貸出」][d-loans-m-loan]・[ドメイン `catalog` のモデル「図書」の属性「配架状態」][d-catalog-m-book-a-shelf_status]
- 前提: [前提「図書が配架中」][d-loans-pre-book_shelved]
- イベント: [イベント「図書を貸し出した」][d-loans-ev-book_lent]
- 行えるロール: [ロール「司書」][r-librarian]

<a name="d-loans-op-return_book"></a>

## 操作「返却を受け付ける」 `return_book`

返された図書を受け取り、貸出を返却済みにする。

- 対象: [モデル「貸出」の属性「貸出状態」][d-loans-m-loan-a-status]
- 前提: [前提「貸出が貸出中」][d-loans-pre-loan_on_loan]
- イベント: [イベント「図書が返却された」][d-loans-ev-book_returned]
- 行えるロール: [ロール「司書」][r-librarian]

<a name="d-loans-op-notify_overdue"></a>

## 操作「延滞を通知する」 `notify_overdue`

返却期限を過ぎた貸出の利用者に、毎朝まとめて知らせる。どのロールも行わず、アプリケーションが自分で行う。

- 対象: [モデル「貸出」][d-loans-m-loan]
- 行えるロール: 無し

<a name="d-loans-op-reserve"></a>

## 操作「予約する」 `reserve`

貸出中の図書を、返ったときに次に借りられるよう予約する。

- 対象: [モデル「予約」][d-loans-m-reservation]
- 前提: [前提「先の予約が無い」][d-loans-pre-no_previous_reservation]
- 行えるロール: [ロール「司書」][r-librarian]・[ロール「利用者」][r-member]

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

[d-catalog-m-book-a-shelf_status]: ../01-catalog/models.md#d-catalog-m-book-a-shelf_status "ドメイン `catalog` のモデル「図書」の属性「配架状態」"
[d-catalog-m-book-a-shelf_status-v-shelved]: ../01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-shelved "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」"
[d-loans-ev-book_lent]: #d-loans-ev-book_lent "ドメイン `loans` のイベント「図書を貸し出した」"
[d-loans-ev-book_returned]: #d-loans-ev-book_returned "ドメイン `loans` のイベント「図書が返却された」"
[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-status]: models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[d-loans-m-loan-a-status-v-on_loan]: models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-reservation]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-previous]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
[d-loans-pre-book_shelved]: #d-loans-pre-book_shelved "ドメイン `loans` の前提「図書が配架中」"
[d-loans-pre-loan_on_loan]: #d-loans-pre-loan_on_loan "ドメイン `loans` の前提「貸出が貸出中」"
[d-loans-pre-no_previous_reservation]: #d-loans-pre-no_previous_reservation "ドメイン `loans` の前提「先の予約が無い」"
[r-librarian]: ../../system/permissions.md#r-librarian "ロール「司書」"
[r-member]: ../../system/permissions.md#r-member "ロール「利用者」"
