# Document Search Manager — 設計メモ・調査記録

このツールを**次に触るとき**（Phase 2: Nexus / Phase 3: Enovia の実装、不具合対応、
他ツールへの転用）に必要な知識をここに集約する。
使い方は `README.md`、変更の経緯は `CHANGELOG.md` を参照。

---

## 1. このツールの位置づけ

社内の3つのドキュメント管理系を、**同一キーワードで横断検索**するツール。

| 選択肢 | 対象 | 状態 |
|---|---|---|
| `0. All` | 有効な全系統を並列検索（既定） | 稼働中（SharePoint ＋ Nexus） |
| `1. SharePoint` | 社内SharePoint全社横断検索 | **Phase 1 完了・実機稼働確認済み** |
| `2. Nexus` | Shareflex品質文書サイト（SF_QualityDocumentsProd） | **実装済み・件数の一致を実測で確認済み** |
| `3. Enovia` | 3DEXPERIENCE / ENOVIA（2017年版） | Phase 3（未着手） |

---

## 2. 最重要の制約：新規のEntra ID権限を申請しない

**これは越智さんからの明確な指示であり、設計上の絶対条件。**

- 社内で新しいAPI権限の承認を取るコストが非常に大きいため、
  **既存の `po_database_organizer` と同一のEntra IDアプリ登録を流用する。**
- 要求スコープは **`Sites.Read.All` のみ**。
- `tenant_id` / `client_id` は `config.json` が空なら既存ツールの `config.json` から
  自動借用する（探索順: `po_database_organizer` → `onenote_report_generator`、
  `credentials_from` で任意パスも指定可）。
  キー名は小文字・大文字の両方に対応（onenote側は `TENANT_ID` と大文字）。

### 実機で確認済みの事実（Phase 1）

- **`POST /search/query`（entityTypes: listItem）は `Sites.Read.All` だけで通る。**
  会社PCで疎通診断が `search-api` モードで成功し、`validation` で50件を取得できた。
  → **当初懸念していた権限不足のリスクは解消済み。**
- 権限不足だった場合に備え、サイト単位検索
  （`GET /sites/{host}:{path}:/drive/root/search`）へ自動フォールバックする実装を
  残してある（`config.json` の `fallback_site_urls` に対象サイトを列挙する）。

---

## 3. 調査で判明した事実（Phase 2/3 の前提）

### 3-1. Nexus（Shareflex）の全文検索の正体 — Phase 2 の設計根拠

会社PCのブラウザ（F12 → Network）で実際の通信を確認した結果：

- 検索の実体は **SharePoint標準のREST API `RenderListDataAsStream`**。
  Shareflex独自の検索エンジンではない。
- リクエストの Query String に **`InplaceSearchQuery: validation`** が入っている。
  → これは **SharePointの検索インデックス**を使う仕組みで、SharePointは文書本文まで
  クロールしている。つまり **Nexusの全文検索＝SharePoint検索インデックスによる
  文書内全文検索**。
- 確定したパラメータ:
  - `@listId` = `guid'eb4ed9f8-81f8-4484-b8f6-64f22d30bfe0'`
  - `FolderServerRelativeUrl` = `/sites/SF_QualityDocumentsProd/Documents`
- URLに `&q=<キーワード>` を付けるだけで、**検索済み状態のNexus画面を直接開ける**。
- 1回の検索に **約4.25秒・1.4MB** かかっている（体感の重さの実測値）。

**したがって Phase 2 の実装方針は以下で確定している。**

- **本命**：Graph の `POST /search/query` に、検索範囲をNexusに限定したKQLを渡す。
  ```
  <キーワード> path:"https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents"
  ```
  参照先インデックスが同一であるため、同等の結果が返る見込みが高い。
  **使用スコープは `Sites.Read.All` のままで、新規権限は不要。**
- **受入テスト**：キーワード `validation` で、Nexus画面とツールの件数・上位ヒットを
  突き合わせる。一致しなければ保険案へ。
- **保険**：`&q=` のディープリンクを生成してワンクリックで開く方式（実装数十行）。
- 有効化と同時に `config.json` の `dedupe_nexus_from_sharepoint` を `true` にする
  （SharePoint全社検索にもNexus文書がヒットして二重表示になるため）。

#### 実装結果（v20260903_09 / Phase 2）

上記の方針どおりに実装した。実装上の判断は以下のとおり。

- **`NexusProvider` は `SharePointProvider` を継承**した。Graph呼び出し・パーサ・
  ページング・フォールバックは同一で、違うのは「検索範囲を絞るKQL」と
  「疎通診断のメッセージ」だけだから。親クラスに4つのフックを設けてある。

  | フック | 役割 | Nexusでの差し替え |
  |---|---|---|
  | `_query_string(keyword)` | Graphに渡すクエリ文字列 | `<kw> path:"<Nexusフォルダ>"` |
  | `_search_fields()` | 要求するマネージドプロパティ | 標準＋`nexus_extra_fields` |
  | `_fallback_sites()` | 権限不足時のサイト単位検索先 | `nexus_site_url` の1件 |
  | `_degrade_fields()` | HTTP 400時の縮退 | 固有列→標準列の2段階 |

  **この構造の利点**：既知の罠（タイトル欠落、拡張子の誤認識、フォルダの扱い、
  `/personal/` の判定）への対策が、Nexus側にも自動的に効く。

