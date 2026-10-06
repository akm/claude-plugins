package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestMain は、利用者の git の設定 (グローバル・システム) がテストの結果を変えないように、
// HOME を一時ディレクトリに替え、システムの設定を読ませない。GIT_ で始まる環境変数を先に
// 取り除くのは、GIT_DIR などが設定されたまま走らせると、テストの git が一時ディレクトリではなく
// その変数が指すリポジトリにコミットやブランチを作るため。
func TestMain(m *testing.M) {
	for _, kv := range os.Environ() {
		if k, _, _ := strings.Cut(kv, "="); strings.HasPrefix(k, "GIT_") {
			os.Unsetenv(k)
		}
	}
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
	// GIT_CONFIG_NOSYSTEM は、道具の gitEnv が取り除くので、取り除いた後に足す列にも入れる
	extraGitEnv = []string{"GIT_CONFIG_NOSYSTEM=1"}
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

	o := r.check(base, "-file", "f.md", "-lines", "2", "-rev", "HEAD")
	wantKind(t, o, holds)
	wantContains(t, o.lines["line 2"], "全量の起点にあったまま (起点の 1 行目)")
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), notHolds)
}

// ファイルの中で並べ替えた行は、差分が残ったと見なした行だけが成り立ち、消して足したと見なした行は
// 成り立たない。末尾の 2 行を先頭へ動かすと、最も長く共通する並び (a・b・c) が 1 つに決まるので、
// 残ったと見なす行が差分の作り方によらない。動かす 2 行は、git blame の移動の検出 (-M) が移動と
// 見なす長さ (英数字 20 文字) を越えるので、道具が移動の検出を使うと 1〜2 行目も成り立ってしまう。
func TestReorderedLinesFollowDiff(t *testing.T) {
	a, b, c := "alpha line of the base file\n", "bravo line of the base file\n", "charlie line of the base file\n"
	d, e := "delta line of the base file\n", "echo line of the base file\n"
	r := newRepo(t)
	r.write("f.md", a+b+c+d+e)
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("f.md", d+e+a+b+c)
	r.commit("move d and e to the top")

	o := r.check(base, "-file", "f.md", "-lines", "3-5", "-rev", "HEAD")
	wantKind(t, o, holds)
	for i, l := range []string{"line 3", "line 4", "line 5"} {
		wantContains(t, o.lines[l], fmt.Sprintf("全量の起点にあったまま (起点の %d 行目)", i+1))
	}
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1-2", "-rev", "HEAD"), notHolds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1-5", "-rev", "HEAD"), notHolds)
}

// 起点に同じ内容の行が複数あっても、内訳の起点の行番号は、git blame が対応させた起点の行を指す。
// その行の内容は対象の行と同じ (D8 の (2) は、この行を起点の内容で読む)。
func TestDuplicateLinesReportBaseLine(t *testing.T) {
	r := newRepo(t)
	r.write("f.md", "# t\n```\nx\n```\ny\n```\nz\n```\n")
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("f.md", "# t\nnew\n```\nx\n```\ny\n```\nz\n```\n")
	r.commit("insert above the fences")

	baseLines := strings.Split(r.git("show", base+":f.md"), "\n")
	for final := 3; final <= 9; final += 2 {
		l := fmt.Sprintf("line %d", final)
		o := r.check(base, "-file", "f.md", "-lines", strconv.Itoa(final), "-rev", "HEAD")
		wantKind(t, o, holds)
		var orig int
		if _, err := fmt.Sscanf(strings.TrimPrefix(o.lines[l], "全量の起点にあったまま (起点の "), "%d", &orig); err != nil {
			t.Fatalf("%s の内訳から起点の行番号を読めない: %q", l, o.lines[l])
		}
		if orig != final-1 || baseLines[orig-1] != "```" {
			t.Fatalf("%s の起点の行が %d 行目 (期待は %d 行目の ```)。内訳: %q", l, orig, final-1, o.lines[l])
		}
	}
}

