package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

// gitRunner は、-root のリポジトリで git を実行する。
type gitRunner struct {
	root string
}

// gitTimeout は、git の 1 回の実行に許す時間。git が応答しなくなったときに、ツールが終了しなくなるのを防ぐ。
var gitTimeout = 5 * time.Minute

// show は、コミットの差分 (コミットメッセージを除く) を返す。利用者の git の設定 (diff.external・
// color.ui・diff.noprefix・textconv の設定) で出力の形が変わらないオプションを付ける。設定 core.fsmonitor は
// 打ち消す。打ち消さないと、git がそこに登録したプログラムを起動することがある。
func (g gitRunner) show(sha string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), gitTimeout)
	defer cancel()
	args := []string{"-C", g.root, "-c", "core.fsmonitor=false",
		"show", "--format=", "--no-ext-diff", "--no-color", "--no-textconv",
		"--src-prefix=a/", "--dst-prefix=b/", sha, "--"}
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.WaitDelay = time.Second
	cmd.Env = gitEnv()
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return "", fmt.Errorf("git show %s が %s 以内に終了しませんでした", sha, gitTimeout)
	}
	if err != nil {
		return "", fmt.Errorf("コミット %s の差分を取れません (git show が失敗しました): %s", sha, strings.TrimSpace(stderr.String()))
	}
	return stdout.String(), nil
}

// extraGitEnv は、gitEnv が GIT_ で始まる変数を取り除いた後に足す変数。本番では空で、
// テストがシステムの git の設定を読ませないために使う (取り除く前に設定しても届かないため)。
var extraGitEnv []string

// gitEnv は git に渡す環境を作る。利用者の環境の GIT_ で始まる変数は、リポジトリの場所を替える
// (GIT_DIR・GIT_WORK_TREE など) か、設定を注入する (GIT_CONFIG_PARAMETERS など) ので、-root と違う
// リポジトリや設定を読ませないよう、すべて取り除いてから要るものだけを足す。
func gitEnv() []string {
	var env []string
	for _, kv := range os.Environ() {
		if !strings.HasPrefix(kv, "GIT_") {
			env = append(env, kv)
		}
	}
	env = append(env,
		// コマンド git replace の置き換えを見ない。見ると、記録の SHA と違う内容の差分を出しうる
		"GIT_NO_REPLACE_OBJECTS=1",
		// 認証などで利用者の入力待ちにならない
		"GIT_TERMINAL_PROMPT=0",
	)
	return append(env, extraGitEnv...)
}
