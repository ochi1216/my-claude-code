# CHANGELOG — tool_launcher

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、
ここに変更点を追記する。

## [20260911_01] - 2026-09-11

**追加ファイル:** `tool_launcher_20260911_01.py`, `tools.json`, `run_tool_launcher.bat`,
`README.md`, `CHANGELOG.md`

**更新ファイル:** リポジトリ直下 `README.md`（本ツールの節を追加）, `.gitignore`（`launcher_log.txt` を除外）

旧 `PythonScripts\tool_launcher_20260808_01.py`（Git管理外・478行）の**全面作り直し**。
リポジトリ内で `git pull` により更新できるようにし、移行済みツールは `.py` の直接起動から
`.bat` 起動へ切り替えた。

### 背景

旧ランチャーは、開発拠点を `PythonScripts` 直下から `my-claude-code` リポジトリへ
移した際に大半のエントリがリンク切れとなり、30枠中17本がダミー化・コメントアウトされた
状態だった。加えて、Pythonのフルパス直書きなど複数の致命的な欠陥を抱えていた。

### 解決した欠陥（13件）

| # | 欠陥 | 対応 |
| --- | --- | --- |
| 1 | `python.exe` の絶対パス直書き（ユーザー名固定） | `.bat` 側へ移譲。本体は `sys.executable` を使用 |
| 2 | `py` へのフォールバックが危険 | `.bat` は `python` のみ。`py` は使わない（後述） |
| 3 | ダミー判定の不整合（`startswith("dummy_")` と実データ `"-"`） | ダミー概念そのものを廃止 |
| 4 | 30エントリ中17本がリンク切れ | `tools.json` で全17本を再定義 |
| 5 | `psutil` 依存（会社PCの `python` に未インストール＝起動不能） | 依存を削除 |
| 6 | 多重起動防止が二重に無効（未呼出＋判定文字列の不一致） | Windows名前付きミューテックス方式に置換 |
| 7 | 表示番号の重複（21〜25が各2回）、並び順と番号の不一致 | 番号を廃止し6カテゴリ表示に変更 |
| 8 | RTOCSの二重登録と ■/□ の矛盾 | `gemini` フィールドに昇格。重複を解消 |
| 9 | 最新ファイル検索が `.py` 以外も候補に含める | `<接頭辞>*.py` に限定 |
| 10 | `except: pass` の多用で失敗原因が消える | 例外種別ごとにログとダイアログで理由を提示 |
| 11 | `launcher_log.txt` が相対パス（CWD依存） | ランチャーフォルダ固定 |
| 12 | `Popen` の `text` / `encoding` 引数が無意味（パイプ未使用） | 削除 |
| 13 | コンソール監視スレッドの1秒ポーリング常駐 | 廃止。ログはGUI内の枠に表示 |

### 主な仕様

- **ツール定義の外部化**: 起動対象は `tools.json` で定義する。本体の `.py` を編集せずに
  ツールを増減・並べ替え・非表示にできる。画面右上の「⚙ tools.json」ボタンから開ける。
- **3つの起動方式**: `kind` が `bat`（`cmd /c` で `.bat` を起動）、`py`（最新の `.py` を
  `python` で起動）、`streamlit`（最新の `.py` を `python -m streamlit run` で起動）。
- **2つのルート**: `root` が `repo`（`my-claude-code` 配下）と `legacy`
  （`%USERPROFILE%\Documents\PythonScripts` 配下）。移行が完了したツールは
  `root` と `kind` を書き換えるだけで方式を切り替えられる。
- **`run_*.bat` の自動検出**: `my-claude-code` 直下のフォルダにある未登録の `run_*.bat` を
  「⚙ 未登録」カテゴリに自動表示する。
- **🔄 更新ボタン**: `git pull --ff-only` を実行し、結果をログ枠に表示する。
  ランチャー本体が更新された場合は再起動を確認する。
- **UI**: 6カテゴリ × 4列のタイル。`#1a1a2e` / `#e94560` の単一ダークテーマ
  （CLAUDE.md のUI規約に準拠）。差し色はホバー中のタイルと更新ボタンにのみ使う。
  タイル左端の縦ストライプで Gemini の呼び出し方式（緑=■プロキシ / 橙=□直接）を示す。

### 登録した17本