func TestFileCreatedInBranchDoesNotHold(t *testing.T) {
	r, base := branched(t)
	r.write("n.md", "n\n")
	r.commit("new file")

	o := r.check(base, "-file", "n.md", "-lines", "1", "-rev", "HEAD")
	wantKind(t, o, notHolds)
	wantContains(t, o.reason, "同じパスのファイルが無い")
}

// 起点ではディレクトリだったパスを、このブランチでファイルにしたなら、起点に同じパスのファイルは無い。
func TestDirectoryAtBaseIsNotAFile(t *testing.T) {
	r, base := branched(t)
	r.write("x/inner.md", "i\n")
	base = r.commit("add directory x") // 起点を、x がディレクトリのコミットにする
	r.git("rm", "-q", "-r", "x")
	r.write("x", "now a file\n")
	r.commit("replace directory x with a file")

	o := r.check(base, "-file", "x", "-lines", "1", "-rev", "HEAD")
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

// 道具は読むだけで、インデックスを書き換えない。更新時刻だけが変わったファイル (git diff なら
// インデックスに記録した更新時刻などを更新して書き換える) があっても、-rev と -worktree のどちらでも変えない。
func TestToolDoesNotWriteIndex(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	r.git("update-index", "--refresh")
	later := time.Now().Add(time.Hour)
	if err := os.Chtimes(filepath.Join(r.dir, "f.md"), later, later); err != nil {
		t.Fatal(err)
	}
	index := filepath.Join(r.dir, ".git", "index")
	before, err := os.ReadFile(index)
	if err != nil {
		t.Fatal(err)
	}

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), holds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-worktree"), holds)
	after, err := os.ReadFile(index)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("道具がインデックスを書き換えた")
	}
}

// skip-worktree を付けたファイルの編集は、インデックスに記録した更新時刻などには現れないが、コミットしていない変更として扱う。
func TestSkipWorktreeEditIsUncommittedChange(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	r.git("update-index", "--skip-worktree", "f.md")
	r.write("f.md", "a\nb\nc\nd\n")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), unverifiable)
}

// シンボリックリンクは、リンクの先ではなくリンクの文字列で比べる。リンクを変えていなければ
// 成り立ち、リンク先を替えればコミットしていない変更になる。
func TestSymlinkIsComparedAsLink(t *testing.T) {
	r := newRepo(t)
	r.write("real.md", "r\n")
	r.write("other.md", "o\n")
	if err := os.Symlink("real.md", filepath.Join(r.dir, "link.md")); err != nil {
		t.Fatal(err)
	}
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("g.md", "branch\n")
	r.commit("branch")

	wantKind(t, r.check(base, "-file", "link.md", "-lines", "1", "-rev", "HEAD"), holds)

	link := filepath.Join(r.dir, "link.md")
	os.Remove(link)
	if err := os.Symlink("other.md", link); err != nil {
		t.Fatal(err)
	}
	wantKind(t, r.check(base, "-file", "link.md", "-lines", "1", "-rev", "HEAD"), unverifiable)
}

