# 実測ガイド — 推測で作らないために、1回だけ測る

このツールのフロー生成は、コネクタの `operationId`・パラメータ名・戻り値の形が
`deploy_config.json` の `measured` に**実測値で**入るまで、生成を止める。
推測値で作ると、インポートは通ってしまい、実行時に初めて失敗するため
(安否確認ツールで実際に起きた。`power_automate_safety_checkin/solution/README.md` 参照)。

このガイドは、実測を **最小のGUI操作** で終えるための手順書である。

## Power Automate の GUI に触る回数(全部で)

| # | 操作 | 場所 | 回数 |
| --- | --- | --- | --- |
| 1 | 使い捨てフローを1本作る(アクションを順に置くだけ。実行は、メールの試験受信の1回) | Power Automate | **1回** |
| 2 | 接続のサインイン(Outlook / SharePoint / Excel Online。Teams は既存) | Power Automate | 接続の数だけ(1クリックずつ) |
| 3 | インポート後に「オンにする」を押す(接続の紐付けが自動で済まない場合は、アクションごとの選び直しも) | Power Automate | 1回 |

それ以外(SharePointのライブラリ作成・Office Scriptの登録・設定ファイルの編集・生成・
検証・取り込み・以降の修正と再展開)は、SharePoint / Excel の画面かコマンドで行う。

> 前回(安否確認ツール)は、フロー本体を GUI で組むと 30 ステップを超え、保存前に
> 画面を再読み込みすると作りかけが消えた。今回は **アクションを置くだけ**(式を書くのは
> Compose の1か所だけ)で、保存さえできればよい。条件・式・カードは、すべて生成側が持つ。

## 実測する項目

| ID | 内容 | 方法 | 反映先(deploy_config.json) |
| --- | --- | --- | --- |
| E1 | 各アクションの operationId・パラメータ名・認証の書き方 | 使い捨てフローをエクスポート → 要約 | `measured.*.operationId` / `params` / `authentication` |
| E2 | Office Script の指定のしかた(`scriptReference`・`source`・`drive`) | 同上(Run script アクションの値) | `measured.runScript.*` |
| E3 | トリガーの戻り値のキー・メール本文のリンクの形式 | 使い捨てフローを1回実行(メールを試験受信。Compose の出力を見る) | `measured.expressions.trigger*` / `requestList.linkMarker` |
| E4 | 手作業で入る印影の位置とサイズ | 手作業で押印済みの証明書に `inspect_shapes` を実行 | `script.targetWidthPt` など |
| E5 | 接続参照を取り込み時に指定できるか | `pac solution import --settings-file` を試す | (運用手順) |
| E6 | Run script の戻り値の取り方 | 最初の dryRun の実行履歴で確認(候補の式が違えば、`CMP_Script_Result` が失敗して通知される) | `measured.expressions.scriptResult` |

## 手順

### 0. 前提

- `pac` CLI がインストール済みで、DEV環境へ `pac auth create` 済み(安否確認ツールで実施済み)
- 作業は PowerShell 7(`pwsh`)で行う。パスは各自の環境に読み替える
- **実測で得たエクスポートの生ファイルは、チャットへ貼らず、コミットもしない。**
  GUID・サイトURL・メールアドレスが入っている。共有するのは、手順4の「要約」の出力だけ

### 1. SharePoint の準備(SharePoint の画面。Power Automate ではない)

1. 対象サイト(`JapanDesign`)に、ドキュメントライブラリを2つ作る
   - `ECS_Work` — 押印の作業コピーと、元ファイルの退避(`_orig`)を置く
   - `ECS_Stamp` — 印影の画像を置く
2. `ECS_Stamp` に、印影の画像(`Ochi_stamp_印鑑_70.png`)をアップロードする。
   **このライブラリのアクセス権は、越智さんだけにする**(「アクセス許可の管理」→ 継承を解除 →
   他のメンバーを外す)。印影はそのまま使える押印の素材であり、閲覧者を増やさない
3. 次を控えて、`deploy_config.json` へ書く
   - 印影のサーバー相対パス → `stampImagePath`(例: `/sites/JapanDesign/ECS_Stamp/Ochi_stamp_印鑑_70.png`)
   - 作業ライブラリのフォルダパス → `libraries.workFolderPath`(例: `/sites/JapanDesign/ECS_Work`)
   - 通知先 → `notifyRecipient`、サイトURL → `sharePointSiteUrl`
4. リクエストのリスト(`Parameter_sheet_request`)のGUIDを取る。ログイン済みのブラウザで開く:

   ```
   https://<tenant>.sharepoint.com/sites/JapanDesign/_api/web/lists/getbytitle('Parameter_sheet_request')?$select=Id,Title
   ```

   表示された `Id` を `requestList.listId` へ。**全ゼロや、中かっこの有無の食い違いに注意**
   (安否確認ツールで実際に起きた)
