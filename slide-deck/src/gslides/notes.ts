// 発表者ノートの指示 (計画の R20・KTD10・U6)。
// ノートは、資料から読んだ文と構成案の文をキーごとに比べ、違うキーだけ入れ直す。スライドの ID のハッシュ値に含めないので、
// ノートだけを直してもスライドは作り直しにならない (計画の KTD9)。
// ノートの欄の ID はスライドを作った後でないと分からないので、作る・作り直すスライドのノートは、送った後に資料を再度読み込んで作る。

import type { Slide } from "../data/types.ts";
import type { KeyPlan } from "./plan.ts";
import type { Presentation } from "./presentation.ts";
import { MAX_FILE_CHARS, packRequests, type Request } from "./requests.ts";

/** 読んだノートの欄の文を、構成案の文と比べられる形にする。Google スライドは文の末尾に改行を付けるので、それを除く */
function normalize(text: string | null): string {
  if (text === null) return "";
  return text.endsWith("\n") ? text.slice(0, -1) : text;
}

/** ノートを入れ直すスライド */
export interface NotesChange {
  key: string;
  requests: Request[];
}

/**
 * ノートを入れ直す指示を、キーごとに作る。対象は、作業が「そのまま」で、資料にいまの ID のスライドがあるキーだけ。
 * 作る・作り直すキーは、ノートの欄の ID がまだ分からないので、送った後に資料を再度読み込んで、もう一度求める。
 */
export function notesChanges(slides: readonly Slide[], keys: readonly KeyPlan[], presentation: Presentation): NotesChange[] {
  const byId = new Map(presentation.slides.map((s) => [s.objectId, s]));
  const changes: NotesChange[] = [];
  keys.forEach((k, i) => {
    const slide = slides[i];
    const read = byId.get(k.newId);
    if (k.action !== "keep" || slide === undefined || read === undefined) return;
    const current = normalize(read.notesText);
    if (current === slide.notes) return;
    const requests: Request[] = [];
    // 欄に文があれば、消してから入れる。空の欄の文を消す指示は失敗するので、空なら消さない (計画の KTD10)。
    // 空かどうかは、text の有無ではなく、末尾の改行を除いた文で決める。text があっても、文を持たない
    // (段落の始まりだけか、改行だけの) 欄があるため
    if (current !== "") {
      requests.push({ deleteText: { objectId: read.notesObjectId, textRange: { type: "ALL" } } });
    }
    if (slide.notes !== "") {
      requests.push({ insertText: { objectId: read.notesObjectId, insertionIndex: 0, text: slide.notes } });
    }
    changes.push({ key: k.key, requests });
  });
  return changes;
}

/**
 * ノートの指示を、ファイルごとの配列にする。スライドの指示と同じ字数の上限 (MAX_FILE_CHARS) で分け、1 枚のスライドの指示は分けない
 * (U6 を実装するときに決めた。枚数で分けると、ノートの長い資料で Bash の出力の上限を超えうるため)
 */
export function notesRequestFiles(changes: readonly NotesChange[], limit: number = MAX_FILE_CHARS): Request[][] {
  return packRequests(
    changes.map((c) => c.requests),
    limit,
  );
}
