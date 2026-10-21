---
name: clord-dispatch
description: "C-lordへ発注・追加指示・状態確認するときに使う。宛先とrepoを分離し、起動確認と重複防止を行う。"
license: MIT
---

# C-lord dispatch

1. **依頼と宛先を確定する。** C-lordはDiscordからClaude Codeを動かす仕組み。新規発注、既存担当への指示、状態確認のどれかに分ける。依頼元の会話ID/URL、対象repo、作業範囲、公開/変更の承認範囲を記録する。CLIは `python3 {baseDir}/scripts/dispatch.py`。`routes` で設定済みの親チャンネルを選び、案件の異なるチャンネルへフォールバックしない。完了条件: 依頼元・宛先・repoが特定できている。
2. **既存担当を探す。** 依頼元の会話、直近の発注記録、既知の作業スレッドを確認する。`receipt --key <operation-key>` で同じ仕事の記録があれば再利用する。記録はこのCLIによる発注だけを含むため、記録なしを「既存担当なし」と扱わない。不明な対象repo/宛先だけ絞って確認する。完了条件: 新規が必要か既存を使うか説明できる。
3. **本文をファイルにする。** 背景、必要な成果、確認方法、触らない対象、止めて相談する条件を含める。本文に `!clord` や `repo:` を手で付けない。repoは `--repo` に独立した引数で渡す。私的な会話全文、認証情報、無関係な案件情報は含めない。新規発注は要約も用意する。完了条件: 無害な形で2000 UTF-16 code units以内に収まる。
4. **新規発注する。** 設定と例は [setup.md](references/setup.md)。同じ仕事に安定した `--key` を使い、まず次の形式で `--dry-run` を付けて入力を確認し、実送信時だけ外す。

   ```sh
   python3 {baseDir}/scripts/dispatch.py new --route ROUTE --repo https://github.com/OWNER/REPO --key TASK_KEY --file /absolute/path/order.md --summary '一行の発注要約' --origin '依頼元URL' --dry-run
   ```

   dry-runはネットワーク確認ではない。実送信では設定された親チャンネルと既存webhookを確認する。`duplicate_blocked` が出たら既存receiptを読む。`sending` や `sent_unconfirmed` は成功でも未送信でもないため、新しいkeyを発行して送り直さない。`observe --route ROUTE --key TASK_KEY --wait 20` で既存発注を再確認する。完了条件: 自分のDispatch-IDを持つスレッドとC-lordの実行開始を観測する。誤送信/clone失敗/未確認ならその状態で報告する。
5. **既存スレッドへの追加は保留を既定にする。** `status --route ROUTE --thread THREAD_ID` は読取のみ。状態unknownはidleではない。Discord上のスレッドの存在はC-lordのセッション生存の証明ではない。配備環境の対応手段で生存確認できないなら送らず保留する。`followup --route ROUTE --thread THREAD_ID --key FOLLOWUP_KEY --file /absolute/path/body.md --origin '依頼元URL'` は既定で送信せず保留する。稼働中への送信は文面に関係なく割り込みを起こし得る。ユーザーがその割り込みを明示承認したとき、または生存が確認済みで担当から求められた質問に回答するときだけ `--interrupt-approved` を付ける。任意の補足はローカルファイルに保留し、後で送ると約束するなら再開手段も設定する。この版に自動キューはない。完了条件: 不要な中断を発生させず、送信/保留を区別する。
6. **着地を確認し、依頼元へ返す。** `state=started` は成果物完成ではない。担当スレッドを読み、指定された成果物・公開URL・PR/CI・実行結果を照合する。作業が続くなら利用可能な永続的監視を設定し、宛先と再開条件を記録する。報告はOpenClawの通常返信またはmessageツールで依頼元に出し、DMや他案件に出さない。完了条件: 要件ごとの観測結果か、未完了の理由・担当・次の確認条件が依頼元に伝わる。

## 適用範囲

Python 3.10+、Unix系ホスト、Discord text channelの既存incoming webhook、読取/既存webhook取得権限を持つC-lord Botトークンを想定。GitHub repo URLのみ対応。送信前に対象チャンネルでC-lordが初期化されている必要がある。既存の案件専用ラッパを無断で置換しない。

## 試験状態

初版は未テスト。作者が「テスト前まで」と指定している間は、モデル比較・単体テスト・実地発注を実行しない。試験仕様はリポジトリの `docs/acceptance.md`。組み込みと実地検証を混同しない。
