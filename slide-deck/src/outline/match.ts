// 構成案のキーと、資料ごとのスクリプト deck.ts が作った図のキーを突き合わせる (計画の R9)。
// 一致しなければ、build は PowerPoint のファイルを作らずに、この結果を一覧にして中断する。

/** キーの突き合わせの結果。どの配列も、それぞれのキーが最初に現れた順序で並べる。 */
export interface KeyMismatch {
  /** 構成案にだけあるキー。 */
  outlineOnly: string[];
  /** 資料ごとのスクリプトにだけあるキー。 */
  deckOnly: string[];
  /** 資料ごとのスクリプトで、2 回以上図を作ったキー (1 回ずつ並べる)。構成案のキーの重複は、構成案を読むときに誤りにする。 */
  deckDuplicates: string[];
}

/** 構成案のキーの配列と、資料ごとのスクリプトの図のキーの配列を突き合わせる。 */
export function matchKeys(outlineKeys: readonly string[], deckKeys: readonly string[]): KeyMismatch {
  const outline = new Set(outlineKeys);
  const deck = new Set(deckKeys);
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const k of deckKeys) {
    if (seen.has(k)) duplicates.add(k);
    seen.add(k);
  }
  return {
    outlineOnly: [...outline].filter((k) => !deck.has(k)),
    deckOnly: [...deck].filter((k) => !outline.has(k)),
    deckDuplicates: [...duplicates],
  };
}

/** 突き合わせの結果に、不一致が 1 つでもあるか。 */
export function hasMismatch(m: KeyMismatch): boolean {
  return m.outlineOnly.length > 0 || m.deckOnly.length > 0 || m.deckDuplicates.length > 0;
}
