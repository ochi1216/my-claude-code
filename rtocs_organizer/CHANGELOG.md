# CHANGELOG — rtocs_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [Gemini呼び出し共通化] - 2026-08-11

**背景:** 会社PC上でGemini APIへの直接アクセスが遮断される事象が発生（2026-08-10頃、原因未確定）。
業務停止を避けるため、自宅PC経由のプロキシへ自動フォールバックする共通クライアント
（`../common/gemini_client.py`、submodule `ochi1216/gemini-common-tools`）を導入し、戦略分析パイプライン
（`strategy_engine.py`）のGemini呼び出しをすべてこちらに置き換えた。詳細は`common/GEMINI_MIGRATION_HANDOVER.md`参照。

**変更ファイル:** `strategy_engine.py`, `requirements.txt`（`rtocs_dashboard_*.py`・`rtocs_index.py`・
`strategy_prompts.py`・`strategy_report.py`は無変更）

- `GeminiClient`の内部実装を、`google-generativeai`/`google-genai` SDKの直接呼び出しから
  `../common/gemini_client.py`の`generate_advanced(payload, model=...)`経由に置き換え
- JSONモード・Google Search Groundingのペイロード組み立て・レスポンス解析ロジックは変更なし
- ディープモード（`gemini-2.5-pro`）判定・戦略批判改訂パスは`self.model_name`をそのまま
  `generate_advanced`に渡すことで維持
- `requirements.txt`から`google-genai`を削除。`google-generativeai`は`rtocs_organizer_20260711_01.py`
  （RTOCS動画スクレイパー、本移行の対象外）が別途直接使用しているため残置
- **未移行**: `rtocs_organizer_20260711_01.py`は今回のスコープ外（Google Search Groundingを使わない
  シンプルなJSON生成用途のため）。移行する場合は別途対応が必要
- **動作検証**: モックで`generate_advanced`をすり替え、`generate_json`/`generate_grounded_json`双方が
  正しいJSONモード/groundingペイロードを組み立て、`model_name`（flash/pro）が正しく伝播し、
  コスト計算も従来通り動作することを確認。実際のGemini API呼び出しは未検証（環境にAPIキー無し）

## [20260715_04] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_04.py`（`_03`からのコピー＋バージョン更新。`_01`〜`_03`はそのまま残置）
**変更ファイル:** `strategy_engine.py`, `requirements.txt`

実機検証で判明したバグ修正:

- 直近ニュース収集ステージが `400 google_search_retrieval is not supported. Please use google_search tool instead.` で必ず失敗する不具合を修正
  - 原因: `google-generativeai`（レガシー・Google公式に開発終了宣言済みのSDK）のグラウンディング機能は旧世代方式(`google_search_retrieval`)のみで、`gemini-2.5-flash`/`gemini-2.5-pro`が要求する新方式(`google_search`)を構成できなかった
  - 対応: ニュース収集ステージのみ、後継の統合SDK `google-genai` に切り替え、`google_search`ツールを使用するよう変更。他の7ステージ（JSONモード呼び出し）は`google-generativeai`のまま変更なし
- `requirements.txt`に`google-genai>=1.0`を追加（`google-generativeai`と共存）

## [20260715_03] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_03.py`（`_02`からのコピー＋バージョン更新。`_01`/`_02`はそのまま残置）
**変更ファイル:** `strategy_prompts.py`, `strategy_engine.py`, `strategy_report.py`

実データでの試用フィードバックに基づく改善:

- 「課題分析」カードの根拠(evidence)を単一文字列から配列スキーマに変更し、1項目ずつ改行して表示するよう修正（読点区切りで1行に詰め込まれ読みにくかった問題を解消）
- 戦略パイプラインに「直近ニュース収集」ステージを新規追加（会社分析の直後、全体で7→8ステージに）。Geminiの検索グラウンディング機能を使い、対象企業の英語・日本語・中国語（簡体字）の名称表記を自動推定した上で、直近12ヶ月以内の重要ニュース（決算・M&A・経営陣交代・規制動向・地政学リスク等）を検索・要約する。結果は課題分析・戦略策定にも自動的に反映される
- レポートに「📰 直近ニュース」カードを新設（会社分析の直後）
- 検索グラウンディングは`google-generativeai`（Google公式に非推奨化済み）のベストエフォート実装のため、モデル世代によっては機能しない可能性がある旨をREADMEに明記

## [20260715_02] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_02.py`（`_01`からのバグ修正版。`_01`はそのまま残置）

- 傾向分析タブの「キーワードの年次トレンド比較」で `NameError: name 'kw' is not defined` が発生する不具合を修正（キーワード頻度上位を取り出すリスト内包表記の誤り）
- Streamlitの `use_container_width` 非推奨引数（2025-12-31以降削除予定）を `width='stretch'` に置換

## [20260715_01] - 2026-07-15

**追加ファイル:** `rtocs_dashboard_20260715_01.py`, `rtocs_index.py`, `strategy_engine.py`, `strategy_prompts.py`, `strategy_report.py`

- 既存の検索用ダッシュボード（`rtocs_dashboard_20260502_04.py`）を土台に、3タブ構成の統合ダッシュボードを追加
  - 📋 一覧・検索（従来機能を踏襲）
  - 📈 傾向分析: 業界分布の年次推移、キーワード頻度・トレンド、地域ミックス、複数回登場企業の一覧、AI俯瞰総評（Geminiによる全ケース横断コメント）
  - 🎯 戦略分析: 企業名を1つ入力すると、会社分析→株式市場分析(yfinance)→業界・競合分析→類似RTOCS事例選定→他業種事例分析→課題分析→戦略策定、を自動実行し1枚のHTMLレポートを生成
- `rtocs_index.py`: `data/JSON_lake` から軽量なケース一覧（`data/rtocs_index.json`）を増分構築する共通部品。傾向分析と戦略分析の類似事例検索（LLM-as-retriever方式）の両方が参照する
- コスト集計・失敗時の部分レポート継続（既存organizerと同じ方針）を踏襲

## [20260711_01] - 2026-07-11

**変更ファイル:** `rtocs_organizer_202060517_01.py` → `rtocs_organizer_20260711_01.py`（リネーム）

- ファイル名を他ツールと同じ `yyyymmdd_連番` 命名規則に統一

## [202060517_01] - 2026-07-10

**追加ファイル:** `rtocs_organizer_202060517_01.py`, `requirements.txt`, `README.md`

- `selenium` 未インストール環境で `ModuleNotFoundError` の生Tracebackが表示される問題を修正。import部分を `try/except` で囲み、`pip install -r requirements.txt` を促す日本語メッセージを表示するよう変更
- `requirements.txt`（selenium, google-generativeai, PyMuPDF）を新規追加
- セットアップ手順（Chromeのリモートデバッグ起動、GEMINI_API_KEY設定、category_map.jsonの準備）を記載したREADME.mdを新規追加
