package main

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// run はパッケージ変数 (reviewTriageDir / judgmentFlowPath) を書き換えるので、
// テストの間だけ退避して戻す。戻さないと後続のテストが前のテストの指定を引き継ぐ。
func withRunGlobals(t *testing.T) {
	t.Helper()
	dir, flow := reviewTriageDir, judgmentFlowPath
	t.Cleanup(func() { reviewTriageDir, judgmentFlowPath = dir, flow })
}

// 指定した置き場・判定フローが存在しないなら、run は非 0 (error) で終わる。
// 「検査が走って合格した」と「そもそも走らなかった」を区別できるようにするための
// 中核の挙動なので、入口 (run) の側でも固定する。
// 判定はエラーが返ること自体で行い、報告メッセージの文言には結合しない。
// 文言で判定すると、挙動を変えない書式の変更だけで落ちる (偽の赤)。
// 報告の本文は stderr に出るので err.Error() には載らず、文言に頼ると実質
// 「書式が変わっていないこと」を検査するテストになる。
func TestRunFailsOnMissingExplicitPaths(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "no-such")
	cases := []struct {
		name string
		args []string
	}{
		{"record-dir が不在", []string{"-record-dir", missing}},
		{"judgment-flow が不在", []string{"-judgment-flow", filepath.Join(missing, "judgment-flow.md")}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			withRunGlobals(t)
			if err := run(tc.args); err == nil {
				t.Fatal("不在のパスを指定したのにエラーにならなかった")
			}
		})
	}
}

// -judgment-flow は省略できる。CLAUDE_PLUGIN_ROOT からも解決できないときは
// 検査対象が無い状態として通す (判定フローはリポジトリ外にあるため)。
func TestRunPassesWhenJudgmentFlowUnavailable(t *testing.T) {
	withRunGlobals(t)
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	if err := run([]string{"-record-dir", recs}); err != nil {
		t.Fatalf("判定フローが無い状態で落ちた: %v", err)
	}
}

// CLAUDE_PLUGIN_ROOT が指す判定フローが無いなら報告する。プラグイン側がファイルを
// 移動・改名したとき、利用側の CI は何も変えていないのに守りだけが外れる型を塞ぐ。
func TestRunFailsWhenPluginRootFlowMissing(t *testing.T) {
	withRunGlobals(t)
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Chdir(t.TempDir())
	t.Cleanup(func() { _ = os.Chdir(cwd) })
	t.Setenv("CLAUDE_PLUGIN_ROOT", filepath.Join(t.TempDir(), "no-such-plugin"))
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}

	if err := run([]string{"-record-dir", recs}); err == nil {
		t.Fatal("CLAUDE_PLUGIN_ROOT が指す判定フローが無いのに緑になった")
	}
}

