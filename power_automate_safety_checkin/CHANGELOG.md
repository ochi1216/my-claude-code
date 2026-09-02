# CHANGELOG — power_automate_safety_checkin

このフォルダ内の変更履歴。

## [20260901_04] - 2026-09-02

**変更ファイル:** `solution/update_deploy_config_20260901_01.py`, `solution/README.md`,
`docs/GATE_STATUS.md`

- **SharePoint「項目の更新」アクションの`operationId`・パラメータ名を実測した。**
  `operationId`は`PatchItem`、項目IDを渡すパラメータ名は`id`(`PostItem`・`GetItems`
  と同じ構造で、`id`パラメータが1つ増えるだけ)。GUIで確認用フローを1本作り、
  エクスポートしたJSONから読み取った。
  - この値はコネクタの固定値であり、`PostItem`/`GetItems`と同様にテナント間で
    変わらず社内情報を含まないため、`update_deploy_config_20260901_01.py`の
    デフォルト値として埋め込んだ。以後、このスクリプトを実行するだけで
    `sharePointUpdateAction`に実測済みの値が自動で入る。
  - 既に`<未実測>`のまま`deploy_config.json`へ`sharePointUpdateAction`が
    入っている場合も、次に実行したときに実測済みの値へ自動で埋まる
    (ユーザーが独自に上書きした値がある場合はそちらを優先し、上書きしない)。
- これで`features.eventClose`(イベントのクローズ処理)を有効化する前提条件が揃った。
  残る前提条件は`EQ_Received_Items`の列の型修正(数値型→1行テキスト)のみ。
- 検証は118項目すべて合格を維持。

## [20260901_03] - 2026-09-01

**追加ファイル:** `solution/update_deploy_config_20260901_01.py`

**変更ファイル:** `solution/build_flows_20260901_02.py`,
`solution/verify_flows_20260901_01.py`, `solution/deploy_config.example.json`,
`solution/README.md`, `docs/GATE_STATUS.md`,
`evidence/sharepoint_internal_names.json`

- **`EQ_Received_Items`の列内部名を実測した(Gate D完了)。** その結果、
  **実際のリストがリポジトリの`EQ_Received_Items.xlsx`と列構成が違う**ことが判明した。
  - エラー内容の列は`ErrorMessage`ではなく**`ErrorDetail`**(`field_6`)。
    フロー側をこの名前に合わせた。
  - **`CreatedAt`列は存在しない。** SharePointの標準列`Created`(作成日時)が
    自動で入るため発生時刻は失われない。`CreatedAt`は、設定にあれば書き、
    無ければ書かない任意扱いにした。
  - `SourceUpdatedAt`/`SourceLink`/`InformationType`という、P2の自動地震検知で
    JMAフィードの受信を記録するためと思われる列がある。
    **このリストがどの版のExcelから作られたかは未確認。**
- **`ProcessingStatus`/`ErrorCode`/`ErrorDetail`が数値型で作られていた。**
  `EQ_Events`で起きたのと同じ、見本データ無しのExcelによる型の誤検出。
  1行テキストへ直すまでエラー記録の書き込みは失敗する(SharePoint側での手作業が必要)。
- **`deploy_config.json`への設定追加を自動化するスクリプトを追加した。**
  このファイルはGit管理外のため新しい設定項目が自動では入らず、手で足すと
  カンマの付け忘れで壊しやすい。すでにある値は書き換えず、書き換え前に控えを作り、
  書き出したあとJSONとして読み直して壊れていないことを確認する。
  リストGUIDは社内情報のためスクリプトには書かず、引数か対話で受け取る。
- **エラー処理・クローズ処理を含むSolutionのインポートが成功した(2026-09-01)。**
  未確認だった前提のうち、「`Scope`の中に`Terminate`を置けるか」「`SCOPE_Catch`の
  構造と`result('SCOPE_Try')`の式が検証を通るか」の2点が実証された。
  実行時の動作は引き続き未検証。
