package main

import (
	"os"
	"os/exec"
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

	// 焼き込む値は実在していること (installWrapper が生成の時点で実在を要求する)。
	recDir := filepath.Join(base, "docs", "review-triages")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, recDir, ""); err != nil {
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

	// -record-dir は script_dir (ラッパーの置き場) からの相対で焼き込まれる。
	// 生成時のカレント (プラグインの展開先) 基準ではない。
	if !strings.Contains(got, `-record-dir "../docs/review-triages"`) {
		t.Errorf("生成物に script_dir 基準の -record-dir が見当たらない:\n%s", got)
	}
	// 基準は $PWD でなく script_dir。$PWD だと叩く場所で見る先が変わる。
	if !strings.Contains(got, `-current-dir "$script_dir"`) {
		t.Errorf("生成物が script_dir を基準にしていない:\n%s", got)
	}
	if strings.Contains(got, `"$PWD"`) {
		t.Errorf("生成物が $PWD に依存している:\n%s", got)
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

	// 焼き込む値は実在していること (installWrapper が生成の時点で実在を要求する)。
	// このテストが見るのは「明示した値が既定パスに優先すること」なので、
	// 値が実在するかどうかは意図の外 — 実在させたうえで優先を確かめる。
	recDir := filepath.Join(base, "docs", "review-triages")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	customFlow := filepath.Join(base, "custom", "judgment-flow.md")
	if err := os.MkdirAll(filepath.Dir(customFlow), 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := os.WriteFile(customFlow, []byte("# 判定フロー\n"), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, recDir, customFlow); err != nil {
			t.Fatalf("installWrapper: %v", err)
		}
	})

	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	got := string(data)
	if !strings.Contains(got, `-judgment-flow "`+customFlow+`"`) {
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
	// 作られるのは出力先の親だけで、焼き込む値 (-record-dir) は実在を要求される。
	outPath := filepath.Join(base, "not-yet-created", "bin", "review-triage-check")
	recDir := filepath.Join(base, "docs", "review-triages")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	withWorkingDir(t, versionDir, func() {
		if err := installWrapper(outPath, recDir, ""); err != nil {
			t.Fatalf("installWrapper: %v", err)
		}
	})

	if _, err := os.Stat(outPath); err != nil {
		t.Errorf("親ディレクトリが作られず書き出しに失敗している: %v", err)
	}
}

// 生成したラッパーを実際に実行して、正しい置き場を検査することを固定する。
//
// 文字列だけを検査していたため、-current-dir の焼き込みを壊しても全テストが
// 通っていた。生成物の契約 (どこから叩いても同じ置き場を見る) は、実行して
// 初めて確かめられる。
func TestInstallWrapperGeneratesRunnableScript(t *testing.T) {
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go が PATH に無いので実行は確かめられない")
	}
	toolDir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	// pluginCacheDir は <展開先>/tools/triagecheck の形を要求するので、その配置を作る。
	// ツール本体と skills はこのリポジトリのものを指すシンボリックリンクで足りる。
	base := realTempDir(t)
	version := filepath.Join(base, "cache", "review-triage", "0.0.1")
	if err := os.MkdirAll(filepath.Join(version, "tools"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(toolDir, filepath.Join(version, "tools", "triagecheck")); err != nil {
		t.Fatal(err)
	}
	skillsSrc := filepath.Join(toolDir, "..", "..", "skills")
	if err := os.Symlink(skillsSrc, filepath.Join(version, "skills")); err != nil {
		t.Fatal(err)
	}

	// 利用者のリポジトリ。記録の置き場を実在させる。
	repo := filepath.Join(base, "repo")
	recDir := filepath.Join(repo, "docs", "review-triages")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatal(err)
	}
	wrapper := filepath.Join(repo, "bin", "rtc")

	// 生成は「展開先の tools/triagecheck から」行う (pluginCacheDir の前提)。
	t.Chdir(filepath.Join(version, "tools", "triagecheck"))
	if err := installWrapper(wrapper, recDir, ""); err != nil {
		t.Fatalf("ラッパーの生成に失敗: %v", err)
	}

	// 叩く場所を変えても同じ置き場を検査すること。$PWD 基準だとここで割れる。
	elsewhere := realTempDir(t)
	for _, dir := range []string{repo, elsewhere, base} {
		cmd := exec.Command(wrapper)
		cmd.Dir = dir
		cmd.Env = append(os.Environ(), "PATH="+filepath.Dir(goBin)+":"+os.Getenv("PATH"))
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("%s から実行して失敗した: %v\n%s", dir, err, out)
		}
	}

	// 置き場に壊れた記録を置いたら、どこから叩いても検出すること
	// (実行はしているが対象が違う、を捕まえる)。
	if err := os.WriteFile(filepath.Join(recDir, "bad.yaml"), []byte("broken: yes\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, dir := range []string{repo, elsewhere} {
		cmd := exec.Command(wrapper)
		cmd.Dir = dir
		cmd.Env = append(os.Environ(), "PATH="+filepath.Dir(goBin)+":"+os.Getenv("PATH"))
		if out, err := cmd.CombinedOutput(); err == nil {
			t.Fatalf("%s から実行したとき、壊れた記録を見逃した:\n%s", dir, out)
		}
	}

	// シンボリックリンク経由で起動しても実体の置き場を検査すること。
	// dirname "$0" だけで基準を求めるとリンクの置き場が基準になり、その隣に
	// 別の置き場があるとそちらを検査して緑になる (実測でそうなった)。
	// リンクの隣に紛らわしい置き場を実在させたうえで確かめる。
	linkDir := filepath.Join(realTempDir(t), "localbin")
	if err := os.MkdirAll(linkDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// ラッパーは <置き場の親>/bin にあり -record-dir は ../docs/review-triages。
	// リンクの親から見た同じ相対位置に、空の (壊れていない) 置き場を作る。
	decoy := filepath.Join(filepath.Dir(linkDir), "docs", "review-triages")
	if err := os.MkdirAll(decoy, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(linkDir, "rtc")
	if err := os.Symlink(wrapper, link); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(link)
	cmd.Dir = linkDir
	cmd.Env = append(os.Environ(), "PATH="+filepath.Dir(goBin)+":"+os.Getenv("PATH"))
	if out, err := cmd.CombinedOutput(); err == nil {
		t.Fatalf("リンク経由で実行したとき、実体の置き場の壊れた記録を見逃した"+
			" (隣の囮を検査している):\n%s", out)
	}

	// 経路のディレクトリ自体がシンボリックリンクでも、実体側の置き場を検査すること。
	// cd -P が cd -L に変わると解決先がリンク側へ割れ、隣の囮を検査して緑になる。
	// ラッパーそのものはリンクでないので、上の [ -L ] のループでは捕まらない経路。
	//
	// リンクは bin ディレクトリに張る。リポジトリごとリンクすると、リンク側から見た
	// ../docs もリンクを通って実体側に戻ってしまい、囮に届かない (-L との差が出ない)。
	viaBase := realTempDir(t)
	if err := os.Symlink(filepath.Join(repo, "bin"), filepath.Join(viaBase, "bin")); err != nil {
		t.Fatal(err)
	}
	// リンク側から見た ../docs/review-triages に、壊れていない囮の置き場を作る。
	if err := os.MkdirAll(filepath.Join(viaBase, "docs", "review-triages"), 0o755); err != nil {
		t.Fatal(err)
	}
	cmd = exec.Command(filepath.Join(viaBase, "bin", "rtc"))
	cmd.Dir = viaBase
	cmd.Env = append(os.Environ(), "PATH="+filepath.Dir(goBin)+":"+os.Getenv("PATH"))
	if out, err := cmd.CombinedOutput(); err == nil {
		t.Fatalf("経路のディレクトリがリンクのとき、実体の置き場の壊れた記録を見逃した"+
			" (cd -P が効いていない):\n%s", out)
	}
}