// 相対パスの基準は推測せず -current-dir で明示させる。基準そのものは絶対で
// 実在するディレクトリでなければならない (基準の基準が要る状態を作らないため)。
func TestResolveBaseDir(t *testing.T) {
	dir := t.TempDir()
	t.Run("絶対で実在するなら通る", func(t *testing.T) {
		got, err := resolveBaseDir(dir)
		if err != nil || got != dir {
			t.Fatalf("got (%q, %v)", got, err)
		}
	})
	t.Run("指定が無ければ空", func(t *testing.T) {
		got, err := resolveBaseDir("")
		if err != nil || got != "" {
			t.Fatalf("got (%q, %v)", got, err)
		}
	})
	t.Run("相対はエラー", func(t *testing.T) {
		if _, err := resolveBaseDir("rel/dir"); err == nil {
			t.Fatal("相対の -current-dir が通った")
		}
	})
	t.Run("実在しなければエラー", func(t *testing.T) {
		if _, err := resolveBaseDir(filepath.Join(dir, "no-such")); err == nil {
			t.Fatal("実在しない -current-dir が通った")
		}
	})
	t.Run("ディレクトリでなければエラー", func(t *testing.T) {
		f := filepath.Join(dir, "file")
		if err := os.WriteFile(f, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := resolveBaseDir(f); err == nil {
			t.Fatal("ファイルを -current-dir に指定できてしまった")
		}
	})
}

// resolvePath は絶対ならそのまま、相対なら基準と組み合わせる。基準が無いまま
// 相対を渡されたら推測せずエラー。2 つ目の戻り値は基準を実際に使ったかで、
// 呼び出し側が「-current-dir が一度も使われなかった」ことを検出するのに使う。
func TestResolvePath(t *testing.T) {
	base := "/base"
	t.Run("絶対はそのまま (基準は使わない)", func(t *testing.T) {
		got, used, err := resolvePath("/abs/recs", base, "-record-dir")
		if err != nil || got != "/abs/recs" || used {
			t.Fatalf("got (%q, %v, %v)", got, used, err)
		}
	})
	t.Run("相対は基準と組み合わせる", func(t *testing.T) {
		got, used, err := resolvePath("docs/rt", base, "-record-dir")
		if err != nil || got != filepath.Join(base, "docs/rt") || !used {
			t.Fatalf("got (%q, %v, %v)", got, used, err)
		}
	})
	t.Run("基準が無いまま相対はエラー", func(t *testing.T) {
		_, _, err := resolvePath("docs/rt", "", "-record-dir")
		if err == nil {
			t.Fatal("基準が無いのに相対が通った")
		}
		if !strings.Contains(err.Error(), "-current-dir") {
			t.Fatalf("エラーが -current-dir を案内していない: %v", err)
		}
	})
}

// -current-dir を渡したのに全パスが絶対で一度も使われないなら、指定が効いて
// いないのでエラーにする。黙って通すと「基準を渡したつもり」のまま別の解決結果を
// 受け取る。検査の経路と -write-summary の経路の両方で課す。
func TestRunRejectsUnusedCurrentDir(t *testing.T) {
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	for _, extra := range [][]string{nil, {"-write-summary"}} {
		name := "検査"
		if len(extra) > 0 {
			name = "write-summary"
		}
		t.Run(name, func(t *testing.T) {
			withRunGlobals(t)
			t.Setenv("CLAUDE_PLUGIN_ROOT", "")
			args := append([]string{"-record-dir", recs, "-current-dir", base}, extra...)
			if err := run(args); err == nil {
				t.Fatal("使われない -current-dir が通った")
			}
		})
	}
}

// 片方が相対でもう片方が絶対、という組み合わせは正当 (基準は相対の側に使われる)。
// ラッパーがまさにこの形で、-record-dir は相対・-judgment-flow は絶対を渡す。
func TestRunAllowsCurrentDirWithMixedPaths(t *testing.T) {
	withRunGlobals(t)
	caller := t.TempDir()
	if err := os.MkdirAll(filepath.Join(caller, "recs"), 0o755); err != nil {
		t.Fatal(err)
	}
	flow := filepath.Join(t.TempDir(), "judgment-flow.md")
	if err := os.WriteFile(flow, []byte(judgmentFlowFixture), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	if err := run([]string{"-record-dir", "recs", "-current-dir", caller, "-judgment-flow", flow}); err != nil {
		t.Fatalf("相対と絶対の組み合わせで落ちた: %v", err)
	}
}

// 実在する置き場を相対で指定し、-current-dir で基準を渡せば検査は通る。
func TestRunAcceptsRelativeRecordDirWithCurrentDir(t *testing.T) {
	withRunGlobals(t)
	caller := t.TempDir()
	if err := os.MkdirAll(filepath.Join(caller, "recs"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	if err := run([]string{"-record-dir", "recs", "-current-dir", caller}); err != nil {
		t.Fatalf("基準を渡した相対指定で落ちた: %v", err)
	}
}

// 基準を渡さずに相対を指定したらエラー。ここで $PWD などを当てにいくと、
// 外れたときに別の場所を検査して黙って緑を返す。
func TestRunRejectsRelativeRecordDirWithoutCurrentDir(t *testing.T) {
	withRunGlobals(t)
	caller := t.TempDir()
	if err := os.MkdirAll(filepath.Join(caller, "recs"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(caller)
	t.Setenv("PWD", caller) // $PWD が正しくても使わない
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	err := run([]string{"-record-dir", "recs"})
	if err == nil {
		t.Fatal("基準が無いのに相対指定が通った ($PWD を当てにしている)")
	}
	if !strings.Contains(err.Error(), "-current-dir") {
		t.Fatalf("エラーが -current-dir を案内していない: %v", err)
	}
}

// -record-dir は必須。省略を許すと「既定の場所を検査したことにする」ため。
func TestRunRequiresRecordDir(t *testing.T) {
	withRunGlobals(t)
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")
	err := run(nil)
	if err == nil {
		t.Fatal("-record-dir を省略しても通った")
	}
	if !strings.Contains(err.Error(), "-record-dir") {
		t.Fatalf("エラーが -record-dir を案内していない: %v", err)
	}
}

// 置き場と判定フローの両方が不在なら、1 回の実行で両方が報告される。
// 置き場の不在で即 return すると判定フローの検査に到達せず、片方を直して
// 再実行するまでもう一方も壊れていることを知れない。
func TestRunReportsBothMissingPaths(t *testing.T) {
	withRunGlobals(t)
	missing := t.TempDir()
	recDir := filepath.Join(missing, "no-recs")
	flow := filepath.Join(missing, "no-flow.md")

	// 報告の本文は stderr に出るので、そこを捕まえて「両方が載ったか」を対象の
	// パスで見る。件数の文言 (「2 件」) で判定すると、挙動を変えない書式の変更で
	// 落ちる — 何を報告したかではなく、どう書いたかを検査することになる。
	stderr := captureStderr(t, func() {
		if err := run([]string{"-record-dir", recDir, "-judgment-flow", flow}); err == nil {
			t.Error("両方が不在なのに緑になった")
		}
	})
	for _, want := range []string{recDir, flow} {
		if !strings.Contains(stderr, want) {
			t.Fatalf("%q の不在が報告されていない:\n%s", want, stderr)
		}
	}
}

// captureStderr は fn の実行中の os.Stderr を捕まえて返す。
func captureStderr(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	orig := os.Stderr
	os.Stderr = w
	done := make(chan string, 1)
	go func() {
		var b strings.Builder
		_, _ = io.Copy(&b, r)
		done <- b.String()
	}()
	fn()
	os.Stderr = orig
	_ = w.Close()
	out := <-done
	_ = r.Close()
	return out
}

// -write-summary も run 経由で explicit が渡ることを固定する。関数を直接呼ぶ
// テストだけだと、run から検査への配線を壊しても全テストが通る (配線を false に
// 固定するミューテーションで実測した) — そのとき「明示指定した置き場が無いのに
// 黙って成功する」挙動が復活する。
func TestRunWriteSummaryFailsOnMissingExplicitRecordDir(t *testing.T) {
	withRunGlobals(t)
	missing := filepath.Join(t.TempDir(), "no-such")
	if err := run([]string{"-write-summary", "-record-dir", missing}); err == nil {
		t.Fatal("明示指定した置き場が無いのに -write-summary が成功した")
	}
}

// 空のパスを明示指定したら、その場で弾く。通すと -record-dir "" は path.Clean が
// "." に畳んでカレント (常に実在する) を検査したことにし、-judgment-flow "" は
// 「指定なし」に化けて検査が走らないまま緑になる — どちらもこの検査が塞ごうと
// している「指定したのに検査されない」型そのもの。
func TestRunRejectsEmptyExplicitPaths(t *testing.T) {
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	// -record-dir は必須なので、他のフラグを試すときも渡しておく。
	cases := map[string][]string{
		"-record-dir":    {"-record-dir", ""},
		"-judgment-flow": {"-record-dir", recs, "-judgment-flow", ""},
		"-current-dir":   {"-record-dir", recs, "-current-dir", ""},
	}
	for name, args := range cases {
		t.Run(name, func(t *testing.T) {
			withRunGlobals(t)
			t.Setenv("CLAUDE_PLUGIN_ROOT", "")
			err := run(args)
			if err == nil {
				t.Fatalf("%s に空文字を渡したのに緑になった", name)
			}
			if !strings.Contains(err.Error(), name) {
				t.Fatalf("エラーがどのフラグかを示していない: %v", err)
			}
		})
	}
}

// -install-wrapper は空の -judgment-flow を受け付ける。あちらはパスを検査せず
// 値を焼き込むだけの経路で、空は「$root からの既定パスを使う」正当な入力である。
// 空文字を弾く検査を検査経路と共有させると、この呼び出しを理由なく拒否する。
func TestRunInstallWrapperAcceptsEmptyJudgmentFlow(t *testing.T) {
	withRunGlobals(t)
	// installWrapper は go run -C <展開先>/tools/triagecheck の位置からしか動かないので、
	// その形を満たすディレクトリを作ってそこから実行する。
	root := filepath.Join(t.TempDir(), "cache", "review-triage", "0.0.1")
	toolDir := filepath.Join(root, "tools", "triagecheck")
	if err := os.MkdirAll(toolDir, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(toolDir)
	out := filepath.Join(t.TempDir(), "wrapper.sh")

	// -install-wrapper の -record-dir は絶対パス (生成時のカレントはプラグインの
	// 展開先なので、相対の基準にならない)。
	recDir := filepath.Join(t.TempDir(), "docs", "rt")
	if err := run([]string{"-install-wrapper", out, "-record-dir", recDir, "-judgment-flow", ""}); err != nil {
		t.Fatalf("空の -judgment-flow で -install-wrapper が拒否された: %v", err)
	}
	script, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	// 空のときは $root からの既定パスが焼き込まれる (wrapper.go の judgmentFlowLine)。
	if !strings.Contains(string(script), `-judgment-flow "$root/skills/review-triage/references/judgment-flow.md"`) {
		t.Fatalf("既定の判定フローのパスが焼き込まれていない:\n%s", script)
	}
}

// -judgment-flow の指定の有無は値ではなく flag.Visit で判定する。値が空かどうかで
// 見ると、明示指定が「指定なし」に化けて不在が黙って通る (-record-dir で避けた型)。
// 空文字は上のテストのとおり手前で弾かれるので、ここでは判定の経路そのものを固定する。
func TestResolveJudgmentFlowPathUsesSpecifiedNotValue(t *testing.T) {
	t.Setenv("CLAUDE_PLUGIN_ROOT", "/plugin")
	// specified が真なら、値が空でも「指定あり」として扱い、
	// CLAUDE_PLUGIN_ROOT へフォールバックしない。
	p, origin := resolveJudgmentFlowPath("", true)
	if origin != "-judgment-flow" {
		t.Fatalf("空の明示指定が指定なしに化けた: (%q, %q)", p, origin)
	}
}

func TestResolveJudgmentFlowPath(t *testing.T) {
	t.Run("明示指定が最優先", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "/plugin")
		p, origin := resolveJudgmentFlowPath("/explicit/flow.md", true)
		if p != "/explicit/flow.md" || origin != "-judgment-flow" {
			t.Fatalf("got (%q, %q)", p, origin)
		}
	})
	t.Run("CLAUDE_PLUGIN_ROOT から解決する", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "/plugin")
		p, origin := resolveJudgmentFlowPath("", false)
		want := filepath.Join("/plugin", "skills", "review-triage", "references", "judgment-flow.md")
		if p != want || origin != "CLAUDE_PLUGIN_ROOT" {
			t.Fatalf("got (%q, %q), want (%q, %q)", p, origin, want, "CLAUDE_PLUGIN_ROOT")
		}
	})
	t.Run("どちらも無ければ既定に落ちる", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "")
		p, origin := resolveJudgmentFlowPath("", false)
		if p != "" || origin != "" {
			t.Fatalf("got (%q, %q), want 空", p, origin)
		}
	})
}

// CLAUDE_PLUGIN_ROOT 由来の判定フローは -current-dir の基準を使わない。
// 環境変数の値は利用者が -current-dir を書いたかどうかとは無関係に決まるので、
// そこへ基準を当てると「環境変数を設定していると -current-dir が使えない」
// (逆に相対の環境変数が黙って解決される) ことになる。分岐の両側を固定する。
func TestRunPluginRootFlowIgnoresCurrentDir(t *testing.T) {
	base := realTempDir(t)
	recs := filepath.Join(base, "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	// base 配下に、相対の CLAUDE_PLUGIN_ROOT から辿れる判定フローを置く。
	// -current-dir を基準にすればこれが見つかってしまう配置。
	flowDir := filepath.Join(base, "relplugin", "skills", "review-triage", "references")
	if err := os.MkdirAll(flowDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(flowDir, "judgment-flow.md"),
		[]byte(judgmentFlowFixture), 0o644); err != nil {
		t.Fatal(err)
	}

	t.Run("相対の環境変数は -current-dir で解決しない", func(t *testing.T) {
		withRunGlobals(t)
		t.Setenv("CLAUDE_PLUGIN_ROOT", "relplugin")
		// -current-dir を渡しても、環境変数由来のパスの基準には使わない。
		// 使ってしまうと上の judgment-flow.md が見つかり、緑になる。
		if err := run([]string{"-record-dir", recs, "-current-dir", base}); err == nil {
			t.Fatal("相対の CLAUDE_PLUGIN_ROOT が -current-dir 基準で解決された")
		}
	})

	t.Run("絶対の環境変数は -current-dir の有無に関わらず通る", func(t *testing.T) {
		withRunGlobals(t)
		t.Setenv("CLAUDE_PLUGIN_ROOT", filepath.Join(base, "relplugin"))
		// -record-dir が相対なので -current-dir は使われる。判定フローは絶対で
		// 解決されるため、両者が同居しても問題にならない。
		if err := run([]string{"-record-dir", "recs", "-current-dir", base}); err != nil {
			t.Fatalf("絶対の CLAUDE_PLUGIN_ROOT と -current-dir の同居で落ちた: %v", err)
		}
	})
}

// 値の出所を報告に反映する。CLAUDE_PLUGIN_ROOT から解決した値の誤りを、
// 利用者が渡していない -judgment-flow の名前で叱らない。案内も、直すべき側
// (環境変数) を向いていること — -current-dir を足しても直らないため。
func TestRunReportsOriginOfBadPluginRoot(t *testing.T) {
	withRunGlobals(t)
	base := realTempDir(t)
	recs := filepath.Join(base, "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PLUGIN_ROOT", "relplugin")

	err := run([]string{"-record-dir", recs})
	if err == nil {
		t.Fatal("相対の CLAUDE_PLUGIN_ROOT が通った")
	}
	if !strings.Contains(err.Error(), "CLAUDE_PLUGIN_ROOT") {
		t.Fatalf("報告が値の出所を示していない: %v", err)
	}
	if strings.Contains(err.Error(), "-judgment-flow") {
		t.Fatalf("渡していないフラグ名で報告している: %v", err)
	}
	if strings.Contains(err.Error(), "-current-dir") {
		t.Fatalf("直らない対処 (-current-dir) を案内している: %v", err)
	}
}
