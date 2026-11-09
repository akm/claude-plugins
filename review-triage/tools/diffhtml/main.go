// diffhtml は、HTML のファイルに書いたマークのコメントを、差分を表示する HTML に置き換える。
//
// review-triage-fix が説明の HTML (選択待ちの問題を判断するためのものと、直した問題を確認するためのもの) を
// 作るときに使う。差分の文字列をモデルにコピーさせず、記録 YAML の案のパッチと git のコミットから取るためのツール。
// マークの形・置き換え方・使い方の SSOT は README.md。
//
// 使い方:
//
//	go run -C <展開先>/tools/diffhtml . -html <HTML の絶対パス> -record <記録 YAML の絶対パス> -root <リポジトリのルートの絶対パス>
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("diffhtml", flag.ContinueOnError)
	htmlPath := fs.String("html", "", "マークを書いた HTML のファイル (絶対パス。必須)。成功したときだけ上書きする")
	recordPath := fs.String("record", "", "記録 YAML (絶対パス。必須)。案のパッチのマークはここから取る")
	root := fs.String("root", "", "リポジトリのルート (絶対パス。必須)。コミットのマークは、ここで git show を実行して取る")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() > 0 {
		return fmt.Errorf("余分な引数があります: %s", strings.Join(fs.Args(), " "))
	}
	if err := requireAbsFile("-html", *htmlPath); err != nil {
		return err
	}
	if err := requireAbsFile("-record", *recordPath); err != nil {
		return err
	}
	if *root == "" || !filepath.IsAbs(*root) {
		return errors.New("-root にリポジトリのルートの絶対パスを渡してください")
	}
	if st, err := os.Stat(*root); err != nil || !st.IsDir() {
		return fmt.Errorf("-root が実在するディレクトリではありません: %s", *root)
	}

	src, err := os.ReadFile(*htmlPath)
	if err != nil {
		return err
	}
	rec, err := loadRecord(*recordPath)
	if err != nil {
		return err
	}
	out, err := fill(string(src), sources{record: rec, git: gitRunner{root: *root}})
	if err != nil {
		return fmt.Errorf("%s を変えずに終了します:\n%w", *htmlPath, err)
	}
	return writeAtomic(*htmlPath, []byte(out))
}

func requireAbsFile(name, path string) error {
	if path == "" || !filepath.IsAbs(path) {
		return fmt.Errorf("%s に絶対パスを渡してください", name)
	}
	st, err := os.Stat(path)
	if err != nil || st.IsDir() {
		return fmt.Errorf("%s が実在するファイルではありません: %s", name, path)
	}
	return nil
}

// writeAtomic は、同じディレクトリの一時ファイルに書いてから名前を替える。途中で失敗しても、
// 元の HTML が半分だけ書かれた状態で残らないようにするため。
func writeAtomic(path string, data []byte) error {
	st, err := os.Stat(path)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".diffhtml-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmp.Name(), st.Mode().Perm()); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