- **`path:` に渡すのは絶対URL**。`config.json` の `nexus_folder_path` は
  サーバー相対パスなので、`nexus_site_url` のスキーム＋ホストと突き合わせて
  絶対URLへ直している（`_nexus_scope_url`）。
- **保険**：`path:` の絞り込みが効かなかった場合に備え、Nexusサイト外の行は
  結果から落とす。無関係な文書を「Nexusのヒット」として見せると、重複排除の
  判定まで狂うため。落とした件数は画面のメッセージに出す（黙って消さない）。
- **重複排除は「Nexusを実際に検索したときだけ」**行う。`1. SharePoint` 単独でも
  除外してしまうと、Nexus配下の文書がどこにも表示されない取りこぼしになるため。
- **認証を排他制御した**。2系統が別スレッドから同時にトークンを要求するように
  なったので、`token_cache.json` の書き込みが重ならないよう直列化した。

### 3-1d. ★解決済★ Nexus画面と件数が合わなかった件（14 vs 116）

**結論：ツールの実装は正しく、原因は入力の非対称だった。**
ツール側にだけ引用符付き `"validation plan"` で入力されており、
完全一致のフレーズ検索になっていた。Nexus画面側は引用符なし＝AND検索。

実機の「Nexus検索診断」の実測値（キーワード `validation plan`）:

| 方式 | Graphが返した該当件数 |
|---|---|
| ① `path:"<Documentsフォルダ>"`（現行方式） | **117 件** |
| ② `SPSiteURL:"<Nexusサイト>"` | 297 件 |
| ③ 絞り込みなし（全社） | 126,090 件 |
| ④ `"validation plan"`（引用符あり）＋ ① | **14 件** |

- **① 117件 ≒ Nexus画面 116件。**参照インデックスが同一という前提どおりで、
  **`path:` によるフォルダ限定が正しい絞り込み方式**であることが実測で確定した。
- ② のサイト単位（297件）は広すぎる。Nexusサイトには `Documents` 以外にも
  文書が存在する。
- ④ が越智さんの見た14件。**引用符の有無だけで 117 → 14 に減る。**

**教訓（同種の突き合わせで必ず効く）:**

- **件数が合わないときは、まず両者の入力条件が本当に同じかを疑う。**
  実装を触る前に、条件を揃えて測り直す。
- **推測で直さず、複数方式を実際に投げて件数を並べる。**
  この診断（`/api/nexus_diag`）を作ったことで、1クリック・数秒で確定した。
  仮説を3つ立てて順に試すより速く、しかも証拠が残る。
- ツールは引用符を勝手に外さない（利用者の意図を尊重する）。
  代わりに、引用符が含まれるときは「完全一致になる／件数が大きく減る」旨を
  ログで警告する。

### 3-1f. ★重要★ 並列実行のタイムアウトで全体を失敗にしてはいけない

- v10 で `❌ 検索でエラーが発生しました: 1 (of 1) futures unfinished` が発生し、
  **HTTP 500 で検索結果が丸ごと失われた**（実機で検出）。
- 原因は `as_completed(..., timeout=...)` の `TimeoutError` を捕まえていなかったこと。
  Index取得（1件につき1リクエスト）を足したことで、上位100件の検索が
  既定の30秒を超えるようになり表面化した。
- **このツールの設計原則は「部分成功方式」**（4-1）。待ち合わせの例外を素通しすると
  この原則が崩れる。**タイムアウトは必ず捕まえ、間に合った系統の結果は返す。**
  間に合わなかった系統は 🔴 と理由を表示する（黙って隠さない）。
- 重い処理を足したら、**既定のタイムアウトが足りているかを必ず見直す**
  （`provider_timeout_sec` を 30 → 180 秒にした）。

### 3-1b. Nexus固有の列（標準Index）— 取得方式（v10で確定）

越智さんから提示されたNexusの標準Indexは次の7列。

`Document Number` / `OldSystemIdentifier` / `Document Title` /
`Doc Author` / `Doc Owner` / `Applicable To` / `Department`

**採用した方式（v20260903_10）**: 検索マネージドプロパティ名を推測せず、
**リスト項目そのものを引く**。

```
GET /shares/{share_token}/driveItem?$expand=listItem($expand=fields)
```

- ファイルのURLさえあれば引けるので、item id や list id を推測しなくてよい。
  `/shares/{token}/driveItem/content`（一括ダウンロード）で実績のある経路。
- 返ってくる `fields` のキーは**SharePoint側の内部名そのもの**なので、確実に実在する。
- 内部名の揺れ（`Document_x0020_Number` / `DocumentNumber` / `Document Number`）は
  正規化して突き合わせる（`_normalize_field_key`）。1つの綴りに決め打ちしない。
- 人物列は `{"LookupValue": ...}`、複数選択列は配列で返るため平坦化する（`_field_text`）。
- **実在した列名は、起動後の最初の検索で1度だけコンソールに出す。**
  自動判別が外れたときに `nexus_field_map` で明示指定するための材料。
- 1件につき1リクエスト増えるため、`nexus_enrich_max` / `nexus_enrich_workers` で制御する。

