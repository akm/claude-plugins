<!-- doc-structured:generated 生成元: docs/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->

# ロールと操作

<a name="r-librarian"></a>

## ロール「司書」 `librarian`

図書館の窓口で、貸出と返却を扱う職員。

<a name="r-member"></a>

## ロール「利用者」 `member`

図書館に登録し、自分で予約する人。

## 操作ごとの、行えるロール

| 操作 | ドメイン | [司書][r-librarian] | [利用者][r-member] |
|---|---|---|---|
| [貸し出す][d-loans-op-lend] | [`loans`][d-loans] | ○ | |
| [返却を受け付ける][d-loans-op-return_book] | [`loans`][d-loans] | ○ | |
| [延滞を通知する][d-loans-op-notify_overdue] | [`loans`][d-loans] | | |
| [予約する][d-loans-op-reserve] | [`loans`][d-loans] | ○ | ○ |
| [利用者を登録する][d-members-op-register] | [`members`][d-members] | ○ | |

[d-loans]: ../domains/02-loans/README.md#d-loans "ドメイン `loans`"
[d-loans-op-lend]: ../domains/02-loans/functions.md#d-loans-op-lend "ドメイン `loans` の操作「貸し出す」"
[d-loans-op-notify_overdue]: ../domains/02-loans/functions.md#d-loans-op-notify_overdue "ドメイン `loans` の操作「延滞を通知する」"
[d-loans-op-reserve]: ../domains/02-loans/functions.md#d-loans-op-reserve "ドメイン `loans` の操作「予約する」"
[d-loans-op-return_book]: ../domains/02-loans/functions.md#d-loans-op-return_book "ドメイン `loans` の操作「返却を受け付ける」"
[d-members]: ../domains/03-members/README.md#d-members "ドメイン `members`"
[d-members-op-register]: ../domains/03-members/functions.md#d-members-op-register "ドメイン `members` の操作「利用者を登録する」"
[r-librarian]: #r-librarian "ロール「司書」"
[r-member]: #r-member "ロール「利用者」"
