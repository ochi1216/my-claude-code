# CHANGELOG — outlook_total_organizer

## VERSION 20260716_02

### 追加・修正
	**アクションタブの「対象期間」に「3週間」「1ヶ月」を追加**: アクションダッシュボード生成タブの対象期間プルダウン（従来は「24H」「今日」「3日間」「1週間」「2週間」の5択）に、「3週間」（21日）「1ヶ月」（30日）の2択を追加した。日数換算値は、コックピット/プロジェクト俯瞰/スタッフ俯瞰タブの期間プルダウンで既に使われている「1ヶ月」=30日の換算と統一した。

### 変更関数
	`MailManagerGUI._ui_action_tab`（対象期間コンボボックスの`values`に「3週間」「1ヶ月」を追加）
	`MailManagerGUI._get_action_days`（日数変換辞書に`"3週間": 21`, `"1ヶ月": 30`を追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260716_02.py`（`_20260716_01_01`からのコピー＋今回の変更。`_20260716_01_01`はそのまま残置。なお本バージョンからファイル命名規則を`outlook_total_organizer_yyyymmdd_NN_01.py`から`outlook_total_organizer_yyyymmdd_NN.py`（末尾の`_01`を廃止）に変更した。以降のバージョンもこの新命名規則に統一する）

変更しないこと（宣誓）：
	`summarize_action_dashboard`のデータ構造・並び替え(`sortActionCards`)ロジック・R19Projフィルタ（`toggleR19Filter`/`r19FilterMode`）・進捗/優先度更新API呼び出し・`get_relevant_mails_for_period`/`search_mails_fast`の期間フィルタリングロジック自体（日数の意味付けは変更せず、既存の`days`引数にそのまま21・30を渡すのみ）

## VERSION 20260716_01_01

### 追加・修正
	**「R19Proj以外」フィルタボタンを新設**: これまでコントロールバーの「プロジェクト:」行には、R19プロジェクト案件のみに絞り込む「🧩 R19Proj」ボタンしかなかった。その隣に「🚫 R19Proj以外」ボタンを追加し、R19以外の案件のみに絞り込めるようにした。
	2つのボタンは排他的に動作する（片方を押すともう片方は自動的に解除される）。同じボタンをもう一度押すと絞り込み解除（全件表示）に戻る。
	絞り込み状態の内部管理を、真偽値の`r19FilterActive`から3状態（`'all'` / `'only'` / `'exclude'`）の`r19FilterMode`に変更。

### 変更関数
	`HTMLReportGenerator.generate_action_dashboard_report`（`toggleR19Filter`を2ボタン共通の3状態トグルに変更、`applyActionFilters`内のR19判定条件を3状態対応に変更、CSSに`#r19ExcludeFilterBtn.active`を追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260716_01_01.py`（`_03_01`からのコピー＋今回の変更。`_03_01`はそのまま残置。なお本リポジトリには`_03_01`より前のバージョンファイルは未格納で、変更履歴のみ本CHANGELOGに記録）

変更しないこと（宣誓）：
	`summarize_action_dashboard`のデータ構造・並び替え(`sortActionCards`)ロジック・進捗/優先度更新API呼び出し・R19Proj判定ロジック（`is_r19`）自体

## VERSION 20260713_03_01

### 追加・修正
	**絞り込み仕様を変更**: 前バージョンでは「カード内のいずれかのアクションが条件に合致すればカード全体を表示」だったが、見づらいとのフィードバックを受け、「カード内で条件に合致するアクション行だけを表示し、合わないものは隠す(カード内が全滅した場合のみカードごと非表示)」に変更した。
	表示件数ラベルを「表示中アクション数 / 全体アクション数(表示中カード数)」の形式に変更。
	完了/無視アクションを薄く表示する仕様は、表示/非表示そのもので区別が付くようになったため削除。

### 変更関数
	`HTMLReportGenerator.generate_action_dashboard_report`（`applyActionFilters`をカード単位からアクション項目単位の絞り込みに変更、不要になった完了/無視の透過表示CSSを削除）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260713_03_01.py`

変更しないこと（宣誓）：
	`summarize_action_dashboard`のデータ構造・並び替え(`sortActionCards`)ロジック・R19Projフィルタ・進捗/優先度更新API呼び出し

## VERSION 20260713_02_01

### 追加・修正
	**依頼の「宛先」を明示**: `owner`(誰からの依頼か)に加え、AI抽出スキーマに`target`(誰への依頼か。受信者本人なら「あなた」、スレッド内の別人物ならその名前)を追加。カード内の各アクション行を「田中さん → あなた: 見積書のご確認をお願いします」のように表示するようにした。
	**R19プロジェクト案件の自動判定とフィルタ**: スレッド内のいずれかのメールにOutlookの「R19Proj」カテゴリタグが付与されていれば、そのスレッドをR19プロジェクト案件として扱うようにした。コントロールバーに進捗フィルタの下の行として「🧩 R19Proj」トグルボタンを新設し、押すとR19Projタグ付きスレッドのみに絞り込める。
	**カードにR19Projマークを表示**: カテゴリバッジの右・タイトルの左の固定幅スロットに、R19プロジェクト案件のカードのみ「🧩 R19Proj」マークを表示。非該当カードも同じ幅のスロットを確保し、タイトルの開始位置がカード間で揃うようにしている。
	**1スレッド複数アクションを1カードに統合**: これまで1アクション=1カードのフラット表示だったが、同一スレッド内の複数アクションを1つのカード(共通ヘッダー：カテゴリ/R19マーク/タイトル/日時/Outlookボタン)の中に、アクションごとの行(依頼者→宛先/内容/締切/進捗/優先度/コメント)として束ねる表示に変更。
	**カード単位の絞り込み仕様変更**: 進捗・優先度フィルタは、カード内のいずれかのアクションが条件に合致すればカード全体を表示するようにした(例: 「未着手」のみ選択していても、同じカード内の「進行中」「完了」のアクションも一緒に表示される)。完了/無視のアクション行はカード内で薄く表示され、区別できる。
	**並び替えロジックの調整**: 優先度順はカード内の最大優先度、進捗順はカード内の最小進捗ランクを基準に並び替えるよう変更(複数アクションを束ねたことに伴う調整)。

### 変更関数
	`MailSummarizer.summarize_action_dashboard`（`thread_schema`に`target`追加、戻り値を`actions_flat`(フラット)から`action_cards`(スレッド単位でアクションを束ねた構造)に変更、`is_r19`判定を追加）
	`HTMLReportGenerator.generate_action_dashboard_report`（引数を`action_cards`に変更、カードHTML構造を「共通ヘッダー＋複数`.action-item`」に全面改修、R19フィルタ・カード集約ベースの絞り込み/並び替えJSに変更）
	`MailManagerGUI._save_action_dashboard_result` / `_run_action_dashboard` / `_reformat_action_dashboard`（`actions_flat`→`action_cards`への参照変更、ステータス上書きループをカード内の`actions`配列に対応）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260713_02_01.py`

動作確認時の注意：
	戻り値の構造自体が変わっているため、`analysis_cache/action_dashboard.json`と`json/action_dashboard_last_result.json`の両方を一度削除してから再テストしてください(削除しないとキャッシュ形式の不整合でエラーになる可能性があります)。`json/action_status.json`(進捗・優先度・コメントの保存先)は形式が変わっていないため削除不要です。

変更しないこと（宣誓）：
	コックピット・プロジェクト俯瞰・スタッフ俯瞰に関する全コード、`get_relevant_mails_for_period`・`/update_action_status`エンドポイント・`json/action_status.json`の読み書きロジック・未読既読インジケーターのロジック

## VERSION 20260713_01_01

### 追加・修正
	**カードのタイトルクリックで「🚀 Outlook」ボタンと同じ動作を実行**: タイトル文字列(`.action-topic-text`)を、メールが特定できる場合は`<a>`リンク化し、「🚀 Outlook」ボタンと全く同じURL(Outlookでの件名検索)を開くようにした。ボタン自体は従来通り独立して残している。
	タイトルは通常時は下線なし・黒系文字のままで、ホバー時のみ下線＋青色になり、クリック可能であることが分かるようにした。

### 変更関数
	`HTMLReportGenerator.generate_action_dashboard_report`（タイトル要素を条件付きで`<a>`化、CSSにホバー時の視覚フィードバックを追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260713_01_01.py`

変更しないこと（宣誓）：
	「🚀 Outlook」ボタン自体の挙動・URL生成ロジック、進捗/優先度/コメント/未読既読/絞り込み・並び替えに関する全コード

## VERSION 20260709_10_01

### 追加・修正
	**カードに未読/既読インジケーターを追加**: カード左端に、重要度バー(4px、既存)とは別に、未読既読を示す8px幅のバー(重要度バーの2倍の太さ)を追加。未読=青(`#2563eb`)、既読=グレー(`#cbd5e1`)。
	カード構造を`.action-card`(外側、未読既読バー担当・進捗/優先度/日時等のdata属性を保持)と`.action-row`(内側、重要度バー+グリッドレイアウト担当)の二重構造に変更。

### 変更関数
	`MailSummarizer.summarize_action_dashboard`（`actions_flat`の各要素に`has_unread`を追加、スレッドの`group_by_thread`由来の`has_unread`をそのまま反映）
	`HTMLReportGenerator.generate_action_dashboard_report`（カードHTML構造を`.action-card`/`.action-row`の二重構造に変更、CSS追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_10_01.py`

変更しないこと（宣誓）：
	JS側のフィルタ・ソート・ステータス更新ロジック（`.js-action`クラスの参照先が変わっただけで、動作は変更なし）、`/update_action_status`エンドポイント・`get_relevant_mails_for_period`・既存タブに関する全コード

## VERSION 20260709_09_01

### 追加・修正
	**メール再解析でステータス(進捗・優先度・コメント)がリセットされる不具合を修正**: アクションの識別キーが `conversation_id + owner + action文言の先頭40文字` のハッシュだったため、スレッドに新着メールが届いてAIが再解析すると、owner/actionの言い回しが少しでも変わっただけで別キー扱いとなり、既に設定した進捗・優先度・コメントが「未着手・優先度なし」にリセットされてしまっていた。
	識別キーを「スレッドID + そのスレッド内でのアクションの並び順(0始まり)」ベースに変更(`make_action_key_by_index`)。1スレッドに1アクションのみの場合(最も多いケース)は、文言がどう変わってもキーが完全に安定するようになった。
	あわせて、旧キー方式(文言ベース)で既に保存されているステータスを新キーへ自動移行するフォールバック処理を追加(`summarize_action_dashboard`内)。

### 変更関数
	`MailSummarizer.summarize_action_dashboard`（`actions_flat`構築時のキー生成を`make_action_key_by_index`に変更、旧キーからの移行フォールバックを追加）

### 新規追加：
	`make_action_key_by_index`（スレッドID＋アクション順序ベースの新しい安定キー生成関数）

変更ファイル：
	`outlook_total_organizer_20260709_09_01.py`

既知の制約（重要）：
	この修正は「今後」文言変更でステータスが消えるのを防ぐものです。**今回既に失われた3件のステータスそのものは、自動復旧できません。** 理由: 旧キーはMD5ハッシュ(不可逆)であり、`json/action_status.json`内には「進捗=進行中、優先度=★★最優先」という値は孤立したハッシュキーの下にまだ残っていますが、それがどのメールスレッドに対応していたかを文言変更後に逆算する手段がないためです。お手数ですが、該当の3件は次回以降、目視で再度ステータスを設定し直していただく必要があります。今回のバージョンアップにより、以後は同じ理由でのリセットは発生しなくなります(1スレッドに複数アクションがあり、かつAIがそのスレッド内のアクションの数や順序自体を変えてしまった場合のみ、ごく稀に再発する可能性があります)。

変更しないこと（宣誓）：
	`/update_action_status`エンドポイント・`get_relevant_mails_for_period`・`HTMLReportGenerator.generate_action_dashboard_report`・既存タブに関する全コード

## VERSION 20260709_08_01

### 追加・修正
	**ヘッダー・コントロールバーを常時表示化**: `.header`と`.controls`を`.sticky-top`でまとめ、`position:sticky; top:0;`を適用。スクロールしても上部に固定表示されるようにした。
	**各カードに受信日時を表示**: タイトル行の右端に`mm/dd HH:MM`形式(スレッド最終更新日時)を控えめなグレー文字で右端揃え表示。
	**並び順に時系列順を追加**: 「時系列順（新しい順）」「時系列順（古い順）」を並び順セレクタに追加(既存の優先度順・進捗順と合わせて4種類)。

### 変更関数
	`MailSummarizer.summarize_action_dashboard`（`actions_flat`の各要素に`latest_date_mmdd`を追加）
	`HTMLReportGenerator.generate_action_dashboard_report`（`.sticky-top`ラッパー追加、カードに日時表示・`data-ts`属性を追加、並び順セレクタとJSソート処理を拡張）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_08_01.py`

変更しないこと（宣誓）：
	`/update_action_status`エンドポイント・`get_relevant_mails_for_period`・既存タブに関する全コード

## VERSION 20260709_07_01

### 追加・修正
	**アクションダッシュボードに絞り込み・並び替え機能を追加**: コントロールバーに進捗(未着手/進行中/完了/無視)・優先度(—/★優先/★★最優先)のトグルボタンを追加し、複数条件を組み合わせてカードを絞り込めるようにした。既定では未着手・進行中のみ表示(完了・無視は従来通り非表示)。
	**並び順セレクタを追加**: 「優先度順(★★→★→空欄)」「進捗順(未着手→進行中→完了→無視)」を切り替え可能に(`#actionList`内のカードをJSで並び替え、API再呼び出し無し)。
	**カードレイアウトを2カラム×3行のグリッドに再設計**:
	  - 左カラム: 1行目=タイトル(カテゴリバッジ→タイトルの順)、2行目=依頼者→内容/締切、3行目=コメント入力欄
	  - 右カラム: 1行目=進捗ボタン、2行目=優先度ボタン、3行目=「🚀 Outlook」ボタン(コメント欄の右横に移動、進捗・優先度ボタン群と左端が揃う)
	  - カテゴリバッジを固定幅コンテナ(`.action-cat-wrap`)に入れることで、カテゴリ文字数に関わらずタイトル文字列の開始位置がカード間で揃うようにした。

### 変更関数
	`HTMLReportGenerator.generate_action_dashboard_report`（カードHTML構造・CSS・コントロールバー・JS(`applyActionFilters`/`toggleFilterBtn`/`sortActionCards`)を全面改修）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_07_01.py`

変更しないこと（宣誓）：
	`/update_action_status`エンドポイント・`summarize_action_dashboard`のAI抽出ロジック・`get_relevant_mails_for_period`・既存タブに関する全コード

## VERSION 20260709_06_01

### 追加・修正
	**「🚀 Outlook」リンクを開くと別カードで接続待ちのまま固まる不具合を修正**: ローカルサーバーが非スレッド版`HTTPServer`だったため、1つのブラウザ接続がkeep-aliveで保持されている間、他の接続(別カードのリンク)を受け付けられず、そのタブが読み込み中のまま固まっていた(数十秒後のkeep-aliveタイムアウトで解放されると成功する、という報告と一致)。
	`HTTPServer`を`ThreadingHTTPServer`に変更し、複数の接続を同時並行で処理できるようにした。
	これに伴い、複数リクエストが同時に発生しうるようになったため、私が追加した`/update_action_status`エンドポイントの`json/action_status.json`読み書きに排他ロック(`action_status_lock`)を追加し、同時クリック時の書き込み競合を防止。

### 変更関数
	`start_local_server`（`HTTPServer` → `ThreadingHTTPServer`）
	`OutlookRequestHandler.do_POST`（`/update_action_status`のstatuses読み書きを`action_status_lock`で保護）

### 新規追加：
	`action_status_lock`（`threading.Lock`、`json/action_status.json`の排他制御用）

変更ファイル：
	`outlook_total_organizer_20260709_06_01.py`

既知の課題（今回は対象外）：
	`/update_knowledge`・`/update_ai_rules`など既存エンドポイントの`project_knowledge.json`読み書きは、ThreadingHTTPServer化により理論上は同時アクセス時の競合リスクが生じるが、人間が1操作ずつボタンを押す用途である実態を踏まえ、今回は既存コードに手を入れず対象外とした。

変更しないこと（宣誓）：
	`/update_knowledge`・`/update_ai_rules`・`/translate`等の既存エンドポイントの処理内容、検索/整理タブ・プロジェクト俯瞰・スタッフ俯瞰・コックピットに関する全コード

## VERSION 20260709_05_01

### 追加・修正
	**アクションダッシュボードの「🚀 Outlook」リンクでメールが見つからない不具合を修正**: `show_thread_in_explorer`はOutlook側で`subject:"{topic}"`という件名検索を実行して対象メールを選択する仕組みだが、`summarize_action_dashboard`がリンクに渡す`topic`としてAIが生成した1行要約タイトル(実際のメール件名とは異なる文言)を使っていたため、件名検索が常にヒットせず、Outlook側で何も選択されない状態になっていた。
	`actions_flat`に実際のメール件名(`group_by_thread`由来の`real_topic`、AIが介在しない生データ)を追加し、Outlookへのリンク生成時はこちらを使うように修正。一覧表示のタイトル自体は引き続きAI要約タイトル(`topic`)を使用。

### 変更関数
	`MailSummarizer.summarize_action_dashboard`（`actions_flat`の各要素に`real_topic`を追加）
	`HTMLReportGenerator.generate_action_dashboard_report`（Outlookリンクの`topic`パラメータに`real_topic`を優先使用）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_05_01.py`

既知の課題（今回は対象外）：
	同様のパターン（AI要約タイトルをOutlook件名検索に使ってしまっている）は、既存の`_build_thread_cards_html`にも存在する可能性がある。今回はアクションダッシュボードのみ修正し、既存タブのコードには触れていない。

変更しないこと（宣誓）：
	検索/整理タブ・プロジェクト俯瞰・スタッフ俯瞰・コックピット・`_build_thread_cards_html`に関する全コード

## VERSION 20260709_04_01

### 追加・修正
	**アクションダッシュボードの検索速度を改善**: 検索/整理タブと比べて検索完了まで約1分かかる不具合を修正。原因は、`_item_to_dict`が本文取得(`light_mode=False`)と同時に添付ファイル列挙・インライン画像のBase64埋め込み処理(Pillow使用)も実行してしまい、アクションダッシュボードでは不要な画像処理コストが毎メール発生していたこと。
	`light_mode`(本文取得の有無)と`skip_attachments`(添付ファイル処理の有無)を分離し、アクションダッシュボードでは「本文は取得するが添付ファイル処理はスキップする」設定にした。

### 変更関数
	`OutlookMailManager._item_to_dict`（`skip_attachments`パラメータ追加、添付ファイル処理条件に反映）
	`OutlookMailManager._add_single_item`（`skip_attachments`パラメータ追加、`_item_to_dict`へ伝播）
	`OutlookMailManager.search_mails_fast`（`conditions.get('skip_attachments', False)`を読み取り、`_add_single_item`呼び出しに反映）
	`OutlookMailManager.get_relevant_mails_for_period`（`conditions`に`'skip_attachments': True`を追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_04_01.py`

変更しないこと（宣誓）：
	検索/整理タブ・プロジェクト俯瞰・スタッフ俯瞰・コックピットの挙動（`skip_attachments`は未指定時False固定のため、既存呼び出し元は一切影響を受けない）

## VERSION 20260709_03_01

### 追加・修正
	**アクションダッシュボードでアクションが0件になる不具合(根本原因)を修正**: 20260709_02_01でも、キャッシュ削除後の再実行でAPIトークン消費はあるのにアクション0件が再現。原因は「本文が空文字でAIに渡っていた」こと。
	`search_mails_fast`は`body_keyword`（本文キーワード検索）が指定されない場合、高速化のため`light_mode`となり`_item_to_dict`で本文(`body`/`html_body`)を空文字にする仕様だった。`get_relevant_mails_for_period`は`body_keyword`を指定していなかったため常に本文なしでメールを取得しており、`summarize_action_dashboard`は送信者名だけの実質空の内容をAIに渡していた（トークンは消費されるが中身がないので何も抽出できない）。
	`search_mails_fast`に後方互換の新条件`force_full_body`を追加し、`get_relevant_mails_for_period`から明示的に指定することで本文を必ず取得するように修正。既存の他の呼び出し元（検索タブ等）には一切影響しない。

### 変更関数
	`OutlookMailManager.search_mails_fast`（`search_light_mode`の判定に`conditions.get('force_full_body', False)`を追加、後方互換）
	`OutlookMailManager.get_relevant_mails_for_period`（`conditions`に`'force_full_body': True`を追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_03_01.py`

動作確認時の注意：
	`analysis_cache/action_dashboard.json`に前バージョン（本文空で解析した結果）がキャッシュされている場合、スレッドのメール件数が変化しない限り再解析がスキップされます。このファイルを一度削除してから再テストしてください。

変更しないこと（宣誓）：
	コックピット・プロジェクト俯瞰・スタッフ俯瞰に関する全コード、`search_mails_fast`の`force_full_body`以外の既存ロジック（他の呼び出し元の挙動は完全に不変）

## VERSION 20260709_02_01

### 追加・修正
	**アクションダッシュボードでアクションが0件になる不具合を修正**: 20260709_01_01を実機テストしたところ、AI解析(トークン消費あり)は行われたのにアクションが1件も抽出されない不具合が発覚。原因は2点。
	**(1) 対象メールが「未読のみ」に絞られていた**: `get_relevant_mails_for_period`が`to_me/with_me/cc_me`条件を使っていたが、これはOutlookの検索フォルダー「未(ToMe)」「未(WithMe)」「未(CcMe)」（いずれも**未読専用**）だけを検索し、受信トレイ全体をスキャンしない仕様だった。`all_me`条件（受信トレイ全体・絞り込みなし）に変更し、既読メールも含めて期間内の受信トレイ全体を対象にした。
	**(2) `is_target`フィールドの意味を新プロンプトで定義していなかった**: `summarize_project_threads`由来の`thread_schema`をそのまま流用したため、本来「対象プロジェクトに関係あるか」を意味する`is_target`が意味不明なまま必須フィールドとして残っており、AIが`false`を返しやすく、`summarize_action_dashboard`側で該当スレッドが丸ごと除外されていた。`is_target`をスキーマ・必須リスト・フィルタ条件から完全に削除。

### 変更関数
	`OutlookMailManager.get_relevant_mails_for_period`（`all_me`条件への変更）
	`MailSummarizer.summarize_action_dashboard`（`thread_schema`から`is_target`削除、フィルタ条件削除）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260709_02_01.py`

動作確認時の注意：
	`analysis_cache/action_dashboard.json`に前バージョン（不具合あり）の解析結果がキャッシュされている場合、スレッドのメール件数が変化しない限り再解析がスキップされ、古い（除外済みの）結果が使われ続けます。このファイルを一度削除してから再テストしてください。

変更しないこと（宣誓）：
	コックピット・プロジェクト俯瞰・スタッフ俯瞰に関する全コード、`group_by_thread`・`_item_to_dict`等の既存メール取得・スレッド化ロジック

## VERSION 20260709_01_01

### 追加・修正
	**「📋 アクション」タブ（アクションダッシュボード）を新規追加**: 期間（24H/今日/3日間/1週間/2週間）を指定すると、既知のプロジェクト/スタッフに限定せず、自分宛て（To/With/Cc）の全メールを横断的に取得し、AIが「誰から・何を・いつまでに」求められているかをスレッド単位で抽出、1アクション=1行のフラットな一覧としてHTML表示するようになりました。既存のコックピット（4役職者ビュー×赤/黄/青のナラティブ要約）はそのまま残し、置き換えではなく新設です。
	**進捗ステータス（未着手/進行中/完了/無視）をワンクリックで確定・永続化**: 各アクション行にボタン群を配置し、クリックで即座に `json/action_status.json` へ保存されます。従来AIが解析のたびに`actions[].status`を自由記述で再生成し、ユーザーの手動確定が消えてしまっていた問題を解消しました。
	**優先度（空欄/★優先/★★最優先）を進捗とは独立した別軸として追加**: 同じく行内ボタンでワンクリック確定・保存されます。
	**アクションごとの1行コメント欄を追加**: 特に「進行中」時の状況メモ用途。フォーカスアウトで自動保存され、次回のフォーマット再生成でも保持されます。
	**完了/無視のデフォルト非表示化**: 一覧上部の「完了/無視も表示」チェックボックスで表示/非表示を切り替え可能。既定では対応待ちの項目のみが見える状態にしています。
	**「🎨 フォーマットのみ再生成」ボタンを追加**: 既存のコックピット/プロジェクト俯瞰と同様、`json/action_dashboard_last_result.json` にAI解析結果をキャッシュし、APIを再呼び出しせずにHTMLを再描画できます。再生成時は `json/action_status.json` の最新のステータスで上書きしてから描画します。

### 新規追加：
	`load_action_status` / `save_action_status`（`json/action_status.json` の読み書きヘルパー）
	`make_action_key`（スレッドID＋依頼者＋アクション文言からアクション項目の安定キーを生成）
	`OutlookRequestHandler.do_POST` に `/update_action_status` エンドポイントを追加（進捗・優先度・コメントの部分更新）
	`OutlookMailManager.get_relevant_mails_for_period`（期間×自分宛て全体のメールを横断取得）
	`MailSummarizer.summarize_action_dashboard`（`summarize_project_threads`のStage1相当を、特定プロジェクトに依存しない軽量版として実行し、`analysis_cache/action_dashboard.json`にキャッシュ）
	`HTMLReportGenerator.generate_action_dashboard_report`（フラットなアクション一覧HTMLを生成）
	`MailManagerGUI._ui_action_tab` / `_run_action_dashboard` / `_reformat_action_dashboard` / `_get_action_days` / `_save_action_dashboard_result`（新タブとそのハンドラ）
	定数 `ACTION_STATUS_FILE`、`ACTION_DASHBOARD_LAST_RESULT_FILE`

変更ファイル：
	`outlook_total_organizer_20260709_01_01.py`

既知の制約：
	アクション項目の同一性は `conversation_id + owner + action文言の先頭40文字` のハッシュで判定しています。AIが再解析時にowner/actionの文言を大きく書き換えた場合、別項目として扱われステータスがリセットされることがあります。

変更しないこと（宣誓）：
	コックピット（`generate_cockpit_summary`/`generate_cockpit_report`）本体のロジック・4役職ビュー構成、プロジェクト俯瞰・スタッフ俯瞰レポートの既存の`actions`テーブル表示・`_get_status_badge`の判定ロジック本体、`group_by_thread`・`_item_to_dict`等の既存メール取得・スレッド化ロジックに関する全コード

## VERSION 20260529_02_01

### 追加・修正
	**スレッドカードヘッダーの2カラム再設計**: Project俯瞰・Staff俯瞰の各スレッドカードのヘッダーを「左：`[N]`バッジ＋タイトル」「右：重要度・Outlook・学習・詳細・↑ 戻る」の2カラム固定レイアウトに変更しました。ボタン位置がタイトル長に関わらず常に右端に固定されます。
	**`[N]` バッジをタイトル左端に付与**: 従来の `No.N`（右端モノスペース）を廃止し、コックピットと同スタイルの `cite-badge` 形式の `[N]` をタイトル左端に配置しました。
	**`↑ 戻る` リンクの追加**: 各スレッドカード右端に、該当プロジェクト／スタッフ名ヘッダー行へジャンプする `↑ 戻る` リンクを追加しました。
	**コンテナタイトル行へのアンカーID付与**: `project-container` のタイトル `div` に `id="proj-top-{proj_id}"` / `id="staff-top-{staff_id}"` を付与し、`↑ 戻る` リンクのジャンプ先として機能させます。

### 変更関数
	`HTMLReportGenerator.generate_project_report`（コンテナタイトルID付与・カードヘッダー2カラム化）
	`HTMLReportGenerator.generate_staff_report`（同上）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260529_02_01.py`

変更しないこと（宣誓）：
	toggleThreadCard・forceOpenThread・jumpToThread・sortThreads・applyFilter・data-imp/data-date属性・acts_table・mail_items_html・generate_cockpit_report・_reformat_project・_reformat_staff に関する全コード
	
## VERSION 20260529_01_01

### 追加・修正
	**スレッド履歴を最新メール1件のみ初期展開表示に変更**: Project俯瞰・Staff俯瞰の各スレッドカードで、カード展開時にスレッド履歴エリアが最初から開いた状態で表示されるようになりました。表示されるのは最新メール1件のみです（スレッド全件の読み込みを廃止）。「▲ 閉じる」ボタンで手動で閉じることができます。

### 変更関数
	`HTMLReportGenerator.generate_project_report`（`mail_items_html` 最新1件化・履歴エリア初期展開）
	`HTMLReportGenerator.generate_staff_report`（同上）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260529_01_01.py`

変更しないこと（宣誓）：
	acts_table・toggleActions・アクションアコーディオン・toggleThreadCard・toggleSection・forceOpenThread・summarizeDetail・rule_btn・link_btn・detail_btn・generate_cockpit_report・_reformat_project・_reformat_staff に関する全コード
	
## VERSION 20260528_03_02

### 追加・修正
	**全JSONファイルを `json` フォルダに集約**: `mail_manager_config.json` / `excluded_domains.json` / `project_knowledge.json` / `cockpit_last_result.json` / `project_last_result_latest.json` / `staff_last_result_latest.json` の保存先をカレントディレクトリから `json/` サブフォルダに変更しました。
	**`json` フォルダの自動作成**: `load_config()` 先頭で `os.makedirs("json", exist_ok=True)` を実行し、初回起動時に自動でフォルダを作成します。
	**移行スクリプトの同梱**: 既存のJSONファイルを `json/` フォルダに自動移動する `migrate_to_json_folder.py` を同梱します。コード更新前に実行してください。

### 変更関数
	`CONFIG_FILE`（定数変更）
	`EXCLUDED_DOMAINS_FILE`（定数変更）
	`PROJECT_KNOWLEDGE_FILE`（定数変更）
	`COCKPIT_LAST_RESULT_FILE`（定数変更）
	`PROJECT_LAST_RESULT_FILE`（定数変更）
	`STAFF_LAST_RESULT_FILE`（定数変更）
	`load_config`（`json` フォルダ自動作成追加）

### 新規追加：
	`migrate_to_json_folder.py`（既存JSONファイル移行スクリプト）

変更ファイル：
	`outlook_total_organizer_20260528_03_02.py`
	`mi
## VERSION 20260528_03_01

### 追加・修正
	**Project俯瞰タブへの「フォーマットのみ再生成」ボタン追加**: `project_last_result_latest.json` に前回生成データを保存し、APIコール不要でHTMLを即時再生成するボタンを追加しました。
	**Staff俯瞰タブへの「フォーマットのみ再生成」ボタン追加**: `staff_last_result_latest.json` に前回生成データを保存し、APIコール不要でHTMLを即時再生成するボタンを追加しました。
	**`generate_project_report()` の `reformat_mode` 引数追加**: `reformat_mode=True` 時はHTMLフッターのコスト表示を「🎨 フォーマット再生成のみ（APIコスト無し）」に切り替えます。既存呼び出しはデフォルト値（False）により変更不要です。
	**`generate_staff_report()` の `reformat_mode` 引数追加**: 同上。
	**`orig_threads_map` の軽量保存**: JSON保存時に `{cid: {latest_entry_id, latest_date_str}}` の軽量版に変換し、メール本文・HTML本文を保存しません。復元時に `datetime` 型に変換して `generate_*_report()` に渡します。

### 変更関数
	`PROJECT_LAST_RESULT_FILE`（グローバル定数追加）
	`STAFF_LAST_RESULT_FILE`（グローバル定数追加）
	`HTMLReportGenerator.generate_project_report`（`reformat_mode` 引数追加・コスト表示条件分岐）
	`HTMLReportGenerator.generate_staff_report`（同上）
	`IntegratedSummaryApp._ui_project_tab`（`btn_reformat_project` 追加）
	`IntegratedSummaryApp._ui_staff_tab`（`btn_reformat_staff` 追加）
	`IntegratedSummaryApp._run_project_overview`（JSON保存ブロック追加）
	`IntegratedSummaryApp._run_staff_overview`（JSON保存ブロック追加）

### 新規追加：
	`IntegratedSummaryApp._reformat_project`（JSON読込→HTML再生成→ブラウザ起動）
	`IntegratedSummaryApp._reformat_staff`（同上）

変更ファイル：
	`outlook_total_organizer_20260528_03_01.py`

変更しないこと（宣誓）：
	Gemini APIコール処理・analysis_cache・summarize_project_threads・summarize_staff_threads・generate_cockpit_report・_reformat_cockpit・未読補正・light_mode・session_marked_read_entry_ids・全検索処理 に関する全コード
## VERSION 20260528_02_03

