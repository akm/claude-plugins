<!-- doc-structured:generated 生成元: docs/domains/02-loans/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->
<a name="d-loans-models"></a>

# ドメイン `loans` のモデル

<a name="d-loans-m-loan"></a>

## モデル「貸出」 `loan`

利用者が図書を借りてから返すまでの 1 回の記録。

<a name="d-loans-m-loan-a-book"></a>

### 属性「貸出図書」 `book`

貸し出した図書。参照先: [ドメイン `catalog` のモデル「図書」][d-catalog-m-book]

<a name="d-loans-m-loan-a-member"></a>

### 属性「借りた利用者」 `member`

図書を借りた利用者。参照先: [ドメイン `members` のモデル「利用者」][d-members-m-member]

<a name="d-loans-m-loan-a-reservation"></a>

### 属性「元の予約」 `reservation`

この貸出のもとになった予約。予約せずに借りたときは無い。参照先: [モデル「予約」][d-loans-m-reservation]

<a name="d-loans-m-loan-a-status"></a>

### 属性「貸出状態」 `status`

貸出が今どの段階にあるか。

状態の遷移 (最初の状態: [値「貸出中」][d-loans-m-loan-a-status-v-on_loan]):

| 前の状態 | 後の状態 | 操作 | 前提 |
|---|---|---|---|
| [貸出中][d-loans-m-loan-a-status-v-on_loan] | [延滞][d-loans-m-loan-a-status-v-overdue] | [延滞を通知する][d-loans-op-notify_overdue] | |
| [貸出中][d-loans-m-loan-a-status-v-on_loan]・[延滞][d-loans-m-loan-a-status-v-overdue] | [返却済み][d-loans-m-loan-a-status-v-returned] | [返却を受け付ける][d-loans-op-return_book] | |

```mermaid
stateDiagram-v2
  state "貸出中" as v_on_loan
  state "延滞" as v_overdue
  state "返却済み" as v_returned
  [*] --> v_on_loan
  v_on_loan --> v_overdue : 延滞を通知する
  v_on_loan --> v_returned : 返却を受け付ける
  v_overdue --> v_returned : 返却を受け付ける
```

<a name="d-loans-m-loan-a-status-v-on_loan"></a>

#### 値「貸出中」 `on_loan`

図書が利用者の手元にある。

<a name="d-loans-m-loan-a-status-v-overdue"></a>

#### 値「延滞」 `overdue`

返却期限を過ぎても、図書が利用者の手元にある。

<a name="d-loans-m-loan-a-status-v-returned"></a>

#### 値「返却済み」 `returned`

図書が図書館に戻った。

<a name="d-loans-m-reservation"></a>

## モデル「予約」 `reservation`

貸出中の図書が返ったときに、次に借りる権利を取っておく記録。

このモデルを参照するモデル: [モデル「貸出」][d-loans-m-loan]・[モデル「予約」][d-loans-m-reservation]

<a name="d-loans-m-reservation-a-book"></a>

### 属性「予約図書」 `book`

予約した図書。参照先: [ドメイン `catalog` のモデル「図書」][d-catalog-m-book]

<a name="d-loans-m-reservation-a-previous"></a>

### 属性「前の予約」 `previous`

同じ図書について、この予約の 1 つ前の予約。参照先: [モデル「予約」][d-loans-m-reservation]

[d-catalog-m-book]: ../01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"
[d-loans-m-loan]: #d-loans-m-loan "ドメイン `loans` のモデル「貸出」"
[d-loans-m-loan-a-status-v-on_loan]: #d-loans-m-loan-a-status-v-on_loan "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"
[d-loans-m-loan-a-status-v-overdue]: #d-loans-m-loan-a-status-v-overdue "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「延滞」"
[d-loans-m-loan-a-status-v-returned]: #d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"
[d-loans-m-reservation]: #d-loans-m-reservation "ドメイン `loans` のモデル「予約」"
[d-loans-op-notify_overdue]: functions.md#d-loans-op-notify_overdue "ドメイン `loans` の操作「延滞を通知する」"
[d-loans-op-return_book]: functions.md#d-loans-op-return_book "ドメイン `loans` の操作「返却を受け付ける」"
[d-members-m-member]: ../03-members/models.md#d-members-m-member "ドメイン `members` のモデル「利用者」"
