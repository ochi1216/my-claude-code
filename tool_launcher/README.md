# Tool Launcher

`my-claude-code` 配下の各ツールと、旧 `PythonScripts` に残っているツールを、
1つの画面からまとめて起動するランチャー。

旧 `PythonScripts\tool_launcher_20260808_01.py`（Git管理外）の後継。
旧ランチャーは削除せずそのまま残してあるため、問題があればいつでも戻せる。

## 構成

| ファイル | 役割 |
| --- | --- |
| `tool_launcher_yyyymmdd_NN.py` | ランチャー本体（GUI・起動制御・git pull） |
| `tools.json` | ツール定義。**ツールの増減はこのファイルだけで行う** |
| `run_tool_launcher.bat` | 起動用バッチ。デスクトップショートカットのリンク先 |
| `launcher_log.txt` | 実行ログ（自動生成、`.gitignore` 対象） |

## セットアップ（初回のみ）

1. 会社PCで `my-claude-code` を最新にする。

   ```
   cd /d "%USERPROFILE%\Documents\PythonScripts\my-claude-code"
   git pull
   ```

2. デスクトップにある既存の「ツールランチャー」ショートカットを右クリック →
   プロパティ → **リンク先**を次の値に差し替える（アイコン・名前はそのままでよい）。

   ```
   C:\Users\<ユーザー名>\Documents\PythonScripts\my-claude-code\tool_launcher\run_tool_launcher.bat
   ```

3. 同じプロパティ画面の**作業フォルダー**を、上記から `\run_tool_launcher.bat` を
   除いたフォルダパスにする。

4. ショートカットをダブルクリックして起動する。

> **補足**：起動直後に黒いコンソールが一瞬見えるが、GUIが開いた時点で自動的に
> 隠れる。気になる場合は、同じプロパティ画面の**実行時の大きさ**を「最小化」に
> しておくとよい。

## 画面の見かた

- **タイル左端の縦ストライプ**が Gemini API の呼び出し方式を表す。
  - 緑 `■ PROXY` … プロキシ経由（会社PCで直接呼び出しが遮断された後の方式に移行済み）
  - 橙 `□ DIRECT` … 直接呼び出しのまま（未移行）
  - 無色 … Gemini を使わないツール
- **`BAT` / `PY` / `STREAMLIT` バッジ**が起動方式を表す。`PY` は「まだ `.bat` を
  整備していない」という意味でもあり、整備が進むと `BAT` に変わる。
- **`移管予定` バッジ**は、自宅PCへ移管予定のツール。
- **差し色（`#e94560`）はホバー中のタイルと「🔄 更新」ボタンにのみ使う。**
- 画面下部の**ログ枠**に、起動したファイル名・PID・エラー内容が出る。
  同じ内容が `launcher_log.txt` にも残る。

## ツールを追加・変更する

`tools.json` の `tools` 配列に1エントリ追加するだけでよい。**本体の `.py` は編集しない。**
画面右上の「⚙ tools.json」ボタンから直接開ける。編集後はランチャーを再起動する。

```json
{
  "id": "my_new_tool",
  "label": "新しいツール",
  "category": "excel_pm",
  "root": "repo",
  "kind": "bat",
  "path": "my_new_tool/run_my_new_tool.bat",
  "gemini": "proxy",
  "status": "active"
}
```

| フィールド | 値 | 意味 |
| --- | --- | --- |
| `id` | 任意の一意な文字列 | 内部識別子 |
| `label` | 表示名 | ボタンに出る文字列 |
| `category` | `categories` のいずれかの `id` | 所属カテゴリ |
| `root` | `repo` / `legacy` | `my-claude-code` 配下か、旧 `PythonScripts` 配下か |
| `kind` | `bat` / `py` / `streamlit` | 起動方式（下記） |
| `path` | `root` からの相対パス | `bat` はファイルパス、`py`/`streamlit` は**ファイル名の接頭辞** |
| `gemini` | `proxy` / `direct` / `none` | ■ / □ / 対象外 |
| `status` | `active` / `planned_move` / `hidden` | 通常 / 移管予定バッジ / 非表示 |