// 指摘のファイルを、作業ツリーでディレクトリに置き換えていたら、コミットしていない変更として扱う。
func TestFileReplacedByDirectoryIsUncommittedChange(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	os.Remove(filepath.Join(r.dir, "f.md"))
	r.write("f.md/inner.md", "i\n")

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

// -worktree で、clean フィルタが設定されたファイルは、作業ツリーの行番号と git blame が見る
// フィルタの後の行番号がずれうるので、確かめずに unverifiable にする。確かめると、書き換えた行が
// 別の (起点のままの) 行に当たり、誤った holds になる。属性の書き方ごとに確かめる。
func TestWorktreeCleanFilterAttributes(t *testing.T) {
	cases := []struct {
		name       string
		attributes string
		driver     string // 設定する clean フィルタのドライバの名前 (空なら設定しない)
		want       string
	}{
		{"-filter はフィルタを外すので確かめる", "f.md -filter\n", "", notHolds},
		{"!filter は属性を無しに戻すので確かめる", "*.md filter=strip\nf.md !filter\n", "strip", notHolds},
		{"filter=strip は確かめない", "f.md filter=strip\n", "strip", unverifiable},
		{"ドライバの名前が unspecified でも確かめない", "f.md filter=unspecified\n", "unspecified", unverifiable},
		{"ドライバの名前が unset でも確かめない", "f.md filter=unset\n", "unset", unverifiable},
		{"名前が unset のドライバがあると -filter も確かめない", "f.md -filter\n", "unset", unverifiable},
		{"値の無い filter は確かめない", "f.md filter\n", "", unverifiable},
		{"設定の無いドライバの名前でも確かめない", "f.md filter=nodriver\n", "", unverifiable},
		{"filter が 2 つ目の属性でも確かめない", "f.md diff=x filter=strip\n", "strip", unverifiable},
		{"filter が 3 つ目の属性でも確かめない", "f.md -text -diff filter=strip\n", "strip", unverifiable},
		{"filter ではない属性の値が filter でも確かめる", "f.md diff=filter\n", "", notHolds},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newRepo(t)
			if c.driver != "" {
				r.git("config", "filter."+c.driver+".clean", "grep -v '^#'")
				r.git("config", "filter."+c.driver+".smudge", "cat")
			}
			r.write(".gitattributes", c.attributes)
			r.write("f.md", "x\ny\nz\n")
			base := r.commit("base")
			r.git("switch", "-q", "-c", "br")
			r.write("g.md", "g\n")
			r.commit("branch")
			// 生の 3 行目 (y2) を書き換えた。フィルタが適用されると、フィルタの後の 3 行目は起点のままの z
			r.write("f.md", "# h\nx\ny2\nz\n")

			o := r.check(base, "-file", "f.md", "-lines", "3", "-worktree")
			wantKind(t, o, c.want)
			if c.want == unverifiable {
				wantContains(t, o.reason, "clean フィルタ")
			}
		})
	}
}

// 名前が unset のドライバを、設定 filter.unset.process だけで登録しても、-filter と区別できないので確かめない。
func TestUnsetDriverWithProcessOnly(t *testing.T) {
	r := newRepo(t)
	r.git("config", "filter.unset.process", "nonexistent-filter-process")
	r.write(".gitattributes", "f.md -filter\n")
	r.write("f.md", "x\ny\nz\n")
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("g.md", "g\n")
	r.commit("branch")
	r.write("f.md", "x\ny2\nz\n")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-worktree"), unverifiable)
}

// scriptedGit は、引数に sub を含む呼び出しだけを、stdout を書いて終了コード code で終え、
// ほかのコマンドは本物の git に渡す偽の git を書き込んだディレクトリを返す。stdout は printf の書式
// (\000 で NUL) で渡す。
func scriptedGit(t *testing.T, sub, stdout string, code int) string {
	t.Helper()
	real, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	script := fmt.Sprintf("#!/bin/sh\ncase \" $* \" in *\" %s \"*) printf '%s'; exit %d;; esac\nexec '%s' \"$@\"\n", sub, stdout, code, real)
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return bin
}

// clean フィルタの確認で git が失敗したときや、出力の形が読めないときは、フィルタ無しとして
// git blame で行を調べに進まず、run-error にする (調べに進むと、誤った holds になりうる)。
func TestCleanFilterCheckFailuresAreRunErrors(t *testing.T) {
	r := newRepo(t)
	r.write(".gitattributes", "f.md -filter\n")
	r.write("f.md", "x\ny\nz\n")
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("g.md", "g\n")
	r.commit("branch")
	args := []string{"-file", "f.md", "-lines", "1", "-worktree"}

	cases := []struct {
		name, sub, stdout string
		code              int
		want              string
	}{
		{"check-attr が失敗する", "check-attr", "", 1, "check-attr"},
		{"check-attr の出力が三つ組にならない", "check-attr", "f.md\\000filter\\000", 0, "git check-attr の出力を読めません"},
		{"check-attr の出力の最後の要素が空でない", "check-attr", "f.md\\000filter\\000set\\000x", 0, "git check-attr の出力を読めません"},
		{"config が想定していない終了コードで終わる", "config", "", 2, "config"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			t.Setenv("PATH", scriptedGit(t, c.sub, c.stdout, c.code))
			wantError(t, r.check(base, args...), 3, "run-error:", c.want)
		})
	}
}

