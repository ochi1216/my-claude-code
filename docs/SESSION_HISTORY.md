# Session History

## Session Index

| Session | Title | Date | Status | Main Files |
| ------- | ----- | ---- | ------ | ---------- |
| S01 | Project Cost developer開発 S01 - KOB1の分析ツール | 2026-07-22〜2026-07-23 | 完了 | CLAUDE.md, docs/PROJECT_STATUS.md, docs/SESSION_HISTORY.md, docs/NEXT_TASK.md, project_cost_analyzer/（_01〜_13）, README.md |

## S01 詳細

### 目的

Project CostのKOB1シート（SAPプロジェクトコスト実績明細）から、プロジェクト単位・
事業部単位・職種単位でコスト分析を行うツールを新規開発する。

### 実施内容

- 管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`,
  `docs/NEXT_TASK.md`）を初期導入
- ユーザー提供のKOB1データ（83,318行・30列）を分析し、通貨（USD単一通貨）・列構造・
  データの欠損パターン等を確認
- Supabaseへのデータ登録を試みたが、機密データの外部送信がClaude Code Webの安全分類器に
  ブロックされたため、ローカル完結型のStreamlitダッシュボード構成に方針転換
- `project_cost_analyzer/`フォルダを新規作成し、`_01`から`_13`まで反復開発:
  - `_01`: 初版（読み込み・プロジェクト別/期間別/カテゴリ別集計・Excel出力）
  - `_02`: ディスク/セッションキャッシュ追加（起動時間短縮）
  - `_03`: 3タブ構成（事業部俯瞰/プロジェクト深掘り/ファンクション横断）へ再編、
    USD統一、棒/円グラフ切替
  - `_04`: サイドバーに実行中ファイル名の常時表示を追加
  - `_05`: プロジェクト深掘りタブの残りのグラフにも棒/円グラフ切替を追加
  - `_06`: 設定永続化のバグ修正（保存対象漏れ・保存タイミング・表示ラベル復元不具合）
  - `_07`: コスト種別深掘り機能を新規追加（Function/Func.Category/B4P category/
    FSI Descriptionの4軸、フィルタ・並び替え付き明細）
  - `_08`: コスト種別深掘りをプロジェクト深掘りタブにも追加
  - `_09`: 明細テーブルのフィルタを全列に拡張し、列表示/非表示と連動させた
  - `_10`: 明細テーブル自体の可視化（期間別棒グラフ・軸選択式内訳グラフ）を追加
  - `_11`: 円グラフの並び順を時計回り・大きい順に修正、内訳グラフを「上位10/5＋その他」化
  - `_12`: 列非表示機能の説明注記追加、グラフ化セクションを折りたたみ式に変更
  - `_13`: 内訳グラフの表示件数に「上位20」を追加
- 各バージョンで実データを用いたコアロジック検証と、Streamlit実起動＋Playwrightによる
  ブラウザ実機確認を実施

### 変更したファイル

- `project_cost_analyzer/project_cost_analyzer_20260722_01.py`〜`_13.py`（新規、全13版）
- `project_cost_analyzer/requirements.txt`（新規）
- `project_cost_analyzer/README.md`（新規）
- `project_cost_analyzer/CHANGELOG.md`（新規、各版ごとに追記）
- `project_cost_analyzer/run_dashboard.bat`（新規、フォルダ内最新版を自動起動）
- リポジトリ直下 `README.md`（新ツールへのリンク追記）
- リポジトリ直下 `.gitignore`（`.pca_settings.json`を除外対象に追加）
- `CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`,
  `docs/NEXT_TASK.md`（新規・本セッションで導入・更新）

### 確定した仕様

- 金額表示はUSD単一通貨（換算処理なし）
- ローカル完結構成（外部サービスへのデータアップロードは行わない）
- コスト種別深掘りは内部労務(Function/Func.Category)と外部購買(B4P category/
  FSI Description)で対象Cost Categoryを使い分ける
- 円グラフは時計回り・大きい順、内訳グラフの表示件数は上位20/10/5＋その他から選択
- 列の表示/非表示はアプリ独自の「表示する列」ウィジェットで行い、フィルタと連動させる
  （Streamlit標準の列非表示機能は非連動）

### テスト結果

- 実データでの集計値（プロジェクト別・期間別・事業部別合計）が全体合計と一致することを
  各バージョンで確認
- Streamlit実起動＋Playwrightによる実機確認: データ読み込み、3タブの表示、フィルタ・
  並び替え・円グラフ切替・設定復元（プロセス再起動を挟んだ確認含む）、コスト種別深掘りの
  軸切替・明細フィルタ・可視化を確認済み
- 自動テストスイート（pytest等）は未整備

### 未確認事項

- 実際のWindows環境（ユーザーのPC）での`run_dashboard.bat`経由の起動・操作性は、
  ユーザー自身による実行結果の報告ベースで確認（本セッションのサンドボックス環境では
  Linux上でのStreamlit実行・Playwright確認のみ）
- 大規模データ（KOB1データが今後さらに増加した場合）でのキャッシュ・描画パフォーマンスは
  未検証

### 次回作業

- 未定。ユーザーからの次回タスク指示待ち（詳細は`docs/NEXT_TASK.md`参照）
