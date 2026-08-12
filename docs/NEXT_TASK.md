# NEXT_TASK

## Project Name

Onenote オーガナイザー開発

## Current Session

S01

## Current Session Title

Outlook オーガナイザー開発 S01 - 新規比較差分追加機能
（実体はOneNote Report Generatorの複数サーバー対応検討。プロジェクト名・
セッションタイトルの表記ゆれはユーザー提示のテンプレートをそのまま使用）

## Current Objective

あらたなサーバー上のOneNoteも取り込んで、内容をプロジェクトベースで比較検討する。
引継ぎ資料（`HANDOVER_onenote_report_generator.md`）6章の「次期タスク」と同一の依頼。

## Background

- 現行の認証（MSAL）・`_token`・`_extractor` はグローバル変数で、単一
  Microsoft 365 テナント・単一アカウントを前提とした設計（コード確認済み）。
- 一方、同一テナント内の複数SharePointサイトへの対応は `config.json` の
  `sites` 配列と `/api/sites` エンドポイントで既に実装済み（コード確認済み、
  VERSION 20260512_03_01）。
- 「別のOneNoteサーバー」が何を指すかは、引継ぎ資料で以下3パターンが
  想定されており、越智さんへの確認が必須とされている（推測で進めない原則）。
  1. 同一テナント内の別サイト/別ノートブック（→ 既に対応済みの可能性）
  2. 別のMicrosoft 365テナント（他社・他組織）のOneNote（→ マルチテナント
     認証が必要な大規模設計変更）
  3. 個人アカウント（Microsoftアカウント）のOneNote（→ 別認証フローが必要）

## Scope

- Phase 1（設計提案）：上記1〜3のどれに該当するかを越智さんに確認し、
  該当パターンに応じた設計案を提示する。**この段階ではコード生成を行わない。**
- Phase 2（監査）以降は、越智さんの「●３．承認します」の発言後に着手する。

## Files That May Be Changed

Phase 1では変更なし（設計提案のみ）。Phase 3着手後の想定範囲：

- `onenote_report_generator/onenote_report_generator_20260706_01.py`
  （認証・`_token`・`_extractor` 関連、必要に応じて `/api/sites` 等）
- `onenote_report_generator/templates/index.html`（テナント/サーバー切替UI等、必要な場合）
- `onenote_report_generator/config.example.json`
- `onenote_report_generator/CHANGELOG.md`

## Files That Must Not Be Changed

- 上記以外の全ファイル・全フォルダ（`po_database_organizer/` 等、他ツール一式）
- 依頼範囲外のメソッド・エンドポイント（「ついでに直す」禁止）

## Task

1. AskUserQuestion等で、越智さんに上記1〜3のどれに該当するかを確認する
2. 該当パターンに応じた設計案（A/B/C等）をPhase 1として提示する
3. 越智さんの案選択・承認を待つ（Phase 2監査を経てから実装）

## Completion Criteria

- 上記1〜3のどれに該当するか確定していること
- Phase 1設計提案が越智さんに提示されていること
- 既存機能に意図しない影響がないこと（Phase 3実装時）
- 必要なテストが実施されていること（Phase 3実装時）

## Required Tests

- Phase 3実装時：Python構文チェック、既存エンドポイントの回帰確認
- 越智さんの実機（Windows/Chrome）でのGraph API認証・複数サイト/複数テナント
  切替の実地確認（本リモートセッションでは実施不可）

## Known Risks

- グローバル変数 `_token` / `_extractor` は複数テナント・複数ユーザーの
  同時アクセスに対して競合リスクがある（Phase 2監査で必須の論点）
- `bookmarks.json` は現状「単一サイトのID」を前提としたデータ構造。複数
  サーバー対応時はサーバー識別子/テナント識別子フィールドの追加要否と
  後方互換性の設計判断が必要
