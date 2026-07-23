# PROJECT_STATUS.md

最終更新: 2026-07-23 (S01)

## Project Overview

- プロジェクト名: Project Cost developer開発
- 目的: Project CostのKOB1シート（SAPのプロジェクトコスト実績明細データ）から、
  プロジェクト単位・事業部単位・職種単位でコスト分析を行うツールを開発する。
- 成果物: `project_cost_analyzer/` フォルダに、Excelファイル（KOB1シートを含む
  `.xlsm`/`.xlsx`）を読み込んで分析するStreamlitダッシュボードを新規開発した。

## Repository Structure

```
my-claude-code/
├── CLAUDE.md                      # セッション管理ルール
├── README.md                      # リポジトリ全体の開発ルール・ツール一覧
├── docs/                          # セッション管理ファイル
│   ├── PROJECT_STATUS.md
│   ├── SESSION_HISTORY.md
│   └── NEXT_TASK.md
├── HANDOVER_analog_ic_scout.md    # 他ツールの構想メモ（旧方式、本プロジェクトと無関係）
├── HANDOVER_youtube_summary_list.md
├── youtube_summary_list_20260703_01.py
├── youtube_summary_list_20260711_01.py
├── po_database_organizer/         # SharePoint PO書類カタログ化ツール（本プロジェクトと無関係）
├── rtocs_organizer/                # RTOCS企業戦略分析ツール（本プロジェクトと無関係）
├── shareflex_dashboard/            # Shareflex文書管理集計ダッシュボード（本プロジェクトと無関係）
└── project_cost_analyzer/          # 本プロジェクトの成果物（S01で新規作成）
    ├── project_cost_analyzer_20260722_01.py 〜 _13.py（最新版は_13、旧版は全て残置）
    ├── requirements.txt
    ├── README.md
    ├── CHANGELOG.md
    └── run_dashboard.bat           # フォルダ内最新版を自動判定して起動するWindows用バッチ
```

## Current Functions

`project_cost_analyzer_20260722_13.py`（最新版）時点の機能:

- **データ読み込み**: サイドバーからExcelファイルをアップロード、またはローカルパス指定で
  KOB1シートを読み込む。パース結果を`.kob1_cache/`（元ファイルの隣、またはOS一時フォルダ）
  にpickleキャッシュし、元ファイル未変更時は次回起動を高速化（実測: 初回15秒前後→再起動後
  2〜3秒）
- **3タブ構成**:
  1. 🏛 事業部俯瞰: 全Profit Center（R03/R04/R07/R0N/R0S/R19）横断のサマリー、
     プロジェクト費/非プロジェクト費比較、期間別コスト推移（棒グラフ・積み上げ切替）、
     Cost Category別/PM cost category別/Function別/Cost Element別の内訳（棒/円グラフ切替）、
     プロジェクト別コスト内訳、コスト種別深掘り（下記）
  2. 🧭 プロジェクト深掘り: 単一プロジェクトのカルテ、バーンチャート、Function別/組織別/
     コスト種別内訳、外部購買明細（PO単位）、工数投下(Man month, FY2026限定)、
     コスト種別深掘り（下記）
  3. 🔧 ファンクション横断: Function（職種）別のプロジェクト別・担当者別チャージ
- **コスト種別深掘り**（事業部俯瞰・プロジェクト深掘り両タブに搭載）: Function／
  Func.Category／B4P category／FSI Descriptionの4軸から選び、内訳グラフ→明細テーブルを
  表示。明細テーブルは金額列を除く全12列でのAND絞り込みフィルタ、列表示/非表示（フィルタと
  連動）、列選択での昇順/降順並び替え、Excelダウンロードに対応。さらに明細テーブル自体を
  期間別棒グラフ・軸選択式の棒/円グラフ（上位20/上位10/上位5＋その他切替）で可視化できる
  （折りたたみ式、既定は閉じた状態）
- **通貨表示**: 金額は全てUSD表示（`Val/COArea Crcy`はSAP統制領域通貨で元々単一通貨のため
  換算不要と確認済み）
- **設定の永続化**: ファイルパス・各種フィルタ・選択中プロジェクト/Function・分類軸・
  積み上げ/円グラフトグル等を`.pca_settings.json`に保存し、ツール再起動後も復元

## Confirmed Specifications