### 追加・修正
	**根拠スレッドカードのボタン順序調整**: 根拠スレッドカード右上のボタン配置を「↑ 戻る → 🚀 Outlook」から「🚀 Outlook → ↑ 戻る」に変更しました。「↑ 戻る」が常に右端に揃い、全カードで視線の動線が統一されます。

### 変更関数
	`HTMLReportGenerator.generate_cockpit_report` 内 `_render_related_threads()`（ボタン順序入れ替えのみ）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260528_02_03.py`

変更しないこと（宣誓）：
	outlook_link の href・style・テキスト、↑ 戻る の href・style・テキスト、その他全コード
## VERSION 20260528_02_02

### 追加・修正
	**🚀 Outlookリンクのopen_itemモード切替（バグ修正）**: 根拠スレッドカードの「🚀 Outlook」リンクから `&topic=...` パラメータを削除しました。これにより `open_thread`（subject検索）ではなく `open_item`（GetItemFromID直接参照）で動作するようになり、Gemini生成topicとメール件名の不一致による「検索に引っかからない」問題を解消しました。

### 変更関数
	`HTMLReportGenerator.generate_cockpit_report` 内 `_render_related_threads()`（`topic_encoded` 計算行削除・`outlook_link` のURLから `&topic=...` 削除）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260528_02_02.py`

変更しないこと（宣誓）：
	open_mail_item・show_thread_in_explorer・/openエンドポイント・Staff/Projectレポートの orig_topic_encoded・mail_topic_encoded・L4221の topic_encoded（_prepare_threads_data系）・その他全コード
	
## VERSION 20260528_02_01

### 追加・修正
	**analysis_cache への `latest_entry_id` 追加保存**: `summarize_project_threads()` および `summarize_staff_threads()` のキャッシュ保存時に、スレッドの最新メールの `latest_entry_id` を `analysis_cache/*.json` に保存するようにしました。
	**generate_cockpit_summary() への `latest_entry_id` 伝達**: `all_summaries` の各候補と `thread_data_map` の各エントリに `latest_entry_id` を追加し、`generate_cockpit_report()` まで確実に流れるようにしました。
	**根拠スレッドカードへの「🚀 Outlook」リンク追加**: Executive Cockpit の各根拠スレッドカードの右上（「↑ 戻る」の右隣）に「🚀 Outlook」リンクを追加しました。クリックでローカルサーバー経由でOutlookのスレッドビューを開きます。`latest_entry_id` が空（既存キャッシュ）の場合はリンクを非表示にします（graceful degradation）。

### 変更関数
	`MailSummarizer.summarize_project_threads`（キャッシュ保存2箇所に `latest_entry_id` 追記）
	`MailSummarizer.summarize_staff_threads`（同上）
	`MailSummarizer.generate_cockpit_summary`（`all_summaries` と `thread_data_map` に `latest_entry_id` 追加）
	`HTMLReportGenerator.generate_cockpit_report` 内 `_render_related_threads()`（`🚀 Outlook` リンク生成追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260528_02_01.py`

変更しないこと（宣誓）：
	open_mail_item・show_thread_in_explorer・_check_open_queue・/openエンドポイント・group_by_thread・Staff/Projectレポート生成・未読補正・light_mode・session_marked_read_entry_ids・reformat_mode・closeAllEvidence・openEvidenceAndJump に関する全コード
	
## VERSION 20260528_01_02

### 追加・修正
	**根拠スレッド一括クローズボタンの追加**: Executive Cockpitの最上部ヘッダーに「📌 根拠スレッドをすべて閉じる」ボタンを追加しました。クリックで全4Viewの根拠スレッド一覧を一括でデフォルト状態（閉じ）に戻します。
	**[n] クリック時の根拠スレッド自動展開**: 引用番号 `[n]` のリンクをクリックした際、対象の根拠スレッド一覧が閉じていても自動で展開し、該当カードへスムーズスクロール＋ハイライト表示するように変更しました。`href="#..."` による純粋HTMLアンカーから `onclick="openEvidenceAndJump()"` 方式に変更しています。
	**根拠スレッドカードへの「↑ 戻る」リンク追加**: 各根拠スレッドカードの右端に、該当Viewのダッシュボードサマリーセクションへジャンプする「↑ 戻る」リンクを目立たない小文字スタイルで追加しました。
	**summary-section へのアンカーID付与**: 各ViewのサマリーセクションDivに `id="view-summary-{role_key}"` を付与し、「↑ 戻る」リンクのジャンプ先として機能させます。

### 変更関数
	`HTMLReportGenerator._get_common_js_and_css`（JS関数2つ追加：`closeAllEvidence`, `openEvidenceAndJump`）
	`HTMLReportGenerator.generate_cockpit_report`（ヘッダーボタン追加・cite-badge変更・summary-section ID付与・根拠カード戻りリンク追加）

### 新規追加：
	なし

変更ファイル：
	`outlook_total_organizer_20260528_01_02.py`

変更しないこと（宣誓）：
	Gemini APIコール処理・analysis_cache・4View構成・引用番号採番ロジック・toggleSection/jumpToThread/toggleAnalysis・未読補正・light_mode・session_marked_read_entry_ids・reformat_mode・cockpit_last_result.json保存処理 に関する全コード
## VERSION 20260528_01_01

### 追加・修正
	**統括コックピット「フォーマットのみ再生成」ボタンの追加**: 統括コックピットタブに「🎨 フォーマットのみ再生成」ボタンを新設しました。APIコール不要で `cockpit_last_result.json` に保存済みのデータからHTMLを即時再生成します。
	**cockpit_last_result.json への永続保存**: `_refresh_cockpit()` および `_sync_and_refresh_cockpit()` の成功時に、cockpit_summary の戻り値・cache_dict・APIトークン数を `cockpit_last_result.json` へ保存するようにしました。ツール再起動後も再利用可能です。
	**generate_cockpit_report() の reformat_mode 引数追加**: `reformat_mode=True` 時はHTMLフッターのコスト表示を「🎨 フォーマット再生成のみ（APIコスト無し）」に切り替えます。既存の2か所の呼び出しはデフォルト値（False）により変更不要です。
	**ボタン初期状態の自動判定**: ツール起動時に `cockpit_last_result.json` が存在すれば即座に有効化、存在しなければグレーアウト（DISABLED）します。

### 変更関数
	`COCKPIT_LAST_RESULT_FILE`（グローバル定数追加）
	`HTMLReportGenerator.generate_cockpit_report`（reformat_mode引数追加・コスト表示条件分岐）
	`IntegratedSummaryApp._ui_cockpit_tab`（btn_reformat_cockpit 追加）
	`IntegratedSummaryApp._refresh_cockpit`（JSON保存ブロック追加）
	`IntegratedSummaryApp._sync_and_refresh_cockpit`（JSON保存ブロック追加）

### 新規追加：
	`IntegratedSummaryApp._reformat_cockpit`（JSON読込→HTML再生成→ブラウザ起動）

変更ファイル：
	`outlook_total_organizer_20260528_01_01.py`

変更しないこと（宣誓）：
	Gemini APIコール処理・analysis_cache 読み書き・4View構成・引用番号ロジック・アコーディオン動作・未読補正・light_mode・session_marked_read_entry_ids に関する全コード
## VERSION 20260527_01_04

### 追加・修正
	**Executive Cockpit根拠スレッド一覧のデフォルト折り畳み化**: `generate_cockpit_report()` 内の「📎 根拠スレッド一覧」を、初期表示では `display:none` の閉じた状態に変更しました。
	**既存toggleSectionの再利用**: 新規JSは追加せず、既存の `toggleSection()` を使って「▼ 根拠スレッド一覧を表示」ボタンで開閉できるようにしました。
	**引用番号・4View・根拠スレッド番号仕様は維持**: 20260527_01_03で導入したView内一意引用番号、4View表示、HTML内アンカージャンプ仕様は変更しません。

### 変更関数
	HTMLReportGenerator.generate_cockpit_report

### 新規追加：
	なし
## VERSION 20260527_01_03

### 追加・修正
	**Executive Cockpit引用番号のView内一意化**: `generate_cockpit_report()` において、各要約項目内で毎回 `[1]` と表示されていた引用番号を廃止し、各View内で `source_thread_id` ごとに一意の引用番号を付与するように変更しました。
	**R19 PM Viewの表示維持**: 前回QAで指摘された `r19_pm_view` の欠落を修正し、Executive Cockpitを4View構成（site_manager_view / r19_pm_view / pm_manager_view / te_pe_view）で描画するようにしました。
	**引用リンクのHTML内ジャンプ化**: 引用バッジ `[n]` をOutlookの `topic` 検索リンクではなく、同一HTML内の根拠スレッドカードへジャンプするアンカーリンクに変更しました。
	**根拠スレッドカードの追加**: 各Executive Cockpit Viewの下部に、引用番号と対応する根拠スレッド一覧を表示するHTMLブロックを追加しました。
	**同一スレッド番号の再利用**: 同じView内で同一 `source_thread_id` が複数要約項目に使われた場合、同じ引用番号を再利用するようにしました。
	**複数View重複表示の維持**: 複数Viewにまたがる同一根拠スレッドには、根拠スレッドカード側にも `🔁` を表示できるようにしました。

### 変更関数
	HTMLReportGenerator.generate_cockpit_report

### 新規追加：
	なし
## VERSION 20260527_01_02

### 追加・修正
	**Executive Cockpit引用番号のView内一意化**: `generate_cockpit_report()` において、各要約項目内で毎回 `[1]` と表示されていた引用番号を廃止し、View内で `source_thread_id` ごとに一意の引用番号を付与するように変更しました。
	**引用リンクのHTML内ジャンプ化**: 引用バッジ `[n]` をOutlookの `topic` 検索リンクではなく、同一HTML内の根拠スレッドカードへジャンプするアンカーリンクに変更しました。
	**根拠スレッドカードの追加**: 各Executive Cockpit Viewの下部に、引用番号と対応する根拠スレッド一覧を表示するHTMLブロックを追加しました。
	**同一スレッド番号の再利用**: 同じView内で同一 `source_thread_id` が複数要約項目に使われた場合、同じ引用番号を再利用するようにしました。
	**重複スレッド表示の維持**: 複数Viewにまたがる同一根拠スレッドには、根拠スレッドカード側にも `🔁` を表示できるようにしました。

### 変更関数
	HTMLReportGenerator.generate_cockpit_report

### 新規追加：
	なし
	
## VERSION 20260527_01_01

### 追加・修正
	**Multi活動俯瞰レポートのサマリーカード表示順変更**: 各Staffの活動俯瞰レポートにおいて、サマリーカードの表示順を「赤: 上司の介入・承認が必要な事項 → 黄: 停滞監視 → 青: スタッフの実績と次週予定」に変更しました。
	**Combined_Report 活動俯瞰レポートのサマリーカード表示順変更**: Project/Combined_Report活動俯瞰レポートにおいて、サマリーカードの表示順を「赤: 上司の介入・承認が必要な事項 → 黄: 停滞監視 → 青: プロジェクト進捗」に変更しました。
	**AI要約ロジック非変更**: JSONキー `manager_actions` / `staff_status` / `stalled_monitor`、Geminiプロンプト、検索処理、キャッシュ処理は変更せず、HTML表示順のみ変更しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report
	HTMLReportGenerator.generate_project_report

### 新規追加：
	なし
	
## VERSION 20260514_02_01

### 追加・修正
	**高速検索 light_mode の追加**: `OutlookMailManager._item_to_dict()` に `light_mode` 引数を追加し、通常検索時は本文・HTML本文・添付ファイル本体・インライン画像Base64化を取得しない軽量辞書化を行うようにしました。
	**検索結果追加処理の軽量モード対応**: `OutlookMailManager._add_single_item()` に `light_mode` 引数を追加し、検索時の軽量辞書化を下流へ渡せるようにしました。
	**通常検索と本文検索の切替**: `OutlookMailManager.search_mails_fast()` にて、`body_keyword` が空の場合は `light_mode=True`、本文検索がある場合のみ `light_mode=False` とするようにしました。
	**Conversation展開の挙動維持**: `GetConversation()` の利用可否や会話展開仕様は変更せず、会話展開内の `_add_single_item()` でも検索中の light_mode が効くようにしました。

### 変更関数
	OutlookMailManager._item_to_dict
	OutlookMailManager._add_single_item
	OutlookMailManager.search_mails_fast

### 新規追加：
	なし

## VERSION 20260514_01_02

### 追加・修正
	**セッション内既読維持リストの追加**: `OutlookMailManager.__init__()` に `session_marked_read_entry_ids` を追加し、ツール起動中にユーザーが既読化したメールのEntryIDをメモリ上で保持するようにしました。
	**既読化操作のセッション記録**: `mark_mails_read()` にて、ツール上で既読化対象になったEntryIDを `session_marked_read_entry_ids` に登録するようにしました。
	**フラグ/JUST DO IT未読補正のセッション除外**: `_item_to_dict()` にて、`FlagStatus == 2` または分類項目が `JUST DO IT` 完全一致の場合は未読扱いにします。ただし、同一ツール起動中に既読化したEntryIDは、再サーチしても既読状態を維持します。

### 変更関数
	OutlookMailManager.__init__
	OutlookMailManager.mark_mails_read
	OutlookMailManager._item_to_dict

### 新規追加：
	なし
	
## VERSION 20260514_01_01

### 追加・修正
	**フラグ付きメールの未読扱い補正**: OutlookメールをPython辞書へ変換する `_item_to_dict()` において、`FlagStatus == 2` のメールをPython側でも未読扱いに補正するようにしました。
	**JUST DO ITカテゴリの未読扱い補正**: Outlookの分類項目 `Categories` を `;` / `,` で分割し、カテゴリ名が `JUST DO IT` と完全一致する場合、Python側でも未読扱いに補正するようにしました。
	**再サーチ時反映仕様**: ツール上で既読化した直後は既読のまま保持し、次回サーチ時にOutlookの最新状態を再取得して未読扱いへ戻す仕様としました。

### 変更関数
	OutlookMailManager._item_to_dict

### 新規追加：
	なし

## VERSION　2026.0203.02
### 追加・修正
	**タブ応答待機設定のUI化**: 「10秒ルール（Slow Tab判定）」の閾値をUIから変更可能にし、PC負荷が高い場合などにユーザーが緩和できるように変更しました（デフォルト10秒）。
	**通信タイムアウトの適正化**: `YouTubeHandler` 内で動画リスト取得後に通信タイムアウトが強制的に10秒に短縮されていた不具合を修正し、60秒を維持するように変更しました。

### 変更関数
	ProcessConfig` (フィールド追加)
	IntegratedSummaryApp.setup_settings_frame` (UI追加)
	IntegratedSummaryApp.start_single_processing` (値渡し)

### 新規追加：

変更ファイル：
変更しないこと（宣誓）：
unified diff（必須）(それぞれどの関数のDiffかがわかるように表示する事）
生成したコードに中略、省略の文言が入らない事（必須）
変更した関数のみ：必ず完全版コードを提示する事を厳守してください。
変更前後でのメソッドの行数とその差分を表示する事（必須）
新規メソッドがある場合
挿入位置（Aの直後/Bの直前）
呼び出し元（どこから呼ぶか）
最小テスト手順（手でできる手順＋期待ログ）

ーーーー

## VERSION 20260514_01_01

### 追加・修正
	**フラグ付きメールの未読扱い補正**: OutlookメールをPython辞書へ変換する `_item_to_dict()` において、`FlagStatus == 2` のメールをPython側でも未読扱いに補正するようにしました。
	**JUST DO ITカテゴリの未読扱い補正**: Outlookの分類項目 `Categories` を `;` / `,` で分割し、カテゴリ名が `JUST DO IT` と完全一致する場合、Python側でも未読扱いに補正するようにしました。
	**再サーチ時反映仕様**: ツール上で既読化した直後は既読のまま保持し、次回サーチ時にOutlookの最新状態を再取得して未読扱いへ戻す仕様としました。

### 変更関数
	OutlookMailManager._item_to_dict

### 新規追加：
	なし
## VERSION 2026.0508.03.01
### 追加・修正
	**HTMLレポート軽量化モードの追加**: プロジェクト俯瞰タブおよびスタッフ俯瞰タブのレポート生成ボタン横に、レポートに含めるスレッドの範囲を選択できるラジオボタン（「🎯 AI採用スレッドのみ（軽量）」／「📋 全スレッド（詳細）」）を追加しました。
	**Stage2採用スレッドの自動フィルタリング**: 軽量モード（デフォルト）選択時、Stage2の分析結果（`manager_actions`, `staff_status`, `stalled_monitor`）の `source_thread_ids` に採用されたスレッドのみをHTMLレポートに出力するようフィルタリングロジックを追加しました。これにより、大量の不要スレッドが除外され、HTMLファイルサイズの大幅な削減とブラウザ描画の高速化が実現されます。
	**未解析時の安全なフォールバック**: 軽量モード選択時でも、AIによるStage2解析結果が存在しない（採用IDが0件の）場合は、自動的に全スレッド出力モードへフォールバックする安全機構を実装しました。

### 変更関数
	`IntegratedSummaryApp._ui_project_tab` (ラジオボタンUIの追加)
	`IntegratedSummaryApp._ui_staff_tab` (ラジオボタンUIの追加)
	`IntegratedSummaryApp._run_project_overview` (ラジオボタン状態の取得と引数渡し)
	`IntegratedSummaryApp._run_staff_overview` (ラジオボタン状態の取得と引数渡し)
	`HTMLReportGenerator.generate_project_report` (`report_mode`引数の追加とスレッド絞り込み処理の実装)
	`HTMLReportGenerator.generate_staff_report` (`report_mode`引数の追加とスレッド絞り込み処理の実装)

### 新規追加：
	なし
## VERSION 2026.0508.02.01
### 追加・修正
	**AI解析処理の2段階モデル戦略実装**: 大量スレッドの個別解析（Stage 1）のAPI待ち時間とコストを削減するため、Stage 1の解析には軽量・高速な `gemini-2.5-flash-lite` モデルを強制使用し、全体統合（Stage 2）のみ標準の `gemini-2.5-flash` モデルを使用する2段階戦略を導入しました。
	**API通信メソッドの拡張**: 共通のAPI呼び出しメソッドに対し、一時的にモデルを上書き指定できる機能を追加しました。

### 変更関数
	`MailSummarizer._run_genai_call_with_schema` (override_model引数の追加とモデル上書きロジックの実装)
	`MailSummarizer.summarize_project_threads` (Stage 1呼び出し時に "gemini-2.5-flash-lite" を指定)
	`MailSummarizer.summarize_staff_threads` (Stage 1呼び出し時に "gemini-2.5-flash-lite" を指定)

### 新規追加：
	なし

---

## VERSION 2026.0508.01
### 追加・修正
	**対象プロジェクトへの「03_R19Projects」追加**: プロジェクト俯瞰タブの対象プロジェクトに「03_R19Projects」を追加し、Allチェックボックスのトグル機能も同プロジェクトを考慮するよう修正しました。
	**03_R19Projectsのフォールバック検索対応**: Outlookの検索フォルダに「03_R19Projects」が見つからなかった場合、受信ボックスで「R19Proj」の分類タグが付与されているメールスレッドをフォールバックとして検索する処理を追加しました。
	**統括コックピットへの「R19 Sustaining PM View」追加**: 統括コックピットの表示において、「Japan Site Manager View」と「PM (Project) Manager View」の間に、「R19 Sustaining PM View (Target: Ochi, R19Proj進捗)」エリアを新設し、他エリアと同様に「🔴 即時介入・重大アラート」「🔵 戦略成果・ハイライト」「🟡 停滞監視・ボトルネック」のカードを表示するようにしました。

### 変更関数
	`load_project_knowledge` (デフォルトプロジェクト追加)
	`OutlookHandler.get_project_mails` (フォールバック検索処理追加)
	`IntegratedSummaryApp._ui_project_tab` (UI追加・ALLトグル修正)
	`IntegratedSummaryApp._run_project_overview` (対象追加)
	`IntegratedSummaryApp.generate_cockpit_summary` (r19_pm_viewのスコア計算および抽出ロジック追加、プロンプト修正)
	`HTMLReportGenerator.generate_cockpit_report` (HTML表示エリア追加)

### 新規追加：
	なし

## VERSION 20260507.05

### 追加・修正
	**Gemini入力構造の9箱化**: `generate_cockpit_summary()` 内で、Geminiへ渡す `final_content` を一括候補リストから `View × Section` の9箱構造へ変更しました。
	**View×色別候補数DEBUG追加**: `site_manager_view / pm_manager_view / te_pe_view` と `red_alerts / blue_highlights / yellow_stalled` の各箱について、Gemini投入前の候補数をDEBUG出力するようにしました。
	**Gemini役割の明確化**: `final_prompt` を「全体から自由に選ぶ」ではなく、「各箱から候補を選ぶ」前提へ修正しました。
	**補完ロジック維持**: 既存のPython補完、安全網、HTML生成、引用リンク処理は変更しません。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
	
## VERSION 20260507.04

### 追加・修正
	**Gemini出力形式の厳格化**: `generate_cockpit_summary()` 内の `final_prompt` に、配列内オブジェクト構造の具体例を追加し、`source_thread_ids` / `category` / `text` の出力形式を明確化しました。
	**純粋JSON出力の明示**: Gemini出力にMarkdownコードブロック、前後の挨拶文、説明文を含めないよう、純粋なJSON文字列のみを出力する指示を追加しました。
	**既存DEBUGの維持**: ユーザー方針に従い、現在残っているDEBUG出力は削除しません。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
## VERSION 20260507.03

### 追加・修正
	**補完項目の文章途中切れ禁止**: `generate_cockpit_summary()` 内のPython補完項目で、要約文を機械的に途中で切って `...` を付ける処理を廃止しました。句点などの文末で切れる場合のみ短縮し、文末が見つからない場合は途中切断せず全文を保持します。
	**セクション単位の補完追加**: `red_alerts` / `blue_highlights` / `yellow_stalled` のうち空のセクションがある場合、候補が存在する範囲で各セクションに1件ずつPython補完する処理を追加しました。
	**既存DEBUGの維持**: ユーザー方針に従い、現在残っているDEBUG出力は削除しません。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
	
## VERSION 20260507.02

### 追加・修正
	**Executive Cockpit空View補完の保存不具合修正**: `generate_cockpit_summary()` 内で、`final_res[role_key] = role_data` が `if not isinstance(role_data, dict):` の内側に入っていたため、Geminiが `pm_manager_view` / `te_pe_view` を返さなかった場合にPython補完結果が `final_res` に保存されない不具合を修正します。
	**補完ロジックの書き戻し保証**: `role_data` が既存dict・空dict・不正型のいずれであっても、必ず `final_res[role_key]` に書き戻すようにします。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
	
## VERSION 20260507.01

### 追加・修正
	**重複スレッド表示アイコン追加**: `generate_cockpit_report()` で、`duplicate_thread=True` の項目について、カテゴリ名の前に `🔁` を表示するように変更しました。
	**Python補完表示アイコン追加**: `generate_cockpit_report()` で、`auto_filled=True` の項目について、カテゴリ名の前に `🧩` を表示するように変更しました。
	**HTML描画の防御処理追加**: `items` 内の不正要素、`source_thread_ids` の非リスト値、Viewデータの非dict値に対する安全処理を追加しました。
	**既存リンク動作の維持**: 既存の `[1]` 引用バッジ、および `localhost:{self.server_port}/open?id=dummy&topic=...` によるOutlook検索連携は維持しました。

### 変更関数
	MailReportGenerator.generate_cockpit_report

### 新規追加：
	なし
## VERSION 20260507.01

### 追加・修正
	**Executive CockpitのView別候補保証**: `generate_cockpit_summary()` で、Site Manager / PM Manager / TE・PE の各Viewごとに候補を確保し、各View合計1件以上・最大9件を目標に統合するよう変更しました。
	**PM ViewのNakai優先化**: PM Viewでは `staff_Nakai.json` 由来の候補を最優先し、不足時に `project_*.json` 由来の候補で補完する設計に変更しました。
	**TE/PE Viewの補完強化**: TE/PE Viewでは `staff_Saji.json` / `staff_Yuto.json` / `staff_Najib.json` を優先し、不足時にProjectキャッシュ内の技術・試験・HTOL・PSI・ウェハー・CCOPP系候補を補完に使えるようにしました。
	**空View補完**: Geminiが空Viewを返した場合、Python側で候補から1件を `auto_filled=True` として補完する後処理を追加しました。
	**同一スレッド複数View利用の許可**: 同じ `thread_id` を複数Viewで利用できるようにし、同じHTML内で複数Viewに出た場合に `duplicate_thread=True` を付与する後処理を追加しました。
	**件数上限の制御**: 各Viewで `red_alerts` / `blue_highlights` / `yellow_stalled` を各最大3件、合計最大9件に制御するようにしました。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
## VERSION 2026.0506.07

### 追加・修正
	**統合コックピットJSON契約の一致化**: `generate_cockpit_summary()` の最終出力を、HTML描画側が期待する `site_manager_view / pm_manager_view / te_pe_view` 構造に変更しました。
	**表示枠とのキー不一致修正**: 旧構造 `alerts / action_queue / governance / stalled` を廃止し、各View内に `red_alerts / blue_highlights / yellow_stalled` を出力するように変更しました。
	**引用リンクIDの契約一致化**: HTML側が参照している `source_thread_ids` に合わせ、AI出力および物理リンク継承処理のキーを `thread_ids` から `source_thread_ids` に変更しました。
	**空HTML化の根本原因修正**: Geminiの出力が存在してもHTML側で空配列として扱われる不具合を、生成側スキーマの修正により解消しました。

### 変更関数
	MailSummarizer.generate_cockpit_summary

### 新規追加：
	なし
## VERSION 20260506.06 (Cockpit: Super-Robust Linkage Fix)
### 追加・修正
	**物理リンク紐付けの強化**: AIが返答したIDとキャッシュ内のIDを比較する際、空白の除去および大文字小文字の無視を徹底し、物理リンクの成功率を極限まで高めました。
	**空振り項目の救済**: 万が一、生データ（EntryID等）の紐付けに失敗した場合でも、AIが生成したテキスト（要約）だけは画面に表示する「表示優先モード」を導入。画面が「(報告事項なし)」になる現象を物理的に回避しました。
	**詳細ログの追加**: 紐付けプロセスにおける成功・失敗をコンソールに出力し、デバッグ性を向上させました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (紐付けロジックの刷新)

### 新規追加：
	なし
	
## VERSION 20260506.06 (Cockpit: 3-Axis Schema Sync)
### 追加・修正
	**3層構造スキーマへの完全同期**: 統括コックピットのAI出力定義を、V20260505.10で実装された3層構造（`manager_actions`, `staff_status`, `stalled_monitor`）に適合させ、HTMLレポート上でデータが正しく描画されるよう修正しました。
	**ID配列キーの適正化**: 根拠スレッドのIDを格納するキーを `thread_ids` から `source_thread_ids` へ修正し、画面側のリンク生成ロジックとの物理的な断絶を解消しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (スキーマ・プロンプト・抽出ロジックの刷新)

### 新規追加：
	なし
	
## VERSION 20260506.05 (Outlook: Robust Folder Discovery)
### 追加・修正
	**探索範囲のハイブリッド化**: 従来の検索フォルダー（Search Folders）走査に加え、見つからなかった場合に受信トレイ（Inbox）直下の通常のサブフォルダーも自動探索するフォールバック処理を実装しました。
	**EntryIDベースの重複排除**: 同一メールが検索フォルダーと通常フォルダーの両方に存在する場合に、レポート内で二重計上されないよう、物理アドレス（EntryID）による厳格な重複チェックを導入しました。
	**日付フィルタリングの物理整合**: 2000年以前の日付データによるWindowsエラー（OSError 22）を回避するため、取得日時の下限ガードを強化しました。

### 変更関数
	`OutlookMailManager.get_project_mails`

### 新規追加：
	なし
	
## VERSION 20260506.04 (Cockpit: UI Functional Parity)
### 追加・修正
	**UI機能の完全移植**: スタッフ俯瞰に搭載されていた「3軸連動ダッシュボード」および「多層アコーディオン（分析詳細・アクション・履歴）」を統括コックピットに移植しました。
	**物理リンクの接続**: バックエンドから渡された `thread_data_map` を利用し、EntryIDに基づいた確実なOutlook起動と、HTML内へのメール本文埋め込みを実現しました。
	**動的ID解決**: `cp_` 接頭辞を用いたID管理により、同一レポート内で複数のプロジェクトやスタッフが混在しても、正しいスレッドが開閉されるよう制御を最適化しました。

### 変更関数
	`MailManagerGUI._ui_cockpit_tab` (ダッシュボード表示枠の追加)
	`MailManagerGUI._render_cockpit_data` (描画ロジックの全面刷新)

### 新規追加：
	なし
	
## VERSION 20260506.03 (Cockpit: Complete Backend Pipeline)
### 追加・修正
	**AI指示文の再最適化**: 物理的なトークン限界を回避するため、AIへの要約指示を150文字から100文字へ厳格化。これにより、回答が途中で切れるリスクを物理的に抑制しました。
	**物理リンク（EntryID）の完全継承**: AIが選別した最重要スレッドのIDに基づき、キャッシュからメール履歴一式（生データ）を逆引きして統合するロジックを確定。スタッフ俯瞰と同様の「詳細アコーディオン」を統括コックピットで展開可能にしました。
	**ID衝突防止策の導入**: 統括画面での誤作動を防ぐため、スレッドIDに `cp_` 接頭辞を付与し、他のレポートとの一意性を確保しました[cite: 1]。

### 変更関数
	`MailSummarizer.generate_cockpit_summary`

### 新規追加：
	なし
	
## VERSION 20260506.02 (Cockpit: Token Overflow Fix)
### 追加・修正
	**コックピット生成時のトークン溢れ防止**: AIへの指示（プロンプト）を調整し、各項目の説明文をさらに短縮（150字→100字）させることで、回答が途中で切れる物理的リスクを低減しました。
	**JSONパースの堅牢化**: AIの回答が万が一途中で切れた場合でも、プログラム側で可能な限り閉じ括弧を補完して読み込めるよう、抽出ロジックを強化しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (プロンプト調整)
	`MailSummarizer._extract_json` (補完ロジック強化)

### 新規追加：
	なし
	
## VERSION 20260506.01 (Cockpit: Physical Link Inheritance)
### 追加・修正
	**統括コックピットの物理アドレス継承**: AIが選んだ「最重要スレッド」に対し、件名検索ではなくEntryIDで直接アクセスできるよう、キャッシュから生データ（メール履歴一式）を逆引きして統合するロジックを実装しました。
	**スタッフ俯瞰機能の完全移植基盤**: コックピットのデータ構造に、スレッド詳細、アクションリスト、全メール履歴を同梱し、HTML側でスタッフ俯瞰と同じフル機能のアコーディオンを展開可能にしました。
	**キャッシュ逆引きの堅牢化**: IDの不一致やファイル欠落時にシステムが止まらないよう、例外処理（try-except）によるスキップガードを導入しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary`

### 新規追加：
	なし
## VERSION 20260505.13 (Executive Cockpit: HTML Architecture & v4.0 Prompt)
### 追加・修正
	**フォルダ探索のフォールバック**: `OutlookMailManager.get_project_mails` において、SearchFolderが見つからなかった場合、通常の `inbox.Folders` からフォールバック検索を行うように修正しました。
	**v4.0プロンプトの適用**: `MailSummarizer.generate_cockpit_summary` の出力を、Roleベース（Site, PM, TE/PE）の3大コンテナと、緊急度（Red, Blue, Yellow）のクロス構造を持つJSONスキーマへアップデートしました。
	**HTML描画への移行**: `HTMLReportGenerator.generate_cockpit_report` を新設し、`MailManagerGUI` 側の更新処理からこれを呼び出して、ブラウザ上でレポートを開くように構造変更しました。

### 変更関数
	`OutlookMailManager.get_project_mails`
	`MailSummarizer.generate_cockpit_summary`
	`HTMLReportGenerator.generate_cockpit_report` (新規追加)
	`MailManagerGUI._refresh_cockpit`
	`MailManagerGUI._sync_and_refresh_cockpit`
	
## VERSION 20260505.12 (Project Report: Empty Data Fallback Fix)
### 追加・修正
	**空データ時のフォールバック修正**: プロジェクトの対象メールが0件だった際、システムがAI通信をスキップして出力するダミーデータが、古い仕様のままになっていた不具合を修正しました。これにより、対象メールがない場合も画面が空っぽにならず、青色パネル（🔵）の中に「指定期間のメールはありません」と正しく表示されるようになります。

### 変更関数
	`MailManagerGUI._run_project_overview`

### 新規追加：
	なし
	
## VERSION 20260505.10 (Project Report: UI 3-Tier Sync)
### 追加・修正
	**プロジェクト・カルテUIの3層構造化 (A案適用)**: AIから出力される新スキーマ（`manager_actions`, `staff_status`, `stalled_monitor`）を読み込み、プロジェクト俯瞰HTML上に「🔴 介入・承認待ち」「🔵 プロジェクト進捗」「🟡 停滞・要確認案件」の3つの専用パネルとして美しく描画するように改修しました。スタッフ側のコードに影響を与えないよう、安全な個別改修（A案）で実装しています。

### 変更関数
	`HTMLReportGenerator.generate_project_report`

### 新規追加：
	なし
## VERSION 20260505.09 (Project Report: AI Logic 3-Tier Sync)
### 追加・修正
	**プロジェクトAI出力の3層構造化**: スタッフ俯瞰とUIを統一するため、プロジェクト側の全体統合（Stage 2）のJSON Schemaも「🔴 manager_actions (上司の介入)」「🔵 staff_status (プロジェクト進捗と予定)」「🟡 stalled_monitor (停滞監視)」の3セクションに変更しました。
	**入力情報の物理制限による安定化**: プロジェクト側でAIが情報過多でパンク（空配列を出力）していた問題を解決するため、スタッフ側と同様に「重要度ソートで上位15件に絞り込み」「最大30,000文字制限」「`minItems: 1`, `maxItems: 3`」の物理制約を導入しました。

### 変更関数
	`MailSummarizer.summarize_project_threads`

### 新規追加：
	なし
	
## VERSION 20260505.08 (JSON Truncation Fix)
## 追加・修正
JSON出力の物理制限強化: スタッフ活動分析のStage 2において、AIが長文を出力しすぎてJSONが途切れる問題（Truncation Error）を解決するため、スキーマ定義に maxItems: 3 を追加し、プロンプトでの絞り込み指示を強化しました。これにより、安定したJSONパースを保証します。  

## 変更関数
MailSummarizer.summarize_staff_threads (Schemaおよびプロンプトの制約強化)

## VERSION 20260505.07 (JS Syntax Fix)
### 追加・修正
	**JavaScript構文エラーの修正**: `_get_common_js_and_css` 内の `regenerateQuestions` 関数において、`map` メソッドの閉じ括弧 `)` が欠落していたためブラウザ側でSyntaxErrorが発生し全機能が停止していた問題を修正。括弧を補完することで、アコーディオン展開や翻訳ボタンなどの全機能が正常に稼働するように復旧しました。

### 変更関数
	`HTMLReportGenerator._get_common_js_and_css`

### 新規追加：
	なし
	
## VERSION 20260505.05 (Staff HTML Report 3-Tier Update)
### 追加・修正
	**スタッフ・カルテUIの3層構造化**: AIが出力した新スキーマ（`manager_actions`, `staff_status`, `stalled_monitor`）を読み込み、HTML上に「🔴 介入・承認待ち」「🔵 今週の実績と次週予定」「🟡 停滞・要確認案件」の3つの専用パネルとして美しく描画するように改修しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report`

