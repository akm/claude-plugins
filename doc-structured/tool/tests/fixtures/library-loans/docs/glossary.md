<!-- doc-structured:generated 生成元: docs/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->

# 用語の索引

| 用語 | 種類 | 英語名 | ドメイン |
|---|---|---|---|
| [予約][d-loans-m-reservation] | モデル | `reservation` | [`loans`][d-loans] |
| [予約する][d-loans-op-reserve] | 操作 | `reserve` | [`loans`][d-loans] |
| [予約の順番が先頭][d-loans-pre-first_in_line] | 前提 | `first_in_line` | [`loans`][d-loans] |
| [予約を取り消す][d-loans-op-cancel_reservation] | 操作 | `cancel_reservation` | [`loans`][d-loans] |
| [予約図書][d-loans-m-reservation-a-book] | モデル「予約」の属性 | `book` | [`loans`][d-loans] |
| [予約状態][d-loans-m-reservation-a-status] | モデル「予約」の属性 | `status` | [`loans`][d-loans] |
| [借りた利用者][d-loans-m-loan-a-member] | モデル「貸出」の属性 | `member` | [`loans`][d-loans] |
| [元の予約][d-loans-m-loan-a-reservation] | モデル「貸出」の属性 | `reservation` | [`loans`][d-loans] |
| [先の予約が無い][d-loans-pre-no_previous_reservation] | 前提 | `no_previous_reservation` | [`loans`][d-loans] |
| [利用者][d-members-m-member] | モデル | `member` | [`members`][d-members] |
| [利用者][r-member] | ロール | `member` | |
| [利用者を登録する][d-members-op-register] | 操作 | `register` | [`members`][d-members] |
| [前の予約][d-loans-m-reservation-a-previous] | モデル「予約」の属性 | `previous` | [`loans`][d-loans] |
| [取り置きの期限を過ぎた][d-loans-pre-hold_expired] | 前提 | `hold_expired` | [`loans`][d-loans] |
| [取り置き中][d-loans-m-reservation-a-status-v-on_hold] | モデル「予約」の属性「予約状態」の値 | `on_hold` | [`loans`][d-loans] |
| [取消][d-loans-m-reservation-a-status-v-cancelled] | モデル「予約」の属性「予約状態」の値 | `cancelled` | [`loans`][d-loans] |
| [司書][r-librarian] | ロール | `librarian` | |
| [図書][d-catalog-m-book] | モデル | `book` | [`catalog`][d-catalog] |
| [図書が返却された][d-loans-ev-book_returned] | イベント | `book_returned` | [`loans`][d-loans] |
| [図書が配架中][d-loans-pre-book_shelved] | 前提 | `book_shelved` | [`loans`][d-loans] |
| [図書を貸し出した][d-loans-ev-book_lent] | イベント | `book_lent` | [`loans`][d-loans] |
| [延滞][d-loans-m-loan-a-status-v-overdue] | モデル「貸出」の属性「貸出状態」の値 | `overdue` | [`loans`][d-loans] |
| [延滞を通知する][d-loans-op-notify_overdue] | 操作 | `notify_overdue` | [`loans`][d-loans] |
| [書名][d-catalog-m-book-a-title] | モデル「図書」の属性 | `title` | [`catalog`][d-catalog] |
| [氏名][d-members-m-member-a-name] | モデル「利用者」の属性 | `name` | [`members`][d-members] |
| [請求記号][d-catalog-ut-call_number] | 未分類のアプリケーション用語 | `call_number` | [`catalog`][d-catalog] |
| [貸し出す][d-loans-op-lend] | 操作 | `lend` | [`loans`][d-loans] |
| [貸出][d-loans-m-loan] | モデル | `loan` | [`loans`][d-loans] |
| [貸出が貸出中][d-loans-pre-loan_on_loan] | 前提 | `loan_on_loan` | [`loans`][d-loans] |
| [貸出中][d-loans-m-loan-a-status-v-on_loan] | モデル「貸出」の属性「貸出状態」の値 | `on_loan` | [`loans`][d-loans] |
| [貸出図書][d-loans-m-loan-a-book] | モデル「貸出」の属性 | `book` | [`loans`][d-loans] |
| [貸出済み][d-loans-m-reservation-a-status-v-fulfilled] | モデル「予約」の属性「予約状態」の値 | `fulfilled` | [`loans`][d-loans] |
| [貸出状態][d-loans-m-loan-a-status] | モデル「貸出」の属性 | `status` | [`loans`][d-loans] |
| [返却を受け付ける][d-loans-op-return_book] | 操作 | `return_book` | [`loans`][d-loans] |
| [返却済み][d-loans-m-loan-a-status-v-returned] | モデル「貸出」の属性「貸出状態」の値 | `returned` | [`loans`][d-loans] |
| [配架中][d-catalog-m-book-a-shelf_status-v-shelved] | モデル「図書」の属性「配架状態」の値 | `shelved` | [`catalog`][d-catalog] |
| [配架状態][d-catalog-m-book-a-shelf_status] | モデル「図書」の属性 | `shelf_status` | [`catalog`][d-catalog] |
| [開館日][d-loans-ut-business_day] | 未分類のアプリケーション用語 | `business_day` | [`loans`][d-loans] |
| [除籍][d-catalog-m-book-a-shelf_status-v-withdrawn] | モデル「図書」の属性「配架状態」の値 | `withdrawn` | [`catalog`][d-catalog] |
| [順番待ち][d-loans-m-reservation-a-status-v-waiting] | モデル「予約」の属性「予約状態」の値 | `waiting` | [`loans`][d-loans] |

