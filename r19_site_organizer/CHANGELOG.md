# CHANGELOG — r19_site_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [20260817_01] - 2026-08-17

**追加ファイル:** `r19_site_organizer_20260817_01.py`, `fix_textcontent.py`, `config.example.json`, `sites_list.example.json`, `quick_links.example.json`, `requirements.txt`, `README.md`

- 別リポジトリ運用で開発されていた「R19 Site Organizer」（社内Windows PC上でローカル運用、`R19_site_organizer_20260519_01_10.py`）をこのリポジトリに移管。
- 移管前の開発履歴（v20260519.01〜.09時点）は、移管元の `PROGRESS.md` / `CLAUDE.md`（引継ぎ資料）に記録されていたもの。要点:
  - v20260519.01: 全サイト横断モードで探索深さ1/2階層を選択可能化
  - v20260519.02: フォルダ選択ダイアログ経由のダウンロード（個別・一括）+ 前回フォルダ記憶を追加
  - v20260519.03: `JSON.stringify`によるonclick属性内SyntaxError、および`pick-folder`のWindowsパス処理バグを修正
  - v20260519.04: ダウンロード先にサイト名サブフォルダを自動作成するよう変更
  - v20260519.05/06: Tab3/Tab2のフォルダ展開状態保持を実装（`CSS.escape()`バグ修正含む）
  - v20260519.07: キャッシュリセット後に`drive_id`が消失するバグを修正
  - v20260519.08/09: `textContent`→`innerHTML` 全20箇所修正（絵文字文字化け解消）
  - 移管時点のファイル名連番は`.10`まで進んでいたが、`.10`時点の変更内容を記録したドキュメントは提供されていない（未確認）。
- 移管に伴い、ファイル命名規則をこのリポジトリの標準（`ツール名_YYYYMMDD_連番.py`、単一連番）に統一。元のファイル名は `R19_site_organizer_YYYYMMDD_MM_NN.py`（2段連番）だった。
- 移管に伴い、開発ワークフローも移管元固有の「Design Proposal→Architecture Audit→Implementation Patch」3フェーズ承認制から、このリポジトリの標準セッション管理ルール（`CLAUDE.md`）に統一。
- テナント全体のサイト一覧マスター（`sites_list_*.json`、実サイト2,821件・実サイトID含む）とクイックリンクマスター（`quick_links_*.json`、実サイトURL含む）は実際の業務データのため、リポジトリにはコミットせず、スキーマのみの`*.example.json`をコミット。
- 起動用の`.bat`スクリプトは未提供のため今回の移管対象外（README参照）。

### 未解決事項（移管元から引き継ぎ、このリポジトリでは未着手）

- drive_id失効時の自動再取得ロジック（現状はサーバー再起動で対応）
- Tab2リストモードボタン絵文字の実機最終確認
- `sites_list_*.json`の生成方法が未確認
