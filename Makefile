# このリポジトリのプラグインについて、手元の Claude Code へのインストール状況を表示し (plugins-status)、user スコープに
# インストールされていないものをインストールする (plugins-install)。
# 中身はスクリプト scripts/plugins.py が行う (表示するもの・前提の検査・インストール・中止と中断・終了コードは、そのファイルの docstring)。
#
# 変数 PLUGINS に、対象にするプラグインの名前をカンマで区切って指定できる。例: make plugins-status PLUGINS=doc-dag,wording-guard
# make のコマンドラインで指定したときだけ、スクリプトに渡す。同じ名前の環境変数では対象を絞らない
# (利用者が気づかないうちに対象が絞られないように)。空の値 (PLUGINS=) は、指定しないのと同じで、すべてを対象にする。
# GNU Make 3.81 (macOS に付属) で動く書き方にする。

# スクリプトのパスは、この Makefile の場所から求める。make -C や make -f で別のディレクトリから実行しても、
# この Makefile と同じリポジトリのスクリプトを実行する。
# make の関数は空白で語を分けるので、パスを abspath で絶対パスにしない。make と make -C では Makefile の場所が
# 相対パス (./) になり、レシピは make の作業ディレクトリで実行されるので、リポジトリのパスに空白があっても動く。
# 空白を含むパスの Makefile を -f で指定したときだけは、make がそのパスを語に分けるので、スクリプトを見つけられない。
# そのときは、別の手段で探さずに、理由と直し方を示して終了する。
# スクリプトの有無は、パスを単一引用符で囲んだシェルの test -f で確認する。make の $(wildcard) はパスの [ ] などを
# グロブのパターンとして扱うので、そのパターンに一致する別のパスがあると、スクリプトがあっても無いと判定するため
PLUGINS_SCRIPT := $(dir $(lastword $(MAKEFILE_LIST)))scripts/plugins.py
ifeq ($(shell test -f '$(subst ','\'',$(PLUGINS_SCRIPT))' && echo found),)
$(error この Makefile の場所から scripts/plugins.py を見つけられない。空白を含むパスの Makefile を make -f で指定すると、make がパスを空白で分けるため起きる。リポジトリのルートで make を実行するか、make -C <リポジトリのルート> を使う)
endif

# 値は、シェルの単一引用符で囲んで 1 つの引数として渡す (値の中の単一引用符は '\'' にする)
ifeq ($(origin PLUGINS),command line)
ifneq ($(strip $(PLUGINS)),)
PLUGINS_OPTION := --plugins='$(subst ','\'',$(strip $(PLUGINS)))'
endif
endif

.PHONY: plugins-status
plugins-status: ## このリポジトリのプラグインの、最新の版とインストール済みの版を表示する
	python3 '$(subst ','\'',$(PLUGINS_SCRIPT))' status $(PLUGINS_OPTION)

.PHONY: plugins-install
plugins-install: ## このリポジトリのプラグインのうち、user スコープにインストールされていないものを、配布元の main からインストールする
	python3 '$(subst ','\'',$(PLUGINS_SCRIPT))' install $(PLUGINS_OPTION)