- **全ゼロのGUIDを、生成側・設定側の両方で弾くようにした。**
  `listIds.EQ_Received_Items`に`00000000-...`が入ったまま生成・インポートまで通り、
  フローを開いた時点で`List not found`になってフローがオフのまま戻せなくなった
  (実機で発生)。全ゼロは書式としては正しいGUIDに見えるため、書式の比較でも
  「設定済み」判定でも異常だと分からなかった。生成側の`is_measured()`が全ゼロを
  未実測として弾き、`--diagnose`が明示的に警告し、すでに入っている全ゼロは
  「未設定」と同じ扱いにして実値で上書きできるようにした。あわせて、複数のリストに
  同じGUIDが入っていないかも点検する。検証は117項目→118項目。
- **設定の書式を点検する`--diagnose`と、揃える`--normalize-list-ids`を追加した。**
  SharePointコネクタの`table`に入れるリストGUIDは環境によって中かっこ付きで
  保持されており、既存の3リストが中かっこ付きなのにあとから足した1つだけ無い、
  という食い違いが起きうる。この食い違いは**インポートは通り、フローを開いたときに
  初めて`GetTable`が`NotFound`になる**ため見つけにくい。`--diagnose`はリストGUID
  そのものを表示せず、書式だけを比べる。
- **エラー処理の動作確認用に、わざと失敗する設定の写しを作れるようにした。**
  `--write-error-test-copy`(元のファイルには触らない)。`features.errorLogging`が
  有効でなければ実行を断る。
- **失敗のさせ方を、リストGUIDから`$filter`の列内部名へ変更した。**
  当初は`EQ_Events`のリストGUIDを存在しない値にしていたが、実機では**実行時ではなく
  デザイナーの保存・検証の時点で`GetTable`が`NotFound`となって弾かれ、フローが
  オフになった**。リストGUIDは保存時に解決されるため`SCOPE_Catch`まで到達しない。
  `$filter`はSharePointがサーバ側で評価する文字列で保存時には検証されないため、
  メンバー抽出のフィルターに使う列の内部名を存在しない名前へ差し替える方式にした。
  この壊し方では`GET_Active_Members`で失敗するため、**個人宛のカードは1通も
  送られない**(送信処理はその後ろにある)。ただし`EQ_Events`に1行でき、拠点の
  チャネルへ開始通知が1件投稿される。
- `.gitignore`を`deploy_config*.json`(exampleのみ例外)と`*.bak_*`に広げた。
  設定の写しや自動生成の控えにも実値が入るため。
- 検証スクリプトに、実測した列構成での確認を追加した(`ErrorDetail`へ書くこと、
  存在しない列へ書きにいかないこと、`CreatedAt`を設定した場合は書くこと、
  `ErrorDetail`だけ未実測でも生成が止まること)。107項目→117項目。

## [20260901_02] - 2026-09-01

**追加ファイル:** `solution/build_flows_20260901_02.py`,
`solution/verify_flows_20260901_01.py`

**変更ファイル:** `solution/deploy_config.example.json`, `solution/README.md`,
`docs/FLOW_LOGIC_SPEC.md`, `docs/GATE_STATUS.md`,
`evidence/sharepoint_internal_names.json`

- **エラー処理(`SCOPE_Try`/`SCOPE_Catch`)を実装した。** EQ06・EQ05の本体を
  `SCOPE_Try`で包み、失敗したら`SCOPE_Catch`で`EQ_Received_Items`へ1行
  (`ProcessingStatus=Error`、エラーコード、エラー内容、発生時刻)記録する。
  EQ05にも入れたのは、15分ごとに自動で動くフローの失敗は実行履歴を見に行かない限り
  誰も気づけないため。
  - 変数の初期化(`InitializeVariable`)はフローの最上位にしか置けないため、
    初期化はスコープの外に残し、それ以降だけを包んでいる。
  - `SCOPE_Catch`の末尾に`Terminate`(Failed)を置いた。これが無いと
    「Catchが成功した」ことで**実行全体が成功扱いになり、本物の失敗が
    実行履歴で緑色になってしまう**。
  - `runAfter`に`Skipped`は含めていない。`SCOPE_Try`の手前は変数の初期化しかなく、
    スキップされる経路が存在しないため。
  - エラー内容は1行テキスト列の上限に合わせて255文字で切り詰める。
  - `Terminate`で終わる経路(拠点コード誤り・震度コード誤り・対象者ゼロ)は
    Catchを通らないため記録に残らない。記録されるのはコネクタの失敗である。
