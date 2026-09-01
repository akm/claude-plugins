package main

import (
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
func TestRunFailsOnMissingExplicitPaths(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "no-such")
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"record-dir が不在", []string{"-record-dir", missing}, "-record-dir"},
		{"judgment-flow が不在", []string{"-judgment-flow", filepath.Join(missing, "judgment-flow.md")}, "-judgment-flow"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			withRunGlobals(t)
			err := run(tc.args)
			if err == nil {
				t.Fatal("不在のパスを指定したのにエラーにならなかった")
			}
			if !strings.Contains(err.Error(), tc.want) && !strings.Contains(err.Error(), "問題が見つかりました") {
				t.Fatalf("エラーの内容が想定と違う: %v", err)
			}
		})
	}
}

// 既定値と同じ値を明示的に渡しても、指定として扱う。既定値との一致で判定すると
// この経路が「指定していない」に化け、不在を報告すべきときに黙って通る
// (flag.Visit で実際に指定されたフラグだけを見る理由)。
func TestRunTreatsExplicitDefaultValueAsSpecified(t *testing.T) {
	withRunGlobals(t)
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Chdir(t.TempDir())
	t.Cleanup(func() { _ = os.Chdir(cwd) })

	// 既定値そのものを明示的に渡す。カレントには置き場が無いので、指定として
	// 扱われれば不在が報告される。
	if err := run([]string{"-record-dir", reviewTriageDir}); err == nil {
		t.Fatal("既定値の明示指定が「指定なし」に化けて、不在が黙って通った")
	}
}

// 指定が無いまま置き場も判定フローも無いのは、スキル未導入の正常な状態として通す
// (後方互換 — 既定のまま実行する利用者の挙動を変えない)。
func TestRunPassesWhenNothingSpecified(t *testing.T) {
	withRunGlobals(t)
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	t.Chdir(t.TempDir())
	t.Cleanup(func() { _ = os.Chdir(cwd) })
	t.Setenv("CLAUDE_PLUGIN_ROOT", "")

	if err := run(nil); err != nil {
		t.Fatalf("未導入のリポジトリで落ちた: %v", err)
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

	if err := run(nil); err == nil {
		t.Fatal("CLAUDE_PLUGIN_ROOT が指す判定フローが無いのに緑になった")
	}
}

func TestResolveJudgmentFlowPath(t *testing.T) {
	t.Run("明示指定が最優先", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "/plugin")
		p, origin := resolveJudgmentFlowPath("/explicit/flow.md")
		if p != "/explicit/flow.md" || origin != "-judgment-flow" {
			t.Fatalf("got (%q, %q)", p, origin)
		}
	})
	t.Run("CLAUDE_PLUGIN_ROOT から解決する", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "/plugin")
		p, origin := resolveJudgmentFlowPath("")
		want := filepath.Join("/plugin", "skills", "review-triage", "references", "judgment-flow.md")
		if p != want || origin != "CLAUDE_PLUGIN_ROOT" {
			t.Fatalf("got (%q, %q), want (%q, %q)", p, origin, want, "CLAUDE_PLUGIN_ROOT")
		}
	})
	t.Run("どちらも無ければ既定に落ちる", func(t *testing.T) {
		t.Setenv("CLAUDE_PLUGIN_ROOT", "")
		p, origin := resolveJudgmentFlowPath("")
		if p != "" || origin != "" {
			t.Fatalf("got (%q, %q), want 空", p, origin)
		}
	})
}
