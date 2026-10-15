# Shareflex Document Dashboard

Nexus Document Management System（SharePoint / Shareflex、Nexperiaの品質文書管理サイト）
からエクスポートしたドキュメント一覧(Excel)を読み込み、組織軸(Department)と業務プロセス軸
(Top Level Process)の2系統でドキュメント件数を集計した静的HTMLダッシュボードを生成するツール。

サイトが `.mcas.ms`（Microsoft Defender for Cloud Apps経由のプロキシ）配下にあり、
Graph API等での自動取得は社内ポリシーでブロックされる可能性があるため、まずは
「手動エクスポート → ローカル集計」というオフラインで完結する構成にしている。

## 必要要件

- Python 3.9以上

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. SharePointの `All Documents` ビューで、必要であれば列を以下がすべて含まれるように調整し、
   「Excelにエクスポート」でファイル(.xlsx)をダウンロードする。

   - Document Number, OldSystemIdentifier, Document Title, Doc Author, Doc Owner,
     Applicable To, Department, Sub Team 1, Sub Team 2, Top Level Process,
     Sub Process 1, Sub Process 2, Sub Process 3, Document Status,
     Publishing Date, Expiry Date, Document Type, Document Language, Confidentiality

3. スクリプトを実行する。

   ```
   python shareflex_dashboard_20260713_01.py <export.xlsx>
   ```

   出力先を指定しない場合、入力ファイルと同じ場所に `<入力ファイル名>_dashboard.html` が生成される。

   ```
   python shareflex_dashboard_20260713_01.py export.xlsx -o dashboard.html
   ```

   もしくは `run_shareflex_dashboard.bat` にエクスポートしたExcelファイルをドラッグ&ドロップ
   する（Windows）。このバッチファイルは、同じフォルダ内で最もファイル名(日付)が新しい
   `shareflex_dashboard_*.py` を自動検出して実行するので、スクリプトが更新されて
   ファイル名(日付)が変わっても `run_shareflex_dashboard.bat` 自体は変更不要。

4. 生成された `dashboard.html` をブラウザで開く。外部リソースを一切読み込まないため、
   社内ネットワーク外・オフラインでも表示できる。

## ダッシュボードの内容

- 総ドキュメント数、Department数、Top Level Process数、Document Type数のサマリーカード
- 組織軸(Department > Sub Team 1 > Sub Team 2)とプロセス軸(Top Level Process > Sub Process
  1〜3)を切り替えられる階層別ドキュメント件数ツリー
- Document Type別・Document Status別・Confidentiality別の件数内訳

## 既知の制限（今回のスコープ外）

- 現時点ではメタデータ(件数・階層)の集計のみ。各ドキュメントの要約内容や、ドキュメント間の
  参照・ネスト構造の可視化は次フェーズで検討する（ドキュメント本文へのアクセス方法の検討が必要）。
- ヘッダー行は「Document Number」列を含む行を自動検出する。エクスポート時に列名や列順が
  大きく変わると読み込みに失敗する可能性がある。
