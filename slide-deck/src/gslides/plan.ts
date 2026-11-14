// 構成案のスライドと、Google スライドの資料の読み込みの結果を比べ、キーごとの作業 (作る・作り直す・消す・そのまま) と、
// 資料のスライドに対する操作の順序を求める (計画の R17・R19・KTD9・KTD10・U6)。
// 作業は、資料を読むだけで機械的に決まる。途中で失敗しても、資料を再度読み込んでもう一度求めれば、残りの作業だけになる (計画の R19)。

import { createHash } from "node:crypto";
import type { Theme } from "../data/theme.ts";
import type { Slide } from "../data/types.ts";
import type { Presentation } from "./presentation.ts";

/** スライドの ID の接頭辞。キーの無いスライド (利用者が足したもの) と区別するため、と ID の長さの下限 (5 文字) を満たすため */
export const SLIDE_ID_PREFIX = "sd_";

/** ハッシュ値の 16 進数の桁数 (計画の KTD9) */
const HASH_LENGTH = 10;

// キーは構成案の書式で [a-z0-9-] の 1〜32 文字に限る (ファイル src/outline/parse.ts)。区切りの _ はキーに入らない
const SLIDE_ID_PATTERN = new RegExp(`^${SLIDE_ID_PREFIX}([a-z0-9-]{1,32})_([0-9a-f]{${String(HASH_LENGTH)}})$`);

/** キーと値の順序を決めて JSON にする。プロパティの順序でハッシュ値が変わらないようにするため */
function stableJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableJson).join(",")}]`;
  if (typeof v === "object" && v !== null) {
    const entries = Object.entries(v)
      .filter(([, value]) => value !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, value]) => `${JSON.stringify(k)}:${stableJson(value)}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

/**
 * スライドの内容のハッシュ値 (SHA-256 の先頭 10 文字)。
 * 入力は、題名・一言・図の要素と、指示に書くテーマのフォント (見出しと本文) で、キー・位置・発表者ノートを含めない (計画の KTD9)。
 * ノートだけの修正や、前へのスライドの挿入で、変えていないスライドまで作り直しにならないため。
 * フォントを含めるのは、テーマのフォントだけを変えたときにも、スライドを作り直すため (U6 を実装するときに決めた)
 */
export function slideHash(slide: Pick<Slide, "title" | "takeaway" | "elements">, fonts: Theme["fonts"]): string {
  const input = stableJson({ title: slide.title, takeaway: slide.takeaway, elements: slide.elements, fonts });
  return createHash("sha256").update(input).digest("hex").slice(0, HASH_LENGTH);
}

/** スライドの ID (sd_<キー>_<ハッシュ値>) */
export function slideObjectId(key: string, hash: string): string {
  return `${SLIDE_ID_PREFIX}${key}_${hash}`;
}

/** スライドの ID からキーとハッシュ値を取り出す。キーの形でない ID (キーの無いスライド) は null */
export function parseSlideObjectId(id: string): { key: string; hash: string } | null {
  const m = SLIDE_ID_PATTERN.exec(id);
  if (m === null) return null;
  const [, key = "", hash = ""] = m;
  return { key, hash };
}

/** 読み込みの結果がスライドの作業を決められないとき (同じキーのスライドが 2 枚あるなど) の誤り */
export class PlanError extends Error {
  override name = "PlanError";
}

/**
 * 構成案のキーごとの作業。
 * create は作る、recreate は作り直す (内容が変わったか、--recreate-all を指定した)、keep はそのまま。
 */
export type KeyAction = "create" | "recreate" | "keep";

/** 構成案の 1 枚のスライドの作業。oldId は資料にあるスライドの ID (作るときは null)、newId は作業の後の ID */
export interface KeyPlan {
  key: string;
  action: KeyAction;
  oldId: string | null;
  newId: string;
}

/**
 * 資料のスライドに対する操作。指示の作成 (ファイル src/gslides/requests.ts) は、この順序で指示に変える。
 * - delete: スライドを消す。
 * - move: 並んだスライドを、まとめて insertionIndex の位置に動かす (Google スライドの API の updateSlidesPosition)。
 *   insertionIndex は、動かす前の順序での位置。
 * - create: スライドを insertionIndex の位置に作る。replaceId があれば、作り直し。replaceFirst が false なら作った後に、
 *   true なら作る前に、replaceId のスライドを消す (新しい ID が古い ID と同じときは、先に消さないと ID が重なるため)。
 */
export type SlideStep =
  | { kind: "delete"; objectId: string }
  | { kind: "move"; objectIds: string[]; insertionIndex: number }
  | { kind: "create"; slide: Slide; objectId: string; insertionIndex: number; replaceId: string | null; replaceFirst: boolean };

/** 構成案と資料の差 */
export interface SlidePlan {
  /** 構成案の順序の、キーごとの作業 */
  keys: KeyPlan[];
  /** 構成案から消したキーの、資料のスライド (消す) */
  removed: { key: string; objectId: string }[];
  /** キーの無いスライドの ID (触れない) */
  untouched: string[];
  /** 新しく作った資料の、最初からあるスライドの ID (消す)。新しい資料でなければ null */
  initialSlideId: string | null;
  /** 操作の順序。delete と move を先に、create を構成案の順序で並べる */
  steps: SlideStep[];
}

/** 計算するときの資料のスライドの順序。キーのあるスライドは key を持つ */
interface Current {
  id: string;
  key: string | null;
}