// -rev では、clean フィルタがあっても確かめる。git blame はコミットの内容を見て、行番号も
// その内容のものなので、ずれない。
func TestRevIgnoresCleanFilter(t *testing.T) {
	r := newRepo(t)
	r.git("config", "filter.strip.clean", "grep -v '^#'")
	r.git("config", "filter.strip.smudge", "cat")
	r.write(".gitattributes", "f.md filter=strip\n")
	r.write("f.md", "x\ny\nz\n")
	base := r.commit("base")
	r.git("switch", "-q", "-c", "br")
	r.write("f.md", "x\nY\nz\n")
	r.commit("change line 2")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), holds)
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "2", "-rev", "HEAD"), notHolds)
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

// 利用者の環境の GIT_ で始まる変数が別のリポジトリを指していても、-root のリポジトリを読み、
// 別のリポジトリを変えない。パスの読み方を替える変数があっても、書いたとおりのファイル名として読む。
func TestGitEnvironmentVariablesAreIgnored(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("change line 3")
	other := newRepo(t)
	other.write("x.md", "x\n")
	other.commit("other")
	snapshot := func() string {
		idx, err := os.ReadFile(filepath.Join(other.dir, ".git", "index"))
		if err != nil {
			t.Fatal(err)
		}
		return other.git("for-each-ref") + "\n" + other.git("symbolic-ref", "HEAD") + "\n" + string(idx)
	}
	before := snapshot()

	vars := map[string]string{
		"GIT_DIR":            filepath.Join(other.dir, ".git"),
		"GIT_WORK_TREE":      other.dir,
		"GIT_INDEX_FILE":     filepath.Join(other.dir, ".git", "index"),
		"GIT_GLOB_PATHSPECS": "1",
	}
	for k, v := range vars {
		t.Setenv(k, v)
	}
	o3 := r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD")
	o1 := r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	for k := range vars {
		os.Unsetenv(k) // 下の確認の git が、別のリポジトリを指さないようにする
	}

	wantKind(t, o3, notHolds)
	wantKind(t, o1, holds)
	if after := snapshot(); after != before {
		t.Fatalf("GIT_DIR が指すリポジトリの参照かインデックスが変わった")
	}
}

// テストの隔離 (システムの git の設定を読ませない) が、道具の git にも届く。
func TestGitEnvKeepsTestIsolation(t *testing.T) {
	found := false
	for _, kv := range gitEnv() {
		if kv == "GIT_CONFIG_NOSYSTEM=1" {
			found = true
		}
	}
	if !found {
		t.Fatal("道具が git に渡す環境に GIT_CONFIG_NOSYSTEM=1 が無い")
	}
}

// 道具が git に渡す環境に、取得と問い合わせを止める変数がある。
func TestGitEnvStopsFetchAndPrompt(t *testing.T) {
	env := strings.Join(gitEnv(), "\n")
	for _, want := range []string{"GIT_NO_LAZY_FETCH=1", "GIT_TERMINAL_PROMPT=0"} {
		if !strings.Contains("\n"+env+"\n", "\n"+want+"\n") {
			t.Errorf("道具が git に渡す環境に %s が無い", want)
		}
	}
}

// diff の textconv があっても、変換した後ではなく元の行を比べる。
func TestTextconvIsIgnored(t *testing.T) {
	r := newRepo(t)
	r.write(".gitattributes", "*.dat diff=csv\n")
	r.write("f.dat", "a,1\nb,2\n")
	base := r.commit("base")
	r.git("config", "diff.csv.textconv", "cut -d, -f1")
	r.git("switch", "-q", "-c", "br")
	r.write("f.dat", "a,1\nb,CHANGED\n")
	r.commit("change the second column")

	wantKind(t, r.check(base, "-file", "f.dat", "-lines", "2", "-rev", "HEAD"), notHolds)
	wantKind(t, r.check(base, "-file", "f.dat", "-lines", "1", "-rev", "HEAD"), holds)
}

// git replace で、行を書き換えたコミットを書き換えていないコミットに置き換えても、置き換えを見ない。
func TestReplaceObjectsAreIgnored(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	changed := r.commit("change line 3")
	fake := r.git("commit-tree", base+"^{tree}", "-p", base, "-m", "fake")
	r.git("replace", changed, fake)

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD"), notHolds)
}

