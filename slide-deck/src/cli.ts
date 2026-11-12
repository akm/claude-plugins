// プラグイン slide-deck のスキルが実行する入口。
// サブコマンドごとの --help が、引数・出力・終了コードの SSOT (計画 docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md の KTD17)。
// 終了コードは、どのサブコマンドも、成功 0・検査の指摘あり 1・実行の誤り (ライブラリが無い・入力の形が違うなど) 2 に分ける。

import { parseArgs } from "node:util";
import { checkDeck, ExecutionError, formatCheckReport } from "./check/deck.ts";
import { formatStatus, inspect, install, REQUIRED_NODE_MAJOR, SetupError, statusExitCode } from "./setup/setup.ts";

const USAGE_PREFIX = "使い方: node <プラグインのディレクトリ>/src/cli.ts";

const CACHE_DIR_HELP = `キャッシュのディレクトリ:
  環境変数 SLIDE_DECK_CACHE_DIR があればその場所そのもの、無ければ $XDG_CACHE_HOME/akm-claude-plugins/slide-deck
  (XDG_CACHE_HOME も無ければ ~/.cache/akm-claude-plugins/slide-deck)。
  venv は venv-<ハッシュ値>/ に、node_modules は node-<ハッシュ値>/node_modules/ に入れる。ハッシュ値は、venv が
  プラグインの uv.lock と .python-version の内容から、node_modules が package-lock.json の内容から求めた SHA-256 の先頭 16 文字。
  ロックファイルを変えないバージョンのプラグインどうしは、同じものを使う。`;

/** サブコマンドの名前の後の引数 */
interface CommandArgs {
  /** サブコマンドの名前の後の、位置で決まる引数 */
  readonly positionals: readonly string[];
  /** --pptx-skill の値 (サブコマンド pptx だけが使う) */
  readonly pptxSkill: string | undefined;
}

interface Command {
  readonly summary: string;
  readonly help: string;
  readonly run: (args: CommandArgs) => number | Promise<number>;
}

/** 引数の誤り。入口は、誤りとサブコマンドの説明を示して終了コード 2 にする */
class UsageError extends Error {
  override name = "UsageError";
}

/** 位置で決まる引数の数と、使えないオプションを検査する */
function expectArgs(args: CommandArgs, names: readonly string[], allowPptxSkill = false): void {
  if (args.positionals.length !== names.length) {
    throw new UsageError(
      names.length === 0
        ? `引数は要らない (渡された引数: ${args.positionals.join(" ")})`
        : `引数 ${names.join(" ")} を指定する (渡された引数の数: ${String(args.positionals.length)})`,
    );
  }
  if (!allowPptxSkill && args.pptxSkill !== undefined) {
    throw new UsageError("--pptx-skill は、サブコマンド pptx だけで使う");
  }
}

const CHECK_STEPS = `  1. 構成案の書式の誤りと、【提案】が付いたままのスライド
  2. deck.ts を tsc と eslint で検査する。規則はプラグインのコードと同じ tseslint.configs.strictTypeChecked で、
     明示の any を禁止する。tsc は build/tsconfig.json を使い、資料のディレクトリより上の tsconfig.json は使わない。
     deck.ts が関数を default export していないか、その関数が型 DeckScript に合わないときも、tsc が指摘する。
     指摘があれば、3 以降を行わない
  3. deck.ts を実行し、テーマの値 (色の値の形・空の名前) を検査する
  4. 構成案と deck.ts のキーの突き合わせ (構成案にだけあるキー・deck.ts にだけあるキー・deck.ts で 2 回以上図を作ったキー)。
     構成案に書式の誤りがあれば行わない
  5. 文字が箱からはみ出しそうな箇所の見積もり (題名・deck.ts の要素の文字・一言)。キーが一致し、テーマに誤りが無いときだけ行う
検査の前に、資料のディレクトリに build/ を作り、.gitignore (内容は *。生成したファイルをコミットに入れない)・tsconfig.json・
deck-type.ts を書く。tsc と eslint は、キャッシュのディレクトリの node_modules のものを使う (setup install で入れる)。`;