5. 記録用のリストは、既存の `EQ_Received_Items`(列は実測済み・1行テキスト)を流用できる。
   同じサイトにあるなら、そのGUIDを `logList.listId` へ。別のサイトなら、そのサイトに
   専用リストを作る(Title・状態・コード・詳細の4列、すべて **1行テキスト**。
   Excelアップロードで作ると列が数値型になるため、見本データを入れること)

### 2. Excel Online に Office Script を登録する(Excel の画面)

1. `ECS_Work` に、テスト用の証明書(過去の証明書のコピー)を置き、Excel Online で開く
2. 「自動化」タブ → 「新しいスクリプト」 → 既存の内容を消し、
   `office_scripts/stamp_approver_20261006_01.ts` の全文を貼り付ける → 名前を
   `ECS_StampApprover` にして保存
3. 同様に `inspect_shapes_20261006_01.ts` を `ECS_InspectShapes` として保存する

> 貼り付けたあとで構文エラーが出た場合は、そのメッセージを共有してほしい
> (ExcelScript の実APIが、ローカルの模擬テストと違う場合に起きる。E4 の確認の一部)。

### 3. 使い捨てフローを作る(Power Automate。**ここだけ GUI**)

1. ソリューションを作る: Power Automate → ソリューション → 新しいソリューション →
   名前 `ECS_Measure`、パブリッシャー `NexperiaJP`
2. その中に「自動化したクラウドフロー」を新規作成する(名前 `ECS_Measure_Flow`)。
   **式を書くのは、Compose の1か所だけ。** 他は適当な固定値でよい(実際に動かすのは、下の4の1回だけ)
3. 下の表の順に、トリガーとアクションを**この順番どおり**に置く。保存して終わり。
   **値はすべて、固定の適当な値でよい**(前のアクションの出力を選ぶ必要はない)。
   エクスポートで見たいのは、アクションの種類・`operationId`・パラメータ名であって、
   値ではないため。Compose だけは、トリガーの出力を見るため**先頭**に置く

| 順 | コネクタ | 置くもの | 入れる値(固定の適当な値で可) |
| --- | --- | --- | --- |
| トリガー | Office 365 Outlook | 新しいメールが届いたとき(V3) | フォルダ: 受信トレイ / 件名フィルター: `[Approval request] 該非判定`。**「差出人」は入れない**(試験受信を自分の転送でできるように) |
| 1 | 組み込み | 作成(Compose) | 式: `triggerOutputs()`(**これだけは式を書く**。実行履歴でトリガーの出力を見るため) |
| 2 | SharePoint | 添付ファイルを取得する(Get attachments) | サイト・リスト(`Parameter_sheet_request`)・ID: `40` |
| 3 | SharePoint | 添付ファイルのコンテンツを取得する(Get attachment content) | 同上・添付ファイルID: `1` |
| 4 | SharePoint | ファイルの作成(Create file) | サイト・フォルダ(`ECS_Work`)・名前: `test.xlsx`・内容: `x` |
| 5 | SharePoint | パスを使用してファイルコンテンツを取得する | 印影のパス |
| 6 | Excel Online (Business) | スクリプトの実行(Run script) | 場所: 対象サイト / ライブラリ: `ECS_Work` / ファイル: 手順2で置いたテスト用の証明書 / スクリプト: `ECS_StampApprover` / 引数: 適当 |
| 7 | SharePoint | ファイル コンテンツの取得(Get file content) | ファイル: `ECS_Work` のテスト用の証明書 |
| 8 | SharePoint | 添付ファイルの削除(Delete attachment) | **ID: `999999`(存在しないもの)**・添付ファイルID: `1` |
| 9 | SharePoint | 添付ファイルの追加(Add attachment) | **ID: `999999`(存在しないもの)**・名前: `test.xlsx`・内容: `x` |

   > 8・9は、このフローを実行しても実在の添付を消さないよう、**存在しない項目ID**にしておく。
   > 実行すると、Compose(1)のあとは、値が適当なため途中で失敗して止まる。それでよい。
   > 実行履歴で見たいのは、Compose(1)の出力だけである。

4. トリガーの試験受信(E3): このフローを**オンにして**、承認依頼メール
   (件名が `[Approval request] 該非判定` で始まるもの)を**自分宛に転送**する。
   転送で件名が `FW: ...` になっても、件名フィルターは「含む」で効くため拾える。
   実行履歴で `作成(Compose)` の出力を開き、**そのまま**コピーして保管する
   (本文のHTMLが入るため、チャットへ貼る前に、品名・メールアドレス・URLの部分を伏せる)。
   確認すること:
   - 件名・差出人・本文の取り出し方(`body/subject` など)
   - 本文の中のリンクの形(`DispForm.aspx?ID=` の前後。`&amp;` や URL エンコードの有無)
5. 確認が済んだら、このフローを**オフ**にする(転送のたびに動くため)

### 4. エクスポートして、要約する(PowerShell)

