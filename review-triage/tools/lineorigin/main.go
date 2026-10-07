// lineorigin は、レビューの指摘の対象の行が、全量の起点 (ブランチの作り始めのコミット) から、
// レビューした内容まで変わっていないかを確かめる。review-triage の判定ノード D8 の条件 (1)。
//
// 結果は「成り立つ」(holds)・「成り立たない」(not-holds)・「確かめられない」(unverifiable) の 3 つで、
// 理由と行ごとの内訳を添えて標準出力に書く。結果を出せないときは標準出力に何も書かず、
// 標準エラー出力の最初の行に印を付けて書く。入力の誤り (フラグの不足・解決できない版・
// レビューした内容に無いファイルや行) は input-error:、道具を実行できないこと (git を起動できない・
// git が古い・git の出力を読めない) は run-error:。コマンド go run で実行すると終了コードは 1 になるので、
// 終了コード (2 と 3) ではなく印で見分ける。
//
// 使い方 (-root はレビューした作業ツリーのルートか、その中のディレクトリの絶対パス。値は単一引用符で囲む):
//
//	go run -C '<展開先>/tools/lineorigin' . -root '<作業ツリーのルート>' -base '<全量の起点>' -file '<ファイル>' -lines '<行>' -rev '<コミット>'
//	go run -C '<展開先>/tools/lineorigin' . -root '<作業ツリーのルート>' -base '<全量の起点>' -file '<ファイル>' -lines '<開始>-<終了>' -worktree
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// run はフラグを読んで確かめ、結果を stdout に書く。戻り値は終了コード
// (0: 結果を出した、2: 入力の誤り、3: 道具を実行できない)。
func run(args []string, stdout, stderr io.Writer) int {
	opts, err := parseFlags(args)
	if err != nil {
		return report(stderr, inputf("%v", err))
	}
	res, err := check(opts)
	if err != nil {
		return report(stderr, err)
	}
	writeResult(stdout, res)
	return 0
}

type options struct {
	root     string      // -root (絶対パス)
	base     string      // -base
	file     string      // -file (ルートからの相対パス。整えたもの)
	ranges   []lineRange // -lines (並べ替え、重なりと隣り合いをまとめたもの)
	rev      string      // -rev (-worktree のときは空)
	worktree bool        // -worktree
}

func parseFlags(args []string) (options, error) {
	fs := flag.NewFlagSet("lineorigin", flag.ContinueOnError)
	// パッケージ flag は誤りのときに使い方を書き出すが、標準エラー出力の最初の行を印にするため捨てる
	// (フラグの一覧は、ファイル review-triage/tools/lineorigin/README.md の「使い方」)
	fs.SetOutput(io.Discard)
	root := fs.String("root", "", "リポジトリのルートか、その中のディレクトリの絶対パス (必須)")
	base := fs.String("base", "", "全量の起点 (必須)。コミットに解決できる版")
	file := fs.String("file", "", "指摘の file (必須)。リポジトリのルートからの相対パス")
	lines := fs.String("lines", "", "指摘の行 (必須)。「12」「12-15」か、それらをコンマで並べた形 (「12,20-23」)")
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
	ranges, err := parseLines(*lines)
	if err != nil {
		return options{}, err
	}
	return options{root: *root, base: *base, file: f, ranges: ranges, rev: *rev, worktree: *worktree}, nil
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

// lineRange は、両端を含む行の範囲。
type lineRange struct {
	from, to int
}

// parseLines は「12」「12-15」か、それらをコンマで並べた形 (「12,20-23」) を読み、範囲を始めの順に
// 並べ、重なる範囲と隣り合う範囲をまとめて返す。連続しない行にまたがる指摘を 1 回で渡すため。
func parseLines(s string) ([]lineRange, error) {
	var ranges []lineRange
	for _, part := range strings.Split(s, ",") {
		a, b, isRange := strings.Cut(part, "-")
		from, err := strconv.Atoi(a)
		if err != nil || from < 1 {
			return nil, fmt.Errorf("-lines は「12」「12-15」か、それらをコンマで並べた形 (「12,20-23」) で、1 以上の行番号を渡してください: %s", s)
		}
		to := from
		if isRange {
			to, err = strconv.Atoi(b)
			if err != nil || to < from {
				return nil, fmt.Errorf("-lines の範囲は、終わりを始め以上にしてください: %s", s)
			}
		}
		ranges = append(ranges, lineRange{from, to})
	}
	sort.Slice(ranges, func(i, j int) bool { return ranges[i].from < ranges[j].from })
	merged := ranges[:1]
	for _, r := range ranges[1:] {
		last := &merged[len(merged)-1]
		if r.from <= last.to+1 {
			last.to = max(last.to, r.to)
			continue
		}
		merged = append(merged, r)
	}
	return merged, nil
}

func writeResult(w io.Writer, res result) {
	fmt.Fprintf(w, "result: %s\n", res.kind)
	fmt.Fprintf(w, "reason: %s\n", res.reason)
	for _, l := range res.lines {
		fmt.Fprintf(w, "line %d: %s\n", l.line, l.note)
	}
}
