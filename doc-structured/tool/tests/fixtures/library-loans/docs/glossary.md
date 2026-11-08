<!-- doc-structured:generated 生成元: docs/domains/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->

# 用語の索引

| 用語 | 種類 | 英語名 | ドメイン |
|---|---|---|---|
| [予約][d-loans-m-reservation] | モデル | `reservation` | [`loans`][d-loans] |
| [予約図書][d-loans-m-reservation-a-book] | モデル「予約」の属性 | `book` | [`loans`][d-loans] |
| [借りた利用者][d-loans-m-loan-a-member] | モデル「貸出」の属性 | `member` | [`loans`][d-loans] |
| [元の予約][d-loans-m-loan-a-reservation] | モデル「貸出」の属性 | `reservation` | [`loans`][d-loans] |
| [利用者][d-members-m-member] | モデル | `member` | [`members`][d-members] |
| [前の予約][d-loans-m-reservation-a-previous] | モデル「予約」の属性 | `previous` | [`loans`][d-loans] |
| [図書][d-catalog-m-book] | モデル | `book` | [`catalog`][d-catalog] |
| [書名][d-catalog-m-book-a-title] | モデル「図書」の属性 | `title` | [`catalog`][d-catalog] |
| [氏名][d-members-m-member-a-name] | モデル「利用者」の属性 | `name` | [`members`][d-members] |
| [請求記号][d-catalog-ut-call_number] | 未分類のアプリケーション用語 | `call_number` | [`catalog`][d-catalog] |
| [貸出][d-loans-m-loan] | モデル | `loan` | [`loans`][d-loans] |
| [貸出中][d-loans-m-loan-a-status-v-on_loan] | モデル「貸出」の属性「貸出状態」の値 | `on_loan` | [`loans`][d-loans] |
| [貸出図書][d-loans-m-loan-a-book] | モデル「貸出」の属性 | `book` | [`loans`][d-loans] |
| [貸出状態][d-loans-m-loan-a-status] | モデル「貸出」の属性 | `status` | [`loans`][d-loans] |
| [返却済み][d-loans-m-loan-a-status-v-returned] | モデル「貸出」の属性「貸出状態」の値 | `returned` | [`loans`][d-loans] |
| [配架中][d-catalog-m-book-a-shelf_status-v-shelved] | モデル「図書」の属性「配架状態」の値 | `shelved` | [`catalog`][d-catalog] |
| [配架状態][d-catalog-m-book-a-shelf_status] | モデル「図書」の属性 | `shelf_status` | [`catalog`][d-catalog] |
| [開館日][d-loans-ut-business_day] | 未分類のアプリケーション用語 | `business_day` | [`loans`][d-loans] |
| [除籍][d-catalog-m-book-a-shelf_status-v-withdrawn] | モデル「図書」の属性「配架状態」の値 | `withdrawn` | [`catalog`][d-catalog] |

[d-catalog]: domains/01-catalog/README.md#d-catalog "ドメイン `catalog`"
[d-catalog-m-book]: domains/01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-catalog-m-book-a-shelf_status]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status "ドメイン `catalog` のモデル「図書」の属性「配架状態」"
[d-catalog-m-book-a-shelf_status-v-shelved]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-shelved "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「配架中」"
[d-catalog-m-book-a-shelf_status-v-withdrawn]: domains/01-catalog/models.md#d-catalog-m-book-a-shelf_status-v-withdrawn "ドメイン `catalog` のモデル「図書」の属性「配架状態」の値「除籍」"
[d-catalog-m-book-a-title]: domains/01-catalog/models.md#d-catalog-m-book-a-title "ドメイン `catalog` のモデル「図書」の属性「書名」"
[d-catalog-ut-call_number]: domains/01-catalog/unclassified_app_terms.md#d-catalog-ut-call_number "ドメイン `catalog` の未分類のアプリケーション用語「請求記号」"
[d-loans]: domains/02-loans/README.md#d-loans "ドメイン `loans`"
[d-loans-m-loan]: domains/02-loans/models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-book]: domains/02-loans/models.md#d-loans-m-loan-a-book "ドメイン `loans` のモデル「貸出」の属性「貸出図書」"
[d-loans-m-loan-a-member]: domains/02-loans/models.md#d-loans-m-loan-a-member "ドメイン `loans` のモデル「貸出」の属性「借りた利用者」"
[d-loans-m-loan-a-reservation]: domains/02-loans/models.md#d-loans-m-loan-a-reservation "ドメイン `loans` のモデル「貸出」の属性「元の予約」"
[d-loans-m-loan-a-status]: domains/02-loans/models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[d-loans-m-loan-a-status-v-on_loan]: domains/02-loans/models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-loan-a-status-v-returned]: domains/02-loans/models.md#d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"
[d-loans-m-reservation]: domains/02-loans/models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-m-reservation-a-book]: domains/02-loans/models.md#d-loans-m-reservation-a-book "ドメイン `loans` のモデル「予約」の属性「予約図書」"
[d-loans-m-reservation-a-previous]: domains/02-loans/models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
[d-loans-ut-business_day]: domains/02-loans/unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"
[d-members]: domains/03-members/README.md#d-members "ドメイン `members`"
[d-members-m-member]: domains/03-members/models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
[d-members-m-member-a-name]: domains/03-members/models.md#d-members-m-member-a-name "ドメイン `members` のモデル「利用者」の属性「氏名」"