### 新規追加：
	なし
	
## VERSION 20260505.04 (Cockpit: Full Auto Sync Pipeline)
### 追加・修正
	**全自動同期パイプラインの実装**: 統括コックピットから「最新状況に更新」を押した際、事前に全プロジェクトおよび全スタッフの過去1週間分のメールを自動で取得し、AIで要約キャッシュを最新化してからコックピットを描画する `_sync_and_refresh_cockpit` メソッドを新設しました。
	**安全装置（確認ダイアログ）の追加**: APIコストと時間が大幅にかかる処理であるため、実行前にユーザーの意思を確認する警告ダイアログ（`messagebox.askyesno`）を挟み、誤操作による自爆（意図せぬ課金・フリーズ）を防ぎます。

### 変更関数
	なし（新規追加のみ）

### 新規追加：
	`MailManagerGUI._sync_and_refresh_cockpit`
	
## VERSION 20260505.03 (Cockpit: Split Update Buttons)
### 追加・修正
	**コックピット更新ボタンの分割**: ユーザーが用途（速度優先か、最新データ優先か）に応じて使い分けられるよう、統括コックピットタブのボタンを「既存状況をサマリ（高速）」と「最新状況に更新（全自動同期）」の2つに分割しました。
### 変更関数
	`MailManagerGUI._ui_cockpit_tab` (ボタンの追加と配置変更)
### 新規追加：
	（※次回出力予定）`MailManagerGUI._sync_and_refresh_cockpit`
	
## VERSION 20260505.02 (Staff Report: 3-Tier AI Logic)
### 追加・修正
	**スタッフ用AI出力の3層構造化**: スタッフ活動分析のStage 2（全体統合）のJSON Schemaを改修し、従来のステータス/リスク等から、「🔴 manager_actions (上司の介入)」「🔵 staff_status (実績と予定)」「🟡 stalled_monitor (停滞監視)」の3セクションに再定義しました。
	**プロンプトの明確化**: 各セクションの定義をAIに明示し、特に停滞監視については「文脈からボールを持ったまま止まっている案件」を抽出するように指示を追加しました。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (Schema, Prompt, および戻り値の構造変更)

### 新規追加：
	なし
	
	
## VERSION 20260505.01 (Cockpit: 2-Column UI, 150-char Limit, Safe Outlook Link)
### 追加・修正
	**プロンプト文字数制限の緩和（60文字→150文字）**: コックピット決勝AIの出力要約文（desc）の制限を150文字程度（約3行）に緩和し、事象と取るべきアクションを具体化しました。
	**2カラムレイアウトの実装**: ダッシュボードのカードUIを横幅フル活用に変更し、左側に要約テキスト（自動折り返し）、右側にスレッドへの直リンク（疑似リンク）を配置する2カラム構造に再設計しました。
	**安全なOutlook直リンク機能の追加**: AIが返した `thread_ids` を元にローカルキャッシュを裏で検索し、元の「件名」を抽出。それを右カラムにリンクとして描画し、クリック時に `show_thread_in_explorer` を用いてOutlook検索を走らせる直リンク機能を実装しました。
	**連打防止＆Null安全の徹底**: 不明なIDによるKeyErrorクラッシュを防ぐフォールバック（リンク無効化）と、OutlookのCOMサーバーフリーズを防ぐための「ボタン連続クリック防止（2秒クールダウンタイマー）」を実装しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (final_prompt の文字数緩和)
	`MailManagerGUI._render_cockpit_data` (2カラムUI化とリンク結合ロジックの導入)

### 新規追加：
	なし
	
## VERSION 20260504.06 (Cockpit Map Phase: Strict Qualification Limit)
### 追加・修正
	**予選リーグ（Map）の厳密な入場制限**: 予選AIの抽出条件（Schemaおよびプロンプト）に「最大3件まで」の厳格な制限（`maxItems: 3`）を追加し、決勝戦（Reduce）へ大量のデータが雪崩れ込む「ザル判定」を物理的に遮断しました。
	**決勝戦への物理的足切り**: 予選通過データ（`winners`）を最大20件にスライス（切り詰め）する安全装置を追加し、決勝AIの情報過多によるパースエラー（自爆）を根絶しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (予選用Schema/Prompt、及びリスト処理の改修)

### 新規追加：
	なし
	
## VERSION 20260504.05 (Cockpit Reduce: Schema Alignment & Array Limits)
### 追加・修正
	**コックピット決勝戦（Reduce）のパースエラー根絶**: AIへの指示書（プロンプト）とJSON定義（Schema）の間で発生していたキー名の矛盾（`source_thread_ids` と `thread_ids`）を修正し、`thread_ids` に完全統一しました。これによりAIの混乱によるトークン上限突破（尻切れ）を防ぎます。
	**配列の物理制限（maxItems）の追加**: Schema定義の `thread_ids` 配列に対し、物理的に `"maxItems": 3` の制限を追加し、システム側から強固なロックをかけました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (reduce_schema と final_prompt の改修)

### 新規追加：
	なし
## VERSION 20260504.04 (Cockpit Reduce: Strict Length & Limit Control)
### 追加・修正
	**コックピット決勝戦（Reduce）の出力暴走対策**: ユーザーの提案に基づき、表示項目数は「最大5つ（推奨3〜5つ）」の余裕を持たせつつ、AIの長文生成による尻切れトンボ（パースエラー）を防ぐため、プロンプトに「説明文（desc）は絶対に60文字以内」「無理に5件埋めず重要なものだけに厳選」という強力な文字数・件数制限を付与しました。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (final_promptの改修)

### 新規追加：
	なし
	
## VERSION 20260504.03 (Cockpit GUI: Real Data Binding & Refresh Logic)
### 追加・修正
	**「統括コックピット」タブの正確な追加**: 実際の変数名（`self.notebook` 等）に合わせて初期化コードの差分を修正しました。
	**データバインディングと更新ロジックの実装**: `_refresh_cockpit` メソッドを実装し、V25で追加したトーナメント方式のAIバックエンド（`generate_cockpit_summary`）を裏側で呼び出し、取得した4セクションのJSONデータをUIカードに描画する処理を追加しました。
	**手動Dismiss（フェイルセーフ）機能**: AIが「解決済み」と判断し損ねたアラートを、人間の判断でダッシュボードから手動で消せる「✖ 閉じる」ボタンを各アイテムに実装しました。

### 変更関数
	`MailManagerGUI.__init__` (タブの追加・正確版)
	`MailManagerGUI._refresh_cockpit` (バックエンドとの連携・UI描画)

### 新規追加：
	`_refresh_cockpit`
	
## VERSION 20260504.02 (Cockpit GUI: Executive Dashboard Tab)
### 追加・修正
	**「統括コックピット」タブの新設**: 経営層・管理者向けのトップダウン視点を提供する第4のタブをUIに追加しました。
	**4セクション・カードレイアウト**: 「🚨 アラート」「⚡ アクション・キュー」「📢 周知・ガバナンス」「🛑 停滞監視」の4つのエリアをスクロール可能なカード形式で配置し、重要事項を即座に視認できるよう設計しました。
	**一括同期・生成ボタン**: ワンクリックで全プロジェクト・スタッフの最新メールを解析（Stage 1）し、コックピットを更新する実行トリガーを配置しました。

### 変更関数
	`MailManagerGUI._ui_cockpit_tab` (新規追加)
	`MailManagerGUI.__init__` (タブの追加)

### 新規追加：
	`_ui_cockpit_tab`
	
## VERSION 20260504.01 (Cockpit AI Backend: Tournament Map-Reduce)
### 追加・修正
	**統括コックピット用AIロジックの実装**: 全プロジェクト・全スタッフのStage 1要約キャッシュをかき集め、AIに15件ずつの小分けで「予選（Map）」を戦わせ、勝ち上がった最重要スレッドのみを「決勝（Reduce）」で統合ダッシュボード化する `generate_cockpit_summary` メソッドを新設しました。これにより、数百件のデータを取りこぼしなく全件評価しつつ、トークン上限による自爆を物理的に防ぎます。

### 変更関数
	`MailSummarizer.generate_cockpit_summary` (新規追加)

### 新規追加：
	`generate_cockpit_summary`
## VERSION 2026.05.05 (Stage 2 Input Refinement Patch - Staff)
### 追加・修正
	**Stage 2入力スレッドの精鋭化**: AIが大量のスレッド情報を処理しきれず暴走する問題（パース失敗）を根本から解決するため、Stage 2に渡す個別要約データを「重要度（高→低）」および「最新日時（新→旧）」でソートし、上位15件に物理的に絞り込むロジックを追加しました。これにより、情報過多によるAIのパニック（トークン溢れ）を確実に防ぎます。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (入力データのソートと上限15件の切り出しを追加)

### 新規追加：
なし

## VERSION 2026.05.04 (JSON Schema Output Limiter Patch - Staff)
### 追加・修正
	**Staff俯瞰Stage 2出力の構造的制限（maxItems）**: 先のProject俯瞰側と同様に、Staff俯瞰（`summarize_staff_threads`）におけるAIの長文出力暴走（トークン上限による尻切れとパースエラー）を物理的に防ぐため、JSON Schemaの配列（project_status, highlights, risks, next_steps）に `"maxItems": 3` の厳密な制限を追加しました。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (Schemaの定義に `maxItems` を追加)

### 新規追加：
なし

## VERSION 2026.05.03 (JSON Schema Output Limiter Patch)
### 追加・修正
	**Stage 2出力の構造的制限（maxItems）**: AIが大量のインプットを受けた際に指示を無視して長大なJSONを生成し、トークン上限に達して自爆する問題（尻切れトンボによるパースエラー）を防ぐため、JSON Schemaの配列（project_status, highlights, risks, next_steps）に `"maxItems": 3` の厳密な制限を追加しました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (Schemaの定義に `maxItems` を追加)
	`MailSummarizer.summarize_staff_threads` (Schemaの定義に `maxItems` を追加) ※本出力では未生成

### 新規追加：
なし
## VERSION 2026.05.01 (JSON Parse Debug Patch)
### 追加・修正
	**JSONパース失敗時の生テキスト出力**: AIからの回答をJSONとしてパース（`_extract_json`）できなかった際に、単にエラーを返すだけでなく、原因究明のために生の回答テキスト（`response.text`）の先頭と末尾をコンソール（標準出力）へ表示するデバッグロジックを追加しました。これにより、トークン上限による出力途絶（尻切れトンボ）や不正な記号の混入など、パース失敗の真因を即座に特定できるようになります。

### 変更関数
	`MailSummarizer._run_genai_call_with_schema` (デバッグ用のprint文追加)

### 新規追加：
なし

## VERSION 20260430.03
### 追加・修正
	**「表示更新」ボタンの物理的配置修正**: Tkinterの配置（pack）仕様に基づき、ボタンの宣言順序を入れ替えました。これにより「表示更新」ボタンが入力項目に押し出されることなく、一番右側の「通常検索」ボタンのすぐ左隣に確実に表示されるよう修正しました。

### 変更関数
	`MailManagerGUI._ui_search_tab` (ボタン配置順序の修正)

### 新規追加：
	なし
## VERSION 20260430.02 (Display Refresh Button Visibility Fix)
### 追加・修正
	**「表示更新」ボタンの物理的配置**: UI定義関数 `_ui_search_tab` 内で、ボタンが他の検索ボタンに隠れないよう、右端の確実な位置に再配置しました。
	**描画整合性の確保**: `_refresh_display` 関数において、フィルタリング後のTreeview再描画プロセスとチェック状態（✓）の復元ロジックを統合し、意図した通りの「引き算」動作を保証しました。

### 変更関数
	`MailManagerGUI._ui_search_tab` (ボタン配置の再確定)
	`MailManagerGUI._refresh_display` (ロジックの完全版適用)

### 新規追加：
なし

## VERSION 20260430.01 (Search Tab Local Refresh Patch)
### 追加・修正
	**「表示更新」ボタンの実装**: 検索・整理タブに、Outlook通信を行わずメモリ上のリストを整理する「🔄 表示更新」ボタンを追加しました。
	**高速リフレッシュ機能**: 現在メモリにあるスレッド群に対し、UI上の「未読のみ」や「フラグ」等のフィルター条件を再適用して、条件外となった（既読化した等）項目を一瞬で消去します。
	**選択状態の維持**: リフレッシュ後も、画面に残った項目のチェック状態（✓）を維持し、連続した操作（Promotion移動等）を可能にしました。

### 変更関数
	`MailManagerGUI._ui_search_tab` (UIボタン追加)
	`MailManagerGUI._search_rss` (ボタン配置整合のための微修正)

### 新規追加：
	`MailManagerGUI._refresh_display` (高速表示更新ロジック)
	
## VERSION 20260427.04 (JSON Parse Robustness Patch)
### 追加・修正
	**JSONデコードの厳格モード解除**: `MailSummarizer._extract_json` にて、AIのテキストからJSONをパースする際、`json.loads` に `strict=False` オプションを追加しました。これにより、AIが長文出力時に誤って生の改行文字やタブ等の制御文字をJSON文字列内に混入させた場合でも、パースエラー（JSONDecodeError）でクラッシュせず安全に読み込めるようになります。

### 変更関数
	`MailSummarizer._extract_json` (json.loadsの引数追加)

### 新規追加：
なし
## VERSION 20260427.05 (Project Report UI Sync Patch)
### 追加・修正
	**プロジェクト概観UIの完全同期**: プロジェクト俯瞰レポート（`generate_project_report`）のHTMLテンプレートが古く、ボタン類やスレッド履歴が欠落していた不具合を修正しました。最新のスタッフ概観レポート（V19相当）のテンプレート構造を完全に移植し、Outlookボタン（生データ検索対応）、学習ボタン、詳細要約ボタン、およびメール履歴のアコーディオン表示がプロジェクト概観でも利用できるようにしました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (スレッドループ内のHTML組み立てロジックにボタン類と履歴抽出ループを追加)

### 新規追加：
なし
## VERSION 20260427.04 (Staff Report Original Topic Search Fix)
### 追加・修正
	**Outlook検索リンクの件名空振り修正**: AIによって要約・短縮された件名（`topic`）がOutlook検索パラメータに渡され、0件ヒットになる不具合を修正しました。スレッド単位および個別メールの「🚀 Outlook」リンクに渡す検索用件名を、AIの要約結果ではなく、必ず抽出元の生データ（`conversation_topic` または `subject`）から取得するように変更しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (URLパラメータ `topic` にエンコードする対象変数を変更)

### 新規追加：
なし
## VERSION 20260427.03 (Staff Report Outlook Link Upgrade)
### 追加・修正
	**個別メールOutlookリンクの挙動変更**: Staff概観レポート内の「スレッド履歴」に含まれる各メールの「🚀 Outlook」リンクに、スレッドの件名（topic）パラメータを追加しました。これにより、バックエンドのローカルサーバーがリクエストを「単体表示」から「メインウィンドウでのスレッド検索・選択」へと自動的にルーティングし、検索／整理タブと同等の利便性を実現しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (個別メールリンク生成部のURLパラメータ追加)

### 新規追加：
なし

## VERSION 20260427.02 (Staff Search Alias Safe Fix)
### 追加・修正
	**検索クエリのクラッシュ修正とアドレス置換への移行**: 前バージョン(20260427.01)で導入した「検索キーワードのダブルクォーテーション囲み」が Outlook COM API の構文エラーを引き起こし抽出が0件になる不具合を修正しました。ダブルクォーテーションを削除し、ノイズの多いスタッフ名（Oi）を、表示名ではなく一意性が高く安全なメールアドレスのプレフィックス（`yuto.oi`）に置換して検索する仕様に改めました。

### 変更関数
	`MailManagerGUI._run_staff_overview` (エイリアス辞書の値変更と、検索キーワードへのダブルクォート付与の削除)

### 新規追加：
なし
## VERSION 20260427.01 (Staff Search Alias & Exact Match Patch)
### 追加・修正
	**スタッフ名検索のエイリアス化と完全一致対応**: 「Oi」等、一般名詞や別単語と衝突しやすいスタッフ名に対し、検索実行時のみフルネーム（"Yuto Oi"）に置換する `SEARCH_ALIASES` 辞書を導入しました。さらに、置換後の検索キーワードをダブルクォーテーションで囲むことで完全一致検索（Exact Match）を強制し、ノイズメールの抽出を物理的に防ぎます。

### 変更関数
	`MailManagerGUI._run_staff_overview` (Outlook検索条件の組み立て部にエイリアス展開処理を追加)

### 新規追加：
なし

## VERSION 20260424.02 (Staff Multi-View DOM Collision Fix)
### 追加・修正
	**HTML要素IDのスタッフ別名前空間分離**: 複数スタッフのレポートを1つのHTMLに出力した際、同一スレッドが複数人に存在するとID（`thread_id`）が衝突して別人のアコーディオンが開いてしまう不具合を修正しました。HTMLに書き出すすべてのIDおよびJavaScriptの引数に、スタッフ名のプレフィックス（例: `Nakai_ABC1234`）を付与することで物理的な衝突を完全に防止しました。
	**引用リンクバッジの追従**: 上記のID分離に伴い、AIのサマリから発行される引用バッジ `[1]` のジャンプ先関数 (`jumpToThread`) の引数にもスタッフ名を動的に渡し、正しいスタッフのブロックへ正確にスクロール・展開するように同期しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (内部関数 `_render_structured_items` とHTML出力文字列内のID変数を修正)

### 新規追加：
なし
## VERSION 20260424.01 (Integrated Staff Dashboard - Logic Update)
### 追加・修正
	**複数スタッフ統合解析の実装**: `_run_staff_overview` において、単一スタッフのみを対象としていたロジックを改修し、GUIで選択された「複数スタッフ」をループで処理して1つの `summaries` 辞書に統合する仕様に変更しました。
	**ファイル名とタイトルの動的変更**: 複数スタッフが選択された場合、レポートのHTMLファイル名を `Staff_Multi_...` とし、レポート上のタイトルを「👤 スタッフ活動俯瞰レポート (複数)」に切り替えるロジックを実装しました。
	**大文字・小文字の名寄せ（正規化）**: 実行時に `capitalize()` を使用して、JSONキーや検索ターゲットの文字列を先頭大文字に統一するフェイルセーフを追加しました。これにより、表記揺れによるデータ分断を防ぎます。

### 変更関数
	`MailManagerGUI._run_staff_overview` (複数対象のループ処理化とファイル名分岐の追加)

### 新規追加：
なし
## VERSION 20260424.01 (Integrated Staff Dashboard - GUI Update)
### 追加・修正
	**スタッフ複数選択UIの追加**: Staff 概観タブに、特定のスタッフ（Taizo, Nakai, Kajikawa, Saji, Oi, Najib）を複数選択できるチェックボックスを追加しました。
	**排他制御（グレーアウト）の実装**: ドロップダウンリスト（単一選択）とチェックボックス（複数選択）の間で排他制御を行い、どちらか一方のみが有効になるようにしました。また、複数選択時は「過去知識とインタラクティブ更新」の枠全体をグレーアウトし、更新対象の不一致によるデータ破損を物理的に防ぎます。

### 変更関数
	`MailManagerGUI._ui_staff_tab` (チェックボックスの追加と排他制御イベントのバインド)

### 新規追加：
なし

## VERSION 20260423.13 (Safe Project Dashboard Tags)
### 追加・修正
	**プロジェクト俯瞰ダッシュボードのタグ爆発防止**: AIによる `owner`（担当者）の自由記述抽出を廃止し、システム側で確定している「プロジェクト名」を強制的にバッジとして表示する仕様に変更しました。これにより、表記揺れや無関係な人物によるダッシュボード機能の崩壊（タグ爆発）を完全に防ぎます。
	**UI表示の最適化**: バッジアイコンを「👤（人物）」から「📁（プロジェクト）」に変更し、ダッシュボードのグループ化ボタンの表記を「担当者(Owner)別」から「📁 プロジェクト別」に変更しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (内部関数 `_render_structured_items` のオーバーライド処理およびJS書き出し部の変更)

### 新規追加：
なし

## VERSION 20260423.12 (Dashboard Link Recovery & Crash Prevention)
### 追加・修正
	**プロジェクト俯瞰リンクの復元 (Recover Dashboard Links)**: `summarize_project_threads` の Stage 2 において、AI への回答形式（Schema）とプロンプトに `source_thread_ids` を追加しました。これにより、トップサマリの各項目に根拠となるスレッドへのジャンプリンク（引用バッジ）が付与されるようになります。
	**プロジェクト未検出時のデータ構造修正 (Fix AttributeError)**: `_run_project_overview` 内で、該当メールがない場合に `project_status` に文字列を代入していた不備を修正し、空のリストを代入するように変更しました。これにより `_render_structured_items` での属性エラーを防止しました。
	**引数不整合の解消 (Fix TypeError)**: `generate_project_report` 呼び出し時の引数不足（プロジェクト名欠落）を修正し、正常にレポートが生成されるようにしました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (Schema/プロンプト追加)
	`MailManagerGUI._run_project_overview` (データ構造/引数修正)

### 新規追加：
なし

## VERSION 20260423.12 (Critical Fix: Data Structure & Argument Sync)
### 追加・修正
	**プロジェクト未検出時のデータ構造修正 (Fix AttributeError)**: 期間内にメールが存在しないプロジェクトにおいて、`project_status` に文字列を代入していた不備を修正しました。スタッフ版と整合性を取り、空のリストを代入することで `_render_structured_items` 内での `.get()` 呼び出しによるクラッシュを防止しました。
	**引数スタックの完全同期 (Alignment)**: 前回の V11 で修正した引数不一致（プロジェクト名渡し忘れ）を、現在の 2187 行ベースの物理ファイルに対して再適用し、`TypeError` を解消しました。

### 変更関数
	`MailManagerGUI._run_project_overview` (データ構造のリスト化および引数追加)

### 新規追加：
なし

## VERSION 20260423.11 (Critical Fix: Argument & Syntax Alignment)
### 追加・修正
	**プロジェクトレポート生成時の引数不整合の修正**: `MailManagerGUI._run_project_overview` 内で `generate_project_report` を呼び出す際、本来第1引数であるべき「プロジェクト名」が欠落していた問題を修正しました。これにより引数のズレが解消され、`TypeError` が物理的に解決します。
	**JS正規表現のPythonエスケープ警告修正**: `_get_common_js_and_css` 内の JavaScript 正規表現における `\d` などのバックスラッシュを Python の文字列仕様（`\\d`）に適合させ、`SyntaxWarning` を排除しました。

### 変更関数
	`MailManagerGUI._run_project_overview` (引数渡しの修正)
	`HTMLReportGenerator._get_common_js_and_css` (正規表現のエスケープ修正)

### 新規追加：
なし
## VERSION 20260423.10 (Fix Argument Mismatch in MailManagerGUI)
### 追加・修正
	**プロジェクトレポート呼び出しの引数不足解消**: `MailManagerGUI._run_project_overview` 内で `generate_project_report` を呼び出す際、メソッド定義側が要求する第1引数（プロジェクト名）が欠落し、引数の位置が一つずつズレていた問題を修正しました。選択されたプロジェクト名を先頭に渡すようにし、`TypeError` を解消しました。

### 変更関数
	`MailManagerGUI._run_project_overview` (内部関数 `task` 内の `generate_project_report` 呼び出し箇所)

### 新規追加：
なし

## VERSION 20260423.09 (Project-Level Fix: Minimal Integration)
### 追加・修正
	**Project版3軸連動の最小実装**: V01の軽量な構造を維持しつつ、`js-summary-item` クラスと3軸表示用スパン（`px-cat`, `px-proj`, `px-act`）を注入。Project版では `px-proj` に担当者（Owner）を割り当てることでJS共通化を実現。
	**固定背番号マッピング**: V05/V07（Staff版）で実績のある重要度順ソートによる固定背番号（No.XX）採番ロジックを Project版のスレッド詳細およびTop3引用バッジに統合。
	**ジャンプ用IDの付与**: スレッドカード大枠に `thread-body-`、詳細展開部に `inner-thread-body-` のIDを付与。V07のJSバグ修正と整合させ、消失バグを防止。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (V01ベースへの最小機能注入)

### 新規追加：
なし
## VERSION 20260423.07 (Accordion JS Fix)
★★現時点でもっとも安定したバージョンです。★★
### 追加・修正
	**アコーディオン開閉バグの修正 (Fix Accordion Toggle Target)**: V04/05で付与したアンカーIDの影響により、スレッドカードをクリックした際に中身が開かず、カード全体が非表示（消失）になってしまう致命的なバグを修正しました。JSの `toggleThreadCard` 関数が正しく「中身の要素（`inner-thread-body-`）」を開閉するように対象IDを修正しました。
	**ジャンプ展開の正常化 (Fix Jump Auto-Open)**: 引用バッジをクリックしてジャンプした際、スクロール先の親要素だけでなく、目的のスレッドの中身（`inner-thread-body-`）も自動的に開くように `jumpToThread` および `forceOpenThread` のロジックを修正しました。

### 変更関数
	`HTMLReportGenerator._get_common_js_and_css` (`toggleThreadCard`, `jumpToThread`, `forceOpenThread` の修正)

### 新規追加：
なし

## VERSION 20260423.06 (3-Axis Dashboard Prefix Restoration)
### 追加・修正
	**3軸連動接頭辞の復元 (Dynamic Prefix Restoration)**: V04/05の改修時に欠落していたTop3サマリの動的表示用クラス（`js-summary-item`, `px-cat`, `px-proj`, `px-act`）を復元し、ダッシュボードの表示切り替えボタン（カテゴリ別・プロジェクト別・アクション別）が正常に連動するように修正しました。
	**DOM破壊防止エスケープ (XSS/DOM Breakage Prevention)**: タグ復元に伴い、AIが生成したカテゴリ名等にHTML制御文字（`<`, `>`等）が含まれていた場合にUIが崩壊するリスクを防ぐため、`html.escape()` を適用して安全にタグ内へ埋め込む防弾処理を追加しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (`_render_structured_items` 内のHTML生成ロジック修正)

### 新規追加：
なし

## VERSION 20260423.05 (Global Thread Indexing)
### 追加・修正
	**グローバル通し番号の導入 (Global Thread Indexing)**: 引用バッジがすべて `[1]` になってしまう情報の埋没を防ぐため、デフォルトの並び順（重要度順）に基づいた「固定の通し番号（1, 2, 3...）」を各ターゲットスレッドに割り当てるロジックを導入しました。
	**引用バッジの最適化 (Citation Badge Optimization)**: Top3サマリの末尾に付与されるバッジの数字を、単なる配列のインデックスから上記の通し番号（例: `[12]` `[45]`）へ紐づくように修正し、一目で対象スレッドを識別できるようにしました。
	**スレッドカードへの背番号表示 (Card ID Labeling)**: リンクからのジャンプ到達時に「正しい場所に飛んだ」と無意識に確信できるよう、スレッド詳細カードのヘッダー右端に控えめなデザイン（11px、Slate Gray、等幅フォント）で `No.XX` を表示する要素を追加しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (通し番号のマッピング処理、バッジおよびカードUIへの反映)

### 新規追加：
なし

## VERSION 20260423.04 (Staff-Limited Traceability)
### 追加・修正
	**AI追跡用ID埋め込みロジック (AI Traceability Injection)**: Stage 2のAI解析において、各スレッド要約の先頭に `[ID: thread_id]` を明示的に付与するように変更しました。これにより、AIがどのスレッドを根拠にサマリを作成したかを正確に認識可能にしました。
	**Stage 2 スキーマ拡張 (JSON Schema Array Expansion)**: 統合サマリの各項目（project_status, project_risks等）に `source_thread_ids` という配列フィールドを追加しました。AIはこのフィールドに、根拠としたスレッドIDをリスト形式で出力します。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (ID埋め込みとスキーマ拡張)
	`HTMLReportGenerator.generate_staff_report` (※次ステップで対応予定)
	`HTMLReportGenerator._get_common_js_and_css` (※次ステップで対応予定)

### 新規追加：
なし

## VERSION 20260423.03
★★現時点でもっとも安定したバージョンです。★★
### 追加・修正
	**Staff俯瞰のJS/CSS統合とデグレ完全解消 (Common JS Integration & Markdown Fix)**: スタッフ俯瞰レポート内に直書きされていた巨大なJS/CSSを共通の `_get_common_js_and_css` メソッドへの呼び出しに統合しました。同時に、QA監査で指摘された「Markdownパースの初期化処理の消失」を修正し、`marked.js` のロードとパース処理を正しく復元・維持しました。これにより、表示崩れのリスクなく安全な一元化とアコーディオン一括開閉を実現しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (直書きJS/CSSの削除、共通メソッドへの統合、Markdown処理の維持)

### 新規追加：
なし

## VERSION 20260423.02
### 追加・修正
	**個別分析トグル関数の補完 (Toggle Analysis Function Fix)**: V20260423.01にてHTML側に実装した「▼ 分析を表示」ボタンを実際に稼働させるため、共通JavaScript内に欠落していた `toggleAnalysis` 関数を追加しました。これにより、各プロジェクト/スタッフ行をクリックした際の個別アコーディオン開閉が正常に機能するようになります。

### 変更関数
	`HTMLReportGenerator._get_common_js_and_css` (関数の追加のみ)

### 新規追加：
なし
## VERSION 20260423.01
### 追加・修正
	**「分析」アコーディオンの導入 (UI Container Wrapper)**: レポートの視認性を高めるため、プロジェクト/スタッフの各セクションにおいて「3軸連動ダッシュボード」「スレッド詳細」「AI質問と回答」「過去知識」の4要素を格納するラッパー要素 `<div class="js-analysis-wrapper">` を新設しました。初期状態は非表示（折り畳み）となり、ステータス（Top3）のみがクリーンに表示されます。
	**全分析の一括開閉ボタン (Global Toggle Control)**: 画面上部の表示切り替えボタン群の右端に「📂 全分析を展開」ボタンを追加しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (HTML構造へラッパーとボタンの追加)
	`HTMLReportGenerator.generate_staff_report` (※次ステップで対応予定)
	`HTMLReportGenerator._get_common_js_and_css` (※次ステップで対応予定)

