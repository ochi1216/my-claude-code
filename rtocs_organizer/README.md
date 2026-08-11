# BBT RTOCS Organizer

BBT「大前研一ライブ」のRTOCSコーナーの講義動画を自動取得し、Gemini APIで要約してHTMLレポート化するツール。

## 必要要件

- Python 3.9以上
- Google Chrome
- Gemini APIキー

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. スクリプト実行前に、リモートデバッグを有効にした状態でChromeを起動しておく。本スクリプトはChromeを新規起動せず、既存のChromeインスタンスにポート9222で接続する（`RTOCSManager.connect_chrome`）。

   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebugProfile"
   ```

3. 環境変数 `GEMINI_API_KEY` にGemini APIキーを設定する（設定後は新しいターミナルを開いて実行する）。

   ```
   setx GEMINI_API_KEY "your-api-key-here"
   ```

4. `BASE_DIR`（`rtocs_organizer_20260711_01.py` 内で `C:\Users\nx023836\Documents\PythonScripts\bbt\RTOCS_organizer` にハードコードされている）配下の `data\category_map.json` に、年度とbbt757のカテゴリID(`subCatId`)の対応表を用意する。このファイルが無いと、import修正後は起動時のGUI (`RTOCSConfigGUI`) が `category_map.json` の読み込みで `FileNotFoundError` を起こす。

   ```json
   {
     "2026": {"id": "xxxxx"},
     "2025": {"id": "yyyyy"}
   }
   ```

5. スクリプトを実行する。

   ```
   python rtocs_organizer_20260711_01.py
   ```

## 既知の制限（今回のスコープ外）

- `BASE_DIR` が特定ユーザー名のパスでハードコードされている。
- `RTOCSConfigGUI` クラスがファイル内で2重定義されており、後方の定義が前方を上書きしている（デッドコードあり）。

## RTOCS 統合ダッシュボード（俯瞰・傾向分析＋一気通貫戦略策定）

蓄積したRTOCSデータを横断的に分析するツール一式。`rtocs_organizer_20260711_01.py` と同じフォルダに置いて使う（`data/` フォルダを共有する）。

- `rtocs_index.py` — `data/JSON_lake` から軽量なケース一覧（`data/rtocs_index.json`）を増分構築する共通部品
- `strategy_prompts.py` / `strategy_engine.py` — 企業名を1つ入力すると「会社分析→直近ニュース収集(英/日/中)→株式市場分析→業界・競合分析→類似RTOCS事例選定→他業種事例分析→課題分析→戦略策定」を自動で実行するパイプライン
- `strategy_report.py` — 分析結果を1枚の自己完結HTMLレポートに整形
- `rtocs_dashboard_20260715_04.py` — 上記をまとめたStreamlitダッシュボード本体（最新版。変更履歴は [`CHANGELOG.md`](CHANGELOG.md) を参照）

### 起動方法

```
git submodule update --init ../common   # 未取得の場合。戦略分析パイプラインが依存する共通Geminiクライアント
pip install -r requirements.txt
streamlit run rtocs_dashboard_20260715_04.py
```

環境変数は`GEMINI_API_KEY`に加えて、会社PCでの直接アクセス遮断時のフォールバック用に
`GEMINI_PROXY_URL`（自宅PC経由プロキシのURL）も設定できる。詳細は
[`/common/GEMINI_MIGRATION_HANDOVER.md`](../common/GEMINI_MIGRATION_HANDOVER.md) を参照。

ブラウザが自動で開き、以下の3タブが表示される。

1. **📋 一覧・検索** — 従来通り、企業名・キーワード・業界でRTOCSを検索し、HTML/PDFを開く
2. **📈 傾向分析** — 業界分布の年次推移、キーワード頻度・トレンド、地域ミックス、複数回登場企業の一覧をグラフで俯瞰。「AI俯瞰総評」ボタンで、全ケースをGeminiに読ませた傾向コメントも生成できる
3. **🎯 戦略分析** — 任意の企業名を入力すると、蓄積RTOCSをケースライブラリとして活用しながら一気通貫で戦略分析レポート（HTML）を生成する。会社分析の直後に、Google Search Groundingで英語・日本語・中国語の企業名表記から直近12ヶ月のニュースを検索するステージが入る。「通常」（gemini-2.5-flash、数十円/回）と「ディープ」（gemini-2.5-pro＋戦略の批判・改訂パス、数百円/回）の2モード

### 注意点

- 上場企業は `yfinance` で株価・財務データを自動取得するが、未上場企業は定性分析のみとなる（自動判定・自動フォールバック）
- 各分析ステージが失敗しても処理は止まらず、レポート内に「取得失敗」として表示される（部分的なレポートは必ず生成される）
- AIの知識に基づく分析は不確実な場合があるため、レポート内の記述は参考情報として扱い、重要な意思決定の前には要確認
- 直近ニュース収集はGeminiの検索グラウンディング機能を使用するベストエフォート実装。この1ステージだけが失敗しても、ニュースセクションが空になるだけで他の分析ステージには影響しない
- Gemini API呼び出しは`../common/gemini_client.py`（submodule `ochi1216/gemini-common-tools`）経由。会社PCでの直接アクセス遮断時は自宅PC経由プロキシへ自動フォールバックする（2026-08-11変更、詳細は[`CHANGELOG.md`](CHANGELOG.md)参照）
