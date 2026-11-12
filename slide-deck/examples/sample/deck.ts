// 見本の資料「キャッシュのしくみ」の資料ごとのスクリプト。
// 構成案 outline.md のキーごとの図を、部品の関数だけで作る。題名・一言・発表者ノートは構成案から読むので、ここには書かない。
// スライドの大きさは 10×5.625 インチ。図は、題名の下 (y が 1.2 インチ) から、一言の上 (y が 4.6 インチ) までに置く。

import type { DeckScript, Theme } from "slide-deck";

const theme: Theme = {
  name: "Cache",
  fonts: { heading: "Noto Sans JP", body: "Noto Sans JP" },
  colors: {
    dk1: "1F2933",
    lt1: "FFFFFF",
    dk2: "52606D",
    lt2: "F2F4F7",
    hlink: "0F6E8C",
    folHlink: "6B4F9E",
  },
  accents: {
    accent1: { color: "0F6E8C", meaning: "アプリケーション" },
    accent2: { color: "0F8B8D", meaning: "キャッシュ" },
    accent3: { color: "1C3D5A", meaning: "DB" },
    accent4: { color: "2F9E44", meaning: "ヒット" },
    accent5: { color: "D9480F", meaning: "ミス・古い値" },
    accent6: { color: "F0A202", meaning: "注意" },
  },
};

const deck: DeckScript = (p) => {
  // 読み出しの流れ。行きの矢印を上の段、帰りの矢印を下の段に描く
  const readPath = p.slide("read-path");
  p.box(readPath, 0.5, 2.0, 2.2, 1.2, "アプリケーション", { fill: "accent1", color: "lt1", bold: true });
  p.box(readPath, 3.9, 2.0, 2.2, 1.2, "キャッシュ", { fill: "accent2", color: "lt1", bold: true });
  p.box(readPath, 7.3, 1.8, 2.0, 1.6, "DB", { shape: "can", fill: "accent3", color: "lt1", bold: true });
  p.arrow(readPath, 2.7, 2.35, 3.9, 2.35);
  p.arrow(readPath, 6.1, 2.35, 7.3, 2.35, { dash: true });
  p.arrow(readPath, 7.3, 2.85, 6.1, 2.85, { dash: true });
  p.arrow(readPath, 3.9, 2.85, 2.7, 2.85);
  p.badge(readPath, 1, 3.15, 1.85, 0.3);
  p.badge(readPath, 2, 6.55, 1.85, 0.3, { fill: "accent5" });
  p.badge(readPath, 3, 6.55, 2.95, 0.3, { fill: "accent5" });
  p.badge(readPath, 4, 3.15, 2.95, 0.3);
  p.text(readPath, "破線の ② と ③ は、キャッシュに値が無いときだけ", 0.5, 3.8, 9.0, 0.4, {
    fontSize: 12,
    color: "dk2",
    align: "center",
  });

  // ヒットとミス。2 枚のカードの上に、見出しと箇条書きを書く
  const hitMiss = p.slide("hit-miss");
  p.card(hitMiss, 0.5, 1.3, 4.3, 3.2);
  p.card(hitMiss, 5.2, 1.3, 4.3, 3.2);
  p.text(hitMiss, [{ text: "ヒット", bold: true, color: "accent4" }], 0.8, 1.5, 3.7, 0.4, { fontSize: 18 });
  p.text(hitMiss, [{ text: "ミス", bold: true, color: "accent5" }], 5.5, 1.5, 3.7, 0.4, { fontSize: 18 });
  p.text(
    hitMiss,
    p.bullets(["キャッシュの値をそのまま返す", "DB に問い合わせない"]),
    0.8,
    2.1,
    3.7,
    1.2,
    { psa: 6 },
  );
  p.text(
    hitMiss,
    p.bullets(["DB から読む", "読んだ値をキャッシュに残す"]),
    5.5,
    2.1,
    3.7,
    1.2,
    { psa: 6 },
  );
  p.box(hitMiss, 2.0, 3.5, 1.3, 0.8, "速い", { shape: "ellipse", fill: "accent4", color: "lt1", bold: true });
  p.box(hitMiss, 6.7, 3.5, 1.3, 0.8, "遅い", { shape: "ellipse", fill: "accent5", color: "lt1", bold: true });

  // 古い値が残る。順序を山形の図形で示し、古い値が残る期間を破線の枠で示す
  const stale = p.slide("stale");
  p.box(stale, 0.5, 1.6, 3.0, 0.8, "DB の値を更新する", { shape: "homePlate", fill: "accent3", color: "lt1" });
  p.box(stale, 3.4, 1.6, 3.0, 0.8, "キャッシュは古い値のまま", { shape: "chevron", fill: "accent6" });
  p.box(stale, 6.3, 1.6, 3.0, 0.8, "古い値を返す", { shape: "chevron", fill: "accent5", color: "lt1" });
  p.arrow(stale, 6.4, 3.0, 6.4, 2.4, { color: "accent5", dash: true });
  p.box(stale, 1.5, 3.0, 7.0, 1.0, "期限が切れるか、消すまで、古い値が残る", {
    shape: "rect",
    fill: "lt1",
    line: "accent5",
    lineW: 1.5,
    dash: true,
  });

  // 期限と消し方。2 つの対処を左右に並べ、両向きの矢印で組み合わせられることを示す
  const expire = p.slide("expire");
  p.box(
    expire,
    0.5,
    1.4,
    3.6,
    1.6,
    [
      { text: "有効期限", bold: true, fontSize: 16, breakLine: true },
      { text: "決めた時間が過ぎたら消す" },
    ],
    { shape: "rect", fill: "lt2", line: "accent2" },
  );
  p.box(
    expire,
    5.9,
    1.4,
    3.6,
    1.6,
    [
      { text: "更新するときに消す", bold: true, fontSize: 16, breakLine: true },
      { text: "DB を更新したら、キャッシュの値を消す" },
    ],
    { shape: "rect", fill: "lt2", line: "accent2" },
  );
  p.arrow(expire, 4.2, 2.2, 5.8, 2.2, { both: true, color: "accent2" });
  p.text(expire, "組み合わせる", 4.1, 2.35, 1.8, 0.35, { fontSize: 11, align: "center", color: "dk2" });
  p.arrow(expire, 0.5, 3.5, 9.5, 3.5, { noHead: true, width: 0.75, color: "dk2" });
  p.text(
    expire,
    [
      { text: "HTTP のキャッシュの規則: " },
      { text: "RFC 9111", link: "https://www.rfc-editor.org/rfc/rfc9111" },
    ],
    0.5,
    3.7,
    9.0,
    0.4,
    { fontSize: 12, color: "dk2" },
  );

  return { theme, slides: [readPath, hitMiss, stale, expire] };
};

export default deck;