**却下した方式**: Graph Search の `fields` に管理プロパティ名を並べて要求する
（v09 の `nexus_extra_fields`）。テナントごとに名前が違って当てられず、
外すと検索全体が HTTP 400 になる。保険として残してあるが、主たる方式ではない。

#### 実機で確定した内部列名（Nexperiaテナント）

Shareflexは画面のラベルとは別に `qm*` / `nx*` の独自接頭辞を使う。
**名前からは推測できなかった。** 実機のログで実在を確認して確定させたもの:

| 画面のラベル | 内部名 |
|---|---|
| Document Number | `qmDocumentNo` |
| OldSystemIdentifier | `nxOldDocumentNo` |
| Document Title | `qmDocumentTitle` |
| Document Type | `qmDocumentType` |
| Applicable To | `nxApplicable` |
| Department | `nxFunctionalOrg` |
| Top Level Process | `qmProcess1` |
| Doc Author | `qmEditor` |
| Doc Owner | `qmConfirmer` |

その他に存在する列（今は未使用だが、後で効いてくる可能性がある）:
`qmStatus` / `qmStatusEn`（文書ステータス）、`qmValidFrom` / `qmValidUntil`（有効期限）、
`qmRevisionNo` / `qmRevisionReason`、`qmApprover` / `qmConfirmerLookupId`、
`nxDocReviewer` / `nxFunctionalOrg`、`qmProcess1`、`qmConfidentialLevel`。

**確定は実機の「Nexus列診断」で行った**（NDS-00072 / FMEA の全列を出力し、
Nexus画面の同じ行と突き合わせ）。Doc Author = Maik Jörn Teschner、
Doc Owner = Ansgar Thorns が一致することを確認済み。
この列データは `tests/test_13_people_concurrency.py` に取り込んであるので、
対応づけが崩れたらテストで落ちる。

#### ★重要★ 人物列の罠（Doc Author / Doc Owner）

Graph は人物列を `<列名>LookupId`（数値ID）でしか返さない（`qmEditorLookupId` = 27）。
ここで **2段階の失敗が起きた（v11で実際に発生）**。

1. **数値をそのまま画面に出してはいけない。**「27」は情報ではない。
2. **数値だから採用しない → 次の候補に回る、という設計が裏目に出た。**
   候補一覧に `nxDocReviewer`（Doc Reviewer）や `qmApprover`（承認者）を
   入れていたため、**Doc Author / Doc Owner の列に別の役割の人が表示された。**
   一部の行だけ値が入っていたのは、それらの列が入力されている文書だけだったため。
   **「空欄を埋めよう」として役割の違う列を流用するのは、空欄より悪い。**

**対処（v12）**: 数値IDを氏名に解決する。サイトの「User Information List」を
`GET /sites/{siteId}/lists/User Information List/items/{id}?$expand=fields` で引き、
`qmEditorLookupId = 27` から `qmEditor = "David Chen"` という列を作ってから
対応づける。同じ人は引き直さない。参照できない環境では**空欄のままにする**。

**その後の発見（v15）**: **Shareflexの人物列は、氏名そのものも一緒に返ってくる。**
`qmEditor = "Maik Jörn Teschner"` と `qmEditorLookupId = 325` の両方が来る。
つまり**この環境では引き当て自体が不要だった**（しかもユーザー情報リストは
HTTP 404 で参照できない）。氏名が既にある列は引き当てに行かないようにした。
残してあるのは、氏名が返らない列への保険。
**教訓**: 「取れないはずだ」と決める前に、**返ってきているデータを全部見る。**
列診断で全列を一覧にして初めて `qmEditor` が入っていることに気づいた。

**あわせて、値の出所を常に見えるようにした。** 画面のラベルと内部名の対応は
名前からは決められないため、各セルにマウスを載せると
「Doc Author ← 内部列 qmEditor」と出る。対応表はコンソールにも出力する。
**Doc Author / Doc Owner の対応は、この表示をNexus画面と突き合わせて確定させること。**

### 3-1i. ★重要★ 並列処理でキャッシュに「空の途中結果」を置いてはいけない

v12〜v13 で、**Doc Author / Doc Owner が行によって空欄になる**不具合を出した。

```python
# 誤り（v13まで）
if lookup_id in self._people_cache:
    return self._people_cache[lookup_id]
self._people_cache[lookup_id] = ""      # ← HTTP要求の「前」に空を置いた
...HTTP要求...
self._people_cache[lookup_id] = name
```

検索結果は6並列で処理される。**同じ人物を同時に引いた2本目以降のスレッドは、
1本目がまだ取得中に置いた空文字を読んで、そのまま空欄を返していた。**
同じ担当者の文書が並ぶほど空欄が増える。

- **修正**: 引き当ての開始から結果を貯めるまでを1本の鍵（`threading.Lock`）で
  囲んで直列化する。同じ人物は先に引いた1本の結果を全員が使う。
- **再現確認**: 修正前のコードに6スレッドから同じ人物を引かせると
  **6本中5本が空欄**になる。この形を `tests/test_13_people_concurrency.py`
  にそのまま残してある。
- **教訓**:
  - 「二重取得を防ぐための placeholder」は、**並列前提では逆に取りこぼしを生む。**
    未取得と取得済みを1つの値で兼ねてはいけない。
  - **例外も権限エラーも出ないため、テストでも画面でも気づけない。**
    「一部の行だけ空欄」という症状は、並行処理を疑う手がかりになる。
  - 並列で走るコードに共有状態を足したら、**必ず並列で検証する**
    （単体で1回呼んで通ることは、何の保証にもならない）。