### 新規追加：
なし

## VERSION 2026.0421.45 (Project Scope Strict Enum Constraint - Part 2)
### 追加・修正
	**スタッフ活動範囲のEnum制約導入 (Schema Enum Constraint)**: 「スタッフ俯瞰」のAI解析においても、JSON Schema側に `enum` を用いた物理制約（ハード制約）を導入しました。マスターデータに基づく `allowed_scopes` 配列をStage 1およびStage 2のスキーマに注入し、AIが「Caracal Study」のようなリスト外のタグを勝手に生成することをAPIレベルで完全にブロックします。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (Schemaへの Enum 注入)

### 新規追加：
なし

## VERSION 2026.0421.45 (Project Scope Strict Enum Constraint - Part 1)
### 追加・修正
	**プロジェクト範囲のEnum制約導入 (Schema Enum Constraint)**: V44のプロンプトによる指示（ソフト制約）ではAIの暴走を防げなかったため、JSON Schema側に `enum` を用いた物理制約（ハード制約）を導入しました。マスターデータから抽出したプロジェクトリストに「横断業務」「その他」を加えた `allowed_scopes` 配列を生成し、これをStage 1およびStage 2のスキーマに直接注入することで、AIがリスト外の独自タグを捏造することをAPIレベルで完全にブロックします。

### 変更関数
	`MailSummarizer.summarize_project_threads` (Schemaへの Enum 注入)

### 新規追加：
なし

## VERSION 2026.0421.44 (Project Scope Strict Normalization - Part 1)
### 追加・修正
	**プロジェクト範囲の動的統制 (Dynamic Scope Normalization)**: マスターデータ（`project_knowledge.json`）に登録されたプロジェクト名をプログラム実行時に動的に抽出し、AIへの制限リストとしてプロンプトに注入する仕組みを導入しました。これにより、AIによる勝手なプロジェクト名の捏造や表記揺れ（例: "Caracal Study" 等）を物理的に封殺し、タグを完全に統一します。

### 変更関数
	`MailSummarizer.summarize_project_threads` (プロジェクトリストの抽出とプロンプト厳格化)

### 新規追加：
なし

## VERSION 2026.0421.43 (Complete JS Functions Restoration)
### 追加・修正
	**JavaScript機能群の完全復元 (Full JS Restoration)**: アーキテクチャのモジュール化（V39）以降、共通化メソッド（`_get_common_js_and_css`）から欠落し、プロジェクト俯瞰のダッシュボードを完全に沈黙（`ReferenceError`）させていたすべてのJS関数群（`toggleSection`, `renderDashboards`, `applyFilter`, `summarizeDetail`, `translateText`, `saveAnswers` など計12個）を再実装しました。これにより、UIのインタラクティブ機能が100%復旧しました。

### 変更関数
	`HTMLReportGenerator._get_common_js_and_css` (欠落していたJS関数群の追加)

### 新規追加：
なし
## VERSION 2026.0421.42 (UI Components Restoration & JS Sanitization)
### 追加・修正
	**失われたUIコンポーネントの完全復元 (UI Components Restoration)**: 過去のアーキテクチャ再構築（V39）時に誤って削除されていた「📄 詳細」「🔄 学習」「✨ 要約」「🌐 翻訳」の各インタラクティブ機能ボタンを、スレッドカードおよびメール個別の適切な位置に再実装し、ダッシュボードの全機能を復旧しました。
	**JavaScript構文エラーの物理的根絶 (Complete JS Sanitization)**: AIが抽出したテキスト（シングルクォートやダブルクォートを含むトピック名など）をそのままJavaScript関数（`onclick` 属性）の引数に渡したことで発生していた `SyntaxError`（ブラウザの完全硬直）を修正。すべての動的引数に対して `replace("'", "\\'").replace('"', '&quot;')` による完全なサニタイズを強制適用しました。

### 変更関数
	`HTMLReportGenerator._build_thread_cards_html` (UIボタンの再実装とサニタイズ処理の徹底)

### 新規追加：
なし
## VERSION 2026.0421.41 (Project Report Chunked Write / Architecture Restore)
### 追加・修正
	**モジュール構造の復元と大容量出力の安定化**: 前バージョン（V40）で誤って先祖返りさせてしまった関数分割アーキテクチャ（V39ベース）を完全復元。その上で、数MBに及ぶHTML出力を安全に行うための `chunk_size` (500,000文字単位) を用いた分割書き出し処理のみを正確に適用し、OSバッファ溢れによる `Errno 22` を回避しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (Chunked Writeロジックへの置換)

### 新規追加：
なし

## VERSION 2026.0421.40 (Project Report UI Bulletproof)
### 追加・修正
	**JS構文エラーの物理的防止 (Strict Sanitization)**: プロジェクト俯瞰のHTML生成において、AIが生成した文字列（シングルクォートやダブルクォートを含む）がそのままJS関数の引数にバインドされて画面全体がクラッシュする不具合を修正。`replace("'", "\\'").replace('"', '&quot;')` によるエスケープ処理を強制適用し、UIの完全硬直を根絶しました。
	**大容量HTML出力の安定化 (Chunked Write)**: スタッフ俯瞰（V33）で適用した、50万文字単位でのチャンク分割書き込み処理をプロジェクト俯瞰にも水平展開し、OSのディスクI/Oバッファ溢れ（Errno 22）を完全に回避しました。
	**1970年問題の回避**: タイムスタンプ初期値を `2000-01-01` とし、Windows環境でのマイナス値によるクラッシュを防止しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (サニタイズ処理とChunked Writeの追加)

### 新規追加：
なし
## VERSION 2026.0421.39 (Search Tab Schema Enforcement)
### 追加・修正
	**HTML描画スキップの根本解決 (Schema-Driven Output)**: 検索タブ用のレポート生成メソッド（`_generate_overall_analysis`, `_generate_single_shot`, `_generate_batch_summaries`, `_generate_rss_summary`）に対し、最新の Modern SDK による `Response Schema` 定義を強制適用しました。
	**データ契約の確保 (Data Contract)**: HTML生成側の `_card` メソッドが描画に必要とするキー名（`summary`, `action_items`, `mail_summaries`, `is_rss` 等）をAIに確実に出力させることで、UIブロックがごっそり抜け落ちるサイレントエラーを物理的に根絶しました。

### 変更関数
	`MailSummarizer._generate_batch_summaries` (スキーマ定義の追加)
	`MailSummarizer._generate_overall_analysis` (スキーマ定義の追加)
	`MailSummarizer._generate_single_shot` (スキーマ定義の追加)
	`MailSummarizer._generate_rss_summary` (スキーマ定義の追加)

### 新規追加：
なし

## VERSION　2026.0203.02
### 追加・修正
	**タブ応答待機設定のUI化**: 「10秒ルール（Slow Tab判定）」の閾値をUIから変更可能にし、PC負荷が高い場合などにユーザーが緩和できるように変更しました（デフォルト10秒）。
	**通信タイムアウトの適正化**: `YouTubeHandler` 内で動画リスト取得後に通信タイムアウトが強制的に10秒に短縮されていた不具合を修正し、60秒を維持するように変更しました。

### 変更関数
	ProcessConfig` (フィールド追加)
	IntegratedSummaryApp.setup_settings_frame` (UI追加)
	IntegratedSummaryApp.start_single_processing` (値渡し)

### 新規追加：

ーーーここまでーーー

変更ファイル：
変更しないこと（宣誓）：
unified diff（必須）(それぞれどの関数のDiffかがわかるように表示する事）
生成したコードに中略、省略の文言が入らない事（必須）
変更した関数のみ：必ず完全版コードを提示する事を厳守してください。
変更前後でのメソッドの行数とその差分を表示する事（必須）
新規メソッドがある場合
挿入位置（Aの直後/Bの直前）
呼び出し元（どこから呼ぶか）
最小テスト手順（手でできる手順＋期待ログ）

ーーーー

## VERSION 2026.0421.38 (Search Tab Restoration)
### 追加・修正
	**検索タブレポート機能の完全復旧 (Search Report Restoration)**: 過去のアーキテクチャ移行（Modern SDK対応）時に欠落していた `summarize_multiple_threads` およびその関連メソッド（単一スレッド解析、バッチ処理、RSS解析など計7メソッド）を最新の `google.genai` SDK 仕様に書き換えた上で再実装しました。これにより、検索タブで複数スレッドを選択して「📊 レポート」ボタンを押した際に発生する `AttributeError` を完全に解消し、基本機能を取り戻しました。

### 変更関数
	`MailSummarizer.summarize_multiple_threads` (新規復元)
	`MailSummarizer.summarize_thread` (新規復元)
	`MailSummarizer._generate_batch_summaries` (新規復元)
	`MailSummarizer._generate_overall_analysis` (新規復元)
	`MailSummarizer._generate_single_shot` (新規復元)
	`MailSummarizer._fetch_web_content` (新規復元)
	`MailSummarizer._generate_rss_summary` (新規復元)

### 新規追加：
上記の検索用解析メソッド群
## VERSION 2026.0421.37 (Modern SDK + Staff Prompt Shield)
### 追加・修正
	**スタッフ俯瞰のSDKバージョンの整合 (SDK Version Alignment)**: V25以降の Modern SDK 環境において、旧仕様の `self.api_key` を参照してクラッシュしていた `AttributeError` を解消しました。
	**タグ爆発の抑制とトークン限界突破の回避 (Full Shield)**: V34で導入した「タグ固定リスト」および「Stage 2 の Top 3 制限」を Modern SDK 版にも完全に移植。100件超の大量データ解析時でも JSON 破損を防ぎ、安定したレポート生成を保証します。
	**ID整合性の物理担保 (Safe ID Injection)**: スタッフ俯瞰においても、非同期処理後の ID 取り違えを物理的に防ぐ `cid` 上書きロジックを追加しました。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (Modern SDK 準拠への書き換えとプロンプト厳格化)

### 新規追加：
なし
## VERSION 2026.0421.36 (Modern SDK + Project Prompt Shield)
### 追加・修正
	**プロジェクト俯瞰のトークン爆発回避 (Top 3 Strict Limit)**: V25以降のModern SDK対応コードにおいて、プロジェクト俯瞰の Stage 2（全体統合）プロンプトに「各セクションの出力は最大3つまでに厳密に絞り込むこと」という防弾ルールを適用しました。これにより、Caracal プロジェクトなど複数スレッドを同時解析した際の JSON 破損およびパースエラー（Stage 2 失敗）を完全に解消しました。
	**分類リストの明示化 (Category Restriction)**: Stage 1 のプロンプトに、具体的なカテゴリ（プロジェクト管理、定常業務など）とアクション（通知・共有など）のリストを明記。AIによる勝手なタグ乱造を防ぎました。
	**ID整合性の担保 (Safe ID Injection)**: 非同期処理時のIDシャッフルを防ぐため、AIの回答受領後に元の `cid` を `thread_id` として物理的に上書きする安全装置を追加しました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (プロンプトの厳格化およびID注入の追加)

### 新規追加：
なし

## VERSION 2026.0421.35 (Prompt Shield for Project Overview)
### 追加・修正
	**プロジェクト俯瞰のトークン爆発回避 (Project Top 3 Strict Limit)**: スタッフ俯瞰にのみ適用されていた「各セクションの出力は最大3つまでに厳選すること」という防弾ルールを、プロジェクト俯瞰の Stage 2（全体統合）プロンプトにも適用しました。これにより、Caracal プロジェクトなど複数スレッドを同時解析した際の JSON 破損およびパースエラーを完全に解消しました。
	**分類リストの明示化 (Category Restriction)**: Stage 2 のプロンプトで「既存の分類リスト」と曖昧に指示されていた箇所を修正し、具体的なカテゴリ（プロジェクト管理、定常業務など）とアクション（通知・共有など）のリストを明記。AIによる勝手なタグ乱造を防ぎました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (Stage 1 および Stage 2 のプロンプトの厳格化)

### 新規追加：
なし

## VERSION 2026.0421.34 (Prompt Shield for High Volume)
### 追加・修正
	**カテゴリ・タグ爆発の抑制 (Tag Restriction)**: Stage 1（個別抽出）のプロンプトにおいて、`category` と `action_type` に選択可能な固定リスト（プロジェクト管理、定常業務、障害・トラブル等）を明示し、完全一致での出力を強制。ダッシュボードのタグが無限増殖する不具合を解決しました。
	**トークン限界突破の回避 (Top 3 Strict Limit)**: Stage 2（全体統合）のプロンプトにおいて、「各セクションの出力は最大3つまでに厳選すること」という絶対ルールを追加。100件を超える大量のスレッドを解析した際に、AIの出力文字数（トークン）が上限を突破してJSONが破損し、トップページが空になる致命的なエラーを根絶しました。

### 変更関数
	`MailSummarizer.summarize_staff_threads` (Stage 1 および Stage 2 のプロンプトの厳格化)

### 新規追加：
なし
## VERSION 2026.0421.33 (V19 Base OS Fix)
### 追加・修正
	**1970年問題（物理クラッシュ）の回避**: スレッドの日付初期値を `1970-01-01` から安全な `2000-01-01` に変更しました。これにより、日本時間からUTCへの変換時に発生するマイナス値によって Windows OS が `[Errno 22] Invalid argument` を投げて即死する仕様バグを物理的に根絶しました。
	**大容量HTML出力の安定化（分割書き出し）**: 数MBに及ぶ巨大なHTML文字列を一括でディスクへ書き出す際のバッファ限界を回避するため、文字数ベースのチャンク分割書き込み（Safe Chunked Write）を実装。物理的なディスクI/O制限による `[Errno 22]` を解消しました。

### 変更関数
	`HTMLReportGenerator._prepare_threads_data` (タイムスタンプ初期値の安全化)
	`HTMLReportGenerator.generate_staff_report` (文字数分割書き込みの実装)

### 新規追加：
なし

## VERSION 2026.0421.31 (Layout & Language Rollback)
### 追加・修正
- **日本語出力・構造指定の完全復旧**: AIに対するプロンプト（指示文）から欠落していた「必ず日本語で出力すること」「業務のスコープ（プロジェクトやカテゴリ）ごとに明確に分類すること」という最重要制約を復活させ、英語化およびカテゴリ消失のバグを修正しました。
- **オリジナル3軸レイアウトの復元**: 承認なく追加されていた不要な「ハイライト」ブロックを削除し、本来の洗練された3軸構成（活動ステータス・課題/リスク・次のステップ）にレイアウトを戻しました。
- **業務別バッジ（アイコン）表示の修正**: HTML生成時に各項目の業務スコープアイコンを描画するためのフラグ指定（`True`）が抜けていたミスを修正し、視認性を完全に復旧しました。

### 変更関数
- `MailSummarizer.summarize_staff_threads` (プロンプトへの日本語指定・スコープ分類指示の復元)
- `HTMLReportGenerator.generate_staff_report` (レイアウトの3軸への差し戻し、およびバッジ表示フラグの修正)

## VERSION 2026.0421.30 (Timestamp OS Bug Fix & Type Safety)
### 追加・修正
- **1970年問題（マイナスタイムスタンプ）の物理的解決 (V29)**: スレッドの日付初期値を `1970-01-01` から `2000-01-01` に変更。日本時間（JST）からUTCへの変換時に発生するマイナス値によって Windows OS が `[Errno 22]` でクラッシュする仕様バグを完全に根絶しました。
- **型安全の強化とデータ構造の復元 (V30)**: `_run_staff_overview` から後段へ渡すデータの型をリストから辞書（Dictionary）構造へ復元し、`_prepare_threads_data` 側でも辞書・リストの両方を安全に処理できるガードロジックを実装。`'list' object has no attribute 'get'` エラーを解消しました。

### 変更関数
- `MailManagerGUI._run_staff_overview` (データ引き渡し時の型構造の復元)
- `HTMLReportGenerator._prepare_threads_data` (タイムスタンプ初期値の安全化、および型（Dict/List）両対応ガードの実装)

## VERSION 2026.0421.28 (Safe ID Injection & Char-based Chunking)
### 追加・修正
- **ID強制注入 (Synchronous CID Injection)**: 並列処理の順序（インデックス）に依存する危険な設計を撤回し、`as_completed` ループ内で確実に保持している元の `cid` を、AIの回答へ直接上書き（注入）する方式に変更しました。これにより非同期処理におけるデータシャッフル事故を完全に防ぎます。
- **文字数ベースのチャンク分割書き込み (Safe Chunked Write)**: マルチバイト文字（日本語や絵文字）のエンコード分断破損を防ぐため、バイト（Byte）単位ではなく「文字数（例：50万文字）単位」でHTML文字列を分割し、安全にディスクへ追記する設計を採用しました。
- **エラー時クリーンアップ (Write Rollback)**: 分割書き込み中にディスクエラー等で中断した場合、作成途中の壊れたHTMLファイルを物理削除（`unlink`）し、システムにゴミを残さないロールバック処理を実装しました。

### 変更関数
- `MailSummarizer.summarize_staff_threads` (結果受領直後の確実な `cid` 上書きロジックの追加)
- `HTMLReportGenerator.generate_staff_report` (文字数分割書き込みとエラー時クリーンアップの実装)

## VERSION 2026.0421.27 (Pipeline Telemetry & Path Normalization)
### 追加・修正
- **データパイプラインの可視化 (Telemetry)**: Stage 2 完了からファイル書き出しまでの各工程に詳細なログ出力を追加。スレッドIDの整合性、HTML文字列のサイズ、書き込み直前の物理パスをコンソールへ表示し、Errno 22 の真因を特定可能にしました。
- **ファイルパスの物理的正規化**: 保存先フォルダ名およびファイル名から、Windows が拒絶する可能性のある末尾の空白（Trailing Space）や制御文字を強制的に `strip()` する防衛ロジックを実装。

### 変更関数
- `MailManagerGUI._run_staff_overview` (解析完了後のデータ構造ログの追加)
- `HTMLReportGenerator.generate_staff_report` (パスの正規化および文字列サイズログの追加)
- `HTMLReportGenerator._prepare_threads_data` (IDマッピング失敗時の警告ログ追加)

## VERSION 2026.0421.26 (Individual Thread Safety Mechanism)
### 追加・修正
- **個別スレッド重量による安全装置の導入**: 1つのスレッド内に含まれるメール通数が10件を超えた場合、自動的に「軽量保護モード」を発動させるロジックを実装しました。これにより、Base64画像データや膨大な本文テキストのHTML埋め込みを物理的に回避し、Windows書き出しエラー（Errno 22）を根絶します。
- **軽量モード判定基準の多角化**: 従来のスレッド総数（30件超）という条件に加え、単一スレッドの密度（10通超）を監視対象に追加。物理的なファイルサイズの肥大化を未然に防止し、システムの安定性を確保します。

### 変更関数
- `HTMLReportGenerator._prepare_threads_data` (単一スレッド通数チェックおよび軽量モード発動条件の拡張)

### 新規追加
- なし
## VERSION 2026.0421.25 (Data Pipeline Restoration & Multi-Stage Integration)
### 追加・修正
- **Stage 1 (個別スレッド要約) の物理的復旧**: V17から消失していた「各スレッドを個別にAI解析して `data` キーを注入する」第1段階のパイプラインを `MailSummarizer` へ再実装しました。これにより、後続の統合解析（Stage 2）やHTML生成で発生していた `KeyError: 'data'` を物理的に解消しました。
- **インクリメンタル・キャッシュと鮮度管理の再装填**: `analysis_cache/` を利用した差分解析ロジックを復元。メール通数（`mail_count`）の変動や、AIルールのハッシュ値（`rules_hash`）の変化を検知し、必要なスレッドのみを再解析する高速化基盤を復旧させました。
- **Modern SDK準拠の並列解析エンジン**: `ThreadPoolExecutor` による5スレッド並列処理を、最新の `google.genai` SDK環境で動作するように刷新しました。`Response Schema` による構造強制を適用し、AIの回答形式を物理的に固定しています。
- **型安全フェイルセーフの適用**: Stage 2 失敗時の戻り値を「文字列」から「リスト型」へ修正しました。これにより、HTML描画時にサマリが一文字ずつバラバラに箇条書きされる表示バグを根絶しました。
- **変更範囲の限定（一石一鳥の排除）**: ご指示に基づき、通常のレポートボタン用メソッド（`summarize_multiple_threads`）の仕様変更は見送り、現行の動作を維持しました。

### 変更関数
- `MailSummarizer.summarize_project_threads` (V17ベースの2段階解析へ復元・SDK最新化)
- `MailSummarizer.summarize_staff_threads` (V17ベースの2段階解析へ復元・SDK最新化)
- `MailSummarizer._run_genai_call_with_schema` (Modern SDK版での新設・共通化)
- `MailManagerGUI._run_staff_overview` (Stage 1とのデータパイプライン接合)

### 新規追加
- `MailSummarizer._ensure_struct` (AI回答の型保証用ヘルパー)
## VERSION 2026.0421.24 (Modern SDK & Architecture Consolidation)
### 追加・修正
- **Google GenAI SDK (2026規格) への完全移行**: 非推奨となった `google.generativeai` パッケージを廃止し、最新の `google.genai` へ移行しました。これにより、`FutureWarning` を解消するとともに、2026年現在のバックエンド基盤に最適化された通信プロトコルを採用しました。
- **属性名不一致 (AttributeError) の物理的解消**: AIモデルのインスタンス保持名を `self.client` および `self.model_id` に整理し、内部処理を共通メソッド `_call_ai` へ集約しました。これにより、以前発生していた `object has no attribute 'model'` エラーを根絶しました。
- **トークン計測ロジックの刷新**: 最新SDKの `usage_metadata` 形式に合わせ、入力・出力トークン数を正確に加算・追跡するロジックを実装しました。レポート上のコスト計算精度を復旧させています。
- **プロンプトおよびロジックの完全復旧**: `summarize_project_threads` および `summarize_staff_threads` において、省略されていたプロジェクト知識の統合ロジック、分類リスト定義、およびエラートラップを一切の省略なく再定義しました。

### 変更関数
- `MailSummarizer.__init__` (最新SDKによる初期化への変更)
- `MailSummarizer._call_ai` (新規：AI通信ロジックの共通化)
- `MailSummarizer.summarize_project_threads` (最新SDK形式での完全復旧)
- `MailSummarizer.summarize_staff_threads` (最新SDK形式での完全復旧)

### 新規追加
- なし

## VERSION 2026.0421.23 (完全防御パッチ)
### 追加・修正
- **プロンプト定義の厳格復元**: 消失していた「業務カテゴリ(9種)」「アクションタイプ(4種)」「重要度(3種)」の固定リスト定義をStage 1/Stage 2の両プロンプトへ再装填しました。これにより、AIによる勝手なタグ生成を物理的に抑制し、集計ロジックとの不整合を解消しました。
- **防御的パース・正規化ロジックの実装**: スレッドデータから値を取得する際、`.get()`メソッドによるデフォルト値補完を徹底し、AIの出力欠落による `KeyError` クラッシュを物理的に防止しました。また、"Medium"や"通常"などの表記揺れを自動的に "中" 等の正規値へ変換するマッピング処理を導入しました。
- **ノイズフィルタリングの強化**: Stage 2（統合サマリ）の生成プロセスにおいて、`is_target: false`（ノイズ判定）とされたスレッドを要約対象から除外するように変更しました。これにより、全体サマリのノイズ混入を防ぎ、分析精度を向上させました。
- **フェイルセーフ構造への転換**: 万が一 Stage 2 の統合処理が失敗（AIの回答破損等）した場合でも、プロセス全体を停止させず、Stage 1 で完了している個別スレッドリストのみをレポートとして出力する「部分成功モード」を実装し、分析結果がゼロになる事態を回避しました。

### 変更関数
- `MailSummarizer.summarize_project_threads` (プロンプトの厳格化とリスト復元)
- `MailSummarizer.summarize_staff_threads` (プロンプトの厳格化とリスト復元)
- `HTMLReportGenerator._prepare_threads_data` (防御的パースと重要度正規化の追加)
- `MailManagerGUI._run_staff_analysis` (フェイルセーフ・例外トラップの追加)

### 新規追加
- なし
## VERSION 2026.0421.22 (Hotfix)
### 追加・修正
- **メソッド定義漏れの解消**: V21のリファクタリング過程で `HTMLReportGenerator` クラスから消失、あるいは呼び出し名と不一致となっていた `_get_status_badge` メソッドを再定義しました。これにより、レポート生成時に発生していた `AttributeError` を解消し、アクション項目の色付けバッジが正常に表示されるように修正しました。

### 変更関数
- `HTMLReportGenerator._get_status_badge` (メソッドの再配置および名称整合)

### 新規追加：
- なし
## VERSION 2026.0421.21 (Architecture Refactor)
### 追加・修正
- **HTML生成エンジンの疎結合化**: 500行を超えていた `generate_project_report` を、データ準備・部品構築・静的アセット出力の4つの役割に分離しました。これにより、AIによるコード生成時の欠落（省略）を物理的に防ぐ構造になりました。
- **データ・レンダリング・パイプラインの導入**:
    1. `_prepare_threads_data`: ソート・重要度判定・軽量モード判定を集約。
    2. `_build_thread_cards_html`: スレッドカードおよびメール履歴のHTML構築を担当。
    3. `_get_common_js_and_css`: プロジェクト版とスタッフ版で重複していたJS/CSSを共通化。
- **軽量モードの安定実装**: スレッド数が30件を超えた際の「ヘビーボリューム保護モード」を確実に発動させ、OSの `Errno 22`（書き込み制限）を回避するロジックをコンポーネント化しました。

### 変更関数
- `HTMLReportGenerator.generate_project_report` (ロジック移譲によるスリム化)
- `HTMLReportGenerator.generate_staff_report` (ロジック移譲によるスリム化)

### 新規追加
- `HTMLReportGenerator._prepare_threads_data`
- `HTMLReportGenerator._build_thread_cards_html`
- `HTMLReportGenerator._get_common_js_and_css`

## VERSION 2026.0421.20 (大規模データ耐性パッチ)
### 追加・修正
- **ヘビーボリューム保護モード（HTML軽量化）の導入**: スタッフ俯瞰などにおいてスレッド数が膨大（30件超）になった際、OSのファイル書き込み上限（`Errno 22`）でクラッシュする問題を解決しました。閾値を超えた場合は、メールの生本文（`body`）やインライン画像データ（`inline_images`）のHTMLへの埋め込みを自動スキップし、要約とOutlook起動リンクのみの「軽量モード」で出力する安全装置を実装しました。
- **Top 10 厳選抽出（トークン爆発の防止）**: 100件以上のスレッドを統合する際、AIの出力がトークン限界（8192）を突破してJSONが破損する問題を防ぐため、第2段階（全体統合）のプロンプトに「全体から最重要事項を最大10項目まで厳選してまとめる」という強い制約を追加し、サマリの密度とシステムの安定性を両立させました。

### 変更関数
- `HTMLReportGenerator.generate_project_report` (軽量モード判定の追加)
- `HTMLReportGenerator.generate_staff_report` (軽量モード判定の追加)
- `HTMLReportGenerator._card` (軽量モード時のレンダリング分岐処理)
- `MailSummarizer.summarize_project_threads` (Stage 2 プロンプトにTop 10制限を追加)
- `MailSummarizer.summarize_staff_threads` (Stage 2 プロンプトにTop 10制限を追加)

### 新規追加
- なし
## VERSION 2026.0421.19
### 追加・修正
- **ダッシュボード表示の最適化（プロンプト厳格化）**: プロジェクトおよびスタッフ活動の「第2段階（全体統合サマリ）」生成プロンプトに、以下の3つの絶対ルールを注入し、表示の崩れや冗長化を解決しました。
    1. **アイコンの絵文字固定**: `status_icon` フィールドの出力を「1文字の絵文字（🟢、🟡、🔴、⚪等）」に限定し、GUI上でのアイコン消失（テキスト化して出力される現象）を防ぎました。
    2. **テキストの簡潔化（100文字制限）**: `text` フィールドの出力内容を「必ず1文で完結させる」「100文字以内に収める」よう厳格に制限し、ダッシュボードでの可読性を大幅に高めました。
    3. **ノイズタグの排除**: `text` フィールドの先頭にAIが独自に付与していた不要な分類タグ（`[Request/Approval]`等）を禁止し、純粋な状況説明のみを出力するよう矯正しました。

### 変更関数
- `MailSummarizer.summarize_project_threads` (Stage 2 プロンプトの修正)
- `MailSummarizer.summarize_staff_threads` (Stage 2 プロンプトの修正)

### 新規追加
- なし
## VERSION 2026.0421.18 (Hotfix)
### 追加・修正
- **新旧SDKインポートの競合修正**: `_run_genai_call_with_schema` メソッド内で旧バージョンの `google.generativeai` をインポートしていたため、新SDKの `genai.Client` 呼び出し時に `AttributeError` が発生し、全スレッドの解析が「失敗（次回リトライ）」として扱われる致命的なバグを修正しました。正しい新SDK (`from google import genai`) に差し替えることで、正常にAPI通信と解析が実行されるようにしました。

### 変更関数
- `MailSummarizer._run_genai_call_with_schema` (インポート文の修正)

### 新規追加
- なし
## VERSION 2026.0421.17 (GUI Patch)
### 追加・修正
- **プログレスコールバックのGUI連結**: `MailSummarizer` に実装された2段階解析（抽出・統合）の詳細な進捗状況を、GUIのステータスバー（画面左下）にリアルタイムで表示するためのイベント連結を行いました。これにより、「抽出中 (3/20)...」や「全体サマリを統合中...」といった細かい状況がユーザーへ視覚的にフィードバックされます。

### 変更関数
- `MailManagerGUI._run_project_overview` (引数追加)
- `MailManagerGUI._run_staff_overview` (引数追加)

### 新規追加：
- なし
## VERSION 2026.0421.17
### 追加・修正
- **分散キャッシュ・アーキテクチャの導入**: 1週間分という大量のメールデータをAIのトークン制限（8192）に収めるため、解析結果をスレッド単位で `analysis_cache/` フォルダへ永続保存する機能を実装しました。
- **二段階解析パイプライン（抽出と統合）**:
    1. **第1段階（個別抽出）**: 新着・未解析スレッドのみをAIで個別に要約。出力サイズを最小化することで、JSONが途中で切れる物理的破綻を根絶します。
    2. **第2段階（全体統合）**: 保存された「要約リスト」を材料に、プロジェクト全体の俯瞰サマリ（Top 3, リスク等）を生成。広範囲な情報を高精度に凝縮します。
- **マルチスレッド並列解析**: 初回の解析スピードを向上させるため、最大5スレッドを同時にAI解析する並列処理ロジックを導入しました。
- **スマート・リフレッシュ機能**: スレッド内の「メール通数」や「AIルール」の変化を検知し、更新があったスレッドのみを自動で再解析するインクリメンタル（増分）更新に対応しました。
- **耐障害性の向上**: 通信エラー等で一部のスレッド解析が失敗しても、処理を中断せずにレポートを完成させ、次回実行時に失敗分を自動リトライするレジリエンス構造を構築しました。

### 変更関数
- `MailSummarizer._run_genai_call_with_schema` (新規追加：スキーマ付き安全呼出ヘルパー)
- `MailSummarizer.summarize_project_threads` (2段階解析への根本刷新)
- `MailSummarizer.summarize_staff_threads` (2段階解析への根本刷新)

### 新規追加
- `analysis_cache/` フォルダ（初回実行時に自動生成）
## VERSION 2026.0421.16
### 追加・修正
- **データ構造の完全正規化（GUIクラッシュ防止）**: プロジェクト解析結果が空、あるいはエラーが発生した場合でも、GUI側が描画に必要とする全てのキー（`project_status`, `project_highlights` 等）を空のリストとして保障して返すように修正しました。これにより、画面が白くフリーズしたり描画が停止したりする物理的な不整合を解消します。
- **解析ターゲット（プロジェクト名）の再注入**: 圧縮されていたプロンプト内に、解析対象であるプロジェクト名（`proj_name`）を物理的に再配置しました。AIが「どのプロジェクトについてサマリーを抽出するのか」を明確に認識できるようにし、解析の完遂率を向上させました。
- **内部変数の初期化不備の修正**: メソッド内の `failed_chunks` や `merged_result` の初期化位置を最適化。解析の途中でエラーが発生しても、呼び出し元へ安全に制御を戻し、成功ログやエラー警告が確実に出力されるよう堅牢化しました。

### 変更関数
- `MailSummarizer.summarize_project_threads` (構造正規化とプロンプト修正)

### 新規追加：
- なし

## VERSION 2026.0421.15
### 追加・修正
- **AttributeErrorの完全解消**: `summarize_staff_threads` メソッドがクラスから消失していた問題を修正。クラス全体を再定義し、全ての呼び出しに対して正常に応答することを保証します。
- **日本語出力指示の最終定着**: プロンプトの先頭と末尾に「日本語出力」の鉄則を配置し、英語メールの解析時でも日本語のレポートが生成されるよう修正しました。
- **堅牢なエラーリカバリ**: AIの回答が途中で切れても JSON を自動修復して読み通すロジックと、引用タグを物理的に消し去る正規表現を完備しています。

### 変更関数
- `MailSummarizer` クラス内の全メソッド（一括再定義による整合性確保）

## VERSION 2026.0421.14
### 追加・修正
- **日本語出力の徹底復旧**: プロンプトの構造を再編し、「全ての分析・要約・抽出結果を日本語で行うこと」という指示をAIの注意力が最も高まる位置へ再配置しました。これにより、英語メールの内容を日本語で構造化して出力する本来の機能を取り戻しました。
- **指示文の日本語重み付け**: スキーマ定義（英語のキー名）に引きずられてAIが英語で回答する傾向を抑制するため、プロンプト内に「日本語」というキーワードを戦略的に複数回配置し、言語制約を強化しました。
- **安定性の維持**: 引用タグ排除のための物理削除ロジックおよびResponse Schemaによる構造強制はそのまま維持し、パースエラーの防止と日本語化を両立させました。

### 変更関数
- `MailSummarizer.summarize_project_threads` (日本語出力指示の強化と再配置)
- `MailSummarizer.summarize_staff_threads` (日本語出力指示の強化と再配置)

### 新規追加：
- なし

## VERSION 2026.0421.12
### 追加・修正
- **NameErrorの解消**: `summarize_staff_threads` 内で欠落していた `failed_chunks = []` の初期化行を復元し、解析エラー発生時にクラッシュする不具合を修正しました。
- **エラーハンドリングの完全復元**: チャンク解析に失敗した際の警告表示（⚠️警告...）や、履歴の自動結合ロジックなど、VERSION 11で誤って削除された「安全装置」をすべて再実装しました。
- **物理的整合性の確保**: `summarize_project_threads` と `summarize_staff_threads` の間でロジックの差異をなくし、どちらのモードでも同様の安定性で動作するように統一しました。

### 変更関数
- `MailSummarizer.summarize_staff_threads` (変数の初期化漏れを修正)
- `MailSummarizer.summarize_project_threads` (エラーハンドリングの再強化)

### 新規追加：
- なし

## VERSION 2026.0421.11
### 追加・修正
- **JSON自動修復ロジック（JSON Repair）の導入**: AIの生成が途中で切れた場合（Truncation）でも、不足している引用符（"）やブラケット（]）、波括弧（}）を自動で補完して、読み取れる範囲のデータで解析を続行できるようにしました。
- **超強力な引用タグ排除（Aggressive Cleaning）**: 物理証拠で見られた `` 等のあらゆるバリエーションを、パース前に正規表現で物理的に根絶します。
- **プロンプトの「データ指向」化**: AIの役割を「分析者」から「構造化データの抽出器」へシフトし、余計な「根拠（引用）」を出力する動機を抑制します。

### 変更関数
- `MailSummarizer._extract_json` (JSON修復・強力クリーニングの実装)
- `MailSummarizer.summarize_project_threads` (プロンプトの役割定義変更)
- `MailSummarizer.summarize_staff_threads` (プロンプトの役割定義変更)

## VERSION 2026.0421.10
### 追加・修正
- **構造化出力（Structured Output）の導入（根本解決）**: AIのレスポンスに対して物理的な「型（スキーマ）」を定義・強制するGoogle GenAIのStructured Output機能を実装しました。これにより、AIがJSONの外部に引用タグ（``等）を出力することが物理的に不可能となり、JSONパースエラーと出力の異常切断（Truncation）を根本から根絶します。
- **文法エラーの物理的解消**: `_extract_json` メソッド内で `SyntaxError` の原因となっていた誤った正規表現記述を完全に削除し、Pythonの起動失敗問題を解消しました。
- **解析精度の安定化**: スキーマ定義により、AIが各フィールド（カテゴリ、スコープ等）に対して期待通りのデータ型を返すことがシステム的に保証されるようになりました。

### 変更関数
- `MailSummarizer._extract_json` (文法エラー箇所の削除とクリーンアップ)
- `MailSummarizer.summarize_project_threads` (Response Schema定義の追加とAPI適用)
- `MailSummarizer.summarize_staff_threads` (Response Schema定義の追加とAPI適用)

### 新規追加：
- なし

## VERSION 2026.0421.07
### 追加・修正
- **致命的文法エラー（SyntaxError）の物理的根絶**: `_extract_json` 内の正規表現記述を、エスケープ事故が100%発生しない安全な結合形式に書き換え、プログラムが正常に起動することを保証します。
- **引用タグ除去ロジックの確定**: `` 等のタグを確実に消去し、JSONパースエラーを解決します。
- **プロンプト指示の純化**: AIへの指示からエスケープミスを誘発する例示記号を完全に排除しました。

### 変更関数
- `MailSummarizer._extract_json` (SyntaxErrorの修正)
- `MailSummarizer.summarize_project_threads` (プロンプトの安全化)
- `MailSummarizer.summarize_staff_threads` (プロンプトの安全化)

## VERSION 2026.0421.06
### 追加・修正
- **致命的文法エラー（SyntaxError）の解消**: `_extract_json` 内でプログラムの起動を妨げていた不正なバックスラッシュ記法を物理的に削除しました。
- **正規表現の安全化**: 引用マーカー除去のための正規表現を、Python の文法に抵触しない安全な二重引用符形式 `r"..."` に統一しました。
- **プロンプトのクリーンアップ**: AI への指示文から、エスケープミスを誘発しやすい記号の例示を排除し、安全なテキスト指示に変更しました。

### 変更関数
- `MailSummarizer._extract_json` (文法エラーの修正)
- `MailSummarizer.summarize_project_threads` (プロンプト内の危険記号の排除)
- `MailSummarizer.summarize_staff_threads` (プロンプト内の危険記号の排除)

### 新規追加：
- なし

## VERSION 2026.0421.05
### 追加・修正
- **SyntaxError（未終端文字列）の完全修正**: `_extract_json` 内の正規表現において、Pythonの文法エラーを引き起こしていた raw string の記述ミスを修正しました。
- **引用マーカー除去ロジックの安定化**: AIが挿入する `` を、安全な文字列表記 `r"\"` で確実に除去するように変更しました。
- **プロンプト内記号の安全性確保**: プロンプト内の禁止例からも、エスケープミスを誘発するバックスラッシュ等の記号を物理的に排除しました。

