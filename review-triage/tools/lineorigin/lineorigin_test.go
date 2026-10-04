package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestMain は、利用者の git の設定 (グローバル・システム) がテストの結果を変えないように、
// HOME を一時ディレクトリに替え、システムの設定を読ませない。
func TestMain(m *testing.M) {
	home, err := os.MkdirTemp("", "lineorigin-home")
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
	code := m.Run()
	os.RemoveAll(home)
	os.Exit(code)
}

// repo は、テストごとに作る使い捨てのリポジトリ。
type repo struct {
	t   *testing.T
	dir string
}

func newRepo(t *testing.T) *repo {
	t.Helper()
	r := &repo{t: t, dir: t.TempDir()}
	r.git("init", "-q", "-b", "main")
	return r
}

func (r *repo) git(args ...string) string {
	r.t.Helper()
	cmd := exec.Command("git", append([]string{"-C", r.dir}, args...)...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		r.t.Fatalf("git %s: %v: %s", strings.Join(args, " "), err, stderr.String())
	}
	return strings.TrimSpace(stdout.String())
}

func (r *repo) write(path, content string) {
	r.t.Helper()
	p := filepath.Join(r.dir, path)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		r.t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		r.t.Fatal(err)
	}
}

// commit はすべての変更をコミットし、そのコミットの SHA を返す。
func (r *repo) commit(msg string) string {
	r.t.Helper()
	r.git("add", "-A")
	r.git("commit", "-q", "--allow-empty", "-m", msg)
	return r.git("rev-parse", "HEAD")
}

type output struct {
	code   int
	kind   string
	reason string
	lines  map[string]string // "line 3" → 内訳
	stdout string
	stderr string
}

func runTool(t *testing.T, args ...string) output {
	t.Helper()
	var stdout, stderr bytes.Buffer
	o := output{code: run(args, &stdout, &stderr), lines: map[string]string{}, stdout: stdout.String(), stderr: stderr.String()}
	for _, l := range strings.Split(o.stdout, "\n") {
		k, v, _ := strings.Cut(l, ": ")
		switch {
		case k == "result":
			o.kind = v
		case k == "reason":
			o.reason = v
		case strings.HasPrefix(k, "line "):
			o.lines[k] = v
		}
	}
	return o
}

// check は、-root にリポジトリのルートを渡して道具を実行する。
func (r *repo) check(base string, extra ...string) output {
	r.t.Helper()
	return runTool(r.t, append([]string{"-root", r.dir, "-base", base}, extra...)...)
}

func wantKind(t *testing.T, o output, kind string) {
	t.Helper()
	if o.code != 0 {
		t.Fatalf("終了コードが %d (期待は 0)。stderr: %s", o.code, o.stderr)
	}
	if o.kind != kind {
		t.Fatalf("結果が %q (期待は %q)。出力:\n%s", o.kind, kind, o.stdout)
	}
}

func wantContains(t *testing.T, got, sub string) {
	t.Helper()
	if !strings.Contains(got, sub) {
		t.Fatalf("%q を含むはずが、%q だった", sub, got)
	}
}

// branched は、f.md を持つ起点のコミットを作り、そこから作業ブランチ br に切り替えた状態を返す。
func branched(t *testing.T) (*repo, string) {
	t.Helper()
	r := newRepo(t)
	r.write("f.md", "a\nb\nc\n")
	r.write("g.md", "g\n")
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	return r, base
}

func TestUnchangedLineHolds(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("change line 3")

	o := r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, holds)
	wantContains(t, o.lines["line 1"], "全量の起点にあったまま")

	o = r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD")
	wantKind(t, o, notHolds)
	wantContains(t, o.lines["line 3"], "全量の起点より後のコミット")
}

func TestRangeWithOneChangedLineDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("change line 3")

	o := r.check(base, "-file", "f.md", "-lines", "1-3", "-rev", "HEAD")
	wantKind(t, o, notHolds)
	if len(o.lines) != 3 {
		t.Fatalf("行ごとの内訳が %d 行 (期待は 3 行)。出力:\n%s", len(o.lines), o.stdout)
	}
}