- **イベントのクローズ処理を実装した。** 全員分の回答待ちが終わったら
  `EQ_Events`の`AlertStatus`を`Closed`に、失敗して`SCOPE_Catch`に入った場合は
  `Error`にする。閉じないと`EQ05`が、終わった訓練の集計カードを15分ごとに
  チャネルへ投稿し続ける。`Closed`と`Error`を分けたのは、あとから
  「失敗して終わった回」を見分けられるようにするため。
  - 更新対象はタイトルではなくSharePointの項目ID(整数)で指す。
    `SP_Create_Event`の応答から`varEventItemId`へ控えて使う。
- **どちらの機能も`deploy_config.json`の`features`で個別に有効化する方式にした。**
  実測値が揃っていない状態で既存の動作を止めないため。未指定・両方falseなら、
  生成物は`20260901_01`と1バイトも変わらない(検証スクリプトで毎回確認している)。
- **未実測の値を推測で埋めない作りにした。** `EQ_Received_Items`の列内部名と、
  SharePoint「項目の更新」アクションの`operationId`・パラメータ名は未実測のため、
  設定ファイルから読む。`<未実測>`のまま機能を有効にすると**生成の時点で止まる**。
  推測値を埋め込むと、インポートは通ってしまい訓練当日の実行で初めて失敗するため。
- **生成物の構造検証スクリプト`verify_flows_20260901_01.py`を追加した。**
  開発環境(Linuxコンテナ)からはテナントへインポートできないため、
  インポートで弾かれる類の間違いをフロー定義(JSON)の段階で潰す。
  機能フラグ4通りすべてで107項目を確認する。
  - 機能オフの生成物が`20260901_01`と一致するか(回帰確認)
  - `runAfter`が同一スコープ内の実在アクションを指しているか
  - アクション名がフロー全体で一意か
  - `Terminate`がループの中に入っていないか、`InitializeVariable`が最上位のみか
  - 参照・代入する変数がすべて初期化済みか、並列ループ内で`SetVariable`を
    使っていないか
  - 未実測のまま機能を有効にすると生成が止まるか
- `verify_flows_20260901_01.py`が外部の`diff`コマンドを呼んでいたため、Windowsでは
  起動直後に`FileNotFoundError`で落ちていた(実機で判明)。ディレクトリの比較を
  Python内で行うようにして、外部コマンドへの依存を無くした。
- 生成時に、いま誰へ届く設定になっているか(`[検証モード]`か`[本番宛先モード]`か)を
  必ずコンソールへ表示するようにした。本番宛先へ切り替わったことに気づかないまま
  実行するのが一番危ないため。
- `solution/README.md`に本番切替チェックリストと、SharePoint「項目の更新」
  アクション・列内部名の実測手順を追加した。
- **エラー処理・クローズ処理はいずれも実機未検証。** 構造検証のみ実施済み。
  実機で確認すべき前提(スコープ内に`Terminate`を置けるか、`result()`の戻り値の形、
  項目IDのキー名、`EQ_Received_Items`の列の型)は`docs/GATE_STATUS.md`に一覧化した。

## [20260901_01] - 2026-09-01

**追加ファイル:** `solution/build_flows_20260901_01.py`,
`solution/deploy_config.example.json`, `evidence/sharepoint_internal_names.json`

**変更ファイル:** `solution/README.md`, `docs/FLOW_LOGIC_SPEC.md`,
`docs/GATE_STATUS.md`, `cards/checkin_card.json`, `.gitignore`