### 3-1g. ★重要★ Shareflexの列フィルタはURLに載る（`@<内部列名>=`）

**Nexusの1件だけを開くリンクは、列フィルタで作る。**

```
https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/SitePages/Shareflex/View.aspx
  ?$List=eb4ed9f8-81f8-4484-b8f6-64f22d30bfe0
  &$RootFolder=%2Fsites%2FSF_QualityDocumentsProd%2FDocuments
  &@qmDocumentNo=NDS-00072
```

- パラメータは `@` ＋ **内部列名**（画面のラベルではない）。
  `$List` / `$RootFolder` が `$` 始まりなのに対し、列フィルタは `@` 始まり。
- **全文検索（`q=`）を使ってはいけない**（越智さんのご指摘）。
  文書番号は他の文書の本文に「参照文献」として書かれていることが多く、
  全文検索だと**それらが全部ヒットして1件に絞れない**。
  **番号は「番号の列」で絞る。** これは検索設計の一般則としても効く。

**この節は2度書き直している。経緯を残しておく（同じ失敗を繰り返さないため）:**

1. v09: 「`&q=` を付ければ検索済み状態で開ける」と想定 → **誤り**。
   F12で見たリクエストのパラメータ名を、画面遷移URLのパラメータ名だと
   思い込んだ。**実際にそのURLを開いて確かめていなかった。**
2. v12: 提供された「検索実行中のURL」に検索語が無かったため
   「Shareflexは検索条件をURLに載せない」と結論 → **これも誤り**。
   そのURLは*全文検索*を使ったときのもので、**列フィルタは載る**。
   **1つの反例だけで「載せない」と一般化してしまった。**
3. v13: 列フィルタを使ったときのアドレスバーを見て確定。

**教訓**: URLの仕様は、**実際にそのURLを開いて**確かめるまで確定としない。
「載らない」という否定の結論は、**操作の種類を変えて試すまで**出さない。

### 3-1j. 有効期限は「日付から判定する」（ステータス列を信じない）

Nexusの標準書は有効期限（`qmValidUntil`）を持ち、期限切れかどうかは業務上の
重要情報。v16でNexusタブに列として追加した。

**判定にShareflexのステータス列を使ってはいけない。**
実機のNDS-00072は `qmStatus = Expired` と `qmStatusEn = Valid` が**食い違っていた**。
どちらが正なのか外部からは判断できない。一方、`qmValidUntil = 2026-07-27` は
明確で、実行日と比べれば誰でも同じ結論に至る。

- **判定は日付で行い、画面には日付そのものを出す**（利用者が検算できる）。
- Shareflex側の両ステータスは**捨てずにツールチップへ添える**。
  情報を捨てると、後で「Nexusの表示と違う」と言われたときに追えなくなる。
- 「まもなく期限」の日数は `expiry_warn_days`（既定60日）で変えられる。

**一般則**: 出所の異なる2つの値が矛盾していたら、**どちらかを選ぶのではなく、
自分で導出できる根拠（この場合は日付）に切り替え、元の値は参考として残す。**

### 3-1h. タイトルだけを検索する（既定オン）

- 本文まで対象にすると、タイトルと無関係な文書まで大量に当たる
  （`validation plan` の全文検索は117件、全社では126,090件）。
  標準書を探す用途では、**タイトルに語が含まれるものだけ**のほうが目的に近い。
- 実装は KQL の `title:` 修飾。複数語は `title:validation title:plan` と並べる
  （KQLはAND既定）。**引用符付きで入力された場合は `title:"validation plan"` と
  して完全一致を尊重する**（利用者の意図を勝手に変えない）。
- 対象の検索プロパティ名は `title_field` で変更できる。Shareflexの
  `qmDocumentTitle` に対応する検索プロパティ名が判明したら差し替えられる。
- Nexus検索診断に「⑤ タイトルのみ」を足したので、件数の差を実測できる。

### 3-1c. 系統別タブ構成（v20260903_10 で実装）

**採用した方式（案A）**: 表・絞り込み・並べ替え・出力・状態復元は1系統のまま流用し、
**列定義（`COLUMN_SETS`）だけをタブごとに切り替える**。表を2本持つと保守コストが
倍になり、必ず片方が腐るため。

- 列構成は「選択したタブ」ではなく **「実際に検索した系統」** に追従させる
  （`/api/search` が `target` を返し、画面がそれを見て切り替える）。
  検索していないのに列だけ変わると、見出しと中身が食い違って誤解を生むため。
- タブを押すと、キーワードが入っていればその系統で検索し直す。
- **列構成を変えるときは、表示しない列の絞り込みを必ず落とす**（`applyColumnSet`）。
  落とさないと、理由の分からない「0件」や「絞り込み後N件」が発生する。
  実際に v09 では、前回の絞り込みが復元されて114件中6件しか見えない状態が起きた。

**Nexusタブに サイト列・フォルダ列を出さない理由**:
Shareflexはドキュメントを `Documents/3E08-CD5F/` のような**内部ハッシュのフォルダ**に
格納する。人間には情報価値がゼロで、SharePointと同じ列に並べても意味を成さない。
`0. All` タブからもフォルダ列を外している（Nexus行では埋まらないため）。