// 上に行を足して行番号がずれても、行そのものが変わっていなければ成り立つ。
func TestLineShiftedByInsertionHolds(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "new\na\nb\nc\n")
	r.commit("insert above")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-rev", "HEAD"), holds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), notHolds)
}

func TestFileCreatedInBranchDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.write("n.md", "n\n")
	r.commit("new file")

	o := r.check(base, "-file", "n.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, notHolds)
	wantContains(t, o.reason, "同じパスのファイルが無い")
}

// このブランチで改名したファイルの行は、git blame が改名を追って起点まで遡るが、成り立たない。
func TestFileRenamedInBranchDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.git("mv", "g.md", "h.md")
	r.commit("rename")

	wantKind(t, r.check(base, "-file", "h.md", "-lines", "1", "-rev", "HEAD"), notHolds)
}

// 起点に同じパスのファイルがあっても、それを消した後に別のファイルをそのパスへ改名したなら、
// 行は改名前のファイルから来ているので成り立たない。
func TestFileRenamedOntoDeletedPathDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.git("rm", "-q", "g.md")
	r.commit("delete g.md")
	r.git("mv", "f.md", "g.md")
	r.commit("rename f.md to g.md")

	o := r.check(base, "-file", "g.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, notHolds)
	wantContains(t, o.lines["line 1"], "全量の起点では f.md")
}

// 起点より前に改名したファイルは、起点で同じパスにあるので成り立つ。
func TestFileRenamedBeforeBaseHolds(t *testing.T) {
	r := newRepo(t)
	r.write("old/f.md", "a\nb\n")
	r.commit("c0")
	r.git("mv", "old/f.md", "f.md")
	base := r.commit("rename before base")
	r.git("switch", "-q", "-c", "br")
	r.write("other.md", "x\n")
	r.commit("branch")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1-2", "-rev", "HEAD"), holds)
}

func TestUncommittedChangeInFileIsUnverifiableWithRev(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")

	r.write("f.md", "a\nb\nc\nd\n")
	o := r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, unverifiable)
	wantContains(t, o.reason, "コミットしていない変更")

	// ステージした変更も同じ
	r.git("add", "f.md")
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), unverifiable)
}

// ほかのファイルの変更は、指摘のファイルの行番号を変えないので見ない。
func TestUncommittedChangeInOtherFileIsIgnored(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")

	r.write("g.md", "uncommitted\n")
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), holds)
}

func TestWorktreeContent(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")

	r.write("f.md", "a\nb\nX\n")
	o := r.check(base, "-file", "f.md", "-lines", "3", "-worktree")
	wantKind(t, o, notHolds)
	wantContains(t, o.lines["line 3"], "コミットしていない行")

	// 同じファイルにコミットしていない変更があっても、変わっていない行は成り立つ
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-worktree"), holds)
}

// 作業ツリーの内容の行番号で読む。コミットしていない行を上に足すと、起点の行は下にずれる。
func TestWorktreeLineNumbersFollowWorktreeContent(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")

	r.write("f.md", "new\na\nb\nc\n")
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-worktree"), holds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-worktree"), notHolds)
}

func TestWorktreeUntrackedFileDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.git("rm", "-q", "g.md")
	r.commit("delete g.md")
	r.write("g.md", "g\n") // 起点と同じ内容で作り直したが、コミットしていない

	o := r.check(base, "-file", "g.md", "-lines", "1", "-worktree")
	wantKind(t, o, notHolds)
	wantContains(t, o.reason, "HEAD に同じパスのファイルが無い")
}

func TestBaseEqualToReviewedCommitIsUnverifiable(t *testing.T) {
	r, base := branched(t)

	o := r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, unverifiable)
	wantContains(t, o.reason, "同じ")

	r.write("f.md", "a\nb\nX\n")
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-worktree"), unverifiable)
}

func TestBaseNotAncestorIsUnverifiable(t *testing.T) {
	r, _ := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	r.git("switch", "-q", "main")
	r.write("g.md", "main\n")
	other := r.commit("main moves on")
	r.git("switch", "-q", "br")

	o := r.check(other, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, unverifiable)
	wantContains(t, o.reason, "祖先ではない")
}

