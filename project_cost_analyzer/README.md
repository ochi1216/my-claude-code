# Project Cost Analyzer

Project Cost管理Excel（`BG ICS Project cost summary_*.xlsm`）内の **KOB1シート**
（SAPのプロジェクトコスト実績明細）を読み込み、プロジェクト単位でコスト分析を行う
Streamlitダッシュボード。

社内の機密性の高いコストデータを扱うため、**ローカル環境で完結する構成**にしている
（外部サービスへのアップロードは行わない）。

## 必要要件

- Python 3.9以上

## セットアップ手順

1. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

2. ダッシュボードを起動する。

   ```
   streamlit run project_cost_analyzer_20260722_01.py
   ```

   Windowsで `run_dashboard.bat` をダブルクリックして起動することもできる。このフォルダ内の
   `project_cost_analyzer_*.py` のうち、ファイル名が最も新しいもの（バージョンアップ時に
   追加された最新リビジョン）を自動判別して起動するため、バージョンアップ後もバッチファイル
   自体を書き換える必要はない。

3. サイドバーから以下のいずれかでデータを読み込む。

   - 「KOB1を含むExcelファイル」欄からファイルをアップロードする
   - 「ローカルパスを指定」欄に、KOB1シートを含む `.xlsm`/`.xlsx` ファイルのパスを入力する
     （デフォルト値は `C:\Users\nx023836\Documents\PythonScripts\PM_organizer\ProjectCost\BG ICS Project cost summary_20260722.xlsm`）

## KOB1シートの前提列

読み込み元のExcelには、以下の列を含む `KOB1` という名前のシートが必要（列順は問わない）。

`Cost Element`, `Cost element name`, `SPARC ID`, `Total Quantity`, `Purchasing Document`,
`Purchase order text`, `Document Header Text`, `Order`, `Partner-CCtr`, `Company Code`,
`Period`, `Fiscal Year`, `Val/COArea Crcy`, `Name`, `Project status`, `Order Type`,
`Profit Center`, `PM`, `S4 FSItem`, `FSI Description`, `B4P category`, `PM cost category`,
`Organization`, `Man month`, `Func.Category`, `Function`, `Project Name`, `Resource name`,
`Cost Category`, `IND`

コスト金額は `Val/COArea Crcy`（コントローリングエリア通貨換算後の値）を使用しており、
Company Code横断で単純合算できる前提。

## ダッシュボードの内容

- サイドバーで Project Name / Fiscal Year / Project status / Cost Category による絞り込み
- 対象コスト合計・明細行数・対象プロジェクト数・対象期間のサマリーカード
- プロジェクト別コスト内訳（コスト・行数・PM一覧）
- 期間（会計年度-期）別のコスト推移
- Cost Category別・PM cost category別・Cost Element別（上位15）・Function別の内訳
- フィルタ後の明細テーブル表示、および分析結果（明細・プロジェクト別・期間別）のExcelダウンロード

## 既知の制限（今回のスコープ外）

- 予算(Budget/Committed)との対比分析（`Project cost against BC`シート相当）は未実装。
  必要になった場合、KOB1実績とBCシートを突き合わせる機能として追加を検討する。
- 通貨は `Val/COArea Crcy` の単一通貨換算値をそのまま利用しており、通貨換算ロジック自体は
  持たない（元のExcel側の換算に依存）。
- データはユーザーがローカルに配置したファイルを都度読み込む方式で、永続的な保存・
  蓄積は行わない（複数バージョンの推移比較などは対象外）。
