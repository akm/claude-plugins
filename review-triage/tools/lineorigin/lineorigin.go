package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// 結果の 3 つの値。D8 の条件 (1) が成り立つ・成り立たない・確かめられない。
const (
	holds        = "holds"
	notHolds     = "not-holds"
	unverifiable = "unverifiable"
)

type result struct {
	kind   string
	reason string
	lines  []lineResult // 行ごとの内訳。行を調べる前に結果が決まったときは空
}

type lineResult struct {
	line int
	kind string
	note string
}

// check は、opts の行が全量の起点からレビューした内容まで変わっていないかを確かめる。
// 入力の誤り (解決できない版・レビューした内容に無いファイルや行) は error で返し、結果にしない。
func check(opts options) (result, error) {
	if err := checkGitVersion(); err != nil {
		return result{}, err
	}
	top, err := toplevel(opts.root)
	if err != nil {
		return result{}, err
	}
	g := gitRunner{root: top}

	base, found, err := g.commit(opts.base)
	if err != nil {
		return result{}, err
	} else if !found {
		return result{}, inputf("-base をコミットに解決できません: %s", opts.base)
	}
	targetName := opts.rev
	if opts.worktree {
		targetName = "HEAD"
	}
	target, found, err := g.commit(targetName)
	if err != nil {
		return result{}, err
	} else if !found {
		return result{}, inputf("レビューした内容のコミット (%s) を解決できません", targetName)
	}

	// 全量の起点がレビューした内容のコミットと同じなら、範囲 <起点>..<コミット> が空になり、
	// コミット済みのどの行も起点にあったままと報告される。ブランチの変更と前からある行を区別できない。
	if base == target {
		return result{kind: unverifiable, reason: fmt.Sprintf("全量の起点 %s が、レビューした内容のコミット (%s) と同じで、このブランチの変更と前からある行を区別できない", short(base), targetName)}, nil
	}
	ok, err := g.isAncestor(base, target)
	if err != nil {
		return result{}, asRun(err)
	}
	if !ok {
		return result{kind: unverifiable, reason: fmt.Sprintf("全量の起点 %s が、レビューした内容のコミット (%s) の祖先ではない", short(base), targetName)}, nil
	}

	// 指摘の file は、レビューした内容にあるはず (根拠の照合 E1 を通っている)。無ければ入力の誤り。
	if opts.worktree {
		st, err := os.Stat(filepath.Join(top, filepath.FromSlash(opts.file)))
		if err != nil || !st.Mode().IsRegular() {
			return result{}, inputf("作業ツリーに -file のファイルがありません: %s", opts.file)
		}
	} else if ok, err := g.exists(target, opts.file); err != nil {
		return result{}, err
	} else if !ok {
		return result{}, inputf("レビューした内容 (%s) に -file のファイルがありません: %s", opts.rev, opts.file)
	}

	if ok, err := g.exists(base, opts.file); err != nil {
		return result{}, err
	} else if !ok {
		return result{kind: notHolds, reason: fmt.Sprintf("全量の起点 %s に同じパスのファイルが無い (このブランチで作った・改名した・移したファイル)", short(base))}, nil
	}
	if opts.worktree {
		if ok, err := g.exists(target, opts.file); err != nil {
			return result{}, err
		} else if !ok {
			return result{kind: notHolds, reason: "HEAD に同じパスのファイルが無い (コミットしていないファイル)"}, nil
		}
		// git blame --contents は、作業ツリーの内容を clean フィルタで変換してから見る。フィルタが行を
		// 増やしたり消したりすると、指摘の行番号 (作業ツリーの生の内容の行番号) が別の行に当たり、
		// 書き換えた行が起点のままと報告されうる (誤った holds)。行番号を対応させられないので確かめない
		filtered, err := g.hasCleanFilter(opts.file)
		if err != nil {
			return result{}, err
		}
		if filtered {
			return result{kind: unverifiable, reason: "指摘のファイルに clean フィルタ (属性 filter) が設定されていて、作業ツリーの行番号と、git blame が見るフィルタの後の内容の行番号がずれうる"}, nil
		}
	} else {
		// 結果のファイルで受け取ったレビューは、共有の作業ツリーでコミットしていない変更を見た可能性があり、
		// 結果のファイルからは分からない。ほかのファイルの変更は、指摘の file の行番号を変えないので見ない。
		changed, err := g.hasUncommittedChange(top, opts.file)
		if err != nil {
			return result{}, asRun(err)
		}
		if changed {
			return result{kind: unverifiable, reason: "指摘のファイルにコミットしていない変更があり、レビューがそれを見たかが分からない"}, nil
		}
	}

	blamed, err := g.blame(base, target, opts)
	if err != nil {
		return result{}, err
	}
	return classify(base, opts.file, blamed), nil
}

