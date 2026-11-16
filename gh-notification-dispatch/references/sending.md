# メッセージの送り方

配信のセッションが、受信のセッションへメッセージを送るときの手順 (計画 [docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md](../../docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md) の R15・KTD2)。スキル `tick` と `dispatch` が使う。

使うもの:

- 宛先の名前と ID: スクリプトの出力の、宛先の名前 (`tick` の `messages[].to` など) と ID (`to_session_id`)。返事を送るときは、受け取ったメッセージの属性 `from-name` と送り手の ID
- 本文: スクリプトの出力の本文 (`body` など)。書き換えずに送る

宛先は名前にする。ID を宛先にしたメッセージは、送る側のセッションで利用者が最後に入力してから送れる数に上限があるという記録 (#114) があるので、ふだんの宛先にはしない。

## 手順

1. ツール `SendMessage` で、`to` を宛先の名前、`message` を本文にして送る。結果が `success:true` なら、届いた。
2. `success:false` なら、ツール `get_session` に、`session_id` として宛先の ID を渡し、結果の `title` を今の名前とする。ツールが読み込まれていなければ、ツール `ToolSearch` で `select:mcp__ccd_session_mgmt__get_session` を読み込む。手順 1 の結果の文が別のセッションの名前を示していても (`Did you mean: …` など)、その名前には送らない。別のセッションへ届いてしまうため。
   - 今の名前が宛先の名前と違えば、`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gh_notification_dispatch.py" subscriptions rename --session-id <ID> --name <今の名前>` を実行してから、今の名前を宛先にして送り直す。`success:true` なら、届いた。
3. まだ届いていなければ (送り直しが `success:false`・`get_session` がセッションを見つけない・名前が同じ)、ID (`local_…`) を宛先にして送り直す。Claude Desktop を再起動した後に利用者が開いていないセッションは、名前では届かないが、ID なら Claude Desktop がそのセッションを起動して届ける (計画の U1)。`success:true` なら、届いた。
4. それでも `success:false` なら、届かなかった。最後の結果の文を、届かなかった理由にする。

名前の引き直しにツール `list_sessions` を使わないのは、2026-11-16 の確認で、引数 `limit` が 100 の結果が 51,039 文字になり、ツールの出力の上限を超えたため (結果はファイルに保存され、宛先の行を探しにくい)。
