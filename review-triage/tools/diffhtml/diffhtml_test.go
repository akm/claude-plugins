package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestMain は、利用者の git の設定と環境がテストの結果を変えないように、GIT_ で始まる環境変数を取り除き、
// 環境変数 HOME を一時ディレクトリに替える。GIT_ で始まる変数を先に取り除くのは、環境変数 GIT_DIR などが
// 設定されたまま実行すると、テストの git が一時ディレクトリではなく、その変数が指すリポジトリにコミットを作るため。
func TestMain(m *testing.M) {
	for _, kv := range os.Environ() {
		if k, _, _ := strings.Cut(kv, "="); strings.HasPrefix(k, "GIT_") {
			os.Unsetenv(k)
		}
	}
	home, err := os.MkdirTemp("", "diffhtml-home")
	if err != nil {
		panic(err)
	}
	for k, v := range map[string]string{
		"HOME":                home,
		"XDG_CONFIG_HOME":     home,
		"GIT_CONFIG_NOSYSTEM": "1",
		"GIT_AUTHOR_NAME":     "t",
		"GIT_AUTHOR_EMAIL":    "t@example.com",
		"GIT_COMMITTER_NAME":  "t",
		"GIT_COMMITTER_EMAIL": "t@example.com",
	} {
		os.Setenv(k, v)
	}
	// 環境変数 GIT_CONFIG_NOSYSTEM は関数 gitEnv が取り除くので、取り除いた後に足すスライスにも入れる
	extraGitEnv = []string{"GIT_CONFIG_NOSYSTEM=1"}
	code := m.Run()
	os.RemoveAll(home)
	os.Exit(code)
}

// ---- マークの読み取り ----

func TestParseMarker(t *testing.T) {
	ok := []struct {
		in   string
		want marker
	}{
		{"review-triage-diff patch run=12 problem=P1 option=A", marker{kind: "patch", run: 12, problem: "P1", option: "A"}},
		{"  review-triage-diff patch run=3 problem=P10 option=H1  ", marker{kind: "patch", run: 3, problem: "P10", option: "H1"}},
		{"review-triage-diff commit cc5f25b2", marker{kind: "commit", sha: "cc5f25b2"}},
	}
	for _, c := range ok {
		got, err := parseMarker(c.in)
		if err != nil {
			t.Errorf("parseMarker(%q) がエラーを返した: %v", c.in, err)
			continue
		}
		if got != c.want {
			t.Errorf("parseMarker(%q) = %+v、期待は %+v", c.in, got, c.want)
		}
	}
	ng := []string{
		"review-triage-diff",
		"review-triage-diff patch run=0 problem=P1 option=A",
		"review-triage-diff patch run=x problem=P1 option=A",
		"review-triage-diff patch problem=P1 run=1 option=A",
		"review-triage-diff patch run=1 problem=P1",
		"review-triage-diff patch run=1 problem=P1 option=A extra=1",
		"review-triage-diff commit",
		"review-triage-diff commit HEAD",
		"review-triage-diff commit cc5f25b2 cc5f25b3",
		"review-triage-diff file a.txt",
		"review-triage-diffpatch run=1 problem=P1 option=A",
		"review-triage-diffcommit cc5f25b2",
	}
	for _, in := range ng {
		if _, err := parseMarker(in); err == nil {
			t.Errorf("parseMarker(%q) がエラーを返さなかった", in)
		}
	}
}

// ---- 差分の HTML ----