const CHECK_OUTPUT = `  指摘が無ければ「検査の指摘は無い (スライド <枚数> 枚)」。
  指摘があれば、種類ごとに、見出しの行と、字下げした指摘の行を示す。tsc と eslint の指摘は、ツールの出力をそのまま示す。
  はみ出しそうな箇所は、キー・要素 (題名・一言・deck.ts の要素の添字)・要る高さ・文字を置ける高さ (インチ)・文字の先頭 40 文字を示す。`;

const COMMANDS: Readonly<Record<string, Command>> = {
  "setup status": {
    summary: "ライブラリがキャッシュのディレクトリに入っているかと、取得するものを示す (何も入れない)",
    help: `${USAGE_PREFIX} setup status

ライブラリ (Python の venv と Node.js の node_modules) が、キャッシュのディレクトリに入っているかを示す。何も入れない。
スキルは、入れるものがあれば (終了コード 1)、出力の「取得するもの」とキャッシュのディレクトリを利用者に示して承認を得てから、
setup install を実行する。

${CACHE_DIR_HELP}

引数:
  なし。--help (-h) でこの説明を示す。

出力 (標準出力):
  キャッシュのディレクトリ、Node.js のバージョン、uv と npm のパス (無ければ「無い」)、
  venv と node_modules の状態とパス。状態は次のどれか。
    入っている
    無い
    作りかけ (venv だけ。ディレクトリがあるのにフラグファイル installed が無い。setup install が uv sync をやり直す)
    壊れている (node_modules だけ。node-<ハッシュ値>/ があるのに node_modules/.package-lock.json が無い)
  入れるものがあれば「取得するもの:」の後に、取得するもの (Python のバージョンと、ロックファイルのバージョンのパッケージ) を示す。
  入れられない理由があれば「入れられない理由:」の後に、理由と直し方を示す。
  setup install が npm ci の途中で強制終了されて残った一時的な名前のディレクトリ (node-<ハッシュ値>.<6 文字>) があれば、
  「残っている一時的なディレクトリ」の後にそのパスを示す。setup install を実行していなければ消してよい。終了コードには影響しない。

終了コード:
  0  venv と node_modules がどちらも入っている
  1  入れるものがある (setup install で入れられる)
  2  入れられない。Node.js が ${String(REQUIRED_NODE_MAJOR)} 未満、入れるのに要る uv か npm が PATH に無い、node_modules のディレクトリが壊れている、
     のどれか。出力の「入れられない理由:」に直し方を示す
`,
    run: (args) => {
      expectArgs(args, []);
      const report = inspect();
      process.stdout.write(formatStatus(report));
      return statusExitCode(report);
    },
  },
  "setup install": {
    summary: "入っていないライブラリだけを、キャッシュのディレクトリに入れる",
    help: `${USAGE_PREFIX} setup install

入っていないライブラリだけを、プラグインに同梱したロックファイルのバージョンで、キャッシュのディレクトリに入れる。
入っているものには何もしない。スキルは、setup status の結果を利用者に示して承認を得てから実行する。
  venv:         uv sync --frozen --no-dev を、環境変数 UV_PROJECT_ENVIRONMENT に venv-<ハッシュ値>/ を指定して実行し、
                完了したらフラグファイル installed を作る。作りかけの venv (フラグファイルが無い) は、uv sync をやり直す。
  node_modules: 一時的な名前のディレクトリで npm ci --omit=dev を実行し、完了したら node-<ハッシュ値>/ に改名する。
                改名の前に、同時に実行した別の setup install が node-<ハッシュ値>/ を作り終えていたら、入ったものとして扱う。

${CACHE_DIR_HELP}

引数:
  なし。--help (-h) でこの説明を示す。

出力:
  標準出力に、実行することと、入れたディレクトリを示す。
  失敗したときは、標準エラー出力に理由と直し方を示す。uv sync か npm ci が失敗したときは、その標準エラー出力も示す。

終了コード:
  0  入れた (入れるものが無かったときを含む)
  2  入れられない (setup status の終了コード 2 と同じ条件)。何も入れずに終了する。
     または、uv sync か npm ci が失敗した。別の方法を試さずに、失敗した時点で終了する。
     npm ci の失敗では一時的な名前のディレクトリを消す。uv sync の失敗では、venv のディレクトリができていれば、
     フラグファイルを作らずに残す (失敗の文が、残したか、作る前に失敗したかを示す)
`,
    run: (args) => {
      expectArgs(args, []);
      install({ log: (line) => process.stdout.write(`${line}\n`) });
      return 0;
    },
  },
  check: {
    summary: "資料のディレクトリの構成案と deck.ts を検査する (PowerPoint のファイルは書かない)",
    help: `${USAGE_PREFIX} check <資料のディレクトリ>

資料のディレクトリの構成案 outline.md と資料ごとのスクリプト deck.ts を、次の順に検査する。PowerPoint のファイルは書かない。
${CHECK_STEPS}

${CACHE_DIR_HELP}

引数:
  <資料のディレクトリ>  outline.md と deck.ts があるディレクトリ
  --help (-h) でこの説明を示す。

出力 (標準出力):
${CHECK_OUTPUT}
  実行の誤りは、標準エラー出力に理由を示す。

終了コード:
  0  指摘が無い
  1  指摘がある (構成案の書式の誤り・【提案】の残り・tsc か eslint の指摘・deck.ts の実行の誤り・テーマの誤り・キーの不一致・
     はみ出しそうな箇所)
  2  実行の誤り。資料のディレクトリか、outline.md・deck.ts が無い。node_modules がキャッシュのディレクトリに入っていない
     (setup status で確認する)。tsc か eslint を実行できないか、指摘以外の理由で失敗した。引数が違う
`,
    run: async (args) => {
      expectArgs(args, ["<資料のディレクトリ>"]);
      const [deckDir = ""] = args.positionals;
      const report = await checkDeck(deckDir);
      process.stdout.write(formatCheckReport(report));
      return report.deck === null ? 1 : 0;
    },
  },
};