```powershell
pac solution export --name ECS_Measure --path .\ECS_Measure.zip
pac solution unpack --zipfile .\ECS_Measure.zip --folder .\measure_src
python .\flows\summarize_export_20261006_01.py .\measure_src
```

出力は、順番に並んだアクションの `operationId` と、パラメータ名・接続参照の論理名・
認証の書き方である。GUID・メールアドレス・URLのホスト名は伏せてある。
**この出力を共有してもらえれば、`deploy_config.json` の `measured` は私が埋める。**
自分で埋める場合の対応は、次のとおり。

| 要約に出るもの | 入れる先 |
| --- | --- |
| トリガーの `operationId` / `type` / パラメータ名(フォルダ・差出人・件名) | `measured.mailTrigger.*` |
| 各アクションの `operationId` | `measured.<名前>.operationId` |
| 各アクションのパラメータ名(順番に、サイト・リスト・ID…) | `measured.<名前>.params.*`(論理名 → 実際の名前) |
| `authentication` の書き方 | `measured.authentication` |
| 接続参照の論理名(`njp_...`) | `connectionReferences.*` |
| Run script の「場所」「ライブラリ」「スクリプト」に入った値 | `measured.runScript.source` / `drive` / `scriptReference` |

### 5. 手作業の印影の位置とサイズを測る(E4。Excel の画面)

1. 手作業で押印済みの過去の証明書(承認済みのもの)を Excel Online で開く
2. 「自動化」タブ → `ECS_InspectShapes` を実行(引数なし。ブックは変更されない)
3. 「出力」に出た JSON を控える。見るのは次の項目
   - `anchorLeft` / `anchorTop`(H15の左上)
   - 越智さんの印影の `left` / `top` / `width` / `height`
4. 比較する: 印影の `left` / `top` が、アンカーの `anchorLeft` / `anchorTop` と一致すれば、
   「H15の左上に自然サイズで配置」で再現できている。**サイズが合わない**(自然サイズより
   小さく貼っている、など)場合は、その `width`(または `height`)を
   `script.targetWidthPt` へ入れる

### 6. 設定 → 生成 → 検証 → 取り込み

```powershell
cd export_control_stamper
copy deploy_config.example.json deploy_config.json   # 実値を入れる(コミットされない)
cd flows
python .\verify_flows_20261006_01.py                 # 生成ロジックの自己検証(設定不要)
python .\build_flows_20261006_01.py --config ..\deploy_config.json --out .\src
pac solution pack --zipfile .\ExportControlStamper.zip --folder .\src
pac solution import --path .\ExportControlStamper.zip
```

未実測の値が残っていると、`build_flows` は**一覧を出して止まる**(何も出力しない)。

### 7. 接続の紐付け(E5)

インポート後、フローが自動でオンにならない場合がある。接続参照の紐付けが済んでいない
ためで、安否確認ツールの EQ05 では、アクションごとに「接続参照を変更する」で選び直す
作業が発生した(`power_automate_safety_checkin/docs/GATE_STATUS.md` 参照)。
これを避けるため、まず取り込み時の指定を試す(**未実測**。動かない場合は、GUIで選び直す):

```powershell
pac connection list                                        # 接続のIDを控える
pac solution create-settings --solution-zip .\ExportControlStamper.zip --settings-file .\settings.json
# settings.json の ConnectionReferences に、ConnectionId を書く(コミットしない)
pac solution import --path .\ExportControlStamper.zip --settings-file .\settings.json
```

### 8. dryRun の動作確認

`dryRun=true` の間は、添付を差し替えず、作業ライブラリのコピーにだけ押印する。

1. フローをオンにし、**次に本物の承認依頼メールが届くのを待つ**(または、転送で試す場合は、
   試験用に `mail.senderAddress` を自分のアドレス、`mail.subjectPrefix` を
   `FW: [Approval request] 該非判定` にした設定で、別に生成して取り込む。
   **試験が終わったら、必ず元の設定で生成し直して取り込み直す**)
2. Teams に届いた通知の「押印後のファイルを開く」で、印影の位置と大きさを**目で確認する**
3. 想定どおりなら、同様に数件確認する
4. 輸出管理規程上の確認(下記)が済んだら、`dryRun=false` にして生成し直す

## 本番(dryRun=false)へ切り替える前の確認

- [ ] 輸出管理規程上、印影の自動貼付が許容されることを確認した(**未確認**。確認先は越智さん)
- [ ] dryRun で、印影の位置・サイズが手作業と一致することを、数件で目視確認した
- [ ] 失敗させたときに、Teams へ通知が来て、実行履歴が失敗になることを確認した
- [ ] 「押印済みのファイルへ差し替えた」あと、元のファイルが `ECS_Work` の `_orig` に残っている
- [ ] 本番モードで生成したときのコンソール表示が `[本番モード]` になっていることを目視した
- [ ] 最終承認は、これまでどおり越智さんがメールの「承認」を押す(自動では押さない)
