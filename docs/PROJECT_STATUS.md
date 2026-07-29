# PROJECT_STATUS.md

最終更新: 2026-07-29 (S01)

## Project Overview

- プロジェクト名: 緊急連絡ツールの開発
- 目的: 緊急地震速報（大分県・大阪府・東京都、震度5弱以上）を検知した際に、
  緊急連絡網の18名のスタッフへ安否確認を送信し、各スタッフが
  「無事/被災」「職場/自宅」「出社可能/出社不可能」の3項目をクリックで回答すると、
  即座に上司3名へ通知される仕組みを構築する。
- 前提環境: Microsoft 365（Microsoft Graph API等の利用を想定）。

## Repository Structure

`my-claude-code` は複数の独立した社内向けPythonツールを
`ツール名/` フォルダ単位で管理するモノレポ。

```
my-claude-code/
├── CLAUDE.md                  # セッション/開発運用ルール（S01で新規作成）
├── README.md                  # リポジトリ全体の開発ルール（バージョン管理規約）
├── docs/                      # プロジェクト管理ファイル（S01で新規作成）
│   ├── PROJECT_STATUS.md
│   ├── SESSION_HISTORY.md
│   └── NEXT_TASK.md
├── emergency_alert_tool/      # 本プロジェクトの成果物（S01で新規作成）
├── po_database_organizer/     # 既存ツール（他プロジェクト、本作業では変更しない）
├── rtocs_organizer/           # 既存ツール（他プロジェクト、本作業では変更しない）
├── shareflex_dashboard/       # 既存ツール（他プロジェクト、本作業では変更しない）
├── HANDOVER_analog_ic_scout.md      # 既存の別プロジェクト引継ぎ資料
├── HANDOVER_youtube_summary_list.md # 既存の別プロジェクト引継ぎ資料
└── youtube_summary_list_*.py         # 既存の別プロジェクト成果物
```

既存フォルダ（`po_database_organizer/`, `rtocs_organizer/`, `shareflex_dashboard/` 等）は
本プロジェクトとは無関係の別ツールであり、本プロジェクトでは変更しない。

## Current Functions

`emergency_alert_tool/` フォルダの内容は S01 の「実作業」セクション、
および同フォルダ内の `README.md` / `CHANGELOG.md` を参照。

## Confirmed Specifications

- 監視対象都府県: 大分県、大阪府、東京都
- トリガー閾値: 震度5弱以上
- 通知対象: 緊急連絡網のスタッフ18名
- スタッフの回答項目（3項目、クリックで選択）:
  1. 安否: 無事 / 被災
  2. 場所: 職場 / 自宅
  3. 出社可否: 出社可能 / 出社不可能
- 回答が送信されたら、即座に上司3名へ通知する。
- 前提環境: Microsoft 365。

## Current Status

- S01時点: プロトタイプ実装段階。実際のAzure ADアプリ登録・M365テナントへの
  接続確認は未実施（このセッション環境から実テナントへの疎通は未確認）。
- 緊急地震速報の取得元API・実データスキーマは、外部ドキュメントへの
  アクセスが本セッション環境では制限されていたため、既知情報を基にした
  想定実装であり、実データでの検証は未確認。

## Known Issues

- 回答リンクはトークン方式（URLに含めるワンタイムトークン）であり、
  Azure AD認証（SSO）は行っていない。本番運用時はセキュリティ要件を
  再検討する必要がある（詳細は `emergency_alert_tool/README.md` 参照）。
- 緊急地震速報の実データ取得元（API）は本番運用前に実データでの
  検証が必要（未確認）。
- 実際のメール送信・Teams通知が本物のM365テナントで動作するかは未確認
  （このセッションでは自動テストによるロジック検証とモックによる
  送信処理の検証のみ実施）。

## Test and Execution

`emergency_alert_tool/README.md` の実行手順、および同フォルダの
テストファイルを参照。S01で実施したテスト結果は
`docs/SESSION_HISTORY.md` のS01エントリに記録する。

## Important Restrictions

- 既存の他ツールフォルダ（`po_database_organizer/` 等）は変更しない。
- APIキー・パスワード・クライアントシークレット等の認証情報はコミットしない。
- コミット・Pushはユーザーが明示的に指示した場合のみ行う。