### 3-1e. ★重要★ Nexus行に SharePoint標準のフォルダビューURLを張ってはいけない

- `.../Documents/Forms/AllItems.aspx?id=...` を開くと、**一度表示された後、数秒で
  Shareflexが自サイトのトップ画面へ強制遷移させる**（実機で確認）。
  Shareflexは独自UIで動くため、標準ビューに留まらせない設計になっている。
- サイトURL（`.../sites/SF_QualityDocumentsProd`）も、Nexusのフォルダトップに
  飛ぶだけで文書には辿り着けない。
- **正しいリンクは、Shareflex自身の画面URLに `&q=` を付けたもの**:
  ```
  https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/SitePages/Shareflex/View.aspx
    ?$List=eb4ed9f8-81f8-4484-b8f6-64f22d30bfe0
    &$RootFolder=%2Fsites%2FSF_QualityDocumentsProd%2FDocuments
    &q=<文書番号>
  ```
  これを `config.json` の `nexus_view_url` に持たせ、`&q=` を付けて生成する。
- ファイル本体のURL（タイトルのリンク先）は従来どおりで問題ない。

### 3-2. SharePoint REST を直接叩いてはいけない理由

- `RenderListDataAsStream` は `nexperia.sharepoint.com/_api/...` を叩く
  **SharePoint REST API** であり、**Graph向けトークンでは通らない**。
  呼ぶには SharePoint 向けの権限追加＝**IT申請が発生する**（＝制約違反）。
- さらにリクエストには MCAS（Microsoft Defender for Cloud Apps）が
  **`McasCtx` / `McasTsid` / `McasUserAuth`** を注入している。
  Pythonから再現するにはブラウザセッションまで持ち込む必要があり非現実的。
- **Graph（`graph.microsoft.com`）はMCASの経路外**なので、この問題を完全に回避できる。
  `po_database_organizer` でも実証済み。

### 3-3. ★解決済★ Enovia（Phase 3）— 実装方式の確定と実装（v20260904_01）

**当初の想定（案A: requests.Session でCASログインを再現）は的中し、
Playwrightは「ログインでCookieを取るときだけ」使う形（案B'）に落ち着いた。**
経緯と確定事項を残す。

#### 調査の経緯（越智さんとの往復）

1. **1回目のF12キャプチャは空振り**：`Keep log` 未チェック／検索実行後に
   DevToolsを開いていたため、検索リクエストが記録されていなかった。
   → 手順を「F12を先に開く→ Keep log ON → その後で検索」に修正して再依頼。
2. **2回目のHARにも検索リクエストが無し**：別画面（Project Management）の
   操作を録ってしまっていた。ただし副産物として、Enoviaのクラシック側の
   表が `emxIndentedTable.jsp`（GET・HTML）で描画されていることが分かった。
3. **3回目、同じキーワードで何度検索してもNetworkに何も出ない**：
   「メモリから再描画しているのでは」と疑ったが誤りだった。件数もアイコンも
   実際に変わっており、**検索は実行されていた**。原因はNetworkパネルの
   フィルタや録画タイミングではなく、**検索の宛先がキャプチャ対象と
   別ホスト（`federated.plm.nexperia.com`）だったため**、そもそもリストに
   出ていなかった。
4. **Consoleに `XMLHttpRequest.prototype.open/send` をフックするコードを
   貼ってもらい、実行中に捕捉**：ここで初めて実際のエンドポイントと
   リクエストボディの一部（`Show more` で省略された分含む）が判明した。
5. **`window.fetch`/`XMLHttpRequest` をフックしてレスポンスまで含めて
   JSONに保存するコードを実行してもらい**、リクエスト全文・レスポンス
   全文（`infos.nhits` / `results[].attributes[]` の構造）を確定した。
6. **越智さんが実際にEnoviaの画面上でURLを3つ試し**、
   「Enoviaで開く」リンクの形式（`emxNavigator.jsp?objectId=<resourceid>`）と、
   `WebPublish URL` によるダウンロードが**文書の状態次第で拒否される**
   ことを実測で確定した。

**教訓**：F12のNetworkタブは「今見えている画面と同じホストへの通信」
   しか直感的には見つけられない。**別ホストへの通信は、Consoleでの
   XHR/fetchフックの方が確実**（ホストをまたいでも捕まえられるため）。

#### 確定した仕様

- **検索の実体**：`POST https://federated.plm.nexperia.com/federated/search
  ?xrequestedwith=xmlhttprequest`（Exalead系のJSON API）。
  クラシックUI（`emxNavigator.jsp` 等）は結果表示にのみ関与し、
  検索そのものには関与しない。
- **認証はCookieのみ**。リクエストヘッダーは `Accept` / `Content-Type` の
  2つだけで、トークン・CSRFの類は不要（実測で確認）。
- **リクエスト本文**：`query`（キーワード）/ `nresults`（1ページの件数）/
  1ページ目は `start`、2ページ目以降は前回応答の `infos.next_start` を
  そのまま `next_start` に入れ `refine: {}` を追加（実測どおりの切り替え）。
  `specific_source_parameter.3dspace.additional_query` に、対象タイプを
  `flattenedtaxonomies:"types/<型名>"` のORで191種類列挙し、
  `Person` / `Security Context` の2種は別枠の `AND NOT (...)` で除外、
  末尾に `AND (latestrevision:true OR NOT listoffields:latestrevision)`
  を付ける（すべてブラウザの実リクエストをそのまま転記）。
