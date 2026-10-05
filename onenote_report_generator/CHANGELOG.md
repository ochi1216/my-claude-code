## VERSION 20261005_01

### 追加（S02）: レポート編集・次週ページ作成・Outlook下書き

越智さんのご依頼（OneNote オーガナイザー開発 S02）。仕様は越智さんとの確認
（Phase 1〜2）で確定。ファイルは `app/onenote_report_generator_20261005_01.py`
（旧版は残置）。

- **レポートの配信方法を変更**：`/reports/open/<名>` は `file://` ではなく
  `http://localhost:5000/reports/view/<名>`（Flask経由）で開く。`file://` のページは
  localhostのAPIをCORSで呼べず、以下の機能が使えないため。ファイル名は
  `reports/`直下の`.html`のみ許可（`..`・パス区切りは拒否）。
- **機能1 Executive Summaryの手動編集**：各ページブロックに「✏要約を編集／💾保存／
  ↩元に戻す」。`summary-box`をその場で編集し `POST /api/report/save_summary` で
  レポートHTMLへ保存（ホワイトリストでサニタイズ）。生成時の内容は初回編集時に
  `<レポート名>.html.orig.json` へ退避し、元に戻せる（7日超削除時に一緒に削除）。
  OneNote元ページは変更しない。
- **機能2 次週ページ作成**：`POST /api/page/copy_next_week`。元ページHTMLを複製し、
  ①青文字（既存`blue_detection`と同じ閾値・`color`のみ、`background-color`は対象外）
  をすべて黒（#000000）へ、②タイトルの最初の`YYYY/MM/DD`を**元の日付より後の最初の
  月曜**へ（元が月曜なら+7日・0埋めの有無は維持）、③同一セクションへ新規ページ作成。
  タイトルに日付が無い場合は**作成を中止**してエラー表示。元ページの作成日メタ
  （`meta name=created`）とGET専用の`id`/`data-id`は外す。
  - 画像は既定で転送しない（枚数を警告表示）。ブロック内の「画像も転送」ON時のみ
    取得してmultipartで同梱（取得失敗は件数を警告）。添付ファイル・埋め込み
    （object/iframe）は未対応で、件数を警告。
  - **既定で無効**：OneNote書込権限が未申請のため、`config.json` の
    `enable_onenote_write`（既定false）がtrueのときだけ有効。falseの間は認証スコープを
    現行（`Notes.Read`ほか）のまま変えず、ボタンは無効表示。trueにすると
    `onenote_write_scope`（既定`Notes.ReadWrite`）を追加して再認証になる。
- **機能3 Outlook下書き**：`POST /api/outlook/draft`。クラシックOutlookをCOM
  （pywin32）で操作し、編集後のサマリー＋OneNoteリンクを本文にした下書きを保存・表示
  する（宛先・件名は空欄、送信はしない）。リンクは元ページ、次週ページ作成済みなら両方。
  `requirements.txt` に `pywin32`（Windowsのみ）を追加。
- `_generate_worker` に `section_id` 引数（既定""）を追加。ページID等は
  `_page_meta` としてレポートHTMLの`data-*`属性へ埋め込む（Geminiへ渡す前回データ
  からは除外）。**旧VERSIONで作ったレポートは再生成が必要。**
- `templates/index.html`：VERSION表記、`/generate`へ`section_id`送信のみ変更。

#### 検証状況
- リモート（Linux）で単体テスト13件・ブラウザ（Chromium）での編集→保存→再読込→
  元に戻す・`file://`でツールバー非表示を確認済み。Graph API・Outlook COMはモック。
- **実機未確認**：Outlook COM（クラシック版）、OneNoteへの実書込（権限付与後）、
  画像転送、実ページの青文字変換漏れ。

## VERSION 20260928_01

### 変更（追記6）: フォルダ構成の整理（コードを`app/`フォルダへ移動）

越智さんより「バージョンアップしたコードが`onenote_report_generator/`直下に
平置きされて見づらい。極力`app/`のような配下フォルダを作ってコードを管理し、
直下はバッチファイルのみに近い状態にしてほしい」との依頼を受けて対応した。

- **移動したもの**（`app/`フォルダへ）：全バージョンの`onenote_report_generator_*.py`
  （現行版・旧版とも）、`templates/`、`requirements.txt`、`config.example.json`
- **直下に残したもの**：`start_onenote_report_generator.bat`、`README.md`、
  `CHANGELOG.md`、および実行時データ（`config.json`・`token_cache.bin`・
  `bookmarks.json`・`logs/`・`reports/`。いずれも認証情報・業務データを含み
  `.gitignore`対象）。実行時データを`app/`と分離したのは、越智さんへの確認の
  結果（データ置き場についてご確認いただき「直下に残す」を選択）。
- **パス解決を`TOOL_ROOT`（`app/`の1つ上）基準に統一**：従来は
  `config.json`/`token_cache.bin`がカレントディレクトリ相対、
  `bookmarks.json`/`reports/`がスクリプト自身の場所（`__file__`）相対と
  混在しており、`app/`フォルダへ移動するとこれらの置き場所がバラバラに
  なってしまう問題があった。すべて`TOOL_ROOT = os.path.dirname(os.path.dirname(
  os.path.abspath(__file__)))`基準に統一し、起動時のカレントディレクトリにも
  スクリプトの配置階層にも依存しないようにした。
- **Gemini共通モジュール（`gemini_client.py`）の探索先に`../../../common`を追加**：
  `app/`フォルダの導入でスクリプト自身がもう1階層深くなったため
  （`PythonScripts\Onenote\onenote_report_generator\app\`）、既存の`../common`・
  `../../common`に加え、実際の配置先`PythonScripts\common\`に届く
  `../../../common`を候補に追加した（`_resolve_common_dirs()`）。
- **起動バッチ（`start_onenote_report_generator.bat`）を`app/`配下を見るよう修正**：
  最新スクリプトの検索・実行パスを`app\onenote_report_generator_*.py`に変更。
  ログ（`logs/`）・実行時データの置き場は変更なし（従来どおり直下）。

### 修正（追記4）: 別セッションのコミットとの統合に伴う軽微な不整合の修正

`claude/onenote-organizer-s01-6zudff`ブランチに、本ツールと並行して別セッション
（tool_launcher/document_search_manager開発セッション）が3件のコミットを追加した
（起動時コンソール表示の修正、日英併記モードのブロック単位レイアウト化、旧プロセス
自動終了）。取り込みにあたりレビューし、以下2点の軽微な不整合を修正した。

- **`<title>`タグのバージョン番号が古いまま**（`templates/index.html`）：本文中の
  `<small>`タグは20260928_01に更新済みだったが、ブラウザタブに出る`<title>`タグの
  みバージョン番号の修正が漏れていた（20260815_01のまま）。20260928_01に修正。
- **日英併記モードの「他n件」オーバーフロー注記が言語分岐していない**
  （`_render_updates_block`）：英語ブロック（Key Updates）側でも日本語の
  「…他 N 件」がそのまま出力されていた。`lang`に応じて日本語ブロックは
  「…他 N 件」、英語ブロックは「…N more」を出すよう修正した。

### 追加（追記5）: 起動用バッチファイルをリポジトリ管理下に追加

`start_onenote_report_generator.bat`（フォルダ内最新の`onenote_report_generator_*.py`
を自動検出して起動するランチャー）が、このツール導入以来ずっとgit管理されておらず
（他ツールは`run_xxx.bat`として全てコミット済みなのに対し例外だった）、
`git clone`のたびに手動コピーが必要になっていた。ユーザー提供の現行版を、作業
フォルダへの移動を`cd /d "C:\Users\...\<固定パス>"`から`cd /d %~dp0`（バッチ
ファイル自身の場所を使う。`document_search_manager/run_document_search_manager.bat`
と同じ慣習）に変更した上でリポジトリに追加した。改行コード（CRLF）・文字コード
（UTF-8）は変更していない（過去にLF化で起動直後に閉じる不具合が発生した経緯が
あるため）。

### 追加（追記3）: 起動時に、ポートを塞いでいる旧プロセスを自動終了する
越智さんは本ツールを頻繁に更新し、そのたびにランチャーから起動し直す運用の
ため、直前に起動したFlaskプロセスが終了しないまま残っていると、新しい
プロセスがポート5000を使えず、ブラウザが古いプロセスの画面につながった
まま（＝最新のコードを更新したつもりが反映されない）になる不具合が実機で
複数回発生した。毎回タスクマネージャーで手動終了する必要があり、このまま
更新を重ねると同じ混乱が繰り返される、との指摘を受けて対策した。

- `_free_port_if_stale(port)`を新設し、起動直前（`app.run()`の前）に呼ぶ
  ようにした。ポート5000を使用中のプロセスがあれば、`python.exe`/
  `pythonw.exe`であることを確認したうえで自動終了する。
- 判定はtool_launcher自身の「応答なしプロセスの自動終了」と同じ考え方
  （対象プロセスの実行ファイル名を確認する、判定に迷えば終了しない）。
  自分自身のPID、python.exe/pythonw.exe以外のプロセス、プロセス情報が
  取得できない場合は、いずれも終了しない（安全側に倒す）。
- 追加ライブラリ（`psutil`等）は使わず、Windows標準コマンド
  （`netstat`/`tasklist`/`taskkill`）のみで実装した。Windows以外では
  何もしない（早期return）。
- 何が起きたかをコンソールに表示する
  （例：「⚠ 既存のプロセス（PID 12345, python.exe）がポート5000を
  使用中のため、終了して起動し直します。」）。
- 合成データ（`unittest.mock`で`subprocess.run`をモック化）によるテストで、
  netstat/tasklistの出力解析、kill対象の判定（python.exe以外・自分自身・
  情報不明の場合はいずれも終了しないこと）、Windows以外では何も呼ばない
  ことを検証済み（計16項目）。実機での動作は未確認。

### 修正（追記2）: 日英併記モードのレイアウトを、行内併記からブロック単位に変更
越智さんの実機確認により、「日本語＋英語で要約」モードの出力が期待と異なる
ことが判明した。修正前は、エグゼクティブ・サマリー内でJP段落の直後にEN段落を
続け、「主な更新内容」の各箇条書きもJP行の直後にEN行を続ける、**行単位での
併記**になっていた。

越智さんの期待は、**ブロック単位での併記**（①日本語のエグゼクティブ・
サマリー＋主な更新内容（差分）をすべて表示 → ②その後に英語版のExecutive
Summary＋Key Updatesをすべて表示 → ③詳細情報は現状の形式を維持）だったため、
そのとおりに変更した。

- `ReportGenerator._render_update_item()`に`lang`引数（`"ja"`/`"en"`/`None`）
  を追加し、更新項目1件をどちらの言語で出すか指定できるようにした。
  `lang=None`は非併記モード向けの後方互換（従来どおり1行併記）。
- 新設`ReportGenerator._render_updates_block(updates, lang)`で、
  カテゴリ見出し＋箇条書き一式を1言語分だけレンダリングする処理を共通化した。
- `generate_html()`の日英併記モード分岐で、JPブロック（サマリー→
  「主な更新内容 (差分)」全体）→ENブロック（Executive Summary→
  「Key Updates」全体）の順で出力するよう変更。EN側のサマリーが空の場合は
  ENブロック自体を出さない（不要な空欄を作らない）。
- 詳細情報・残アクション（`details`/`pending_actions`）は変更していない
  （従来どおり日本語のみ、現状の表示形式のまま）。
- 非併記モード（`translate_ja`/`keep_original`）の出力は変更していない
  （見出しは1つのまま、項目もプレーン文字列のまま表示される）。

### 修正（追記1）
起動時のコンソール表示が古いバージョン番号（`20260812_02`）のままになっていた
誤字を修正した。`_20260812_02.py`から複製した際の直し忘れで、動作への影響は
無い（Flask自体は`onenote_report_generator_20260928_01`として正しく起動して
いた）。越智さんの実機確認で発見。

### 仕様変更（ご確認ください）
**黒文字単独の話題は「主な更新内容(updates)」に出なくなりました。** 青文字（今週の更新）が
無い話題は、背景情報として「詳細情報」欄に格納されます。これは今回の依頼どおりの仕様変更
であり、不具合ではありません。

### 追加・修正

**① 青文字（今週の更新）が抽出処理でほとんど検出されていなかった不具合を修正**

調査の結果、`extract_with_color()` はOneNoteが実際に出力するHTMLの形のうち1パターン
（`<p style="color:...">` に直接色指定がある場合）しか検出できておらず、次のいずれも
マーカーが付与されていなかった。
- 行をまるごと青くする、OneNoteで最も一般的な書き方（`<p><span style="color:...">`）
  → 親`<p>`が先に黒として出力され、重複除去で青い`<span>`が捨てられていた
- 色指定が16進数（`color:#0070c0`）の場合 → `rgb()`記法しか判定していなかった
- 表のセル内の青 → 表処理が色判定を一切していなかった