// classify は blame の結果を行ごとに分類し、全体の結果を決める。
// 成り立たない行が 1 つでもあれば成り立たない、無くて確かめられない行があれば確かめられない。
func classify(base, file string, blamed []blameLine) result {
	res := result{kind: holds}
	for _, b := range blamed {
		l := lineResult{line: b.final}
		switch {
		case isZero(b.commit):
			l.kind, l.note = notHolds, "コミットしていない行"
		case !b.boundary:
			l.kind, l.note = notHolds, fmt.Sprintf("全量の起点より後のコミット %s が書いた・書き換えた行", short(b.commit))
		case b.commit != base:
			// 起点より前に分かれた履歴をマージすると、行がその分岐点まで遡り、そこが境界になる。
			// その行が起点にもあったかは、この結果からは決められない。
			l.kind, l.note = unverifiable, fmt.Sprintf("全量の起点を通らない履歴 (起点より前に分かれた履歴のマージなど) から来た行で、境界のコミットが %s。全量の起点にあったかを決められない", short(b.commit))
		case b.filename != file:
			l.kind, l.note = notHolds, fmt.Sprintf("このブランチで改名・移動したファイルの行 (全量の起点では %s)", b.filename)
		default:
			l.kind, l.note = holds, "全量の起点にあったまま"
		}
		res.lines = append(res.lines, l)
		switch {
		case l.kind == notHolds:
			res.kind = notHolds
		case l.kind == unverifiable && res.kind == holds:
			res.kind = unverifiable
		}
	}
	switch res.kind {
	case notHolds:
		res.reason = "対象の行のうち、全量の起点から変わった行がある"
	case unverifiable:
		res.reason = "対象の行のうち、全量の起点にあったかを決められない行がある"
	default:
		res.reason = fmt.Sprintf("対象の行はどれも、全量の起点 %s にあったまま変わっていない", short(base))
	}
	return res
}

// lineCount は、レビューした内容の -file の行数を返す。数え方は git blame と同じで、
// 末尾に改行の無い最後の行も 1 行と数える。
func (g gitRunner) lineCount(target string, opts options) (int, error) {
	var content []byte
	if opts.worktree {
		b, err := os.ReadFile(filepath.Join(g.root, filepath.FromSlash(opts.file)))
		if err != nil {
			return 0, runf("作業ツリーの -file を読めません: %v", err)
		}
		content = b
	} else {
		out, _, err := g.run("cat-file", "-p", target+":"+opts.file)
		if err != nil {
			return 0, asRun(err)
		}
		content = []byte(out)
	}
	n := bytes.Count(content, []byte("\n"))
	if len(content) > 0 && content[len(content)-1] != '\n' {
		n++
	}
	return n, nil
}

type blameLine struct {
	final    int    // レビューした内容での行番号
	commit   string // その行を最後に変えたコミット。範囲の外なら境界のコミット
	boundary bool   // 範囲 <起点>..<コミット> の境界のコミットか
	filename string // そのコミットでのパス
}

var blameHeader = regexp.MustCompile(`^([0-9a-f]{40}|[0-9a-f]{64}) [0-9]+ ([0-9]+)( [0-9]+)?$`)

