# 引継ぎ資料: youtube_summary_list プロジェクト

**作成日**: 2026-07-10
**引継ぎ元**: Claude (claude.ai チャットスレッド)
**引継ぎ先**: Claude Code
**対象者**: 越智さん（プログラム初心者と自認・厳格なワークフロー運用者）

---

## 1. プロジェクト概要

YouTubeプレイリスト内の動画を自動要約し、HTMLサマリーレポートを生成するPythonツール。
Selenium + Chrome（デバッグポート接続）+ Glasp/API要約エンジンで動作する。

### 動作環境
- **OS**: Windows
- **作業ディレクトリ**: `C:\Users\nx023836\Documents\PythonScripts\Youtube\`
- **Python**: `C:\Users\nx023836\AppData\Local\Programs\Python\Python313\python.exe`（固定パス起動）
- **Chrome**: デバッグポート9222、専用プロファイル `%LOCALAPPDATA%\ChromeDebugProfile9223`
- **UIフレームワーク**: Tkinter（ライトテーマ `#f0f0f0`）

### 関連ファイル群
| ファイル | 役割 |
|---|---|
| `youtube_summary_list_YYYYMMDD_NN[_NN].py` | 本体（最新: `20260703_01`） |
| `run_youtube_summary_auto.bat` | Automode起動バッチ（VERSION 20260515_01_01） |
| `config.json` | ConfigManagerが読む設定（`playlists.fixed`キーでプレイリスト上書き可） |
| `config/playlists.json` | プレイリストID定義。**ただし本体コードからは現状未参照**（重要な罠・後述） |
| `learned_channels.json` | チャンネルメタデータ・favorites・登録者数 |
| `summary_database.json` | 要約DB |
| `output/summary_{playlist}_{timestamp}.html` | 出力HTML |
| `logs/run_log_*.log` | BATの実行ログ |

### 兄弟プロジェクト（同一エコシステム・別ファイル）
- `Youtube_List_Setup_*.py`: 動画取得→プレイリスト登録ツール（Selenium+Tkinter、ヘッドレス対応）
- `Youtube_Playlist_management`: チャンネル→プレイリスト割当GUI（`ChannelRulesManager`）
- `consolidated_html_summary_manager`: HTML要約の統合ダッシュボード管理

---

## 2. 開発ワークフロー（厳守事項）

越智さんは**3フェーズワークフロー**を厳格に運用している。**勝手にコードを書いてはいけない。**

1. **Phase 1: Design Proposal v1.0** — 設計提案とQ&Aのみ。コード生成禁止。
2. **Phase 2: Architecture Audit v2.0** — 批判的検証。承認ゲート表・デビルズチェック・副作用リスクTop3・ロールバック条件・不足情報を提示。
3. **Phase 3: Implementation Patch v2.0** — 越智さんの明示的承認（`●３．承認します`等）後のみコード生成。

### Phase 3 出力規約
- Change Manifest（CHANGELOG.md形式・マークダウンコードブロック）を先頭に
- unified diff → 完全版コードの順（Diffのみは不合格）
- 変更前後の行数・差分を必ず表示
- 省略・中略の文言禁止（完全版関数を提示）
- テスト手順はコードブロック外に記載
- 変更しないことの「宣誓」を明記

### 原則
- **一石一鳥**: 1パッチ=1変更目的。関連修正でも目的が違えば別パッチ
- **UI変更禁止**: 明示的指示なしにUI・カラー変更不可（本ツールはライトテーマ維持）
- **バージョン命名**: `YYYYMMDD_NN` または `YYYYMMDD_NN_NN`（越智さんが指定した番号を使う）
- **回答**: 常に日本語。結論先出し→項目→詳細の順

---

## 3. このスレッドで実施した変更履歴

### VERSION 20260602_01_01 — 再生時間の抽出とHTML表示
**目的**: プレイリスト取得時に動画の再生時間を抽出し、HTMLサマリーの登録者数の右横に表示。

変更内容:
1. **`parse_duration_text(text) -> int`** 新規追加（`format_duration()` 直後、約1582行）
   - `"H:MM:SS"` / `"M:SS"` を秒数に変換。`"LIVE"`, `"PREMIERING"`, 空文字, `"4K"` 等の異常入力は全て `0` を返す
   - `len(parts)==1` のケースも明示的に `return 0`（Audit指摘対応）
