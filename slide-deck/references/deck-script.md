# 資料ごとのスクリプトの書き方

資料ごとのスクリプト (資料のディレクトリのファイル `deck.ts`) の書き方。スキル `build` が、構成案の図の説明 (`- 図:` の行) から書く。部品の関数の引数・オプション・デフォルト値の SSOT (single source of truth。ある事実を定めている唯一の記述) は、ファイル [src/data/parts.ts](../src/data/parts.ts) の型とコメント、テーマの SSOT はファイル [src/data/theme.ts](../src/data/theme.ts)。この文書は、書くときの規則と、どの関数を使うかを示す。

この文書で使う語:

- **部品の関数**: 資料ごとのスクリプトが図を作るのに使う関数 (`box`・`text`・`arrow` など)。資料ごとのスクリプトは、引数で受け取る。
- **テーマの色の名前**: テーマの 12 色の名前 (`dk1`・`lt1`・`dk2`・`lt2`・`accent1`〜`accent6`・`hlink`・`folHlink`)。図形と文字の色は、色の値ではなく、この名前で指定する。

## 資料ごとのスクリプトが書くもの

- **書く**: テーマ (色とフォント) と、キーごとの図。
- **書かない**: 題名・一言・発表者ノート。構成案から読み、ツールが決まった位置の文字の箱に入れる。資料ごとのスクリプトに書く手段は無い (部品の関数の集まりに、題名と一言の関数は無い)。
- **書けない**: 表・画像・グラフ。PowerPoint と Google スライドの両方に同じ形で書き出せる要素 (下の部品の関数が作る図形・線・文字) だけを使う。

## 形

```ts
import type { DeckScript, Theme } from "slide-deck";

const theme: Theme = { /* 下の節「テーマ」 */ };

const deck: DeckScript = (p) => {
  const readPath = p.slide("read-path");
  p.box(readPath, 0.5, 2.0, 2.2, 1.2, "アプリケーション", { fill: "accent1", color: "lt1", bold: true });
  // ...
  return { theme, slides: [readPath /* , ... */] };
};

export default deck;
```

- 型 `DeckScript` の関数を default export する。関数は、部品の関数の集まり `p` を受け取り、テーマとキーごとの図の配列を返す。
- 図は `p.slide("<キー>")` で作り、ほかの部品の関数で要素を足す。キーは構成案のスライドの見出しのキーと同じにし、構成案のすべてのキーの図を 1 回ずつ作る。配列の順序はスライドの順序に影響しない (順序は構成案で決まる)。
- 名前 `slide-deck` からは、`import type` で型だけを読み込む。実行時にプラグインのモジュールを import しない。名前 `slide-deck` は、サブコマンド `check` が書くファイル `build/tsconfig.json` で、プラグインの型に対応させる。
- 明示の `any` は書かない。サブコマンド `check` が、tsc (strict) と、typescript-eslint の規則集 `strictTypeChecked` で検査する。

例の全体は、ファイル [examples/sample/deck.ts](../examples/sample/deck.ts) (見本の資料「キャッシュのしくみ」) を参照する。

## スライドの大きさと、図の要素の範囲

位置と大きさの単位はインチ。スライドの大きさは 10×5.625 インチ。

| 範囲 | 位置 (上端〜下端) | 書くもの |
| --- | --- | --- |
| 題名 | 0.58〜1.2 インチ | ツールが構成案の題名を入れる |
| 図 | 1.2〜4.6 インチ | 資料ごとのスクリプトの要素 |
| 一言 | 4.78〜5.2 インチ | ツールが構成案の一言を入れる |

図の要素は、題名と一言の範囲に重ねない。

## テーマ

```ts
const theme: Theme = {
  name: "Cache",
  fonts: { heading: "Noto Sans JP", body: "Noto Sans JP" },
  colors: { dk1: "1F2933", lt1: "FFFFFF", dk2: "52606D", lt2: "F2F4F7", hlink: "0F6E8C", folHlink: "6B4F9E" },
  accents: {
    accent1: { color: "0F6E8C", meaning: "アプリケーション" },
    accent2: { color: "0F8B8D", meaning: "キャッシュ" },
    accent3: { color: "1C3D5A", meaning: "DB" },
    accent4: { color: "2F9E44", meaning: "ヒット" },
    accent5: { color: "D9480F", meaning: "ミス・古い値" },
    accent6: { color: "F0A202", meaning: "注意" },
  },
};
```