// ファイル .git/info/grafts (非推奨) は打ち消さない。途中のコミットを隠すと、書き換えて元へ戻した行が
// holds になるが、その行の内容は起点と同じなので、誤った holds には当たらない (README の「保証すること」)。
func TestGraftsHidingRewriteAndRevert(t *testing.T) {
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("change line 3")
	r.write("f.md", "a\nb\nc\n")
	reverted := r.commit("revert line 3")

	wantKind(t, r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD"), notHolds)

	r.git("config", "advice.graftFileDeprecated", "false")
	r.write(".git/info/grafts", reverted+" "+base+"\n")
	if r.git("rev-parse", "HEAD^") != base {
		t.Skip("この版の git は .git/info/grafts を読まない")
	}
	wantKind(t, r.check(base, "-file", "f.md", "-lines", "3", "-rev", "HEAD"), holds)
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

	// 先頭の : を特別な指定として読むと、:c.md に変更があっても無いと判定する
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
		{"ファイルの行数を越える行", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "9", "-rev", "HEAD"}, "行数 (3) を越えます"},
		{"作業ツリーのファイルの行数を越える行", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "2-4", "-worktree"}, "行数 (3) を越えます"},
		{"存在しない -root", []string{"-root", filepath.Join(notRepo, "none"), "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"}, "存在するディレクトリではありません"},
		{"余分な引数", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD", "extra"}, "余分な引数"},
		{"未知のフラグ", []string{"-root", r.dir, "-base", base, "-file", "f.md", "-lines", "1", "-rev", "HEAD", "-unknown"}, "unknown"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			wantError(t, runTool(t, c.args...), 2, "input-error:", c.want)
		})
	}
}

// wantError は、結果を出さずに、標準エラー出力の最初の行が印で始まり、終了コードが code であることを確かめる。
func wantError(t *testing.T, o output, code int, label, want string) {
	t.Helper()
	if o.code != code {
		t.Fatalf("終了コードが %d (期待は %d)。stdout: %s stderr: %s", o.code, code, o.stdout, o.stderr)
	}
	if o.stdout != "" {
		t.Fatalf("結果を出せないときは標準出力に書かないはずが、%q を書いた", o.stdout)
	}
	first, _, _ := strings.Cut(o.stderr, "\n")
	if !strings.HasPrefix(first, label+" ") {
		t.Fatalf("標準エラー出力の最初の行が %q で始まらない: %q", label, o.stderr)
	}
	wantContains(t, o.stderr, want)
}

// ビルドした実行ファイルを、別のプロセスとして走らせても、標準エラー出力の最初の行が印で始まり、
// 終了コードで種類が分かれる。フラグの誤りで flag が使い方を書き出すと、最初の行が印にならない。
func TestExecutableReportsLabelOnFirstLine(t *testing.T) {
	r, _ := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	bin := filepath.Join(t.TempDir(), "lineorigin")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		t.Fatalf("go build: %v: %s", err, out)
	}
	cases := []struct {
		name  string
		args  []string
		code  int
		label string
	}{
		{"未知のフラグ", []string{"-unknown"}, 2, "input-error:"},
		{"解決できない -base", []string{"-root", r.dir, "-base", "no-such-rev", "-file", "f.md", "-lines", "1", "-rev", "HEAD"}, 2, "input-error:"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			cmd := exec.Command(bin, c.args...)
			var stdout, stderr bytes.Buffer
			cmd.Stdout, cmd.Stderr = &stdout, &stderr
			err := cmd.Run()
			var exitErr *exec.ExitError
			if !errors.As(err, &exitErr) || exitErr.ExitCode() != c.code {
				t.Fatalf("終了コードが期待 (%d) と違う: %v", c.code, err)
			}
			first, _, _ := strings.Cut(stderr.String(), "\n")
			if !strings.HasPrefix(first, c.label+" ") || stdout.Len() != 0 {
				t.Fatalf("最初の行が %q で始まらないか、標準出力に書いた。stderr: %q stdout: %q", c.label, stderr.String(), stdout.String())
			}
		})
	}
}

