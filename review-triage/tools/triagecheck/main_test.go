package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// run はパッケージ変数 (reviewTriageDir / judgmentFlowPath) を書き換えるので、
// テストの間だけ退避して戻す。戻さないと後続のテストが前のテストの指定を引き継ぐ。
//
// あわせて、run が読む環境変数 CLAUDE_PLUGIN_ROOT をここでクリアする。run を呼ぶ
// テストは必ずこの関数を最初に呼ぶので、環境に依存しない状態をこの 1 か所で作れる
// (経路ごとに書くと、書き忘れたテストだけが環境依存になる — 実測で、この変数が
// 設定された環境で 1 つだけ落ち、3 つが別の理由で赤になっていた)。環境変数を
// 意図的に使うテストは、この関数の後で t.Setenv して上書きする。
func withRunGlobals(t *testing.T) {
	t.Helper()
	dir, flow := reviewTriageDir, judgmentFlowPath
	t.Cleanup(func() { reviewTriageDir, judgmentFlowPath = dir, flow })
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")
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
	// 実在する相対パスを渡す。実在しない値だと、絶対パスの検査を外しても
	// 次の os.Stat が代わりにエラーを返し、この検査が失われたことに気づけない。
	t.Run("相対はエラー", func(t *testing.T) {
		if err := os.MkdirAll(filepath.Join(dir, "sub"), 0o755); err != nil {
			t.Fatal(err)
		}
		t.Chdir(dir)
		if _, err := resolveBaseDir("sub"); err == nil {
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
	// 文言ではなく番兵で識別する。必須検査を外すと空の recordDir が先へ進んで
	// 別のエラー (相対パスの基準要求) が立ち、その文言にも -record-dir が
	// 含まれるため、部分一致だと検査が失われたことに気づけない。
	if !errors.Is(err, errRecordDirRequired) {
		t.Fatalf("必須検査ではないエラーが返っている: %v", err)
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

// 空のパス (空文字・空白だけ・不可視のフォーマット文字だけの値) を明示指定したら、
// どの経路でもその場で弾く。通すと -judgment-flow "" は「指定なし」として扱われ
// 検査が走らないまま成功し、空白や不可視の値は展開先を基準にした無関係なパスに
// なる — どちらも「指定したのに検査されない」型そのもの。
//
// 規則は経路の分岐より前の 1 か所 (resolveInputs) にあるので、表は
// 経路 × フラグ × 入力 で回す。経路ごとに別のテストを書くと、規則を経路ごとに
// 書いていた頃と同じ抜け方 (片方の経路だけ見張られない) をする。
func TestRunRejectsEmptyExplicitPaths(t *testing.T) {
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(t.TempDir(), "bin", "rtc")
	routes := []struct {
		name  string
		extra []string
	}{
		{"検査", nil},
		{"write-summary", []string{"-write-summary"}},
		{"install-wrapper", []string{"-install-wrapper", out}},
	}
	values := []struct{ label, value string }{
		{"空文字", ""},
		{"空白のみ", "   "},
		{"不可視のみ", "\u200b"},
	}
	assertEmpty := func(t *testing.T, err error, flag, label string) {
		t.Helper()
		if err == nil {
			t.Fatalf("%s に%sを渡したのに緑になった", flag, label)
		}
		// 文言ではなく番兵で識別する。この検査を外しても別のエラー
		// (相対パスの基準要求など) が立ち、その文言にもフラグ名が
		// 含まれるため、部分一致だと検査が失われたことに気づけない。
		if !errors.Is(err, errEmptyPath) {
			t.Fatalf("空のパスの検査ではないエラーが返っている: %v", err)
		}
		if !strings.Contains(err.Error(), flag) {
			t.Fatalf("エラーがどのフラグかを示していない: %v", err)
		}
	}
	for _, route := range routes {
		for _, v := range values {
			// 経路を選ぶフラグ以外のパスのフラグ。
			for _, flag := range []string{"-judgment-flow", "-current-dir"} {
				t.Run(route.name+"/"+flag+"/"+v.label, func(t *testing.T) {
					withRunGlobals(t)
					t.Setenv("CLAUDE_PLUGIN_ROOT", "")
					args := append([]string{"-record-dir", recs, flag, v.value}, route.extra...)
					assertEmpty(t, run(args), flag, v.label)
				})
			}
			// -record-dir の空文字だけは省略と区別できないので必須の検査が先に立つ
			// (TestRunRequiresRecordDir)。空白と不可視は空のパスとして弾く。
			if v.value != "" {
				t.Run(route.name+"/-record-dir/"+v.label, func(t *testing.T) {
					withRunGlobals(t)
					t.Setenv("CLAUDE_PLUGIN_ROOT", "")
					args := append([]string{"-record-dir", v.value}, route.extra...)
					assertEmpty(t, run(args), "-record-dir", v.label)
				})
			}
		}
	}
	// 経路を選ぶフラグ自身の値。
	for _, v := range values {
		t.Run("-install-wrapper/"+v.label, func(t *testing.T) {
			withRunGlobals(t)
			t.Setenv("CLAUDE_PLUGIN_ROOT", "")
			assertEmpty(t, run([]string{"-install-wrapper", v.value, "-record-dir", recs}), "-install-wrapper", v.label)
		})
	}
}

func TestRunEmptyInstallWrapperDoesNotFallThroughToCheck(t *testing.T) {
	withRunGlobals(t)
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")
	recs := filepath.Join(t.TempDir(), "recs")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	// 生成サマリの対象になる記録を 1 つ置く。中身は検査を通す必要が無い —
	// 見るのは .md が作られるかどうかだけ。
	if err := os.WriteFile(filepath.Join(recs, "rec.yaml"), []byte("runs: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	err := run([]string{"-install-wrapper", "", "-record-dir", recs, "-write-summary=true"})
	if err == nil {
		t.Fatal("空の -install-wrapper と -write-summary=true が通った")
	}
	if !strings.Contains(err.Error(), "-install-wrapper") {
		t.Fatalf("-install-wrapper の空文字として弾かれていない: %v", err)
	}
	if _, err := os.Stat(filepath.Join(recs, "rec.md")); !os.IsNotExist(err) {
		t.Fatalf("頼んでいない生成サマリが書き出された (err=%v)", err)
	}
}

// -judgment-flow を省略したときだけ、ラッパーは $root からの既定パスを使う。
// 「既定を使う」は省略で表す — 明示した空は他の経路と同じく弾かれる
// (TestRunRejectsEmptyExplicitPaths)。空文字を「既定」の意味に使うと、
// 空のパスの規則に生成の経路だけの例外ができ、規則を足すたびに例外の処理が要る。
func TestRunInstallWrapperOmittedJudgmentFlowUsesDefault(t *testing.T) {
	withRunGlobals(t)
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")
	// installWrapper は go run -C <展開先>/tools/triagecheck の位置からしか動かないので、
	// その形を満たすディレクトリを作ってそこから実行する。
	root := filepath.Join(t.TempDir(), "cache", "review-triage", "0.0.1")
	toolDir := filepath.Join(root, "tools", "triagecheck")
	if err := os.MkdirAll(toolDir, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(toolDir)
	out := filepath.Join(t.TempDir(), "wrapper.sh")
	recDir := filepath.Join(t.TempDir(), "docs", "rt")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := run([]string{"-install-wrapper", out, "-record-dir", recDir}); err != nil {
		t.Fatalf("-judgment-flow を省略した -install-wrapper が拒否された: %v", err)
	}
	script, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(script), `-judgment-flow "$root/skills/review-triage/references/judgment-flow.md"`) {
		t.Fatalf("既定の判定フローのパスが焼き込まれていない:\n%s", script)
	}
}

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

// -write-summary の経路も、検査の経路と同じパスの解決規則に従う。
// 判定フローの解決より手前で分岐すると、相対の -judgment-flow に基準を要求しないまま
// 生成が進み、同じ入力に対して経路ごとに違う契約を持つことになる。
func TestRunWriteSummarySharesPathRules(t *testing.T) {
	withRunGlobals(t)
	recs := realTempDir(t)
	if err := os.WriteFile(filepath.Join(recs, "x.yaml"), []byte(validRecordYAML), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	err := run([]string{"-record-dir", recs, "-judgment-flow", "rel/flow.md", "-write-summary"})
	if err == nil {
		t.Fatal("-write-summary が相対の -judgment-flow に基準を要求せず通った")
	}
	if !strings.Contains(err.Error(), "-judgment-flow") {
		t.Fatalf("報告が -judgment-flow を示していない: %v", err)
	}
}

// -install-wrapper と -write-summary=true は「何を書き出すか」が食い違うので、
// 黙って片方を無視せずエラーにする。無視すると「指定したのに効かない」を作る —
// 検査の経路で errCurrentDirUnused として禁じているのと同じ型。
// -current-dir は併用できる (相対パスの基準として、他の経路と同じ規則で使う)。
func TestRunInstallWrapperRejectsUnusedFlags(t *testing.T) {
	recs := filepath.Join(realTempDir(t), "docs", "rt")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, extra := range [][]string{{"-write-summary"}, {"-write-summary=true"}} {
		t.Run(extra[0], func(t *testing.T) {
			withRunGlobals(t)
			out := filepath.Join(t.TempDir(), "w")
			args := append([]string{"-install-wrapper", out, "-record-dir", recs}, extra...)
			err := run(args)
			if err == nil {
				t.Fatalf("%s を併記したのに生成が通った", extra[0])
			}
			if !errors.Is(err, errFlagUnusedWithInstallWrapper) {
				t.Fatalf("併用禁止ではないエラーが返っている: %v", err)
			}
		})
	}
}

// -install-wrapper の経路も、検査の経路と同じパスの規則に従う。規則は経路の分岐より
// 前の 1 か所 (resolveInputs) にあり、生成の経路は解決済みの絶対パスを焼き込むだけ。
//
// 以前は生成の経路がパスの解決より前で分岐して戻っていたため、検査の経路の規則が
// 1 つも届かず、同じ規則を wrapper.go に別の条件で書き直しては、その差を
// レビューに指摘されることを回を重ねて繰り返した (相対の -judgment-flow が
// 展開先を暗黙の基準に解決され、版のディレクトリを含む固定パスが焼き込まれる、など)。
func TestRunInstallWrapperSharesPathRules(t *testing.T) {
	base := realTempDir(t)
	toolDir := filepath.Join(base, "cache", "review-triage", "0.0.1", "tools", "triagecheck")
	if err := os.MkdirAll(toolDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 利用者のリポジトリ。置き場と判定フローを実在させる。
	repo := filepath.Join(base, "repo")
	recDir := filepath.Join(repo, "docs", "rt")
	if err := os.MkdirAll(recDir, 0o755); err != nil {
		t.Fatal(err)
	}
	flow := filepath.Join(repo, "flow.md")
	if err := os.WriteFile(flow, []byte("# 判定フロー\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// 展開先の tools/triagecheck に、相対の -judgment-flow が「たまたま」指す
	// ファイルを置く。暗黙の基準で解決する実装なら、これが見つかって通る。
	if err := os.MkdirAll(filepath.Join(toolDir, "rel"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(toolDir, "rel", "flow.md"), []byte("# 囮\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	type tc struct {
		name string
		args []string
		// wantErr は期待するエラーの番兵。nil なら成功を期待する。
		wantErr error
		// wantHint はエラーの文言に含まれるべき語 (番兵が無い規則の識別用)。
		wantHint string
	}
	out := filepath.Join(repo, "bin", "rtc")
	cases := []tc{
		{"相対の -judgment-flow に基準が無い", []string{"-install-wrapper", out, "-record-dir", recDir, "-judgment-flow", "rel/flow.md"}, nil, "-current-dir"},
		{"相対の -record-dir に基準が無い", []string{"-install-wrapper", out, "-record-dir", "docs/rt"}, nil, "-current-dir"},
		{"相対の -install-wrapper に基準が無い", []string{"-install-wrapper", "bin/rtc", "-record-dir", recDir}, nil, "-current-dir"},
		{"全パスが絶対なのに -current-dir がある", []string{"-install-wrapper", out, "-record-dir", recDir, "-current-dir", repo}, errCurrentDirUnused, ""},
		{"-record-dir が不在", []string{"-install-wrapper", out, "-record-dir", filepath.Join(repo, "no-such")}, errPathMissing, ""},
		{"-judgment-flow が不在 (綴りの誤り)", []string{"-install-wrapper", out, "-record-dir", recDir, "-judgment-flow", filepath.Join(repo, "floww.md")}, errPathMissing, ""},
		{"-judgment-flow が空に展開された変数", []string{"-install-wrapper", out, "-record-dir", recDir, "-judgment-flow", "/skills/review-triage/references/judgment-flow.md"}, errPathMissing, ""},
		{"相対を -current-dir で解決して生成", []string{"-current-dir", repo, "-install-wrapper", "bin/rtc", "-record-dir", "docs/rt", "-judgment-flow", "flow.md"}, nil, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			withRunGlobals(t)
			t.Setenv("CLAUDE_PLUGIN_ROOT", "")
			_ = os.Remove(out)
			var err error
			withWorkingDir(t, toolDir, func() { err = run(c.args) })
			if c.wantErr == nil && c.wantHint == "" {
				if err != nil {
					t.Fatalf("生成が拒否された: %v", err)
				}
				script, rerr := os.ReadFile(out)
				if rerr != nil {
					t.Fatalf("ラッパーが書き出されていない: %v", rerr)
				}
				got := string(script)
				// 置き場はラッパーの位置からの相対、判定フローは利用者の基準で
				// 解決した絶対パス (展開先の囮ではない)。
				if !strings.Contains(got, `-record-dir "../docs/rt"`) {
					t.Errorf("-record-dir が script_dir 基準の相対で焼き込まれていない:\n%s", got)
				}
				if !strings.Contains(got, `-judgment-flow "`+flow+`"`) {
					t.Errorf("-judgment-flow が -current-dir 基準で解決されていない:\n%s", got)
				}
				return
			}
			if err == nil {
				t.Fatal("規則に反する入力で生成が通った")
			}
			if c.wantErr != nil && !errors.Is(err, c.wantErr) {
				t.Fatalf("期待した規則のエラーではない: %v", err)
			}
			if c.wantHint != "" && !strings.Contains(err.Error(), c.wantHint) {
				t.Fatalf("エラーが %s を案内していない: %v", c.wantHint, err)
			}
			// エラーのときはラッパーを書き出さない (壊れた生成物を残さない)。
			if _, serr := os.Stat(out); serr == nil {
				t.Fatal("エラーなのにラッパーが書き出された")
			}
		})
	}

	// CLAUDE_PLUGIN_ROOT からの判定フローは焼き込まない (既定は実行時に $root から
	// 解決する) が、実在の要求は他の経路と同じく課す。
	t.Run("CLAUDE_PLUGIN_ROOT は焼き込まないが実在は要求する", func(t *testing.T) {
		withRunGlobals(t)
		plugin := filepath.Join(base, "plugin")
		flowDir := filepath.Join(plugin, "skills", "review-triage", "references")
		t.Setenv("CLAUDE_PLUGIN_ROOT", plugin)
		_ = os.Remove(out)
		var err error
		withWorkingDir(t, toolDir, func() { err = run([]string{"-install-wrapper", out, "-record-dir", recDir}) })
		if !errors.Is(err, errPathMissing) {
			t.Fatalf("環境変数が指す判定フローが無いのに拒否されなかった: %v", err)
		}
		if err := os.MkdirAll(flowDir, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(flowDir, "judgment-flow.md"), []byte("# 判定フロー\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		withWorkingDir(t, toolDir, func() { err = run([]string{"-install-wrapper", out, "-record-dir", recDir}) })
		if err != nil {
			t.Fatalf("環境変数が指す判定フローが実在するのに拒否された: %v", err)
		}
		script, rerr := os.ReadFile(out)
		if rerr != nil {
			t.Fatal(rerr)
		}
		if !strings.Contains(string(script), `-judgment-flow "$root/skills/review-triage/references/judgment-flow.md"`) {
			t.Fatalf("環境変数の値が焼き込まれ、既定の $root が使われていない:\n%s", script)
		}
	})
}

func TestRunInstallWrapperAcceptsFalseWriteSummary(t *testing.T) {
	withRunGlobals(t)
	root := filepath.Join(realTempDir(t), "cache", "review-triage", "0.0.1")
	toolDir := filepath.Join(root, "tools", "triagecheck")
	if err := os.MkdirAll(toolDir, 0o755); err != nil {
		t.Fatal(err)
	}
	recs := filepath.Join(realTempDir(t), "docs", "rt")
	if err := os.MkdirAll(recs, 0o755); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(t.TempDir(), "w")

	withWorkingDir(t, toolDir, func() {
		if err := run([]string{"-install-wrapper", out, "-record-dir", recs, "-write-summary=false"}); err != nil {
			t.Fatalf("-write-summary=false で生成が拒否された: %v", err)
		}
	})
	if _, err := os.Stat(out); err != nil {
		t.Fatalf("ラッパーが書き出されていない: %v", err)
	}
}
