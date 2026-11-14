// 入口のサブコマンド requests の処理 (計画の U6)。check と同じ検査に合格したときだけ、
// 資料の読み込みの結果 build/presentation.json と比べて、Google スライドの指示のファイルを build/ に書く。
// 入口のサブコマンド requests の引数・出力・終了コードの SSOT は、ファイル src/cli.ts の --help。

import { existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { type CheckOptions, type CheckReport, checkDeck, deckPaths, ExecutionError, type Finding } from "../check/deck.ts";
import type { Deck } from "../data/types.ts";
import { notesChanges, notesRequestFiles } from "./notes.ts";
import { PlanError, planSlides, type SlidePlan } from "./plan.ts";
import { type Presentation, parsePresentation, PRESENTATION_FIELDS, PRESENTATION_SHAPE } from "./presentation.ts";
import { countObjects, mastersToRecolor, MAX_OBJECTS_PER_SLIDE, type Request, slideRequestFiles } from "./requests.ts";

/** 前の実行が書いた指示のファイルの名前 */
const REQUEST_FILE = /^requests-(notes-)?\d+\.json$/;

/** サブコマンド requests の引数 */
export interface RequestsOptions extends CheckOptions {
  /** ハッシュ値が一致するスライドも作り直すか (計画の KTD10) */
  readonly recreateAll?: boolean;
}

/** 書いた指示のファイル */
export interface WrittenFile {
  readonly path: string;
  /** 指示の数 */
  readonly count: number;
  /** ファイルの字数 (JSON の文字列の長さ) */
  readonly chars: number;
}

/** サブコマンド requests の結果。検査の指摘があれば、plan は null で、ファイルを書かない */
export interface RequestsReport {
  readonly check: CheckReport;
  /** check の指摘に加えた、指示を作れないスライドの指摘 */
  readonly findings: readonly Finding[];
  readonly presentation: Presentation;
  readonly plan: SlidePlan | null;
  /** 配色を変えるマスターの ID */
  readonly colorMasters: readonly string[];
  /** ノートを入れ直すキー */
  readonly notesKeys: readonly string[];
  /** スライドの指示のファイル */
  readonly files: readonly WrittenFile[];
  /** ノートの指示のファイル */
  readonly notesFiles: readonly WrittenFile[];
}

/**
 * 前の実行が書いた指示のファイルを消す。終了コード 2 で終了しうる確認より前に呼ぶ。
 * 消さずに終了すると、前の実行のファイルを Claude が送るおそれがあるため
 */
function removePreviousRequests(deckDir: string): void {
  const buildDir = join(resolve(deckDir), "build");
  if (!existsSync(buildDir) || !statSync(buildDir).isDirectory()) return;
  for (const name of readdirSync(buildDir)) {
    if (!REQUEST_FILE.test(name)) continue;
    const path = join(buildDir, name);
    try {
      rmSync(path, { force: true });
    } catch (e) {
      throw new ExecutionError(`前に書いた ${path} を消せない: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
}

/** build/presentation.json を読んで検査する。無いか形が違えば、期待する形を示す ExecutionError を送出する */
export function readPresentation(path: string): Presentation {
  if (!existsSync(path)) {
    throw new ExecutionError(
      `資料の読み込みの結果 ${path} が無い。Google スライドのコネクタで、項目 (fields) に次の値を指定して資料を読み込み、` +
        `結果をそのまま書く:\n  ${PRESENTATION_FIELDS}`,
    );
  }
  let json: unknown;
  try {
    json = JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    throw new ExecutionError(`${path} が JSON として読めない: ${e instanceof Error ? e.message : String(e)}`);
  }
  const r = parsePresentation(json);
  if (!r.ok) {
    throw new ExecutionError(
      `${path} の形が違う:\n${r.errors.map((e) => `  ${e}`).join("\n")}\n期待する形:\n${PRESENTATION_SHAPE}`,
    );
  }
  return r.presentation;
}

/** 図形の数が上限を超えるスライドの指摘。無ければ null */
function overflowFinding(deck: Deck): Finding | null {
  const lines = deck.slides
    .filter((s) => countObjects(s) > MAX_OBJECTS_PER_SLIDE)
    .map((s) => `${s.key}: 図形 ${String(countObjects(s))} 個`);
  if (lines.length === 0) return null;
  return {
    heading: `図形が ${String(MAX_OBJECTS_PER_SLIDE)} 個を超えるスライド (題名・一言と、円などの中の文字の箱を含む。スライドを分ける)`,
    lines,
  };
}

function writeFiles(dir: string, prefix: string, files: readonly Request[][]): WrittenFile[] {
  return files.map((requests, i) => {
    const path = join(dir, `${prefix}${String(i + 1)}.json`);
    const text = JSON.stringify(requests);
    writeFileSync(path, text);
    return { path, count: requests.length, chars: text.length };
  });
}

/**
 * 資料のディレクトリを検査し、指摘が無ければ、build/presentation.json と比べて指示のファイルを書く。
 * 前に書いた指示のファイルは、最初に消す (ファイルがあることと、最後の実行が書いたことを一致させるため)
 */
export async function buildRequests(deckDir: string, options: RequestsOptions = {}): Promise<RequestsReport> {
  removePreviousRequests(deckDir);
  const paths = deckPaths(deckDir);
  const presentation = readPresentation(join(paths.buildDir, "presentation.json"));
  const check = await checkDeck(deckDir, options);
  const empty = { colorMasters: [], notesKeys: [], files: [], notesFiles: [] };
  if (check.deck === null) return { check, findings: check.findings, presentation, plan: null, ...empty };
  const deck = check.deck;
  const overflow = overflowFinding(deck);
  if (overflow !== null) return { check, findings: [overflow], presentation, plan: null, ...empty };

  let plan: SlidePlan;
  try {
    plan = planSlides(deck.slides, deck.theme.fonts, presentation, options.recreateAll ?? false);
  } catch (e) {
    if (e instanceof PlanError) throw new ExecutionError(e.message);
    throw e;
  }
  const colorMasters = mastersToRecolor(presentation, deck.theme);
  const changes = notesChanges(deck.slides, plan.keys, presentation);
  return {
    check,
    findings: [],
    presentation,
    plan,
    colorMasters,
    notesKeys: changes.map((c) => c.key),
    files: writeFiles(paths.buildDir, "requests-", slideRequestFiles(plan, presentation, deck.theme)),
    notesFiles: writeFiles(paths.buildDir, "requests-notes-", notesRequestFiles(changes)),
  };
}

const ACTION_NAME = { create: "作る", recreate: "作り直す", keep: "そのまま" } as const;

/** 結果を、利用者に示す文字列にする */
export function formatRequestsReport(report: RequestsReport): string {
  const { plan } = report;
  if (plan === null) {
    return report.findings.map((f) => `${f.heading}:\n${f.lines.map((l) => `  ${l}`).join("\n")}\n`).join("\n");
  }
  const lines = [`検査の指摘は無い (スライド ${String(plan.keys.length)} 枚)`, "キーごとの作業:"];
  for (const k of plan.keys) {
    const ids = k.action === "keep" ? "" : k.oldId === null ? ` (${k.newId})` : ` (${k.oldId} → ${k.newId})`;
    lines.push(`  ${k.key}: ${ACTION_NAME[k.action]}${ids}`);
  }
  if (plan.removed.length > 0) {
    lines.push("消すスライド (構成案から消したキー):", ...plan.removed.map((r) => `  ${r.key}: ${r.objectId}`));
  }
  if (plan.initialSlideId !== null) lines.push(`新しく作った資料の、最初からあるスライドを消す: ${plan.initialSlideId}`);
  if (plan.untouched.length > 0) lines.push(`キーの無いスライド (触れない): ${plan.untouched.join(", ")}`);
  const moves = plan.steps.filter((s) => s.kind === "move").length;
  lines.push(`並べ替え: ${moves === 0 ? "なし" : `${String(moves)} 回`}`);
  lines.push(`配色を変えるマスター: ${report.colorMasters.length === 0 ? "なし" : report.colorMasters.join(", ")}`);
  lines.push(`ノートを入れ直すキー: ${report.notesKeys.length === 0 ? "なし" : report.notesKeys.join(", ")}`);
  const files = [...report.files, ...report.notesFiles];
  if (files.length === 0) {
    lines.push("送る指示は無い");
  } else {
    lines.push(
      `送る指示のファイル (この順に送る。どのファイルも、送る直前に読み込んだ資料の revisionId を付ける):`,
      ...files.map((f) => `  ${f.path} (指示 ${String(f.count)} 個、${String(f.chars)} 字)`),
    );
  }
  if (plan.keys.some((k) => k.action !== "keep")) {
    lines.push("作る・作り直すスライドのノートは、指示を送った後に資料を再度読み込み、もう一度 requests を実行すると、ノートの指示のファイルに入る");
  }
  return `${lines.join("\n")}\n`;
}