// .git があるのに git がリポジトリとして読めないとき (権限など) は、渡し方では直せないので run-error にする。
// git はこのときも「not a git repository」と言うので、入力の誤りと取り違えやすい。
func TestUnreadableRepositoryIsRunError(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root では権限を外しても読めてしまう")
	}
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	dotGit := filepath.Join(r.dir, ".git")
	if err := os.Chmod(dotGit, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(dotGit, 0o755) })

	wantError(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), 3, "run-error:", "git がリポジトリとして読めません")
}

// オブジェクトを読めないとき (壊れたリポジトリ) は、パスが無いことと取り違えず、run-error にする。
// 取り違えると、起点にあるファイルが「起点に無い」として not-holds になる。
func TestMissingObjectIsRunError(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	tree := r.git("rev-parse", base+"^{tree}")
	if err := os.Remove(filepath.Join(r.dir, ".git", "objects", tree[:2], tree[2:])); err != nil {
		t.Fatal(err)
	}

	wantError(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), 3, "run-error:", "ls-tree")
}

// git を起動できないときは、入力の誤りではなく、道具を実行できないこととして返す。
func TestGitNotFoundIsRunError(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")

	t.Setenv("PATH", t.TempDir())
	wantError(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), 3, "run-error:", "git を起動できません")
}

// fakeGit は、git version の出力だけを versionLine に偽り、ほかのコマンドは本物の git に渡す
// git を書き込んだディレクトリを返す。PATH の先頭に置いて、版の確認を確かめるのに使う。
func fakeGit(t *testing.T, versionLine string) string {
	t.Helper()
	real, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	script := "#!/bin/sh\nif [ \"$1\" = version ]; then echo '" + versionLine + "'; exit 0; fi\nexec '" + real + "' \"$@\"\n"
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return bin
}

// git の版の確認は、2.30 を受け付けて 2.29 を拒む (README の前提の節に書いた要件)。版を読めない
// 出力も、道具を実行できないこととして返す。
func TestGitVersionBoundary(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	args := []string{"-file", "f.md", "-lines", "1", "-rev", "HEAD"}

	t.Run("2.30.0 は受け付ける", func(t *testing.T) {
		t.Setenv("PATH", fakeGit(t, "git version 2.30.0"))
		wantKind(t, r.check(base, args...), holds)
	})
	t.Run("2.29.9 は拒む", func(t *testing.T) {
		t.Setenv("PATH", fakeGit(t, "git version 2.29.9"))
		wantError(t, r.check(base, args...), 3, "run-error:", "git 2.30 以降が要ります")
	})
	t.Run("1.99.0 は拒む", func(t *testing.T) {
		t.Setenv("PATH", fakeGit(t, "git version 1.99.0"))
		wantError(t, r.check(base, args...), 3, "run-error:", "git 2.30 以降が要ります")
	})
	t.Run("3.0.0 は受け付ける", func(t *testing.T) {
		t.Setenv("PATH", fakeGit(t, "git version 3.0.0"))
		wantKind(t, r.check(base, args...), holds)
	})
	t.Run("版を読めない", func(t *testing.T) {
		t.Setenv("PATH", fakeGit(t, "not a version"))
		wantError(t, r.check(base, args...), 3, "run-error:", "git の版を読めません")
	})
}

