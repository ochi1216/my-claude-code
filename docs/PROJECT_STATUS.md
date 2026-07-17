# PROJECT_STATUS.md

## Project Overview

- **プロジェクト名**: Target Point Video Organizer
- **目的・要件**: 未確認（ユーザーからの実作業依頼が未指定のため）
- **リポジトリ**: `ochi1216/my-claude-code`（複数の個人用業務効率化ツールを格納するモノレポ）
- **作業ブランチ**: `claude/target-point-video-organizer-s01-775l4x`

## Repository Structure

リポジトリ直下（2026-07-17 時点、S01セッション開始時に確認）:

```
my-claude-code/
├── CLAUDE.md                          (S01で新規作成)
├── README.md
├── HANDOVER_analog_ic_scout.md        (未着手コンセプトの引継ぎ資料)
├── HANDOVER_youtube_summary_list.md   (youtube_summary_listプロジェクトの引継ぎ資料)
├── youtube_summary_list_20260703_01.py
├── youtube_summary_list_20260711_01.py
├── po_database_organizer/             (PO書類カタログ化ツール、稼働中)
├── rtocs_organizer/                   (RTOCSダッシュボード/戦略レポート生成、稼働中)
├── shareflex_dashboard/               (Shareflex文書ダッシュボード、稼働中)
└── docs/                              (S01で新規作成、Target Point Video Organizer用)
    ├── PROJECT_STATUS.md
    ├── SESSION_HISTORY.md
    └── NEXT_TASK.md
```

**Target Point Video Organizer 専用のフォルダ・ファイルはリポジトリ内にまだ存在しません。**
既存の `youtube_summary_list_*.py`（動画関連ツール）との関係も未確認です。

## Current Functions

未確認（実作業が未指定のため、Target Point Video Organizerとしての機能はまだ存在しない）。

## Confirmed Specifications

未確認。

## Current Status

- 管理ファイル（`CLAUDE.md`, `docs/PROJECT_STATUS.md`, `docs/SESSION_HISTORY.md`, `docs/NEXT_TASK.md`）を導入済み。
- S01の実作業内容（今回の依頼・対象ファイル・完了条件）はユーザー未記入のため、着手待ち。

## Known Issues

未確認。

## Test and Execution

未確認（対象コードが存在しないため）。

## Important Restrictions

- リポジトリ共通の開発ルール（`CLAUDE.md` 参照）: ファイル名バージョニング（`ツール名_yyyymmdd_連番.py`）、旧バージョン非削除、ツールフォルダごとの `CHANGELOG.md`。
- APIキー・パスワード・認証情報はコミットしない。
- ユーザーの指示なしにマージ・リベース・リセットを行わない。
- セッション終了処理（`SESSION_HISTORY.md`確定記録・`NEXT_TASK.md`更新・最終コミット・Push）はユーザーが明示的に指示した場合のみ実施する。
