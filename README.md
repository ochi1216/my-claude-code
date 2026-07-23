# my-claude-code

## BBT RTOCS Organizer

セットアップ手順は [`rtocs_organizer/README.md`](rtocs_organizer/README.md) を参照。

## Shareflex Document Dashboard

セットアップ手順は [`shareflex_dashboard/README.md`](shareflex_dashboard/README.md) を参照。

## Project Cost Analyzer

セットアップ手順は [`project_cost_analyzer/README.md`](project_cost_analyzer/README.md) を参照。

## 開発ルール（バージョン管理）

- **ファイル命名**: プログラムを更新する際は、ファイル名を `ツール名_yyyymmdd_連番.py`（例: `rtocs_organizer_20260711_01.py`）とする。同日に複数回更新する場合は連番（`_01`, `_02`...）を上げる。
- **旧バージョンの保持**: バージョンアップ時に旧ファイルは削除・上書きしない。新旧のファイルをフォルダ内に併存させ、リポジトリから過去にpushしたバージョンをそのままダウンロードできる状態を維持する。
- **CHANGELOG**: 各ツールフォルダに `CHANGELOG.md`（Markdown形式）を置き、バージョンごとの変更点を記録する。