// 部分クローンで欠けたオブジェクトを、道具がネットワークから取得してリポジトリに書き込まない。
// GIT_NO_LAZY_FETCH は git 2.44 からなので、それより前の git では飛ばす。
func TestPartialCloneDoesNotFetch(t *testing.T) {
	out, err := exec.Command("git", "version").Output()
	if major, minor, ok := parseGitVersion(string(out)); err != nil || !ok || major == 2 && minor < 44 {
		t.Skipf("GIT_NO_LAZY_FETCH を受け付けない git: %s", strings.TrimSpace(string(out)))
	}
	r, base := branched(t)
	r.write("f.md", "a\nb\nC\n")
	r.commit("change line 3")
	r.git("config", "uploadpack.allowFilter", "true")
	clone := &repo{t: t, dir: filepath.Join(t.TempDir(), "clone")}
	if out, err := exec.Command("git", "clone", "-q", "--no-local", "--filter=blob:none", "--branch", "br", "file://"+r.dir, clone.dir).CombinedOutput(); err != nil {
		t.Fatalf("git clone: %v: %s", err, out)
	}
	missing := func() string { return clone.git("rev-list", "--objects", "--all", "--missing=print") }
	before := missing()
	if !strings.Contains(before, "?") {
		t.Fatal("部分クローンに欠けたオブジェクトが無く、確かめられない")
	}

	o := clone.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD")
	if after := missing(); after != before {
		t.Fatalf("道具が欠けたオブジェクトを取得した。前:\n%s\n後:\n%s", before, after)
	}
	if o.kind == holds {
		t.Fatalf("起点の内容を読めないのに holds を返した: %s", o.stdout)
	}
}

// stallingGit は、引数に word を含む呼び出しで止まり、ほかのコマンドは本物の git に渡す偽の git を
// 書き込んだディレクトリを返す。止まるときは sleep を子のプロセスとして起動するので、期限で git (の偽物) を
// 止めても、sleep が標準出力を開いたまま残る。
func stallingGit(t *testing.T, word string) string {
	t.Helper()
	real, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	sleep, err := exec.LookPath("sleep")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	script := "#!/bin/sh\ncase \" $* \" in *\" " + word + " \"*) '" + sleep + "' 30;; esac\nexec '" + real + "' \"$@\"\n"
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return bin
}

// git が期限までに終わらなければ、道具は待ち続けずに run-error で終わる。止めた git の子の
// プロセスが標準出力を開いたままでも待たない (待つと、子が終わる 30 秒後まで返らない)。
func TestGitTimeoutIsRunError(t *testing.T) {
	r, base := branched(t)
	r.write("g.md", "branch\n")
	r.commit("branch")
	saved := gitTimeout
	gitTimeout = 2 * time.Second
	t.Cleanup(func() { gitTimeout = saved })

	t.Run("blame で止まる", func(t *testing.T) {
		t.Setenv("PATH", stallingGit(t, "blame"))
		start := time.Now()
		wantError(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), 3, "run-error:", "以内に終わりませんでした")
		if d := time.Since(start); d > 20*time.Second {
			t.Fatalf("期限を越えても %s 待った", d)
		}
	})
	t.Run("git version で止まる", func(t *testing.T) {
		t.Setenv("PATH", stallingGit(t, "version"))
		start := time.Now()
		wantError(t, r.check(base, "-file", "f.md", "-lines", "1", "-rev", "HEAD"), 3, "run-error:", "git version が")
		if d := time.Since(start); d > 20*time.Second {
			t.Fatalf("期限を越えても %s 待った", d)
		}
	})
}

func TestParseGitVersion(t *testing.T) {
	cases := []struct {
		in           string
		major, minor int
		ok           bool
	}{
		{"git version 2.50.1 (Apple Git-155)\n", 2, 50, true},
		{"git version 2.30.0.windows.1", 2, 30, true},
		{"git version 2.29.2", 2, 29, true},
		{"not git", 0, 0, false},
	}
	for _, c := range cases {
		major, minor, ok := parseGitVersion(c.in)
		if major != c.major || minor != c.minor || ok != c.ok {
			t.Errorf("parseGitVersion(%q) = %d, %d, %v (期待は %d, %d, %v)", c.in, major, minor, ok, c.major, c.minor, c.ok)
		}
	}
}

func TestParsePorcelainUnquotesFileName(t *testing.T) {
	out := strings.Join([]string{
		"0123456789012345678901234567890123456789 3 1 1",
		"boundary",
		`filename "\346\227\245.md"`,
		"\tline",
		"",
	}, "\n")
	lines, err := parsePorcelain(out)
	if err != nil {
		t.Fatal(err)
	}
	if len(lines) != 1 || lines[0].filename != "日.md" || !lines[0].boundary || lines[0].orig != 3 || lines[0].final != 1 {
		t.Fatalf("読み取りが違う: %+v", lines)
	}
}
