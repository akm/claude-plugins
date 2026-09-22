// nearedges は Markdown の修正の差分から「近くの辺」— 変更した箇所と同じ表の全行・
// 同じ箇条書きとその親・同じ節の全文・変更行が参照する先 — を列挙する。
//
// review-triage-fix の段 3 (修正) でコミットの前に読む範囲を、人の判断ではなく差分から
// 決めるための道具 (verification.md の観点 B)。-hints を付けると、差分の種類に応じて
// 当てる観点 (B・C・F) も提示する。
//
// 使い方 (diff は標準入力か -diff で渡す。-root はリポジトリのルートの絶対パス):
//
//	git diff <base>..<head> -- '*.md' | go run -C <展開先>/tools/nearedges . -root "$(pwd)"
//	git diff --cached -- '*.md' | go run -C <展開先>/tools/nearedges . -root "$(pwd)" -hints
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string, stdin io.Reader, stdout io.Writer) error {
	fs := flag.NewFlagSet("nearedges", flag.ContinueOnError)
	root := fs.String("root", "", "リポジトリのルート (絶対パス。必須)。diff のパスをここから解決する")
	diffPath := fs.String("diff", "-", "unified diff のファイル。\"-\" なら標準入力")
	withHints := fs.Bool("hints", false, "差分の種類に応じた検証の観点 (B・C・F) も提示する")
	noContent := fs.Bool("no-content", false, "範囲の本文を出さず、位置だけを出す")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *root == "" || !filepath.IsAbs(*root) {
		return fmt.Errorf("-root にリポジトリのルートの絶対パスを渡してください")
	}
	if st, err := os.Stat(*root); err != nil || !st.IsDir() {
		return fmt.Errorf("-root が実在するディレクトリではありません: %s", *root)
	}
	var r io.Reader = stdin
	if *diffPath != "-" {
		f, err := os.Open(*diffPath)
		if err != nil {
			return err
		}
		defer f.Close()
		r = f
	}
	changes, err := parseUnifiedDiff(r)
	if err != nil {
		return err
	}
	edges, err := nearEdges(*root, changes)
	if err != nil {
		return err
	}
	fmt.Fprint(stdout, render(*root, edges, !*noContent))
	if *withHints {
		hs := hints(changes, edges)
		fmt.Fprintln(stdout, "# 当てる観点 (verification.md)")
		fmt.Fprintln(stdout)
		if len(hs) == 0 {
			fmt.Fprintln(stdout, "差分の種類から導ける観点はありません (観点 A・D・E は差分の形から導けないので、修正の内容で判断する)")
		}
		for _, h := range hs {
			fmt.Fprintln(stdout, "- "+h)
		}
	}
	return nil
}