- **フロー構築方式を、GUIでの手組みからJSON生成+CLIインポートへ変更した。**
  GUIでの構築はEQ06だけで30ステップを超える上、「保存」前に画面を再読み込みすると
  作りかけが全て消える(実際に一度失った)。クラウドフローの実体はJSONであり
  Solutionとしてインポートできるため、生成をスクリプト化した。
  結果、EQ06のフロー本体はGUIのクリック操作ゼロで構築できるようになった。
- Solutionへフローを格納する形式は公開情報だけでは特定できなかったため、
  実テナントに最小フローを作ってエクスポート・unpackし、実測で確定させた
  (`.json.data.xml`という対のメタデータファイルが必要、`JsonFileName`は先頭スラッシュ必須、
  `Customizations.xml`の`<Workflows />`は空のまま、など)。
- **Gate B 合格**: Teamsの「チャットやチャネルにカードを投稿する」
  (`PostCardToConversation`、応答を待たない)が標準コネクタに存在し、非推奨でないことを実測。
  投げ切り型の非同期設計をそのまま採用できる。1:1チャットへの投稿
  (`location: "Chat with Flow bot"`)も実機で成功を確認。
- **Gate D 実測完了**: Excelアップロードで作ったリストは、内部名が表示名と一致せず
  `field_1`,`field_2`...という連番になることが判明(`Title`のみ標準列)。
  あわせて、見本データ無しでアップロードしたため多くの列が数値型で作られていたことも判明し、
  5列の型を修正した。実測値は`evidence/sharepoint_internal_names.json`に記録。
- `docs/FLOW_LOGIC_SPEC.md`の設計上の誤りを修正。Switchアクションには出力が無く
  `outputs('CMP_Site_Config')`のような参照はできないため、変数
  (`varSiteConfig`/`varIntensityValue`)経由で受け渡す設計に変更した。
- **`EQ06_Manual_Drill_DEV`の実機動作確認完了**(単一拠点TOKYO)。
  閾値未満(震度4)は`END_Below_Threshold`で正常終了、閾値以上(震度5弱)は
  EQ_Eventsへのレコード作成・Teamsチャネルへのカード投稿・対象者2名への
  個人カード送信まで、全アクションが成功した。
- **検証中の誤送信防止として、`testRecipientOverride`設定を追加。** 空でない限り、
  個人カードの宛先は名簿の内容にかかわらず常にこのアドレスになる。実機テストで
  実在の同僚2名へ安否確認カードが届いてしまったための再発防止策。
  `IsTest`や拠点選択には依存させていない。防ぎたいのは人為ミス(訓練フラグの
  付け忘れ、拠点の選び間違い)であり、人の操作を条件にするとそのミス自体で
  安全弁が外れるため。本番移行時にこの値を空にすることが唯一の切替操作となる。
- **カード応答の受け取り〜`EQ_Responses`への保存〜被災時の上司通知を実装。**
  応答JSONの構造を実機で実測(`evidence/teams_card_response_sanitized.json`)し、
  `data`配下の回答値と`responder`配下の実際の回答者を取得できることを確認した。
  `EQ_Responses.Email`には、カード内のIDではなく`responder.email`(実際に回答した人)を
  記録する(カードのdataは詐称されうるため)。
  上司通知は、`operationId`が実測済みの`PostCardToConversation`を流用し、
  `cards/manager_alert_card.json`を新規作成した。
- **回答保存・上司通知まで含めたEQ06の一連の動作を実機で確認**(2026-09-01)。
  カードで「被災」を選んだ場合に、`EQ_Responses`へ安否`Affected`・出社可否・
  回答者メール・回答日時が正しく記録され、続けて上司へ「【訓練】被災報告」カードが
  届くところまで通しで成功した。
- 当初設計にあった回答の重複防止(Upsert)は不要と判断し、単純な新規作成にした。
  待機型では1回の実行につき1人1回しか回答を受け取れない(回答するとカードが
  「受け付けました」に置き換わる)ため。