// 起点の後に既定のブランチで変わった行を、ブランチにマージで取り込んだなら成り立たない。
func TestLineChangedOnMainAfterBaseAndMergedDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	r.git("switch", "-q", "main")
	r.write("f.md", "A\nb\nc\n")
	r.commit("main changes line 1")
	r.git("switch", "-q", "br")
	r.git("merge", "-q", "--no-edit", "main")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), notHolds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-rev", "HEAD"), holds)
}

// 起点より前に分かれた履歴をマージすると、行がその分岐点まで遡る。起点にあったかは決められない。
func TestLineFromHistoryForkedBeforeBaseIsUnverifiable(t *testing.T) {
	r := newRepo(t)
	r.write("m.md", "m1\nm2\n")
	r.commit("P")
	r.git("switch", "-q", "-c", "side")
	r.write("m.md", "m1\nSIDE\n")
	r.commit("side")
	r.git("switch", "-q", "main")
	r.write("m.md", "m1\nMAIN\n")
	base := r.commit("main")
	r.git("switch", "-q", "-c", "br")
	r.git("merge", "-q", "--no-edit", "-X", "theirs", "side")

	o := r.check(base, "-file", "m.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, unverifiable)
	wantContains(t, o.lines["line 1"], "境界のコミット")
	wantKind(t, r.check(base, "-file", "m.md", "-lines", "2", "-rev", "HEAD"), notHolds)
}

// 無関係な履歴をマージして入った行は、そのルートのコミットの行として報告され、成り立たない。
// 起点にある同じパスのファイル (g.md) の行を、無関係な履歴の内容で置き換えて確かめる。
func TestLineFromUnrelatedHistoryDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("branch")
	r.git("switch", "-q", "--orphan", "other") // 追跡しているファイルは作業ツリーから取り除かれる
	r.write("g.md", "u\n")
	r.commit("other root")
	r.git("switch", "-q", "br")
	r.git("merge", "-q", "--no-edit", "--allow-unrelated-histories", "-X", "theirs", "other")
	if got := r.git("show", "HEAD:g.md"); got != "u" {
		t.Fatalf("マージの後の g.md が %q (期待は u)", got)
	}

	wantKind(t, r.check(base, "-file", "g.md", "-lines", "1", "-rev", "HEAD"), notHolds)
}

// 起点がルートのコミット (最初のコミット) でも、起点から変わっていない行は成り立つ。
func TestBaseAtRootCommit(t *testing.T) {
	r := newRepo(t)
	r.write("f.md", "a\nb\n")
	base := r.commit("root")
	r.git("switch", "-q", "-c", "br")
	r.write("f.md", "a\nB\n")
	r.commit("change")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), holds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-rev", "HEAD"), notHolds)
}

// 設定 blame.ignoreRevsFile にブランチのコミットを挙げても、そのコミットが書き換えた行は成り立たない。
func TestIgnoreRevsFileConfigIsCleared(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	changed := r.commit("change line 3")
	r.write(".git-blame-ignore-revs", changed+"\n")
	r.git("config", "blame.ignoreRevsFile", ".git-blame-ignore-revs")
	r.commit("add ignore list")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD"), notHolds)
}

// -root がルートの下のディレクトリでも、-file はルートからのパスとして読む。
func TestRootMayBeSubdirectory(t *testing.T) {
	r, base := branched(t)
	r.write("sub/s.md", "s\n")
	r.commit("branch")

	o := runTool(t, "-root", filepath.Join(r.dir, "sub"), "-base", base, "-file", "f.md", "-lines", "3", "-rev", "HEAD")
	wantKind(t, o, holds)

	r.write("f.md", "a\nb\nc\nd\n")
	o = runTool(t, "-root", filepath.Join(r.dir, "sub"), "-base", base, "-file", "f.md", "-lines", "3", "-rev", "HEAD")
	wantKind(t, o, unverifiable)
}

