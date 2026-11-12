// 入口のサブコマンド pptx の処理。check と同じ検査に合格したときだけ PowerPoint のファイルを書き、
// pptx のスキルの scripts/apply_theme.js でテーマの色を書き込み、scripts/office/validate.py で形式を検査する (計画の R10〜R12・U5)。
// pptx のスキルは、Claude のデスクトップアプリが配るもの (スキルの一覧での名前は anthropic-skills:pptx)。
// ディレクトリは、スキル build が引数で渡す。~/.claude の下などを探さない (計画の KTD11)。
// 入口のサブコマンド pptx の引数・出力・終了コードの SSOT は、ファイル src/cli.ts の --help。

import { spawnSync } from "node:child_process";
import { existsSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { type CheckOptions, type CheckReport, checkDeck, deckPaths, ExecutionError, installedCache } from "../check/deck.ts";
import { type CachePaths, venvState } from "../setup/setup.ts";
import { applyThemeInput, loadPptxGen, renderPptx } from "./write.ts";

/** pptx のスキルのディレクトリと、使う 2 つのスクリプトのパス */
export interface PptxSkill {
  readonly dir: string;
  /** scripts/apply_theme.js */
  readonly applyTheme: string;
  /** scripts/office/validate.py */
  readonly validate: string;
}

/** pptx のスキルのディレクトリを受け取り、使う 2 つのスクリプトがあることを確認する。無ければ ExecutionError を送出する */
export function pptxSkill(dir: string): PptxSkill {
  const abs = resolve(dir);
  const skill: PptxSkill = {
    dir: abs,
    applyTheme: join(abs, "scripts", "apply_theme.js"),
    validate: join(abs, "scripts", "office", "validate.py"),
  };
  const missing = [skill.applyTheme, skill.validate].filter((p) => !existsSync(p));
  if (missing.length > 0) {
    throw new ExecutionError(
      `pptx のスキルのディレクトリ ${abs} に、次のファイルが無い:\n${missing.map((p) => `  ${p}`).join("\n")}\n` +
        "Claude のデスクトップアプリが配る pptx のスキル (スキルの一覧での名前は anthropic-skills:pptx) のディレクトリを渡す。" +
        "マーケットプレイス anthropic-agent-skills のプラグイン document-skills が配る pptx のスキルには、scripts/apply_theme.js が無い",
    );
  }
  return skill;
}

/**
 * テーマの色を PowerPoint のファイルに書き込む処理。pptxPath のファイルを書き換え、利用者に示す出力を返す。
 * 失敗したら ExecutionError を送出する。テストで差し替えられるよう、関数として渡す
 */
export type ApplyTheme = (pptxPath: string, themePath: string) => string;

/**
 * pptx のスキルの scripts/apply_theme.js を、環境変数 NODE_PATH にキャッシュの node_modules を指定した子プロセスで実行する
 * (計画の KTD8)。apply_theme.js は pptxgenjs に同梱の jszip を、require で NODE_PATH から探す
 */
export function skillApplyTheme(skill: PptxSkill, cache: CachePaths, env: NodeJS.ProcessEnv): ApplyTheme {
  return (pptxPath, themePath) => {
    const r = spawnSync(process.execPath, [skill.applyTheme, pptxPath, themePath], {
      env: { ...env, NODE_PATH: cache.nodeModulesDir },
      encoding: "utf8",
    });
    const output = `${r.stdout}${r.stderr}`.trimEnd();
    if (r.error !== undefined || r.status !== 0) {
      throw new ExecutionError(
        `pptx のスキルの ${skill.applyTheme} が失敗した (終了コード ${String(r.status)}${r.error === undefined ? "" : `、${r.error.message}`}):\n${output}`,
      );
    }
    return output;
  };
}

/** pptx のスキルの scripts/office/validate.py の結果。ok が false なら、形式の誤りがある */
export interface ValidateResult {
  readonly ok: boolean;
  readonly output: string;
}

/**
 * pptx のスキルの scripts/office/validate.py を、キャッシュの venv の Python で実行する。
 * 終了コード 0 は誤りなし、1 は形式の誤りあり。それ以外は ExecutionError にする
 */
export function skillValidate(skill: PptxSkill, cache: CachePaths, pptxPath: string, env: NodeJS.ProcessEnv): ValidateResult {
  const r = spawnSync(cache.venvPython, [skill.validate, pptxPath], { env, encoding: "utf8" });
  const output = `${r.stdout}${r.stderr}`.trimEnd();
  if (r.error === undefined && (r.status === 0 || r.status === 1)) return { ok: r.status === 0, output };
  throw new ExecutionError(
    `pptx のスキルの ${skill.validate} を、${cache.venvPython} で実行できなかった (終了コード ${String(r.status)}` +
      `${r.error === undefined ? "" : `、${r.error.message}`}):\n${output}`,
  );
}

/** サブコマンド pptx の引数 */
export interface PptxOptions extends CheckOptions {
  /** pptx のスキルのディレクトリ */
  readonly skillDir: string;
  /** テーマの色を書き込む処理。省略すると、pptx のスキルの scripts/apply_theme.js を実行する */
  readonly applyTheme?: ApplyTheme;
}

/** サブコマンド pptx の結果 */
export interface PptxReport {
  readonly check: CheckReport;
  /** 書いた PowerPoint のファイル。check に指摘があれば null */
  readonly pptx: string | null;
  /** テーマの色を書き込む処理の出力 */
  readonly applyThemeOutput: string;
  /** validate.py の結果。check に指摘があれば null */
  readonly validate: ValidateResult | null;
}

/**
 * 前に書いた build/deck.pptx を消す。終了コード 2 で終了しうる確認 (pptx のスキル・ライブラリ・資料のディレクトリ) より前に呼ぶ。
 * 確認の後に消すと、確認で終了した実行の後に、前の実行のファイルが残る。
 * 資料のディレクトリのパスがディレクトリでなければ (無い・通常のファイル)、消すものは無く、後の関数 deckPaths が実行の誤りにする。
 * 消せないとき (build/deck.pptx がディレクトリのときなど) は、パスと理由を示す ExecutionError を送出する
 */
function removePreviousPptx(deckDir: string): void {
  const dir = resolve(deckDir);
  if (!existsSync(dir) || !statSync(dir).isDirectory()) return;
  const pptxPath = join(dir, "build", "deck.pptx");
  try {
    rmSync(pptxPath, { force: true });
  } catch (e) {
    throw new ExecutionError(`前に書いた ${pptxPath} を消せない: ${e instanceof Error ? e.message : String(e)}`);
  }
}

/**
 * 資料のディレクトリを検査し、指摘が無ければ build/deck.pptx を書き、テーマの色を書き込み、形式を検査する。
 * 前に書いた build/deck.pptx は、最初に消す (ファイルがあることと、最後の実行が書いたことを一致させるため)。
 * テーマの色の書き込みが失敗したら、書いたファイルも消す。validate.py が形式の誤りを見つけたときは、調べられるようファイルを残す
 */
export async function buildPptx(deckDir: string, options: PptxOptions): Promise<PptxReport> {
  removePreviousPptx(deckDir);
  const env = options.env ?? process.env;
  const skill = pptxSkill(options.skillDir);
  const cache = installedCache(options);
  if (venvState(cache) !== "installed") {
    throw new ExecutionError(
      `ライブラリ (Python の venv) が、キャッシュのディレクトリ ${cache.venvDir} に入っていない。` +
        "サブコマンド setup status で状態を確認し、setup install で入れる",
    );
  }
  const paths = deckPaths(deckDir);
  const pptxPath = join(paths.buildDir, "deck.pptx");
  const themePath = join(paths.buildDir, "theme.json");

  const check = await checkDeck(deckDir, options);
  if (check.deck === null) return { check, pptx: null, applyThemeOutput: "", validate: null };

  writeFileSync(pptxPath, await renderPptx(check.deck, loadPptxGen(cache.nodeModulesDir)));
  writeFileSync(themePath, `${JSON.stringify(applyThemeInput(check.deck.theme), null, 2)}\n`);
  const applyTheme = options.applyTheme ?? skillApplyTheme(skill, cache, env);
  let applyThemeOutput: string;
  try {
    applyThemeOutput = applyTheme(pptxPath, themePath);
  } catch (e) {
    rmSync(pptxPath, { force: true });
    const message = e instanceof Error ? e.message : String(e);
    throw new ExecutionError(`${message}\nテーマの色を書き込めなかったので、PowerPoint のファイル ${pptxPath} は消した`);
  }
  const validate = skillValidate(skill, cache, pptxPath, env);
  return { check, pptx: pptxPath, applyThemeOutput, validate };
}
