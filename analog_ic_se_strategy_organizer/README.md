# analog_ic_se_strategy_organizer

TI（Texas Instruments）のアナログ・電源半導体製品を型番1つから、市場分析・キーカスタマー推定・競合IC比較・次世代スペック提案まで一気通貫でまとめるツール。詳細な背景・設計は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md)（リポジトリルート）と [`/HANDOVER_analog_ic_scout.md`](../HANDOVER_analog_ic_scout.md) を参照。

**現状（2026-07-16時点）:** パイプライン本体・ダッシュボードの初版を実装済み。ただし**実際のGemini API呼び出しでの動作確認はまだ完了していない**（越智さんの環境で`GEMINI_API_KEY`を設定した上での実行確認が必要。詳細は「既知の制限」参照）。

## 必要要件

- Python 3.9以上
- Gemini APIキー（[Google AI Studio](https://aistudio.google.com/)で取得）

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. 環境変数 `GEMINI_API_KEY` にGemini APIキーを設定する。

   ```
   export GEMINI_API_KEY="your-api-key-here"      # macOS/Linux
   setx GEMINI_API_KEY "your-api-key-here"         # Windows（設定後は新しいターミナルを開く）
   ```

3. ダッシュボードを起動する。

   ```
   streamlit run analog_ic_se_strategy_organizer_20260716_01.py
   ```

ブラウザが自動で開き、以下の3タブが表示される。

1. **📦 製品登録・検索** — 型番を入力して「ステージ0のみ実行」すると、TI公式情報を検索してカテゴリ・主要仕様を軽量に確認できる（低コスト）。既存の分析済み製品を型番・アプリケーションで検索することもできる
2. **📊 ポートフォリオ俯瞰** — 競合企業データベース（67社）の地域別・カテゴリ別分布、分析済み製品のカテゴリ分布・競合ギャップランキング・次世代スペック提案の優先度分布をグラフで俯瞰。「AI俯瞰総評」ボタンで、全ケースをGeminiに読ませた傾向コメントも生成できる
3. **🎯 製品ディープダイブ** — 型番を入力すると、製品取り込み→市場分析→キーカスタマー推定→競合IC比較→次世代スペック提案の5ステージを自動実行し、HTMLレポート（`data/ic_reports/`）を生成する。「通常」（gemini-2.5-flash）と「ディープ」（gemini-2.5-pro）の2モード、競合IC比較は「通常モード」（地域代表1社ずつ、計4社程度）と「フルモード」（該当カテゴリの主要/限定 全社、コスト増）を選べる

## 競合企業データベース（`config/competitors_db.json`）

越智さんが調査した米国・欧州・日本・アジア（台湾・中国・韓国）のアナログ／パワー半導体企業67社のデータベース。各社について、9つの製品カテゴリ（DC-DC/PMIC・LDO・LEDドライバー・AC-DC・ゲートドライバー・ロードスイッチ/eFuse・アイデアルダイオード/ORing・GaNパワーIC/デバイス・パワーディスクリート/モジュール）ごとに「●主要／△限定／—確認できず」の判定、製品群幅スコア、車載対応可否、公式製品URL等を持つ。

**データの更新方法**（越智さんがExcelを更新した場合）:

```
python3 ic_competitor_import.py
```

`config/source_data/analog_power_semiconductor_companies_global_2026.xlsx` を読み込み、`config/competitors_db.json` を再生成する。JSONを直接手編集する必要はない。特定企業を一時的に対象外にしたい場合はExcel側で行毎に管理し、恒久的な除外はExcel側で削除してから再インポートすることを推奨（`competitors_db.json`内の`active`フラグは再インポート時に`true`へ上書きされるため、恒久除外の管理には使わないこと）。

## 製品カテゴリ別比較パラメータ（`config/category_schema.json`）

上記9カテゴリそれぞれについて、データシートに実際に載る比較パラメータ（例: DC-DC/PMICなら入力/出力電圧範囲・効率・スイッチング周波数・静止電流等、LDOならドロップアウト電圧・PSRR・出力ノイズ等）を定義したもの。ステージ0（製品取り込み）・ステージ3（競合IC比較）で、カテゴリごとに埋めるべき項目一覧として使う。

## 事実確度構造（fact構造）

各分析ステージが返す事実値は `{value, unit, source_type, source_detail, source_url, confidence, as_of, note}` の構造を持つ。`source_type`は`TI_official`/`third_party`/`llm_estimate`/`user_input`の4値、`confidence`は`high`/`medium`/`low`の3段階。HTMLレポートでは各値に出典・確度バッジを表示する。詳細は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) 3章を参照。

## 既知の制限・未検証事項

- **実際のGemini API呼び出しは未検証**: この開発環境には`GEMINI_API_KEY`が無く、また`google-generativeai`パッケージの依存関係（`cryptography`のRustバインディング）が壊れていたため、実機でのAPI呼び出し確認ができなかった。パイプラインの制御ロジック（ステージ間のデータ受け渡し、失敗時のフォールバック、HTMLレポート生成）はモック応答で検証済みだが、grounded searchで実際にTIのデータシート数値をどこまで正確に拾えるかは未検証（`DESIGN_analog_ic_se_strategy_organizer.md` 11章参照）。越智さんの環境でAPIキーを設定し、実際のTI型番数件で試してほしい
- キーカスタマー推定は公開情報のみに基づく「推定」であり、TIとの契約関係を示すものではない
- 競合他社のデータシート由来スペックを比較表として利用する際の著作権・利用規約上の扱いは法務未確認（レポート内に免責は記載済み）

その他の未解決事項は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) 11章を参照。