- **レスポンス**：`infos.nhits` が総件数（**絞り込み前の全種別合計**。
  Documentだけの件数ではない）。`results[].attributes[]` は
  `{format, name, value}` の配列で、`ds6w:identifier`（文書番号）/
  `ds6w:label`（タイトル）/ `ds6w:description` / `ds6wg:revision` /
  `ds6w:what/ds6w:status`（状態）/ `ds6w:who/ds6w:responsible`（Doc Owner）/
  `ds6w:who/ds6w:responsible/ds6w:originator`（作成者）/
  `ds6w:who/ds6w:lastModifiedBy`（最終更新者。無い行もある）/
  `ds6w:when/ds6w:modified` / `ds6w:when/ds6w:created`（いずれもUTC ISO8601）/
  `ds6w:where/ds6w:context/ds6w:folder` / `ds6w:what/ds6w:docExtension` /
  `resourceid`（internal）が実測で確認できた。
- **`ds6w:what/ds6w:type`** で文書型を判定できる（`"Document"` / `"Issue"` 等）。
  型のOR条件は緩いまま（Issueも含めて191種類）にし、**応答を受けてから
  クライアント側で `Document` だけに絞る**設計にした
  （`enovia_document_type_only`、既定true）。理由：型のOR条件を絞り込むと
  Enovia画面の挙動と食い違うリスクがあるが、応答後の絞り込みなら
  いつでも設定で戻せる。
- **同一Document Numberでもリビジョン違いは別行のまま返る**（実機の
  3DSearch画面でも同様。`latestrevision` 句はほとんど効いていない）。
  → **D1（承認済み）**：全部表示する。Enovia画面と一致させることを優先。
- **「Enoviaで開く」リンク**：`https://dspace.plm.nexperia.com/3dspace/
  common/emxNavigator.jsp?objectId=<resourceid>` で実際に文書が開くことを
  実機で確認済み（2026-09-04、`DOC-594838` 1件）。
- **ダウンロードは実装しない**：詳細画面の `WebPublish URL`
  （`.../nexwebpublish/download?type=Document&name=<番号>&fileName=<ファイル名>`）
  は、`Allow Web publish: No` の文書では
  `Document ... doesnt exist or not in valid state, Download is not possible`
  で拒否されることを実機で確認した。`fileName` を省略しても同じ結果。
  **一括ZIPダウンロードの対象からEnoviaは除外し**、「Enoviaで開く」から
  Enovia画面上のDownload操作に委ねる設計にした。
- ★解決済★ **タイトル限定検索は非対応と確定した（2026-09-04, 実機確認）**。
  推測で `title:` 等の構文を決め打ちせず、「Enovia検索診断」ボタンで候補
  （`title:"FMEA"` / `ds6w:label:"FMEA"`）を実測したところ、**どちらも0件**
  だった（全文検索は1952件で正常）。0件は「該当する文書が無い」ではなく
  「そのフィールド名自体が検索エンジンに認識されていない」ことを意味する。
  `ds6w:label` は**応答（結果）の項目名としては実在する**が、**検索クエリの
  フィールド名としては別物**であるとみられる（Exalead系エンジンでは表示用
  項目名と検索用フィールド名が一致しないことがある）。
  越智さんにEnovia画面自体に「タイトルだけで検索する」機能が無いか確認を
  依頼し、無ければ**これ以上の推測は行わず、Enoviaは常に全文検索のみ**と
  して確定する（3個目の構文を当てずっぽうで試すことはしない）。

#### 認証の実装（越智さんの回答を反映）

- 「1日1回ログインすれば、その後はEnoviaのトップにそのまま入れる。
  ログインが必要ならその場は手作業ログインで構わない」という回答から、
  **Playwrightで会社PC既存のEdge（`channel="msedge"`。Chromiumの追加
  ダウンロードは発生しない）をログイン時だけ起動し、越智さんが手動で
  ログイン後にウィンドウを閉じたらCookieを保存する**方式にした
  （画面の「Enoviaにログイン」ボタン）。
- EnoviaのDOM構造やログイン後の遷移先URLを推測して自動判定すると、
  UI変更に弱くなるため、**「ウィンドウを閉じる」という人間の意思表示**
  を合図にした（タイムアウトした場合もその時点のCookieで保存を試みる）。
- 保険として、Cookieを `config.json` に手で貼る方式
  （`enovia_auth_mode="manual"`）も残した。

---

## 4. 実装上の重要な設計判断

### 4-1. アーキテクチャ

- `SearchProvider` 抽象 ＋ プロバイダ別アダプタ。
  `search(keyword, max_results) -> {"results": [...], "total": int, "note": str}` の
  I/Fだけを満たせば、Nexus / Enovia を後から足せる。
- `0. All` は薄い並列実行層（`ThreadPoolExecutor`）。**部分成功方式**で、
  1系統が落ちても他系統の結果は必ず返す。系統ごとに 🟢/🟡/🔴/⚪ を表示する。
