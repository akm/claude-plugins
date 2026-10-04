// lineorigin は、レビューの指摘の対象の行が、全量の起点 (ブランチの作り始めのコミット) から、
// レビューした内容まで変わっていないかを確かめる。review-triage の判定ノード D8 の条件 (1)。
//
// 結果は「成り立つ」(holds)・「成り立たない」(not-holds)・「確かめられない」(unverifiable) の 3 つで、
// 理由と行ごとの内訳を添えて標準出力に書く。入力の誤り (フラグの不足・解決できない版・
// レビューした内容に無いファイルや行) は結果にせず、標準エラー出力に書いて終了コード 2 で終わる。
//
// 使い方 (-root はリポジトリのルートか、その中のディレクトリの絶対パス):
//
//	go run -C <展開先>/tools/lineorigin . -root "$(pwd)" -base <全量の起点> -file <ファイル> -lines <行> -rev <コミット>
//	go run -C <展開先>/tools/lineorigin . -root "$(pwd)" -base <全量の起点> -file <ファイル> -lines <開始>-<終了> -worktree
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// run はフラグを読んで確かめ、結果を stdout に書く。戻り値は終了コード (0: 結果を出した、2: 入力の誤り)。
func run(args []string, stdout, stderr io.Writer) int {
	opts, err := parseFlags(args, stderr)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	res, err := check(opts)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	writeResult(stdout, res)
	return 0
}

type options struct {
	root     string // -root (絶対パス)
	base     string // -base
	file     string // -file (ルートからの相対パス。整えたもの)
	from, to int    // -lines
	rev      string // -rev (-worktree のときは空)
	worktree bool   // -worktree
}

func parseFlags(args []string, stderr io.Writer) (options, error) {
	fs := flag.NewFlagSet("lineorigin", flag.ContinueOnError)
	fs.SetOutput(stderr)
	root := fs.String("root", "", "リポジトリのルートか、その中のディレクトリの絶対パス (必須)")
	base := fs.String("base", "", "全量の起点 (必須)。コミットに解決できる版")
	file := fs.String("file", "", "指摘の file (必須)。リポジトリのルートからの相対パス")
	lines := fs.String("lines", "", "指摘の行 (必須)。「12」か「12-15」の形")
	rev := fs.String("rev", "", "レビューした内容のコミット。結果のファイルで受け取ったレビューならその head。-worktree と同時には使えない")
	worktree := fs.Bool("worktree", false, "レビューした内容が作業ツリー (コミットしていない変更を含む) のとき。-rev と同時には使えない")
	if err := fs.Parse(args); err != nil {
		return options{}, err
	}
	if fs.NArg() > 0 {
		return options{}, fmt.Errorf("余分な引数があります: %s", strings.Join(fs.Args(), " "))
	}
	var missing []string
	for _, f := range []struct {
		name, value string
	}{{"-root", *root}, {"-base", *base}, {"-file", *file}, {"-lines", *lines}} {
		if f.value == "" {
			missing = append(missing, f.name)
		}
	}
	if len(missing) > 0 {
		return options{}, fmt.Errorf("必須のフラグがありません: %s", strings.Join(missing, " "))
	}
	if (*rev == "") == !*worktree {
		return options{}, errors.New("レビューした内容を、-rev <コミット> か -worktree のどちらか 1 つで指定してください")
	}
	if !filepath.IsAbs(*root) {
		return options{}, fmt.Errorf("-root には絶対パスを渡してください (go run -C で実行すると、相対パスは道具のディレクトリを基準に読まれます): %s", *root)
	}
	f, err := normalizeFile(*file)
	if err != nil {
		return options{}, err
	}
	from, to, err := parseLines(*lines)
	if err != nil {
		return options{}, err
	}
	return options{root: *root, base: *base, file: f, from: from, to: to, rev: *rev, worktree: *worktree}, nil
}

// normalizeFile は -file をルートからの相対パスに整える。ルートの外を指すパスは受け付けない。
func normalizeFile(file string) (string, error) {
	if filepath.IsAbs(file) {
		return "", fmt.Errorf("-file にはリポジトリのルートからの相対パスを渡してください: %s", file)
	}
	clean := filepath.ToSlash(filepath.Clean(file))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
		return "", fmt.Errorf("-file がリポジトリの中のファイルを指していません: %s", file)
	}
	return clean, nil
}

// parseLines は「12」か「12-15」を読む。
func parseLines(s string) (int, int, error) {
	a, b, isRange := strings.Cut(s, "-")
	from, err := strconv.Atoi(a)
	if err != nil || from < 1 {
		return 0, 0, fmt.Errorf("-lines は「12」か「12-15」の形で、1 以上の行番号を渡してください: %s", s)
	}
	if !isRange {
		return from, from, nil
	}
	to, err := strconv.Atoi(b)
	if err != nil || to < from {
		return 0, 0, fmt.Errorf("-lines は「12」か「12-15」の形で、終わりを始め以上にしてください: %s", s)
	}
	return from, to, nil
}

func writeResult(w io.Writer, res result) {
	fmt.Fprintf(w, "result: %s\n", res.kind)
	fmt.Fprintf(w, "reason: %s\n", res.reason)
	for _, l := range res.lines {
		fmt.Fprintf(w, "line %d: %s\n", l.line, l.note)
	}
}