- 並列ループ内では変数を使わない方針を明記。Power Automateの変数はフロー実行全体で
  共有されるため、並列実行中に`変数の設定`を使うと値が混ざる。安否・出社可否の判定は
  式で直接計算している。
- **`EQ05_Status_Summary_DEV`(定期集計)を実装。** `AlertStatus=Open`のイベントごとに
  対象者数・回答数・未回答数・被災者数を集計し、拠点のチャネルへカードで投稿する。
  拠点→通知先の解決は、ループ内でSwitchや変数を使わずに済むよう、先頭の`CMP_Site_Map`で
  作った対応表をキー参照する方式にした。被災者数はWDLに`filter`関数が無いため
  「配列のフィルター」アクション(`type: Query`)で絞ってから数えている。
  実機で集計カードがチャネルへ投稿されることを確認済み。
- **未回答(タイムアウト)でループが失敗しないよう、待機アクションの後続を条件1つに
  まとめた。** 当初は後続を2つに分けて片方を`runAfter=TimedOut`で受けたが、実機では
  タイムアウト時に`ActionFailed. No dependent actions succeeded.`でループ全体が
  失敗した(受け皿は成功していたが、もう一方がスキップのまま残るとスコープが失敗判定に
  なる)。`CHK_Responded`(runAfter=[Succeeded,TimedOut])で受け、その中で
  `actions('TM_Post_CheckIn_Card')?['status']`を見て回答あり/未回答に分岐する。
  `Failed`は受けないため、本物の失敗は引き続きフローの失敗として表に出る。
  この構造で、タイムアウト後にフローが正常終了することを実機で確認した。
- `responseTimeout` / `loopConcurrency` / `summaryIntervalMinutes` を設定で
  変えられるようにした。生成対象のフローは`workflowIds`に載っているものだけになる。
- 検証用の架空拠点`NARA`(検証者1名のみ所属)を導入。実在拠点の名簿に触れずに
  拠点分岐・閾値判定・メンバー抽出まで試せるようにした。実機で`NARA`を指定した
  訓練を実行し、検証者だけに`【訓練】安否確認`カードが届くことを確認済み。
- 個人カード(`cards/checkin_card.json`)の見出しにも`【訓練】`を付けるよう修正。
  チャネル通知にしか訓練表示が無く、個人カードを受け取った人が訓練かどうか
  判断できない状態だった(実機テストで実際に2名へ訓練表示なしのカードが届いた)。

## [20260731_04] - 2026-07-31

- ユーザーがSharePointサイト(MyPrivate)へ4リスト
  (`EQ_Config_Members`, `EQ_Received_Items`, `EQ_Events`, `EQ_Responses`)を
  Excelアップロードで登録完了したことを確認。これによりP1完成条件のうち
  SharePoint側の準備が整い、3フロー(`EQ06_Manual_Drill_DEV`等)のGUI構築へ
  進めるようになった。Gate D(列内部名の実測)は、フィルタークエリで内部名を
  使う箇所(`GET_Active_Members`等)に到達した時点で都度確認する方針とする。

## [20260731_03] - 2026-07-31

**追加ファイル:** `EQ_Config_Members.xlsx`, `EQ_Received_Items.xlsx`,
`EQ_Events.xlsx`, `EQ_Responses.xlsx`(SharePointアップロード用テンプレート)

**変更ファイル:** `docs/FLOW_LOGIC_SPEC.md`

- SharePointの「Excelから新しいリストを作る」機能がテーブル形式でないと
  エラーになることが実機検証で判明したため、4リスト分のExcelテンプレートを
  Excelテーブル(ヘッダー+実例行1件)として作成し、ユーザーへ送付した。
- `EQ_Responses.xlsx`初版に、`FLOW_LOGIC_SPEC.md`の`SP_Get_Existing_Response`
  (Title列でのフィルター)と実際の書き込み列一覧との不整合を発見。
  `Title`列(`ResponseKey`格納用)がExcel側に無く、`FLOW_LOGIC_SPEC.md`の
  「書き込む列」一覧にも明記されていなかった(書き忘れると重複回答防止が
  機能しない)。`Title`列を追加し、`FLOW_LOGIC_SPEC.md`のGate 6箇所も修正。