func TestRenderDiffEscapesAndClassifies(t *testing.T) {
	diff := "diff --git a/x.html b/x.html\n" +
		"index 1111111..2222222 100644\n" +
		"--- a/x.html\n" +
		"+++ b/x.html\n" +
		"@@ -1,3 +1,3 @@\n" +
		" <p>a & b</p>\n" +
		"-<b>old</b>\n" +
		"+<b>new</b>\n" +
		"\\ No newline at end of file\n"
	got := renderDiff(diff)
	for _, want := range []string{
		`<div class="rt-diff"><pre>`,
		`<span class="rt-file">diff --git a/x.html b/x.html</span>`,
		`<span class="rt-file">--- a/x.html</span>`,
		`<span class="rt-file">+++ b/x.html</span>`,
		`<span class="rt-hunk">@@ -1,3 +1,3 @@</span>`,
		`<span class="rt-ctx"> &lt;p&gt;a &amp; b&lt;/p&gt;</span>`,
		`<span class="rt-del">-&lt;b&gt;<mark>old</mark>&lt;/b&gt;</span>`,
		`<span class="rt-add">+&lt;b&gt;<mark>new</mark>&lt;/b&gt;</span>`,
		`<span class="rt-meta">\ No newline at end of file</span>`,
	} {
		if !strings.Contains(got, want) {
			t.Errorf("出力に %q が無い:\n%s", want, got)
		}
	}
	if strings.Contains(got, "<b>") || strings.Contains(got, "<p>") {
		t.Errorf("差分の中の < がエスケープされていない:\n%s", got)
	}
}

func TestRenderDiffHighlightsJapaneseChange(t *testing.T) {
	diff := "diff --git a/a.md b/a.md\n--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n" +
		"-パッチは記録から書き出して渡す。\n" +
		"+パッチは記録から一時ファイルに書き出して渡す。\n"
	got := renderDiff(diff)
	if !strings.Contains(got, `<span class="rt-add">+パッチは記録から<mark>一時ファイルに</mark>書き出して渡す。</span>`) {
		t.Errorf("追加の行の変わった部分が強調されていない:\n%s", got)
	}
	// 削除の行は変わった部分が空なので、強調しない
	if !strings.Contains(got, `<span class="rt-del">-パッチは記録から書き出して渡す。</span>`) {
		t.Errorf("削除の行の形が期待と違う:\n%s", got)
	}
}

func TestRenderDiffPairsInOrderAndSkipsUnrelatedLines(t *testing.T) {
	diff := "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,3 +1,2 @@\n" +
		"-alpha one\n" +
		"-beta two\n" +
		"-gamma\n" +
		"+alpha ONE\n" +
		"+xyz\n"
	got := renderDiff(diff)
	for _, want := range []string{
		`<span class="rt-del">-alpha <mark>one</mark></span>`,
		`<span class="rt-add">+alpha <mark>ONE</mark></span>`,
		// 共通の部分が無い組は強調しない
		`<span class="rt-del">-beta two</span>`,
		`<span class="rt-add">+xyz</span>`,
		// 組の相手が無い行は強調しない
		`<span class="rt-del">-gamma</span>`,
	} {
		if !strings.Contains(got, want) {
			t.Errorf("出力に %q が無い:\n%s", want, got)
		}
	}
}

func TestRenderDiffHunkLinesStartingWithHeaderWords(t *testing.T) {
	// hunk の中の、--- や +++ で始まる削除や追加の行を、ファイルの見出しとして扱わない
	diff := "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n" +
		"--- old rule\n" +
		"+++ new rule\n"
	got := renderDiff(diff)
	if !strings.Contains(got, `<span class="rt-del">-<mark>-- old</mark> rule</span>`) {
		t.Errorf("hunk の中の削除の行がファイルの見出しとして扱われた:\n%s", got)
	}
	if !strings.Contains(got, `<span class="rt-add">+<mark>++ new</mark> rule</span>`) {
		t.Errorf("hunk の中の追加の行がファイルの見出しとして扱われた:\n%s", got)
	}
}

// ---- 記録 YAML のパッチ ----

const testRecord = `runs:
  - plans:
      - problem_id: P1
        option_patches:
          - option: A
            base: abc1234
            patch: |
              diff --git a/a b/a
              --- a/a
              +++ b/a
              @@ -1 +1 @@
              -old
              +new
          - option: B
            no_change: true
      - problem_id: P2
        option_patches:
          - option: A
            covered_by:
              problem_id: P1
              option: A
`