抽出処理を「文書順に1回だけたどり、テキストノード単位で色を解決する」線形化方式に
全面刷新し、上記すべてに対応した。箇条書きの階層・見出しも保持するようにし、黒文字が
青文字の対象・主語を補う関係がAIに伝わるようにした。

**② プロンプトを「青文字優先」に変更**

updatesは青文字（【更新ポイント】）の内容から作成し、黒文字は青の対象・主語・前提を
補うためにのみ使うこととした。凡例文（「※青字＝更新」等）は更新として扱わないルールも
追加。updates上限（各カテゴリ最大3項目）は維持しつつ、超過時は統合して収め、内容を
理由なく削除しないよう指示。

**③ レポートに青文字の検出状況を表示（警告のみ、除外はしない）**

各週の見出し下に「青文字 n行を検出」を表示。0行の場合は「⚠ 青文字なし：前回データ
との比較で推定」、直前ページと文言が完全一致する青がある場合は「⚠ 前週と同文の青
k行（コピー残りの可能性）」と警告する（越智さんの確認：運用ミス対策は警告表示のみで
よい）。

**④ 3つ目の要約モード「日本語＋英語で要約」を追加**

英語(en)を先に生成してから日本語(ja)を生成させ、表示は日本語を先にする。jaは英語からの
再翻訳にせず原文から直接執筆させ、固有名詞・数値は原文表記を保つ。英語の読み手は
自分と上司の確認用（越智さんの確認）のため、併記するのはsummary/updatesのみとし、
details・残アクションは日本語のみ。既定モードは従来どおり「日本語に翻訳して要約」。

### 範囲外として報告のみ（今回は修正していません）
- Gemini API利用料金の概算は、思考トークン（thoughtsTokenCount）を含んでいないため、
  実際より低く出ている可能性がある（既存の問題、今回のスコープ外）。
- 「原文の言語のまま要約」モードでは、マーカー「【更新ポイント】」は日本語のまま固定
  （既存の既知事項、CHANGELOG 20260729_02 参照）。

### 変更関数・追加関数（`OneNoteGraphExtractor`）
- `is_blue` / `_extract_color_rgb` / `_parse_css_color` / `_rgb_is_blue`：16進数・rgba()
  対応、大文字小文字を区別しない判定に刷新
- `extract_with_color`：線形化方式へ全面書き換え
- 新規：`_resolve_is_blue` `_render_line` `_flush` `_has_block_descendant`
  `_block_prefix` `_emit_block_line` `_collect_into` `_process_children` `_extract_table`

### 変更関数・追加関数（プロンプト・レポート）
- `_LANG_VARIANTS`：`bilingual_ja_en` を追加、各モードの`summary_hint`/ルール3・4を
  青文字優先の内容に更新
- 新規：`UPDATES_MAX` `_INPUT_FORMAT_NOTE` `_COMMON_RULE3` `_strip_markers`
  `_clean_updates_value`
- `GeminiProcessor.analyze_html`：日英併記モード対応、マーカーの出力後除去を追加
- `ReportGenerator.generate_html`：`language_mode`引数を追加、青文字検出状況の表示、
  updates上限超過時の「…他n件」表示、日英併記の表示に対応
- 新規：`ReportGenerator._render_update_item`
- `_generate_worker`：青文字行数・前週重複の集計、`_build_prev_context`（併記モードの
  前回データを日本語側に絞る）を追加
- 新規：`_blue_lines_from_content` `_ja_only` `_build_prev_context`

### 実機での確認が必要な事項（未実施）
- 実際に使っている青が閾値（`blue_detection`）内に入るか（濃紺 `#002060` は現在の
  閾値では非検出）。ハイパーリンクの色が誤って青と判定されていないか。
- 黒だけの話題がupdatesから消え、サマリーが青文字中心になっているか。
- 日英併記モードの日本語の質が、「日本語に翻訳して要約」モードと同等以上か。
- 起動用バッチファイルのファイル名を `_20260928_01.py` に更新する必要がある。

### テスト
本セッション内でユニットテストを実施（合成HTMLによる自動テスト）。
- 抽出処理：行まるごと青・部分青・16進数・表セルの青・青の中の黒明示span・
  background-colorの誤検出防止・入れ子li・br分割・div直下テキスト・英単語境界の
  空白保持・書式違いspanの結合・rgba()・color後勝ち・凡例行・入れ子の表 等、計17パターン
- プロンプト：既存2モードとの差分が「青文字優先ルール・summary指示・入力形式説明」の
  追加のみであることをdiffで確認（意図しない変更が無いことを保証）
- レポート生成：青文字検出0件時の警告・前週重複警告・updates上限超過時の表示・
  日英併記の形（str/dict混在、en欠け、ja欠け）
- 通し実行：偽のGemini/Graph APIを注入し `/generate` 相当の処理を実行、
  `[DEBUG blue]` の出力・`_build_prev_context` による前回データの絞り込みを確認
- index.html：`languageMode` の選択肢が3つ、既定値が`translate_ja`であることを確認

いずれもリモートセッションでの自動テストのみ。**実機での確認は未実施。**

### 変更ファイル
- `onenote_report_generator_20260928_01.py`（新規、`_20260812_02.py`から複製・改修）
- `templates/index.html`（VERSION 20260928_01、要約言語の選択肢を追加）


## VERSION 20260815_01

### 追加・修正
ブックマーク復元が**初回は必ず失敗し、同じブックマークを選び直すと成功する**という
事象への対策。原因を1つに断定せず、考えられる2つの原因の**両方に効く対策**を入れた。

**対策① タイムアウトを10秒 → 60秒へ延長**

`restoreBookmark` だけが `fetchWithTimeout`（10秒）を使っており、手動でドロップダウンを
操作する経路（`loadNotebooks` / `loadSections` / `loadPages`）にはタイムアウトが無い。
「ブックマークだけ失敗し、手動操作なら成功する」という非対称性は、この差で説明できる。
OneNote Graph API は、しばらくアクセスしていないノートブックへの初回リクエストに
10〜30秒以上かかることがあり、10秒では足りていなかった。

**対策② 失敗時に自動で1回だけ再試行**

ユーザーが選び直す操作を不要にした。再試行中はUIをクリアせず（画面のちらつき防止）、
2回とも失敗した場合のみUIをクリアして失敗表示する。失敗トーストには試行回数を表示する。

**対策③ 認証完了前はブックマーク選択を無効化**

`window.onload` が `checkAuth()` と `loadBookmarks()` を同時に走らせているため、
認証（MSALのトークン更新でネットワーク往復が発生する）が完了する前にブックマークを
選ぶと、サーバー側の `_token` がまだ空で `/api/notebooks` が `{"error":"未認証"}` を
返して失敗する競合があった。`bmSelect` の初期状態を `disabled` とし、
`setAuthenticated()` でサイト一覧の読み込み完了を待ってから有効化するようにした。

### 設計上の判断
- **あえて `AbortController` でリクエストを中断していない。** タイムアウト後も裏で
  走り続けるリクエストが OneNote 側のキャッシュを暖めるため、再試行が成功しやすくなる。
  読み取り専用のGETなので副作用はない。

### 変更関数
- `setAuthenticated` （async化し、`loadSites()` 完了後に `bmSelect` を有効化）
- `restoreBookmark` （`attempt` 引数を追加、タイムアウト60秒、catch節に自動再試行を追加）

### 新規追加
- なし

### 変更ファイル
- templates/index.html のみ（**Python本体は変更なし**。引き続き
  `onenote_report_generator_20260812_02.py` を使用する）

