# CHANGELOG — rtocs_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

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
