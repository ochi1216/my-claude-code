# ツール別シート: BBT レクチャーオーガナイザー

Gemini APIプロキシ化の作業対象シート。**共通ガイド `HANDOVER_gemini_proxy_common.md`
と2点セットで使う。**

作成: 2026-08-17 / 記入者: Claude Code（S01 セッションで調査）
調査対象ファイル: `BBT_lecture_script_getter_20260804_01.py`（3319行）

---

## 1. ツールの基本情報

| 項目 | 内容 |
|---|---|
| ツール名 | BBT レクチャーオーガナイザー（BBTサマリ） |
| 配置場所 | `C:\Users\nx023836\Documents\PythonScripts\bbt\` |
| **`PythonScripts` からの階層** | **1階層** → `../common` で届く |
| ツールの形態 | tkinter GUI（複数ダイアログ）＋ コンソール実行（`execution_log.log`） |
| Git管理の有無 | ローカルはGit未使用。`my-claude-code` の `bbt_lecture_organizer/` に取り込み（2026-08-17 ユーザー判断） |
| 現在の最新リビジョン | `BBT_lecture_script_getter_20260817_01.py`（旧: `..._20260804_01.py`） |

### 階層の判定

```
実際のパス: C:\Users\nx023836\Documents\PythonScripts\bbt\BBT_lecture_script_getter_20260804_01.py

  PythonScripts\bbt\  → "../common" = PythonScripts\common\  届く  → 階層は1
