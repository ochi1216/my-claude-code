# CHANGELOG — excel_translation

## VERSION 20260817_01

### 追加・修正

**セルが複数行にわたる、またはセル自身が箇条書き番号(`1.` `2.` 等)を持つ場合に、翻訳結果が欠落・混線する不具合を修正**。ユーザーから実際に報告された事例で再現・修正した。報告されたセルの内容:

```
Prevent action: 
1. increase the design margin ( trim range) for critical parameters to cover posdel inaccurate.
2. Confirm with DBH for post-sim extracted data
Mitigation plan: accept real-si performance or modify in re-spin
```

このセルの翻訳結果が、内部の項目1つ分（`重要なパラメータの設計マージン（トリム範囲）を増やし、posdelの不正確さをカバーする。`）だけに切り詰められ、`Prevent action:` `Mitigation plan:` の行が消え、`Confirm with DBH...` の行も出力されないという症状だった。

**原因**: `translate_batch_parallel()`は、バッチ内の複数セルを1回のGemini呼び出しにまとめる際、セルの区切りとして単純な「連番＋ピリオド」(`f"{i}. {item}\n"`)を使い、応答も**1行ずつ**「`数字.`で始まる行＝新しい項目の境界」とみなす正規表現(`^(\d+)\.\s*(.+)`)で解析していた。このためセル自体が複数行の文章で、かつ内部に`1.` `2.`のような箇条書き番号を含む場合、その内部の番号がバッチの外側の項目番号と区別できず、(a) 同じバッチ内の別項目の訳文を上書きしてしまう、(b) 番号の付かない行(`Mitigation plan:`のような継続の文)は正規表現に一切マッチせずそのまま消失する、という2つの不具合が同時に起きていた。これは特定のセルに限った偶然ではなく、改行を含むセルや内部に番号付きリストを持つセル全般で再現する構造的な欠陥だった。

**対策**: バッチの区切りを、セルの中身に出現しうる「数字+ピリオド」ではなく、専用マーカー`<<<ITEM n>>>`に変更した。プロンプト・システム指示でも「マーカーから次のマーカーまでの全行(内部の番号・空行を含む)を1項目の完全な内容として扱う」ことを明示している。応答側の解析も、1行ごとの正規表現マッチから、**マーカー行を境界として次のマーカーまでの全行を1項目分としてまとめて蓄積する方式**に変更した(`_flush_current_item`)。これによりセル内部の番号や改行は単なる本文として扱われ、バッチの境界と混同されなくなる。マーカー行は念のためMarkdown太字(`**<<<ITEM 1>>>**`)で多少崩れても認識できるよう正規表現に許容を持たせてある。

応答が完全に得られなかった場合・想定外の形だった場合のフォールバック挙動(該当項目のみ原文を返す)は従来どおり維持している。

### 変更関数

- `translate_batch_parallel`（バッチ結合の区切り方式とプロンプト文面、応答解析ロジックを変更。Gemini呼び出し自体・レスポンス互換シムは`_20260812_01`から変更なし）

### 新規追加

- 定数 `_ITEM_MARKER_RE`（応答パース用の項目マーカー正規表現）
- 関数 `_flush_current_item`（`translate_batch_parallel`内のネスト関数。マーカー単位で蓄積した行を1項目分の訳文として確定する）
- テスト `tests/test_excel_translation_20260817_01.py`（今回報告された事例をそのまま再現するケースを含む）

### 削除

- なし

### 変更ファイル

- `excel_translation_20260817_01.py`（`excel_translation_20260812_01.py`からのコピー＋今回の変更。**`_20260812_01`はそのまま残置**。AST関数単位のハッシュ比較で、変更は`translate_batch_parallel`の1関数のみ、他の30定義(Excel処理・Gemini共通シム含む)はすべて完全一致であることを確認済み）
- `tests/test_excel_translation_20260817_01.py`（新規）

### 動作確認時の注意

**実機・実際のGemini APIでの検証はできていない**。本セッションの実行環境(Linuxコンテナ)からは実際のGemini APIにもプロキシにも到達できないため、以下は偽の`gemini_client`を注入するテストでのみ確認している。