// parsePorcelain は git blame --line-porcelain の出力を読む。
func parsePorcelain(out string) ([]blameLine, error) {
	var lines []blameLine
	var cur *blameLine
	for _, s := range strings.Split(out, "\n") {
		if cur == nil {
			if s == "" {
				continue
			}
			m := blameHeader.FindStringSubmatch(s)
			if m == nil {
				return nil, fmt.Errorf("git blame の出力を読めません: %q", s)
			}
			n, _ := strconv.Atoi(m[2])
			cur = &blameLine{final: n, commit: m[1]}
			continue
		}
		switch {
		case strings.HasPrefix(s, "\t"):
			if cur.filename == "" {
				return nil, fmt.Errorf("git blame の出力に行 %d のファイル名がありません", cur.final)
			}
			lines = append(lines, *cur)
			cur = nil
		case s == "boundary":
			cur.boundary = true
		case strings.HasPrefix(s, "filename "):
			name, err := unquotePath(strings.TrimPrefix(s, "filename "))
			if err != nil {
				return nil, err
			}
			cur.filename = name
		}
	}
	if cur != nil {
		return nil, fmt.Errorf("git blame の出力が行 %d の途中で終わっています", cur.final)
	}
	return lines, nil
}

// unquotePath は、git が引用符で囲んで出したパス (日本語や " を含むもの。例: "\346\227\245.md") を元に戻す。
func unquotePath(s string) (string, error) {
	if !strings.HasPrefix(s, `"`) {
		return s, nil
	}
	u, err := strconv.Unquote(s)
	if err != nil {
		return "", fmt.Errorf("git blame の出力のファイル名を読めません: %s", s)
	}
	return u, nil
}

func isZero(sha string) bool { return strings.Trim(sha, "0") == "" }

func short(sha string) string {
	if len(sha) > 12 {
		return sha[:12]
	}
	return sha
}

// gitRunner は、リポジトリのルートを基準に git を実行する。
type gitRunner struct{ root string }

// toplevel は -root からリポジトリのルートを求める。入力の誤りにするのは、-root が存在する
// ディレクトリでないときと、-root から上のどこにも .git が無いときだけ。.git があるのに git が
// リポジトリとして読めない (権限・所有者など) ときは、渡し方では直せないので run-error にする。
// git は .git を読めないときも「not a git repository」と言うので、.git の有無は道具が確かめる。
func toplevel(dir string) (string, error) {
	if st, err := os.Stat(dir); err != nil || !st.IsDir() {
		return "", inputf("-root が存在するディレクトリではありません: %s", dir)
	}
	out, _, err := gitRunner{root: dir}.run("rev-parse", "--show-toplevel")
	if err == nil {
		return strings.TrimSpace(out), nil
	}
	var re *runError
	if errors.As(err, &re) {
		return "", err
	}
	if strings.Contains(err.Error(), "not a git repository") {
		if dotGit, ok := findDotGit(dir); ok {
			return "", runf("%s があるが、git がリポジトリとして読めません: %v", dotGit, err)
		}
		return "", inputf("-root が git のリポジトリの中を指していません: %s", dir)
	}
	return "", runf("-root のリポジトリを git で読めません: %v", err)
}

// findDotGit は、dir から上のディレクトリをたどって、最初に見つかった .git (ディレクトリか、
// 作業ツリーが持つファイル) のパスを返す。
func findDotGit(dir string) (string, bool) {
	for d := filepath.Clean(dir); ; d = filepath.Dir(d) {
		p := filepath.Join(d, ".git")
		if _, err := os.Lstat(p); err == nil {
			return p, true
		}
		if filepath.Dir(d) == d {
			return "", false
		}
	}
}

// run は git を実行し、標準出力と終了コードを返す。終了コードが 0 でなければ error も返す。
//
// どのディレクトリから実行しても同じ結果になるよう、-C でルートを指定する。環境は gitEnv が作る。
func (g gitRunner) run(args ...string) (string, int, error) {
	return g.runIn(nil, args...)
}

// gitTimeout は、git の 1 回の実行に許す時間。越えたら run-error にする。git や、git が起動する
// フィルタのプログラムが止まったときに、道具が終わらなくなるのを防ぐ。テストが短くする。
var gitTimeout = 5 * time.Minute