/**
 * スライドの順序を、先頭のキーの無いスライドの集まりと、キーのあるスライドごとの集まり (そのスライドと、直後に続くキーの無いスライド) に分ける。
 * キーの無いスライドは、直前のキーのあるスライドと一緒に動く (計画の R17)
 */
function groups(list: readonly Current[]): { head: string[]; byKey: Map<string, string[]> } {
  const head: string[] = [];
  const byKey = new Map<string, string[]>();
  let current = head;
  for (const s of list) {
    if (s.key !== null) {
      current = [s.id];
      byKey.set(s.key, current);
    } else {
      current.push(s.id);
    }
  }
  return { head, byKey };
}

/**
 * 構成案のスライドと読み込みの結果から、作業を求める。
 * fonts はハッシュ値に含めるテーマのフォント。recreateAll が true なら、ハッシュ値が一致するスライドも作り直す
 * (プラグインの版が変わり、利用者がすべて作り直すことを選んだとき。計画の KTD10)
 */
export function planSlides(
  slides: readonly Slide[],
  fonts: Theme["fonts"],
  presentation: Presentation,
  recreateAll: boolean,
): SlidePlan {
  // 新しく作った資料は、キーの形でない ID のスライドが 1 枚だけある。そのスライドは最初からあるタイトルのスライドなので消す (計画の R15)。
  // 最初のファイルが失敗しても、再度読み込んだときに同じ条件になるので、やり直しで消せる (U6 を実装するときに決めた)
  const [only] = presentation.slides;
  const initialSlideId =
    presentation.slides.length === 1 && only !== undefined && parseSlideObjectId(only.objectId) === null ? only.objectId : null;

  let current: Current[] = presentation.slides
    .filter((s) => s.objectId !== initialSlideId)
    .map((s) => ({ id: s.objectId, key: parseSlideObjectId(s.objectId)?.key ?? null }));
  const existing = new Map<string, string>();
  for (const s of current) {
    if (s.key === null) continue;
    const before = existing.get(s.key);
    if (before !== undefined) {
      throw new PlanError(`資料に、キー ${s.key} のスライドが 2 枚ある (${before} と ${s.id})。どちらかを Google スライドで消してから、資料を再度読み込む`);
    }
    existing.set(s.key, s.id);
  }

  const outlineKeys = new Set(slides.map((s) => s.key));
  const keys: KeyPlan[] = slides.map((s) => {
    const newId = slideObjectId(s.key, slideHash(s, fonts));
    const oldId = existing.get(s.key) ?? null;
    if (oldId === null) return { key: s.key, action: "create", oldId, newId };
    if (oldId === newId && !recreateAll) return { key: s.key, action: "keep", oldId, newId };
    return { key: s.key, action: "recreate", oldId, newId };
  });
  const removed = current.filter((s) => s.key !== null && !outlineKeys.has(s.key)).map((s) => ({ key: s.key ?? "", objectId: s.id }));
  const untouched = current.filter((s) => s.key === null).map((s) => s.id);

  const steps: SlideStep[] = [];
  if (initialSlideId !== null) steps.push({ kind: "delete", objectId: initialSlideId });
  for (const r of removed) steps.push({ kind: "delete", objectId: r.objectId });
  const removedIds = new Set(removed.map((r) => r.objectId));
  current = current.filter((s) => !removedIds.has(s.id));

  // 資料にあるキーのスライドを、構成案の順序に並べ替える。先頭から順に、あるべき位置に無い集まりを、その位置へ動かす。
  // 前の位置は決まっているので、動かす集まりは常にあるべき位置より後ろにあり、動かす前の順序での位置がそのまま insertionIndex になる
  const { head, byKey } = groups(current);
  let order = current.map((s) => s.id);
  let position = head.length;
  for (const k of keys) {
    const group = byKey.get(k.key);
    if (group === undefined) continue;
    const [first = ""] = group;
    const at = order.indexOf(first);
    if (at !== position) {
      steps.push({ kind: "move", objectIds: group, insertionIndex: position });
      order = order.filter((id) => !group.includes(id));
      order.splice(position, 0, ...group);
    }
    position += group.length;
  }

  // 作る・作り直すスライドを、構成案の順序で処理する。作るスライドは、構成案で 1 つ前のキーの集まりの後ろ
  // (キーの無いスライドが続いていれば、その後ろ) に入れる。前のキーは、この時点で資料にある
  const groupOf = (key: string, id: string): string[] => byKey.get(key) ?? [id];
  let previous: string[] = head;
  for (const [i, k] of keys.entries()) {
    const slide = slides[i];
    if (slide === undefined) continue;
    if (k.action === "create") {
      const last = previous.at(-1);
      const insertionIndex = last === undefined ? 0 : order.indexOf(last) + 1;
      steps.push({ kind: "create", slide, objectId: k.newId, insertionIndex, replaceId: null, replaceFirst: false });
      order.splice(insertionIndex, 0, k.newId);
      byKey.set(k.key, [k.newId]);
    } else if (k.action === "recreate" && k.oldId !== null) {
      // 作り直しは、新しい ID で同じ位置に作り、古いスライドを消す (計画の U6 の Approach 4)
      const insertionIndex = order.indexOf(k.oldId);
      const replaceFirst = k.oldId === k.newId;
      steps.push({ kind: "create", slide, objectId: k.newId, insertionIndex, replaceId: k.oldId, replaceFirst });
      order[insertionIndex] = k.newId;
      byKey.set(k.key, groupOf(k.key, k.oldId).map((id) => (id === k.oldId ? k.newId : id)));
    }
    previous = groupOf(k.key, k.newId);
  }
  return { keys, removed, untouched, initialSlideId, steps };
}
