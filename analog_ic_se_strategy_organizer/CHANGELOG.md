# CHANGELOG — analog_ic_se_strategy_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [構想・詳細設計段階] - 2026-07-16

このツールはまだパイプライン本体（`ic_index.py` / `ic_schema.py` / `ic_prompts.py` / `ic_engine.py` / `ic_report.py` / Streamlitダッシュボード）を実装していない。今回のセッションでは以下のみを作成した。詳細設計は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md)（リポジトリルート）を参照。

**追加ファイル:**
- `config/source_data/analog_power_semiconductor_companies_global_2026.xlsx` — 越智さんが調査した競合企業一覧（米欧日亜、67社）の原本
- `config/category_schema.json` — 上記Excelの9製品カテゴリ（DC-DC/PMIC, LDO, LEDドライバー, AC-DC, ゲートドライバー, ロードスイッチ/eFuse, アイデアルダイオード/ORing, GaNパワーIC/デバイス, パワーディスクリート/モジュール）ごとの比較パラメータ定義
- `config/competitors_db.json` — 上記Excelを`ic_competitor_import.py`で変換した競合企業データベース（67社）
- `ic_competitor_import.py` — Excel→competitors_db.jsonの変換スクリプト。Excel更新時はこれを再実行するだけでよい
- `requirements.txt` — 将来のパイプライン実装を見越した依存パッケージ一覧（現時点で実際に使用しているのは`openpyxl`のみ）

**次にやること（次セッション）:** [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) の「後続実装セッションへの実装順序」節を参照。
