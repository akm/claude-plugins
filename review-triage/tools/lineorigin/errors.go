package main

import (
	"errors"
	"fmt"
	"io"
)

// 結果を出せないときのエラーは 2 種類で、標準エラー出力の最初の行に付ける印で見分ける。
// 終了コードでも分けるが、go run で実行すると、道具の終了コードが 0 でなければ go run は
// 1 を返すので、終了コードでは見分けられない。
const (
	inputErrorLabel = "input-error:"
	runErrorLabel   = "run-error:"
	exitInputError  = 2
	exitRunError    = 3
)

// inputError は入力の誤り。渡したもの (フラグ・版・ファイル・行) を直せば実行し直せる。
type inputError struct{ msg string }

func (e *inputError) Error() string { return e.msg }

// runError は、道具を実行できないこと。git を起動できない・git が古い・git の出力を読めない、など。
// 渡したものを直しても結果は出ない。
type runError struct{ msg string }

func (e *runError) Error() string { return e.msg }

func inputf(format string, a ...any) error { return &inputError{msg: fmt.Sprintf(format, a...)} }

func runf(format string, a ...any) error { return &runError{msg: fmt.Sprintf(format, a...)} }

// asRun は、err を道具を実行できないことにする。渡したものでは説明できない git の失敗に使い、
// git の標準エラー出力を含む元の文言を残す。
func asRun(err error) error {
	var re *runError
	if errors.As(err, &re) {
		return err
	}
	return runf("%v", err)
}

// report は err を印を付けて w に書き、終了コードを返す。どちらの種類でもないエラーは
// 道具の側の想定外なので、道具を実行できないことにする。
func report(w io.Writer, err error) int {
	var ie *inputError
	if errors.As(err, &ie) {
		fmt.Fprintln(w, inputErrorLabel, ie.msg)
		return exitInputError
	}
	fmt.Fprintln(w, runErrorLabel, err.Error())
	return exitRunError
}
