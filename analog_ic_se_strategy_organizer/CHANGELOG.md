# CHANGELOG — analog_ic_se_strategy_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [起動スクリプト追加] - 2026-07-16

**追加ファイル:** `run_dashboard.bat`

Windows用の起動バッチファイル。`analog_ic_se_strategy_organizer_YYYYMMDD_NN.py`のうち
ファイル名（日付・連番）が最も新しいものを`dir /b /o-n`で自動選出して起動するため、
バージョンアップでファイル名が変わってもこのバッチファイル自体は書き換え不要。
コード本体・`requirements.txt`と同じフォルダに置いて使う（バッチファイル自体は日付連番の
バージョン管理対象外とする。常に最新版を指す「固定名の起動口」という役割のため）。

## [20260716_01] - 2026-07-16

`DESIGN_analog_ic_se_strategy_organizer.md` に基づき、パイプライン本体とStreamlitダッシュボードを実装した初版。

**追加ファイル:**
- `ic_schema.py` — fact構造ヘルパー（`make_fact`/`normalize_fact`）、`category_schema.json`/`competitors_db.json`のローダー、カテゴリ解決（9カテゴリ以外は`generic_analog_ic`にフォールバック）、地域代表企業選定（`pick_regional_representatives`）、競合DBサマリー（`competitors_summary`）
- `ic_index.py` — `data/product_lake/*.json`（1製品=1ファイル）から`data/ic_index.json`を増分構築（`rtocs_index.py`と同型）。`save_product_case`でパイプライン結果を保存
- `ic_prompts.py` — 5ステージ分のGeminiプロンプト（fact構造での出力を指示）＋ポートフォリオ俯瞰タブ用のAI総評プロンプト
- `ic_engine.py` — `GeminiClient`（JSONモード＋Google Search Grounding、`google-genai`使用）と`IcPipeline`（5ステージ: 製品取り込み→市場分析→キーカスタマー推定→競合IC比較→次世代スペック提案。各ステージ失敗しても継続する部分レポート方針）
- `ic_report.py` — 自己完結HTMLレポート生成（fact構造は出典・確度バッジ付きで描画）
- `analog_ic_se_strategy_organizer_20260716_01.py` — Streamlit 3タブダッシュボード（📦製品登録・検索／📊ポートフォリオ俯瞰／🎯製品ディープダイブ）

**動作検証:**
- `ic_schema.py`/`ic_index.py`: 単体テストで増分構築・fact構造正規化・カテゴリフォールバックを確認
- `ic_engine.py`/`ic_report.py`: `GeminiClient`をモックした一気通貫パイプラインで、ステージ間のデータ受け渡し・HTMLレポート生成（Playwrightでスクリーンショット確認）を確認
- ダッシュボード3タブ: `streamlit run`で起動し、Playwrightで実画面を確認（3タブとも正常表示、チャート描画も確認）
- **未検証**: 実際のGemini API呼び出し（`GEMINI_API_KEY`未設定、かつこの開発環境では`google-generativeai`の依存関係(`cryptography`のRustバインディング)が壊れており動作確認不可）。`GEMINI_API_KEY`を設定した環境で`pip install -r requirements.txt`後に実際のTI型番で動作確認することを推奨する
- **未検証**: grounded searchでデータシートの数値項目をどこまで正確に拾えるか（`DESIGN_analog_ic_se_strategy_organizer.md` 11章の要検証事項1）。実データでの検証が必要

## [構想・詳細設計段階] - 2026-07-16

このツールはまだパイプライン本体（`ic_index.py` / `ic_schema.py` / `ic_prompts.py` / `ic_engine.py` / `ic_report.py` / Streamlitダッシュボード）を実装していない。今回のセッションでは以下のみを作成した。詳細設計は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md)（リポジトリルート）を参照。

**追加ファイル:**
- `config/source_data/analog_power_semiconductor_companies_global_2026.xlsx` — 越智さんが調査した競合企業一覧（米欧日亜、67社）の原本
- `config/category_schema.json` — 上記Excelの9製品カテゴリ（DC-DC/PMIC, LDO, LEDドライバー, AC-DC, ゲートドライバー, ロードスイッチ/eFuse, アイデアルダイオード/ORing, GaNパワーIC/デバイス, パワーディスクリート/モジュール）ごとの比較パラメータ定義
- `config/competitors_db.json` — 上記Excelを`ic_competitor_import.py`で変換した競合企業データベース（67社）
- `ic_competitor_import.py` — Excel→competitors_db.jsonの変換スクリプト。Excel更新時はこれを再実行するだけでよい
- `requirements.txt` — 将来のパイプライン実装を見越した依存パッケージ一覧（現時点で実際に使用しているのは`openpyxl`のみ）

**次にやること（次セッション）:** [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) の「後続実装セッションへの実装順序」節を参照。