// runIn は、stdin を標準入力に渡して run と同じように git を実行する。
func (g gitRunner) runIn(stdin io.Reader, args ...string) (string, int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), gitTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", append([]string{"-C", g.root, "-c", "core.quotePath=false"}, args...)...)
	cmd.WaitDelay = time.Second // 期限で止めた git の子のプロセスが出力を開いたままでも、待ち続けない
	cmd.Env = gitEnv()
	cmd.Stdin = stdin
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return "", -1, runf("git %s が %s 以内に終わりませんでした", strings.Join(args, " "), gitTimeout)
	}
	if err == nil {
		return stdout.String(), 0, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return stdout.String(), exitErr.ExitCode(), fmt.Errorf("git %s: %s", strings.Join(args, " "), strings.TrimSpace(stderr.String()))
	}
	return "", -1, runf("git を起動できません: %v", err)
}

var gitVersionRe = regexp.MustCompile(`^git version ([0-9]+)\.([0-9]+)`)

// checkGitVersion は、git を起動できることと、道具が要る版 (2.30 以降。関数 commit が使う
// git rev-parse --end-of-options が 2.30.0 から) であることを確かめる。古い git では、正しい版を
// 渡しても解決できないので、入力の誤りと取り違えないよう、道具を実行できないこととして返す。
func checkGitVersion() error {
	ctx, cancel := context.WithTimeout(context.Background(), gitTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", "version")
	cmd.WaitDelay = time.Second
	cmd.Env = gitEnv()
	out, err := cmd.Output()
	if ctx.Err() == context.DeadlineExceeded {
		return runf("git version が %s 以内に終わりませんでした", gitTimeout)
	}
	if err != nil {
		return runf("git を起動できません: %v", err)
	}
	major, minor, ok := parseGitVersion(string(out))
	if !ok {
		return runf("git の版を読めません: %s", strings.TrimSpace(string(out)))
	}
	if major < 2 || major == 2 && minor < 30 {
		return runf("git 2.30 以降が要ります (git rev-parse --end-of-options を使うため)。この git は %s", strings.TrimSpace(string(out)))
	}
	return nil
}

func parseGitVersion(s string) (major, minor int, ok bool) {
	m := gitVersionRe.FindStringSubmatch(strings.TrimSpace(s))
	if m == nil {
		return 0, 0, false
	}
	major, _ = strconv.Atoi(m[1])
	minor, _ = strconv.Atoi(m[2])
	return major, minor, true
}

// extraGitEnv は、gitEnv が GIT_ で始まる変数を取り除いた後に足す変数。本番では空で、
// テストがシステムの git の設定を読ませないために使う (取り除く前に設定しても届かないため)。
var extraGitEnv []string

// gitEnv は git に渡す環境を作る。利用者の環境の GIT_ で始まる変数は、リポジトリの場所を替える
// (GIT_DIR・GIT_WORK_TREE・GIT_INDEX_FILE など)、設定を注入する (GIT_CONFIG_PARAMETERS・
// GIT_CONFIG_COUNT など)、パスの読み方を替える (GIT_GLOB_PATHSPECS など) ので、-root と違う
// リポジトリや設定を読ませないよう、すべて取り除いてから道具が要るものだけを足す。
func gitEnv() []string {
	var env []string
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(kv, "GIT_") {
			env = append(env, kv)
		}
	}
	env = append(env,
		// git の文言 (not a git repository など) を、利用者の言語の設定によらず英語にして比べられるようにする
		"LC_ALL=C",
		// パスを pathspec (パターンや先頭の : で始まる指定) として解釈させない
		"GIT_LITERAL_PATHSPECS=1",
		// git replace の置き換えを見ない。見ると、blame が置き換えた後の履歴で、行を最後に変えたコミットを求める
		"GIT_NO_REPLACE_OBJECTS=1",
		// 部分クローンで欠けたオブジェクトを、ネットワークから取得してリポジトリに書き込まない (git 2.44 以降)。
		// 取得できないと git は失敗し、道具は run-error になる
		"GIT_NO_LAZY_FETCH=1",
		// 認証などで利用者に尋ねて待たない
		"GIT_TERMINAL_PROMPT=0",
	)
	return append(env, extraGitEnv...)
}

// commit は版をコミットの完全な SHA に解決する。版が無いとき (--quiet で終了コード 1) は
// found を false にする。それ以外の失敗 (リポジトリを読めない、など) は run-error。
func (g gitRunner) commit(rev string) (sha string, found bool, err error) {
	out, code, err := g.run("rev-parse", "--verify", "--quiet", "--end-of-options", rev+"^{commit}")
	switch {
	case err == nil:
		return strings.TrimSpace(out), true, nil
	case code == 1:
		return "", false, nil
	default:
		return "", false, asRun(err)
	}
}

