# Excel翻訳ツール (excel_translation)

Excelファイル(`.xlsx` / `.xlsm` / `.xls`)のセルをGemini APIで翻訳し、書式・結合セル・列幅・VBAを保持したまま別ファイルへ出力するGUIツール。複数シート・範囲指定・並列バッチ翻訳に対応。

## 最新版

`excel_translation_20260817_01.py`

バージョンごとの変更点は [`CHANGELOG.md`](CHANGELOG.md) を参照。旧版(`excel_translation_20260616_03.py` / `excel_translation_20260812_01.py`)は削除せず残してある。

## セットアップ

### 1. 依存ライブラリ

```
pip install -r requirements.txt
```

`20260812_01` 以降、旧SDK `google-generativeai` は不要になった(Gemini呼び出しは共通モジュール経由へ移行したため)。

### 2. 共通モジュール `gemini_client.py` の配置

会社PCからGemini APIへの直接アクセスが遮断されているため、共通モジュール
[`gemini-common-tools`](https://github.com/ochi1216/gemini-common-tools) の
`gemini_client.py` を経由して呼び出す(直接呼び出しが失敗したら自宅PCプロキシへ自動フォールバック)。

想定している配置:

```
PythonScripts\
├── common\
│   └── gemini_client.py
└── excel\
    └── excel_transrate\
        └── excel_translation_20260817_01.py
```

`GEMINI_COMMON_DIR` 未設定時は、スクリプトから見て 1つ上 → 2つ上 → 3つ上 の順に
`common\gemini_client.py` を探し、最初に見つかったものを使う。上記以外の場所に置く場合は
`GEMINI_COMMON_DIR` で明示する。

### 3. 環境変数

| 変数 | 用途 | 必須 |
|---|---|---|
| `GEMINI_API_KEY` | 直接呼び出し用のAPIキー | いずれか一方 |
| `GEMINI_PROXY_URL` | 自宅PCプロキシのURL(直接呼び出し失敗時のフォールバック先) | いずれか一方 |
| `GEMINI_COMMON_DIR` | `gemini_client.py` のあるフォルダを明示したい場合のみ | 任意 |
| `GEMINI_RETRY_DIRECT_AFTER_SECONDS` | 直接呼び出しを再試行するまでの秒数(既定1800) | 任意 |

`GEMINI_API_KEY` と `GEMINI_PROXY_URL` は**どちらか一方でも設定されていれば起動する**
(プロキシ専用構成を弾かないため)。

> `setx` で設定した場合は現在のコマンドプロンプトに反映されない。
> **設定後にコマンドプロンプトを開き直してから起動すること。**
> `GEMINI_RETRY_DIRECT_AFTER_SECONDS` は `gemini_client.py` が読むため、
> `rtocs_organizer` など他のツールにも同時に効く。

## 実行

```
python excel_translation_20260817_01.py
```

翻訳対象のExcelファイルは事前に閉じておくこと。出力は
`<元のファイル名>_<言語略号>_<yyyymmdd_HHMMSS>.xlsx`(マクロ有効ブックは`.xlsm`)として
元ファイルと同じフォルダに保存される。

## テスト

```
python tests/test_excel_translation_20260817_01.py
```

偽の `gemini_client` を `sys.modules` へ注入し、`generate_advanced()` へ渡るpayloadと
レスポンス契約を検証する(Windows・Excel・実際のGemini APIに依存しない)。
`tkinter` / `pandas` はテスト側でスタブ化するため未導入の環境でも実行できる。