// パターンの文字や先頭の : を含む名前・日本語の名前・" を含む名前も、書いたとおりのファイル名として読む。
func TestSpecialFileNames(t *testing.T) {
	names := []string{"[a].md", ":c.md", "日本.md", `x"y.md`, "*.md"}
	r := newRepo(t)
	for _, n := range names {
		r.write(n, "1\n")
	}
	r.write("a.md", "a\n") // [a].md と *.md をパターンとして読むと一致する名前
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("other.md", "x\n")
	r.commit("branch")

	for _, n := range names {
		t.Run(n, func(t *testing.T) {
			wantKind(t, r.check(base, "-file", n, "-lines", "1", "-rev", "HEAD"), holds)
			wantKind(t, r.check(base, "-file", n, "-lines", "1", "-worktree"), holds)
		})
	}

	// パターンとして読むと a.md の変更を [a].md の変更とみなしてしまう
	r.write("a.md", "changed\n")
	wantKind(t, r.check(base, "-file", "[a].md", "-lines", "1", "-rev", "HEAD"), holds)
	r.write("a.md", "a\n")

	// 先頭の : を特別な指定として読むと、:c.md の変更を見逃す
	r.write(":c.md", "changed\n")
	wantKind(t, r.check(base, "-file", ":c.md", "-lines", "1", "-rev", "HEAD"), unverifiable)
}

func TestInputErrors(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	notRepo := t.TempDir()

	cases := []struct {
		name string
		args []string
		want string
	}{
		{"フラグが無い", nil, "必須のフラグがありません"},
		{"-rev と -worktree の両方", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD", "-worktree"}, "どちらか 1 つ"},
		{"-rev も -worktree も無い", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1"}, "どちらか 1 つ"},
		{"相対パスの -root", []string{"-root", ".", "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"}, "絶対パス"},
		{"git のリポジトリでない -root", []string{"-root", notRepo, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"}, "git のリポジトリの中を指していません"},
		{"行番号が 0", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "0", "-rev", "HEAD"}, "-lines"},
		{"終わりが始めより前", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "3-2", "-rev", "HEAD"}, "-lines"},
		{"数でない行番号", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "x", "-rev", "HEAD"}, "-lines"},
		{"ルートの外を指す -file", []string{"-root", r.dir, "-base", base, "-file", "../f.md", "-lines", "1", "-rev", "HEAD"}, "リポジトリの中のファイルを指していません"},
		{"絶対パスの -file", []string{"-root", r.dir, "-base", base, "-file", filepath.Join(r.dir, "f.md"), "-lines", "1", "-rev", "HEAD"}, "相対パス"},
		{"解決できない -base", []string{"-root", r.dir, "-base", "no-such-rev", "-file", "f.md", "-lines", "1", "-rev", "HEAD"}, "-base をコミットに解決できません"},
		{"解決できない -rev", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "no-such-rev"}, "解決できません"},
		{"レビューした内容に無いファイル", []string{"-root", r.dir, "-base", base, "-file", "none.md", "-lines", "1", "-rev", "HEAD"}, "ファイルがありません"},
		{"作業ツリーに無いファイル", []string{"-root", r.dir, "-base", base, "-file", "none.md", "-lines", "1", "-worktree"}, "ファイルがありません"},
		{"ファイルの行数を越える行", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "9", "-rev", "HEAD"}, "git blame"},
		{"余分な引数", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD", "extra"}, "余分な引数"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			o := runTool(t, c.args...)
			if o.code != 2 {
				t.Fatalf("終了コードが %d (期待は 2)。stdout: %s stderr: %s", o.code, o.stdout, o.stderr)
			}
			if o.stdout != "" {
				t.Fatalf("入力の誤りでは結果を出さないはずが、stdout に %q を出した", o.stdout)
			}
			wantContains(t, o.stderr, c.want)
		})
	}
}

func TestParsePorcelainUnquotesFileName(t *testing.T) {
	out := strings.Join([]string{
		"0123456789012345678901234567890123456789 1 1 1",
		"boundary",
		`filename "\346\227\245.md"`,
		"\tline",
		"",
	}, "\n")
	lines, err := parsePorcelain(out)
	if err != nil {
		t.Fatal(err)
	}
	if len(lines) != 1 || lines[0].filename != "日.md" || !lines[0].boundary || lines[0].final != 1 {
		t.Fatalf("読み取りが違う: %+v", lines)
	}
}
