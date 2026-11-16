<!-- doc-structured:generated 生成元: docs/domains/ コマンド: bin/doc-structured generate (このファイルを直接編集せず、生成元を直して生成し直す) -->

# ドメインの読む順

ドメインの依存の表と図は [`dependencies.md`][dependencies.md] にある。

| 順 | ドメイン | 説明 |
|---|---|---|
| 1 | [`01-catalog`][d-catalog] | 図書館が持つ図書と、その目録を扱う。 |
| 2 | [`03-members`][d-members] | 図書館に登録した利用者を扱う。 |
| 3 | [`02-loans`][d-loans] | 図書の貸出と返却を扱う。 |

[d-catalog]: 01-catalog/README.md#d-catalog "ドメイン `catalog`"
[d-loans]: 02-loans/README.md#d-loans "ドメイン `loans`"
[d-members]: 03-members/README.md#d-members "ドメイン `members`"
[dependencies.md]: dependencies.md "ドメインの依存"