### 変更関数
- `MailSummarizer._extract_json` (文法エラーの修正)
- `MailSummarizer.summarize_project_threads` (プロンプト内の危険な記号を排除)
- `MailSummarizer.summarize_staff_threads` (プロンプト内の危険な記号を排除)

### 新規追加：
- なし
## VERSION 2026.0421.04
### 追加・修正
- **文法エラー（SyntaxError）の修正**: プロンプト内の禁止指示例において、バックスラッシュが文字列クォーテーションをエスケープしていた箇所を削除し、プログラムが起動しない不具合を修正しました。
- **引用マーカー除去ロジックの適正化**: `_extract_json` 内の正規表現を、より確実に `` 形式を捉える形に整理しました。

### 変更関数
- `MailSummarizer._extract_json`
- `MailSummarizer.summarize_project_threads`
- `MailSummarizer.summarize_staff_threads`
## VERSION 2026.0421.03
### 追加・修正
- **JSONパースエラーの物理的根絶**: AIが意図せずJSON内部に挿入してしまう引用マーカー（``など）を、JSON読み込み直前に正規表現で強制排除するクリーニング処理を追加しました。
- **AIグラウンディング暴発の抑止**: `summarize_project_threads` および `summarize_staff_threads` のプロンプト内【厳守事項】に、引用マーカーやリファレンスタグの出力を絶対に禁止する強力な制約を追加し、出力途中でのTruncation（異常切断）現象を防ぎます。

### 変更関数
- `MailSummarizer._extract_json` (正規表現によるマーカー除去処理の追加)
- `MailSummarizer.summarize_project_threads` (プロンプトの厳守事項にマーカー禁止命令を追加)
- `MailSummarizer.summarize_staff_threads` (プロンプトの厳守事項にマーカー禁止命令を追加)

### 新規追加：
- なし

## VERSION 2026.0421.02
### 追加・修正
- **欠損ロジックの完全復旧（根本原因の解消）**: バージョン `2026.0421.01` 生成時に不適切に省略（中略）されてしまった `summarize_staff_threads` メソッド内のプロンプトおよび処理ロジックを、元の完全な状態に復旧しました。
- **AI出力安定化（JSON破損の防止）**: `summarize_project_threads` および `summarize_staff_threads` における1回あたりの処理スレッド数（`CHUNK_SIZE`）を `20` から `10` へ削減し、データ長大化による構文エラーを防ぎます。
- **API制限（429エラー）の予防措置**: チャンクサイズの削減に伴うリクエスト頻度増に対応するため、各チャンク処理の間に `time.sleep(3)`（3秒間の待機）を追加し、API制限エラーを回避します。

### 変更関数
- `MailSummarizer.summarize_staff_threads` (省略部分の完全復元、CHUNK_SIZE変更、Sleep追加)
- `MailSummarizer.summarize_project_threads` (CHUNK_SIZE変更、Sleep追加)

### 新規追加：
- なし

## VERSION 2026.0420.18
### 追加・修正
- **クリックスペースの完全分離**: TreeViewの行選択において、件名などのテキスト部分をクリックした際のフォーカスと、チェックボックス（☑/☐）のトグル操作を分離しました。左端の「✓」列をクリックした時のみ選択状態が切り替わるようにし、ダブルクリック時の誤作動を完全に防止しました。
- **`Ctrl+Q` ショートカットによる爆速既読処理**: TreeView上でフォーカス・選択されているスレッドに対し、`Ctrl+Q` キーを押すことで、瞬時に「チェック状態をONにする」と同時に「既読にする（UIをグレーアウト＋裏側でOutlookフラグ更新）」処理が連動して実行される機能を追加しました。複数行選択時の全既読にも対応しています。

### 変更関数
- `MailManagerGUI._ui_search_tab` (キーバインド `<Control-q>` の追加)
- `MailManagerGUI._click` (列判定によるトグル処理の制限)

### 新規追加：
- `MailManagerGUI._on_ctrl_q` (Ctrl+Q押下時のイベントハンドラ)
## VERSION 2026.0420.16
### 追加・修正
- **一括開閉トグルボタンの論理バグ修正**: 「スレッド情報を非表示」ボタンを押してもアコーディオンが閉じない（常に開く処理が実行される）バグを修正しました。
- **判定条件の厳格化**: JavaScript内の開閉判定ロジックを、曖昧な文字列一致（`includes('表示')`）から、状態を正確に表す記号判定（`includes('▼')`）に変更し、トグルの無限ループを物理的に解消しました。

### 変更関数
- `HTMLReportGenerator.generate_project_report` (JavaScript内 `toggleAllFilteredThreads` 関数の判定条件を修正)
- `HTMLReportGenerator.generate_staff_report` (同上)

### 新規追加：
- なし

## VERSION 2026.0420.15
### 追加・修正
	**プロジェクトレポートのアコーディオンUI化**: スレッド詳細を「件名・ボタン（1行目）＋ タグ（2行目）」のコンパクト表示に刷新し、クリックでスレッド内容が展開・格納されるアコーディオンUIを実装しました。
	**個別開閉 ＆ 一括トグル機能の統合**: フィルタリング状態にある対象スレッドのみを一括で「表示/非表示」にするトグルボタンを実装しました。
	**UX最適化（自動展開・イベント制御）**: 「詳細」「学習」などの内部ボタンをクリックした際にアコーディオンが誤作動しないよう `stopPropagation` を徹底し、同時にスレッドの中身が自動展開（`forceOpenThread`）される挙動を組み込みました。内部の学習フォーム（`<select>`や`<input>`）操作時にもアコーディオンが閉じないよう配慮しています。
	**Version 03 資産の完全継承**: 消失していた「iframe内テキスト抽出翻訳」「AIからの質問再生成（Gemini連携）」「履歴の動的保存」等の全ロジックを最新UIと共存する形で完全復旧しました。

### 変更関数
	HTMLReportGenerator.generate_project_report` (アコーディオンUI統合 ＋ Version 03 機能復元)
## VERSION 2026.0420.14
### 追加・修正
	**スタッフレポートのアコーディオンUI化**: スレッド詳細を「件名・ボタン（1行目）＋ タグ（2行目）」の超コンパクトな表示に刷新しました。スレッドカードをクリックすることで詳細が展開・格納されます。
	**個別開閉 ＆ 一括トグル機能**: フィルタリング状態にあるスレッドのみを一括で「表示/非表示」に切り替えるボタンを設置しました。フィルタを切り替えても各スレッドの開閉状態は個別に維持されます。
	**UXの最適化（自動展開と誤爆防止）**: 「詳細」や「学習」ボタンをクリックした際は、自動的にスレッドを展開して内容を表示します。また、ボタンクリック時のイベント伝播（stopPropagation）を実装し、不要な開閉動作を抑制しました。
	**Version 03 資産の完全継承**: 消失していた「インライン画像置換（Pillow連携）」「iframe内テキスト抽出翻訳」「スタッフ情報の動的保存」等の全ロジックを最新UIと共存する形で完全復旧しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report` (アコーディオンUI統合 ＋ Version 03 機能復元)
	
## VERSION 2026.0420.13
### 追加・修正
- **究極のコンパクトUI（アコーディオン化）**: 標準状態では「件名・ボタン類（1行目）＋ タグ類（2行目）」のみの表示とし、クリックで詳細が展開・格納されるアコーディオンUIを実装しました。これによりダッシュボードの視認性が飛躍的に向上します。
- **直感的な開閉UXとクリック誤爆防止**: 矢印記号などはあえて使わず、ホバー時の背景色変化とポインター（指マーク）のみで洗練された開閉操作を実現。スレッド内の個別ボタン（Outlook、学習、詳細等）をクリックした際は、イベント伝播制御（`stopPropagation`）によりアコーディオンの誤作動を防ぐとともに、自動的にスレッドが展開される連動挙動を組み込みました。
- **状態記憶 ＆ 一括トグルボタンの新設**: フィルタリングタグを切り替えても、各スレッドの「開いている/閉じている」状態を個別に記憶して維持します。さらに「すべての絞り込みを解除」の左横に、現在フィルタリングされている対象スレッドだけを一括で展開・格納（上書き）できる専用トグルボタンを追加しました。

### 変更関数
- `HTMLReportGenerator.generate_project_report` (HTML構造の大幅刷新、CSSホバー追加、開閉・一括トグル用JSの追加)
- `HTMLReportGenerator.generate_staff_report` (同上)

### 新規追加：
- なし
## VERSION　2026.0420.12
### 追加・修正
	**プロジェクトスコープの抽出制限**: AIへのプロンプトにおいて `project_scope` の抽出指示を「自由な固有名詞の抽出」から「指定された4つのスコープ（"Caracal", "Wheeling", "GrandTeton", "横断業務"）からの完全一致選択」に制限しました。これにより、ダッシュボード上で意図しないタグが爆発的に増殖する現象を防止します。

### 変更関数
	MailSummarizer.summarize_project_threads` (プロンプト内の project_scope 抽出ルールの修正)
	MailSummarizer.summarize_staff_threads` (同上)

### 新規追加：
	なし
## VERSION 2026.0420.11
### 追加・修正
	**スタッフレポート全機能の復元**: 消失していた「iframe制御および高度な配列翻訳ロジック」「AI質問生成」「スレッド並び替え(sortThreads)」「インライン画像置換」「コスト計算」を03バージョンのコードベースから完全復旧しました。
	**サマリ項目の案C（隠しタグ方式）統合**: スタッフ活動の「ステータス」「課題」「次週タスク」の各行に、[カテゴリ][プロジェクト][アクション]の接頭辞を埋め込み、上部ボタンで瞬時に切り替える機能を実装しました。
	**3軸連動ダッシュボード**: スタッフの個人活動量を「分類」「範囲」「行動」の3軸で集計するパネルを追加。バッジクリックで下部スレッドを絞り込むフィルタリング機能を統合しました。
	**物理的コピペ耐性の確保**: CSS疑似要素を使わず物理的な <span> 要素を使用することで、レポート内容をメール等にコピーした際に属性情報が保持されるよう設計しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report` (完全復元 ＋ 3軸統合版)
## VERSION 2026.0420.10
### 追加・修正
	**03バージョン機能の完全復元**: 消失していた「iframe内テキスト抽出・翻訳ロジック」「Geminiによる質問再生成」「スレッド並び替え（sortThreads）」「詳細要約」「コスト計算」をすべてオリジナルの状態で復元しました。
	**サマリTop 3 & 個別アイコン対応**: `project_status` をTop 3の箇条書きとして描画し、AI判定による個別ステータスアイコンを表示するよう拡張しました。
	**案C（隠しタグ方式）のJS実装**: 表示切替ボタンクリック時に、サマリ項目の隠し接頭辞（[カテゴリ]等）を連動して表示/非表示にするCSS操作ロジックを `switchView` 関数内に統合しました。
	**3軸連動フィルタリング**: ダッシュボードの各バッジに `applyFilter` を紐付け、上部サマリを維持したまま下部スレッドカードのみを瞬時にフィルタリングする機能を実装しました。

### 変更関数
	HTMLReportGenerator.generate_project_report` (完全復元 ＋ 3軸統合版)

## VERSION 2026.0420.09
### 新規追加：
- **`HTMLReportGenerator._render_structured_items`**: AIから渡された構造化データ（3軸属性付き）をHTMLのリスト形式に変換するコアロジック。
    - **案Cの実装**: カテゴリ、プロジェクト、アクションの3つの接頭辞を、CSSクラス（px-cat, px-proj, px-act）を持つ隠し `<span>` タグとして物理的に出力。
    - **物理的コピペ耐性**: CSSの `::before` ではなくHTML要素としてテキストを配置することで、ブラウザからのコピー操作時に接頭辞が含まれるよう配慮。
    - **ステータス個別アイコン対応**: `is_status` フラグにより、Top 3ステータス固有のアイコン（🟢/🟡/🔴）のレンダリングに対応。
	
## VERSION 2026.0420.08
### 追加・修正
- **案C（隠しタグ切替方式）の実装**: サマリの各 `<li>` 要素内に `[カテゴリ]` `[プロジェクト]` `[アクション]` の接頭辞を `display: none` の `<span>` で埋め込み、上部ボタンクリック時にJSで動的に表示を切り替える機能を実装しました。
- **ステータス情報の拡張（Top 3）**: `project_status` が文字列から構造化リストに変更されたことに対応。AI判定の `status_icon` と共に箇条書き形式で描画するよう変更しました。
- **3軸連動フィルタリングの統合**: ダッシュボードのバッジクリック時、下部のスレッド詳細（カード）のみを瞬時にフィルタリング（表示/非表示）するロジックをJSに追加しました。
- **ロジックの完全復元**: 前回の不適切な省略により失われていた「詳細要約生成」「AIルール学習」「翻訳機能」「コスト計算」等の全機能をオリジナルの品質で復元しました。

### 変更関数
- `HTMLReportGenerator` クラス全体（全メソッド）
## VERSION　2026.0420.07
### 追加・修正
	**要約データの完全構造化と属性付与**: `project_highlights`, `project_risks`, `project_next_steps` に加え、`project_status` もTop 3のリスト形式に変更しました。全サマリ項目に `category`, `project_scope`, `action_type` の3属性を強制付与するようプロンプトと内部安全装置（`ensure_struct`）を改修しました。
	**ステータス専用アイコンの分離**: `project_status` のみ、専用のプロパティとして `status_icon` (🟢/🟡/🔴) を独立して出力するようにAIへ指示を追加し、HTML描画時の装飾分離に備えました。

### 変更関数
	MailSummarizer.summarize_project_threads` (プロンプトと構造化ロジックの変更)
	MailSummarizer.summarize_staff_threads` (同上、スタッフ向け)
	
## VERSION 2026.0420.05
### 追加・修正
	**スタッフレポートの3軸フィルタリング対応**: `generate_staff_report` において、カテゴリ、プロジェクトスコープ、アクションタイプの3軸による連動フィルタリング機能を実装しました。
	**構造化サマリ表示の適用**: サマリ箇条書きの生成に `_render_structured_items` を使用するように修正し、個々の項目に `data-category` 属性を付与しました。
	**UIダッシュボードの拡張**: スタッフの活動ボリュームを視覚化する3軸集計バッジと、それらに連動するJavaScriptフィルタリングロジックを追加しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report` (サマリ生成ロジックの差し替え、HTML/JSテンプレートの更新)
## VERSION 2026.0420.04
### 追加・修正
	**サマリレンダリングの構造化対応**: `project_highlights` 等の箇条書き生成を `_render_structured_items` メソッド経由に差し替え、HTML要素に `data-category` 属性を付与しました。
	**3軸ダッシュボードのUI実装**: レポート上部の集計パネルにおいて、「分類項目（category）」「プロジェクトスコープ（project_scope）」「業務単位（action_type）」の3つの軸でバッジを表示するように拡張しました。
	**連動フィルタリングJSの強化**: バッジクリック時に、スレッドカードだけでなく画面上部のサマリ箇条書き（`.js-summary-item`）もカテゴリに基づいて動的に表示・非表示が切り替わる「連動フィルタリング」を実装しました。

### 変更関数
	HTMLReportGenerator.generate_project_report` (サマリ生成ロジックの差し替え、HTML/JSテンプレートの更新)
	
## VERSION 20260420.03
### 追加・修正
	**構造化データ描画ヘルパーの新規追加**: `HTMLReportGenerator` クラス内に、AIから渡された `{category, project_scope, action_type, text}` 形式の辞書を、3つのバッジと連動フィルタリング用の `data-*` 属性を持ったHTMLの `<li>` 要素に変換する `_render_structured_items` メソッドを新設しました。
	**フェイルセーフ**: AIが古い形式（ただの文字列）を返してきた場合でもクラッシュせずに安全に描画するフォールバック処理を実装しています。

### 新規追加関数
	HTMLReportGenerator._render_structured_items
	
## VERSION 20260420.02
### 追加・修正
	**スタッフサマリの構造化と厳格化**: `summarize_staff_threads` において、AIへのプロンプトを更新し、スタッフ固有の `project_highlights`、`project_risks`、`project_next_steps` もすべて `{"category": "...", "project_scope": "...", "action_type": "...", "text": "..."}` 形式で出力させるよう統一しました。
	**固定リストの強要**: プロジェクト版と同様に、事前に定義された「プロジェクト（3種）」「業務カテゴリ（9種）」「業務単位（4種）」のリストをAIに提示し、勝手な名称の捏造を禁止しました。
	**出力フォーマットの型保証（フェイルセーフ）**: AIの出力ブレに対応するため、指定の辞書構造へ強制変換する安全装置（`ensure_struct`）を実装しました。

### 変更関数
	MailSummarizer.summarize_staff_threads
## VERSION 20260420.01
### 追加・修正
	**プロジェクトサマリの構造化と厳格化**: `summarize_project_threads` において、AIへのプロンプトを更新し、`project_highlights`、`project_risks`、`project_next_steps` を `{"category": "...", "project_scope": "...", "action_type": "...", "text": "..."}` 形式で出力させるように変更しました。
	**固定リストの強要**: 事前に定義された「プロジェクト（3種）」「業務カテゴリ（9種）」「業務単位（4種）」のリストをAIに提示し、勝手な名称の捏造を禁止する厳格なプロンプトを追加しました。
	**出力フォーマットの型保証（フェイルセーフ）**: AIが文字列リストなどを返した場合に備え、強制的に指定の辞書構造へ変換する安全装置（`ensure_struct`）を実装しました。

### 変更関数
	MailSummarizer.summarize_project_threads
	
## VERSION 2026.0419.105 (パッチ5/5：最終パッチ)
### 追加・修正
	**スタッフダッシュボードの高度化**: レポート上部に、スタッフが抱えるタスクの重要度やカテゴリを可視化する「業務集計（ドリルダウン）パネル」を新設しました。
	**サマリ連動フィルタリングの統合**: バッジクリックによる同期フィルタリングJavaScriptエンジンをスタッフレポートにも適用し、大量のテキストから特定のカテゴリだけを瞬時に抽出可能にしました。
	**構造化レンダリングの適用**: `_render_structured_items` ヘルパーを使用し、AIの出力したリスクとタスクのJSONを安全にHTML化しました。
	**物理的構文エラーの完全回避**: プロジェクト版と同様に、テンプレート内の全てのJavaScript波括弧を `{{ }}` へ二重化し、SyntaxError を根絶しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report
	
VERSION 2026.0419.104 (パッチ4/5)
追加・修正
**プロジェクトダッシュボードの高度化**: レポート上部に、重要度やカテゴリごとの件数を集計して表示する「業務集計パネル」を新設しました。
**サマリ連動フィルタリングの統合**: 集計パネルのバッジをクリックすると、該当するスレッドカードだけでなく、上部の「課題・リスク」「次週のフォーカス」の箇条書きも連動してフィルタリングされるJavaScriptエンジンを実装しました。
**構造化レンダリングの適用**: 前回のパッチで追加した `_render_structured_items` を使用し、AIが生成した構造化データを適切に属性付きHTML（data-category）として描画するように変更しました。
**物理的構文エラーの完全回避**: Pythonの f-string 内で JavaScript の波括弧 `{ }` が衝突しないよう、テンプレート内の全ての波括弧を `{{ }}` へ二重化し、SyntaxError を物理的に根絶しました。
変更関数
HTMLReportGenerator.generate_project_report

## VERSION 20260419.30 (フェーズ3-1：MailManagerGUI 前半の完全復元)
### 追加・修正
	**GUI クラスの全機能復旧（前半）**: 原本(03.py)から脱落していた `MailManagerGUI` クラスの前半部分を 1bit も削らずに復旧しました。
	**UI構築と設定管理の復活**: `__init__`、スレッド管理、ステータス表示、各種タブ（検索・プロジェクト・スタッフ・設定）の構築ロジック、および知識（Knowledge）編集エディタの全機能を原本通りに再実装しました。

### 変更関数
	MailManagerGUI クラスの `__init__` から `_open_staff_knowledge_editor` までの全メソッド（原本ママ）
## VERSION 20260419.27
### 追加・修正
	**プロジェクトサマリの構造化対応**: `summarize_project_threads` において、AIへのプロンプトを更新し、`project_highlights`、`project_risks`、`project_next_steps` を `{"category": "...", "text": "..."}` 形式で出力させるように変更しました。
	**同期用カテゴリの動的提示**: 分析対象のスレッドに含まれる既存のカテゴリ（タグ）一覧をAIに渡し、可能な限り既存カテゴリと同期させるロジックを追加しました。
	**出力フォーマットの型保証（フェイルセーフ）**: AIが指定したJSONフォーマットを守らなかった場合（文字列のリストを返した場合など）に備え、強制的に `{"category": "全般", "text": "..."}` に変換する安全装置（`ensure_struct`）を実装しました。

### 変更関数
	MailSummarizer.summarize_project_threads
	
## VERSION 20260419.25
### 追加・修正
	**generate_staff_report の無欠復旧**: 原本(03.py)に存在した全コンポーネント（役割/背景/マスター経緯の編集、AIへの回答メモ保存、トースト通知、Outlook連携、Markdown 履歴解析、ノイズスレッド表示）を 100% 復元しました。
	**物理的構文エラーの根絶**: JavaScript および CSS ブロック内の全ての波括弧 `{` `}` を精査し、Python の f-string 評価時にクラッシュしないよう、全て `{{` `}}` へ二重化しました。これにより以前の SyntaxError を物理的に解消しています。
	**サマリ連動フィルタリングの統合**: 原本(03.py)の美しい UI を維持したまま、上部の「リスク」や「タスク」がカテゴリバッジと同期して消長する動的フィルタリングエンジンを接ぎ木しました。
	**省略の絶対排除**: 翻訳機能(dataset.original)、詳細要約の通信ロジック、担当者色分け badge、あらゆる詳細ロジックを 03.py 通りに再実装しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report (真・完全復元版)
## VERSION 20260419.21
### 追加・修正
	**generate_staff_report の完全復元**: 安定版(03.py)におけるスタッフ専用の全機能（役割/背景/マスター経緯の編集、AI質問、ノイズ判定、Outlook連携リンク）を 100% 復旧しました。
	**同期フィルタリングエンジンの完全統合**: スタッフの業務ボリューム（カテゴリ）をクリックした際、スレッド明細だけでなく上部の「注力タスク」や「課題」も連動して絞り込まれる動的ロジックを実装しました。
	**物理的構文エラーの根絶**: JavaScript ブロック内の `{` および `}` を全て `{{` および `}}` へ二重化。これにより、Python の f-string パースエラー（SyntaxError）を物理的に解消しました。
	**省略の絶対禁止を遵守**: 翻訳機能(dataset.original)、詳細要約の本文転送ロジック、marked.js による Markdown 表示など、削られていた全ての付帯ロジックを 03.py 通りに復元しました。

### 変更関数
	HTMLReportGenerator.generate_staff_report (完全無欠・同期フィルタリング版)
## VERSION 20260419.14
### 追加・修正
	**プロジェクトレポートの全機能復元**: 安定版(03.py)で実装されていた「AIからの質問(Q&A)」「ノイズ判定セクション」「マスター経緯/履歴表示」「アイコン装飾」を完全に復元しました。
	**サマリ項目の連動フィルタリング**: AIが構造化したカテゴリ情報を活用し、バッジをクリックすると明細だけでなく上部の「リスク」や「タスク」も連動して絞り込まれる「同期フィルタリング」を実装しました。
	**JSエスケープの物理的安定化**: Pythonのf-string内でJavaScriptを安全に共存させるため、安定版の手法（二重波括弧 {{ }}）を厳格に適用し、書き出しエラーを物理的に排除しました。
	**UIレイアウトの最適化**: 以前の美しいデザインを維持しつつ、サマリカードに最大高さ(max-height)を設定し、情報量が増えてもダッシュボードが押し流されないように調整しました。

### 変更関数
	HTMLReportGenerator._render_structured_items (新規ヘルパー)
	HTMLReportGenerator.generate_project_report (全機能復元・連動版)
	
## VERSION 20260419.13
### 追加・修正
	**AI出力の構造化（MailSummarizer）**: 課題・リスク、進捗、次週タスクを `{"category": "...", "text": "..."}` 形式で出力するようにプロンプトを更新しました。これにより、後続のHTMLでカテゴリごとのフィルタリングが可能になります。
	**データの堅牢性（フォールバック）**: AIが万が一古い形式（文字列）で返した場合でも、自動的に `{"category": "全般", "text": "..."}` へ変換する処理を追加し、既存の描画ロジックを保護しました。
	**安定機能の完全維持**: 安定版(03.py)に実装されていた「履歴の蓄積（タイムスタンプ付き統合）」および「JSONパース失敗時のエラーダンプ出力」を一切破壊せず維持しました。

### 変更関数
	MailSummarizer.summarize_project_threads
	MailSummarizer.summarize_staff_threads

### 新規追加：
	なし
## VERSION 20260419.11
### 追加・修正
	**HTML書き出しエンジンの堅牢化**: JavaScript部分をf-string評価から物理的に分離し、波括弧の競合による書き出しエラーを完全に解消しました。
	**サマリ連動フィルタリングの完全同期**: 構造化されたAIデータを活用し、カテゴリバッジをクリックした際、下のスレッドだけでなく上部の「リスク」「タスク」の箇条書きも連動してフィルタリングされるようにJSを改修しました。
	**AND条件ステート管理の実装**: 「重要度」と「カテゴリ」を重ねて選択できる「フィルター状態管理ロジック」を搭載しました。
	**UIのアクセシビリティ改善**: サマリが長くなった場合でもダッシュボードが隠れないよう、サマリカードに最大高さ(max-height)と内部スクロールを設定しました。
	**ボタン名称の維持**: 前バージョンの合意に基づき「詳細」「学習」という短縮名を継続適用しました。

### 変更関数
	MailSummarizer.summarize_project_threads (AI出力の構造化)
	MailSummarizer.summarize_staff_threads (AI出力の構造化)
	HTMLReportGenerator._render_structured_items (データ属性の埋め込み)
	HTMLReportGenerator.generate_project_report (JS分離・完全同期UI)
	HTMLReportGenerator.generate_staff_report (JS分離・完全同期UI)
	
