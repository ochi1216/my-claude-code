# analog_ic_se_strategy_organizer

TI（Texas Instruments）のアナログ・電源半導体製品を型番1つから、市場分析・キーカスタマー推定・競合IC比較・次世代スペック提案まで一気通貫でまとめるツール（構想）。詳細な背景・設計は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md)（リポジトリルート）と [`/HANDOVER_analog_ic_scout.md`](../HANDOVER_analog_ic_scout.md) を参照。

**現状（2026-07-16時点）:** 構想・詳細設計段階。パイプライン本体（Gemini検索グラウンディングによる5ステージ分析）とStreamlitダッシュボードは未実装。今回作成したのは以下の設計・データ資産のみ。

## 現時点で使えるもの

### 競合企業データベース（`config/competitors_db.json`）

越智さんが調査した米国・欧州・日本・アジア（台湾・中国・韓国）のアナログ／パワー半導体企業67社のデータベース。各社について、9つの製品カテゴリ（DC-DC/PMIC・LDO・LEDドライバー・AC-DC・ゲートドライバー・ロードスイッチ/eFuse・アイデアルダイオード/ORing・GaNパワーIC/デバイス・パワーディスクリート/モジュール）ごとに「●主要／△限定／—確認できず」の判定、製品群幅スコア、車載対応可否、公式製品URL等を持つ。

**データの更新方法**（越智さんがExcelを更新した場合）:

```
pip install -r requirements.txt
python3 ic_competitor_import.py
```

`config/source_data/analog_power_semiconductor_companies_global_2026.xlsx` を読み込み、`config/competitors_db.json` を再生成する。JSONを直接手編集する必要はない。特定企業を一時的に対象外にしたい場合はExcel側で行毎に管理し、恒久的な除外はExcel側で削除してから再インポートすることを推奨（`competitors_db.json`内の`active`フラグは再インポート時に`true`へ上書きされるため、恒久除外の管理には使わないこと）。

### 製品カテゴリ別比較パラメータ（`config/category_schema.json`)

上記9カテゴリそれぞれについて、データシートに実際に載る比較パラメータ（例: DC-DC/PMICなら入力/出力電圧範囲・効率・スイッチング周波数・静止電流等、LDOならドロップアウト電圧・PSRR・出力ノイズ等）を定義したもの。将来のステージ0（製品取り込み）・ステージ3（競合IC比較）で、カテゴリごとに埋めるべき項目一覧として使う。

## 未実装（次セッションで着手）

- `ic_schema.py` / `ic_index.py` / `ic_prompts.py` / `ic_engine.py` / `ic_report.py`
- Streamlitダッシュボード本体（`analog_ic_se_strategy_organizer_YYYYMMDD_NN.py`）

実装順序・各ファイルの詳細設計・未解決事項は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) を参照。