func (g gitRunner) isAncestor(a, b string) (bool, error) {
	_, code, err := g.run("merge-base", "--is-ancestor", a, b)
	switch code {
	case 0:
		return true, nil
	case 1:
		return false, nil
	default:
		return false, err
	}
}

// exists は、コミット commit の file のパスにファイル (ブロブ) があるかを返す。パスが無いときと、
// ファイルでないもの (ディレクトリなど) のときは false。git が失敗したとき (オブジェクトを読めない、
// など) は、パスが無いことと取り違えないよう run-error を返す。commit は解決済みの SHA。
func (g gitRunner) exists(commit, file string) (bool, error) {
	out, _, err := g.run("ls-tree", "-z", commit, "--", file)
	if err != nil {
		return false, asRun(err)
	}
	for _, entry := range strings.Split(out, "\x00") {
		meta, path, ok := strings.Cut(entry, "\t")
		if !ok || path != file {
			continue
		}
		fields := strings.Fields(meta)
		return len(fields) == 3 && fields[1] == "blob", nil
	}
	return false, nil
}

// hasUncommittedChange は、file に HEAD からのコミットしていない変更 (ステージしたものを含む) があるかを返す。
//
// git diff は使わない。インデックスに記録した更新時刻などが作業ツリーのファイルと合わないと、
// GIT_OPTIONAL_LOCKS=0 を立ててもそれを更新してインデックスを書き換えるため。代わりに、HEAD・インデックス・
// 作業ツリーの内容のハッシュを比べる。インデックスに記録した更新時刻などに頼らないので、skip-worktree や assume-unchanged が付いた
// ファイルの編集も変更として扱う。
func (g gitRunner) hasUncommittedChange(top, file string) (bool, error) {
	head, err := g.blob("HEAD", file)
	if err != nil {
		return false, err
	}
	out, _, err := g.run("ls-files", "--stage", "--", file)
	if err != nil {
		return false, err
	}
	var index string
	if entries := strings.Split(strings.TrimSpace(out), "\n"); out != "" {
		if len(entries) != 1 {
			return true, nil // 衝突の解消の途中 (段が複数ある)
		}
		fields := strings.Fields(entries[0])
		if len(fields) < 3 || fields[2] != "0" {
			return true, nil
		}
		index = fields[1]
	}
	// 作業ツリーの内容のハッシュを、git が記録するのと同じ形で求める。git が記録するのは通常の
	// ファイルとシンボリックリンクだけで、シンボリックリンクはリンクの先ではなくリンクの文字列を記録する
	var worktree string
	abs := filepath.Join(top, filepath.FromSlash(file))
	st, err := os.Lstat(abs)
	switch {
	case os.IsNotExist(err):
		// 作業ツリーから消した。worktree は空のまま
	case err != nil:
		return false, runf("作業ツリーの -file を読めません: %v", err)
	case st.Mode().IsRegular():
		// --path で、そのパスの属性によるフィルタ (改行の変換など) を当ててからハッシュを求める。-w を付けないので書き込まない
		out, _, err := g.run("hash-object", "--path="+file, "--", abs)
		if err != nil {
			return false, err
		}
		worktree = strings.TrimSpace(out)
	case st.Mode()&os.ModeSymlink != 0:
		link, err := os.Readlink(abs)
		if err != nil {
			return false, runf("作業ツリーの -file のリンクを読めません: %v", err)
		}
		out, _, err := g.runIn(strings.NewReader(link), "hash-object", "--no-filters", "--stdin")
		if err != nil {
			return false, err
		}
		worktree = strings.TrimSpace(out)
	default:
		// ディレクトリなど、git が記録しない種類に置き換わっている
		return true, nil
	}
	return head != index || index != worktree, nil
}

