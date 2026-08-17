# BBT レクチャーオーガナイザー（BBTサマリ）

BBT757 eラーニングプラットフォームから講義動画のトランスクリプトを抽出し、
Gemini AI で要約して HTML レポートを生成するツール。

- 最新版: `BBT_lecture_script_getter_20260817_01.py`
- 実行環境: Windows PC、Python 3系
- ローカル配置: `C:\Users\nx023836\Documents\PythonScripts\bbt\`

---

## セットアップ

### 1. 依存パッケージ

```
pip install -r requirements.txt
```

**`google-generativeai` は不要になりました**（VERSION 20260817_01 でプロキシ化。
非推奨パッケージへの依存が無くなり、実行時の `FutureWarning` も出なくなります）。
新SDK `google-genai` も使いません。

### 2. Gemini 共通モジュール

Gemini API の呼び出しは共通モジュール `gemini_client.py` を経由します。

```
C:\Users\nx023836\Documents\PythonScripts\
├── common\
│   └── gemini_client.py          ← 共通モジュール（全ツール共有）
└── bbt\
    └── BBT_lecture_script_getter_20260817_01.py
```

本ツールは `..\common` → `..\..\common` の順に自動探索します。
別の場所に置く場合は環境変数 `GEMINI_COMMON_DIR` でフォルダを指定してください。

共通モジュールの入手元: https://github.com/ochi1216/gemini-common-tools

### 3. 環境変数

**同じPCの他のツール（`outlook_total_organizer` 等）で設定済みなら、追加設定は不要です。**

| 変数 | 用途 |
|---|---|
| `GEMINI_API_KEY` | 直接呼び出し用のAPIキー |
| `GEMINI_PROXY_URL` | 自宅PCプロキシのngrok URL。**ngrok再起動のたびに変わるため都度更新が必要** |
| `GEMINI_COMMON_DIR` | `gemini_client.py` の場所を明示したい場合のみ（未設定なら自動探索） |
| `GEMINI_RETRY_DIRECT_AFTER_SECONDS` | 直接呼び出しを諦める秒数（現在 86400＝1日）。**全ツール共通** |

`GEMINI_API_KEY` と `GEMINI_PROXY_URL` は、**どちらか一方があれば起動します**
（直接アクセスが遮断されていてもプロキシ経由で動くため）。両方とも未設定の場合のみ
エラーになります。

> ⚠️ 環境変数を `setx` で設定した場合、**開いているコマンドプロンプトには反映されません。**
> 設定後はコマンドプロンプトを開き直してください。

### 4. Chrome（デバッグモード）

```
Chrome Path   : C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
User Data Dir : C:\Users\nx023836\AppData\Local\ChromeDebugProfile9222
Debug Port    : 9222
```

これらは `SimpleIntegrator` クラスの定数（`CHROME_PATH` / `CHROME_USER_DATA_DIR` /
`CHROME_DEBUG_PORT`）に直書きされています。モード選択の直前にChromeが未起動なら
自動起動します（起動済みなら何もしません）。

---

## 実行

```
python BBT_lecture_script_getter_20260817_01.py
```

同フォルダに `execution_log.log` が自動生成されます（実行のたびに上書き）。

起動するとモード選択ダイアログが出ます。

1. 最新コンテンツ一覧から選ぶ
2. 検索結果一覧から選ぶ（10分未満の動画は自動除外）
3. 開いているタブから選ぶ（レガシー方式）

---

## Gemini API のプロキシ経由呼び出しについて

会社PCからGemini APIへの直接アクセスが遮断されたため、共通モジュール経由に
移行しています（VERSION 20260817_01）。

- まず**直接**Gemini APIを試す
- 失敗したら**自宅PCのプロキシ**（ngrok経由のFlaskサーバー）へ自動フォールバック
- IT側で遮断が解除されれば、次回以降は自動的に直接呼び出しへ戻る

どちらの経路が使われたかは `execution_log.log` に `[gemini_client]` 行として出ます。

直接呼び出しの無効化状態は `PythonScripts\common\.gemini_direct_disabled_until` に
保存され、**他の全ツールと共有されます**。直接接続の挙動を再現したい場合は
このファイルを削除してください（全ツールに効きます）。

---

## テスト

```
python test_gemini_proxy_20260817_01.py
```

偽の `gemini_client` を注入して、`generate_advanced()` に渡る payload と
レスポンス契約を検証します（79項目）。selenium / tkinter が無い環境でも動きます。

`..\common\gemini_client.py` が存在する場合は、実物を使ったパス解決テスト（J節）も
自動で走ります。無い場合はJ節がスキップされ、77項目になります。

> **このテストでは「プロキシ経由で実際にGeminiの応答が返るところ」は検証できません。**
> Claude Code の実行環境からは会社PCの共通モジュールにも自宅PCのプロキシにも
> 到達できないためです。実機での確認が必要です。

---

## バージョン管理

ルート `README.md` の開発ルールに従い、更新時はファイル名を
`BBT_lecture_script_getter_yyyymmdd_連番.py` として**旧バージョンは削除せず併存**させます。
変更点は `CHANGELOG.md` に記録します。

| ファイル | 内容 |
|---|---|
| `BBT_lecture_script_getter_20260817_01.py` | 最新版（Geminiプロキシ化） |
| `BBT_lecture_script_getter_20260804_01.py` | 旧版（直接 `google.generativeai` 呼び出し） |

## 関連資料

- `TOOLSHEET_bbt_lecture_organizer.md` — Geminiプロキシ化の調査結果シート
- `HANDOVER_gemini_proxy_common.md`（ローカル資料） — プロキシ化の共通ガイド
- `BBT サマリ開発 — Claude Code移管資料`（ローカル資料） — アーキテクチャ・開発ルール