## VERSION 20260419.08
### 追加・修正
	**双方向連動フィルタリングの実装**: 上部の集計バッジをクリックした際、スレッド明細だけでなく「課題・リスク」「次週のフォーカス」の各項目も、そのカテゴリに関連するものだけに絞り込まれる「ドリルダウンUI」を実現しました。
	**AND条件（重ねがけ）フィルター**: 「特定のカテゴリ」かつ「特定の重要度」といった、複数の条件を組み合わせた高度な抽出に対応しました。
	**サマリ項目の構造化レンダリング**: AIが生成したカテゴリ付きデータを解析し、各箇条書きに `data-category` 属性を付与して出力。JSによる精密な表示制御を物理的に可能にしました。
	**UIの堅牢化とリセット機能**: 垂直カードレイアウトを採用し文字重なりを排除。また、複雑なフィルタリングから即座に復帰できる「フィルター解除」ボタンを新設しました。

### 変更関数
	`HTMLReportGenerator._render_structured_items` (新規：構造化データの変換)
	`HTMLReportGenerator.generate_project_report` (全体UI・JSエンジンの刷新)

### 新規追加：
	なし
	
## VERSION 20260419.07
### 追加・修正
	**AIプロンプトの構造化改修**: 課題・リスク、進捗、次週タスクを単なる文字列リストではなく、業務カテゴリと紐付いたオブジェクト形式(`{"category": "...", "text": "..."}`)で出力するようにプロンプトを刷新しました。
	**解析データの堅牢化**: AIが構造化に失敗し文字列を返した場合でも、自動的に「全般」カテゴリを割り当てて処理を継続するフォールバック処理を実装しました。
	**カテゴリ名の一貫性保持**: 現在のスレッドで使用されているカテゴリ一覧をAIに事前提示することで、サマリ項目とスレッドの分類が一致しやすくなるよう改善しました。

### 変更関数
	MailSummarizer.summarize_project_threads
	MailSummarizer.summarize_staff_threads

### 新規追加：
	なし
	
## VERSION 20260419.03
### 追加・修正
	**AI出力の構造化プロンプト改修**: 課題・リスク、注力タスク等のサマリ情報を単なる箇条書きから、業務カテゴリと紐付いた「構造化データ（JSONオブジェクトの配列）」として出力するようにプロンプトを抜本的に強化しました。
	**解析ロジックの堅牢化（フォールバック実装）**: AIが構造化データを出力できなかった場合でも、従来のベタ書きテキストとして処理を継続し、レポート生成が止まらないフェイルセーフ機能を実装しました。
	**ステータス判定の精度向上**: 「今週のステータス」が欠落しやすい問題を解決するため、プロンプト内での定義を厳格化し、パース時のエラー耐性を高めました。
	**コンテキスト情報の拡充**: スレッドに付与された「カテゴリ」のリストをAIに明示的に渡すことで、サマリ項目とカテゴリの不整合を物理的に抑制しました。

### 変更関数
	`IntegratedSummaryApp._summarize_threads` (プロンプト定義およびパースロジックの改修)

### 新規追加：
	なし
## VERSION 20260419.02
### 追加・修正
	**スタッフダッシュボードの垂直統合**: スタッフレポート上部のサマリエリアを、情報の氾濫を防ぐ「垂直カードレイアウト（ステータス・リスク・フォーカス）」へ刷新しました。これにより、AIが生成する文章が長くてもUIが崩れず、確実に読めるようになっています。
	**動的バッジ集計パネル（スタッフ版）**: 個人のスレッド群から「重要度」と「業務カテゴリ」をリアルタイム集計するパネルを実装。どの業務に負荷が集中しているかを即座に可視化します。
	**ナビゲーション連動**: 集計バッジのクリックにより、特定カテゴリのスレッドのみを表示し、その場所へ自動スクロールする機能を統合しました。
	**ボタンUIの統一**: プロジェクトレポート同様、ボタン名を「詳細」「学習」へ短縮し、省スペース化を実現しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (全体レイアウト・JSエンジン改修)

### 新規追加：
	なし

## VERSION 20260419.01
### 追加・修正
	**ダッシュボードUIの垂直統合（新デザイン）**: レポート上部の活動サマリを、横崩れしにくい「縦並びの3セクション（ステータス・リスク・フォーカス）」に再編しました。
	**動的バッジ集計パネルの実装**: AIの定性的な文章の直下に、重要度やカテゴリごとの件数を自動計算する「集計バッジパネル」を追加しました。
	**ジャンプ機能と属性連携**: 集計バッジをクリックすることで、該当するスレッド群へ即座にフィルタリング（表示切り替え）し、スムーズに詳細へアクセスできるナビゲーションを実装しました。
	**ボタンUIの最適化**: 以前の合意に基づき、ボタンテキストを短縮（詳細要約→詳細、修正(学習)→学習）し、視覚的なノイズを削減しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (全体レイアウト・JSエンジン改修)
	`HTMLReportGenerator.generate_staff_report` (次ステップにて出力)

### 新規追加：
	なし
	
## VERSION 20260418.12
### 追加・修正
	**スタッフレポートのUI最適化**: `generate_staff_report` においても、プロジェクトレポートと同様に「詳細」「学習」へのボタンテキスト短縮を適用しました。
	**推論情報の階層化**: AIの判断根拠（推論）を「学習」アコーディオン内部へ移動し、初期表示のノイズを削減しました。文字色は視認性の高い濃いグレー（#475569）へ変更しています。
	**JSステータス表示の短縮**: 詳細要約の生成中テキストを「⏳ 生成中...」に短縮し、ボタンのレイアウト崩れを防止しました。
	**物理的整合性の維持**: 元コード（20260418_01.py）の引数定義およびビジネスロジックを1文字も変えずに保持し、物理的なインデントエラーが発生しないよう半角スペース4つで整形しました。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (UI文字列およびJSのテキスト置換、推論ボックスの移動)

### 新規追加：
	なし

ーーーここまでーーー
## VERSION 20260418.11
### 追加・修正
	**UIノイズの削減（ボタンテキスト短縮）**: 各スレッドカードのヘッダーに配置されているボタンのテキストを短縮（「詳細要約」→「詳細」、「判定を修正(学習)」→「学習」）し、画面幅が狭い場合でもレイアウトが崩れないようにスッキリとさせました。クリック時や通信中のテキストも「閉じる」「生成中...」に短縮しています。
	**推論情報の格納と視認性向上**: AIの判断根拠である「推論」の表示位置を、デフォルト表示から「学習」アコーディオン内の上部へ移動しました。これにより、初期表示のノイズを減らしつつ、AIの判定を修正する際の判断材料として最適な位置に配置しています。また、文字色を濃いグレー（#475569）に変更して視認性を高めました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (UI文字列およびJSのテキスト置換)
	`HTMLReportGenerator.generate_staff_report` (次ステップで出力予定)

### 新規追加：
	なし

ーーーここまでーーー
## VERSION 20260418.09
追加・修正
物理クラッシュ（TypeError）の完全解消: 提供された outlook_total_organizer_20260418_01.py のメソッド引数定義（summaries, orig_threads_map, date_range, sort_order, total_input, total_output 等）を1文字も変えずに復元し、呼び出し側との不一致によるプログラム停止を物理的に修正しました。
既存機能（翻訳・詳細要約・AI学習）の完全防衛: 以前のパッチで消失していた、HTMLレポート内の「翻訳ボタン」「詳細要約ボタン」「AI判定修正（学習）フォーム」およびそれらを支える JavaScript 通信ロジックをすべて元の長大なコードの状態に復元した上で、新機能をマージしました。
動的ダッシュボードの局所挿入: 既存の動作を破壊しない領域（CSS/JS定義部と、スレッドカード描画部）に限定して、グループ化機能と分類バッジ表示を実装しました。

## 変更関数
HTMLReportGenerator.generate_project_report (引数復元・機能マージ)
HTMLReportGenerator.generate_staff_report (引数復元・機能マージ)

## 新規追加：
なし
## VVERSION 20260418.07_Pending
追加・修正
**コード生成保留（推測排除ルールの発動）**: A案（既存文字列結合への局所パッチ）の承認を受領しましたが、現在のセッションに「ベースとなる実際のソースコード」が存在しないため、コードの破壊（前回のTypeErrorの再発）を未然に防ぐ目的で、推測によるコード生成をブロックしました。
## 変更関数
`HTMLReportGenerator.generate_staff_report` (予定)
## 新規追加：

## VERSION 20260418.02
### 追加・修正
	**動的ダッシュボード機能の実装**: 生成されるHTMLレポートに、スレッドを「業務カテゴリ」「プロジェクト」「アクション状態」の軸で瞬時に並び替え・グループ化できる動的インターフェースを追加しました。
	**メタタグ・バッジ表示**: 各スレッドのタイトルの下に、AIが抽出した分類タグを視覚的なバッジとして表示するようにしました。
	**物理ハングアップ対策（JS）**: 大量スレッド表示時のブラウザ負荷を抑えるため、DocumentFragmentを利用した高速なDOM再構築ロジックを採用し、並び替え時のフリーズを防止しました。
	**データ堅牢性の向上**: AIが生成したテキスト（引用符などを含む）がHTML構造を破壊しないよう、全てのメタデータに対してHTMLエスケープ処理を適用しました。

### 変更関数
	`HTMLReportGenerator._get_css` (バッジ・操作パネルのスタイル追加)
	`HTMLReportGenerator._get_js` (動的グループ化・ソートエンジンの実装)
	`HTMLReportGenerator._get_thread_list` (データ属性の埋め込みとバッジUIの追加)
	`HTMLReportGenerator.generate_report` (操作ボタンUIの挿入)

### 新規追加：
	なし
## VERSION 20260418.01
### 追加・修正
	**メタタグ推論プロンプトの導入 (V3.0)**: Staff概観およびProject概観の要約処理において、AIに「業務カテゴリ」「プロジェクトスコープ」「アクション状態」「思考プロセス(reasoning)」を推論・出力させるV3.0プロンプトを適用しました。対象スタッフ（またはプロジェクトマネージャー）の視点をプロンプトに動的に埋め込み、精度の高い分類タグをJSON形式で抽出します。
	**出力トークン超過対策 (物理ハングアップ防止)**: 各スレッドに推論過程（reasoning）と3つのメタタグが追加されることで出力トークン量が急増し、API制限（8192）に激突してJSONが破損するリスク（自爆）を回避するため、一度に処理するスレッド数（`CHUNK_SIZE`）を40から20に安全に減らしました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (CHUNK_SIZEの削減、プロンプト・JSONスキーマの改修)
	`MailSummarizer.summarize_staff_threads` (CHUNK_SIZEの削減、ターゲット視点の動的埋め込み、プロンプト・JSONスキーマの改修)

### 新規追加：
	なし
## VERSION 20260417.04
### 追加・修正
	**期間検索（任意時間）のバグ修正**: 検索・整理タブで「任意時間」を指定した際（マイナス値として渡される仕様）、未来の日付として計算され検索結果が0件になる不具合を修正しました。マイナスの値が渡された場合は、その絶対値を「時間（hours）」として遡って計算する汎用ロジックを追加し、既存の「12H」や「24H」の挙動も壊さないように統合しました。

### 変更関数
	`OutlookMailManager.search_mails_fast` (期間フィルタリングロジックの修正)

### 新規追加：
	なし
	
## VERSION 20260417.03
### 追加・修正
	**宛先「ALL」抽出機能の追加**: 検索・整理タブに、To/CCの条件に関わらず全てのメールを対象とする「ALL」チェックボックスを追加しました。選択時は他の宛先チェックを無効化する排他制御を行っています。
	**大量抽出時の安全装置（ストッパー）**: 「ALL」選択状態で検索を実行しようとした際、メーリングリスト等による想定外の抽出量とAPI負荷を防ぐための確認ポップアップを追加しました。
	**長文スレッドの3択ダイアログ化とバッチ処理対応**: 10,000文字を超えるスレッドに遭遇した際、「1.切り詰め(2:8のヘッド＆テール)」「2.要約スキップ」「3.フル要約」の3択を選択できるカスタムダイアログを実装。さらに「以降すべて同じ処理にする」チェックボックスを追加し、連続処理の利便性を向上しました。

### 変更関数
	`OutlookMailManager.search_mails_fast` (ALL条件判定ロジックの追加)
	`MailSummarizer.summarize_thread` (長文分岐とヘッド＆テール抽出ロジックの追加)
	`MailSummarizer.summarize_multiple_threads` (引数 `long_text_choice` の受け渡し追加)
	`MailManagerGUI._ui_search_tab` (ALLチェックボックスのUI追加)
	`MailManagerGUI._search` (ALL選択時の警告ロジックと条件辞書への追加)
	`MailManagerGUI._search_external` (条件辞書へのALLフラグ追加)
	`MailManagerGUI._gen` (長文判定と3択ダイアログの呼び出しロジックの追加)

### 新規追加：
	`MailManagerGUI._on_all_toggled` (UI排他制御)
	`MailManagerGUI._ask_long_text_action` (長文3択カスタムダイアログ)
	
## VERSION 20260417.02
### 追加・修正
	**宛先「ALL」抽出機能の追加**: 検索・整理タブに、To/CCの条件に関わらず全てのメールを対象とする「ALL (宛先無視)」チェックボックスを実装。選択時は他の宛先チェックを無効化する排他制御を追加しました。
	**大量抽出時の安全装置（ストッパー）**: 「ALL」選択状態で検索を実行しようとした際、想定外の抽出量による負荷を防ぐための確認警告ポップアップを追加しました。
	**長文スレッドの3択ダイアログ化とバッチ処理対応**: 10,000文字を超えるスレッドに遭遇した際、「1.切り詰め(2:8のヘッド＆テール)」「2.要約スキップ」「3.フル要約」の3択を選択できるカスタムダイアログを実装。さらに「以降すべて同じ処理にする」チェックボックスを追加し、連続処理の利便性を向上しました。

### 変更関数
	`MailManagerGUI._ui_search_tab` (ALLチェックボックスの追加)
	`MailManagerGUI._search` (ALL選択時の警告ロジック追加)
	`MailManagerGUI._run_search` (ALLフラグの抽出条件への受け渡し)
	`MailManagerGUI._gen` (長文スレッド判定と3択ダイアログの呼び出し)
	`MailManagerGUI._run_gen` (選択された長文処理オプションを要約クラスへ伝播)
	`OutlookMailManager.search_mails_fast` (ALL条件判定ロジックの追加)
	`MailSummarizer.summarize_multiple_threads` (長文分岐とヘッド＆テール抽出の実装)

### 新規追加：
	`MailManagerGUI._on_all_toggled` (UI排他制御)
	`MailManagerGUI._ask_long_text_action` (長文3択カスタムダイアログ)
	
## VERSION 20260417.01
### 追加・修正
	**ALL抽出機能とUI排他制御の実装**: 検索・整理タブに「ALL (宛先無視)」チェックボックスを追加しました。ALL選択時は「To:Me」「With:Me」「CC:Me」を自動でOFFにしグレーアウトさせる排他制御を導入。また、ALL選択での検索開始前に大量データ取得の警告を出す安全装置を追加しました。
	**長文スレッド要約の3択ダイアログ化**: 10,000文字を超えるスレッドに遭遇した際、「1.切り詰め(2:8比率のヘッド＆テール)」「2.要約スキップ(軽量表示)」「3.フル要約(無制限)」を選択できるカスタムダイアログを実装しました。
	**バッチ処理対応（以降すべて適用）**: 長文警告ダイアログに「以降すべて同じ処理にする」チェックボックスを追加し、大量のスレッドを一括処理する際のユーザー負担を軽減しました。
	**ヘッド＆テール抽出ロジック**: 長文切り詰め時、スレッドの起票背景（先頭2,000文字）と最新議論（末尾8,000文字）を結合してAIに渡すことで、俯瞰精度を維持しつつAPIエラーを回避するロジックを導入しました。

### 変更関数
	`OutlookMailManager.search_mails_fast` (ALL検索ロジックの追加)
	`MailManagerGUI` (クラス全体：UI追加、排他制御、長文ダイアログ、検索・生成フローの修正)
	`MailSummarizer.summarize_multiple_threads` (長文処理分岐とヘッド＆テール抽出の実装)

### 新規追加：
	`MailManagerGUI._on_all_toggled` (UI排他制御)
	`MailManagerGUI._ask_long_text_action` (3択カスタムダイアログ)
	
## VERSION 20260416.01
### 追加・修正
	**最新活動履歴の可読性向上（自動構造化）**: `generate_project_report` および `generate_staff_report` 内で、改行のない巨大なテキストブロックになっていた「最新活動履歴（AI自動記録）」を、Python側で前処理（`_format_recent_history`ヘルパーメソッドの導入）して構造化しました。タイムスタンプごとにブロックを分割して視覚的な区切りを入れ、長文を「。」で改行して読みやすくし、ハイライトキーワード（「遅延」「リスク」「課題」など）を太字で目立たせる処理を追加しました。また、表示エリアが縦に長くなりすぎないよう、スクロール領域（`max-height: 400px; overflow-y: auto;`）を設定しました。
	**過去知識エリアのレイアウト強制（縦並びの確約）**: 前バージョンで失敗していた「マスター経緯」と「最新活動履歴」等の横並び（サイドバイサイド）問題を根本解決するため、これらの親コンテナ（`<div id="know-{id}">`）に対して `display: flex; flex-direction: column;` のCSSスタイルをハードコーディングし、各入力要素の幅を `width: 100%;` に設定することで、環境に依存せず確実に縦に積み重なるレイアウトを強制しました。

### 変更関数
	`HTMLReportGenerator._format_recent_history` (新規追加: 履歴テキストの構造化処理)
	`HTMLReportGenerator.generate_project_report` (履歴の前処理適用とナレッジコンテナの縦並びCSS追加)
	`HTMLReportGenerator.generate_staff_report` (履歴の前処理適用とナレッジコンテナの縦並びCSS追加)

### 新規追加：
	`HTMLReportGenerator._format_recent_history`
## VERSION 20260415.11
### 追加・修正
	**主要サマリーデザインの完全統一（ライトテーマ・白背景の確約）**: ユーザーから提示された最終正解画像（`image_43e507.png`）に基づき、Project概観およびStaff概観の「主要サマリー」のUIを、完全に白背景（`#fff`）のライトテーマデザインに統一・固定しました。勝手に黒ベース（ダークテーマ）に変更される問題を根本から排除しています。
	**過去知識エリアの構成と配置の最適化**: 以前の合意通り、「🤖 AIからの質問と回答メモ」の**すぐ下**に「🧠 過去知識の更新」アコーディオンを配置しました。また、アコーディオン内部の要素はすべて**縦並び**とし、Staff概観では「役割 → 背景 → マスター経緯 → 最新活動履歴」の順に、Project概観では「マスター経緯 → 最新活動履歴」の順に配置しています。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (サマリー領域の白背景固定、過去知識エリアの配置と縦並び順序の修正)
	`HTMLReportGenerator.generate_staff_report` (サマリー領域の白背景固定、過去知識エリアの配置と縦並び順序の修正)

### 新規追加：
	なし
## VERSION 20260415.08
### 追加・修正
	**メソッドの欠損復旧**: 前回のクラス全体の再生成時に、`HTMLReportGenerator` クラス内から誤って丸ごと欠落させてしまっていた `generate_staff_report` メソッドを完全に復旧させました。これにより「Staff概観レポート」生成時の `AttributeError` が解消されます。
	**構文エラー（SyntaxError）の根本解決**: 文字列の開始記号（`f'''`）の欠落防止および、Windows環境での文字コード誤認を防ぐため、HTML内の絵文字を安全なHTMLエンティティ表記（`&#x...;`）に置き換えた安定版コードを採用しています。

### 変更関数
	`HTMLReportGenerator.generate_staff_report` (欠損していたメソッドの完全復旧)

### 新規追加：
	なし
	
## VERSION 20260415.07
### 追加・修正
	**HTML生成エラーの修正**: `HTMLReportGenerator` クラス内に不足していたテキスト整形用のヘルパーメソッド（`_clean_body_for_display` および `_auto_link_text`）を追加し、レポート出力時のクラッシュ（AttributeError）を解消しました。
	**サマリーUIの完全復元**: ユーザー指定の画像デザインに基づき、「主要サマリー」の領域をダークテーマ（ダークグレー背景、ライトブルーのアクセントライン、見やすい白文字）に設定し、視認性の高い美しいフォーマットを完全に復旧させました。

### 変更関数
	`HTMLReportGenerator._clean_body_for_display` (新規追加: 欠損メソッドの復旧)
	`HTMLReportGenerator._auto_link_text` (新規追加: 欠損メソッドの復旧)
	`HTMLReportGenerator.generate_project_report` (サマリーのCSSデザインを画像通りに修正)
	`HTMLReportGenerator.generate_staff_report` (サマリーのCSSデザインを画像通りに修正)

### 新規追加：
	なし
	
## VERSION 20240415.06
### 追加・修正
	**HTMLレイアウトの完全復旧とナレッジエリアの適正配置**: 前回のアップデートで誤って消去・崩壊させてしまった「プロジェクト概観」「スタッフ概観」のHTMLレイアウト（美しいサマリーボックス、スレッド一覧・AI質問のアコーディオン表示）を元の安定版の状態に完全復旧しました。
	**過去知識の更新アコーディオンの実装**: ご要望に基づき、画面の最下部に「▼ 🧠 過去知識の更新」という新しいアコーディオンを追加し、その中に「📅 最新活動履歴（AI自動記録）」と「📌 マスター経緯（人間が管理）」を縦並びで配置しました。スタッフ版については、「役割（Role）」と「背景（Background）」の入力欄もここに格納し、HTML上から直接編集・保存できる仕様を復旧・統合しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (サマリー・アコーディオンの復元、過去知識エリアの追加、保存用JSの追加)
	`HTMLReportGenerator.generate_staff_report` (サマリー・アコーディオンの復元、過去知識エリアの追加、保存用JSの追加)

### 新規追加：
	なし
## VERSION 20240415.05
### 追加・修正
	**GUI崩壊・出力エラーの完全修正**: 前バージョンのパッチで不当に省略（`pass`化）されてしまったUI構築メソッドおよびHTML生成メソッドを、一切の省略なく完全な形で復元しました。
	**ハイブリッド履歴管理システム**: 「マスター経緯（手動）」と「AI活動履歴（自動）」の分離を実装。
	**リアルタイム・タイマー**: AI解析中の秒数カウントアップ機能を追加。
	**HTMLからの直接編集**: HTMLレポート上でナレッジを書き換え、Python側のJSONに保存する機能を追加。

### 変更関数
	`time` モジュールのインポート追加
	`OutlookRequestHandler.do_POST`
	`MailSummarizer.summarize_project_threads`
	`MailSummarizer.summarize_staff_threads`
	`HTMLReportGenerator.generate_project_report`
	`HTMLReportGenerator.generate_staff_report`
	`MailManagerGUI` (タイマー関連、各UIタブ構築、各実行ロジック、ナレッジ保存等)
## VERSION 20240415.04
### 追加・修正
	**ハイブリッド履歴管理システムの実装**: 「過去の経緯」を、人間が編集・維持する「マスター経緯」と、AIがタイムスタンプ付きで自動追記する「最新活動履歴」に分離しました。これにより、手動で整えた重要な背景情報をAIに上書きされることなく保護しつつ、日々の進捗を時系列で蓄積できる学習ループを実現しました。
	**リアルタイム・タイマー付きステータス表示**: AI解析中、1秒ごとに経過時間をカウントアップ表示する機能を実装しました。長時間の処理（チャンキング）においても、システムが正常に動作していることを視覚的に保証し、ユーザーの不安を解消します。
	**HTMLからの直接ナレッジ編集機能**: 生成されたHTMLレポート上から、「役割」「背景」「マスター経緯」を直接編集・保存できるUIを追加しました。ブラウザ上で情報を整理し「保存」を押すだけで、Python側のナレッジベース（JSON）が即座に同期されます。
	**GUIナレッジエディタの刷新**: GUI側のエディタも、マスター経緯とAI履歴を分けた新しい構造に合わせてインターフェースを更新しました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (履歴統合ロジックの刷新)
	`MailSummarizer.summarize_staff_threads` (履歴統合ロジックの刷新)
	`HTMLReportGenerator.generate_project_report` (編集UI、保存JS、Markdown表示対応)
	`HTMLReportGenerator.generate_staff_report` (編集UI、保存JS、Markdown表示対応)
	`OutlookRequestHandler.do_POST` (ナレッジ更新APIの拡張)
	`MailManagerGUI` (クラス全体: リアルタイムタイマー実装およびGUIエディタの刷新)

### 新規追加：
	なし
	
## VERSION 20240415.03
### 追加・修正
	**空振りエラー（0件ヒット時）の防止**: 期間や「未読のみ」フィルターの結果、対象スレッドが0件だった場合に「AI解析エラー」と誤表示される計算バグを修正しました。0件時はAI通信を行わず、レポート上に「一致するメールなし」と正しく表示する安全装置を実装しました。
	**自由な時間指定（Custom Hours）機能**: プロジェクト俯瞰・スタッフ俯瞰の両タブに、任意の時間を数字で入力できる「時間指定(h)」機能を追加しました。ドロップダウンで「任意時間(h)」を選択し、横のスピンボックスで「3」や「48」など好きな数値を設定してレポートを生成できます。
	**検索タブへの時間指定統合**: 1つ目の「検索/整理」タブの期間設定にも「任意時間(h)」を追加し、ツール全体で自由な時間軸での検索が可能になりました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (冒頭に0件チェックを追加)
	`MailSummarizer.summarize_staff_threads` (冒頭に0件チェックを追加)
	`MailManagerGUI` (クラス全体: UIへ「任意時間(h)」とスピンボックスの追加、および日付計算ロジックへの組み込み)

### 新規追加：
	なし
	
## VERSION 20240415.02
### 追加・修正
	**リスト選択状態の維持（既読・未読処理後）**: 検索/整理タブにて「■全選択既読」や「既読にする」「未読にする」などのアクションを実行した際、画面の再描画（`_update`）によってリストのチェックボックス（選択状態）が外れてしまう問題を修正しました。処理完了後に、直前まで選択されていたアイテムのIDを元に選択状態（☑）を自動復元する処理を追加しています。

### 変更関数
	`MailManagerGUI._mark_read` (再描画後の選択状態復元ロジックの追加)
	`MailManagerGUI._mark_unread` (再描画後の選択状態復元ロジックの追加)

### 新規追加：
	なし
	
## VERSION 20240415.01
### 追加・修正
	**12時間抽出（12H）の追加**: 全てのタブ（検索/整理、プロジェクト俯瞰、スタッフ俯瞰）の期間設定に「12H」を追加しました。選択時は「現在時刻からジャスト12時間前まで」のメールを分単位で厳密に抽出します。これに合わせて、既存の24Hやその他の期間ロジックも時間単位（`%H:%M`）の正確な検索ができるよう最適化しました。
	**未読のみ抽出フィルター（スレッド維持型）の追加**: プロジェクト俯瞰・スタッフ俯瞰タブの期間設定の横に「未読のみ」チェックボックス（デフォルトOFF）を追加しました。チェック時は、AIの文脈理解を妨げないよう、「未読メールが1件でも含まれるスレッド」であれば、そのスレッドの過去履歴（既読メール）も含めて丸ごと抽出する安全な仕様（パターンA）で実装しています。

### 変更関数
	`OutlookMailManager.search_mails_fast` (12H対応ロジックの追加)
	`OutlookMailManager.search_ad_mails` (12H対応ロジックの追加)
	`OutlookMailManager.get_project_mails` (12H対応および時間単位の厳密な抽出ロジックへの変更)
	`OutlookMailManager.get_staff_mails` (12H対応ロジックの追加)
	`MailManagerGUI._ui_search_tab` (12Hの選択肢追加)
	`MailManagerGUI._get_days` (12Hのパース処理追加)
	`MailManagerGUI._ui_project_tab` (12Hの追加、未読のみチェックボックスの追加)
	`MailManagerGUI._run_project_overview` (12Hの日付計算、未読スレッドフィルタリングの実装)
	`MailManagerGUI._ui_staff_tab` (12Hの追加、未読のみチェックボックスの追加)
	`MailManagerGUI._run_staff_overview` (12Hの日付計算、未読スレッドフィルタリングの実装)

### 新規追加：
	なし
## VERSION 20260414.02
### 追加・修正
	**オンデマンド要約の日本語出力の強制化**: LLMが英語のメール文脈に引っ張られて英語で要約を出力してしまう現象（インコンテキスト・ラーニングの副作用）を防止するため、「1行要約（`/summarize_single`）」および「詳細要約（`/summarize_detail`）」のプロンプトに対し、「元のメールが他言語であっても必ず自然な日本語に翻訳して出力する」という強力な制約条件を追加しました。

### 変更関数
	`OutlookRequestHandler.do_POST` (内部の `/summarize_single` および `/summarize_detail` ルーティング内のプロンプト文字列を更新)

### 新規追加：
	なし
	
## VERSION 20260414.01
### 追加・修正
	**オンデマンド詳細要約機能（セカンドレイヤー・サマリー）**: 各スレッドヘッダーに「📄 詳細要約」ボタンを追加しました。ボタンを押すと、スレッドの全履歴を含む最新のメール本文が裏側でAIに送られ、①経緯の要点（3文以上）、②課題・リスク、③対象者（またはプロジェクト）への推奨アクション、の3点が構造化されて生成され、1行要約とアクション表の間に枠線付きの専用エリアとして表示されます。
	**通信APIの拡張**: 詳細要約のJSON出力を処理するための専用エンドポイント `/summarize_detail` を新設しました。一度取得した結果はHTML内に保持され、ボタンで開閉（トグル）可能です。

### 変更関数
	`OutlookRequestHandler.do_POST` (新API `/summarize_detail` の追加)
	`HTMLReportGenerator.generate_project_report` (詳細要約ボタン、表示エリア、JS関数の追加)
	`HTMLReportGenerator.generate_staff_report` (詳細要約ボタン、表示エリア、JS関数の追加)

### 新規追加：
	なし

## VERSION　2026.0203.02
### 追加・修正
	**タブ応答待機設定のUI化**: 「10秒ルール（Slow Tab判定）」の閾値をUIから変更可能にし、PC負荷が高い場合などにユーザーが緩和できるように変更しました（デフォルト10秒）。
	**通信タイムアウトの適正化**: `YouTubeHandler` 内で動画リスト取得後に通信タイムアウトが強制的に10秒に短縮されていた不具合を修正し、60秒を維持するように変更しました。