```

共通ガイド第5節のシムの探索候補（`../common` → `../../common`）で**そのまま届く**。
候補の追加は不要。

---

## 2. 調査結果（共通ガイド第9節のコマンド結果）

| 調査項目 | コマンド | 結果 |
|---|---|---|
| 呼び出し方式（新SDK） | `grep -n "genai.Client("` | **0箇所**（新SDK未使用） |
| 呼び出し方式（旧SDK） | `grep -n "import google.generativeai"` | **1箇所**（L32 `import google.generativeai as genai`）← **旧SDK** |
| 呼び出し方式（直接POST） | `grep -n "generativelanguage.googleapis.com"` | 0箇所 |
| 削除対象のimport | `grep -n "from google import genai"` | 0箇所 |
| 残すimport | `grep -n "from google.genai import types"` | **0箇所**（`types` は未使用） |
| `contents` の形 | `grep -n "contents="` | **0箇所**。L2369 で**位置引数に文字列**を渡す（`generate_content(final_prompt, ...)`）。リスト・マルチモーダルなし |
| Grounding の使用 | `grep -n "google_search\|grounding\|tools="` | **0箇所**（未使用） |
| APIキーガード | `grep -n "gemini_api_key\|GEMINI_API_KEY"` | **1箇所**（L2149-2151）。設定ファイルは使わず環境変数のみ |
| ガードの文言 | `grep -n "APIキーが設定され"` | 0箇所（文言は英語 `"GEMINI_API_KEY not found in environment variables"`） |
| シムが満たす契約 | `grep -n "usage_metadata\|response_schema"` | `usage_metadata` **2箇所**（L2375-2376）／`response_schema` **0箇所**。`response_mime_type` のみ **1箇所**（L2371、**素のdict・snake_case**） |

### Gemini 関連コードの全量（これで全部）

| 行 | 内容 |
|---|---|
| L32 | `import google.generativeai as genai` |
| L2149-2151 | `self.api_key = os.getenv("GEMINI_API_KEY")` / 未設定なら `raise ValueError(...)` |
| L2153 | `genai.configure(api_key=self.api_key)` |
| L2154 | `self.model = genai.GenerativeModel('gemini-2.5-flash')` |
| L2369-2372 | `response = self.model.generate_content(final_prompt, generation_config={"response_mime_type": "application/json"})` |
| L2375-2376 | `response.usage_metadata.prompt_token_count` / `.candidates_token_count` |
| L2381-2382 | `response.text` |

モデルは `gemini-2.5-flash` 固定（切替UIなし）。L2476 のコスト表示にもモデル名が直書き。

### 判定

- [ ] 共通ガイド第5節のシムが**そのまま使える**（新SDK `genai.Client` を使用）
- [x] シムの**作り直しが必要**（旧SDK `google.generativeai` を使用）
- [ ] **別方式**（`requests` で直接POST）
- [x] `contents` のリスト対応は**不要**（文字列のみ。ただし保険として両対応にする）
- [x] Grounding 対応（`tools`）は**不要**

### 第5節のシムをそのまま流用できない理由（3点）

1. **インターフェースが違う**。旧SDKは `genai.GenerativeModel(model_name)` →
   `.generate_content(prompt, generation_config=...)`。新SDKの
   `Client().models.generate_content(model=, contents=, config=)` とは別物。
2. **`generation_config` が素のdictで snake_case**。第5節のシムは
   `getattr(config, "response_mime_type", None)` と**属性アクセス**で読むため、
   dictを渡すと常に `None` になり **`responseMimeType` が payload に載らない**
   → JSONモードが無効化される silent failure。snake_case→camelCase 変換が必要。
3. **モデル名がコンストラクタで束縛される**。`generate_advanced(payload, model=...)`
   へ確実に渡さないと共通モジュール既定モデルに落ちる（共通ガイド 6-(5)）。

---

## 3. このツール固有の判断事項

- **APIキーガード（共通ガイド 6-(3)）が致命的**
  - L2149-2151 の `raise ValueError` は `GeminiAutomator.__init__()` 内。
  - 呼び出し元 L3129 `sender = GeminiAutomator(headless_mode=False)` は
    **`try` ブロックの外**（`send_all_to_gemini()` 冒頭）。
  - → プロキシ専用構成（`GEMINI_API_KEY` 未設定）にすると、
    **要約処理が1件も走らずツールが例外で停止する**。必ず修正が必要。
- **「直接接続の復活お知らせ」を入れるか** → **今回は入れない**（2026-08-17 ユーザー判断）
  - 全ツールに入れると同じ日に複数回ポップアップが出る未決事項があるため見送り。
    実装済みは `outlook_total_organizer` のみ。
- **納品方法**（共通ガイド第11節） → **リポジトリに `bbt_lecture_organizer/` を新設**
  （2026-08-17 ユーザー判断）。ローカルへはダウンロードして差し替える。
- **移行方式** → **旧SDK互換シム**（2026-08-17 ユーザー判断）。
  新SDK `google.genai` への書き換えは行わない。`genai` 名前空間ごとシムへ差し替えることで
  `GeminiAutomator` の要約ロジックを1行も変更せずに済むため。

---

## 4. 作業ログ

| 日付 | 実施内容 | 結果 |
|---|---|---|
| 2026-08-17 | 共通ガイド第9節の調査コマンドを実行、本シートを記入 | 旧SDK使用と判明。シム作り直しが必要 |
| 2026-08-17 | 移行方式・お知らせ機能・納品方法をユーザーへ確認 | 旧SDK互換シム／お知らせ無し／リポジトリ取込 で承認 |
| 2026-08-17 | 旧SDK互換シムを実装（`BBT_lecture_script_getter_20260817_01.py`） | 変更は import 1行の置換とAPIキーガード1箇所のみ |
| 2026-08-17 | 偽 `gemini_client` を注入した検証テストを作成・実行 | **79項目すべて合格** |
| 2026-08-17 | `ast.parse` ／ 旧版との `diff` ／ 関数単位MD5ハッシュ比較 | 既存99関数中98関数が1バイトも変化なし。変更は `GeminiAutomator.__init__` のみ |
| 2026-08-17 | クラスのメソッド構成比較（移管資料 §8 の混入バグ再発防止） | 既存クラスのメソッド構成は全て同一 |
| 2026-08-17 | 実物の `gemini_client.py` を使ったパス解決確認（1階層・2階層） | 両方とも import 成功 |
| 2026-08-17 | 行末（CRLF/LF混在）の保全確認 | 元ファイルのLF専用68行をそのまま維持 |

---

## 5. 完了条件

- [x] 共通ガイド第10節の手順1〜10を完了
- [x] 偽 `gemini_client` を注入したテストが全項目合格（79/79）
- [x] 既存機能の回帰確認（K節）・パス解決の確認（J節）を実施
- [x] CHANGELOG に「**実機でのプロキシ経由の応答は未確認**」を明記
- [x] ユーザーへ納品
- [ ] （ユーザーの明示的な指示があれば）コミット・Push
- [ ] **会社PCでの実機動作確認（ユーザー作業）** ← 残タスク
