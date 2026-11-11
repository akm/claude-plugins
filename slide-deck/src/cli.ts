// プラグイン slide-deck のスキルが実行する入口。
// サブコマンドごとの --help が、引数・出力・終了コードの SSOT (計画 docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md の KTD17)。
// 終了コードは、どのサブコマンドも、成功 0・検査の指摘あり 1・実行の誤り (ライブラリが無い・入力の形が違うなど) 2 に分ける。

import { parseArgs } from "node:util";
import { formatStatus, inspect, install, REQUIRED_NODE_MAJOR, SetupError, statusExitCode } from "./setup/setup.ts";

const USAGE_PREFIX = "使い方: node <プラグインのディレクトリ>/src/cli.ts";

const CACHE_DIR_HELP = `キャッシュのディレクトリ:
  環境変数 SLIDE_DECK_CACHE_DIR があればその場所そのもの、無ければ $XDG_CACHE_HOME/akm-claude-plugins/slide-deck
  (XDG_CACHE_HOME も無ければ ~/.cache/akm-claude-plugins/slide-deck)。
  venv は venv-<ハッシュ値>/ に、node_modules は node-<ハッシュ値>/node_modules/ に入れる。ハッシュ値は、venv が
  プラグインの uv.lock と .python-version の内容から、node_modules が package-lock.json の内容から求めた SHA-256 の先頭 16 文字。
  ロックファイルを変えないバージョンのプラグインどうしは、同じものを使う。`;

interface Command {
  readonly summary: string;
  readonly help: string;
  readonly run: () => number;
}

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

終了コード:
  0  venv と node_modules がどちらも入っている
  1  入れるものがある (setup install で入れられる)
  2  入れられない。Node.js が ${String(REQUIRED_NODE_MAJOR)} 未満、入れるのに要る uv か npm が PATH に無い、node_modules のディレクトリが壊れている、
     のどれか。出力の「入れられない理由:」に直し方を示す
`,
    run: () => {
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
     npm ci の失敗では一時的な名前のディレクトリを消す。uv sync の失敗では、venv をフラグファイルを作らずに残す
`,
    run: () => {
      install({ log: (line) => process.stdout.write(`${line}\n`) });
      return 0;
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

function main(argv: readonly string[]): number {
  let help: boolean;
  let positionals: string[];
  try {
    const parsed = parseArgs({
      args: [...argv],
      options: { help: { type: "boolean", short: "h" } },
      allowPositionals: true,
      strict: true,
    });
    help = parsed.values.help ?? false;
    positionals = parsed.positionals;
  } catch (e) {
    process.stderr.write(`${e instanceof Error ? e.message : String(e)}\n\n${TOP_HELP}`);
    return 2;
  }
  const name = positionals.join(" ");
  const command = COMMANDS[name];
  if (command === undefined) {
    if (help && (name === "" || name === "setup")) {
      process.stdout.write(TOP_HELP);
      return 0;
    }
    process.stderr.write(`${name === "" ? "サブコマンドを指定する" : `存在しないサブコマンド: ${name}`}\n\n${TOP_HELP}`);
    return 2;
  }
  if (help) {
    process.stdout.write(command.help);
    return 0;
  }
  try {
    return command.run();
  } catch (e) {
    // 想定していない誤りも、終了コード 1 (検査の指摘あり) と区別できるよう、実行の誤り 2 にする
    process.stderr.write(`${e instanceof SetupError ? e.message : e instanceof Error ? (e.stack ?? e.message) : String(e)}\n`);
    return 2;
  }
}

process.exitCode = main(process.argv.slice(2));
