<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-terms"></a>

# ドメイン `loans` の用語の索引

| 用語 | 種類 | 英語名 |
|---|---|---|
| [予約][d-loans-m-reservation] | モデル | `reservation` |
| [予約する][d-loans-op-reserve] | 操作 | `reserve` |
| [予約図書][d-loans-m-reservation-a-book] | モデル「予約」の属性 | `book` |
| [借りた利用者][d-loans-m-loan-a-member] | モデル「貸出」の属性 | `member` |
| [元の予約][d-loans-m-loan-a-reservation] | モデル「貸出」の属性 | `reservation` |
| [先の予約が無い][d-loans-pre-no_previous_reservation] | 前提 | `no_previous_reservation` |
| [前の予約][d-loans-m-reservation-a-previous] | モデル「予約」の属性 | `previous` |
| [図書が返却された][d-loans-ev-book_returned] | イベント | `book_returned` |
| [図書が配架中][d-loans-pre-book_shelved] | 前提 | `book_shelved` |
| [図書を貸し出した][d-loans-ev-book_lent] | イベント | `book_lent` |
| [延滞][d-loans-m-loan-a-status-v-overdue] | モデル「貸出」の属性「貸出状態」の値 | `overdue` |
| [延滞を通知する][d-loans-op-notify_overdue] | 操作 | `notify_overdue` |
| [貸し出す][d-loans-op-lend] | 操作 | `lend` |
| [貸出][d-loans-m-loan] | モデル | `loan` |
| [貸出が貸出中][d-loans-pre-loan_on_loan] | 前提 | `loan_on_loan` |
| [貸出中][d-loans-m-loan-a-status-v-on_loan] | モデル「貸出」の属性「貸出状態」の値 | `on_loan` |
| [貸出図書][d-loans-m-loan-a-book] | モデル「貸出」の属性 | `book` |
| [貸出状態][d-loans-m-loan-a-status] | モデル「貸出」の属性 | `status` |
| [返却を受け付ける][d-loans-op-return_book] | 操作 | `return_book` |
| [返却済み][d-loans-m-loan-a-status-v-returned] | モデル「貸出」の属性「貸出状態」の値 | `returned` |
| [開館日][d-loans-ut-business_day] | 未分類のアプリケーション用語 | `business_day` |

[d-loans-ev-book_lent]: functions.md#d-loans-ev-book_lent "ドメイン `loans` のイベント「図書を貸し出した」"
[d-loans-ev-book_returned]: functions.md#d-loans-ev-book_returned "ドメイン `loans` のイベント「図書が返却された」"
[d-loans-m-loan]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-book]: models.md#d-loans-m-loan-a-book "ドメイン `loans` のモデル「貸出」の属性「貸出図書」"
[d-loans-m-loan-a-member]: models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"
[d-loans-m-loan-a-reservation]: models.md#d-loans-m-loan-a-reservation "ドメイン `loans` のモデル「貸出」の属性「元の予約」"
[d-loans-m-loan-a-status]: models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[d-loans-m-loan-a-status-v-on_loan]: models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-loan-a-status-v-overdue]: models.md#d-loans-m-loan-a-status-v-overdue "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「延滞」"
[d-loans-m-loan-a-status-v-returned]: models.md#d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"
[d-loans-m-reservation]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-book]: models.md#d-loans-m-reservation-a-book "ドメイン `loans` のモデル「予約」の属性「予約図書」"
[d-loans-m-reservation-a-previous]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
[d-loans-op-lend]: functions.md#d-loans-op-lend "ドメイン `loans` の操作「貸し出す」"
[d-loans-op-notify_overdue]: functions.md#d-loans-op-notify_overdue "ドメイン `loans` の操作「延滞を通知する」"
[d-loans-op-reserve]: functions.md#d-loans-op-reserve "ドメイン `loans` の操作「予約する」"
[d-loans-op-return_book]: functions.md#d-loans-op-return_book "ドメイン `loans` の操作「返却を受け付ける」"
[d-loans-pre-book_shelved]: functions.md#d-loans-pre-book_shelved "ドメイン `loans` の前提「図書が配架中」"
[d-loans-pre-loan_on_loan]: functions.md#d-loans-pre-loan_on_loan "ドメイン `loans` の前提「貸出が貸出中」"
[d-loans-pre-no_previous_reservation]: functions.md#d-loans-pre-no_previous_reservation "ドメイン `loans` の前提「先の予約が無い」"
[d-loans-ut-business_day]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"