| カテゴリ | ツール | root | kind | gemini |
| --- | --- | --- | --- | --- |
| 📄 翻訳 | Word翻訳ツール | repo | bat | ■ |
| | PowerPoint翻訳ツール | repo | bat | ■ |
| | PDF翻訳ツール | repo | bat | ■ |
| | Excel翻訳ツール | repo | py | ■ |
| 📧 メール・文書 | Outlook管理ツール | repo | bat | ■ |
| | OneNote要約ツール | repo | py | ■ |
| 📊 Excel・PM | BCパラメータ抽出 | legacy | py | ■ |
| | LLフィードバックツール | legacy | py | □ |
| | VVCMチェッカー | legacy | py | − |
| 🔗 SharePoint | R19 SharePointツール | legacy | py | □ |
| | PO reportアップデート | legacy | py | □ |
| | SharePointリンクツール | legacy | py | − |
| 🧠 分析・戦略 | SE戦略立案 | repo | bat | ■ |
| | RTOCS連続要約（移管予定） | repo | py | ■ |
| | RTOCSダッシュボード（移管予定） | repo | streamlit | □ |
| 📚 情報収集 | Books検索統合ツール | legacy | py | − |
| | 図書館管理ツール | legacy | py | □ |

**旧ランチャーから除外したもの**（自宅PCへ移管済み、または未使用のため）:
Youtube関連3本、BBT講義スクリプトゲッター、RSS管理ツール、HTMLサマリ統合ツール、
YT PlayList登録修正ツール、PMインデックスセレクター、PMインデックスサーチ、
ダミーツール13枠。

**ランチャーに登録していない同居ツール**: `po_database_organizer`,
`shareflex_dashboard`, `youtube_summary_list_*.py`, `rss_organizer`（移管済み）。

### 実装中に判明し、設計に追加した点

- **`rtocs_dashboard` は Streamlit アプリだった**ため、`python <file>.py` では起動できない。
  `kind: "streamlit"` を新設し、`python -m streamlit run` で起動するようにした。
  `streamlit` コマンドを直接呼ばず `-m` 経由にしているのは、ランチャー自身と同じ
  インタプリタで確実に動かすため。
- **`py` コマンドは使用禁止**。会社PCの `py` は `python3.13t.exe`（Python 3.13.5 の
  実験的フリースレッディングビルド）に解決され、`pywin32` がメッセージなしでクラッシュし、
  `google-genai` は `pydantic_core` のホイールが無く import に失敗することを実機で確認した。
  `python` は `C:\Program Files\Python\python.exe`（3.13.3）に解決され、
  `pywin32` / `google-genai` / `streamlit` のすべてが揃っている。
- **`SharePointリンクツール` のパス**は旧ランチャーの `share_point\...` が誤りで、
  実際は `SharePoint\BC_tranfer\...` だった（実機で確認して訂正）。

### 動作確認時の注意

- **本ツールは Windows 専用**（`tkinter` GUI・Windows API・`cmd /c` に依存）。開発環境
  （Linuxコンテナ）では GUI の起動・見た目・実際のツール起動を一度も検証していない。
  実機での確認が必要。
- 開発環境で実施した検証は、GUI非依存ロジックのスタンドアロンハーネス56項目
  （バージョン抽出、最新ファイル選択、`tools.json` の整合性、repo配下ツールの実体確認、
  パス組み立て、`run_*.bat` の自動検出、旧欠陥13件の再発防止）と、
  `py_compile` による構文チェック、`run_tool_launcher.bat` のASCII純度チェックのみ。
- `legacy` 側8本の `.py` は開発環境に存在しないため、**実際に起動できるかは未検証**。
  パス文字列は実機の `dir` 出力で確認済み。
- 起動直後にコンソールが一瞬見え、GUIが開くと自動的に隠れる。GUIの組み上げ前に
  失敗した場合はコンソールが残り、traceback をそのまま読める。

### 変更していないもの（宣誓）

- 既存の `.bat` 5本（`word_translator`, `ppt_translator`, `pdf_translator`,
  `outlook_total_organizer`, `analog_ic_se_strategy_organizer`）は**一切変更していない**。
  venv 方針の見直しを含め、次セッション（S03）でまとめて扱う。
- 各ツール本体の `.py` 全ファイル
- `common/`（submodule）
- 旧ランチャー `PythonScripts\tool_launcher_20260808_01.py`（Git管理外。そのまま残す）
- `docs/` 配下

### 申し送り（次セッション S03 以降）

1. `.bat` 未整備の4本（Excel翻訳・OneNote要約・RTOCS連続要約・RTOCSダッシュボード）に
   `run_*.bat` を新設し、`tools.json` の `kind` を `bat` に変更する。
2. 既存 `.bat` 5本の venv 方針を見直す。会社PCには venv が1つも存在せず、
   `C:\Program Files\Python` に必要なパッケージが揃っていることを実機で確認済み。
   Word/PPT/PDF翻訳の3本は venv を作る設計のままなので、システムPython直に統一するか判断する。
3. RTOCS 2本の自宅PC移管が完了したら、`tools.json` から削除する。