[d-catalog]: domains/01-catalog/README.md#d-catalog "ドメイン `catalog`"
[d-catalog-m-book]: domains/01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-catalog-m-book-a-shelf_status]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status "ドメイン `catalog` のモデル「図書」の属性「配架状態」"
[d-catalog-m-book-a-shelf_status-v-shelved]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-shelved "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」"
[d-catalog-m-book-a-shelf_status-v-withdrawn]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-withdrawn "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「除籍」"
[d-catalog-m-book-a-title]: domains/01-catalog/models.md#d-catalog-m-book-a-title "ドメイン `catalog` のモデル「図書」の属性「書名」"
[d-catalog-ut-call_number]: domains/01-catalog/unclassified_app_terms.md#d-catalog-ut-call_number "ドメイン `catalog` の未分類のアプリケーション用語「請求記号」"
[d-loans]: domains/02-loans/README.md#d-loans "ドメイン `loans`"
[d-loans-ev-book_lent]: domains/02-loans/functions.md#d-loans-ev-book_lent "ドメイン `loans` のイベント「図書を貸し出した」"
[d-loans-ev-book_returned]: domains/02-loans/functions.md#d-loans-ev-book_returned "ドメイン `loans` のイベント「図書が返却された」"
[d-loans-m-loan]: domains/02-loans/models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-book]: domains/02-loans/models.md#d-loans-m-loan-a-book "ドメイン `loans` のモデル「貸出」の属性「貸出図書」"
[d-loans-m-loan-a-member]: domains/02-loans/models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"
[d-loans-m-loan-a-reservation]: domains/02-loans/models.md#d-loans-m-loan-a-reservation "ドメイン `loans` のモデル「貸出」の属性「元の予約」"
[d-loans-m-loan-a-status]: domains/02-loans/models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[d-loans-m-loan-a-status-v-on_loan]: domains/02-loans/models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-loan-a-status-v-overdue]: domains/02-loans/models.md#d-loans-m-loan-a-status-v-overdue "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「延滞」"
[d-loans-m-loan-a-status-v-returned]: domains/02-loans/models.md#d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"
[d-loans-m-reservation]: domains/02-loans/models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-book]: domains/02-loans/models.md#d-loans-m-reservation-a-book "ドメイン `loans` のモデル「予約」の属性「予約図書」"
[d-loans-m-reservation-a-previous]: domains/02-loans/models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
[d-loans-m-reservation-a-status]: domains/02-loans/models.md#d-loans-m-reservation-a-status "ドメイン `loans` のモデル「予約」の属性「予約状態」"
[d-loans-m-reservation-a-status-v-cancelled]: domains/02-loans/models.md#d-loans-m-reservation-a-status-v-cancelled "ドメイン `loans` のモデル「予約」の属性「予約状態」の値「取消」"
[d-loans-m-reservation-a-status-v-fulfilled]: domains/02-loans/models.md#d-loans-m-reservation-a-status-v-fulfilled "ドメイン `loans` のモデル「予約」の属性「予約状態」の値「貸出済み」"
[d-loans-m-reservation-a-status-v-on_hold]: domains/02-loans/models.md#d-loans-m-reservation-a-status-v-on_hold "ドメイン `loans` のモデル「予約」の属性「予約状態」の値「取り置き中」"
[d-loans-m-reservation-a-status-v-waiting]: domains/02-loans/models.md#d-loans-m-reservation-a-status-v-waiting "ドメイン `loans` のモデル「予約」の属性「予約状態」の値「順番待ち」"
[d-loans-op-cancel_reservation]: domains/02-loans/functions.md#d-loans-op-cancel_reservation "ドメイン `loans` の操作「予約を取り消す」"
[d-loans-op-lend]: domains/02-loans/functions.md#d-loans-op-lend "ドメイン `loans` の操作「貸し出す」"
[d-loans-op-notify_overdue]: domains/02-loans/functions.md#d-loans-op-notify_overdue "ドメイン `loans` の操作「延滞を通知する」"
[d-loans-op-reserve]: domains/02-loans/functions.md#d-loans-op-reserve "ドメイン `loans` の操作「予約する」"
[d-loans-op-return_book]: domains/02-loans/functions.md#d-loans-op-return_book "ドメイン `loans` の操作「返却を受け付ける」"
[d-loans-pre-book_shelved]: domains/02-loans/functions.md#d-loans-pre-book_shelved "ドメイン `loans` の前提「図書が配架中」"
[d-loans-pre-first_in_line]: domains/02-loans/functions.md#d-loans-pre-first_in_line "ドメイン `loans` の前提「予約の順番が先頭」"
[d-loans-pre-hold_expired]: domains/02-loans/functions.md#d-loans-pre-hold_expired "ドメイン `loans` の前提「取り置きの期限を過ぎた」"
[d-loans-pre-loan_on_loan]: domains/02-loans/functions.md#d-loans-pre-loan_on_loan "ドメイン `loans` の前提「貸出が貸出中」"
[d-loans-pre-no_previous_reservation]: domains/02-loans/functions.md#d-loans-pre-no_previous_reservation "ドメイン `loans` の前提「先の予約が無い」"
[d-loans-ut-business_day]: domains/02-loans/unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"
[d-members]: domains/03-members/README.md#d-members "ドメイン `members`"
[d-members-m-member]: domains/03-members/models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
[d-members-m-member-a-name]: domains/03-members/models.md#d-members-m-member-a-name "ドメイン `members` のモデル「利用者」の属性「氏名」"
[d-members-op-register]: domains/03-members/functions.md#d-members-op-register "ドメイン `members` の操作「利用者を登録する」"
[r-librarian]: system/permissions.md#r-librarian "ロール「司書」"
[r-member]: system/permissions.md#r-member "ロール「利用者」"
