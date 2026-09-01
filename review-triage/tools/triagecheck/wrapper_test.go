package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// realTempDir は t.TempDir() をシンボリックリンク解決した実パスで返す。
// pluginCacheDir は os.Getwd() (カーネルが返す実パス) から逆算するため、
// macOS で /var が /private/var のシンボリックリンクである環境では、
// t.TempDir() の生の値と文字列比較すると表記だけが違って一致しない。
func realTempDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	resolved, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatalf("EvalSymlinks(%s): %v", dir, err)
	}
	return resolved
}

// withWorkingDir は dir に一時的に cd してから fn を実行し、元のディレクトリに戻す。
// pluginCacheDir は os.Getwd() の値から逆算するため、テストでは実際にカレント
// ディレクトリを動かす必要がある。
func withWorkingDir(t *testing.T, dir string, fn func()) {
	t.Helper()
	orig, err := os.Getwd()
	if err != nil {
		t.Fatalf("Getwd: %v", err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatalf("Chdir(%s): %v", dir, err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(orig); err != nil {
			t.Fatalf("Chdir 復帰に失敗: %v", err)
		}
	})
	fn()
}

func TestPluginCacheDirResolvesFromVersionedLayout(t *testing.T) {
	// 実際のプラグインキャッシュの配置 (.../review-triage/<版>/tools/triagecheck)
	// を模した一時ディレクトリを作り、そこから実行したときに版ディレクトリの
	// 1 つ上 (.../review-triage) が返ることを確かめる。
	base := realTempDir(t)
	pluginRoot := filepath.Join(base, "cache", "akm-claude-plugins", "review-triage")
	versionDir := filepath.Join(pluginRoot, "0.1.0", "tools", "triagecheck")
	if err := os.MkdirAll(versionDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	var got string
	withWorkingDir(t, versionDir, func() {
		var err error
		got, err = pluginCacheDir()
		if err != nil {
			t.Fatalf("pluginCacheDir: %v", err)
		}
	})

	want := filepath.Join(pluginRoot)
	if got != want {
		t.Errorf("pluginCacheDir() = %q, want %q", got, want)
	}
}

func TestPluginCacheDirRejectsUnexpectedLayout(t *testing.T) {
	// tools/triagecheck で終わらない場所 (go run -C を経ずに直接 go run . した
	// ときなど、プラグインキャッシュと無関係な場所) では、実体と食い違ったパスを
	// 黙って書き出す代わりにエラーにする。
	dir := t.TempDir()

	withWorkingDir(t, dir, func() {
		_, err := pluginCacheDir()
		if err == nil {
			t.Fatal("pluginCacheDir: エラーを期待したが nil だった")
		}
		if !strings.Contains(err.Error(), "-install-wrapper") {
			t.Errorf("エラーメッセージに -install-wrapper の使い方が含まれていない: %v", err)
		}
	})
}

func TestInstallWrapperWritesExecutableScript(t *testing.T) {
	base := realTempDir(t)
	pluginRoot := filepath.Join(base, "cache", "akm-claude-plugins", "review-triage")
	versionDir := filepath.Join(pluginRoot, "0.1.0", "tools", "triagecheck")
	if err := os.MkdirAll(versionDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	outPath := filepath.Join(base, "bin", "review-triage-check")

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, "docs/review-triages", ""); err != nil {
			t.Fatalf("installWrapper: %v", err)
		}
	})

	info, err := os.Stat(outPath)
	if err != nil {
		t.Fatalf("Stat(%s): %v", outPath, err)
	}
	if info.Mode()&0o111 == 0 {
		t.Errorf("生成したスクリプトに実行権限が無い: mode=%v", info.Mode())
	}

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	got := string(data)

	// -record-dir はそのまま焼き込まれる。
	if !strings.Contains(got, `-record-dir "docs/review-triages"`) {
		t.Errorf("生成物に -record-dir の焼き込みが見当たらない:\n%s", got)
	}
	// plugin_cache は版ディレクトリの 1 つ上を指す。
	wantCache := `plugin_cache="` + pluginRoot + `"`
	if !strings.Contains(got, wantCache) {
		t.Errorf("生成物に想定した plugin_cache が見当たらない (want substring %q):\n%s", wantCache, got)
	}
	// -judgment-flow を明示しなかったときは、$root からの既定パスを使う。
	if !strings.Contains(got, `-judgment-flow "$root/skills/review-triage/references/judgment-flow.md"`) {
		t.Errorf("生成物に -judgment-flow の既定値が見当たらない:\n%s", got)
	}
}

func TestInstallWrapperEmbedsExplicitJudgmentFlow(t *testing.T) {
	base := t.TempDir()
	versionDir := filepath.Join(base, "cache", "akm-claude-plugins", "review-triage", "0.1.0", "tools", "triagecheck")
	if err := os.MkdirAll(versionDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	outPath := filepath.Join(base, "bin", "review-triage-check")

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, "docs/review-triages", "/custom/judgment-flow.md"); err != nil {
			t.Fatalf("installWrapper: %v", err)
		}
	})

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	got := string(data)
	if !strings.Contains(got, `-judgment-flow "/custom/judgment-flow.md"`) {
		t.Errorf("生成物に明示した -judgment-flow の焼き込みが見当たらない:\n%s", got)
	}
	// 明示したときは $root からの既定パスを使わない (二重に書かれない)。
	if strings.Contains(got, `"$root/skills/review-triage/references/judgment-flow.md"`) {
		t.Errorf("明示指定があるのに既定パスも書かれている:\n%s", got)
	}
}

func TestInstallWrapperCreatesParentDirectory(t *testing.T) {
	base := t.TempDir()
	versionDir := filepath.Join(base, "cache", "akm-claude-plugins", "review-triage", "0.1.0", "tools", "triagecheck")
	if err := os.MkdirAll(versionDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	// bin/ はまだ存在しない。installWrapper が作る必要がある。
	outPath := filepath.Join(base, "not-yet-created", "bin", "review-triage-check")

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, "docs/review-triages", ""); err != nil {
			t.Fatalf("installWrapper: %v", err)
		}
	})

	if _, err := os.Stat(outPath); err != nil {
		t.Errorf("親ディレクトリが作られず書き出しに失敗している: %v", err)
	}
}