2. **`get_playlist_videos_selenium` 内JSスクリプト**に `duration_text` 取得を追加
   - セレクタ: `ytd-thumbnail-overlay-time-status-renderer span#text, #overlays ytd-thumbnail-overlay-time-status-renderer span`
   - **重要な教訓**: JSはPythonのf-string内にあるため `{` `}` は `{{` `}}` エスケープ必須。初回パッチでこれを怠り `SyntaxError: let durationText...` が発生した
3. **`VideoInfo` 生成時**に `duration=parse_duration_text(data.get('duration_text', ''))` を追加
   - `VideoInfo.duration: int = 0` フィールドは元から存在（取得ロジックだけが未実装だった）
4. **HTML生成（`channel_display` 組み立て）**: 登録者数の右に `⏱ M:SS`（青 `#2b6cb0`、`&#x23F1;` エンティティ使用）。`duration=0` は非表示

テスト: `ast.parse` 構文チェック合格、`parse_duration_text` 9ケース+`format_duration` 4ケース全合格済み。

### VERSION 20260703_01 — プレイリストV・P+の追加
**目的**: プレイリスト選択を `ALL V S A B N M P+` に拡張。デフォルトは `□ALL ■V ■S ■A ■B ■N ■M □P+`（P+のみ標準OFF）。

変更内容:
1. **`ConfigManager.get_playlist_config`** の `default_playlists` に V を追加、順序を V S A B N M P+ L に整理
   - `"V": "PL0UGJjoPnxKgZaJvHD5lGzOmGnEAdrn9H"`
   - `"P+": "PL0UGJjoPnxKggbm7xrXUJQAExVbuca8-M"`（元から定義済み）
2. **`IntegratedSummaryApp.__init__` の `playlist_vars`**: V〜M は `value=True`、P+ は `value=False`
   - UIチェックボックスは辞書定義順で自動描画されるため、定義順=表示順
3. **`all_playlists_var` 初期値を `False` に変更**（P+がOFFなので全チェック揃いでない）
4. **`format_playlist_name` の `name_mapping`**: V・P+・L のコメントアウト解除
- ALLトグルは案A採用（ALL ON で P+ も ON になる）。`toggle_all_playlists` は変更不要

---

## 4. 未解決の不具合（次の作業・最優先）

### 🔴 バグ①: `--playlists` の `choices` に `'V'` が未登録 → Automode起動不能
- **場所**: `youtube_summary_list_20260703_01.py` の argparse 定義（約8354行）
- **現状**: `choices=['S', 'A', 'B', 'N', 'M', 'P+', 'L']` — `'V'` がない
- **症状**: BAT が `--playlists V S A B N M` を渡すため argparse がエラーで即終了し、Automodeが一切動かない
- **修正**: `choices=['V', 'S', 'A', 'B', 'N', 'M', 'P+', 'L']` に変更（1行）
- **ステータス**: 原因特定・修正案提示済み。**越智さんの承認待ち・パッチ未生成**

### 🟡 バグ②: `all_playlists_var` の初期値が `True` のまま残っている
- **場所**: 同ファイル 約6288行 `self.all_playlists_var = tk.BooleanVar(value=True)`
- 20260703_01 パッチで `False` にする予定だったが、越智さんの手元のファイルでは未反映と判明
- 影響は起動時のALLチェック表示ズレのみ（機能影響は軽微）
- **ステータス**: 修正案提示済み・承認待ち

**注意**: 上記2件を修正するバージョン番号は越智さんが指定する。勝手に採番しない。

### 参考: BATファイル側は修正済みの模様
最新アップロード版のBATでは実行行が `--playlists V S A B N M` に修正済み（以前は echo 行だけ V があり実行行に V がない不整合があった）。Python側の choices バグが残っているため現在も起動失敗する。

---

## 5. コードの重要な構造知識（調査済み事実）