- 未実装の系統は**黙って0件を返さず**、「Phase 3で実装予定」と明示する。

### 4-2. パスの扱い

設定・キャッシュ・出力はすべて `Path(__file__).resolve().parent` 基準。
**カレントディレクトリに依存させない**（`po_database_organizer` は cwd 基準のため、
batやショートカットから起動するとパスがずれる。この弱点は継承しない）。
起動バッチは先頭で `cd /d %~dp0` を実行し、**コメントはASCIIのみ**にする
（日本語コメントをUTF-8で書くとCP932のコマンドプロンプトが誤解釈してエラーを出す）。

### 4-3. バージョン管理と `old/`

- ファイル名は `document_search_manager_YYYYMMDD_NN.py`。旧版は削除しない。
- **起動時に、自分より古い版を自動的に `old/` へ移動**する（`_archive_old_versions`）。
  自分自身と自分より**新しい**版は動かさない。
- **リポジトリ側でも旧版を `old/` に置く。** ローカルだけで移動すると
  `git pull` のたびに旧版が復活して重複するため、構成を一致させることが必須。

### 4-4. フォルダとファイルの区別（案A）

- 検索結果には**フォルダ自体もヒットする**。これを除外してはいけない。
  **フォルダ名にキーワードが含まれる一方で、中のファイルには含まれない**ケースでは、
  フォルダの存在そのものが有用な情報になるため（越智さんの指摘）。
- 除外せず、**種別列に「フォルダ」と表示して区別**する。種別フィルタ（複数選択）で
  ファイル／フォルダを切り替えられる。フォルダ行は一括ダウンロードの対象外。
- `config.json` の `exclude_folders`（既定 `false`）で除外にも切り替えられる。

### 4-5. フォルダ表示の短縮

- `Shared Documents` などの既定ライブラリ名は、どのサイトにもあり情報価値が低いため
  **ライブラリのルートを示す `/` に置き換える**。
- **単純に文言を削除してはいけない。** 直下の場合に空欄となり、
  「フォルダ情報が取れなかった行」と区別できなくなる（越智さんの指摘）。
- 固有のライブラリ名（`PO` など）はそのまま残す。
- ツールチップとExcel/CSVには**フルパス**を出すので情報は失わない。

---

## 5. 既知の罠（同種のツールを作るときも要注意）

### 5-1. Graph の `listItem` は既定でタイトルを返さない

- `POST /search/query` を `entityTypes: ["listItem"]` で呼ぶと、`resource` には
  `webUrl` / `createdBy` / `lastModifiedDateTime` 程度しか入らず、
  **タイトルも拡張子も返らない**（画面が全行「(タイトルなし)」になる）。
- 対策：リクエストに **`fields`（検索マネージドプロパティ名）を明示的に要求**する。
  現在の要求項目は `config.json` の `search_fields`。
- テナントに存在しない名前を指定すると **HTTP 400** になるため、
  400を検知したら **`fields` 無しで自動再試行**し、以後は要求しない実装にしている。
- さらに保険として、**リンク先URLの末尾からファイル名を復元**するフォールバックを
  持つ（`_name_from_url`）。

### 5-2. 拡張子の誤認識（社内命名規則との衝突）★特に重要

- 「最後のピリオド以降を拡張子とみなす」実装は、**社内では必ず破綻する。**
  `12. Validation` / `40. Bench Validation` / `01. Validation_Plan` / `MRA2.0` のように
  **番号やバージョンを含むフォルダ名が多用されている**ため。
- 実際に、種別列に `%20validation` という値が表示され、**これらのフォルダがすべて
  ファイルと誤判定**されていた（種別フィルタも機能していなかった）。
- 対策：拡張子とみなす条件を **「英字で始まる1〜10文字の英数字」**に限定
  （例外として `7z` を許容）。`_EXT_RE` を参照。
- あわせて、名前は必ず **URLデコード**する（`%20` が残ると拡張子として表示される）。

### 5-3. サイト判定は `/sites/` だけでは足りない

- `/teams/`（Teams連携サイト）と `/personal/`（OneDrive）も存在する。
  `/personal/` を見落とすと、**サイト列に人名が出てフォルダ列が空**になる。

### 5-4. 絞り込みパネルの再描画

- チェックボックス変更のたびに見出しを再描画すると、**開いているパネルが消えて
  複数選択ができない**。パネル表示中は見出しを作り直さず、表示状態だけ更新する
  （`refreshHeadIndicators`）。
- パネルは表の横スクロール領域に切り取られるため **`position: fixed`** とし、
  ボタン位置から座標を計算する。リサイズ・スクロール時は閉じる。

### 5-5. 一括ダウンロードの対象未指定

- 出力（Excel/CSV）は「未指定なら全件」でよいが、**ダウンロードで同じ扱いにすると
  選択していないファイルまで一括取得してしまう**。ダウンロードは
  **明示的な選択（`idx`）を必須**にすること。

### 5-6. 「上位N件」は関連度順

- Graph が返すのは **SharePoint検索の関連度（レリバンス）順**。
- **画面での並べ替えは「取得した範囲の中での並べ替え」**にすぎない。
  「関連度上位10件を最終更新日で降順」は「全社で最も新しい文書」ではない。
  UIのラベルを「関連度上位 N 件」としているのはこの誤解を防ぐため。

### 5-7. Excel出力

