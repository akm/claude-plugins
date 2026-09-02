// wrapper.go は triagecheck を毎回 go run で起動する薄いシェルスクリプトを
// 書き出す (-install-wrapper)。
//
// プラグインはバイナリを配らず go run で都度実行する運用のため、利用者は
// これまで自分の Makefile に「最新版のプラグイン展開先を探して go run する」
// 定型コードを書いていた (tools/triagecheck/README.md の「Makefile に置く例」)。
// この定型コードそのものをここで生成し、-record-dir 等の値もインストール時に
// 焼き込むことで、呼び出し側は生成されたスクリプトを叩くだけにする。
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// wrapperTemplate はラッパースクリプトの雛形。%s は順に
// (1) PLUGIN_CACHE の値, (2) -record-dir に焼き込む値 (script_dir からの相対),
// (3) -judgment-flow に焼き込む値 (空なら省略) が入る。
//
// -summary-command は焼き込まず、実行時に "$0 -write-summary" を組み立てて渡す。
// サマリの 1 行目に入る案内なので、実際に叩ける形でなければ意味が無い —
// -record-dir と同じ理由で、絶対パスを焼き込むと移動・再クローンで外れる。
//
// 基準には $PWD ではなく script_dir (ラッパー自身の実体の位置) を使う。$PWD は
// シェルが更新する慣習にすぎず、非シェルの親 (CI ランナー・cron・make -C) が
// chdir すると古いままになるので、利用者が叩いた場所を指すとは限らない。
// ラッパーはリポジトリの中に置かれるので自分の位置を知っており、推測が要らない。
//
// ただし「自分の位置」は実体の位置でなければならない。dirname "$0" はリンクを
// 解決しないので、PATH 上などに張ったリンク経由で起動すると基準がリンクの置き場に
// なり、その隣に別の置き場があるとそちらを検査して緑を返す (基準が検査対象から
// 切り離される点で、絶対パスを焼き込む案を退けたのと同じ型)。リンクを辿ってから
// 基準を求める。realpath 一発でも解けるが POSIX ではなく古い macOS に無いため、
// bash 組み込みと readlink だけで済むループを使う。
//
// 置き場を絶対パスで焼き込む案は採らない。リポジトリを移動・再クローンすると
// 移動元を検査して緑を返し、移動先の壊れた記録を見逃す (実測)。
//
// PLUGIN_CACHE の解決 (最新版を拾う) は Makefile の例と同じロジック。ここを
// 変えるときは README の「Makefile に置く例」も合わせて直す。
const wrapperTemplate = `#!/usr/bin/env bash
# review-triage/tools/triagecheck -install-wrapper が生成した。手で編集しない
# (再生成すると上書きされる)。
set -eu -o pipefail

# 基準はこのスクリプト自身の位置。$PWD は叩いた場所によって変わるので使わない。
# シンボリックリンク経由で起動されても実体の位置を採る — dirname "$0" だけでは
# リンクの置き場が基準になり、その隣に別の置き場があるとそちらを検査してしまう。
script_src=$0
while [ -L "$script_src" ]; do
  link_dir=$(cd -P "$(dirname "$script_src")" && pwd)
  script_src=$(readlink "$script_src")
  case $script_src in /*) ;; *) script_src=$link_dir/$script_src;; esac
done
script_dir=$(cd -P "$(dirname "$script_src")" && pwd)

# サマリの再生成手段としてツールに案内させる文字列。利用者がこのラッパーを
# 叩いた形 ($0) をそのまま渡す — 焼き込んだ固定のパスだと、リポジトリを
# 移動・再クローンしたときや、リンク経由で叩かれたときに、案内が実際の
# 呼び出し方と食い違う。
summary_command="$0 -write-summary"

plugin_cache=%q
root=$(ls -d "$plugin_cache"/*/ 2>/dev/null | sort -V | tail -1)
if [ -z "$root" ]; then
  echo "review-triage プラグインが見つかりません ($plugin_cache)" >&2
  exit 1
fi

exec go run -C "$root/tools/triagecheck" . \
  -current-dir "$script_dir" \
  -record-dir %q \
  -summary-command "$summary_command" \
%s  "$@"
`