func TestRecordPatch(t *testing.T) {
	rec, err := parseRecord([]byte(testRecord))
	if err != nil {
		t.Fatal(err)
	}
	p, err := rec.patch(marker{kind: "patch", run: 1, problem: "P1", option: "A"})
	if err != nil {
		t.Fatalf("P1 の案 A のパッチを取れなかった: %v", err)
	}
	if !strings.HasPrefix(p, "diff --git a/a b/a\n") || !strings.HasSuffix(p, "+new\n") {
		t.Errorf("パッチの中身が期待と違う: %q", p)
	}
	for _, c := range []struct {
		m    marker
		want string
	}{
		{marker{kind: "patch", run: 2, problem: "P1", option: "A"}, "回"},
		{marker{kind: "patch", run: 1, problem: "P9", option: "A"}, "P9"},
		{marker{kind: "patch", run: 1, problem: "P1", option: "Z"}, "Z"},
		{marker{kind: "patch", run: 1, problem: "P1", option: "B"}, "no_change"},
		{marker{kind: "patch", run: 1, problem: "P2", option: "A"}, "covered_by"},
	} {
		_, err := rec.patch(c.m)
		if err == nil {
			t.Errorf("%+v でエラーにならなかった", c.m)
			continue
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%+v のエラーに %q が無い: %v", c.m, c.want, err)
		}
	}
}

// ---- 置き換え全体 ----

type fakeGit map[string]string

func (f fakeGit) show(sha string) (string, error) {
	if d, ok := f[sha]; ok {
		return d, nil
	}
	return "", errString("git show " + sha + " が失敗しました")
}

type errString string

func (e errString) Error() string { return string(e) }

const page = "<!doctype html>\n<html><head><title>t</title>\n</head><body>\n" +
	"<h2>P1</h2>\n<!-- review-triage-diff patch run=1 problem=P1 option=A -->\n" +
	"<h2>commit</h2>\n<!-- review-triage-diff commit abc1234 -->\n" +
	"<!-- ふつうのコメント -->\n</body></html>\n"

func TestFillReplacesMarkersAndInsertsStyleOnce(t *testing.T) {
	rec, err := parseRecord([]byte(testRecord))
	if err != nil {
		t.Fatal(err)
	}
	src := sources{record: rec, git: fakeGit{"abc1234": "diff --git a/c b/c\n--- a/c\n+++ b/c\n@@ -1 +1 @@\n-x\n+y\n"}}
	got, err := fill(page, src)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(got, "review-triage-diff") {
		t.Errorf("マークが残っている:\n%s", got)
	}
	if !strings.Contains(got, "<!-- ふつうのコメント -->") {
		t.Errorf("マークでないコメントが消えた:\n%s", got)
	}
	if !strings.Contains(got, `<span class="rt-add">+<mark>new</mark></span>`) && !strings.Contains(got, `<span class="rt-add">+new</span>`) {
		t.Errorf("案のパッチが入っていない:\n%s", got)
	}
	if !strings.Contains(got, `<span class="rt-file">diff --git a/c b/c</span>`) {
		t.Errorf("コミットの差分が入っていない:\n%s", got)
	}
	if n := strings.Count(got, `id="rt-diff-style"`); n != 1 {
		t.Errorf("<style> の数が %d (期待は 1)", n)
	}
	if strings.Index(got, `id="rt-diff-style"`) > strings.Index(got, "</head>") {
		t.Errorf("<style> が </head> の前に無い:\n%s", got)
	}
	again, err := fill(got, src)
	if err != nil {
		t.Fatal(err)
	}
	if again != got {
		t.Errorf("置き換えた後の HTML にもう一度実行すると、内容が変わった")
	}
}

func TestFillWithoutMarkersStillInsertsStyle(t *testing.T) {
	got, err := fill("<html><head></head><body>x</body></html>", sources{record: &record{}, git: fakeGit{}})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(got, `id="rt-diff-style"`) {
		t.Errorf("<style> が入っていない:\n%s", got)
	}
}