### HTMLサマリーの記事順序の制御
- **プレイリスト上の並び順（`playlist_order`）が唯一の順序制御**。配信日時・チャンネル・登録者数によるソートは実装されていない
- フロー: JSがプレイリストDOMを上から走査し `playlist_order: i` を付与 → バッチ並列処理で `results_dict[video_id]` に完了順で格納（順序崩れる）→ **最終ソート（約5203〜5206行）で必ず元順序に整列**:
  ```python
  final_results = list(results_dict.values())
  original_order = {v.video_id: idx for idx, v in enumerate(videos)}
  final_results.sort(key=lambda x: original_order.get(x.video_info.video_id, 9999))
  ```
- **敗者復活戦（失敗動画のリトライ）が実行されても順序は崩れない**。リトライ結果は同じ `results_dict[video_id]` に上書きされ、最後に上記sortが効くため。越智さんに確認済み・仕様通り

### Automodeの仕組み
- `--auto` 引数 → `auto_mode_manager.enable()` → 起動5秒後に `auto_start_processing()` が発火
- Automodeは**GUIの `playlist_vars` チェック状態をそのまま使う**（Automode専用のプレイリスト指定なし）
- `--playlists` 引数指定時は全チェックOFF後に指定分のみON（`if playlist in self.playlist_vars` で安全にフィルタ）
- ダイアログは `auto_askyesno` / `auto_showinfo` 等のラッパーで自動応答

### 出力ファイル名
- `generate_html()` 内: `summary_{clean_filename(playlist_id[:30])}_{timestamp}.html`
- V → `summary_V_20260703_083000.html`
- P+ → `summary_P+_....html`（`clean_filename` は `+` を除去しない。Windowsでは合法だが一部ツールで問題になりうる。越智さんへ確認済み・現状対応不要の扱い）

### config の罠（超重要）
- `ConfigManager` は `config.json`（`CONFIG_FILE = "config.json"`）のみ読む
- `config/playlists.json` は存在するが**本体コードから未参照**。プレイリストIDの実体は `get_playlist_config()` 内の `default_playlists` ハードコード
- `config.json` の `playlists.fixed` が非空ならハードコードを上書きマージする
- 兄弟ツール側では「既存の `config/playlists.json` が古い内容のままバリデーションをパスする」既知の罠があるため、新カテゴリ追加時は手動削除が必要

### その他
- `clean_filename()`: Windows禁止文字除去・空白→`_`・最大15文字
- リトライ設定: `retry_count: 2` 等（約339行）。FATAL例外時はブラウザ強制再起動→同一バッチ2回まで再試行
- 敗者復活戦の前にブラウザを強制再起動してクリーン状態を作る設計（ゾンビタブ対策）

---

## 6. 既知の周辺課題（別パッチ・未着手）

- `datetime.min` 安全ガード（`upload_time` の None 処理）— 一石一鳥原則により別パッチ扱いで未着手
- `config/playlists.json` をコードから実際に読む構造への整理 — 今回スコープ外と合意済み
- 兄弟ツール `Youtube_List_Setup` 側: トリアージUI（`ttk.Treeview` 高密度テーブル化）の Phase 1 提案済み・Phase 2 はコード提供待ち

---

## 7. Claude Code での作業開始チェックリスト

1. `C:\Users\nx023836\Documents\PythonScripts\Youtube\` 内の最新ファイルを確認（BATは `dir /b /o-n youtube_summary_list_*.py` の**名前降順で最初の1件**を実行する点に注意。ファイル名の付け方次第で意図しないバージョンが動く）
2. 最優先タスク: バグ①（argparse choices への `'V'` 追加）— 越智さんに承認を得てからパッチ生成
3. 併せてバグ②（`all_playlists_var=False`）の反映確認
4. 修正後の検証: `python -c "import ast; ast.parse(open('<file>', encoding='utf-8').read())"` → BAT 実行 → `logs/run_log_*.log` と GUI 起動を確認
5. どんな小さな修正でも 3 フェーズワークフローと出力規約に従うこと

---

## 8. コミュニケーション上の注意

- 呼称は「越智さん」
- 回答は日本語・結論先出し
- 越智さんは鋭い仕様質問を投げてくる（例:「Automodeで V は動くのか」「リトライで順序は崩れないか」）。**コードの該当行を根拠に事実ベースで回答**すること。推測で答えると信頼を損なう
- 不明点は「不明」と明記して質問として列挙する
