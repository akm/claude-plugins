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
// (1) PLUGIN_CACHE の値, (2) -record-dir に焼き込む値, (3) -judgment-flow に
// 焼き込む値 (空なら省略) が入る。
//
// PLUGIN_CACHE の解決 (最新版を拾う) は Makefile の例と同じロジック。ここを
// 変えるときは README の「Makefile に置く例」も合わせて直す。
const wrapperTemplate = `#!/usr/bin/env bash
# review-triage/tools/triagecheck -install-wrapper が生成した。手で編集しない
# (再生成すると上書きされる)。
set -eu -o pipefail

plugin_cache=%q
root=$(ls -d "$plugin_cache"/*/ 2>/dev/null | sort -V | tail -1)
if [ -z "$root" ]; then
  echo "review-triage プラグインが見つかりません ($plugin_cache)" >&2
  exit 1
fi

exec go run -C "$root/tools/triagecheck" . \
  -record-dir %q \
%s  "$@"
`

// installWrapper はラッパースクリプトを path に書き出す。recordDir は
// 呼び出し時点の -record-dir の値をそのまま焼き込む (相対パスならカレント
// ディレクトリ基準のまま埋め込まれる — 呼び出し元が意図して相対指定した
// ときにそれを尊重するため、ここで絶対パス化はしない)。
//
// judgmentFlow が明示されていれば同様に焼き込み、空なら
// -judgment-flow は付けず、プラグイン展開先の既定パス
// (skills/review-triage/references/judgment-flow.md) を使わせる。
func installWrapper(path, recordDir, judgmentFlow string) error {
	pluginCache, err := pluginCacheDir()
	if err != nil {
		return err
	}

	judgmentFlowLine := "  -judgment-flow \"$root/skills/review-triage/references/judgment-flow.md\" \\\n"
	if judgmentFlow != "" {
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
