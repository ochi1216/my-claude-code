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