### `kind` の使い分け

- **`bat`** … `path` で指定した `.bat` を `cmd /c` 経由で起動する。最新バージョンの
  選択・依存関係の解決は `.bat` 側の責任。**移行済みツールはこれを使う。**
- **`py`** … `path` を接頭辞として `<接頭辞>*.py` を検索し、**最も新しいバージョンを
  1本選んで**起動する。`.bat` をまだ整備していないツール、および旧 `PythonScripts`
  に残っているツール用。
- **`streamlit`** … `py` と同じ方法で最新版を選び、`python -m streamlit run` で
  起動する。`rtocs_dashboard` のような Streamlit アプリ用。

### バージョン番号の形式

`kind` が `py` / `streamlit` のとき、最新版の判定には次の2形式を使う。

- `ツール名_yyyymmdd_NN.py`
- `ツール名_yyyymmdd_NN_MM.py`

どちらにも一致しないファイルは常に「最も古い」と判定されるため、選ばれない。
`.py` 以外の拡張子は候補に入らない。サブフォルダは検索しない。

### `run_*.bat` の自動検出

`tools.json` に載っていない `run_*.bat` が `my-claude-code` 直下のフォルダに
あると、**「⚙ 未登録」カテゴリに自動で表示される**。新しいツールを作って `.bat`
を置けば、`tools.json` を編集しなくてもひとまず起動できる。
正式に登録するときは、表示名やカテゴリを決めて `tools.json` に追記する。

## 🔄 更新ボタン

`my-claude-code` フォルダで `git pull --ff-only` を実行し、結果をログ枠に表示する。

- **失敗しても自動修復は一切しない。** `git stash`・`git reset`・`git checkout` は
  実行しない。競合や未コミットの変更がある場合は、コマンドプロンプトで手動で対処する。
- pull によって**ランチャー本体が新しくなった場合は、再起動を確認するダイアログ**が出る。
- 起動時の自動 pull は行わない。ネットワークが不調なときに起動が止まるのを避けるため。

## 動作環境

| 項目 | 内容 |
| --- | --- |
| OS | Windows（Windows固有処理は `sys.platform` で分岐） |
| Python | `python` コマンドで解決されるもの。会社PCでは `C:\Program Files\Python\python.exe`（3.13.3） |
| 追加ライブラリ | **なし**（標準ライブラリのみ。`psutil` にも `customtkinter` にも依存しない） |
| 仮想環境 | 使わない（システムPython直） |

### `py` コマンドを使ってはいけない

会社PCの `py` は `...\Python313\python3.13t.exe`（Python 3.13.5 の**実験的
フリースレッディングビルド**）に解決される。この環境では次の問題が起きる。

- `pywin32` … メッセージを出さずにプロセスが落ちる（アクセス違反）
- `google-genai` … `pydantic_core` のフリースレッディング版ホイールが無く import 失敗

`run_tool_launcher.bat` は `python` のみを使い、`py` へのフォールバックを持たない。
他ツールの `.bat` を新設・改修するときも同じ方針にすること。

## 既知の制約

- 多重起動防止は**Windowsの名前付きミューテックス**で行う。Windows以外では機能しない。
- `root: legacy` のツールは、フォルダを移動・改名すると起動に失敗する。
  そのときは「対象の .py ファイルが1件も見つかりません」と検索パターンを表示するので、
  `tools.json` の `path` を直す。
- GUI・Windows API・`cmd /c` の実動作は開発環境（Linuxコンテナ）では検証できない。
  実機での確認が必要。

## 関連

- 変更履歴: [`CHANGELOG.md`](CHANGELOG.md)
- リポジトリ全体のルール: ルート [`README.md`](../README.md) の「開発ルール」節