- 6 つのアクセント色に、資料ごとに意味を割り当て、`meaning` に書く (例: 新しいもの・古いもの・失敗・成功)。同じ意味の図形には、同じアクセント色を使う。
- 色の値は、`#` を付けない 16 進数 6 桁。
- `fonts.heading` は題名に、`fonts.body` はほかの文字に使う。
- テーマの色は、PowerPoint のファイルのテーマと、Google スライドのマスターの配色に書き込む。Google スライドでは、色だけを変えたときは、スライドを作り直さずにマスターの配色だけを変える。

## 部品の関数

| 関数 | 作るもの | 主な使い方 |
| --- | --- | --- |
| `slide(key)` | キーごとの空の図 | 最初に 1 回呼び、戻り値をほかの関数に渡す |
| `box(s, x, y, w, h, 文字, オプション)` | 文字の入った図形。形のデフォルト値は角の丸い四角 | 図の主な箱。`shape` で四角 (`rect`)・円 (`ellipse`)・円柱 (`can`)・山形 (`chevron`)・五角形の矢印 (`homePlate`) にする。文字が空なら、文字の無い図形になる |
| `text(s, 文字, x, y, w, h, オプション)` | 塗りつぶしと枠線の無い文字の箱 | 見出し・説明・箇条書き・リンク |
| `arrow(s, x1, y1, x2, y2, オプション)` | 始点から終点への線 | 矢印。`dash` で破線、`noHead` で矢じりの無い線、`both` で両向き |
| `badge(s, 番号, x, y, 直径, オプション)` | 番号の入った円 | 順序を示す番号 |
| `card(s, x, y, w, h, オプション)` | 文字の無い、角の丸い四角 | 図の部分をまとめる背景 |
| `bullets(項目の配列, オプション)` | 箇条書きの文字 | 戻り値を `text` か `box` の文字に渡す |

`box` と `text` は、文字の引数の順序が違う (`box` は位置の後、`text` は位置の前)。

### 文字

`box` と `text` の文字には、文字列か、書式の違う部分の配列を渡す。

```ts
p.text(s, [{ text: "HTTP のキャッシュの規則: " }, { text: "RFC 9111", link: "https://www.rfc-editor.org/rfc/rfc9111" }], 0.5, 3.7, 9.0, 0.4, { fontSize: 12 });
p.box(s, 0.5, 1.4, 3.6, 1.6, [{ text: "有効期限", bold: true, breakLine: true }, { text: "決めた時間が過ぎたら消す" }], { shape: "rect" });
```

- 部分ごとに、大きさ・太字・色・リンクを指定できる。指定しなかった書式は、関数のオプションの書式になる。
- `breakLine: true` の部分の後と、文字の改行 (`\n`) で、段落を分ける。段落の分け方の規則は、ファイル [src/data/parts.ts](../src/data/parts.ts) の型 `RunInput` のコメントの規則 1〜6。
- 段落の後の間隔は、`text` のオプション `psa` (ポイント) で指定する。

## はみ出しの見積もり

サブコマンド `check` は、題名・一言・図の要素の文字が箱からはみ出しそうな箇所を見積もり、一覧があれば指摘にする (PowerPoint のファイルを書かない)。指摘されたら、箱を広げるか、文を縮める。文を縮めるときは、構成案の題名・一言を直す (図の要素の文字なら `deck.ts` を直す)。見積もりは、Google スライドの文字の箱の余白 (左右 0.1 インチ・上下 0.05 インチ) も含めて行う。小さな円 (`badge`) は、この余白のために、直径 0.3 インチでは 12 ポイントの 1 行が入らない (見本の資料は 0.32 インチにした)。

## Google スライドでの描き方

Google スライドの API の都合で、PowerPoint と描き方が違う要素がある (円などの中の文字・大きな角の丸い四角など)。一覧は、ファイル [google-slides.md](google-slides.md) の節「Google スライドの API への対処」を参照する。
