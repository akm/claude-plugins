<a name="d-loans-concept"></a>

# ドメイン `loans` の概念

[モデル「貸出」]は、利用者が図書を借りてから返すまでを 1 回として記録する。借りるものは[ドメイン `catalog` のモデル「図書」]で、借りる人は[利用者][d-members-m-member]である。

<a name="d-loans-concept-h-return_deadline"></a>

## 返却期限

返却期限は、貸出の日から 14 日後の[開館日]とする。期限を過ぎた貸出の扱いは[延滞の通知][d-loans-design-f-overdue_notice]に書く。

<a name="d-loans-concept-h-reservation_order"></a>

## 予約の順番

同じ図書の[予約]は[属性「前の予約」]でつなぎ、先に予約した利用者から借りる。

[モデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[ドメイン `catalog` のモデル「図書」]: ../01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-members-m-member]: ../03-members/models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"
[d-loans-design-f-overdue_notice]: design/overdue_notice.md#d-loans-design-f-overdue_notice "ドメイン `loans` のファイル `design/overdue_notice.md`"
[予約]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[属性「前の予約」]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「予約」の属性「前の予約」"