// hasCleanFilter は、file に属性 filter (git add のときにファイルを変換するプログラム) が
// 設定されているかを返す。属性 filter の値はドライバ (設定 filter.<名前>.clean などで登録する、
// 変換のプログラムの名前) で、設定の無いドライバの名前や、値の無い filter も「あり」とする。
// 「あり」なら呼び出し元は確かめずに unverifiable を返すので、迷う場合を「あり」として扱っても、
// 誤った holds にはならない。
func (g gitRunner) hasCleanFilter(file string) (bool, error) {
	// -a は、値のある属性 (unset を含む) だけを出し、属性が無い (unspecified) ものは出さない。
	// filter だけを尋ねると、属性が無いことと、名前が unspecified のドライバを同じ出力で返す
	out, _, err := g.run("check-attr", "-a", "-z", "--", file)
	if err != nil {
		return false, asRun(err)
	}
	// -z の出力は「<パス> NUL <属性> NUL <値> NUL」の繰り返しで、属性が無ければ空。NUL で分けると、
	// 要素の数は 3 の倍数に 1 を足した数になり、最後は空になる。そうでない出力は読めないので run-error にする
	// (読めない出力をフィルタ無しとして扱い、git blame で行を調べに進むと、誤った holds になりうる)
	parts := strings.Split(out, "\x00")
	if len(parts)%3 != 1 || parts[len(parts)-1] != "" {
		return false, runf("git check-attr の出力を読めません: %q", out)
	}
	for k := 0; k+2 < len(parts); k += 3 {
		if parts[k+1] != "filter" {
			continue
		}
		if parts[k+2] != "unset" {
			return true, nil
		}
		// unset は、-filter (フィルタを外す) と、名前が unset のドライバを区別できないので、
		// そのドライバの設定があれば「あり」とする
		_, code, err := g.run("config", "--get-regexp", `^filter\.unset\.(clean|process)$`)
		switch code {
		case 0:
			return true, nil
		case 1:
			return false, nil
		default:
			return false, asRun(err)
		}
	}
	return false, nil
}

// blob は、コミット commit の file のブロブの SHA を返す。そのパスが無ければ空。
func (g gitRunner) blob(commit, file string) (string, error) {
	out, code, err := g.run("rev-parse", "--verify", "--quiet", commit+":"+file)
	switch {
	case err == nil:
		return strings.TrimSpace(out), nil
	case code == 1:
		return "", nil
	default:
		return "", err
	}
}

// blame は、範囲 <起点>..<コミット> で opts の行を最後に変えたコミットを求める。
// 範囲を起点で区切ると、起点から変わっていない行は起点が境界 (boundary) として報告される。
func (g gitRunner) blame(base, target string, opts options) ([]blameLine, error) {
	args := []string{
		"blame",
		// 範囲の中のルートのコミット (無関係な履歴のマージ) を境界として扱わず、そのコミットの行として報告させる
		"--root",
		// 設定 blame.ignoreRevsFile に挙げたコミットを無視すると、そのコミットが書き換えた行が起点のままと報告される
		"--ignore-revs-file", "",
		// diff の textconv (比べる前にファイルを別の形へ変換する設定) で変換した行を比べると、
		// 変換で消える部分だけを書き換えた行が、起点のままと報告される
		"--no-textconv",
		"--line-porcelain",
		"-L", fmt.Sprintf("%d,%d", opts.from, opts.to),
	}
	if opts.worktree {
		args = append(args, "--contents", filepath.Join(g.root, filepath.FromSlash(opts.file)))
	}
	// 行がレビューした内容の行数を越えるのは渡し方の誤りなので、blame の前に道具が数えて
	// input-error にする。blame そのものの失敗は、渡し方では説明できないので run-error にする
	n, err := g.lineCount(target, opts)
	if err != nil {
		return nil, err
	}
	if opts.to > n {
		return nil, inputf("行 %d が、レビューした内容の -file の行数 (%d) を越えます", opts.to, n)
	}
	args = append(args, base+".."+target, "--", opts.file)
	out, _, err := g.run(args...)
	if err != nil {
		return nil, asRun(err)
	}
	lines, err := parsePorcelain(out)
	if err != nil {
		return nil, asRun(err)
	}
	if want := opts.to - opts.from + 1; len(lines) != want {
		return nil, runf("git blame が %d 行を返しました (求めたのは %d 行)", len(lines), want)
	}
	return lines, nil
}
