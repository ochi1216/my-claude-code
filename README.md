# my-claude-code

このリポジトリは `common/` を [gemini-common-tools](https://github.com/ochi1216/gemini-common-tools) の
git submoduleとして含む（会社PCでのGemini API直接アクセス遮断時、自宅PC経由プロキシへ自動フォールバックする
共通クライアント）。クローン時は以下でsubmoduleも取得すること。

```
git clone --recurse-submodules https://github.com/ochi1216/my-claude-code.git
# または、既にクローン済みの場合
git submodule update --init common
```

## BBT RTOCS Organizer

セットアップ手順は [`rtocs_organizer/README.md`](rtocs_organizer/README.md) を参照。

## analog_ic_se_strategy_organizer

セットアップ手順は [`analog_ic_se_strategy_organizer/README.md`](analog_ic_se_strategy_organizer/README.md) を参照。設計背景は [`DESIGN_analog_ic_se_strategy_organizer.md`](DESIGN_analog_ic_se_strategy_organizer.md)。

## PO Database Organizer

セットアップ手順は [`po_database_organizer/README.md`](po_database_organizer/README.md) を参照。

## Shareflex Document Dashboard

セットアップ手順は [`shareflex_dashboard/README.md`](shareflex_dashboard/README.md) を参照。

## 開発ルール（バージョン管理）

- **ファイル命名**: プログラムを更新する際は、ファイル名を `ツール名_yyyymmdd_連番.py`（例: `rtocs_organizer_20260711_01.py`）とする。同日に複数回更新する場合は連番（`_01`, `_02`...）を上げる。
- **旧バージョンの保持**: バージョンアップ時に旧ファイルは削除・上書きしない。新旧のファイルをフォルダ内に併存させ、リポジトリから過去にpushしたバージョンをそのままダウンロードできる状態を維持する。
- **CHANGELOG**: 各ツールフォルダに `CHANGELOG.md`（Markdown形式）を置き、バージョンごとの変更点を記録する。