- 開発ルール（リポジトリ共通、`README.md` より）:
  - ファイル命名: `ツール名_yyyymmdd_連番.py`
  - 旧バージョンは削除・上書きせず併存させる
  - 各ツールフォルダに `CHANGELOG.md` を置き、バージョンごとの変更点を記録する
- KOB1シートは83,318行・30列（2026-07-22時点のユーザー提供ファイル）。金額列
  `Val/COArea Crcy`はUSD単一通貨（ブック内「Cost by nature」シートが"Cost in $"と明示、
  Company Code別金額規模でも裏付け済み）
- 工数(Man month)・担当者(Resource name)はFY2026分のみ記録（過去年度は金額のみ）
- Function/Func.Category列はTime Writing(内部労務)行にのみ値が入る。B4P category/
  FSI Description列はMaterial・Service(外部購買)行を対象にすると意味のある分解になる
  （内部労務行でこれらを使うとほぼ単一カテゴリに潰れるため）
- "SSC Package R&D"・"Quality"等の一部Functionは、個人単位のResource nameマッピングが
  されておらず、Function/Organization/Resource nameが同一値になる「バケット化」データで、
  KOB1データからは個人単位への分解ができない（92%程度がDocument Header Text空欄で追跡不可）
- Supabase等の外部サービスへのデータアップロードは、Claude Code Webの自動判定（安全分類器）
  にブロックされたため採用せず、ローカル完結構成（Excel直接読み込み→ローカル集計→
  Streamlit表示）を正式な方針として確定
- ユーザーの実運用パス:
  `C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost\BG ICS Project cost summary_20260722.xlsm`
- 予算(Budget/Committed)との対比分析（`Project cost against BC`シート等との突き合わせ）は
  提案のみ行い、実装はスコープ外のまま保留中

## Current Status

- S01: セッション管理ファイル導入後、同一セッション内でKOB1コスト分析ツールを新規開発。
  `_01`（初版）から`_13`（最新版）まで、ユーザーからのフィードバックを反映しながら反復開発。
  全てコミット・Push済み（詳細は`docs/SESSION_HISTORY.md`参照）。

## Known Issues

- Streamlitのselectboxウィジェットに、`session_state`経由で値を復元した際にプルダウンの
  表示ラベルだけが最初の選択肢のまま更新されない癖がある（`_06`で、ウィジェット自体のkeyと
  永続化keyを分離し`index`を明示計算する方式で回避済み。新規にselectboxを追加する際は
  同じパターンを踏襲すること）
- Plotlyの円グラフは既定で反時計回りに配置されるため、`_11`で`sort=False`+
  `direction="clockwise"`を明示指定して時計回り・大きい順にした（`render_breakdown()`に
  今後手を入れる際はこの指定を維持すること）
- `st.dataframe`標準の列非表示アイコン（テーブル右上の目のアイコン等）は、アプリ独自の
  「表示する列」ウィジェットとは連動しない（Streamlit側がPython側に状態を返さないため技術的に
  同期不可）。`_12`でその旨を注記表示して対応済み

## Test and Execution

- 実行方法: `project_cost_analyzer/`フォルダで`pip install -r requirements.txt`後、
  `streamlit run project_cost_analyzer_20260722_13.py`。Windowsでは`run_dashboard.bat`
  実行でフォルダ内最新版を自動起動
- テスト方法: 本セッションでは、実データ（KOB1シート）でのコアロジック検証（pandas単体、
  合計値の突合）と、Streamlitを実起動しPlaywrightでブラウザ経由の実機動作確認（UI操作・
  グラフ表示・フィルタ・設定復元等）を毎バージョンで実施
- 自動テストコード（pytest等）は未整備。テストは都度スクラッチで作成・実行し、恒久的な
  テストスイートとしては残していない

## Important Restrictions

- APIキー・パスワード・認証情報はコミットしない。
- コミット・Pushはユーザーの明示的な指示がある場合、またはセッション終了処理の
  場合に限る。
- 既存の他ツール（`po_database_organizer/`, `rtocs_organizer/`,
  `shareflex_dashboard/` 等）には本プロジェクトの作業で影響を与えない。
- `.pca_settings.json`と`.kob1_cache/`は環境依存・機密データを含み得るため、
  `.gitignore`でGit管理対象外にしている（`.pca_settings.json`）か、そもそもリポジトリ外
  （`.kob1_cache/`は元データファイルの隣かOS一時フォルダ）に配置している。