### 動作確認時の注意
- 実物のJavaScriptをDOMスタブ・モックfetch上で実行して検証（全13項目合格）。
  検証済み：初期状態で `bmSelect` が無効であること／`setAuthenticated()` 完了後に
  有効化されること／1回目が失敗しても自動再試行して最終的に成功すること／
  2回とも失敗した場合のみUIをクリアすること／タイムアウトが60秒であること。
- **実機での確認は未実施。** 特に「実際に初回から成功するようになったか」は
  OneNote Graph API の実応答時間に依存するため、実機での確認が必要。
- 60秒待っても失敗する場合は、原因がタイムアウトではない可能性が高い。その場合は
  ブラウザの開発者ツール（F12）のConsoleタブに出る
  `[BM] restoreBookmark失敗 (試行 n/2)` のログを確認すること。

### 変更しないこと（宣誓）
- Python側の全コード（`onenote_report_generator_20260812_02.py`）
- `loadBookmarks` / `saveBookmark` / `deleteBookmark` / `showToast`
- `loadNotebooks` / `loadSections` / `loadPages` / `updatePageRange` / `startGenerate`
- `restoreBookmark` の try 節の中身（①〜④の取得順序・`Array.isArray` ガード）

## VERSION 20260812_02

### 追加・修正
- **`gemini_client.py` の探索先を自動判定するよう修正**：VERSION 20260812_01 の
  既定の探索先は引継ぎ資料どおり `../common` だったが、**本ツールだけ他ツールより
  フォルダ階層が1つ深い**ため、実際の配置先に届いていなかった。

  ```
  スクリプト位置: PythonScripts\Onenote\onenote_report_generator\
  20260812_01 の探索先: PythonScripts\Onenote\common\   ← 存在しない
  実際の配置先:         PythonScripts\common\           ← 1階層上
  ```

  他ツール（例: `outlook_total_organizer`）は `PythonScripts\<ツール名>\` 直下に
  あるため `../common` で正しく届くが、本ツールは2階層下にあるため届かなかった。
  `../common` → `../../common` の順に `gemini_client.py` の実在を確認して自動選択する
  方式へ変更した。これにより**環境変数の設定なしで、共通の `gemini_client.py` を
  1つだけ置いて全ツールで共有できる**。
- **エラーメッセージに探索した全候補を表示**：見つからなかった場合、どのフォルダを
  探したかを全て列挙するようにした（1つだけ表示していると原因の切り分けが難しいため）。

### 優先順位
1. 環境変数 `GEMINI_COMMON_DIR`（設定されていればこれのみを使う）
2. `../common`（他ツールと同じ階層構成の場合）
3. `../../common`（本ツールのようにもう1階層深い場合）

### 変更関数
- なし（既存関数への変更ゼロ。`analyze_html` / `extract_with_color` /
  `generate_html` / `_generate_worker` / `gemini_credentials_available` /
  `_contents_to_payload_contents` がハッシュ比較で同一であることを確認済み）

### 新規追加
- `_resolve_common_dirs()` （探索先候補を優先順に返す）
- `_COMMON_DIR_CANDIDATES` （モジュールレベル定数）

### 変更ファイル
- onenote_report_generator_20260812_02.py （20260812_01 比 +35行 / -9行）
- templates/index.html は**変更なし**

### 動作確認時の注意
- 越智さんの実環境と同じ階層構造を再現し、**実物の `gemini_client.py` を
  `PythonScripts\common` に置いた状態で import に成功することを確認済み**。
  あわせて以下も検証済み：`../common` にある場合は近い方を優先すること／
  `GEMINI_COMMON_DIR` が最優先されること／どこにも無い場合もツールは起動でき、
  AI実行時のエラーに探索した全候補が表示されること。
- VERSION 20260812_01 のシム検証（全27項目）も本バージョンで再実行し、全て合格。
- **実機でのプロキシ経由の応答は引き続き未確認**（Linuxコンテナから到達できないため）。

## VERSION 20260812_01

### 追加・修正
- **Gemini APIプロキシ対応への移行**：会社PCからGemini APIへの直接アクセスが
  遮断された（2026-08-10頃）ことへの対応。共通モジュール `gemini_client.py` の
  `generate_advanced()` 経由に移行し、直接呼び出しが失敗したら自宅PCのプロキシへ
  自動フォールバックする構成にした。`rtocs_organizer` /
  `analog_ic_se_strategy_organizer` / `outlook_total_organizer` に続く4ツール目。
- **互換シム方式を採用**：`genai.Client` と同じインターフェースだけを持つ薄い
  互換シム（`_CommonGeminiClient`）を追加し、**`genai.Client(...)` の生成箇所
  1行だけ**を差し替えた。これにより `response.text` の読み取り・
  `usage_metadata` によるトークン計測とコスト表示・`types.GenerateContentConfig(...)`
  による config 構築は**一切変更不要**。実際に `analyze_html()` は1行も変更していない
  （関数単位のハッシュ比較で同一を確認済み）。
- **APIキー必須ガードの撤廃**：移行後は `config.json` の `GEMINI_API_KEY` が空でも
  プロキシ経由で成功しうるため、旧来の「APIキーが無ければ例外」ガードを
  `gemini_credentials_available()` に置き換えた。`GEMINI_API_KEY` /
  `GEMINI_PROXY_URL` の**どちらか一方でも**あれば通す（プロキシ専用構成を
  誤って弾かないため）。旧来の `config.json` 設定しか無い環境も止めない。
  **このガードを放置すると移行後に全AI機能が例外で停止する**ため、移行の必須項目。
- **`contents` のリスト形式に対応**：本ツールは `contents=[prompt]` とリストで
  渡しており、文字列前提の既存シム実装のままでは `{"text": ["..."]}` という
  不正なpayloadになる。`_contents_to_payload_contents()` を設けて文字列・リストの
  両方に対応させた（`outlook_total_organizer` は全て文字列だったため未対応だった箇所）。
- **`model` の明示的な受け渡し**：`generate_advanced(payload, model=model)` として
  常に明示指定。省略すると共通モジュール側の既定モデルに落ち、「UI上は別モデルを
  表示しているのに実際は flash が動く」silent failure になるため。

### 事前調査で確定した事項
- **Google Search Grounding は未使用**（`grep` で0件）。したがってシムに `tools` を
  載せる処理は不要（引継ぎ資料 4-(5) の分岐は該当せず）。
- **`genai.Client(` は1箇所のみ**（`outlook_total_organizer` は6箇所）。
- **APIキーガードも1箇所のみ**（同5箇所）。
- 本ツールは **Flask Webアプリ**であり、tkinter GUIでもバッチでもない。

### 変更関数
- `GeminiProcessor.__init__` （APIキーガードを `gemini_credentials_available()` へ
  置換、`genai.Client(...)` → `_CommonGeminiClient(...)`）

### 新規追加
- `_COMMON_DIR` / `_generate_advanced` / `_GEMINI_CLIENT_IMPORT_ERROR`（モジュールレベル）
- `gemini_credentials_available()` （認証情報の判定）
- `_schema_to_jsonable()` （`response_schema` のpydantic変換への保険。現状本ツールは
  `response_schema` 未使用だが、将来使用時に備えて残す）
- `_contents_to_payload_contents()` （contents の文字列／リスト両対応）
- `_CommonUsageMetadata` / `_CommonGeminiResponse` / `_CommonGeminiModels` / `_CommonGeminiClient`
- `import sys` （共通モジュールのパス追加用）

### 削除
- `from google import genai` （`from google.genai import types` は
  `types.GenerateContentConfig(...)` の構築に引き続き使うため**残す**）

### 変更ファイル
- onenote_report_generator_20260812_01.py （+160行 / -7行）
- templates/index.html は**変更なし**（VERSION 20260729_02_01 のまま流用可）

### 動作確認時の注意
- **実機でのプロキシ経由の応答は未確認**。Linuxコンテナからは共通モジュールにも
  自宅PCプロキシにも到達できないため、検証は偽の `gemini_client` を
  `sys.modules` へ注入する方式で実施した（全27項目合格）。
  検証済み：payload形状／`model`の明示的受け渡し／`response.text`・`usage_metadata`の
  読み取り／`responseMimeType` の camelCase 化／`json.dumps` 可能性／空・壊れた
  レスポンスで例外を投げないこと／共通モジュール未配置時に原因の分かるエラーが出ること／
  認証情報判定の4パターン。
- **`gemini_client.py` の配置が必要**。既定の探索先はスクリプトから見て `../common`
  （＝ `Onenote\common\gemini_client.py`）。別の場所に置く場合は環境変数
  `GEMINI_COMMON_DIR` でフォルダを指定する。
- 共通モジュールが見つからない場合でも**ツール自体は起動する**（OneNote閲覧・
  ブックマーク・過去レポート閲覧は使える）。AI要約を実行した時点で、探索したパスと
  元のエラーを含むメッセージが表示される。
- **`setx` で環境変数を設定した場合、現在開いているコマンドプロンプトには反映されない。**
  設定後はコマンドプロンプトを開き直すこと。
- `GEMINI_RETRY_DIRECT_AFTER_SECONDS` は `gemini_client.py` が読むため**3ツール共通に効く**。
  本ツール側で個別に変えることはできない。

### 変更しないこと（宣誓）
- `GeminiProcessor.analyze_html` （プロンプト・`_LANG_VARIANTS` 含め一切変更なし）
- `OneNoteGraphExtractor` の全メソッド（`extract_with_color` 等）
- `ReportGenerator` の全メソッド
- ブックマーク機能全体・全Flaskエンドポイント・`_generate_worker`
- `templates/index.html`

## VERSION 20260729_02_01

### 追加・修正
- **要約の出力言語モード追加**：UIに「要約の言語」選択（`<select>`）を追加。
  - 「日本語に翻訳して要約」（既定・`translate_ja`）：従来通り、原文が英語・
    中国語等でも日本語に翻訳して要約する（現行動作を完全維持）。
  - 「原文の言語のまま要約」（新規・`keep_original`）：翻訳せず、原文と同じ
    言語（カテゴリ名・項目名・タスク名を含む全項目）でJSONを出力する。
- **プロンプトの言語依存文字列を`_LANG_VARIANTS`辞書に集約**：`critical_rules`の
  ルール2だけでなく、`system_directive`の末尾文・`_thinking`ヒント・`summary`
  ヒント・`updates`/`details`のカテゴリ名/項目名プレースホルダ・
  `pending_actions.task_name`ヒント・`<execution>`確認文の計7箇所が言語に
  依存していたため、モード切替時に全箇所を一括で差し替える設計とした
  （1箇所だけの条件分岐だと、スキーマ内に残った日本語強制の指示文とルール2が
  競合し、「原文の言語のまま」モードでも日本語化されてしまうリスクがあったため）。
  `translate_ja`側の文言は変更前バージョンの文言と完全一致させており、
  テストでプロンプト文字列がバイト単位で一致することを確認済み（既定動作は無変更）。
- 本バージョンは、VERSION 20260729_01_01のCHANGELOGで宣誓した
  「GeminiProcessorの全メソッド（プロンプト含む）を変更しない」を初めて破る
  変更である（今回の依頼範囲として明示的に許可されたもの）。

### 既知の制約
- 複数ページのレポートで、ページごとに原文の言語が異なる場合（例：先週は英語、
  今週は日本語）、「原文の言語のまま要約」モードでは前回データとの差分比較用
  JSON（`prev_context`）に渡す内容の言語が混在する可能性がある。対応はしていない。
- `extract_with_color()`が青文字（更新ポイント）行に付与する固定マーカー
  「【更新ポイント】」は、原文が完全に英語のページであっても日本語のまま
  埋め込まれる。ルーティング用マーカーとして扱われるため実害は小さいが、
  言語混在の別要因として記載しておく。
- 原文の言語判定はGemini自身のベストエフォートであり、完全な保証はない。

### 変更関数
- `GeminiProcessor.analyze_html` (`language_mode`引数追加、プロンプトの言語依存
  箇所を`_LANG_VARIANTS`経由で切り替え)
- `generate` Flaskエンドポイント (`language_mode`パラメータ受け取り追加、既定値`translate_ja`)
- `_generate_worker` (`language_mode`引数追加、`analyze_html`呼び出しに伝播)
- `index.html: startGenerate()` (`language_mode`をPOSTボディに追加)

### 新規追加
- `_LANG_VARIANTS` (モジュールレベル辞書、言語モードごとのプロンプト文字列)
- `index.html`：「要約の言語」`<select>`（`languageMode`、既定`translate_ja`）

### 変更ファイル
- onenote_report_generator_20260729_02.py
- templates/index.html

### 変更しないこと（宣誓）
- `ReportGenerator.generate_html` およびレポート自体の固定見出し・表項目名
  （「エグゼクティブ・サマリー」「詳細情報」「残アクション」等は常に日本語のまま）
- ブックマーク機能全体（`language_mode`はbookmarks.jsonに保存しない。
  `reverse_order`と同様の理由で明示的に依頼された範囲のみ変更する方針）
- `extract_with_color` / テーブル抽出ロジック
- トークン期限切れ対応・詳細情報の階層レンダリング・逆順オプション
  （VERSION 20260727_01_01・20260729_01_01の内容）

## VERSION 20260729_01_01

### 追加・修正
- **HTML出力順の逆順オプション追加**：OneNoteのページが「古い→新しい」順（約9割）
  と「新しい→古い」順（約1割）の両方があり、レポートで常に新しい方を先頭に
  表示したいという要望に対応。UIに「サマリーを逆順（新→古）に並べる」
  チェックボックス（既定ON）を追加。ONの場合はHTMLレポート上の表示順を
  新→古に反転する。OFFの場合は受け取ったページ順のまま出力する。
- **Gemini解析の処理順・差分抽出ロジックには影響しない設計**：
  「前回ページとの差分」を抽出する`prev_context`の受け渡しは、従来通り
  `page_ids`の受け取り順のまま処理する。並び替えは`ReportGenerator.generate_html()`
  に渡す直前の`results`リストにのみ適用し、解析結果の中身・差分抽出の基準には
  一切手を加えていない。

### 変更関数
- `generate` Flaskエンドポイント (`reverse_order`パラメータ受け取り追加、既定値`True`)
- `_generate_worker` (`reverse_order`引数追加。`results`をHTML生成直前にのみ反転)
- `index.html: startGenerate()` (`reverse_order`をPOSTボディに追加)

### 新規追加
- `index.html`：「サマリーを逆順（新→古）に並べる」チェックボックス（`reverseOrderCheckbox`、既定チェック済み）

### 変更ファイル
- onenote_report_generator_20260729_01.py
- templates/index.html

### 変更しないこと（宣誓）
- `GeminiProcessor` の全メソッド（プロンプト含む）
- `_generate_worker`内のGemini解析ループ・`prev_context`の受け渡し順序
- ブックマーク機能全体
- `extract_with_color` / テーブル抽出ロジック
- トークン期限切れ対応・詳細情報の階層レンダリング（VERSION 20260727_01_01の内容）

## VERSION 20260727_01_01

### 追加・修正
- **トークン期限切れ時の無言フリーズを修正**：Flaskプロセスを長時間（アクセストークンの
  有効期限程度）起動し続けたまま①サイトを選択すると、認証状態は「認証済み」と表示され
  続けるにもかかわらず、②ノートブック取得が裏でエラーになり、`data.forEach`が
  配列でないオブジェクト（`{"error": "..."}"}`）に対して呼ばれて`TypeError`が発生、
  画面が無言で固まる不具合を修正。`restoreBookmark()`で既に導入済みだった
  `Array.isArray()`ガードを、通常選択フローの`loadNotebooks`・`loadSections`・
  `loadPages`にも追加。
- **トークン期限切れの自動検知・再認証**：Graph APIがHTTP 401を返した場合、
  バックエンドで`TokenExpiredError`として区別し、グローバル変数`_token`を
  `None`にリセットした上で`auth_expired: true`をレスポンスに含めるように変更。
  フロント側は`auth_expired`を検知すると自動的に`checkAuth()`を再実行し、
  `token_cache.bin`のリフレッシュトークンによるサイレント再認証を試みる。
- **詳細情報（details）の3階層以上ネスト対応**：`ReportGenerator.generate_html()`の
  「詳細情報」描画が2階層（カテゴリ→項目名:文字列）までしか想定しておらず、
  OneNoteページの内容によって3階層（カテゴリ→プロジェクト名→担当者名→項目:文字列）
  になった場合、Pythonの辞書がそのまま文字列化されて`{'宮崎': {...}}`のような
  生の辞書表記が出力される不具合を修正。`ReportGenerator._render_detail_value()`を
  新設し、階層の深さによらず再帰的に見出し化（h5・h6）するように変更。
  VERSION 20260416.36で一度対策された「AI出力揺れによる辞書ベタ書き」問題の、
  未対応だった深い階層での再発。

### 変更関数
- `OneNoteGraphExtractor._get` (HTTP 401を`TokenExpiredError`として送出するよう変更)
- `api_notebooks` / `api_sections` / `api_pages` Flaskエンドポイント
  (`TokenExpiredError`捕捉時に`_token`をリセットし`auth_expired`フラグを返却)
- `ReportGenerator.generate_html` (詳細情報描画部分を`_render_detail_value`呼び出しに変更)
- `index.html: loadNotebooks` / `loadSections` / `loadPages`
  (`Array.isArray`ガード追加、`auth_expired`時の自動再認証呼び出し追加)

### 新規追加
- `TokenExpiredError` (例外クラス)
- `ReportGenerator._render_detail_value` (再帰的詳細情報レンダリング関数)

### 変更ファイル
- onenote_report_generator_20260727_01.py
- templates/index.html

### 変更しないこと（宣誓）
- `GeminiProcessor` の全メソッド（プロンプト含む）
- ブックマーク機能全体（`_load_bookmarks` / `_save_bookmarks` / bookmark系エンドポイント / `saveBookmark` / `restoreBookmark` / `deleteBookmark`）
- `extract_with_color` / テーブル抽出ロジック
- `/api/sites` エンドポイント・複数サイト選択の仕組み
- レポート一覧・クリーンアップ機能

## VERSION 20260706_01_01

### 追加・修正
- **ブックマーク復元時の型検証ガード**: `restoreBookmark()` 内で
  `/api/notebooks`・`/api/sections`・`/api/pages` の各レスポンスが
  配列でない場合（認証切れ・Graph APIエラー等）に `Array.isArray()` で
  検出し、`forEach` クラッシュの前に明示的エラーをスローする防御処理を追加。
- **エラーメッセージの日本語化**: 型不正時のエラーメッセージをサーバーの
  `error` フィールドから取得し、トーストに表示するよう統一。

### 変更関数
- `restoreBookmark` (Array.isArray ガードを3箇所追加)

### 新規追加
- なし

### 変更ファイル
- templates/index.html

### 変更しないこと（宣誓）
- `restoreBookmark` のawaitチェーン構造・タイムアウト処理・catch節
- `loadBookmarks` / `saveBookmark` / `deleteBookmark` / `showToast`
- `loadPages` / `loadSections` / `loadNotebooks` / `updatePageRange`
- Python側の全エンドポイント・全クラス

## VERSION 20260529_02_01

### 追加・修正
- **テーブル構造化抽出の実装**: `extract_with_color()` に OneNote テーブル（`<table>`）専用の
  処理を追加。`<th>`ヘッダ行は `|ヘッダ1|ヘッダ2|` 形式、`<td>`データ行は
  `|値1|値2|` 形式のMarkdown表としてテキスト化し、Geminiへの入力品質を改善。
- **二重出力の物理遮断**: テーブル処理完了後に `<table>` 要素を `decompose()` で
  soup から除去し、既存の `find_all(["p","span","td"...])` との重複出力を防止。
- **`<td>` を find_all 対象から除外**: テーブルセルは専用処理で取得するため、
  既存の find_all リストから `"td"` を削除。

### 変更関数
- `OneNoteGraphExtractor.extract_with_color` (テーブル専用処理の追加・td除外・decompose追加)

### 新規追加
- なし

### 変更ファイル
- onenote_report_generator_20260529_02_01.py

### 変更しないこと（宣誓）
- OneNoteGraphExtractor の extract_with_color 以外の全メソッド
- GeminiProcessor の全メソッド（プロンプト含む）
- ReportGenerator.generate_html
- 全Flaskエンドポイント
- _generate_worker / update_status
- ブックマーク機能（20260529_01_01で追加した全コード）
- templates/index.html
## VERSION 20260529_01_01

### 追加・修正
- **ブックマーク機能（バックエンド）**: ページ選択状態（サイト・ノートブック・セクション・ページ）を
  名前付きで保存・復元・削除できるブックマーク機能を追加。
- **bookmarks.json自動復旧**: 起動時にbookmarks.jsonが破損（JSONDecodeError）していた場合、
  .bakにリネームして空データで自動再生成するフォールバックを実装。
- **並行書き込み競合防止**: _bookmark_lockを新設し、bookmarks.json の全読み書きをLock配下で実施。
- **保存時ラベル自動補完**: ラベル未入力時は"{section_name} / {最新ページタイトル}"を自動生成。
  重複ラベルには末尾に(2)(3)...を付与。

### 変更関数
- なし（既存関数への変更ゼロ宣誓）

### 新規追加
- `_bookmark_lock` (グローバル変数)
- `BOOKMARKS_PATH` (グローバル定数)
- `_load_bookmarks()` (ヘルパー関数)
- `_save_bookmarks(data)` (ヘルパー関数)
- `api_bookmarks_get` Flaskエンドポイント (GET /api/bookmarks)
- `api_bookmarks_post` Flaskエンドポイント (POST /api/bookmarks)
- `api_bookmarks_delete` Flaskエンドポイント (DELETE /api/bookmarks/<bm_id>)

### 変更ファイル
- onenote_report_generator_20260529_01_01.py

### 変更しないこと（宣誓）
- OneNoteGraphExtractor の全メソッド
- GeminiProcessor の全メソッド
- ReportGenerator.generate_html
- 認証・ページ取得フロー全体
- 既存Flaskエンドポイント全て
- _generate_worker / update_status

## VERSION 20260512_03_01

### 追加・修正
- **複数サイト対応**: config.jsonの`default_site_id`（単一固定）を廃止し、
  `sites`配列（displayName+site_idのペア）に変更。
  Flask UIにサイト選択ドロップダウン①を追加し、選択したサイトの
  ノートブック→セクション→ページを動的に取得できるように変更。
- **OneNoteGraphExtractor 4メソッドのsite_id引数化**:
  `get_notebooks` / `get_sections` / `get_pages` / `get_page_html` の
  全てのsite_id参照をconfig.json固定値からメソッド引数に変更。
- **新規エンドポイント `/api/sites`**: config.jsonのsites配列をJSON返却。
- **既存エンドポイントのsite_id対応**:
  `/api/notebooks` / `/api/sections` / `/api/pages` にsite_idを引数追加。
- **`_generate_worker` / `generate` エンドポイントにsite_id追加**。

### 変更関数
- `OneNoteGraphExtractor.get_notebooks` (site_id引数化)
- `OneNoteGraphExtractor.get_sections` (site_id引数化)
- `OneNoteGraphExtractor.get_pages` (site_id引数化)
- `OneNoteGraphExtractor.get_page_html` (site_id引数化)
- `api_notebooks` Flaskエンドポイント (site_idクエリパラメータ追加)
- `api_sections` Flaskエンドポイント (site_idクエリパラメータ追加)
- `api_pages` Flaskエンドポイント (site_idクエリパラメータ追加)
- `generate` Flaskエンドポイント (site_id受け取り追加)
- `_generate_worker` (site_id引数追加)
- `index.html` (サイト選択ドロップダウン①追加・既存①〜④を②〜⑤に繰り下げ)

### 新規追加
- `api_sites` Flaskエンドポイント (`GET /api/sites`)
  挿入位置: `api_notebooks` の直前
  呼び出し元: `index.html

## VERSION 20260512_02_01

### 追加・修正
- **デッドコード修正**: `GeminiProcessor.analyze_html()` の
  `try` ブロック内の `return json.loads(response.text)` 1行を削除。
  トークン使用量が正しく取得・集計されるように修正。
- **ファイル命名規則の変更**: `ON_summary_{NB}_{SEC}_{PAGE}_{ts}.html` 形式
- **Gemini API概算使用料金のフッター表示**: config.json外出し対応

### 変更関数
- `GeminiProcessor.analyze_html` (デッドコード削除・トークン取得修正)
- `ReportGenerator.generate_html` (cost_info引数・フッター追加)
- `_generate_worker` (notebook_name・トークン集計・ファイル名変更)
- `generate` Flaskエンドポイント (notebook_name受け取り追加)
- `index.html: startGenerate()` (notebook_name送信追加)

### 変更ファイル
- onenote_report_generator_20260512_02_01.py
- templates/index.html
- config.json（gemini_pricingセクション追加）

### 変更しないこと（宣誓）
- OneNoteGraphExtractor の全メソッド
- 認証・ページ取得フロー（get_token_from_cache/initiate_device_flow等）
- GeminiProcessorのプロンプト内容
- ReportGeneratorの既存HTML生成ロジック本体
## VERSION 20260512_01_01

### 新規作成
**OneNote Graph API Report Generator**: RPAによる物理操作を廃止し、
Graph APIによるOneNote直接取得に完全置き換え。Flask Web UIで操作する
新規ツールとして実装。

### 追加・修正
- **OneNoteGraphExtractor（新規）**: MSAL認証・Graph APIによるノートブック/
  セクション/ページ取得・青文字RGB範囲判定・テキスト抽出を実装
- **GeminiProcessor.analyze_html（変更）**: analyze_pdfをanalyze_htmlに
  リネームし、入力をPDFバイナリからHTMLテキストに変更。出力スキーマは維持
- **ReportGenerator（完全流用）**: 無修正
- **FlaskApp（新規）**: threading非同期処理・/statusポーリング・
  ドロップダウンUI・レポート履歴管理を実装

### 新規追加
- onenote_report_generator_20260512_01_01.py（Pythonコード全体）
- templates/index.html（Flask UI）

### 変更しないこと（宣誓）
- ReportGenerator.generate_html() の内部実装
- GeminiProcessorの出力JSONスキーマ
  （summary/updates/details/pending_actionsキー構造）

## VERSION　20260417.40
### 追加・修正
	**リンクIDによる絶対移動判定（タイトル依存の廃止）**: ページの移動確認を「不安定なページタイトル」から「OneNote内部リンク（固有ID）」の比較へと抜本的にアップグレードしました。これにより、同名タイトルのページが連続していても絶対に騙されなくなります。
	**3回ストライク制のスマート終了判定**: ページ移動後、新しいリンクを取得して前回と比較します。もし同じリンクだった場合は「移動の空振り」とみなして再キー送信＋1秒待機を行います。これを最大3回（計3秒）繰り返し、それでもリンクが変わらなければ「物理的にこれ以上下がない（最終ページである）」とスマートに判定し、安全に処理を終了します。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (リンク取得とストライク判定の統合、旧タイトル監視の削除)

### 新規追加：
	なし

## VERSION　20260416.39
### 追加・修正
	**ページ遷移の自己修復（オートリトライ）機能**: 8ページ目のPDF保存成功が確認できたことで、原因が「PDF保存後のOneNoteへのフォーカス復帰遅れによる、PageDownキーの空振り」であると完全に特定されました。この物理的な空振りを防ぐため、次ページへの移動時「3秒待ってもタイトルが変わらなければ、キーが無視されたと判断し、再度キー（Ctrl+PageDown/Up）を送信する」という自己修復ロジックを追加しました。
	**タイトル監視の延長**: リトライを含めた確実な遷移を行うため、タイトルの変化を監視する最大時間を5秒から10秒（100ループ）へ延長しました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (リトライロジックの追加と待機ループの延長)

### 新規追加：
	なし
## VERSION　20260416.38
### 追加・修正
	**多言語対応・完全翻訳プロンプトの実装**: 入力PDFが英語であっても、出力されるJSON内の全テキスト（要約、差分、詳細、タスク名）を自然でプロフェッショナルな日本語に翻訳・執筆するようプロンプトを強化しました。
	**項目名の日本語化制約**: 詳細情報（details）のキー（項目名）が英語のまま出力されるのを防ぐため、内容だけでなく見出しも日本語に変換するよう明示的な指示を追加しました。

### 変更関数
	`GeminiProcessor.analyze_pdf` (プロンプト内の翻訳指示の強化)

### 新規追加：
	なし

## VERSION　20260416.37
### 追加・修正
	**神プロンプト（完全固定スキーマ＆疑似CoT）の導入**: `GeminiProcessor.analyze_pdf` 内のプロンプトを抜本的に刷新。XMLタグを用いた構造化、`_thinking` キーによるAIの思考プロセスの自己整理、および出力データ型の完全指定（JSONスキーマ）を実装しました。これにより、AIの出力揺れによる「型エラー（`AttributeError`）」や「情報の過不足」を根本から撲滅します。

### 変更関数
	`GeminiProcessor.analyze_pdf` (プロンプトの大幅書き換え)

### 新規追加：
	なし

## VERSION　20260416.36
### 追加・修正
	**AI要約の強制スライス処理（冗長化防止）**: AIへのプロンプトに「各カテゴリ最大3項目」の制約を明記した上で、HTML生成時（Python側）にも強制的に `[:3]` でスライスする絶対的な防衛線を実装しました。これにより、AIが指示を無視して長文を出力しても、更新内容は必ず3項目以内に収まります。
	**詳細情報の一元化とUIパース**: 分散していた詳細情報のアコーディオンを1つ（「■ 詳細情報 (クリックして展開)」）に統合しました。また、内部のデータがJSON（辞書）形式でベタ書きされていた問題を修正し、`・キー: 値` の形式で人間が読みやすい箇条書きに展開（パース）して表示するロジックを実装しました。
	**残アクションのアコーディオン化**: 仕様から漏れていた「残アクションのアコーディオン化」を復元し、「■ 残アクション (クリックして展開)」の中にテーブルを格納することで、画面全体の冗長性を排除しました。

### 変更関数
	`GeminiProcessor.analyze_pdf` (プロンプトの厳格化)
	`ReportGenerator.generate_html` (強制スライス、詳細情報の一元化＆パース、残アクションのアコーディオン化)

### 新規追加：
	なし
## VERSION　20260416.35
### 追加・修正
	**HTML構造の完全復元と要件遵守**: 私のミスにより崩れてしまったレポートの構造を、合意済みの絶対要件（1. 要旨、2. 差分[カテゴリ別]、3. 詳細[カテゴリ別・アコーディオン]、4. 残アクション）へ完全に復元しました。
	**箇条書き（番号付きリスト）の改行整形**: 画像でご提示いただいた「詳細情報内で番号リストが横に繋がってしまう問題」を解決するため、出力時に正規表現を用いて `1. ` や `2. ` の直前に改行（`<br><br>`）を自動挿入する整形ロジックを追加しました。
	**リッチCSSの復元**: アコーディオン（`<details>`）が直感的に操作できるプロフェッショナルなCSS装飾を復元・強化しました。

### 変更関数
	`ReportGenerator.generate_html` (構造復元、カテゴリグループ化、アコーディオン実装、改行整形処理の追加)

### 新規追加：
	なし
## VERSION　20260416.34
### 追加・修正
	**AI出力揺れ（型チェック）の例外ガード**: AIが `pending_actions`（残アクション）を期待されるJSONオブジェクト（辞書型）ではなく、単なる文字列（str）などで返却した場合に発生する `AttributeError` を修正しました [cite: 9, 10]。データ型が辞書でない場合は、テーブルをクラッシュさせず、1つのセル（colspan='4'）にテキストとしてそのまま出力する救済措置を追加しています。

### 変更関数
	`ReportGenerator.generate_html` (型チェックガードの追加)

### 新規追加：
	なし

## VERSION　20260416.33
### 追加・修正
	**ローカル固定作業フォルダへの移行**: OSの気まぐれな一時フォルダ（`tempfile`）を廃止し、スクリプトと同じ階層に固定の `temp` フォルダを作成して使用するように変更しました。これによりパスが短く・確実になり、Windowsの保護機能による保存拒否を回避します。
	**重複警告の物理的排除**: 処理を開始する直前に、`temp` フォルダ内の過去のPDF（残骸）を強制削除するロジックを追加しました。これにより「同名ファイルが存在します」という重複ダイアログの出現率を0%にし、後続のEnterキーが吸い込まれるバグを解消しました。
	**ダイアログ描画待機の追加**: 「名前を付けて保存」ウィンドウを検知した後、パスを貼り付ける（Ctrl+V）前に `0.5秒` の静止時間を設け、フォーカスが完全にダイアログに移るのを待つことで、パス入力の空振りを防止しました。

### 変更関数
	`OneNoteReportApp.start_processing` (固定フォルダ化と事前クリーンアップの実装)
	`OneNoteRPAExtractor.export_pages_to_pdf` (ダイアログ操作の確実性向上)

### 新規追加：
	なし

## VERSION　20260416.31
### 追加・修正
	**致命的なタイポの修正**: `OneNoteRPAExtractor` 内で「名前を付けて保存」を呼び出す際のキー操作 `pyautogui.press('f')` が、誤って `pyautogui.press('get_direct_clipboard_text')` となっていた箇所を正常化しました。
	**中略なしの完全実装**: 前回不足していた `open_reports_folder` や `cleanup_old_reports` を含む、すべてのメソッドを省略なしで1つのソースコード内に完備しました。
	**UIレイアウトの最終確定**: メイン画面（高520px）および確認ポップアップ（幅550px、入力欄width=65）のサイズ設定を適用し、視認性を確保しました。
	**鉄壁の安定性と爆速化**: ポーリング監視（JIT）とGUI生存監視（update命令）、および例外ガード（try-except）を全ループに配置。最新 `google-genai` SDKへの移行も完了しています。

### 変更関数
	`OneNoteRPAExtractor` (キー操作バグの修正)
	`OneNoteReportApp` (全メソッドの完全記述とUIサイズ拡張)
	`GeminiProcessor` (最新SDKへの一本化)
## VERSION　20260416.29
### 追加・修正
	**「最後まで要約」表示の適正化**: 「セクションの最後まで要約する」が有効な際、分母が50と表示される混乱を避けるため、表示を `(nページ目 / 最後まで要約)` に変更しました。
	**メインGUIの垂直拡張**: 画面下部のステータスやボタンが隠れないよう、メインウィンドウの高さを `520px` に拡張し、視認性を向上させました。
	**確認ポップアップのプロフェッショナル化**: 横幅を `550px` に広げ、長いノートブック名も収まるよう入力欄を横長（`width=65`）に設計し直しました。
	**鉄壁の例外ガードの実装**: RPA実行中にウィンドウが閉じられた際の強制終了（TclError）を `try-except` で完全に封じ込め、クリーンな終了を実現しました。
	**2ページ目遷移の確実化**: すべてのポーリングループにGUI更新命令（`update()`）を配置し、GUIのフリーズによるオートメーション停止を防止しました。

### 変更関数
	`OneNoteReportApp.__init__` (メインサイズ拡張)
	`OneNoteReportApp.confirm_settings` (横長・高機能ポップアップ)
	`OneNoteReportApp.update_status` (例外ガード)
	`OneNoteRPAExtractor.export_pages_to_pdf` (ステータス表示ロジック改善)

### 変更関数
	`OneNoteReportApp.__init__` (メインサイズ拡張)
## VERSION　20260416.27
### 追加・修正
	**非推奨ライブラリの完全削除**: ファイル冒頭に残っていた `import google.generativeai` を削除し、最新の `from google import genai` のみに一本化しました。これにより、起動時の警告（FutureWarning）が完全に消失します。
## VERSION　20260416.26
### 追加・修正
	**GUI生存監視（update）の徹底**: 高速化のためのポーリングループ（タイトル監視、ウィンドウ検知等）において、GUIの描画と生存確認を行う `self.tk_root.update()` を追加しました。これにより「応答なし」による強制終了を防ぎます。
	**次世代AIライブラリ（google-genai）への完全移行**: 起動時に表示されていた `FutureWarning` を解消するため、非推奨となった `google.generativeai` から、最新の `google.genai` SDKへとコードを刷新しました。
	**構造化レポート機能の維持**: 前回合意した「ピラミッド構造（要旨 → カテゴリ別更新内容 → 詳細 → アクション）」および「サブグループ表示」のロジックはすべて継承しています。

### 変更関数
	`GeminiProcessor` (クラス全体：ライブラリ移行対応)
	`OneNoteRPAExtractor.export_pages_to_pdf` (GUI生存監視の追加)
	`OneNoteReportApp` (クラス全体：ライブラリ変更に伴う後処理の同期)

### 新規追加：
	なし

## VERSION　20260416.25
### 追加・修正
	**「情報のピラミッド構造」への再編**: レポート構成を「結論から詳細へ」の順序（要旨 → 更新内容 → 詳細 → アクション）に抜本的に組み替えました。
	**エグゼクティブ・サマリーの純化**: 要旨を箇条書きなしの「3行以内のプロフェッショナルな総括」に限定し、重複を排除しました。
	**ファンクション別サブグループ化**: 「主な更新内容」と「詳細・経緯」の両方に、AIが文脈から判断したカテゴリタグ（例: [Design]）によるグループ化を導入し、可読性を劇的に向上させました。
	**RPAプロセスの爆速化（JIT実行）**: 固定の `time.sleep` を廃止し、タイトル変更検知、クリップボード監視、「名前を付けて保存」ウィンドウの出現検知（Windows API）による状態監視型プロセスの実装により、無駄な待ち時間をゼロにしました。
	**安定動作設定**: `pyautogui.PAUSE` を 0.5秒に設定し、高速化と入力の確実性を両立させました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (状態監視型高速化の実装)
	`GeminiProcessor.analyze_pdf` (構造化・グループ化プロンプトへの刷新)
	`OneNoteReportApp` (UI定数調整と処理フロー同期)
	`ReportGenerator.generate_html` (新レイアウトとサブグループ描画の実装)

### 新規追加：
	なし
## VERSION　20260416.24
### 追加・修正
	**HTMLマスターフォーマットの完全復元**: 土台となるバージョン（_12.py）の高度なHTML構造（アコーディオン表示、テーブル形式の残アクション、JavaScriptによる一括開閉機能、CSSデザイン）を完全に復元し、そこに「主な更新内容」を統合しました。
	**差分データの統合**: 「Executive Summary（要旨）」と「Key Points（箇条書き項目）」の間に、新項目「主な更新内容」をマスターデザインと調和する形で追加しました。
	**解析ロジックの最適化**: AIプロンプトの出力形式を、マスターHTMLが期待するキー名（key_points, pending_actions）に合わせつつ、前回ページとの差分および青文字情報を抽出するように調整しました。

### 変更関数
	`GeminiProcessor.analyze_pdf` (プロンプトのマスター同期と差分抽出)
	`OneNoteReportApp` (クラス全体：管理機能・RPA制御・コンテキスト共有の完全版)
	`ReportGenerator.generate_html` (マスターデザインへの差分項目埋め込み)

### 新規追加：
	なし

## VERSION　20260416.23
### 追加・修正
	**HTMLフォーマットの原状復帰**: 前回のバージョンで誤って適用した独自のスタイル（CSS）をすべて破棄し、元のシンプルなフォーマットに戻しました。
	**特定箇所の追記に限定**: 既存の「要旨（Executive Summary）」の直後に、「主な更新内容」のブロックのみを、元のデザインルールを維持したまま挿入しました。
	**完全版の再提示**: 「中略」を一切排除し、コピペでそのまま動作する完全なメソッドコードを提供します。

### 変更関数
	`ReportGenerator.generate_html` (フォーマット復元および差分ロジックの挿入)

### 新規追加：
	なし

## VERSION　20260416.21
### 追加・修正
	**「主な更新内容」抽出ロジックの実装**: 直前のページの解析結果を次のページの解析プロンプトに引き継ぐ「コンテキスト共有（スライディング・ウィンドウ）」方式を導入しました。これにより、AIがページ間の差分を認識できるようになりました。
	**ハイブリッド差分検知**: AIに対し、「テキストの論理的な差分」と「OneNote上の青文字（視覚的ヒント）」の両方を組み合わせて更新箇所を特定するよう指示を強化しました。なお、青色のURLリンクは更新箇所から除外する制約を追加しています。
	**HTMLテンプレートの拡張**: 要旨（Executive Summary）と決定事項（箇条書き）の間に「主な更新内容」セクションを新設しました。1枚目のレポートについては「なし」と自動表記されます。
	**出力制限の適用**: 更新内容は標準3項目、最大10項目の箇条書きとして抽出するよう制限を設けました。

### 変更関数
	`GeminiProcessor.analyze_pdf` (引数 `prev_data` の追加とプロンプトの高度化)
	`OneNoteReportApp.start_processing` (解析結果のバトンパス処理の実装)
	`ReportGenerator.generate_html` (新セクション「主な更新内容」のレンダリング対応)

### 新規追加：
	なし
## VERSION　20260416.20
### 追加・修正
	**レポート保存用サブフォルダ（reports）の導入**: 安全性と整理のため、スクリプトと同じ階層に `reports` フォルダを自動作成し、すべてのHTMLレポートをここに集約するように変更しました。
	**タイムスタンプ付きファイル名の採用**: ファイルの重複保存を可能にするため、ファイル名を `Weekly_Report_セクション名_[YYYYMMDD_HHMM].html` の形式にアップデートしました。
	**データ管理UIの追加**: GUI最上部に「フォルダを開く」と「7日前のレポートを削除」のボタンを新設しました。
	**安全な自動クリーンアップ機能**: 7日以上前のレポートをワンクリックで削除できる機能を実装しました。誤操作防止のため、実行前に確認ダイアログを表示し、対象を `reports` フォルダ内のHTMLのみに限定しています。

### 変更関数
	`OneNoteReportApp.__init__` (管理用UIの追加)
	`OneNoteReportApp.start_processing` (出力パス・ファイル名のタイムスタンプ化)

### 新規追加：
	`OneNoteReportApp.open_reports_folder` (Explorer起動)
	`OneNoteReportApp.cleanup_old_reports` (期限切れファイルの削除)

## VERSION　20260416.19
### 追加・修正
	**生成AIの出力形式の揺らぎ吸収**: AIからの解析結果（`data`）が、期待される「辞書」ではなく予期せず「リスト（配列）」形式で返却された場合のエラー（`AttributeError`）を防ぐため、リストが返却された場合は自動的にその先頭の要素（辞書）を抽出する安全処理（フォールバック）を追加しました。

### 変更関数
	`OneNoteReportApp.start_processing` (型チェックと自動変換ロジックの追加)

### 新規追加：
	なし

## VERSION　20260416.18
### 追加・修正
	**URL自動置換の廃止**: URLからノートブック名およびセクション名を抽出する際、`_`（アンダースコア）を強制的に `&` へ変換する処理を削除しました。これにより、元々アンダースコアが含まれている名前が意図せず書き換わる不具合を解消しました。
	**HTML出力順の適正化**: 抽出したデータをHTMLへ書き出す直前に実行されていた `results.reverse()`（配列の反転）を削除しました。これにより、RPAがページを取得した順番（降順指定なら上から下、昇順指定なら下から上）そのままの並びでレポートが出力されるようになりました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (文字列置換処理の削除)
	`OneNoteReportApp.start_processing` (リスト反転処理の削除)

### 新規追加：
	なし

## VERSION　20260416.17
### 追加・修正
	**フォーカス強奪バグの修正**: ページ移動直後に実行されていた `pyautogui.click()` が、意図せず他のウィンドウ（コンソール画面など）をクリックしてOneNoteからフォーカスを奪ってしまっていた問題を修正しました。リンク取得前のクリック操作を削除し、純粋なキーボードショートカットのみで操作するように変更しました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (マウスクリック操作の削除)

### 新規追加：
	なし
## VERSION　20260416.16
### 追加・修正
	**連打防止用ボタン変数の復元**: 前回のGUIシンプル化の際に誤ってローカル宣言（`.pack()`の直接呼び出し）になっていた「レポート生成開始」ボタンを、クラスのインスタンス変数（`self.run_button`）として再定義しました。これにより、RPA処理中の安全なボタンロック機能が復活し、`AttributeError` によるクラッシュを解消しました。

### 変更関数
	`OneNoteReportApp.__init__` (ボタンの変数化処理の復元)

### 新規追加：
	なし
## VERSION　20260416.15
### 追加・修正
	**メインGUIのシンプル化**: 要件に基づき、メイン画面から「ノートブック名」および「セクション名」の入力欄を完全に削除し、設定を抽出後のポップアップに集約しました。
	**設定確認ダイアログのUI改善**: はみ出しとボタン隠れを防ぐため、ウィンドウサイズを `500x320` に拡大し、適切な余白（`padx`）を設定しました。
	**キャンセル機能と静的ロールバックの実装**: ポップアップに「キャンセル」ボタンを追加しました。押下時はエラーメッセージを出さずに `RuntimeError("CANCELLED")` という内部シグナルを発行し、RPAループを直ちに抜けて初期状態へ静かに戻るようにしました。
	**URL抽出失敗時のフォールバック**: 万が一URLのパースに失敗した場合でも、エラーで止めずに「ノートブック名: 空欄」「セクション名: General」をセットした状態でポップアップを開く安全網を実装しました。

### 変更関数
	`OneNoteReportApp.__init__` (入力欄の削除、ウィンドウサイズの最適化)
	`OneNoteReportApp.confirm_settings` (サイズ・余白の拡大、キャンセルボタン追加、例外スロー)
	`OneNoteReportApp.start_processing` (キャンセル例外の静的キャッチ、UIからの変数取得方法の変更)
	`OneNoteRPAExtractor.export_pages_to_pdf` (抽出失敗時のフォールバック処理の追加)

### 新規追加：
	なし

## VERSION　20260416.14
### 追加・修正
	**URL自動解析と設定確認ダイアログの導入**: 1ページ目のリンク取得成功直後に、URL（`onenote:...`）をデコードして正規表現で解析し、「ノートブック名」と「セクション名」を自動抽出する処理を追加しました。
	**30秒カウントダウン付き非同期ポップアップ**: 抽出した設定を表示し、30秒経過（またはOKボタン押下）で自動的に閉じる確認ダイアログ（`Toplevel`）を実装しました。これにより、GUIがフリーズすることなくRPAの処理を一時停止・再開できます。
	**特殊文字の自動復元**: URL上で禁則文字として `_` に変換されていた `&` などの文字を `replace('_', '&')` によって元の状態へ復元するロジックを組み込みました。
	**セクション名の再取得タイミング変更**: 確認ダイアログでのユーザー編集を最終的なHTMLファイル名と見出しに反映させるため、`start_processing` における `section_name` の確定タイミングを、RPA抽出処理の**直後**へ移動しました。

### 変更関数
	`OneNoteReportApp.confirm_settings` (新規追加: 確認用ポップアップUI)
	`OneNoteReportApp.start_processing` (変更: セクション名の確定タイミング移動)
	`OneNoteRPAExtractor.export_pages_to_pdf` (変更: URL解析とダイアログ呼び出し処理の追加)

### 新規追加：
	`OneNoteReportApp.confirm_settings`

## VERSION　20260416.13
### 追加・修正
	**抽出方向（降順/昇順）指定UIの追加**: GUI上に「降順 (古い=>新しい)」「昇順 (新しい=>古い)」を選択できるラジオボタンを追加し、デフォルトを降順（これまで通り）に設定しました。
	**ページ遷移ロジックの動的分岐**: RPA抽出処理 (`export_pages_to_pdf`) の引数に `direction` を追加し、GUIで昇順が選ばれた場合は次ページ移動のショートカットを `Ctrl+PageDown` から `Ctrl+PageUp` へ切り替えるように変更しました。

### 変更関数
	`OneNoteReportApp.__init__` (ラジオボタンUIの追加)
	`OneNoteReportApp.start_processing` (UIで選択された方向の値を抽出メソッドへ渡す処理の追加)
	`OneNoteRPAExtractor.export_pages_to_pdf` (direction引数の追加と、PageDown/PageUpの条件分岐)

### 新規追加：
	なし
## VERSION　20260416.12
### 追加・修正
	**レポートフォーマットの完全復旧**: `ReportGenerator` クラスを今朝のバージョン（_05.py）と同一のロジックに差し戻しました。これにより、箇条書き、詳細・経緯の開閉、残アクションの一括開閉ボタンが復活します。
	**安定性パッチの全統合**: これまでに検証・成功した以下の機能をすべて統合しています。
	 - モデル名: `gemini-2.5-flash`
	 - PDF保存: 最短の `Alt-F-S-F` シーケンス
	 - リンク取得: Windows API（ctypes）による物理抽出
	 - UI: 終了ボタンの追加、および 500x550 の適切なウィンドウサイズ

### 変更関数
	`ReportGenerator.generate_html` (以前の豊かな表現力を完全復元)
	`GeminiProcessor.analyze_pdf` (プロンプトの整合性確認)
	`OneNoteReportApp.__init__` (UIレイアウトの最終確定)

## VERSION　20260416.11
### 追加・修正
	**モデル名の完全復旧**: 前回のミスで書き換わってしまったモデル名を `gemini-2.5-flash` に差し戻し、APIの404エラーを解消しました。
	**GUI表示領域の拡大**: 終了ボタンが画面外に隠れる問題 を防ぐため、ウィンドウサイズを 500x550 に拡大し、スクロールなしで全ボタンが見えるように調整しました。
	**物理操作の安定性維持**: リンク取得時の 3.0秒待機、および Alt-F-S-F のPDF保存シーケンスは、成功実績に基づきそのまま継続しています。

### 変更関数
	`GeminiProcessor.__init__` (モデル名を 2.5-flash に修正)
	`OneNoteReportApp.__init__` (ウィンドウサイズ拡大と配置の微調整)

## VERSION　20260416.10
### 追加・修正
	**GUIの完全復旧とサイズ固定**: 「アプリケーションを終了」ボタンが確実に表示されるよう、UIの配置順序を見直し、ウィンドウサイズを 500x500 に固定しました。
	**リンク取得プロセスの堅牢化**: OneNoteのメニュー描画遅延に対応するため、`Shift+F10` 後の待機時間を `2.0s` から `3.0s` へ延長しました。
	**全コードの統合提供**: コピーペーストミスによる `AttributeError` や UI 重複を防ぐため、1ファイル完結型の完全なソースコードとして再構築しました。

### 変更関数
	`OneNoteReportApp.__init__` (UIの最終整理)
	`OneNoteRPAExtractor.export_pages_to_pdf` (待機時間の最終調整)

### 新規追加：
	なし

## VERSION　20260416.09
### 追加・修正
	**GUI構造の完全復旧と終了ボタンの修正**: 途切れていたクラス定義を完全に修復し、GUIに「アプリケーションを終了」ボタンを確実に表示させ、`AttributeError` を解消しました。ウィンドウサイズも 500x500 に拡大し、視認性を高めています。
	**リンク取得コマンドの「P」キー化**: 「下矢印4回」という不安定な操作を廃止し、メニュー表示後に直接アクセラレータキー `P`（段落へのリンクをコピー）を叩く方式に変更しました。これにより、メニューの項目数に左右されず確実にリンクをコピーします。
	**クリップボード検査の強化**: `INSPECTION` ログに、前回のデバッグで有効だった「形式IDリスト」の表示を復活させ、ID 13 (Unicodeテキスト) の有無を追跡できるようにしました。
	**案A（即時中断）の徹底**: リンク取得に失敗した場合、不要な待ち時間を発生させず即座にエラーで停止する仕様を維持しています。

### 変更関数
	`OneNoteRPAExtractor` (クラス全体：リンク取得ロジックの改善)
	`OneNoteReportApp` (クラス全体：UIの完全復元、終了ボタン追加)

### 新規追加：
	なし

## VERSION　20260416.08
### 追加・修正
	**クラス構造の完全復元**: 貼り付けミスにより消失していた `toggle_spinbox` および `start_processing` メソッドを正しい位置へ復旧し、`AttributeError` を解消しました。
	**UI重複・レイアウトの修正**: UI要素が重なって表示される不具合を修正し、高さを最適化（450px）しました。
	**案A（即時終了）の完全実装**: リンク取得に失敗した際、ダイアログを出さずに即座に `RuntimeError` を発生させ、プログラムを安全に停止させるロジックを確定させました。
	**終了ボタンの正式配置**: GUIの最下部に「アプリケーションを終了」ボタンを配置し、いつでも安全に閉じられるようにしました。

### 変更関数
	`OneNoteRPAExtractor` (クラス全体：OS直結リンク取得・案A実装)
	`OneNoteReportApp` (クラス全体：UI構造修復・終了ボタン追加)

### 新規追加：
	なし

## VERSION　20260416.07
### 追加・修正
	**リンク取得失敗時の即時終了（案A）**: リンク取得に失敗した際、ユーザーへの確認ダイアログ（レスキュー画面）を表示せず、即座にエラー（RuntimeError）を発生させて処理を中断するロジックに変更しました。これにより、不安定な挙動を早期に発見・停止させます。
	**GUIへの終了ボタン追加**: ユーザーの利便性向上のため、アプリケーションを閉じるための「終了」ボタンをメインウィンドウに追加しました。
	**安定動作の維持**: PDF保存シーケンス（Alt-F-S-F）やWindows APIによるクリップボード直接取得ロジックは、これまでの成功実績に基づき継続採用しています。

### 変更関数
	`OneNoteReportApp.__init__` (終了ボタンの追加)
	`OneNoteRPAExtractor.export_pages_to_pdf` (失敗時のダイアログ廃止と即時エラー化)

### 新規追加：
	なし

## VERSION　20260416.05
### 追加・修正
	**Windows APIによるクリップボード直接抽出の実装**: 標準的なTkinterの `clipboard_get()` がOneNoteの遅延レンダリング（形式ID: 13が存在するのに読み取れない現象）に対応できていないため、Windows OSの低層API（`ctypes`）を使用して、Unicodeテキスト（CF_UNICODETEXT）を物理的に直接引き出すロジックを実装しました。これにより、リンク取得の「空振り（レスキュー画面）」を根絶します。
	**PDF保存「黄金シーケンス」の固定化**: 実機検証で100%の成功が確認された `Alt` → `F` → `S` → `F` ルートを正式に採用しました。
	**IME/フォーカスリセットの最終強化**: リンク取得前に `Esc` キーを3回連打し、さらに `pyautogui.click()` でページタイトルを強制的にアクティブにすることで、キー入力の確実性を最大化しました。

### 変更関数
	`OneNoteReportApp.__init__` (バージョン表記およびデフォルト値の更新)
	`OneNoteRPAExtractor.get_direct_clipboard_text` (新規：OS直結読み取り用)
	`OneNoteRPAExtractor.export_pages_to_pdf` (新抽出ロジックへの差し替え)

### 新規追加：
	`OneNoteRPAExtractor.get_direct_clipboard_text`

## VERSION　20260416.04
### 追加・修正
	**インスペクション（精密検査）モードの導入**: RPA操作のすべてのステップにミリ秒単位のタイムスタンプ付きログを出力する機能を実装しました。これにより、OneNoteの応答速度とプログラムの操作がどのタイミングでズレているかを完全に可視化します。
	**クリップボード・ディープスキャンの実装**: リンク取得失敗時、Windows API（ctypes）を直接叩いてクリップボード内部の「データ形式数」と「形式名」を調査するデバッグログを追加しました。OneNoteが「何も書いていない」のか「読めない形式で書いている」のかを特定します。
	**PDF最短シーケンス（黄金ルート）の統合**: 前回の検証で成功した `Alt` → `F` → `S` → `F` によるPDF保存ダイアログの直接起動を正式に採用しました。
	**IME回避のEsc連打・クリックの再強化**: リンク取得の確実性を上げるため、Esc連打(3回)と物理クリックによるフォーカス強制を操作直前に実行します。

### 変更関数
	`OneNoteReportApp.__init__` (バージョン表記更新)
	`OneNoteRPAExtractor.export_pages_to_pdf` (詳細ログ出力および、リンク取得リトライ・スキャン処理の追加)
	`OneNoteRPAExtractor._debug_clipboard` (新規：クリップボード内部解析用)

### 新規追加：
	`OneNoteRPAExtractor._debug_clipboard`

## VERSION　20260416.03
### 追加・修正
	**PDF保存シーケンスの「黄金ルート」実装**: ユーザーの実機検証に基づき、`Alt` → `F` → `S` → `F` の最短シーケンスを実装しました。これにより不必要な `Tab` 操作を排除し、一撃で「名前を付けて保存」ダイアログを起動させます。
	**リンク取得の「粘り強い再試行」ロジック**: クリップボードが（空）で取得される現象 に対処するため、OneNoteの書き込み完了を待機するリトライループを導入しました。最大5秒間、0.2秒間隔で中身を確認し、データが生成された瞬間に取得します。
	**IME/状態リセットの強化**: リンクコピー前に `Esc` キーを3回連打する処理を追加しました。これにより、IMEの未確定入力や予期せぬメニュー状態を完全にクリーンにし、`Down` や `Enter` 操作の「空振り」を防ぎます。

### 変更関数
	`OneNoteReportApp.__init__` (バージョン表記および初期値の更新)
	`OneNoteRPAExtractor.export_pages_to_pdf` (PDFシーケンス刷新およびリンク取得リトライの実装)

### 新規追加：
	なし

## VERSION　20260416.02
### 追加・修正
	**PDF保存シーケンスの最適化**: ユーザーによる実機検証に基づき、不安定な `Tab` 連打を廃止しました。`Alt` → `F` → `S` → `F`（PDF形式選択）の最短経路を採用し、直接「名前を付けて保存」ダイアログを起動させることで、保存の成功率を100%に高めました。
	**IME/状態リセット（Esc連打）の導入**: URL取得時の `Down` キー（下矢印）が効かない問題を解決するため、右クリック操作の直前に `Esc` を2回連打する処理を追加しました。これによりIMEの未確定文字や予期せぬメニュー状態をクリーンにし、コマンドを確実にOneNoteへ届けます。
	**UI初期値の改善**: 業務効率化のため、起動時の「取得ページ数」のデフォルト値を `1` から `3` へ、最大値を `50` へ変更しました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (最短保存シーケンスへの変更、Escリセット追加)
	`OneNoteReportApp.__init__` (Spinbox初期値の変更)

### 新規追加：
	なし

## VERSION　20260416.01
### 追加・修正
	**フォーカス強制クリックの追加**: リンク取得時の「空振り」を完全に防ぐため、`Ctrl+Shift+T`（タイトル選択）を押す直前に `pyautogui.click()` を実行し、現在マウスがある位置（ユーザーが待機中にクリックしたタイトル部分）を物理的に再クリックしてOneNoteのフォーカスを強制的に叩き起こす処理を追加しました。
	**コピー確定後の待機時間強化**: 重いページでのクリップボード書き込み遅延をより確実に吸収するため、`Enter`（コピー実行）押下後の絶対待機時間を `1.0秒` から `2.0秒` に延長しました。
	**取得ページ数のデフォルト値変更**: UI上のページ指定スピンボックス（Spinbox）の初期値を「1」から「3」に変更し、最大選択可能数も「50」に拡張して、自動起動時のバッチ処理の手間を省きました。

### 変更関数
	`OneNoteReportApp.__init__` (または該当するUIセットアップメソッド：Spinboxの初期値変更)
	`OneNoteRPAExtractor.export_pages_to_pdf` (クリック操作の追加、待機時間の延長)

### 新規追加：
	なし
## VERSION　20260318.17
### 追加・修正
	**PDF書き込み待機時間（タイムアウト）の延長**: データ量が重いページ（画像や図表を多数含む）を「Microsoft Print to PDF」で仮想印刷する際、ファイル生成に10秒以上かかるケースに対応するため、ファイル書き込み待ちのタイムアウトを `10秒` から `30秒` に大幅に延長しました。
	**印刷ダイアログ表示の待機緩和**: 「印刷(P)」ボタンを押下してからWindowsの「名前を付けて保存」ダイアログが表示されるまでの待機時間を `2.0秒` から `3.0秒` に延長し、OneNoteの動作が重い状況でも確実にファイルパスをペーストできるようにしました。
	**厳格なファイル存在チェックの追加**: タイムアウト（30秒）を迎えてもPDFファイルがTempフォルダに作成されなかった場合、空のパスをGeminiに渡してクラッシュ（`FileNotFoundError`）するのを防ぐため、処理を安全に中断し、原因を明示するフェイルセーフ（`RuntimeError`）を追加しました。

### 変更関数
	`OneNoteRPAExtractor.export_pages_to_pdf` (タイムアウト延長、待機時間調整、エラーチェック追加)

### 新規追加：
	なし