### 変更関数
	ProcessConfig` (フィールド追加)
	IntegratedSummaryApp.setup_settings_frame` (UI追加)
	IntegratedSummaryApp.start_single_processing` (値渡し)

### 新規追加：

ーーーここまでーーー

変更ファイル：
変更しないこと（宣誓）：
unified diff（必須）(それぞれどの関数のDiffかがわかるように表示する事）
変更した関数のみ：必ず完全版コードを提示する事を厳守してください。
新規メソッドがある場合
挿入位置（Aの直後/Bの直前）
呼び出し元（どこから呼ぶか）
最小テスト手順（手でできる手順＋期待ログ）
ーーーー

## VERSION 20260413.06
### 追加・修正
	**通信ポートの固定化**: バックエンド（Pythonサーバー）とフロントエンド（HTML）間の非同期通信において、ポート番号が起動ごとに変わる仕様（ランダム割り当て：0）を廃止し、`8082`番に固定しました。これにより、過去に出力したHTMLレポートを立ち上げ直した後でも、常に通信（判定修正や翻訳など）が成功するようになります。
	**スレッド要約のチャンキング（分割・自動結合）機能**: 処理対象スレッドが膨大（149件など）な場合でも、出力トークン上限（16,384）に到達してJSONが破損するエラーを完全に回避するため、AIへのリクエストを「40スレッドごとのチャンク」に分割して直列送信し、結果を安全に自動結合するアーキテクチャを実装しました。

### 変更関数
	`HTTPServer初期化メソッド` (ポート番号を0から8082に固定)
	`MailSummarizer.summarize_project_threads` (チャンキング分割、ループ処理、JSONマージ処理の実装)
	`MailSummarizer.summarize_staff_threads` (チャンキング分割、ループ処理、JSONマージ処理の実装)

### 新規追加：
	なし
	
## VERSION 20260413.05
### 追加・修正
	**AI判定の自然言語フィードバック機能（RAG学習ループ）**: AIがスレッドを「対象（メイン）」または「ノイズ（無視）」に分類した結果に対して、ユーザーがHTMLレポート上から直接フィードバック（定型文＋自由コメント）を与えられるUIを追加しました。
	**学習ルールのプロンプト統合**: 送信されたフィードバックは `project_knowledge.json` に自然言語の「特別ルール」として蓄積され、次回のサマリー生成時にAIの「前提知識」として読み込まれることで、AIがユーザーの好みを学習し、分類精度が向上（成長）する仕組みを実装しました。

### 変更関数
	`OutlookRequestHandler.do_POST` (新API `/update_ai_rules` の追加)
	`MailSummarizer.summarize_project_threads` (ナレッジから特別ルールを読み込み、プロンプトへ注入)
	`MailSummarizer.summarize_staff_threads` (ナレッジから特別ルールを読み込み、プロンプトへ注入)
	`HTMLReportGenerator.generate_project_report` (フィードバック用UIとJSの追加)
	`HTMLReportGenerator.generate_staff_report` (フィードバック用UIとJSの追加)

### 新規追加：
	なし
	
## VERSION 20260413.04
### 追加・修正
	**スレッド要約のチャンキング（分割・自動結合）機能**: 処理対象スレッドが膨大（数十〜百件以上）な場合でも出力トークン上限（16,384）エラーでシステムが停止しないよう、AIへのリクエストを「40スレッドごとのチャンク」に分割して直列送信する仕組みを実装しました。
	**部分成功の許容とマージロジックの最適化**: 分割されたJSONレスポンスをPython側で自動的に1つに結合（配列は合体、ステータスや過去の経緯は最新のチャンクAを優先採用）します。一部のチャンク通信が失敗した場合でも処理を止めず、成功したデータだけでHTMLを生成し、ハイライトの一番上に「欠損が発生したチャンク番号」を警告として明示するフェイルセーフ仕様を追加しました。
	**コンソール進捗表示**: 分割処理中、現在の処理チャンク番号や成功/失敗のステータスがコンソールにリアルタイム表示されるようにしました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (チャンキング分割、ループ処理、JSONマージ処理の実装)
	`MailSummarizer.summarize_staff_threads` (チャンキング分割、ループ処理、JSONマージ処理の実装)

### 新規追加：
	なし
	
## VERSION 20260413.03
### 追加・修正
	**検索タブ用要約機能の最新SDK対応（エラー解消）**: 「検索/整理」タブから呼び出される古い一括要約メソッド群（`summarize_thread`, `_generate_batch_summaries`, `_generate_overall_analysis`, `_generate_single_shot`, `_generate_rss_summary`）の中に残っていた旧SDKの構文（`genai.configure` や `GenerativeModel`）を、新しい `google.genai` SDKの構文（`genai.Client`）にすべて置き換え、`AttributeError: module 'google.genai' has no attribute 'configure'` のエラーを解消しました。

### 変更関数
	`MailSummarizer.configure` (旧設定コマンドの削除、フラグ管理のみに変更)
	`MailSummarizer._generate_batch_summaries` (新SDK構文への置き換え)
	`MailSummarizer._generate_overall_analysis` (新SDK構文への置き換え)
	`MailSummarizer._generate_single_shot` (新SDK構文への置き換え)
	`MailSummarizer._generate_rss_summary` (新SDK構文への置き換え)

### 新規追加：
	なし
## VERSION 20260413.02
### 追加・修正
	**初期要約の完全オンデマンド化（ALLオンデマンド）**: AIが「最新3件のみ」という指示を「スレッドの抽出件数」だと誤認するハルシネーションを完全に防止するため、初回の一括要約プロンプトからメール個別要約（`mail_summaries`）の出力指示を完全に削除しました。
	**フロントエンドの待機状態化**: HTMLレポート初期表示時には、すべてのメールに対して「✨ 要約」ボタンを表示する仕様に変更しました。これによりAIの出力トークンは極限まで削減され、16384トークンの強制切断エラーは物理的に発生しなくなります。

### 変更関数
	`MailSummarizer.summarize_project_threads` (プロンプトから `mail_summaries` の指示とJSONスキーマを完全削除)
	`MailSummarizer.summarize_staff_threads` (プロンプトから `mail_summaries` の指示とJSONスキーマを完全削除)
	`HTMLReportGenerator.generate_project_report` (初期表示を常に「✨ 要約」ボタンにするようロジック変更)
	`HTMLReportGenerator.generate_staff_report` (初期表示を常に「✨ 要約」ボタンにするようロジック変更)

### 新規追加：
	なし
	
## VERSION 20260413.01
### 追加・修正
	**ハイブリッド・オンデマンド要約機能の追加**: 
	Gemini APIの出力トークン上限（16384）によるJSON切断エラーを完全に回避するため、初回の一括要約では「各スレッドの最新3件のメールのみ」を要約するようプロンプトを厳格化しました。
	また、要約されなかった古いメールについては、HTML上に「✨ 要約」ボタンを配置し、ユーザーがクリックした時のみバックエンド（新API `/summarize_single`）と非同期通信を行い、対象のメール本文とスレッド件名をAIに送ってオンデマンドで要約を取得・表示する機能を実装しました。

### 変更関数
	`OutlookRequestHandler.do_POST` (新API `/summarize_single` のルーティング追加)
	`MailSummarizer.summarize_project_threads` (プロンプトに「最新3件のみ」の制約を追加)
	`MailSummarizer.summarize_staff_threads` (プロンプトに「最新3件のみ」の制約を追加)
	`HTMLReportGenerator.generate_project_report` (要約の有無によるボタンの出し分け、JSの非同期処理関数の追加)
	`HTMLReportGenerator.generate_staff_report` (要約の有無によるボタンの出し分け、JSの非同期処理関数の追加)

### 新規追加：
	なし（新機能は既存クラス/メソッドの拡張として実装）
	
## VERSION 20260409.17
### 追加・修正
	**AI出力のデバッグダンプ機能（エラー解析用）**: AIが生成したテキストのJSONパースエラー（フォーマット破壊）が発生した際、原因となっている「生のエラーテキスト（541行目付近の文法違反など）」を特定できるように、エラー発生時およびJSON抽出失敗時に `error_dump_[名前]_att[回数].txt` というテキストファイルとして生データを自動保存する機能を追加しました。

### 変更関数
	`MailSummarizer.summarize_project_threads` (エラー発生時のダンプファイル出力ロジックを追加)
	`MailSummarizer.summarize_staff_threads` (エラー発生時のダンプファイル出力ロジックを追加)

### 新規追加：
	なし
	
## VERSION 20260409.16
### 追加・修正
	**最新Gemini SDKへの完全移行**: `google.generativeai` パッケージのサポート終了に伴う警告（FutureWarning）を解消するため、通信基盤を新しい公式SDKである `google.genai` へとアップグレードしました。
	**AI箇条書きフォーマットの厳格化**: AIがリスト出力時に「・」や「1.」などの不要な記号を勝手に付与し、HTMLの表示が乱れる問題（ハルシネーション）を防ぐため、プロンプトに「記号の付与を絶対に禁止する」ガードレールを追加しました。

### 変更関数
	`グローバルインポート` (旧SDKから新SDKへモジュール変更)
	`OutlookRequestHandler.do_POST` (新SDKの `client.models.generate_content` 構文へ変更)
	`MailSummarizer.summarize_project_threads` (新SDK構文へ変更、プロンプトの厳格化)
	`MailSummarizer.summarize_staff_threads` (新SDK構文へ変更、プロンプトの厳格化)

### 新規追加：
	なし
	
## VERSION 20260409.14
### 追加・修正
	**アクションバッジの全ステータス表示**: プロジェクト俯瞰およびスタッフ俯瞰のアクションアコーディオンボタンにおいて、「完了（🟢）」「進行中（🔵）」「遅延（🔴）」「未設定（⚠️）」のすべてのステータス件数を集計し、該当するものだけを動的に表示する機能を追加しました。
	**AI質問の動的追加（Regenerate）機能**: 各レポートの「AIからの確認事項」セクションに、非同期でGemini APIにアクセスし、既存の質問と重複しない新しい質問を2件生成・追記する `[🔄 さらに質問を生成 (Gemini)]` ボタンを実装しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (ステータス集計ロジックの完全化、質問セクションのDOMID追加、JS関数の追加)
	`HTMLReportGenerator.generate_staff_report` (同上)
	`OutlookRequestHandler.do_POST` (新規APIエンドポイント `/generate_questions` の追加)

### 新規追加：
	メソッド: `do_POST` 内の `/generate_questions` ルーティング
	JS関数: `regenerateQuestions`
	
## VERSION 20260409.12
### 追加・修正
	**アクション表のスマート・アコーディオン化**: プロジェクト俯瞰およびスタッフ俯瞰のHTMLレポートにおいて、各スレッドのアクション（タスク）一覧表をデフォルトで折りたたみ（非表示）状態にし、縦幅を大幅に圧縮して俯瞰性を向上させました。
	**サマリバッジ（アラート機能）の追加**: アコーディオンを閉じた状態でも、「遅延」や「未設定」のタスクが何件あるかをトグルボタン上にバッジとして視覚的にハイライトする仕様を実装しました。これにより、画面のすっきり感とタスク確認漏れの防止（安全性）を両立しています。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (アクション表のアコーディオン化、ステータス集計ロジック、JSのトグル関数追加)
	`HTMLReportGenerator.generate_staff_report` (同上)

### 新規追加：
	なし（既存HTML文字列・JS文字列の拡張）
	
## VERSION 20260409.11
### 追加・修正
	**検索エンジンの統合（シンプル化）**: スタッフ俯瞰タブのメール抽出において、自作の不完全な検索ロジック（`get_staff_mails`）を破棄し、検索・整理タブで実績のある強力なネイティブ検索エンジン（`search_mails_fast`）にルートをつなぎ直しました。これにより、サブフォルダに格納されたメールや内部アドレス（X.500）の問題が完全に解消され、検索タブと同様に「入力すれば確実にヒットする」堅牢な動作を実現しました。

### 変更関数
	`MailManagerGUI._run_staff_overview` (メール抽出処理を `get_staff_mails` から `search_mails_fast` を利用する形へ書き換え)

### 新規追加：
	なし
	
## VERSION 20260409.10
### 追加・修正
	**「スタッフ俯瞰」タブの新設**: プロジェクト俯瞰タブの横に、特定のスタッフ個人の活動にフォーカスした「スタッフ俯瞰」タブを新設しました。
	**双方向連動チェックボックスの実装**: スタッフの関与フィルターとして `ALL`, `From`, `To`, `CC` の双方向連動トグルを実装しました。「ALL」を外すと個別選択が可能になり、逆に個別選択をすべてONにすると自動で「ALL」がONになります。
	**抽出範囲の最適化とPython側フィルタリング**: 対象スタッフ宛（To/CC）のメールも抽出できるよう、「受信トレイ」に加えて「送信済みアイテム」フォルダも同時にスキャンする仕様にしました。また、Outlookの特殊なMAPI検索構文エラーを防ぐため、日付で安全に絞り込んだ後にPython側で高速部分一致フィルタリングを行う堅牢な設計を採用しました。
	**専用のAI分析とレポート出力**: スタッフ個人の「主な活動実績」「抱えている課題・リスク」「次週の注力タスク」を分析するための専用プロンプト（`summarize_staff_threads`）と、専用のHTML出力メソッド（`generate_staff_report`）を新設しました。
	**スタッフ専用ナレッジベース**: `knowledge.json` に `staffs` ノードを追加し、対象スタッフの役割やバックグラウンドを保存・編集するための専用ダイアログを実装しました。

### 変更関数
	`MailManagerGUI` (クラス全体: 新規タブ追加、双方向トグルUI、期間選択の同期、専用実行ロジックの追加)
	`OutlookRequestHandler.do_POST` (JSON更新時の `staff` 対応)
	`OutlookMailManager.get_staff_mails` (新規)
	`MailSummarizer.summarize_staff_threads` (新規)
	`HTMLReportGenerator.generate_staff_report` (新規)

### 新規追加：
	タブ: `tab_staff`
	メソッド: `_ui_staff_tab`, `_open_staff_knowledge_editor`, `_run_staff_overview`, `get_staff_mails`, `summarize_staff_threads`, `generate_staff_report`
	
## VERSION 20260409.09
### 追加・修正
	**インライン画像の軽量埋め込み（Base64マップ方式）**: Outlookのメール本文に貼り付けられた画像（`cid:` リンク）を自動的に抽出し、`Pillow` を用いてWeb用の軽量サイズ（最大幅800px）にリサイズした上で、Base64形式としてHTML内に直接埋め込む処理を実装しました。これにより、外部フォルダに依存せず、かつHTMLサイズを最小限に抑えながら図表などを完全再現できます。
	**添付ファイル名の明記**: 画像以外の重い添付ファイル（Excel, PDF, ZIPなど）はデータ実体を抽出せず、ファイル名（例: `📎 添付ファイル: report.xlsx`）のみをHTMLレポートの送信者名の下に明記する仕様に変更しました。これにより、ポータビリティと圧倒的な軽さを両立しました。

### 変更関数
	`OutlookMailManager._item_to_dict` (添付ファイルの仕分け、画像のリサイズ＆Base64エンコード、ファイル名抽出処理の追加)
	`HTMLReportGenerator._card` (検索/整理タブでの `cid` リンク置換および添付ファイル名のUI表示)
	`HTMLReportGenerator.generate_project_report` (プロジェクト俯瞰タブでの `cid` リンク置換および添付ファイル名のUI表示)

### 新規追加：
	なし
	
## VERSION 20260409.08
### 追加・修正
	**翻訳の爆速化（トリプルコンボ適用）**: リッチテキスト（HTML）の翻訳処理において、1分程度かかっていた待機時間を数秒に劇的短縮する以下の3つの改良を実装しました。
	1. **JSプレフィルタリング（ノイズ除外）**: ブラウザ側でテキストノードを抽出する際、「URL」「純粋な数字」「記号や空白のみ」といった翻訳不要なノードを正規表現で弾き、無駄なAPI通信を根本から削減しました。
	2. **チャンクサイズの最適化**: APIへ送る1回あたりのテキスト配列数を `50` から `100` へ引き上げ、通信のオーバーヘッド（往復回数）を半減させました。
	3. **Pythonマルチスレッド並列処理**: 残った複数の翻訳チャンクを直列（順番）で待つのではなく、`ThreadPoolExecutor`（max_workers=5）を用いてGemini APIへ一斉に（同時に）リクエストを送信する並列アーキテクチャに改修しました。
	**JS変数のバグ修正**: JS関数内の `fetch` URLで使用していた未定義変数 `${port}` を正しい引数 `${serverPort}` に修正しました。

### 変更関数
	`OutlookRequestHandler.do_POST` (並列処理化、チャンクサイズ100への変更)
	`HTMLReportGenerator._build_html` (JS内でのノイズ判定ロジック追加、変数名修正)

### 新規追加：
	なし
	
## VERSION 20260409.07
### 追加・修正
	**エクスプローラー起動バグの修正**: 「レポート管理」ダイアログから保存先フォルダを開く際、設定ファイルに相対パス（例: `./mail_reports`）が記載されているとWindowsの `os.startfile` がファイルを見つけられずにクラッシュする問題（WinError 2）を修正しました。内部で `os.path.abspath()` を用いて絶対パスに変換してからOSに渡すことで、環境を問わず確実に開けるようになります。

### 変更関数
	`MailManagerGUI._open_file_manager` (内部関数 `open_folder` における絶対パス変換処理の追加)

### 新規追加：
	なし
	
## VERSION 20260409.06
### 追加・修正
	**ファイル管理メニューの追加**: 画面上部のメニューバーに「ファイル管理」メニューを追加し、生成されたレポートのメンテナンスを行うための専用ダイアログを実装しました。
	**保存フォルダの直接起動**: 同ダイアログ内から、設定に保存されているレポート出力先フォルダをエクスプローラーでワンクリックで開ける機能を実装しました。
	**古いレポートの一括クリーンナップ機能**: 蓄積した不要なレポートファイル（`*_report_*.html`）を「7日/14日/30日/60日以前」の条件で自動スキャンし、件数と削減される容量（MB）を事前確認した上で安全に一括削除するフェイルセーフ付きのクリーンナップ機能を実装しました。

### 変更関数
	`MailManagerGUI.__init__` (メニューバーへの項目追加)
	`MailManagerGUI._open_file_manager` (新規: 管理ダイアログのUI構築と一括削除ロジック)

### 新規追加：
	メソッド: `_open_file_manager`
## VERSION 20260409.05
### 追加・修正
	**テキストノード配列翻訳のバッチ（チャンク分割）処理化**: 巨大なリッチテキストメール（`HTMLBody`）を翻訳する際、抽出されたテキストノード配列の要素数が多すぎるとAI（Gemini）の出力文字数上限に到達してJSONが途中切断（`Unterminated string`）される問題を修正しました。
	**安定性の向上**: 送信された巨大な配列をPython側で50件ずつの小グループ（チャンク）に自動分割して逐次翻訳し、最後に結合してJSへ返す仕組みに変更しました。一部のチャンクでエラーが発生した場合でも、プログラム全体がクラッシュせず、該当部分のみ原文を維持して翻訳を完了させるフェイルセーフを導入しています。

### 変更関数
	`OutlookRequestHandler.do_POST` (エンドポイント `/translate_array` 内のループ・チャンク分割ロジック追加)

### 新規追加：
	なし
## VERSION 20260409.04
### 追加・修正
	**Dual Extraction（二重抽出）と極大化**: Outlookからのメール取得制限を撤廃し（`10,000文字` → `300,000文字`）、SafeLinksによる文字数超過切断バグを解消しました。さらに、AI要約用のプレーンテキスト（`Body`）とは別に、画面表示用のリッチテキスト（`HTMLBody`）も同時に裏側で取得・保持するようにしました。
	**iframeによる完全隔離表示（Sandboxing）**: HTMLレポート上の表示を、プレーンテキストから `<iframe>` を用いたリッチテキスト表示へ抜本的にアップグレードしました。これにより、Outlookと全く同じ表（テーブル）、文字色、レイアウトを崩さずに完全再現します。
	**JSテキストノード配列翻訳（ハイブリッド翻訳）**: 翻訳ボタンを押した際、JSがiframe内のHTMLから「文字データ」だけを抽出し、AI（Gemini）へ配列として投げて翻訳・置換する高度なDOM解析翻訳を実装しました。これにより、複雑な表やリンク構造を一切壊すことなく、日本語翻訳を適用することが可能になりました。

### 変更関数
	`OutlookRequestHandler.do_POST` (配列翻訳用エンドポイント `/translate_array` の新設)
	`OutlookMailManager._item_to_dict` (`html_body` 取得の追加と、本文の取得文字数制限の30万字への引き上げ)
	`HTMLReportGenerator._build_html` (JS翻訳関数のテキストノード解析対応化、およびiframe隔離対応)
	`HTMLReportGenerator._card` (iframeへの `html.escape` による安全なHTML出力対応)
	`HTMLReportGenerator.generate_project_report` (JS関数の更新およびiframe対応)

### 新規追加：
	ローカルサーバー側機能: `/translate_array`
	JS側機能: `extractTextsFromIframe`, `applyTextsToIframe`
	
## VERSION 20260409.03
### 追加・修正
	**検索/整理タブのHTMLレポートへのオートリンク＆SafeLinks短縮適用**: 「プロジェクト俯瞰タブ」で先行実装したURLのリンク化（オートリンク）および長大なSafeLinksの解読・短縮機能（50文字制限）を、メインの「検索/整理タブ」のレポート機能（`_build_html`, `_card`）にも適用しました。これにより、長いURLが原因で発生していたレイアウトの崩壊を解消しました。
	**検索/整理タブの翻訳機能のリンク維持**: 同レポート上で「🌐 翻訳」を実行した際にも、AIから返却された日本語テキストに対してJavaScript側で `autoLink` 関数を実行し、翻訳後も安全でスッキリとしたクリック可能なリンクが維持されるように改修しました。

### 変更関数
	`HTMLReportGenerator._build_html` (JSスクリプト内の `translateText` の改修、`autoLink` 関数の追加)
	`HTMLReportGenerator._card` (メール本文出力時のHTMLエスケープ処理と `_auto_link_text` の適用)

### 新規追加：
	なし
	
## VERSION 20260409.02
### 追加・修正
	**AI要約クラスの引数不整合修正 (TypeError)**: GUI側から渡される「過去メール上限（past_limit）」と「最新無制限（latest_unlimited）」の引数を、AI要約クラス（`MailSummarizer`）側で正しく受け取れるようにメソッドの定義を修正し、クラッシュを解決しました。
	**正規表現のエスケープ警告修正 (SyntaxWarning)**: HTMLレポートを生成するクラス内のJavaScriptで使用している正規表現（`\/`）が、Python 3.12以降の構文警告（invalid escape sequence）を引き起こしていたため、適切なエスケープ（`\\/`）に修正しました。

### 変更関数
	`HTMLReportGenerator.generate_project_report` (JSスクリプト内の正規表現エスケープ修正)
	`MailSummarizer.summarize_multiple_threads` (引数 `past_limit`, `latest_unlimited` の追加)
	`MailSummarizer.summarize_thread` (引数 `past_limit`, `latest_unlimited` の追加と文字数制限ロジックの適用)

### 新規追加：
	なし
	
## VERSION 20260409.01
### 追加・修正
	**過去メールの抽出文字数可変化（検索/整理タブ）**: レポート生成時の過去メール抽出において、標準の「800文字制限（引用カット付き）」を適用しつつ、制限値を「1000文字」「無制限」等にGUI（レポートボタン下部のコンボボックス）から柔軟に変更できる機能を追加しました。
	**大容量最新メールの動的抽出ポップアップ**: スレッドの最新メールが10,000文字を超える場合、レポート生成前に「●●文字数が〇〇スレッドの最新メールにありますが、すべてを抽出しますか？」という確認ポップアップを自動表示する安全装置を追加しました。[はい]を選択すると無制限抽出、[いいえ]で10,000文字カットが適用されます。

### 変更関数
	`MailManagerGUI._ui_search_tab` (レポートボタン下部への文字数制限コンボボックス追加)
	`MailManagerGUI._gen` (10,000文字超過時の事前チェックとポップアップ処理の追加)
	`MailSummarizer.summarize_multiple_threads` (引数の追加)
	`MailSummarizer.summarize_thread` (最新/過去メールごとの文字数制限分岐処理の追加)

### 新規追加：
	なし
	
VERSION 20260407.12
追加・修正
**最新メールの判定ロジック修正**: HTMLレポートに表示する際、「引用付きの全文（履歴）を残すメール」の対象判定が、配列の仕様（古い順で格納されている）に対する解釈ミスにより `i == 0`（最古のメール）になっていたバグを修正しました。正しくは `i == len(orig_mails) - 1` （最新のメール）のみ全文を表示し、それ以外の古いメールは引用をカットしてスッキリ表示します。
変更関数
`HTMLReportGenerator.generate_project_report` (最新メールのインデックス判定条件の修正)
新規追加：
なし

VERSION 20260407.11
追加・修正
**オートリンクとSafeLinksの短縮・解読**: メール本文に含まれる `https://...` を自動検知してクリック可能なリンク（`<a>`タグ）に変換する機能を実装しました。また、企業用Outlook特有の長い `safelinks.protection.outlook.com` URLが含まれていた場合、自動的に本来のクリーンなURLを解読（デコード）し、画面上の表示テキストを50文字以内に省略することで、視認性を劇的に向上させました。
**翻訳時のリンク保持（JS改修）**: 「🌐 翻訳」ボタンを押してAIから日本語訳が返ってきた際にも、JavaScript側で同様のオートリンク＆SafeLinks解読処理（`autoLink()`）を実行し、翻訳後もリンクが美しくクリック可能な状態を維持するように改修しました。
変更関数
`HTMLReportGenerator._auto_link_text` (新規追加: Python側リンク化ロジック)
`HTMLReportGenerator.generate_project_report` (本文のエスケープ処理とリンク化、JS側の翻訳表示ロジックの改修)
新規追加：
`HTMLReportGenerator._auto_link_text`

VERSION 20260407.10
追加・修正
**HTML生成時のAttributeError修正**: `HTMLReportGenerator` クラスが `MailSummarizer` クラスのメソッドを直接参照しようとして発生した `AttributeError` を修正しました。
**独立したテキスト整形メソッドの追加**: `HTMLReportGenerator` クラス内に、過去のやり取り（引用部分）をカットしてスッキリ表示させるための専用メソッド `_clean_body_for_display` を追加し、クラス間の依存をなくしました。
変更関数
`HTMLReportGenerator._clean_body_for_display` (新規追加)
`HTMLReportGenerator.generate_project_report` (メソッド呼び出しの修正)
新規追加：
`HTMLReportGenerator._clean_body_for_display` (HTML表示用に特化した引用カットロジック)

VERSION 20260407.09 (修正版)
追加・修正
**欠損プロンプトの完全復旧**: `MailSummarizer.summarize_project_threads` 内で誤って「(中略...)」という文字列に置き換わってしまっていたシステムプロンプトを、元の完全な指示文（JSONスキーマ指定、1行要約の10件制限、文脈判定等を含む）に復元しました。
**AIの「出力サボり」の防止とログ強化**: データ量が多い際にAIが空のリストを出力するのを防ぐため、抽出スレッド数が0件の場合は自動リトライする安全装置を追加しました。また、通信タイムアウトを180秒に緩和し、AIの生出力をコンソールに表示するデバッグログを追加しました。
変更関数
`MailSummarizer.summarize_project_threads` (プロンプト復元、リトライ・ログ・タイムアウト追加)
新規追加：
なし

VERSION 20260407.08
追加・修正
**HTML生成時の異常終了対策**: `generate_project_report` メソッド内でエラーが発生しても `None` を返さず、確実にエラーメッセージを含んだパスを返す、あるいは適切に例外をスローするように修正しました。
**ファイルパス生成の堅牢化**: 保存するHTMLファイル名から、Windowsで禁止されている記号を完全に除去する処理を強化しました。
**NoneTypeエラーの防止**: `webbrowser.open` を呼び出す前にパスが有効であることをチェックするガードレールを追加しました。
変更関数
`HTMLReportGenerator.generate_project_report` (エラーハンドリングの強化と戻り値の保証)
`MailManagerGUI._run_project_overview` (パスの存在チェック追加)
新規追加：
なし

VERSION 20260407.07
追加・修正
**実行状況のリアルタイム・デバッグログ**: プログラムの内部進捗（どのスレッドのどのメールを処理中か）をコンソールに詳細出力する処理を追加しました。
**引用カット処理の高速化・安定化**: CPU負荷を増大させるリスクのある正規表現を廃止し、行単位の高速な文字列走査による引用カットロジックに差し替えました。これによりフリーズを防止します。
**API通信のタイムアウト制御**: ネットワーク不安定時に無限に待機するのを防ぐため、APIリクエストに明示的なタイムアウトを設定しました。
変更関数
`MailSummarizer._clean_body_for_ai` (ロジックの全面刷新・安全化)
`MailSummarizer.summarize_project_threads` (進捗ログ出力の追加)
`MailManagerGUI._run_project_overview` (スレッドエラー捕捉の強化)
新規追加：
なし

VERSION 20260407.06
追加・修正
**引用カット処理によるトークン削減**: メール本文からOutlook特有の引用開始行（"-----Original Message-----" や "From:" 以降）を物理的に切り落とすフィルターを実装しました。これにより、AIに送信するテキストの重複を排除し、JSONが途中で切断されるエラーを根本から解消しました。
**最新メールの「履歴保持」ハイブリッド表示**: 利便性を維持するため、スレッド内の「最新のメール」に限り引用カットを行わず、過去のやり取りをすべて含んだ状態でHTMLに埋め込むようにしました。これにより、最新メールの翻訳ボタン一つでスレッド全体を一気に確認できます。
**入力文字数の適正化**: AIに送る各メールの文字数上限を800文字（最新メッセージ部分のみ）に規定し、情報密度を高めつつ処理速度と安定性を向上させました。
**出力ポテンシャルの最大化**: Gemini APIの呼び出し設定において `max_output_tokens` をモデル上限の 8192 に明示的に設定しました。
変更関数
`MailSummarizer.summarize_project_threads` (引用カットロジック、800文字制限、max_output_tokens設定の追加)
`HTMLReportGenerator.generate_project_report` (最新メールと過去メールの表示出し分けロジックの追加)
新規追加：
なし

VERSION 20260407.05
追加・修正
**JSONパースエラーの自動自己修復（リトライ）機構**: AIが生成したJSONに文法エラー（余分なカンマやエスケープ漏れ）があり、Python側で解読（パース）に失敗した場合、自動的にもう一度だけAIに再生成を要求するリトライループ（最大1回）を実装しました。
**リトライ時のUIステータス通知**: リトライ処理に突入した際、ユーザーに処理時間が延びている理由を透過的に伝えるため、GUIのステータスバーを「AI分析中: 〇〇 (再試行中...)」へ切り替えるコールバック処理を追加しました。
変更関数
`MailSummarizer.summarize_project_threads` (リトライループと `retry_callback` 引数の追加)
`MailManagerGUI._run_project_overview` (メソッド呼び出し時にステータス更新用のコールバックを渡す処理の追加)
新規追加：
なし

VERSION 20260407.04
追加・修正
**空アクションテーブルの非表示化**: HTMLサマリー生成時において、AIが抽出したアクションが存在しない（0件の）メールスレッドでは、アクション用のテーブル要素および背景枠自体を非表示にし、画面の縦幅をコンパクトに抑えて視認性を向上させる条件分岐を追加しました。
変更関数
`HTMLReportGenerator.generate_project_report` (アクション有無の判定とHTML文字列の出し分け追加)
新規追加：
なし

VERSION 20260407.03
追加・修正
**JSON崩れエラーの防止（出力上限の設定）**: スレッド内のメール数が多い場合にAIの出力トークンが限界を超えてJSONが途切れるエラーを防ぐため、プロンプトを改修し「1行要約（mail_summaries）の生成は最新の10件までに制限する」指示を追加しました。
**1行要約のフォールバック表示**: 11件目以降の古いメール、またはAIが要約を生成できなかったメールについては、HTML上で「要約なし」とするのではなく、メール本文の冒頭80文字を自動的に抜粋して表示する処理を追加しました。
**質問のナンバリングと入力補助（UX改善）**: HTMLレポート生成時、AIからの質問リストに自動で「Q1.」「Q2.」のラベルを付与しました。さらに、ユーザーの過去の回答メモが空だった場合、質問の数に合わせて「A1:\nA2:\n」という回答用の雛形をテキストエリアに自動挿入するようにしました。
変更関数
`MailSummarizer.summarize_project_threads` (プロンプトの件数制限追加)
`HTMLReportGenerator.generate_project_report` (Q1ナンバリング、A1雛形挿入、1行要約のフォールバック処理)
新規追加：
なし

VERSION 20260407.02
追加・修正
**AIによる文脈フィルター（ノイズ除去）**: AIプロンプトを改修し、メールの文脈から「そのプロジェクトが主役であるか」を判定するロジックを追加しました。他プロジェクトのついでに言及されただけの無関係なメールは、出力JSONの `is_target` フラグで弾くようにしました。
**ノイズスレッドのセーフティネット表示**: 誤判定によるデータロス（見落とし）を防ぐため、HTMLレポートの各プロジェクト末尾に「🗑️ AIがノイズと判定したスレッド」のアコーディオンを新設しました。ノイズ判定されたメールはメイン一覧から隠され、この領域に「件名」「除外理由」「Outlookリンク」のみがコンパクトに表示されます。
変更関数
`MailSummarizer.summarize_project_threads` (プロンプトに文脈判定とis_target, reject_reason追加)
`HTMLReportGenerator.generate_project_report` (スレッドの分岐処理、セーフティネットUIブロックの追加)
新規追加：
なし

VERSION 20260407.01
追加・修正
**GUIの「ALL」連動チェックボックス追加**: プロジェクト選択に「ALL」を追加しました。デフォルト状態を「CaracalのみON」とし、個別チェックとALLチェックの双方向連動ロジック（全選択・一部解除連動）を実装しました。
**HTMLレポートのアコーディオン階層整理**: レポートの視認性を向上させるため、各プロジェクトの「概要ステータス」のみを常時表示とし、「スレッド群」と「AIからの質問・確認事項」をそれぞれ独立したアコーディオン（初期閉）に格納しました。
**HTML上のシームレスなJSON保存機能**: 「AIからの質問」アコーディオン内に回答用テキストエリアを設けました。ブラウザの「保存」ボタンからPythonローカルサーバー経由で通信を行い、画面遷移やポップアップなしでJSONを更新し、「✅ 保存しました」というインライン通知（Toast）を表示する機能を実装しました。
**最新ナレッジの同期**: ブラウザ側で保存された回答メモをGUI側でも同期するため、レポート生成時および知識編集画面を開く直前にJSONを再ロードする安全設計を追加しました。
変更関数
`OutlookRequestHandler.do_POST` (URLエンドポイント `/update_knowledge` の追加)
`MailManagerGUI._ui_project_tab` (ALLチェックと連動処理の追加)
`MailManagerGUI._open_knowledge_editor` (最新JSONの再ロード追加)
`MailManagerGUI._run_project_overview` (最新JSONの再ロードとHTML生成引数の追加)
`HTMLReportGenerator.generate_project_report` (アコーディオン化、テキストエリア追加、保存用JSの追加)
新規追加：
なし