- `EQ_Responses.xlsx`に、各列の想定型・説明をヘッダーセルのコメントとして付与し、
  実例行(斜体グレー、アップロード後に削除する旨を明記)とREADMEシートを追加。

## [20260731_02] - 2026-07-31

**追加ファイル:** `evidence/README.md`

**変更ファイル:** `docs/GATE_STATUS.md`

- S02(Power AutomateフローのGUI構築とGate B/D検証)を開始。
  Gate B(Teamsカードアクション実測)・Gate D(SharePoint列内部名実測)の
  結果を格納する`evidence/`ディレクトリを新規作成し、置くべきファイルの
  一覧・サニタイズ方法(個人メール・Tenant ID・Team ID・Channel IDを
  マスクする方法)を`evidence/README.md`に明文化した。
- `GATE_STATUS.md`のGate D行を、SharePointリスト作成手段をExcelアップロード
  方式へ切替えた実態(S01末の変更)に合わせて修正。
  `scripts/provision_sharepoint_*.ps1`による自動出力は前提にできないため、
  「リストの設定」画面からの手動確認・`evidence/sharepoint_internal_names.json`
  への記録に変更した。
- ユーザーへ確認した結果、SharePoint 4リストへのExcelアップロードは
  **まだ未着手**と判明。このため本セッションでは、3フロー
  (`EQ06_Manual_Drill_DEV` / `EQ04b_On_Response_DEV` / `EQ05_Status_Summary_DEV`)
  のGUI構築・Gate B/D実測には進めなかった(SharePointの準備が前提のため)。
  ユーザーが`docs/MANUAL_STEPS.md`§2に沿ってアップロードを完了させた後、
  フローGUI構築の式・手順提示とトラブル対応を再開する。

## [20260731_01] - 2026-07-31

**追加ファイル:** `scripts/provision_sharepoint_20260730_03.ps1`(`_01`/`_02`は規約により残置)

**変更ファイル:** `config/members.example.json`, `docs/FLOW_LOGIC_SPEC.md`,
`docs/MANUAL_STEPS.md`, `README.md`

- `EQ_Config_Sites`をSharePointリストから廃止。監視対象拠点(大分・大阪・東京)と
  震度閾値は運用中も変わらない固定値であり、かつ`TeamId`/`ChannelId`をサイト
  閲覧者全員に見えるリストへ置く必要もないという指摘を受け、
  `EQ06_Manual_Drill_DEV`内のSwitchアクション(`CMP_Site_Config`)に
  固定値として持たせる設計に変更した。`docs/FLOW_LOGIC_SPEC.md`のアクション
  順序・式を全面的に更新。
- `provision_sharepoint_*.ps1`から`EQ_Config_Sites`関連のリスト作成・データ投入
  処理を削除(SharePointリストは4個に)。
- `EQ_Config_Members`のマネージャー3件のIDを`boss01`/`boss02`/`boss03`から
  `mgr01`/`mgr02`/`admin01`に変更。
- 実機検証で、PnP.PowerShellによるSharePoint自動化にはEntra IDアプリ登録
  (IT部門の承認)が必要と判明したため、`docs/MANUAL_STEPS.md`の推奨手順を
  「Excelアップロードによる一度限りの手動作成」に変更(スクリプトは代替手段として残置)。

## [20260730_01] - 2026-07-30

**追加ファイル:** `README.md`, `config/sites.json`, `config/members.example.json`,
`cards/channel_alert_card.json`, `cards/checkin_card.json`,
`scripts/provision_sharepoint.ps1`, `scripts/deploy_solution.ps1`,
`solution/README.md`, `docs/FLOW_LOGIC_SPEC.md`, `docs/MANUAL_STEPS.md`,
`docs/GATE_STATUS.md`

