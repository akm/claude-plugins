# このリポジトリのプラグインについて、手元の Claude Code へのインストール状況を表示する。
# 中身はスクリプト scripts/plugins.py が行う (表示するもの・前提の検査・終了コードは、そのファイルの docstring)。
#
# 変数 PLUGINS に、対象にするプラグインの名前をカンマで区切って指定できる。例: make plugins-status PLUGINS=doc-dag,wording-guard
# make のコマンドラインで指定したときだけ、スクリプトに渡す。同じ名前の環境変数では対象を絞らない
# (利用者が気づかないうちに対象が絞られないように)。空の値 (PLUGINS=) は、指定しないのと同じで、すべてを対象にする。
# GNU Make 3.81 (macOS に付属) で動く書き方にする。

# スクリプトのパスは、この Makefile の場所から求める。make -C や make -f で別のディレクトリから実行しても、
# この Makefile と同じリポジトリのスクリプトを実行する
PLUGINS_SCRIPT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))scripts/plugins.py)

# 値は、シェルの単一引用符で囲んで 1 つの引数として渡す (値の中の単一引用符は '\'' にする)
ifeq ($(origin PLUGINS),command line)
ifneq ($(strip $(PLUGINS)),)
PLUGINS_OPTION := --plugins='$(subst ','\'',$(strip $(PLUGINS)))'
endif
endif

.PHONY: plugins-status
plugins-status: ## このリポジトリのプラグインの、最新の版とインストール済みの版を表示する
	python3 $(PLUGINS_SCRIPT) status $(PLUGINS_OPTION)