- 報告されたセルと同じ構造(複数行＋内部に`1.` `2.`の箇条書き＋番号なしの行)を持つ入力を使い、**その項目の訳文が4行とも欠落なく1つの項目としてまとまって返ること**、**同じバッチ内の前後の単一行セルの訳文が巻き込まれて上書きされないこと**を確認
- マーカーが正しくプロンプトへ埋め込まれ、セル内部の番号がそのまま(改変されず)渡ること
- 空応答・マーカー無し応答・一部項目欠落・通信失敗の各ケースで、従来どおり原文へフォールバックすること
- Markdown太字で多少崩れたマーカーも認識できること

**実機でご確認いただきたい点**: 実際のセルを含むExcelファイルで翻訳を実行し、(1) 複数行・箇条書きを含むセルの内容が省略されずすべて翻訳されること、(2) 前後のセルの翻訳が入れ替わったり欠けたりしていないこと、を目視でご確認ください。あわせて、今回プロンプトの文面自体を変更しているため、**翻訳の文体・言い回しが`_20260812_01`までと若干変わる可能性があります**(内容の正確性・完全性を優先した変更のため、許容範囲と考えています)。

## VERSION 20260812_01

### 追加・修正

**Gemini APIへの直接アクセス遮断に伴い、共通クライアント(`gemini_client.py`)の自宅PCプロキシ自動フォールバック機構経由へ移行**。会社PCからGemini APIへの直接アクセスが遮断される事象(2026-08-10頃)を受け、先行して移行済みの`rtocs_organizer`・`analog_ic_se_strategy_organizer`・`outlook_total_organizer`と同じ方式に揃えた。全体設計は`gemini-common-tools`リポジトリの`GEMINI_MIGRATION_HANDOVER.md`、実装方針は`HANDOVER_onenote_gemini_proxy.md`(TYPE A引継ぎ資料)を参照。実装にあたり`gemini-common-tools`を実際にcloneし、`gemini_client.py`本体(`generate_advanced()`／`_call_proxy_advanced()`)を精読したうえでpayload形式を確定させている。

本ツールのGemini呼び出しは`translate_batch_parallel()`の1箇所だけだが、他ツールと実装・保守方法を揃えるため、同じ形の薄い互換シム(`_CommonGeminiClient`)を1つ用意し、そこを経由する方式にした。レスポンスを読む側のコード(`response.text`を行ベースで解析して番号付きリストへ戻す処理)は**一切変更していない**。

**移行に伴う挙動の変更(要確認)**: 認証情報は環境変数から読まれるようになった。会社PCで必要な環境変数は`GEMINI_API_KEY`(直接呼び出し用)と`GEMINI_PROXY_URL`(自宅PCプロキシ。直接呼び出し失敗時のフォールバック先)。`gemini_client.py`の置き場所を明示したい場合のみ`GEMINI_COMMON_DIR`も設定する。環境変数は`setx`で設定しただけでは現在のコマンドプロンプトに反映されないため、**設定後にコマンドプロンプトを開き直してから起動する**必要がある。

**設計提案書(PHASE1)から踏み込んで対応した点(3件)**。いずれも、提案書どおりに置換するだけでは動かない・機能が劣化することが実物のコードと共通モジュールを読んで判明したため対応した。

(1) **`system_instruction`をpayloadへ載せる処理をシムへ追加した**。旧版は`genai.GenerativeModel(system_instruction=...)`でSDKに渡していたが、共通モジュールはREST APIのpayloadをそのまま転送する方式のため、シムが`systemInstruction`フィールドを組み立てないと**「翻訳結果だけを出力せよ」という指示が silent に消える**(翻訳文に余計な前置きが混ざる等の劣化につながる)。参考にしたTYPE A(`outlook_total_organizer`)のシムは`system_instruction`を使っていなかったため、この処理は本ツール向けに追加した。`_system_instruction_to_jsonable()`で文字列を`{"parts": [{"text": ...}]}`形式へ変換している。