func TestFillReportsAllErrors(t *testing.T) {
	rec, err := parseRecord([]byte(testRecord))
	if err != nil {
		t.Fatal(err)
	}
	in := "<html><head></head><body>\n" +
		"<!-- review-triage-diff patch run=1 problem=P1 option=B -->\n" +
		"<!-- review-triage-diff commit deadbeef -->\n" +
		"<!-- review-triage-diff bogus -->\n" +
		"</body></html>"
	_, err = fill(in, sources{record: rec, git: fakeGit{}})
	if err == nil {
		t.Fatal("エラーにならなかった")
	}
	for _, want := range []string{"no_change", "deadbeef", "bogus"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("エラーに %q が無い: %v", want, err)
		}
	}
}

func TestFillInsertsStyleBeforeHeadEndAfterCaseChangingRunes(t *testing.T) {
	// ケルビン記号 (U+212A、3 バイト) は小文字にすると k (1 バイト) になる。</head> の位置を、小文字にした
	// 文字列ではなく元の文字列で求めていることを確認する
	in := "<html><head><title>\u212a\u212a\u212a</title></HEAD><body></body></html>"
	got, err := fill(in, sources{record: &record{}, git: fakeGit{}})
	if err != nil {
		t.Fatal(err)
	}
	want := "<title>\u212a\u212a\u212a</title>" + diffStyle + "</HEAD>"
	if !strings.Contains(got, want) {
		t.Errorf("<style> が </HEAD> の直前に無い:\n%s", got)
	}
}

func TestFillReportsMalformedMarkers(t *testing.T) {
	// 閉じ --> の無いマークと、review-triage-diff の直後に空白の無いマークを、エラーにすることを確認する
	for _, body := range []string{
		"<!-- review-triage-diff commit abcd </body>",
		"<!-- review-triage-diff commit abcd <p>x</p> <!-- review-triage-diff commit abcd -->",
		"<!--review-triage-diffpatch run=1 problem=P1 option=A-->",
	} {
		in := "<html><head></head><body>" + body + "</body></html>"
		if _, err := fill(in, sources{record: &record{}, git: fakeGit{"abcd": "diff --git a/a b/a\n"}}); err == nil {
			t.Errorf("形の誤ったマークでエラーにならなかった: %q", body)
		}
	}
}

func TestFillRequiresHeadEnd(t *testing.T) {
	if _, err := fill("<html><body></body></html>", sources{record: &record{}, git: fakeGit{}}); err == nil {
		t.Error("</head> が無いのにエラーにならなかった")
	}
}

// ---- コマンド全体 (git のリポジトリを使う) ----

