package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
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
	top, err := toplevel(opts.root)
	if err != nil {
		return result{}, err
	}
	g := gitRunner{root: top}

	base, err := g.commit(opts.base)
	if err != nil {
		return result{}, fmt.Errorf("-base をコミットに解決できません: %s", opts.base)
	}
	targetName := opts.rev
	if opts.worktree {
		targetName = "HEAD"
	}
	target, err := g.commit(targetName)
	if err != nil {
		return result{}, fmt.Errorf("レビューした内容のコミット (%s) を解決できません", targetName)
	}

	// 全量の起点がレビューした内容のコミットと同じなら、範囲 <起点>..<コミット> が空になり、
	// コミット済みのどの行も起点にあったままと報告される。ブランチの変更と前からある行を区別できない。
	if base == target {
		return result{kind: unverifiable, reason: fmt.Sprintf("全量の起点 %s が、レビューした内容のコミット (%s) と同じで、このブランチの変更と前からある行を区別できない", short(base), targetName)}, nil
	}
	ok, err := g.isAncestor(base, target)
	if err != nil {
		return result{}, err
	}
	if !ok {
		return result{kind: unverifiable, reason: fmt.Sprintf("全量の起点 %s が、レビューした内容のコミット (%s) の祖先ではない", short(base), targetName)}, nil
	}

	// 指摘の file は、レビューした内容にあるはず (根拠の照合 E1 を通っている)。無ければ入力の誤り。
	if opts.worktree {
		st, err := os.Stat(filepath.Join(top, filepath.FromSlash(opts.file)))
		if err != nil || !st.Mode().IsRegular() {
			return result{}, fmt.Errorf("作業ツリーに -file のファイルがありません: %s", opts.file)
		}
	} else if !g.exists(target, opts.file) {
		return result{}, fmt.Errorf("レビューした内容 (%s) に -file のファイルがありません: %s", opts.rev, opts.file)
	}

	if !g.exists(base, opts.file) {
		return result{kind: notHolds, reason: fmt.Sprintf("全量の起点 %s に同じパスのファイルが無い (このブランチで作った・改名した・移したファイル)", short(base))}, nil
	}
	if opts.worktree {
		if !g.exists(target, opts.file) {
			return result{kind: notHolds, reason: "HEAD に同じパスのファイルが無い (コミットしていないファイル)"}, nil
		}
	} else {
		// 結果のファイルで受け取ったレビューは、共有の作業ツリーでコミットしていない変更を見た可能性があり、
		// 結果のファイルからは分からない。ほかのファイルの変更は、指摘の file の行番号を変えないので見ない。
		changed, err := g.hasUncommittedChange(opts.file)
		if err != nil {
			return result{}, err
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

func toplevel(dir string) (string, error) {
	out, _, err := gitRunner{root: dir}.run("rev-parse", "--show-toplevel")
	if err != nil {
		return "", fmt.Errorf("-root が git のリポジトリの中を指していません: %s", dir)
	}
	return strings.TrimSpace(out), nil
}

// run は git を実行し、標準出力と終了コードを返す。終了コードが 0 でなければ error も返す。
//
// どのディレクトリから実行しても同じ結果になるよう、-C でルートを指定する。環境は gitEnv が作る。
func (g gitRunner) run(args ...string) (string, int, error) {
	cmd := exec.Command("git", append([]string{"-C", g.root, "-c", "core.quotePath=false"}, args...)...)
	cmd.Env = gitEnv()
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	if err == nil {
		return stdout.String(), 0, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return stdout.String(), exitErr.ExitCode(), fmt.Errorf("git %s: %s", strings.Join(args, " "), strings.TrimSpace(stderr.String()))
	}
	return "", -1, fmt.Errorf("git を実行できません: %w", err)
}

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
	return append(env,
		// パスを pathspec (パターンや先頭の : で始まる指定) として解釈させない
		"GIT_LITERAL_PATHSPECS=1",
		"GIT_OPTIONAL_LOCKS=0",
		// git replace の置き換えを見ない。見ると、blame が置き換えた後の履歴で、行を最後に変えたコミットを求める
		"GIT_NO_REPLACE_OBJECTS=1",
	)
}

// commit は版をコミットの完全な SHA に解決する。
func (g gitRunner) commit(rev string) (string, error) {
	out, _, err := g.run("rev-parse", "--verify", "--quiet", "--end-of-options", rev+"^{commit}")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
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

// exists は、コミット commit に file のパスがあるかを返す。
func (g gitRunner) exists(commit, file string) bool {
	_, _, err := g.run("cat-file", "-e", commit+":"+file)
	return err == nil
}

// hasUncommittedChange は、file に HEAD からのコミットしていない変更 (ステージしたものを含む) があるかを返す。
func (g gitRunner) hasUncommittedChange(file string) (bool, error) {
	_, code, err := g.run("diff", "--quiet", "HEAD", "--", file)
	switch code {
	case 0:
		return false, nil
	case 1:
		return true, nil
	default:
		return false, err
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
	args = append(args, base+".."+target, "--", opts.file)
	out, _, err := g.run(args...)
	if err != nil {
		return nil, err
	}
	lines, err := parsePorcelain(out)
	if err != nil {
		return nil, err
	}
	if want := opts.to - opts.from + 1; len(lines) != want {
		return nil, fmt.Errorf("git blame が %d 行を返しました (求めたのは %d 行)", len(lines), want)
	}
	return lines, nil
}
