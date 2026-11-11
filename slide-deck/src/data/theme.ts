// テーマ。資料ごとに、6 つのアクセント色の値と意味の名前・フォントを決める (計画の R11)。
// 図形の色はテーマの色の名前で指定し、色の値はテーマだけが持つ。

/** アクセント色。color は 16 進数 6 桁の RGB の値 (例: "0F8B8D")、meaning はその色に割り当てた意味 (例: "新しい版")。 */
export interface AccentColor {
  color: string;
  meaning: string;
}

/**
 * 資料のテーマ。
 * colors はアクセント色以外の 6 色 (dk1 は文字、lt1 は背景、dk2 は補助の文字、lt2 は補助の背景、hlink はリンク、folHlink は開いたリンク)。
 * accents は 6 つのアクセント色で、どれも省略できない。
 * name はテーマの名前で、PowerPoint のファイルに書き込む。
 */
export interface Theme {
  name: string;
  fonts: {
    heading: string;
    body: string;
  };
  colors: {
    dk1: string;
    lt1: string;
    dk2: string;
    lt2: string;
    hlink: string;
    folHlink: string;
  };
  accents: {
    accent1: AccentColor;
    accent2: AccentColor;
    accent3: AccentColor;
    accent4: AccentColor;
    accent5: AccentColor;
    accent6: AccentColor;
  };
}

/** テーマの 12 色の名前。PowerPoint のファイルの形式の配色の名前と同じ。 */
export type SchemeColorName = keyof Theme["colors"] | keyof Theme["accents"];

/** テーマの 12 色の名前を、配色の順序で並べた配列。 */
export const SCHEME_COLOR_NAMES: readonly SchemeColorName[] = [
  "dk1",
  "lt1",
  "dk2",
  "lt2",
  "accent1",
  "accent2",
  "accent3",
  "accent4",
  "accent5",
  "accent6",
  "hlink",
  "folHlink",
];

/** テーマの 12 色の名前と値の対応を返す。PowerPoint のファイルと Google スライドに配色を書き込むときに使う。 */
export function schemeColorValues(theme: Theme): Record<SchemeColorName, string> {
  const { colors, accents } = theme;
  return {
    ...colors,
    accent1: accents.accent1.color,
    accent2: accents.accent2.color,
    accent3: accents.accent3.color,
    accent4: accents.accent4.color,
    accent5: accents.accent5.color,
    accent6: accents.accent6.color,
  };
}

const RGB_HEX = /^[0-9A-Fa-f]{6}$/;

/**
 * テーマの値の誤りを、すべて集めて返す。誤りが無ければ空の配列を返す。
 * 型では検査できない、色の値の形 (16 進数 6 桁。"#" を付けない) と、空の名前・フォント・意味を検査する。
 */
export function checkTheme(theme: Theme): string[] {
  const errors: string[] = [];
  if (theme.name.trim() === "") errors.push("テーマの name が空");
  if (theme.fonts.heading.trim() === "") errors.push("テーマの fonts.heading が空");
  if (theme.fonts.body.trim() === "") errors.push("テーマの fonts.body が空");
  const values = schemeColorValues(theme);
  for (const name of SCHEME_COLOR_NAMES) {
    const value = values[name];
    if (!RGB_HEX.test(value)) {
      errors.push(`テーマの色 ${name} の値 ${JSON.stringify(value)} が、16 進数 6 桁 (例: "0F8B8D") ではない`);
    }
  }
  for (const [name, accent] of Object.entries(theme.accents)) {
    if (accent.meaning.trim() === "") errors.push(`テーマの色 ${name} の meaning が空`);
  }
  return errors;
}