- Power Automate(標準コネクタのみ)による地震安否確認システムのPoC初版を開始。
  Python + Microsoft Graph API版がAzure ADアプリ登録・管理者同意の壁に当たったこと、
  および先行して提示されたPower Automate構想の精査結果(`docs/REVIEW_earthquake_safety_system_0730_02.md`)
  を踏まえ、手動トリガー版(P1)から着手する。
- SharePoint 5リスト・全列・拠点3件・メンバー21名(スタッフ18名+上司3名)を
  PnP PowerShellで自動プロビジョニングするスクリプトを作成(GUIでの手作業を排除)。
- 非同期アーキテクチャ(カード投げ切り+応答トリガー分離)によるフローロジック仕様を、
  Power Automate画面へそのまま貼り付けられる形で文書化。
- pac CLIによるSolutionのexport/unpack/pack/importスクリプトを作成し、
  DEV→TEST→PRODの環境展開時にフローを再構築する手間を排除。
- 自動化できない最小限の手作業(接続認証、フロー本体の初回構築、Gate B証拠取得)を
  `docs/MANUAL_STEPS.md`に明記。
- PowerShellスクリプトはASTパーサーで構文検証済み(実テナントでの実行は未検証)。

## [20260730_02] - 2026-07-30

**変更ファイル(リネーム):** `scripts/provision_sharepoint.ps1` →
`scripts/provision_sharepoint_20260730_01.ps1`、
`scripts/deploy_solution.ps1` → `scripts/deploy_solution_20260730_01.ps1`

**追加ファイル:** `run_power_automate_tools.bat`

- リポジトリの命名規約(`ツール名_yyyymmdd_連番.拡張子`)が`.py`だけでなく
  実行コード全般に適用されるべきという指摘を受け、`.ps1`スクリプトに
  リビジョン番号を付与した(初回作成のため、旧ファイル名は残さずリネーム)。
- ファイル名から最新リビジョンを自動検出して起動するランチャー
  `run_power_automate_tools.bat` を追加。SharePointプロビジョニング、
  DEVからのSolutionエクスポート、TEST/PRODへのpack-importをメニューから選べる。
- `emergency_alert_tool/run_emergency_alert_tool.bat` で過去に発生した
  文字化け起動不能事案(UTF-8のバッチファイルがShift-JISコンソールで誤解釈された)
  を踏まえ、表示メッセージを全て英数字(ASCII)に統一し、CRLF改行で保存した。
  この方針をリポジトリ直下の`CLAUDE.md`にも明文化した。

## [20260730_03] - 2026-07-30

**変更ファイル:** `run_power_automate_tools.bat`, `docs/MANUAL_STEPS.md`

- 実機検証の結果、`PnP.PowerShell` 3.x系はWindows標準の「Windows PowerShell 5.1」
  では動作せず、PowerShell 7.4以降(`pwsh`)が必須であることが判明。
  `run_power_automate_tools.bat`が`powershell`(5.1)ではなく`pwsh`を呼び出すよう修正。
  `pwsh`が見つからない場合はエラーメッセージで導線(https://aka.ms/PSWindows)を示す。
- 実機で遭遇した2つのトラブルと対処法を`docs/MANUAL_STEPS.md`に追記:
  - 非管理者アカウントでの`Install-PackageProvider`失敗(`-Scope CurrentUser`で解決)
  - 古い`PowerShellGet`(`1.0.0.1`)による`Install-Module`の`Telemetry`型エラー
    (`PowerShellGet`自体の更新+PowerShellウィンドウの再起動で解決)

## [20260730_04] - 2026-07-30

**追加ファイル:** `scripts/provision_sharepoint_20260730_02.ps1`(`_01`は規約により残置)

- 実機検証で、PnP.PowerShellがインストール済み・`Import-Module`単体では動作するにも
  関わらず、スクリプト実行時には`Connect-PnPOnline`が「認識されないコマンド」として
  失敗する事象を確認(モジュールの自動読み込みが環境によって効かない)。
  スクリプト冒頭で明示的に`Import-Module PnP.PowerShell`を行うよう修正。
