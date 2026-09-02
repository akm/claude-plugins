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

plugin_cache=%q
root=$(ls -d "$plugin_cache"/*/ 2>/dev/null | sort -V | tail -1)
if [ -z "$root" ]; then
  echo "review-triage プラグインが見つかりません ($plugin_cache)" >&2
  exit 1
fi

exec go run -C "$root/tools/triagecheck" . \
  -current-dir "$script_dir" \
  -record-dir %q \
%s  "$@"
`

// installWrapper はラッパースクリプトを path に書き出す。
//
// recordDir は「ラッパーの置き場 (script_dir) から見た相対パス」に変換して
// 焼き込む。生成時のカレントとラッパーの置き場は違いうるので (例:
// プラグインの展開先から -install-wrapper <リポジトリ>/bin/rtc を実行する)、
// 渡された値をそのまま埋めると、実行時に script_dir 基準で解決されたときに
// 別の場所を指す。両方を絶対にしてから差を取る。
//
// judgmentFlow が明示されていれば絶対パスにして焼き込み、空なら
// -judgment-flow は付けず、プラグイン展開先の既定パス
// (skills/review-triage/references/judgment-flow.md) を使わせる。
func installWrapper(path, recordDir, judgmentFlow string) error {
	pluginCache, err := pluginCacheDir()
	if err != nil {
		return err
	}

	// -install-wrapper は「展開先の tools/triagecheck から」実行する決まりなので
	// (pluginCacheDir がその形を要求する)、生成時のカレントはプラグイン側を指す。
	// そこからの相対と解釈しても利用者の意図には当たらないので、推測せずに弾く —
	// 検査の経路で相対に基準を要求するのと同じ理由。
	if !filepath.IsAbs(recordDir) {
		return fmt.Errorf(
			"-install-wrapper の -record-dir は絶対パスで指定してください (生成時のカレントは"+
				"プラグインの展開先なので、相対パスの基準になりません): %s", recordDir)
	}

	// 焼き込む -record-dir を script_dir 基準の相対にする。
	absPath, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("%s: ラッパーの置き場を解決できません: %w", path, err)
	}
	scriptDir := filepath.Dir(absPath)
	absRecordDir, err := filepath.Abs(recordDir)
	if err != nil {
		return fmt.Errorf("%s: 記録の置き場を解決できません: %w", recordDir, err)
	}
	relRecordDir, err := filepath.Rel(scriptDir, absRecordDir)
	if err != nil {
		return fmt.Errorf(
			"%s: 記録の置き場をラッパーの位置 (%s) からの相対パスにできません: %w", recordDir, scriptDir, err)
	}
	recordDir = filepath.ToSlash(relRecordDir)

	judgmentFlowLine := "  -judgment-flow \"$root/skills/review-triage/references/judgment-flow.md\" \\\n"
	if judgmentFlow != "" {
		// 判定フローはリポジトリの外 (プラグインの展開先) にあるので、script_dir
		// 基準の相対にしても意味が無い。絶対パスで焼き込む。
		absFlow, err := filepath.Abs(judgmentFlow)
		if err != nil {
			return fmt.Errorf("%s: 判定フローのパスを解決できません: %w", judgmentFlow, err)
		}
		judgmentFlowLine = fmt.Sprintf("  -judgment-flow %q \\\n", absFlow)
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