// installWrapper はラッパースクリプトを path に書き出す。
//
// 3 つの引数はすべて解決済みの絶対パス (規則は run の resolveInputs が経路の
// 分岐より前に当てる)。ここではパスを検査しない — 検査を持つと、検査の経路と
// 別の条件で同じ規則を書き直すことになり、同じ入力に経路ごとに違う契約ができる。
//
// recordDir は「ラッパーの置き場 (script_dir) から見た相対パス」に変換して
// 焼き込む。絶対パスを焼き込まないのは、リポジトリを移動・再クローンすると
// 移動元を検査して緑を返すため。
//
// judgmentFlow が非空なら絶対パスのまま焼き込み、空なら -judgment-flow は付けず、
// プラグイン展開先の既定パス (skills/review-triage/references/judgment-flow.md) を
// 実行時に $root から解決させる。空になるのは省略したときだけで、明示した空は
// resolveInputs が弾く。
func installWrapper(path, recordDir, judgmentFlow string) error {
	pluginCache, err := pluginCacheDir()
	if err != nil {
		return err
	}

	// 焼き込む -record-dir を script_dir 基準の相対にする。
	scriptDir := filepath.Dir(path)
	relRecordDir, err := filepath.Rel(scriptDir, recordDir)
	if err != nil {
		return fmt.Errorf(
			"%s: 記録の置き場をラッパーの位置 (%s) からの相対パスにできません: %w", recordDir, scriptDir, err)
	}
	recordDir = filepath.ToSlash(relRecordDir)

	judgmentFlowLine := "  -judgment-flow \"$root/skills/review-triage/references/judgment-flow.md\" \\\n"
	if judgmentFlow != "" {
		// 判定フローはリポジトリの外 (プラグインの展開先) にあるので、script_dir
		// 基準の相対にしても意味が無い。絶対パスで焼き込む。
		judgmentFlowLine = fmt.Sprintf("  -judgment-flow %q \\\n", judgmentFlow)
	}

	script := fmt.Sprintf(wrapperTemplate, pluginCache, recordDir, judgmentFlowLine)

	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("%s: 置き場の作成に失敗しました: %w", dir, err)
		}
	}
	// 0o755: シェルスクリプトなので実行権限を付ける。
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		return fmt.Errorf("%s: 書き出しに失敗しました: %w", path, err)
	}
	fmt.Printf("生成: %s (record-dir: %s)\n", path, recordDir)
	return nil
}

// pluginCacheDir はこのプロセス自身の実行位置 (go run -C <展開先>/tools/triagecheck)
// から、プラグインキャッシュのルート (.../review-triage/ — 版のディレクトリの
// 1 つ上) を逆算する。
//
// 値を書き出す側でここを決め打ちにせず実行位置から逆算するのは、開発中の
// チェックアウトから -install-wrapper を実行した場合でも、実際に go run が
// 動いた場所を正として書き出すため (決め打ちだと実体と食い違ったパスを
// 書き出しかねない)。
func pluginCacheDir() (string, error) {
	wd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("実行位置の取得に失敗しました: %w", err)
	}
	wd = filepath.ToSlash(wd)
	// go run -C は指定ディレクトリに cd してから実行するため、Getwd は
	// "<何か>/tools/triagecheck" になっているはずである。
	const suffix = "/tools/triagecheck"
	if !strings.HasSuffix(wd, suffix) {
		return "", fmt.Errorf(
			"-install-wrapper は `go run -C <展開先>/tools/triagecheck . -install-wrapper ...` の形でだけ使える (現在位置: %s)", wd)
	}
	pluginRoot := strings.TrimSuffix(wd, suffix)
	// pluginRoot は ".../review-triage/0.1.0" のような版ディレクトリなので、
	// その親 (版ごとのディレクトリが並ぶ場所) をキャッシュのルートとする。
	return filepath.Dir(filepath.FromSlash(pluginRoot)), nil
}
