# CHANGELOG — ppt_translator

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

> **置き場所について**: 20260812_01 から、実機の置き場所を
> `PythonScripts\excel\`（単独ファイル）から `PythonScripts\Powerpoint\ppt_translator\`
> （専用フォルダ）へ移した。フォルダ名は `ppt_translator`、スクリプトのファイル名の接頭辞は
> `ppt_translation` のままである（起動用バッチのワイルドカードを書くときに間違えやすい）。

## [20260911_01] - 2026-09-11

**追加ファイル:** `ppt_translation_20260911_01.py`

**更新ファイル:** `README.md`, `CHANGELOG.md`

**リネームしたファイル:** `tests/test_ppt_translation_20260812_01.py` →
`tests/test_ppt_translation_20260911_01.py`（テストは常に最新版を対象にする運用のため。
`pdf_translator` もスクリプトは2版併存・テストは1つという構成になっている）

翻訳後のファイル名に付く言語部分を、翻訳先言語そのままから**2文字の言語コードへ短縮**した
（ユーザー依頼による）。

```
旧: 資料_gemini_japanese.pptx / 資料_gemini_english.pptx / 資料_gemini_chinese.pptx
新: 資料_ja.pptx            / 資料_en.pptx            / 資料_cn.pptx
```

- `LANGUAGE_SUFFIX_MAP`（日本語 `ja` / 英語 `en` / 中国語簡体字 `cn` / 韓国語 `ko`）と
  `lang_to_suffix()` を新規追加した。表に無い言語は先頭2文字を小文字にして使う。
  `pdf_translator` の同名関数と同じ考え方に揃えてある。
- 変更したのは `translate_ppt_document_thread` の出力パス組み立て2行だけ。
  旧: `lang_code = target_language.split()[0].lower()` →
  新: `lang_suffix = lang_to_suffix(target_language)`
- **翻訳処理・書式保持・Gemini呼び出しには一切手を入れていない。** ASTによる関数単位の
  ハッシュ比較で、24個の関数・クラス（`_CommonGeminiClient` / `gemini_credentials_available` /
  `init_gemini` / `translate_batch_gemini` / `translate_super_fast_parallel` /
  `WordProgressWindow` / `select_file` など）が `20260812_01` と**完全一致**することを確認済み。
  変更は `translate_ppt_document_thread` 1つ、新規は `lang_to_suffix` 1つだけ。

### 申し送り

- **出力ファイル名が変わる。** 旧版で作った `_gemini_japanese.pptx` は消えないので、
  同じ資料を新版で翻訳すると `_ja.pptx` が別ファイルとしてできる（上書きはされない）。
  過去の翻訳済みファイルを参照している手順書やリンクがあれば、影響を確認すること。
- **中国語簡体字は `cn` にした（ユーザー指定）。** `pdf_translator` は同じ言語に `zh`
  （ISO 639-1）を使っているため、ツール間で綴りが揃っていない。
  また `excel_translation` は日本語に `jp`、中国語簡体字に `zh` を使っている。
  揃えるかどうかは未決（依頼があれば対応する）。
- `run_ppt_translator.bat` は変更不要。フォルダ内で最も新しい
  `ppt_translation_????????_??.py` を自動で選ぶため、`20260911_01` が起動対象になる。

### テスト

`tests/test_ppt_translation_20260911_01.py`（**106項目、すべて合格**）。
`20260812_01` の95項目に、今回の変更ぶん11項目を追加した。

- `lang_to_suffix()` の変換（`Japanese`→`ja` / `English`→`en` /
  `Chinese Simplified`→`cn` / `Korean`→`ko`）、未知の言語のフォールバック、前後空白の除去
- 日本語・英語・中国語簡体字それぞれで、**実際に合成PPTXを翻訳して出力ファイル名を確認**
  （`_ja.pptx` / `_en.pptx` / `_cn.pptx`）
- **旧仕様の長い名前（`_gemini_japanese.pptx`）では出力されない**こと
- 日本語以外ではフォント名を `游ゴシック` に変えないこと（既存仕様の回帰確認）
- 移行前の `ppt_translation_20260309_03.py` と新版に同じ翻訳文を与えると、**出力PPTXの
  run 構成・テキスト・書式・フォント名が完全一致する**こと
  （＝ファイル名だけが変わり、中身は変わっていないことの証明）

### 未検証（実機での確認が必要）

Linuxコンテナからは共通モジュールにも自宅PCプロキシにも到達できないため、**実際にプロキシ経由で
Geminiの応答が返るところは未確認**。ただし Gemini 呼び出し部分は `20260812_01`（実機確認済み）から
1文字も変えていない。実機では次を確認すること。

1. `PythonScripts\Powerpoint\ppt_translator\` に `ppt_translation_20260911_01.py` を追加する
   （既存の `20260812_01` は消さなくてよい）
2. `run_ppt_translator.bat` から起動し、`Target script:` に `20260911_01` が表示されること
3. 翻訳結果が `元ファイル名_ja.pptx` で保存されること

## [20260812_01] - 2026-08-12

**追加ファイル:** `ppt_translation_20260812_01.py`, `tests/test_ppt_translation_20260812_01.py`

**新規作成ファイル:** `requirements.txt`, `run_ppt_translator.bat`, `README.md`, `CHANGELOG.md`
（20260309_03 まではスクリプト1ファイルのみで、付随ファイルは存在しなかった）

会社PCからGemini APIへの直接アクセスが遮断された（2026-08-10頃）ことへの対応。共通モジュール
`gemini_client.py` の `generate_advanced()` を経由し、直接呼び出しが失敗したら自宅PCのプロキシへ
自動フォールバックする方式へ移行した（`rtocs_organizer` / `analog_ic_se_strategy_organizer` /
`outlook_total_organizer` / `excel_translation` / `pdf_translator` と同じ方式。本ツールで5ツール目）。

- **本ツール固有の事情**: 旧版は起動時の `init_gemini()` で `genai.list_models()` を呼んで
  使用可能モデルを自動検出していた。これはネットワークアクセスを伴うため、遮断下では必ず例外に
  なり「API初期化エラー」ダイアログを出して `sys.exit(1)` していた。つまり本ツールは、移行しない
  限り**起動すらできない**状態だった（`pdf_translator` と全く同じ構図）。自動モデル検出は廃止し、
  固定モデル名を使う方式へ変更した。
  - **副作用（申し送り）**: モデル名を自動で拾わなくなるため、指定モデルが使えない環境では404が
    出るようになる。既定の `gemini-2.5-flash` は他4ツールで実績があるため実害はまず無いが、
    将来モデル名が変わった場合は手で更新が必要。環境変数 `GEMINI_MODEL` で上書きできる。
- 旧SDK `google.generativeai` への依存を廃止した。`genai.Client` と同じインターフェースだけを持つ
  薄い互換シム（`_CommonGeminiClient`）を1つ用意し、クライアント生成箇所だけを差し替えている。
  これにより、レスポンス解析（`[番号] 訳文` の正規表現パース）・3回リトライ・3バッチ連続エラーでの
  フェイルファスト・進捗表示のロジックは一切変更していない。
- `safety_settings`（BLOCK_NONE ×4）は、REST APIの `safetySettings` としてpayloadへ載せるように
  した。載せ忘れると資料の内容によっては応答が空になり、「一部のバッチだけ翻訳されない」という
  切り分けにくい症状になるため、シム側で明示的に転送している。
- 空応答の判定に使っている `response.parts` を維持するため、シムのレスポンスにも `.parts` を
  持たせた（空応答なら `[]` を返すので、従来の「空なら `ValueError` を投げてリトライ」という挙動が
  そのまま保たれる）。
- **挙動差**: `request_options={"timeout": 40}` は共通モジュールに同等の機能が無いため削除した。
  タイムアウトは `gemini_client.py` 側の固定値（直接15秒／プロキシ60秒）になる。遮断下では最初の
  バッチだけ直接呼び出しの15秒タイムアウトを待つぶん遅くなるが、一度失敗すると以降はプロキシ直行に
  なるため2バッチ目以降は影響しない（**仕様どおりの挙動であり、不具合ではない**）。
- **PowerPointの処理は1行も変更していない。** スライド走査・表セル／スピーカーノートの収集・
  run単位の書き戻し・進捗ウィンドウ・ファイル選択はそのまま。ASTによる関数単位のハッシュ比較で、
  13個の関数・クラス（`translate_ppt_document_thread` / `translate_super_fast_parallel` /
  `WordProgressWindow` / `select_file` / `is_translatable` / `get_logger` など）が旧版と
  **完全一致**することを確認済み。変更したのは `check_dependencies` / `init_gemini` /
  `translate_batch_gemini` の3つだけ（`pdf_translator` でも全く同じ3つだった）。

### 新規作成した付随ファイル

- `requirements.txt`: `python-pptx` と `requests` を記載した（`requests` は `gemini_client.py` が
  使用する）。`run_ppt_translator.bat` は専用のvenvを作ってここに書かれたものだけを入れるため、
  `requests` を書き忘れると起動はするがAI呼び出し時に失敗する。旧SDK `google-generativeai` は
  20260812_01 以降不要。
- `run_ppt_translator.bat`: 初回のみvenvを作成して `pip install -r requirements.txt` を実行し、
  フォルダ内で最も新しい `ppt_translation_????????_??.py` を自動起動する。認証情報は
  **`GEMINI_API_KEY` と `GEMINI_PROXY_URL` の両方が未設定のときだけ**警告する
  （プロキシ専用構成も正常な構成のため）。
  - **このファイルは絶対にASCIIのみで書くこと。** 日本語を入れると日本語版WindowsのcmdがShift-JIS
    として解釈し、マルチバイト文字の隣にあるASCIIキーワード（`goto` 等）まで壊れて起動しなくなる。
    `chcp 65001` では直らない（`pdf_translator` で実際に踏んだ問題）。
- `README.md`: 環境変数（`GEMINI_API_KEY` / `GEMINI_PROXY_URL` の**どちらか一方以上**）、
  `gemini_client.py` の探索パス（上位の `common` を1つ上・2つ上・3つ上の順に自動探索）、
  モデルが固定になったことと `GEMINI_MODEL` での上書き方法、「最初のバッチだけ遅い」のは仕様で
  あることを記載した。
- `CHANGELOG.md`: 本ファイル。

### テスト

検証用に `tests/test_ppt_translation_20260812_01.py`（95項目）を追加した。偽の `gemini_client` を
差し込んでpayloadを捕捉する方式で、実際のGemini APIに接続せずに検証できる。`python-pptx` は本物を
使い、合成PPTX（タイトル＋本文＋表＋スピーカーノート。run ごとにフォントサイズ・太字・色・段落配置を
設定）を生成してエンドツーエンドで確認している。

- **旧版と新版に同じ翻訳文を与えると、出力PPTXの run 構成・テキスト・書式・フォント名が完全一致する**
  ことを確認済み（＝PowerPoint出力への影響がゼロであることの直接的な証拠）。
  なおPPTX（zip）はタイムスタンプが毎回変わるためバイト単位の比較はできないので、run 単位で比較している。
- **run 単位の書式（`font.size` / `font.bold` / `font.color.rgb` / 段落の配置）が翻訳前後で完全一致**
  すること。表のセル・スピーカーノートも翻訳対象として拾えていること。日本語指定時に
  `run.font.name` が `游ゴシック` になること。
- `init_gemini()` がネットワークアクセスなしで成功すること（ソケット生成を禁止した状態で検証。
  `list_models()` を消せている証拠）。
- `safetySettings` が4カテゴリ分そのまま載ること、`temperature: 0.1` が `generationConfig` へ
  camelCaseで載ること、`model` が明示的に渡ること。
- 空応答・通信失敗時に3回リトライして原文へフォールバックすること、3バッチ連続エラーで
  フェイルファストすること、進捗コールバックが従来どおり呼ばれること。
- 認証情報判定の4パターン（**`GEMINI_PROXY_URL` のみでも通る**ことが最重要）。
- 共通モジュール未配置時に「探索したパス」と `GEMINI_COMMON_DIR` の案内を含むエラーが出ること。
- 共通モジュールの探索が「2つ上が common」（新しい置き場所）でも「1つ上が common」（移行元の
  `PythonScripts\excel\`）でも解決すること。

### 未検証（実機での確認が必要）

Linuxコンテナからは共通モジュールにも自宅PCプロキシにも到達できないため、**実際にプロキシ経由で
Geminiの応答が返るところは未確認**。実機では次を確認すること。

1. 新フォルダ `PythonScripts\Powerpoint\ppt_translator\` に5ファイルを配置する
2. `GEMINI_API_KEY` / `GEMINI_PROXY_URL` を設定後、**コマンドプロンプトを開き直してから**起動する
3. **起動できること**（移行前は初期化の時点で落ちていた）
4. 実際にPPTXを翻訳し、`translation_debug.log` と画面に `[gemini_client]` のログが出たうえで
   翻訳結果が返ること
5. フォント・色・配置・表・スピーカーノートの書式が従来どおり保持されていること
6. 初回バッチだけ遅くなる場合があるが仕様であること

## [20260309_03] - 2026-03-09

移行前の最終版（`PythonScripts\excel\ppt_translation_20260309_03.py`）。この版までは
スクリプト1ファイルのみで運用しており、付随ファイル（`requirements.txt` / 起動用バッチ /
`README.md` / `CHANGELOG.md`）は存在しなかった。以下は当時のファイル冒頭の docstring より。

- **進捗の可視化とUIハングアップ対策**: 並列処理エンジンがバッチ（10項目）を処理するごとに
  プログレスバーを更新するコールバック関数を導入し、画面上で進捗がリアルタイムに確認できるように
  変更した（根拠：0%で固まって見えるUIの欠陥を解消するため）。
- **APIタイムアウトとリトライ機構**: `generate_content` に40秒のタイムアウトを設定し、失敗時は
  「3回・3秒間隔」で再試行するロジックを追加した（根拠：APIの応答遅延による無限フリーズを防ぐため）。
- **フェイルファスト（即時撤退）と強制切断**: 3バッチ連続でエラーが発生した場合、残りの処理を即座に
  キャンセル（スレッド待機フラグによる安全停止）し、エラーメッセージを出して終了する安全装置を
  追加した（根拠：API障害時に無駄なリクエストを送り続けるゾンビ化を防ぐため）。
- **デバッグ用ログ（LOG）出力**: 処理の足跡と通信エラーの詳細を `translation_debug.log` に記録し、
  コンソールにも出力するロギング機構を追加した（根拠：問題切り分けの証拠を残すため）。
- **ファイルロックの事前検知**: 翻訳処理を開始する前に、出力先ファイルの書き込み権限をチェックし、
  ロックされている場合は即座に警告を出す処理を追加した（根拠：数分間のAPI処理が終わった直後に
  WinError 32 で落ちる悲劇を防ぐため）。

### 既知の挙動（移行スコープ外。触っていない）

実機で気になったときに「移行のせいではない」と切り分けられるよう記録しておく。

- `translate_super_fast_parallel()` … チャンクが例外で失われたとき `[""] * batch_size` で埋めるため、
  最終チャンクだと翻訳結果の件数が合わなくなりうる。
- `WordProgressWindow` … PowerPointのツールなのにクラス名が `Word` のまま（Word版から流用した名残）。
  動作に影響はない。
- 出力ファイル名 … `target_language.split()[0].lower()` を使うため `_gemini_japanese.pptx` になる
  （`pdf_translator` の `_ja.pdf` のような2文字コードではない）。既存の出力名が変わると運用に影響
  するため、依頼が無い限り変更しない。