- URLを別列に平置きすると使いづらい。**セル自体をハイパーリンクにする**
  （`cell.hyperlink` ＋ 青字＋下線）。
- **CSVはハイパーリンクを持てない**ため、URLは列として残す必要がある。

---

## 6. 検証のしかた

```
cd document_search_manager
python tests/run_tests.py              # ネットワーク不要。663項目
python tests/ui_check.py               # ブラウザ操作テスト（Playwright必要・任意）
python tests/ui_check.py --shot ui.png # 画面のスクリーンショットを保存
```

- テストは **最新バージョンの本体を自動検出**して読み込む（`tests/_harness.py`）。
  バージョンを上げてもテスト側の修正は不要。
- **Graph API にもネットワークにも一切アクセスしない**ため、開発環境でも会社PCでも
  そのまま実行できる。
- 仕様を意図的に変更したときは、**テストの期待値も同じコミットで更新**する
  （変更理由をコメントで残す）。

### 実機でしか確認できないこと

以下は開発環境では検証不可能。会社PCでの確認を越智さんに依頼する。

- Graph の疎通（`search-api` モードで通るか）
- 結果リンクが `.mcas.ms` 経由のブラウザで開けるか
  （開けない場合は `rewrite_host_to_mcas` を `true` にする）
- フォルダリンク（`Forms/AllItems.aspx?id=...`）が正しくフォルダを開くか
  ← **確認済み（2026-09-03）**
- 一括ダウンロード（`/shares/{token}/driveItem/content`）が成功するか
  ← **確認済み（2026-09-03）**。失敗した場合はZIP内の
  `_ダウンロード失敗一覧.txt` に理由が記録される
- Nexusタブの有効期限の表示と期限切れバッジ ← **確認済み（2026-09-03）**

**SharePoint / Nexus 側に、実機未確認の項目は残っていない。**

**Enovia（Phase 3, v20260904_01）も、以下すべて実機で確認済み（2026-09-04）：**

- 「Enoviaにログイン」ボタンでのEdge起動〜Cookie保存 ← **確認済み**（Cookie 35件を取得）
  - **会社PCの環境依存の注記**：Enoviaへの通信で
    `SSLCertVerificationError: unable to get local issuer certificate` が発生した。
    原因は会社ネットワークのSSLインスペクション（`federated.plm.nexperia.com`
    向けの通信を検査するため、社内の証明書に差し替えられる）で、Python
    （`requests`）が会社の証明書を知らないために起きた。Graph API
    （`graph.microsoft.com`）はこの検査対象から外れているため影響を受けず、
    Enoviaだけがこの問題を起こした。`pip install pip-system-certs`
    （WindowsのOS証明書ストアをPythonにも使わせるパッケージ）の導入で解消。
    コード変更は不要だった。
- 実際のキーワード（`FMEA`）での検索 ← **確認済み**。Enovia画面が最初に
  示した件数（1952件）と、`federated/search` の `infos.nhits`（1952）が
  **完全に一致**した。検索範囲の再現が正確であることの強い裏付けになった。
- 「Enovia検索診断」でのタイトル限定構文の確認 ← **確認済み。非対応と確定**
  （3-3参照。`title:` / `ds6w:label:` とも0件で、フィールド名が
  検索エンジンに認識されていないことを意味する）。
- 「Enoviaで開く」リンク ← **複数の文書（`DOC-594838` / `DOC-581582` 他）で
  確認済み**。いずれも正しい文書の詳細画面が開いた。
- 疎通診断でEnoviaが 🟢 になること ← **確認済み**
- **同一Document Numberでのリビジョン違いの別行表示（D1）** ← 実データ
  （`DOC-581582` の Revision 3/2、`DOC-606637` の Revision 1/2）で確認済み

**残る小さな未解明事項**：日付表示に最大1日程度のずれが見られることがある
（例：`DOC-581582` Revision 2 の最終更新日が、ツールでは `2026-09-03`、
Enovia詳細画面では `Sep 4, 2026 12:33:31 AM` 表示）。ツールはUTC→JST変換
（`_format_datetime`、Graph側と共通のロジック）を行っているが、Enovia画面
の表示がJSTちょうどではない可能性がある。**日付のみの表示（時刻を出さない）
であるため実務上の影響は小さいと判断し、現時点では追加調査を行わない**
（越智さんの利用上、支障が出た場合に再調査する）。

---

## 7. 越智さんとの進め方（このプロジェクトでの実績）

- **3フェーズ厳守**：Phase 1 設計提案 → Phase 2 設計監査 → Phase 3 実装。
  コード生成は明示的な承認後のみ。
- **推測で進めない。** 不明点は「未確認」と明記して質問する。
  Enoviaのように公開情報が当てにならない対象では、**実機のF12キャプチャを依頼する**のが
  最短かつ確実だった。
- **設計判断は必ず選択肢と推奨を提示**してから決める。
  フォルダの扱い（案A/B/C）、フォルダ表示の短縮方式などは、この形で決定した。
- **仕様変更でテストが落ちたら、まず「仕様変更に伴う陳腐化」か「機能の劣化」かを
  切り分けて報告する。** 黙って期待値を書き換えない。
- コミット・Pushは**明示的な指示があったときのみ**（Stop hookの自動リマインダーは
  指示ではない）。