(2) **共通モジュールの探索パスを、1つ上だけでなく上位ディレクトリを順に探す方式にした**。TYPE Aのシムは`../common`固定だが、本ツールは会社PCで`PythonScripts\excel\excel_transrate\`に置かれ、`gemini_client.py`は`PythonScripts\common\`にあるため、**1つ上(`PythonScripts\excel\common`)では見つからず、正解は2つ上**になる。`GEMINI_COMMON_DIR`未設定時は1つ上→2つ上→3つ上の順に`gemini_client.py`の実在を確認し、最初に見つかったものを使う(他ツールと同じ配置に置かれた場合もそのまま動く)。

(3) **設計提案書が前提としていた`from google.genai import types`は、本ツールには存在しなかった**。本ツールが使っていたのは新SDK(`google.genai`)ではなく**旧SDK(`google.generativeai`)の`genai.GenerativeModel`**であり、`types.GenerateContentConfig`は元々使っていない。移行のために`google.genai`を新たにimportすると**未導入の会社PCで起動できなくなる**新規依存が増えるため、同等の入れ物`_GeminiGenerateConfig`をスクリプト内に定義した。シム側は`getattr`で属性を読むだけなので、将来`types.GenerateContentConfig`を渡すようにしてもそのまま動く。

**旧SDK(`google-generativeai`)への依存が無くなった**。`genai.configure(api_key=..., transport='rest')`(gRPC遮断回避のためのREST強制)も、共通モジュールが`requests`でREST呼び出しを行うため不要になり削除した。起動時の依存関係チェックも、`google-generativeai`の有無ではなく**共通モジュールを読み込めたかどうか**を見るように変更している。

**AI応答が空だったときに警告を出すようにした**(1行追加)。従来は空応答でも黙って原文がそのまま出力されるため、翻訳されていないことに気づけなかった。移行後の切り分け(プロキシ経由で応答が返っているか)を実機で判断しやすくするために追加した。

### 変更関数

- `check_dependencies`（`google-generativeai`の有無チェックを廃止し、共通モジュール`gemini_client.py`を読み込めたかどうかのチェックへ変更。読み込めない場合は「探索したパス」「元のエラー」「`GEMINI_COMMON_DIR`で指定できること」を含むメッセージを表示する）
- `translate_batch_parallel`（`genai.GenerativeModel(...).generate_content(prompt)`を`_CommonGeminiClient().models.generate_content(model=..., contents=..., config=...)`へ置換。`model`は`"gemini-2.5-flash"`を明示的に渡す。応答が空のときの警告出力を追加。レスポンス解析・原文フォールバックのロジックは従来どおり）
- `translate_excel_parallel`（Gemini利用不可時のエラーメッセージを、原因の分かる共通モジュールの案内へ変更）
- `check_api_key`（`GEMINI_API_KEY`必須の判定から`gemini_credentials_available()`ベースへ変更。**この修正を入れないと、プロキシ専用構成のときに起動直後に強制終了する**）

### 新規追加

- 定数 `_COMMON_DIR` / `_COMMON_DIR_CANDIDATES`（`GEMINI_COMMON_DIR`、未設定時は上位ディレクトリを順に探索）
- 変数 `_generate_advanced` / `_GEMINI_CLIENT_IMPORT_ERROR`（共通モジュールの`try/except`インポート結果）
- クラス `_CommonGeminiClient` / `_CommonGeminiModels` / `_CommonGeminiResponse` / `_CommonUsageMetadata`（`genai.Client`互換シム）
- クラス `_GeminiGenerateConfig`（`types.GenerateContentConfig`相当。`google.genai`への新規依存を避けるためスクリプト内に定義）
- 関数 `_gemini_common_module_error_message`（共通モジュール未配置時の案内文）
- 関数 `_system_instruction_to_jsonable`（`system_instruction`をREST APIの`systemInstruction`形式へ変換）
- 関数 `_schema_to_jsonable`（`response_schema`がpydanticモデルへ自動変換された場合の保険。本ツールは`response_schema`未使用のため通常は出番がないが、他ツールのシムと契約を揃えるため残置）
- 関数 `gemini_credentials_available`（`GEMINI_API_KEY`／`GEMINI_PROXY_URL`のどちらか一方でもあれば通す）
- テスト `tests/test_excel_translation_20260812_01.py`

### 削除

- `import google.generativeai as genai`（旧SDKへの依存を廃止）
- `genai.configure(api_key=api_key, transport='rest')`（認証・通信方式は共通モジュールが担うため不要）

### 変更ファイル

- `excel_translation_20260812_01.py`（`excel_translation_20260616_03.py`からのコピー＋今回の変更。**旧版`_20260616_03`はそのまま残置**）
- `CHANGELOG.md` / `README.md` / `requirements.txt` / `tests/test_excel_translation_20260812_01.py`（新規）

### 動作確認時の注意

**実機検証はできていない**。本セッションの実行環境(Linuxコンテナ)からは、会社PCの共通モジュールにも自宅PCプロキシにも到達できないため、**実際にプロキシ経由でGeminiから翻訳結果が返るところは未確認**。特に、今回追加した`systemInstruction`フィールドを自宅PC側の`/generate`エンドポイントがそのままGeminiへ転送するかは未検証(仮に脱落しても、プロンプト本文に同等の指示があるため翻訳自体は成立する)。実施済みの確認は以下のとおり。

- `ast.parse`による構文チェック
- 旧版との`diff`が7ハンク・意図した変更箇所のみであることの確認
- 関数単位のハッシュ比較（AST抽出）で、**Excel処理側の17定義(`get_merged_cell_info`／`parse_excel_range`／`validate_range`／`is_translatable`／`copy_cell_format`／`preserve_data_type`／`_translate_sheet_content`／`select_file`／`SimpleProgressWindow`ほか)が旧版と完全一致**＝今回の移行で触っていないことを確認。変更は4関数、削除は0件
- 偽の`gemini_client`を`sys.modules`へ注入する方式(引継ぎ資料 第7章)のテスト**40項目**を実行し全て合格。検証内容: payload形状／`model`が`gemini-2.5-flash`で明示的に渡ること／`temperature: 0`が`generationConfig`へcamelCaseで載ること／`systemInstruction`がREST形式で載ること／`response.text`・`response.usage_metadata`が読めること／payloadが`json.dumps`可能なこと／空・壊れたレスポンス4パターンで例外を投げないこと／空応答・番号無し応答・欠番時に原文へフォールバックすること／通信失敗時も例外を投げず原文を返すこと／認証情報判定4パターン(プロキシ専用構成を弾かないこと含む)／共通モジュール未配置時に探索パスと`GEMINI_COMMON_DIR`の案内を含むエラーが出ること
- 共通モジュールの探索パスを、会社PC想定(2つ上が`common`)・他ツール想定(1つ上が`common`)・`GEMINI_COMMON_DIR`明示指定の3レイアウトで実際にディレクトリを作って確認

**実機(会社PC)でのご確認をお願いしたい点**

1. `GEMINI_API_KEY`／`GEMINI_PROXY_URL`を設定し、**コマンドプロンプトを開き直してから**起動すること
2. 起動時に「Gemini認証情報が設定されていません」「共通モジュールを読み込めませんでした」のダイアログが出ないこと（出た場合はメッセージ内の「探索したパス」を確認し、必要なら`GEMINI_COMMON_DIR`を設定）
3. 実際にExcelを翻訳し、コンソールに`[gemini_client] 直接呼び出し失敗（...）→ ... プロキシに固定します`が出たうえで**翻訳結果が返ること**
4. 翻訳結果に「はい、承知しました」等の余計な前置きが混ざっていないこと（混ざっている場合は`systemInstruction`がプロキシ側で脱落している可能性がある）
5. 「バッチ N 警告: 応答が空でした」が頻発しないこと
6. 書式・結合セル・列幅・`.xlsm`のVBA保持が従来どおりであること（Excel処理側は未変更のため影響しない想定）

**未実施(今回スコープ外)**: TYPE Aで実装した「直接接続の復活お知らせ」機能は、3ツールすべてに入れると同じ日に複数回ポップアップが出るため、引継ぎ資料 第10章のとおり集約方針が未確定。本ツールには入れていない。
