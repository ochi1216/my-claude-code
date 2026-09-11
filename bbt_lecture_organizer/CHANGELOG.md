# CHANGELOG — BBT レクチャーオーガナイザー

BBT757 eラーニングプラットフォームから講義動画情報をスクレイピングし、
Gemini AI で要約HTMLレポートを自動生成するツール。

バージョン形式は `YYYYMMDD_連番`（ルート `README.md` の開発ルール準拠）。
`2026.0708.02` 以前の履歴は claude.ai 時代のもので、`BBT サマリ開発 — Claude Code移管資料`
の §9 を参照。

---

## VERSION 20260817_01

**Gemini API のプロキシ化（旧SDK `google.generativeai` からの移行）**

会社PCからGemini APIへの直接アクセスがIT部門により遮断されたため、共通モジュール
`gemini_client.py`（`PythonScripts\common\`）経由の呼び出しへ移行した。
`generate_advanced()` が「まず直接 → 失敗したら自宅PCプロキシ（ngrok経由）」を
自動で切り替えるため、**呼び出し側はどちらの経路が使われたかを意識しない**。
IT側で遮断が解除されれば、自動的に直接呼び出しへ戻る。

### 追加・修正

- **旧SDK互換シムを追加**（新規、ファイル冒頭 L32〜264）
  本ツールは旧SDK `google.generativeai` を使っていたため、他5ツール
  （`rtocs_organizer` 等）で使っている新SDK `genai.Client` 向けのシムはそのまま
  流用できない。`configure()` と `GenerativeModel.generate_content()` だけを持つ
  互換シムを新設し、`genai` という名前をシムへ差し替えた。
  これにより **`GeminiAutomator` の要約ロジック本体は1行も変更していない**。
  - `genai.configure(api_key=...)` … そのまま動く（no-op）
  - `genai.GenerativeModel('gemini-2.5-flash')` … そのまま動く
  - `model.generate_content(prompt, generation_config={...})` … そのまま動く
  - `response.text` / `response.usage_metadata.*` … そのまま読める
- **`GEMINI_API_KEY` 必須チェックを廃止**（`GeminiAutomator.__init__`）
  直接呼び出しが遮断されていてもプロキシ経由なら成功しうるため、
  `GEMINI_API_KEY` / `GEMINI_PROXY_URL` の**どちらか一方でもあれば通す**判定
  （`gemini_credentials_available()`）に置き換えた。
  旧実装のままだと、プロキシ専用構成（`GEMINI_API_KEY` 未設定）で `ValueError` となり、
  かつ呼び出し元 `send_all_to_gemini()` は `try` ブロックの外でこのクラスを生成するため、
  **要約処理が1件も走らずツールが停止する**状態だった。
- **`generation_config` の camelCase 変換**
  旧SDKの `generation_config` は snake_case の素のdict（`response_mime_type`）だが、
  Gemini REST API の `generationConfig` は camelCase（`responseMimeType`）。
  変換しないと payload に載らず、**JSONモードが黙って無効化される** silent failure に
  なるため、シム内で変換する（`_snake_to_camel`）。
- **モデル名を明示的に渡す**
  `generate_advanced(payload, model=self.model_name)`。省略すると共通モジュール側の
  既定モデルに落ち、UI表示と実際のモデルが食い違う。`'models/'` 接頭辞は除去する。
- **共通モジュールの探索を自動化**
  `../common` → `../../common` の順に `gemini_client.py` を探す。環境変数
  `GEMINI_COMMON_DIR` を設定した場合はそちらを優先。
  import は `try/except` で受け、共通モジュールが無くてもツール自体は起動する
  （トランスクリプト抽出などAIを使わない機能を巻き添えで止めないため）。
  実際にAI呼び出しが行われた時点で、**試した全候補パス**・元のエラー・
  `GEMINI_COMMON_DIR` で指定できることを含む `RuntimeError` を出す。

### 変更した関数

| 関数 | 変更内容 |
|---|---|
| `GeminiAutomator.__init__` | APIキー必須チェックを `gemini_credentials_available()` に置き換え |

**それ以外の既存関数99個のうち98個は1バイトも変更していない**（AST＋MD5ハッシュで検証済み）。
`add_prompt_text()`・`extract_summary_from_page()`・`HTMLGenerator` 各メソッド・
両スクレイパークラスは全て変更なし。

### 新規追加した関数・クラス

| 名前 | 役割 |
|---|---|
| `_resolve_common_dirs()` | `gemini_client.py` の探索先候補を返す |
| `gemini_credentials_available()` | `GEMINI_API_KEY` / `GEMINI_PROXY_URL` のどちらかがあれば True |
| `_snake_to_camel()` | `generation_config` のキーを REST の camelCase へ変換 |
| `_schema_to_jsonable()` | `response_schema` が pydantic 化された場合の dict 化（保険） |
| `_generation_config_to_payload()` | dict / オブジェクト両対応の `generationConfig` 構築 |
| `_contents_to_payload_contents()` | `contents` を REST 形式へ変換（文字列・リスト両対応） |
| `_CommonUsageMetadata` | `response.usage_metadata` の代替 |
| `_CommonGeminiResponse` | `response.text` / `.usage_metadata` の代替 |
| `_CommonGenerativeModel` | `genai.GenerativeModel` の代替 |
| `_CommonGenaiNamespace` | `google.generativeai` モジュールの代替（`genai`） |

### 削除

- `import google.generativeai as genai`（L32）
  **非推奨パッケージ `google-generativeai` への依存が完全に無くなり、
  実行時の `FutureWarning` も出なくなる。** 新SDK `google-genai` も不要。

### 変更ファイル

| ファイル | 内容 |
|---|---|
| `BBT_lecture_script_getter_20260817_01.py` | 新リビジョン（3562行 / 旧版3320行） |
| `BBT_lecture_script_getter_20260804_01.py` | 旧リビジョン（変更なし・保持） |
| `test_gemini_proxy_20260817_01.py` | 検証テスト（新規） |
| `TOOLSHEET_bbt_lecture_organizer.md` | ツール別シート（新規） |
| `README.md` | セットアップ手順（新規） |
| `requirements.txt` | 依存パッケージ（新規） |

### 検証結果

偽 `gemini_client` を注入したテスト（`test_gemini_proxy_20260817_01.py`）
**79項目すべて合格**。

| 節 | 検証内容 |
|---|---|
| A | シムの構成・旧SDKを import していないこと |
| B | 共通モジュールの探索パス候補 |
| C | `generate_advanced` に渡る payload の形状（`parts[0].text` が文字列であること／`model` が明示的に渡ること） |
| D | `generationConfig` の camelCase 変換・`json.dumps` 可能性 |
| E | `response.text` / `usage_metadata` / コスト計算（160円/$） |
| F | シム単体の境界ケース（リスト contents・`models/` 接頭辞・各種 config キー・pydantic schema） |
| G | 空・壊れたレスポンス・共通モジュール側の例外で落ちないこと |
| H | 認証情報ガードの全パターン（キーのみ／プロキシのみ／両方／両方なし） |
| I | 共通モジュール未配置時にツールが起動でき、AI呼び出し時に原因の分かるエラーが出ること |
| J | **実物の `gemini_client.py`** を実配置に置いたパス解決（1階層・2階層） |
| K | 既存機能の回帰（要約→JSONパース→HTMLレポート生成→講師名/配信日/収録時間/コスト表示/ネクストアクション） |

そのほか、`ast.parse` による構文チェック、旧版との `diff`（変更は意図した2箇所のみ）、
関数単位のMD5ハッシュ比較、クラスのメソッド構成比較
（移管資料 §8 の「スクレイパークラスのメソッド混入」再発防止）を実施済み。

### ⚠️ 動作確認時の注意（実機確認のお願い）

- **実機でのプロキシ経由の応答は未確認。**
  Claude Code の実行環境（Linuxコンテナ）からは、会社PCの共通モジュール
  （`PythonScripts\common\gemini_client.py`）にも自宅PCのプロキシ（ngrok）にも
  到達できないため、**「プロキシ経由で実際にGeminiの応答が返るところ」は
  原理的に検証できない。** 会社PCでの実行確認をお願いします。
- 環境変数 `GEMINI_PROXY_URL` は **ngrok を再起動するたびに変わる**ため、
  都度更新が必要（`setx` で設定した値は、開いているコマンドプロンプトには
  反映されない。設定後は開き直すこと）。
- 直接呼び出しの無効化状態は `PythonScripts\common\.gemini_direct_disabled_until` に
  保存され、**他の全ツールと共有される**。「さっきまで直接接続だったのに急に
  プロキシ経由になった」ときは、別のツールが遮断を検知した可能性がある。
  直接接続の挙動を再現したい場合はこのファイルを削除する（全ツールに効く）。
- **「直接接続の復活お知らせ」機能は今回入れていない**（本セッションで見送りを判断）。
  実装済みは `outlook_total_organizer` のみ。
