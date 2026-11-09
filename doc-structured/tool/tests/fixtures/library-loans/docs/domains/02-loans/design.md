<a name="d-loans-design"></a>

# ドメイン `loans` の設計

<a name="d-loans-design-h-status_values"></a>

## 貸出状態を 2 つの値に限る

[属性「貸出状態」]の値は[貸出中]と[返却済み]の 2 つだけにする。延滞は状態にせず、[節「返却期限」]と今日の日付から求める。状態にすると、日付が変わるたびに書き換える処理が要るため。

延滞した貸出の通知は、子のファイル [`design/overdue_notice.md`] に書く。

[属性「貸出状態」]: models.md#d-loans-m-loan-a-status "ドメイン `loans` のモデル「貸出」の属性「貸出状態」"
[貸出中]: models.md#d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[返却済み]: models.md#d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"
[節「返却期限」]: concept.md#d-loans-concept-h-return_deadline "ドメイン `loans` のファイル `concept.md` の節「返却期限」"
[`design/overdue_notice.md`]: design/overdue_notice.md#d-loans-design-f-overdue_notice "ドメイン `loans` のファイル `design/overdue_notice.md`"