const TOP_HELP = `${USAGE_PREFIX} <サブコマンド> [--help]

サブコマンド:
${Object.entries(COMMANDS)
  .map(([name, c]) => `  ${name.padEnd(14)} ${c.summary}`)
  .join("\n")}

サブコマンドごとの引数・出力・終了コードは、<サブコマンド> --help で示す。
`;

/** 位置で決まる引数の先頭から、サブコマンドの名前を探す。名前の語の数が多いものを優先する */
function findCommand(positionals: readonly string[]): { name: string; command: Command; rest: string[] } | undefined {
  for (let n = Math.min(2, positionals.length); n >= 1; n--) {
    const name = positionals.slice(0, n).join(" ");
    const command = COMMANDS[name];
    if (command !== undefined) return { name, command, rest: positionals.slice(n) };
  }
  return undefined;
}

async function main(argv: readonly string[]): Promise<number> {
  let help: boolean;
  let positionals: string[];
  let pptxSkill: string | undefined;
  try {
    const parsed = parseArgs({
      args: [...argv],
      options: { help: { type: "boolean", short: "h" }, "pptx-skill": { type: "string" } },
      allowPositionals: true,
      strict: true,
    });
    help = parsed.values.help ?? false;
    positionals = parsed.positionals;
    pptxSkill = parsed.values["pptx-skill"];
  } catch (e) {
    process.stderr.write(`${e instanceof Error ? e.message : String(e)}\n\n${TOP_HELP}`);
    return 2;
  }
  const found = findCommand(positionals);
  if (found === undefined) {
    const name = positionals.join(" ");
    if (help && (name === "" || name === "setup")) {
      process.stdout.write(TOP_HELP);
      return 0;
    }
    process.stderr.write(`${name === "" ? "サブコマンドを指定する" : `存在しないサブコマンド: ${name}`}\n\n${TOP_HELP}`);
    return 2;
  }
  const { command } = found;
  if (help) {
    process.stdout.write(command.help);
    return 0;
  }
  try {
    return await command.run({ positionals: found.rest, pptxSkill });
  } catch (e) {
    if (e instanceof UsageError) {
      process.stderr.write(`${e.message}\n\n${command.help}`);
      return 2;
    }
    // 想定していない誤りも、終了コード 1 (検査の指摘あり) と区別できるよう、実行の誤り 2 にする
    const known = e instanceof SetupError || e instanceof ExecutionError;
    process.stderr.write(`${known ? e.message : e instanceof Error ? (e.stack ?? e.message) : String(e)}\n`);
    return 2;
  }
}

process.exitCode = await main(process.argv.slice(2));