func gitIn(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

func TestRunEndToEnd(t *testing.T) {
	repo := t.TempDir()
	gitIn(t, repo, "init", "-q", "-b", "main")
	os.WriteFile(filepath.Join(repo, "a.txt"), []byte("one <tag>\n"), 0o644)
	gitIn(t, repo, "add", "a.txt")
	gitIn(t, repo, "commit", "-q", "-m", "first")
	os.WriteFile(filepath.Join(repo, "a.txt"), []byte("two <tag>\n"), 0o644)
	gitIn(t, repo, "commit", "-q", "-am", "second")
	sha := gitIn(t, repo, "rev-parse", "--short", "HEAD")
	// 利用者の git の設定が差分の形を変えないこと (diff.noprefix と color.ui)
	gitIn(t, repo, "config", "diff.noprefix", "true")
	gitIn(t, repo, "config", "color.ui", "always")

	work := t.TempDir()
	recPath := filepath.Join(work, "rec.yaml")
	os.WriteFile(recPath, []byte(testRecord), 0o644)
	htmlPath := filepath.Join(work, "page.html")
	html := "<html><head></head><body>\n<!-- review-triage-diff commit " + sha + " -->\n" +
		"<!-- review-triage-diff patch run=1 problem=P1 option=A -->\n</body></html>\n"
	os.WriteFile(htmlPath, []byte(html), 0o644)

	if err := run([]string{"-html", htmlPath, "-record", recPath, "-root", repo}); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(htmlPath)
	for _, want := range []string{
		`<span class="rt-file">diff --git a/a.txt b/a.txt</span>`,
		`<span class="rt-del">-<mark>one</mark> &lt;tag&gt;</span>`,
		`<span class="rt-add">+<mark>two</mark> &lt;tag&gt;</span>`,
	} {
		if !strings.Contains(string(got), want) {
			t.Errorf("出力に %q が無い:\n%s", want, got)
		}
	}
	if strings.Contains(string(got), "\x1b[") {
		t.Errorf("色の制御文字が入っている:\n%q", got)
	}
}

func TestRunLeavesHTMLUnchangedOnError(t *testing.T) {
	repo := t.TempDir()
	gitIn(t, repo, "init", "-q", "-b", "main")
	work := t.TempDir()
	recPath := filepath.Join(work, "rec.yaml")
	os.WriteFile(recPath, []byte(testRecord), 0o644)
	htmlPath := filepath.Join(work, "page.html")
	html := "<html><head></head><body>\n<!-- review-triage-diff commit 0123abcd -->\n</body></html>\n"
	os.WriteFile(htmlPath, []byte(html), 0o644)

	if err := run([]string{"-html", htmlPath, "-record", recPath, "-root", repo}); err == nil {
		t.Fatal("無いコミットを指すマークでエラーにならなかった")
	}
	got, _ := os.ReadFile(htmlPath)
	if string(got) != html {
		t.Errorf("エラーなのに HTML が変わった:\n%s", got)
	}
	entries, _ := os.ReadDir(work)
	if len(entries) != 2 {
		t.Errorf("作業のディレクトリに一時ファイルが残った: %v", entries)
	}
}

func TestRunIgnoresGitDirOfCaller(t *testing.T) {
	// 呼び出し元の環境変数 GIT_DIR が別のリポジトリを指していても、-root のリポジトリを読む
	repo := t.TempDir()
	gitIn(t, repo, "init", "-q", "-b", "main")
	os.WriteFile(filepath.Join(repo, "a.txt"), []byte("x\n"), 0o644)
	gitIn(t, repo, "add", "a.txt")
	gitIn(t, repo, "commit", "-q", "-m", "first")
	sha := gitIn(t, repo, "rev-parse", "--short", "HEAD")
	other := t.TempDir()
	gitIn(t, other, "init", "-q", "-b", "main")
	t.Setenv("GIT_DIR", filepath.Join(other, ".git"))

	work := t.TempDir()
	recPath := filepath.Join(work, "rec.yaml")
	os.WriteFile(recPath, []byte(testRecord), 0o644)
	htmlPath := filepath.Join(work, "page.html")
	os.WriteFile(htmlPath, []byte("<html><head></head><body><!-- review-triage-diff commit "+sha+" --></body></html>"), 0o644)
	if err := run([]string{"-html", htmlPath, "-record", recPath, "-root", repo}); err != nil {
		t.Fatalf("GIT_DIR があるとエラーになった: %v", err)
	}
}

func TestRunValidatesArguments(t *testing.T) {
	work := t.TempDir()
	f := filepath.Join(work, "f")
	os.WriteFile(f, []byte("x"), 0o644)
	for _, args := range [][]string{
		{},
		{"-html", "rel.html", "-record", f, "-root", work},
		{"-html", f, "-record", filepath.Join(work, "none.yaml"), "-root", work},
		{"-html", f, "-record", f, "-root", filepath.Join(work, "none")},
		{"-html", f, "-record", f, "-root", work, "extra"},
	} {
		if err := run(args); err == nil {
			t.Errorf("引数 %v でエラーにならなかった", args)
		}
	}
}
