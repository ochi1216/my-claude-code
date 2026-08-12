# CHANGELOG — word_translator

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

> **フォルダ名とファイル名の接頭辞が違う点に注意**: フォルダ名は `word_translator`、
> スクリプトのファイル名の接頭辞は `word_translation` である（起動用バッチのワイルドカードを
> 書くときに間違えやすい。`ppt_translator` / `ppt_translation` と同じ罠）。

## [20260812_01] - 2026-08-12

**追加ファイル:** `word_translation_20260812_01.py`, `tests/test_word_translation_20260812_01.py`

**新規作成ファイル:** `requirements.txt`, `run_word_translator.bat`, `README.md`, `CHANGELOG.md`
（20260306_01 まではスクリプト1ファイルのみで、付随ファイルは存在しなかった）

会社PCからGemini APIへの直接アクセスが遮断された（2026-08-10頃）ことへの対応。共通モジュール
`gemini_client.py` の `generate_advanced()` を経由し、直接呼び出しが失敗したら自宅PCのプロキシへ
自動フォールバックする方式へ移行した（`rtocs_organizer` / `analog_ic_se_strategy_organizer` /
`outlook_total_organizer` / `excel_translation` / `pdf_translator` / `ppt_translation` と同じ方式。
本ツールで6ツール目）。

- **本ツール固有の事情**: 旧版は起動時の `init_gemini()` で `genai.list_models()` を呼んで
  使用可能モデルを自動検出していた。これはネットワークアクセスを伴うため、遮断下では必ず例外に
  なり「API初期化エラー」ダイアログを出して `sys.exit(1)` していた。つまり本ツールは、移行しない
  限り**起動すらできない**状態だった（`pdf_translator` / `ppt_translation` と全く同じ構図。
  なお本ツールの `init_gemini` は移行前の `ppt_translation_20260309_03.py` の同名関数と
  1文字も違わない完全一致だったため、症状も同一）。自動モデル検出は廃止し、固定モデル名を使う
  方式へ変更した。
  - **副作用（申し送り）**: モデル名を自動で拾わなくなるため、指定モデルが使えない環境では404が
    出るようになる。既定の `gemini-2.5-flash` は他5ツールで実績があるため実害はまず無いが、
    将来モデル名が変わった場合は手で更新が必要。環境変数 `GEMINI_MODEL` で上書きできる。
- 旧SDK `google.generativeai` への依存を廃止した。`genai.Client` と同じインターフェースだけを持つ
  薄い互換シム（`_CommonGeminiClient`）を1つ用意し、クライアント生成箇所だけを差し替えている。
  これにより、レスポンス解析（`[番号] 訳文` の正規表現パース）・並列処理・進捗表示のロジックは
  一切変更していない。
- `GEMINI_API_KEY` が未設定だと起動を止めていたガードを、`gemini_credentials_available()`
  （`GEMINI_API_KEY` と `GEMINI_PROXY_URL` の**どちらか一方でもあれば通す**）へ差し替えた。
  移行後は「APIキーは無いがプロキシURLはある」という構成も正常な構成であり、旧ガードのままだと
  その構成で全機能が死ぬため。
- `check_dependencies()` の `google-generativeai` チェックを共通モジュールのチェックへ差し替えた。
  共通モジュールは `pip install` で入るものではないため、`pip install ...` を案内する一覧には
  混ぜず、**探索したパス**と `GEMINI_COMMON_DIR` の案内を含む専用のエラーを出す（他ツールと同じ形）。
  `python-docx` のチェックはそのまま残している。
- `safety_settings`（BLOCK_NONE ×4）は、REST APIの `safetySettings` としてpayloadへ載せるように
  した。載せ忘れると資料の内容によっては応答が空になるが、**本ツールは空応答のとき原文をそのまま
  返すだけ**なので、「一部の段落だけ翻訳されていない」という気づきにくい症状になる。そのため
  シム側で明示的に転送している。
- 空応答の判定に使っている `response.parts` を維持するため、シムのレスポンスにも `.parts` を
  持たせた（空応答なら `[]` を返すので、従来の「空ならそのバッチは原文を返す」という挙動が
  そのまま保たれる）。
- **挙動差（タイムアウト）**: 旧版はタイムアウトを指定していなかった（`request_options` 自体が
  無い）ため旧SDKの既定に従っていたが、移行後は `gemini_client.py` 側の固定値
  （直接15秒／プロキシ60秒）になる。呼び出し側から指定する口は無い。遮断下では最初のバッチだけ
  直接呼び出しの15秒タイムアウトを待つぶん遅くなるが、一度失敗すると以降はプロキシ直行になるため
  2バッチ目以降は影響しない（**仕様どおりの挙動であり、不具合ではない**）。
  - ただし**本ツールにはリトライ機構が無い**ため、初回バッチが15秒で失敗した場合、そのバッチは
    その場で原文のまま返る（＝「最初の10項目だけ英語のまま」という症状になりうる）。これは移行で
    新たに生じたリスクではなく、20260306_01 から続く構造だが、実機で報告されたときの切り分け用に
    記録しておく。