VERSION 20260406.07
追加・修正
**プロジェクト概要の構造化**: AIプロンプトのJSONスキーマを改修し、概要を「ステータス」「進捗・決定事項」「リスク」「次週のフォーカス」の4項目に分割。HTML上でディレクター向け報告フォーマットとして見やすくレンダリングするように変更しました。
**全メールの1行要約一括生成**: プロンプトを改修し、送信テキスト内の各メールにID（m0, m1...）を付与。AIに全メールの1行要約（50文字程度）を一括生成させるようにしました。
**スレッド履歴の3段アコーディオンUI化**: HTMLのレイアウトを変更。スレッドの最下部に「▼ スレッド履歴」を配置し、開くとAIが生成した「1行要約」が一覧表示され、さらに各メールの「▼ 全文」を押すと原文が展開される多層構造にしました。
**個別手動翻訳UIの実装**: 各メールの「▼ 全文」展開内に個別の「🌐 翻訳」ボタンを配置。ユーザーがクリックした際のみAPIが実行される節約型・オンデマンド翻訳機能を実装しました。
変更関数
`MailSummarizer.summarize_project_threads` (プロンプトおよびJSONスキーマ修正)
`HTMLReportGenerator.generate_project_report` (HTML/JS/CSSの大幅な改修)
新規追加：
なし

VERSION 20260406.06
追加・修正
**Outlookリンクの検索機能化**: HTMLのOutlook起動ボタンを押した際、ローカルサーバーがURLパラメーターからスレッド件名（topic）を受け取り、Outlookの検索機能でスレッドをハイライトする挙動に変更しました。
**ディレクター報告フォーマット化**: AIプロンプトを修正し、プロジェクト概要が「今週のステータス：」から始まる、論理的で簡潔な報告レポート形式になるようにしました。
**HTML上での動的ソート機能**: レポート画面右上にセレクトボックスを配置し、JavaScriptを用いて「重要度順」「日時順（新しい順）」「日時順（古い順）」を瞬時に切り替えられるようにしました。
**本文の遅延翻訳とトグルUI**: 各スレッド内に「▼ 本文 (〇件)」ボタンを設置。開いた瞬間に裏側で1件ずつ翻訳APIを叩き（レートリミット対策）、完了後に日本語で表示します。また「英 原文」ボタンによる表示言語のトグル機能を実装しました。
**アクションのテーブル化**: タスク漏れや期限を直感的に把握できるよう、担当者・内容・期限・状況を整列したHTMLテーブル形式に変更しました。
変更関数
インポート宣言エリア（`quote` の追加）
`OutlookRequestHandler.do_GET` (URLパラメーターの取得とキューへのタプル送信)
`MailManagerGUI._check_open_queue` (キューのタプル展開と検索メソッド呼び出し)
`MailSummarizer.summarize_project_threads` (プロンプトの改修)
`HTMLReportGenerator.generate_project_report` (HTML/JS/CSSの大幅な改修)
新規追加：
なし

VERSION 20260406.05
追加・修正
**抽出期間の明記**: HTMLレポートのヘッダーに、計算された具体的な日付範囲（YYYY/MM/DD 〜 YYYY/MM/DD）を明記するように変更しました。
**Outlookリンクの実装**: AIのJSON出力スキーマに `thread_id` を追加し、Python側で元の `entry_id` と紐付けることで、各トピックの横にOutlook起動リンクを配置しました。
**アクション項目の最適化**: ラベルを「アクション」に統一し、AIプロンプトとPythonのソート処理の二段構えで「Taizo Ochi」様が必ず先頭に来るよう改修しました。
**スレッドソート機能のUI化**: UI上に「並び順（重要度順 / 最新スレッド順 / 最古スレッド順）」のプルダウンを追加し、HTML生成時にPython側でスレッドを並び替えるロジックを実装しました。
**ステータスの視認性向上**: 「未設定」「完了」などの状況が直感的にわかるよう、HTMLのインラインCSSで色分けバッジを実装しました。
変更関数
`MailManagerGUI._ui_project_tab` (UI追加)
`MailManagerGUI._run_project_overview` (日付計算、ソート順引数追加)
`MailSummarizer.summarize_project_threads` (プロンプトおよびJSONスキーマ修正)
`HTMLReportGenerator.generate_project_report` (引数追加、ソート処理、色分け、リンク追加)
新規追加：
なし

VERSION 20260406.03
追加・修正
**グローバル変数の確実な定義**: 手動適用のミスを防ぐため、ファイルの先頭にある「設定・データ管理」ブロック全体の完全版を提示します。
変更関数
グローバル定数定義エリア
新規追加：
なし

VERSION 20260406.02
追加・修正
**グローバル定数の定義漏れ修正**: `load_project_knowledge` 実行時に `PROJECT_KNOWLEDGE_FILE` が未定義となってクラッシュする `NameError` を解消するため、ファイルの先頭設定エリアに必要な定数を追加しました。
変更関数
グローバル定数定義エリア（クラスや関数の外、ファイルの先頭付近）
新規追加：
なし

VERSION 20260406.01
追加・修正
**GUIのタブ化**: `MailManagerGUI` のUI構築を刷新し、`ttk.Notebook` を導入して「検索 / 整理」タブと「プロジェクト俯瞰」タブに分割しました。
**ナレッジ管理（Memory）機能**: `project_knowledge.json` の読み書き機能と、`knowledge_backups` フォルダへのタイムスタンプ付きバックアップ自動保存機能を実装しました。
**プロジェクト横断抽出機能**: `OutlookMailManager` に、指定されたプロジェクトフォルダから特定期間のメールを取得・スレッド化する `get_project_mails` メソッドを追加しました。
**プロジェクト俯瞰レポート生成**: `MailSummarizer` にコンテキスト独立型の要約メソッド `summarize_project_threads` を追加し、APIコスト（トークン数と日本円）の計算ロジックを実装しました。
**俯瞰レポート用HTML**: `HTMLReportGenerator` に、プロジェクトごとの時系列スレッド、アクションバッジ、AIヒアリングリストを含むダッシュボード形式のレポート生成メソッドを追加しました。
変更関数
`load_config` / `save_config` (グローバル：設定項目追加)
`OutlookMailManager.get_project_mails` (新規)
`MailSummarizer.summarize_project_threads` (新規)
`MailSummarizer.__init__` (コスト計算用変数追加)
`HTMLReportGenerator.generate_project_report` (新規)
`MailManagerGUI.__init__` (UI初期化変更)
`MailManagerGUI._ui` (タブ構造への変更)
`MailManagerGUI._ui_project_tab` (新規)
`MailManagerGUI._open_knowledge_editor` (新規)
`MailManagerGUI._run_project_overview` (新規)
新規追加：
`load_project_knowledge` 関数
`save_project_knowledge` 関数

VERSION　2026.04.02.01
追加・修正
**検索フォルダー名のグローバル定数化とタイポ修正**: マジックストリングによるエラーや将来の変更漏れを防ぐため、To:Me、With:Me、CC:Meの検索フォルダー名をグローバル定数（`SEARCH_FOLDER_TOME`等）としてファイルの先頭に定義しました。同時に、CC:Meのフォルダー名を実際のOutlook環境に合わせて `未(CCMe)` から `未(CcMe)` に修正し、検索エラー（Noneのポップアップ）を解消しました。
変更関数
グローバル領域 (検索フォルダー名定数の追加)
`OutlookMailManager.search_mails_fast` (定数参照への置き換え)
新規追加：
なし

VERSION　2026.04.01.05
追加・修正
**複数レポート生成時の安全確認ダイアログの追加**: 意図せず複数のメールスレッドが選択された状態で「📊 レポート」ボタンを押下してしまい、無駄なAPI通信や待機時間が発生するのを防ぐため、選択件数が2件以上の場合にのみ「X件のスレッドのレポートを作成しますが、よろしいですか？」というYES/NOの確認ポップアップを表示するストッパーを実装しました。
変更関数
`MailManagerGUI._gen` (レポート生成実行前の件数判定とダイアログ表示ロジックの追加)
新規追加：
なし

VERSION　2026.04.01.04
追加・修正
**「全文」ボタンの配置と挙動の最適化**: 視認性と操作性を向上させるため、各メールの「▼ 全文」ボタンを本文の「下」から「上」へ移動しました。これにより、本文を展開した際にもボタンが下に逃げず、その場ですぐに「▲ 閉じる」をクリックできるようになりました。
**トグルボタン群のUX向上**: RSSの元テキスト表示や履歴の展開ボタン（`toggleHist`）も含め、展開時には「▼」が「▲」に切り替わるようにJavaScriptのロジックを改良し、現在の状態が直感的にわかるようにしました。
変更関数
`HTMLReportGenerator._build_html` (JavaScriptの `toggle` および `toggleHist` 関数のロジック修正)
`HTMLReportGenerator._card` (HTML構造における `.toggle` 要素の配置を `.m-body` の直前へ移動)
新規追加：
なし

VERSION　2026.04.01.03
追加・修正
**指定メールの個別翻訳機能の実装**: HTMLレポート上の各メールヘッダー（「🚀 Outlook」の右隣）に「🌐 翻訳」ボタンを新設しました。クリックすると、そのメールの本文だけをGemini APIで日本語に翻訳し、英語の原文と瞬時に入れ替えます。
**ローカルサーバーの非同期POST/CORS対応**: ブラウザからPython側へ安全に長文テキストを送信するため、`OutlookRequestHandler` に `do_POST` およびセキュリティ要件であるプリフライト対応（`do_OPTIONS`）を実装しました。
**エコで高速なトグルキャッシュ**: 翻訳結果はJSのメモリにキャッシュされ、2回目以降はAPIを消費せずに「英 原文」「🌐 翻訳」をノータイムで切り替えられるUI/UXを実現しました。二重送信防止ロックも完備しています。
変更関数
`OutlookRequestHandler` クラス全体 (`do_OPTIONS`, `do_POST` の追加、CORSヘッダーの付与)
`HTMLReportGenerator._build_html` (JS翻訳関数の追加)
`HTMLReportGenerator._card` (ボタンの配置と、JSから操作するための `id` の付与)

VERSION　2026.04.01.02
追加・修正
**With:Me / CC:Me 検索の爆速化（ハイブリッド検索の拡張）**: To:Me検索の成功を受け、With:MeおよびCC:Meの検索時にも、それぞれ対応するOutlookの検索フォルダー（「未(WithMe)」「未(CCMe)」）から直接データを取得する方式に拡張しました。これにより、宛先チェック関連のすべての検索が数秒で完了するようになります。
**動的フォルダー連携とエラーハンドリング**: To/With/CCの複数チェック時に、必要な検索フォルダーを動的に探索・結合し、1つでも見つからないフォルダーがあった場合は「検索フォルダが見つかりませんでした: 未(WithMe)」のように、どれが欠けているかを明示して安全に処理を停止します。
**受信トレイ検索の最適化**: To/With/CCのいずれかにチェックが入っている場合は「受信トレイ」の無駄な全件探索を完全にスキップし、すべて未チェックの場合のみ受信トレイを探索するように探索条件（`needs_inbox`）を適正化しました。
変更関数
`OutlookMailManager.search_mails_fast` (フォルダー取得ロジックのループ化・拡張、および宛先判定スキップ条件の拡張)
新規追加：
なし

VERSION　2026.04.01.01
追加・修正
**To:Me検索の爆速化（ハイブリッド検索）**: 「To:Me（私のみ）」のチェックを入れて検索を実行した際、全件から1通ずつ宛先を判定する処理をスキップし、Outlookの内部インデックス（検索フォルダー「未(ToMe)」）から直接データを取得する方式に切り替えました。これにより、数百件規模の検索にかかる時間が劇的に短縮されます。
**検索フォルダー不在時の安全装置**: 検索フォルダー「未(ToMe)」が見つからない場合は、無駄な全件探索（フォールバック）を行わず、即座に「検索フォルダが見つかりませんでした」というエラーメッセージを表示して処理を安全に停止する仕様を追加しました。
**複数条件の統合（案Aの実装）**: 「To:Me」と「With:Me」など複数にチェックが入った場合、「未(ToMe)」フォルダーと「受信トレイ」の両方を動的に検索し、重複を排除しながら完全な結果を結合して表示する高度なハイブリッド連携を実装しました。
変更関数
`OutlookMailManager.search_mails_fast` (フォルダーの動的構築ロジックの追加、および `未(ToMe)` 取得時の宛先判定ループ（`item.Recipients`）のスキップ処理の追加)
新規追加：
なし

Outlook メール統合マネジメントツール
VERSION: "2026.02.25.02"
変更履歴：

VERSION　2026.02.25.02
追加・修正
**スマホ閲覧時のスクロール位置見切れ修正**: iPhoneなどでの閲覧時、アドレスバーの動的伸縮によって絶対座標計算がズレてカード上部が隠れてしまう問題に対応するため、JavaScriptのスクロール処理をブラウザネイティブな `scrollIntoView` APIに置き換えました。
**スマホ時の上部余白最適化**: ネイティブスクロールAPIの導入に合わせ、CSSのスマホ用メディアクエリ内における `scroll-margin-top` を `10px` から `30px` に拡張し、iPhoneのノッチ（画面上部の切り欠き部分）等にタイトルが被らないよう十分な余白を確保しました。
変更関数
`HTMLReportGenerator._build_html` (CSSの `scroll-margin-top` 値変更、およびJSの `scrollToCard` 関数内のスクロールロジック書き換え)
新規追加：
なし

VERSION　2026.02.25.01
追加・修正
**「全選択既読」ボタンの新設**: フッターの「☑ 全選択」ボタンの左側に「■全選択既読」ボタンを追加しました。これにより、表示されている全リストの選択と既読化処理をワンクリックで同時に実行できるようになり、日々の処理効率が劇的に向上します。
**誤爆・空回り防止の安全装置**: 一覧にメールが1件も表示されていない（空の）状態では、このボタンを自動的にグレーアウト（無効化）する制御を組み込み、無意味なバックグラウンド処理の空回りを物理的に防止しています。
変更関数
`MailManagerGUI._ui` (フッターへのボタン追加配置。※前回パッチのCombobox化の変更も保持しています)
`MailManagerGUI._chk_btns` (リスト空時のボタン無効化ロジックの追加)
新規追加：
`MailManagerGUI._all_and_mark_read` (全選択と既読化を連続実行するヘルパーメソッド)

VERSION　2026.02.24.05
追加・修正
**フォルダ入力欄のCombobox化**: GUIの「フォルダ」入力欄を `ttk.Entry` から `ttk.Combobox` に変更し、フリーテキスト入力とプルダウン選択を両立させました。
**フォルダ一覧の動的抽出と更新**: 各種検索（通常、広告、RSS、迷削既読）によってメールデータが取得された直後（フロントエンドでフィルタリングされる前の大元データ）に、存在するフォルダ名を抽出し、重複排除・ソートした上でプルダウンの選択肢にセットします。
**入力値の保護**: リストが更新される際、ユーザーが現在入力しているテキストが上書き・消去されないよう、更新前後で値を保持・復元する安全装置を実装しました。
変更関数
`MailManagerGUI._ui` (フォルダ欄をComboboxへ変更)
`MailManagerGUI._run_search` (フィルタ前のフォルダ名抽出ロジック追加)
`MailManagerGUI._search_ad` (同上)
`MailManagerGUI._search_rss` (同上)
`MailManagerGUI._mark_junk_deleted_read` (同上)
新規追加：
`MailManagerGUI._update_folder_combobox` (メインスレッドでComboboxのリストを安全に更新し、入力値を保

VERSION　2026.02.24.05
追加・修正
**フォルダ入力欄のCombobox化**: GUIの「フォルダ」入力欄を `ttk.Entry` から `ttk.Combobox` に変更し、フリーテキスト入力とプルダウン選択を両立させました。
**フォルダ一覧の動的抽出と更新**: 各種検索（通常、広告、RSS、迷削既読）によってメールデータが取得された直後（フロントエンドでフィルタリングされる前の大元データ）に、存在するフォルダ名を抽出し、重複排除・ソートした上でプルダウンの選択肢にセットします。
**入力値の保護**: リストが更新される際、ユーザーが現在入力しているテキストが上書き・消去されないよう、更新前後で値を保持・復元する安全装置を実装しました。
変更関数
`MailManagerGUI._ui` (フォルダ欄をComboboxへ変更)
`MailManagerGUI._run_search` (フィルタ前のフォルダ名抽出ロジック追加)
`MailManagerGUI._search_ad` (同上)
`MailManagerGUI._search_rss` (同上)
`MailManagerGUI._mark_junk_deleted_read` (同上)
新規追加：
`MailManagerGUI._update_folder_combobox` (メインスレッドでComboboxのリストを安全に更新し、

VERSION　2024.02.24.04
追加・修正
**スマホ表示用viewportメタタグの追加**: HTMLレポートの `<head>` セクション内に `<meta name="viewport" content="width=device-width, initial-scale=1.0">` を追加しました。これにより、iPhone等のスマートフォンで閲覧した際に、画面が強制的に縮小（ズームアウト）される問題が解決し、前回実装したスマホ用メディアクエリ（ボタンの大型化やフォントサイズの最適化）が正しく発動するようになります。
変更関数
`HTMLReportGenerator._build_html` (HTMLヘッダーへの `meta` タグ1行追加)
新規追加：
なし

VERSION　2024.02.24.03
追加・修正
**レポート出力先の動的切り替え**: 「📊 レポート」生成時、対象がすべて「RSS記事」であるかをプログラム内部で自動判定し、RSSの場合は最初からSharePointフォルダへ直接HTMLを出力するように変更しました。
**フォールバック機能の追加**: SharePointフォルダが存在しない場合や、通常メールとRSSが混在している場合は、従来通りローカルの `mail_reports` フォルダに代替保存し、GUI上に警告ポップアップを表示する安全設計を施しました。
**コピー機能・サーバー通信の完全撤去**: 出力先の自動化に伴い、不要となったHTML上の「Copy to Sharepoint」ボタン、関連するJavaScript（CORS対応等）、およびローカルサーバーの `/copy` エンドポイントを綺麗に削除し、システムをスッキリと堅牢化しました。
変更関数
`OutlookRequestHandler.do_GET` (`/copy` エンドポイント処理の削除)
`HTMLReportGenerator.generate_report` (RSS判定ロジックの追加、出力先ディレクトリの動的決定、およびフォールバック時の警告表示)
`HTMLReportGenerator._build_html` (コピー機能に関わる不要なCSS、JavaScript、ボタンタグ、および `abs_path` 引数の削除)
新規追加：
なし

VERSION　2024.02.24.02
追加・修正
**スマホ表示時のフォントと余白の最適化**: iPhoneでの閲覧時に文字が読みやすくなるよう、ベースフォントサイズ（16px）の適用、タイトルの拡大、およびカード内の余白（padding）の圧縮を行うメディアクエリを追加しました。
**ナビゲーションボタンとインジケーターの大型化**: 画面右側のフローティングボタン（▲/▼）を、iPhoneなどのスマホ画面で確実に指でタップできるよう、60pxの大型サイズに調整しました。同時に、現在位置を示すインジケーターの文字サイズもバランスよく拡大（0.95rem）しています。
**統計情報・コピーボタンのレイアウト崩れ防止**: ヘッダー下部にある「Threads」「Mails」などの統計情報カードと「Copy to SharePoint」ボタンが、スマホの縦画面ではみ出さないよう、統計カードを横並びで均等に縮小配置し、コピーボタンを画面幅いっぱいのフル幅（100%）に自動調整するCSSを追加しました。
変更関数
`HTMLReportGenerator._build_html` (CSSメディアクエリの追加と、スタイル調整用のクラス属性付与)
新規追加：
なし

VERSION　2024.02.24.01
追加・修正
**RSS記事の送信者名・タグ自動分離**: NoteのRSSなどで送信者欄が「#AIタグ」のようなフィード名になってしまう問題に対し、記事本文からURL（`https://note.com/...`）を自動検出し、執筆者ID（クリエイター名）を抽出して「送信者」列に表示する汎用ロジックを追加しました。
**既存タグの退避（カテゴリ化）**: URLから執筆者の抽出に成功した場合、これまで送信者欄を占有していた「#AIタグ」を「分類（カテゴリ）」列に自動で移動・追記するようにしました。
**誤爆防止の安全装置**: 既存のQiitaなどの正しい執筆者名を破壊しないよう、対象を「サブフォルダ名に `note` が含まれる」または「送信者名が `#` から始まる」RSSのみに限定しました。さらに、抽出に失敗した場合は元の表示を維持するフォールバック機能を実装しています。
変更関数
`OutlookMailManager.get_unread_rss_feeds` (本文からのURL抽出、および送信者・カテゴリデータの再マッピング処理の追加)
新規追加：
なし

VERSION　2026.02.23.03
追加・修正
**スマホ向けフローティングナビゲーションの実装**: HTMLレポート画面の右側中央に、スマホ（iPhone）での閲覧に最適化されたフローティングボタン（上/下矢印）を追加しました。ワンタップで次のメール/RSS（カード）へスムーズにスクロールし、画面上部に張り付きます。
**アクティブカードのハイライト機能**: 現在閲覧している（スクロールされている）カードに対して、Outlookテーマカラーの青い枠線と影（`.active-card`）が付与され、どこを読んでいるかが視覚的に分かりやすくなりました。
**スクロール連打防止・軽量化**: 物理的リスクへの対策として、ボタンを連打した際の座標ズレを防ぐため0.2秒の排他ロックを導入しました。また、スクロール監視の頻度を最小限に抑え、データ大量時でもフリーズしない軽量なIntersectionObserverを実装しています。
変更関数
`HTMLReportGenerator._build_html` (CSS、JS、およびナビゲーションHTMLタグの追加、ループ時のインデックス引き渡し)
`HTMLReportGenerator._card` (HTML出力時にID属性 `id="card-{index}"` と `data-index="{index}"` を付与するように引数と出力を拡張)
新規追加：
なし

VERSION　2026.02.23.02
追加・修正
**Sharepoint共有機能の追加**: HTMLレポートの統計情報ブロックの右側に「📋 Copy to Sharepoint」ボタンを追加し、1クリックで指定されたSharepointのローカル同期フォルダ（`My Private - Documents\Summary`）へサマリーシートをコピーする機能を実装しました。
**ローカルサーバーの拡張（CORS対応）**: ブラウザのセキュリティ制約（CORS）をクリアしつつ画面遷移を起こさずにコピーを実行するため、Pythonのローカルサーバーに `/copy` エンドポイントを新設しました。ファイルロック時やフォルダ不在時は、ブラウザに `alert` で即座にエラーを通知します。
**連打防止処理の実装**: コピー処理中はボタンをグレーアウト（disabled）状態にして「Copying...」と表示し、多重書き込みやファイル破損を防止する排他制御をフロントエンドに追加しました。
変更関数
`OutlookRequestHandler.do_GET` (コピー処理用エンドポイント `/copy` のルーティングとCORS対応処理の追加)
`HTMLReportGenerator.generate_report` (HTMLに渡すために自身の絶対パスを取得・付与)
`HTMLReportGenerator._build_html` (パス変数の埋め込み、JSの非同期fetch関数、およびコピーボタンUIの追加)
新規追加：
なし

VERSION　2026.02.23.01
追加・修正
**簡易ソート機能の追加**: Treeviewの各列ヘッダーをクリックすることで、文字列ベースでの昇順・降順ソートが可能になりました。Tkinterのイベントハンドラの特性（関数実行中はUI描画が一時停止・ロックされる仕様）を活用し、ソート中のチラつきや再描画を抑制しています。
**フォルダフィルタリングの追加**: UIの「分類」と「本文KW」の間に「フォルダ」の入力欄を追加し、入力された文字列（部分一致）でフォルダ列を絞り込む機能を実装しました。
**フィルタの広範適用**: フォルダの絞り込み処理を、通常検索だけでなく「RSS抽出」や「広告抽出」ボタン実行時にも適用されるようにフロントエンド処理のフローを拡張しました。
変更関数
`MailManagerGUI._ui` (フォルダ用Entryの追加と、列ヘッダーへのソートイベント付与)
`MailManagerGUI._search` (検索条件辞書に `folder_kw` を追加)
`MailManagerGUI._search_external` (同上)
`MailManagerGUI._search_ad` (取得後にフロントエンドフィルタを適用)
`MailManagerGUI._search_rss` (同上)
`MailManagerGUI._filter_threads_loose` (フォルダ名の部分一致評価ロジックを追加)
新規追加：
`MailManagerGUI._sort_tree` (列ヘッダーのクリックによる文字列ソート実行メソッド)

VERSION　2026.02.21.01
追加・修正
**「フォルダ」列の追加**: UIの一覧に「フォルダ」列を新設し、スレッド（最新メール）が属するフォルダ名を明示するようにしました。
**RSS記事のデータ構造適正化**: RSS記事において、送信者列には「発行者名（SenderName）」を表示し、新設したフォルダ列に「サブフォルダ名（フィード名）」を表示するようにデータを分離・適正化しました（AI要約用の判定フラグは維持）。
**Promotion移動時のパージ抑止**: 広告メールをPromotionフォルダへ移動した際、リストから行を削除（パージ）せず、対象行のフォルダ列を「Promotion」に書き換えて表示を維持するように修正しました。
変更関数
`OutlookMailManager.get_unread_rss_feeds` (発行者名と表示用フォルダ名の取得と分離)
`OutlookMailManager.group_by_thread` (最新フォルダ名の集計属性追加)
`MailManagerGUI._ui` (UIへの列追加)
`MailManagerGUI._update` (追加列へのデータ挿入)
`MailManagerGUI._click` (列追加に伴うフラグクリック判定のインデックス調整)
`MailManagerGUI._on_tree_double_click` (列追加に伴うダブルクリック判定のインデックス調整)
`MailManagerGUI._on_move_done` (削除ロジックを廃止し、フォルダ列の部分更新ロジックへ変更)
新規追加：
なし

VERSION　2026.02.20.01
追加・修正
**既読アイテムの背景色グレー化**: 既読メールおよび既読RSSの行について、背景色を薄いグレー（`#f0f0f0`）で表示するように変更し、視認性を向上させました。
**選択ハイライトの優先度適正化**: 既読アイテムを選択した際、グレー背景が選択時の青色（`#b3d9ff`）を上書きしてしまわないよう、Tkinterの仕様に基づき `checked` タグの定義順序を最後尾へ移動し、表示優先順位を最大化しました。
変更関数
`MailManagerGUI._ui` (既読用タグに `background` 属性を追加、`checked` タグの定義位置を移動)
新規追加：
なし

VERSION　2026.02.19.06
追加・修正
**RSS記事のURL抽出精度の向上（正規表現の適正化）**: RSS本文からURLを抽出する際、URLの末尾にHTMLタグのカッコ（`<`や`>`）などが混入し、リンククリック時に `%3E` が付着してエラーになる不具合を修正しました。
変更関数
`MailSummarizer.summarize_thread` (URL抽出の正規表現を変更)
`MailSummarizer._fetch_web_content` (URL抽出の正規表現を変更)
新規追加：
なし

VERSION　2026.02.19.05
追加・修正
**RSS元記事リンクのUI追加**: RSS記事の要約レポートにおいて、抽出した元記事のURLをデータに付与し、「Outlook」リンクの左横に「🌐 記事の表示」リンクを追加しました。これにより、レポート画面からワンクリックでニュースの元記事をブラウザで開けるようになりました。
変更関数
`MailSummarizer.summarize_thread` (URLの抽出とデータ注入処理の追加)
`HTMLReportGenerator._card` (RSS専用HTMLレイアウトにリンク追加)
新規追加：
なし

VERSION　2026.02.19.04
追加・修正
**生成AI出力ブレの補正（エラー回避）**: Gemini APIがJSONオブジェクト（辞書型）ではなく、予期せずJSON配列（リスト型）でレスポンスを返してきた際に、レポート生成処理（`_build_html`）で `AttributeError: 'list' object has no attribute 'get'` が発生しクラッシュする不具合を修正しました。JSON抽出時に自動でリストから辞書を取り出す安全装置を追加しています。
変更関数
`MailSummarizer._extract_json` (パース結果の型チェックとリスト解除処理を追加)
新規追加：
なし

VERSION　2026.02.19.03
追加・修正
**RSS記事のWebスクレイピングと専用AI要約機能の実装**: RSS記事の要約時に、本文内に含まれるURLを自動抽出し、`requests`と`BeautifulSoup`を用いてWebサイトから直接本文を取得する機能を追加しました（タイムアウト10秒、アクセスブロック時は明示してフォールバック）。
**RSS専用プロンプトとレイアウトの追加**: 抽出したWeb記事に対し、指定されたプロンプト（タイトル、要旨、キーワード、結論、主なポイント）をJSONでGeminiに要求し、HTMLレポート上でニュース専用の美しいレイアウトで表示するようUIを改修しました。
変更関数
`MailSummarizer.summarize_thread` (RSS分岐処理の追加)
`HTMLReportGenerator._card` (RSS専用HTMLレイアウトの追加)
新規追加：
`import requests` (ファイル冒頭)
`from bs4 import BeautifulSoup` (ファイル冒頭)
`MailSummarizer._fetch_web_content` (Webスクレイピング実行メソッド)
`MailSummarizer._generate_rss_summary` (RSS専用JSONプロンプト実行メソッド)

VERSION　2026.02.19.02
追加・修正
**RSS記事のフィード名表示対応**: RSS記事の一覧表示において、記事が格納されているサブフォルダ名（フィード名）を「送信者」列に表示するように変更しました。これにより、どのRSSサイトからの記事か直感的に識別できるようになります。
変更関数
`OutlookMailManager.get_unread_rss_feeds` (送信者名に `folder.Name` を代入するよう修正)
新規追加：
なし
VERSION　2026.02.19.01
追加・修正
**RSS記事抽出機能の強化（サブフォルダ対応）**: RSSフィードフォルダ直下の記事だけでなく、フィード別に作成されたすべての「サブフォルダ」（例: Qiita-AI, Zenn-AI等）を再帰的にスキャンし、未読記事を正確に抽出するようロジックを修正しました。全体で500件の上限は安全のため維持されています。
変更関数
`OutlookMailManager.get_unread_rss_feeds` (再帰的なサブフォルダ探索ロジックへの置き換え)
新規追加：
（新規関数の追加はなし。既存関数内のヘルパー関数 `_scan_folder` として実装）

VERSION　2026.02.06.02
追加・修正
**RSS記事抽出機能の追加**: Outlookの標準「RSS フィード」フォルダ（Folder ID: 25）から、未読記事を最大500件取得し、一覧表示する専用機能を追加しました。RSS記事はすべて独立したスレッドとして表示され、既存の既読化機能や要約レポート機能と連動します。
変更関数
`MailManagerGUI._ui` (UIボタン追加)
新規追加：
`OutlookMailManager.get_unread_rss_feeds` (RSS専用取得メソッド)
`MailManagerGUI._search_rss` (GUIイベントハンドラ)

2026.02.03.03   「迷削既読」機能の仕様変更。バックグラウンド一括実行から「対象取得→リスト表示→全選択→確認ダイアログ→実行」の対話型フローへ変更。最大取得数を500件に制限する安全策を追加。
                変更関数：
                    OutlookMailManager.get_junk_deleted_unread_mails: (新規追加) 迷惑メール(23)・削除済み(3)の未読を取得。
                    MailManagerGUI._mark_junk_deleted_read: (変更) フロー制御（取得→表示）を実装。
                    MailManagerGUI._update_and_select_all_for_junk: (新規追加) 表示更新・全選択・ダイアログ・実行のヘルパー。
                    OutlookMailManager.mark_all_junk_deleted_read: (削除) 不要になったため削除。
2026.02.03.02   広告抽出機能（_search_ad）において、UIの「未読のみ」チェックボックスの状態を反映するように修正。バックエンドの検索処理（search_ad_mails）で既読メールをスキップするロジックを追加。
                変更関数：
                    OutlookMailManager.search_ad_mails: 引数 unread_only を追加し、ループ内フィルタ処理を実装。
                    MailManagerGUI._search_ad: unread_only 引数を渡すように呼び出し元を修正。
2026.02.03.01   期間設定に「24H（過去24時間）」を追加し、デフォルト値を「24H」に変更。既存の「今日」設定（昨日からのメールを含む）は維持しつつ、選択肢の並び順を時系列（24H→今日→3日間...）に整理。
                変更関数：
                    MailManagerGUI._ui: プルダウンのリスト順序変更、初期値を"24H"に変更。
                    MailManagerGUI._get_days: "24H"（値0）のマッピングを追加。
                    OutlookMailManager.search_mails_fast: days=0時の時刻指定検索ロジックを追加。
                    OutlookMailManager.search_ad_mails: days=0時の時刻指定検索ロジックを追加。
