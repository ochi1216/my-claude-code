# PROJECT_STATUS.md

最終更新: 2026-07-22 (S01)

## Project Overview

- プロジェクト名: Project Cost developer開発
- 目的: Project CostのKOB1シート（SAPのプロジェクトコスト実績明細データ）から、
  該当プロジェクトのコスト分析を行うツールを開発する。
- リポジトリ内での位置付け: `my-claude-code` リポジトリは複数の独立業務ツールを
  格納するモノレポであり、本プロジェクトは新規ツールとして追加される想定。
  ツール専用フォルダ名・出力形式などの詳細仕様は未確認（S01時点で未着手）。

## Repository Structure

```
my-claude-code/
├── CLAUDE.md                      # 本セッション管理ルール（S01で新規作成）
├── README.md                      # リポジトリ全体の開発ルール・ツール一覧
├── docs/                          # セッション管理ファイル（S01で新規作成）
│   ├── PROJECT_STATUS.md
│   ├── SESSION_HISTORY.md
│   └── NEXT_TASK.md
├── HANDOVER_analog_ic_scout.md    # analog_ic_scout構想の引継ぎメモ（旧方式）
├── HANDOVER_youtube_summary_list.md
├── youtube_summary_list_20260703_01.py
├── youtube_summary_list_20260711_01.py
├── po_database_organizer/         # SharePoint PO書類カタログ化ツール
├── rtocs_organizer/                # RTOCS企業戦略分析ツール
└── shareflex_dashboard/            # Shareflex文書管理集計ダッシュボード
```

Project Cost / KOB1関連のフォルダ・ファイルはリポジトリ内に存在しない（S01時点、
全文検索・全ファイル名検索で確認済み）。

## Current Functions

Project Cost / KOB1分析ツールとしての機能は未確認（S01時点で未実装）。

参考: リポジトリ内の既存ツールは共通して「業務システムからの手動エクスポート
（Excel/CSV）→ ローカルで読み込み・集計 → Streamlitダッシュボード or 静的HTML出力」
という構成を取っている（`po_database_organizer/`, `rtocs_organizer/`,
`shareflex_dashboard/` のREADME参照）。

## Confirmed Specifications

- 開発ルール（リポジトリ共通、`README.md` より）:
  - ファイル命名: `ツール名_yyyymmdd_連番.py`
  - 旧バージョンは削除・上書きせず併存させる
  - 各ツールフォルダに `CHANGELOG.md` を置き、バージョンごとの変更点を記録する
- KOB1データの入手方法・列構成・対象プロジェクトの絞り込み条件・希望する分析軸
  （コスト要素別／期間推移／予算対実績など）: 未確認

## Current Status

- S01: セッション管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`,
  `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）を新規導入。
- KOB1分析の実作業は、対象データファイルの仕様確認待ちのため未着手（詳細は
  `docs/NEXT_TASK.md` を参照）。

## Known Issues

なし（S01時点、実装未着手のため該当なし）。

## Test and Execution

Project Cost / KOB1分析ツールのテスト・実行方法は未確認（S01時点で未実装）。

## Important Restrictions

- APIキー・パスワード・認証情報はコミットしない。
- コミット・Pushはユーザーの明示的な指示がある場合、またはセッション終了処理の
  場合に限る。
- 既存の他ツール（`po_database_organizer/`, `rtocs_organizer/`,
  `shareflex_dashboard/` 等）には本プロジェクトの作業で影響を与えない。