- **Wordの処理は1行も変更していない。** 段落・表の走査、run単位の書き戻し、進捗ウィンドウ、
  ファイル選択はそのまま。ASTによる関数単位のハッシュ比較で、11個の関数・クラス
  （`translate_word_document_thread` / `translate_super_fast_parallel` / `translate_chunk` /
  `WordProgressWindow`（`__init__` / `update_progress` / `_update_gui` / `close`）/
  `is_translatable` / `select_file` / `start_translation`）が旧版と**完全一致**することを
  確認済み。変更したのは `check_dependencies` / `init_gemini` / `translate_batch_gemini` の
  3つだけ（`pdf_translator` / `ppt_translation` でも全く同じ3つだった）。

### 意図的にやらなかったこと（スコープ外）

本ツールは `ppt_translation` の「祖先」にあたるため、PowerPoint版が持っている次の機能が存在しない。
**今回の移行では意図的に足していない**（移行と機能追加を混ぜると、実機で不具合が出たときに
「移行のせいか、追加機能のせいか」の切り分けができなくなるため）。必要なら次の版
（`word_translation_YYYYMMDD_02.py`）で別途対応する。

- 失敗時の3回リトライ・3秒待機
- ロギング（`translation_debug.log`）
- 翻訳中のバッチごとの進捗バー更新（現状は `0` → `完了` の2段階のみ）
- 3バッチ連続エラーでのフェイルファスト
- ファイルロックの事前検知（現状は保存時に初めてエラーになる）

### 新規作成した付随ファイル

- `requirements.txt`: `python-docx` と `requests` を記載した（`requests` は `gemini_client.py` が
  使用する）。`run_word_translator.bat` は専用のvenvを作ってここに書かれたものだけを入れるため、
  `requests` を書き忘れると起動はするがAI呼び出し時に失敗する。旧SDK `google-generativeai` は
  20260812_01 以降不要。
- `run_word_translator.bat`: 初回のみvenvを作成して `pip install -r requirements.txt` を実行し、
  フォルダ内で最も新しい `word_translation_????????_??.py` を自動起動する。認証情報は
  **`GEMINI_API_KEY` と `GEMINI_PROXY_URL` の両方が未設定のときだけ**警告する
  （プロキシ専用構成も正常な構成のため）。
  - **このファイルは絶対にASCIIのみで書くこと。** 日本語を入れると日本語版WindowsのcmdがShift-JIS
    として解釈し、マルチバイト文字の隣にあるASCIIキーワード（`goto` 等）まで壊れて起動しなくなる。
    `chcp 65001` では直らない（`pdf_translator` で実際に踏んだ問題）。非ASCIIバイトが0であることを
    確認済み。
- `README.md`: 環境変数（`GEMINI_API_KEY` / `GEMINI_PROXY_URL` の**どちらか一方以上**）、
  `gemini_client.py` の探索パス（上位の `common` を1つ上・2つ上・3つ上の順に自動探索）、
  モデルが固定になったことと `GEMINI_MODEL` での上書き方法、「最初のバッチだけ遅い」のは仕様で
  あること、および**既知の制限**（ヘッダー/フッター・脚注・テキストボックスが翻訳対象外である
  ことなど）を記載した。
- `CHANGELOG.md`: 本ファイル。

### テスト

検証用に `tests/test_word_translation_20260812_01.py`（98項目）を追加した。偽の `gemini_client` を
差し込んでpayloadを捕捉する方式で、実際のGemini APIに接続せずに検証できる。`python-docx` は本物を
使い、合成DOCX（見出し＋本文（同一段落に書式違いの複数run）＋表。runごとにフォントサイズ・太字・色・
段落配置を設定）を生成してエンドツーエンドで確認している。

- **旧版と新版に同じ翻訳文を与えると、出力DOCXの run 構成・テキスト・書式・フォント名が完全一致する**
  ことを確認済み（＝Word出力への影響がゼロであることの直接的な証拠）。
  なおDOCX（zip）はタイムスタンプが毎回変わるためバイト単位の比較はできないので、run 単位で比較している。
- **run 単位の書式（`font.size` / `font.bold` / `font.color.rgb` / 段落の `alignment` と `style`）が
  翻訳前後で完全一致**すること。表のセルも翻訳対象として拾えていること。日本語指定時に
  `run.font.name` が `游ゴシック` になること。元ファイルが書き換えられないこと。
- **ヘッダー/フッターが翻訳対象外のまま**であること（既存仕様。移行のついでに対応範囲を広げて
  いないことの証明）。
- `init_gemini()` がネットワークアクセスなしで成功すること（ソケット生成を禁止した状態で検証。
  `list_models()` を消せている証拠）。
- `safetySettings` が4カテゴリ分そのまま載ること、`temperature: 0.1` が `generationConfig` へ
  camelCaseで載ること、`model` が明示的に渡ること。
- **空応答・通信失敗のとき、リトライせず1回で原文を返す**こと（＝本ツールの既存挙動が保たれている
  証明。PowerPoint版の3回リトライへ「揃えて」いないことの確認）。全バッチ失敗時もフェイルファスト
  せず最後まで投げ切ること。
