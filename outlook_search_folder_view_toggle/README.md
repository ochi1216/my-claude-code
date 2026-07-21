# Outlook 検索フォルダー 表示モード一括制御ツール

設計の経緯は `DESIGN.md`（v1レビュー）と `PLAN.md`（v2プラン）を参照。
このフォルダーには、そのプランに基づく実装（VBAコード一式）を置く。

## 収録ファイル

| ファイル | 種類 | 役割 |
|---|---|---|
| `vba/modSearchFolderRegistry.bas` | 標準モジュール | 登録台帳の保存・照合 |
| `vba/modSearchViewController.bas` | 標準モジュール | 未読／すべて切替、フィルター適用、復元、診断 |
| `vba/clsExplorerWatcher.cls` | クラスモジュール | Outlook画面（Explorer）ごとのフォルダー切替検知 |
| `vba/ThisOutlookSession.txt` | 貼り付け用 | 起動時の初期化・新規ウィンドウの検知 |

## 導入手順

1. Outlookで `Alt+F11` を押してVBAエディタを開く。
2. `modSearchFolderRegistry.bas` と `modSearchViewController.bas` を、
   それぞれ「ファイル」→「ファイルのインポート」でプロジェクトに追加する。
3. `clsExplorerWatcher.cls` も同様にインポートする。
4. 左側のプロジェクトツリーにある既存の `ThisOutlookSession` をダブルクリックで開き、
   `ThisOutlookSession.txt` の中身をそのまま貼り付ける。
5. VBAエディタのメニューで「ツール」→「参照設定」を開き、
   `Microsoft Scripting Runtime` にチェックが入っているか確認する
   （`Scripting.Dictionary` を使うため。入っていなければチェックを入れる）。
6. 一度保存し、Outlookを再起動する。
   - 再起動せずにそのまま試したい場合は、`ThisOutlookSession` 内の
     `SFVT_ManualInitialize` を一度手動実行すれば、再起動しなくても
     見張り役が設置される。
7. マクロの実行には署名が必要な場合、社内ポリシーに従って
   このVBAプロジェクトに署名した上で、Outlookのマクロセキュリティ設定を
   「デジタル署名されたマクロを除き、警告を表示」にする。

## フェーズ0の実地確認（本格運用の前に必ず一度行う）

PLAN.mdの検証計画どおり、まず1フォルダーだけで試す。

1. 対象の検索フォルダー（例：`NTAN`）を開いた状態で、
   `modSearchViewController.DiagnoseCurrentFolderView` を実行する。
   共有範囲が「この種類の全フォルダー共通」と出ても、このツールは
   複製した専用ビューだけを操作するため実害はない（次項参照）。
   あくまで現状把握用。
2. `登録：現在の検索フォルダー`（`RegisterCurrentFolder`）を実行する。
3. `未読モード：管理対象すべて`（`SetUnreadModeAll`）→
   `すべてモード：管理対象すべて`（`SetAllModeAll`）を試し、
   件数・表示が正しく切り替わることを確認する。
4. 受信トレイなど**未登録の他フォルダー**を開き、表示が変わっていない
   ことを確認する（他フォルダーへの波及がないことの確認）。
5. 問題なければ `Flags` など他の検索フォルダーにも展開する。

## 実装上の要点（v2プランからの変更点）

PLAN.mdのフェーズ0は「元のビューのスコープを診断し、必要なら変換する」
という書き方だったが、実装では**元のビューには一切触れず、複製した
専用ビュー（`SFVT_Managed`という名前で各フォルダー内に作成）だけを
操作する**方式にした。元のビューの共有スコープが何であっても、
複製先の専用ビューは常に「このフォルダー・自分のみ」で作成するため、
診断結果に関わらず他フォルダーへの影響が原理的に発生しない。
診断マクロ（`DiagnoseCurrentFolderView`）は事前の状況把握用として残した。

## 用意されているマクロ（QATへは初回のみ手動でピン留めする）

| マクロ | 場所 |
|---|---|
| 登録：現在の検索フォルダー | `modSearchViewController.RegisterCurrentFolder` |
| 解除：現在の検索フォルダー | `modSearchViewController.UnregisterCurrentFolder` |
| 未読モード：管理対象すべて | `modSearchViewController.SetUnreadModeAll` |
| すべてモード：管理対象すべて | `modSearchViewController.SetAllModeAll` |
| 状態確認：管理対象一覧 | `modSearchViewController.ShowStatus` |
| 緊急復元：元ビューへ戻して制御停止 | `modSearchViewController.EmergencyRestoreAll` |
| （診断用）現在のフォルダーのビュー情報 | `modSearchViewController.DiagnoseCurrentFolderView` |

QATへの登録手順：Outlookの「その他のコマンド」→「コマンドの選択」で
「マクロ」を選び、上記の各マクロを1回ずつクイックアクセスツールバーへ
追加する。この作業はOutlookの仕様上、VBAから自動化できない。

## 既知の制限（意図的に対応していない事項）

- 複数のOutlookウィンドウを開いたり閉じたりを繰り返すと、閉じたウィンドウ
  の見張り役オブジェクトがメモリ上に残り続ける（軽微なリーク）。
  個人利用の範囲では実害は小さいと判断し、今回は対応していない。
- 複数のメールボックス（共有メールボックスやPST）をまたいだ検索フォルダーの
  検出は未実装。`modSearchViewController.IsSearchFolder` は
  `fld.Store.GetSearchFolders`（そのフォルダーが属するストアのみ）を見る。
  複数ストアを横断して検索フォルダー台帳を作る必要が出てきたら、
  `Session.Stores` をループする形に拡張する。

## 未検証であることの明示

この環境にはOutlookが無いため、実際にOutlook上で動かした確認は
できていない。構文・API名は公式リファレンス（Store.GetSearchFolders、
View.Filter、View.SaveOption、Explorer.FolderSwitch、
Explorer.CurrentView等）に基づき注意深く書いたが、実機での動作確認は
「フェーズ0の実地確認」の手順で越智さんに行っていただく必要がある。