- `translate_batch_gemini` / `translate_super_fast_parallel` のシグネチャが旧版のままであること
  （PowerPoint版とは引数・戻り値が違うため、寄せていないことを固定する）。
- 認証情報判定の4パターン（**`GEMINI_PROXY_URL` のみでも通る**ことが最重要）。
- 共通モジュール未配置時に「探索したパス」と `GEMINI_COMMON_DIR` の案内を含むエラーが出ること。
- 共通モジュールの探索が「2つ上が common」（会社PCの実配置）でも「1つ上が common」でも解決すること。

### 未検証（実機での確認が必要）

Linuxコンテナからは共通モジュールにも自宅PCプロキシにも到達できないため、**実際にプロキシ経由で
Geminiの応答が返るところは未確認**。実機では次を確認すること。

1. `PythonScripts\word\word_translator\` に5ファイル（スクリプト新版・`requirements.txt`・
   `run_word_translator.bat`・`README.md`・`CHANGELOG.md`）を配置する
2. `GEMINI_API_KEY` / `GEMINI_PROXY_URL` を設定後、**コマンドプロンプトを開き直してから**起動する
3. **起動できること**（移行前は初期化の時点で落ちていた。ここが今回いちばん重要）
4. 実際にDOCXを翻訳し、画面に `[gemini_client]` のログが出たうえで翻訳結果が返ること
   （**本ツールはログファイルを作らない**ので、確認はコンソール表示のみ）
5. フォント・色・配置・表の書式が従来どおり保持されていること（Word処理側は未変更なので影響しない想定）
6. 初回バッチだけ遅くなる場合があるが仕様であること
7. **進捗バーが途中で動かないのは元からの挙動**であること

## [20260306_01] - 2026-03-06

移行前の最終版（`PythonScripts\word\word_translator\word_translation_20260306_01.py`）。この版までは
スクリプト1ファイルのみで運用しており、付随ファイル（`requirements.txt` / 起動用バッチ /
`README.md` / `CHANGELOG.md`）は存在しなかった。ファイル冒頭のバージョン docstring も無い。
以下はコードから読み取れる仕様。

- Wordファイル（.docx）を Gemini API で翻訳する tkinter GUI ツール。**run（文字書式が同じ
  ひとかたまり）単位**でテキストだけを差し替えるため、フォント・サイズ・太字・色・段落配置・
  表の書式がそのまま保持される。
- 翻訳対象は `doc.paragraphs`（本文の段落）と `doc.tables`（表のセル）の run。
  `is_translatable()` で空文字・記号のみ・数字のみ・2文字以下を除外する。
- 集めたテキストを**10件ずつのバッチ**にまとめ、`ThreadPoolExecutor` で**最大3並列**送信する。
- 出力は元ファイルと同じフォルダに `元ファイル名_gemini_japanese.docx`
  （`target_language.split()[0].lower()` を使うため言語名がそのまま入る）。元ファイルは変更しない。
- 翻訳先が日本語のときのみ `run.font.name = '游ゴシック'` を設定する。
- 起動時に `genai.list_models()` で使用可能モデルを自動検出していた（→ 20260812_01 で廃止）。

### 既知の挙動（移行スコープ外。触っていない）

実機で気になったときに「移行のせいではない」と切り分けられるよう記録しておく。

- **リトライが無い**… 例外時は `print` して原文を返すだけ。1回失敗したらそのバッチ（10項目）は終わり。
- **ロギングが無い**… `translation_debug.log` は出ない。エラーはコンソールへ `print` されるだけで、
  バッチファイルから起動していると窓が閉じて見えないことがある。
- **進捗バーがほぼ動かない**… 翻訳中の更新が無く、`0` → `完了` の2段階だけ。長い文書では
  「固まったように見える」。
- **フェイルファストが無い**… API障害時も全バッチにリクエストを投げ続ける。
- **ファイルロックの事前検知が無い**… 出力先が開いていると、数分の翻訳が終わった後の保存時に
  初めてエラーになる。読み込み元のチェックも無い。
- ヘッダー/フッター・脚注・テキストボックス内の文字は**翻訳対象外**（`doc.paragraphs` と
  `doc.tables` しか走査していない）。
- Wordの日本語フォント指定は `run.font.name` だけでは日本語文字に効かない（`w:eastAsia` の設定が
  別途必要）。元コードは `run.font.name = '游ゴシック'` のみ。
- `translate_super_fast_parallel()` … チャンクが例外で失われたとき `[""] * batch_size` で埋めるため、
  最終チャンクだと翻訳結果の件数が合わなくなりうる。
- `select_file()` … `filetypes` に `*.doc` が含まれているが、`python-docx` は旧形式 `.doc` を
  開けないため、選ぶとエラーになる。
- 出力ファイル名 … `_gemini_japanese.docx` になる（`pdf_translator` の `_ja.pdf` のような
  2文字コードではない）。既存の出力名が変わると運用に影響するため、依頼が無い限り変更しない。
- 素の `except:` が複数ある。
