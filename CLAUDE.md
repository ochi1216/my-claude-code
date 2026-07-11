# CLAUDE.md — 越智さん個人開発プロジェクト引継ぎ資料

> 本ファイルは Claude.ai（Web）での開発セッションから Claude Code への移管用引継ぎ資料である。
> プロジェクトルートに `CLAUDE.md` として配置すること。Claude Code は起動時に本ファイルを自動で読み込む。

最終更新: 2026-07-08（Claude.ai セッションからの移管時点）

---

## 1. プロジェクト全体像

越智さん（Nexperia Japan Site Manager）が個人の情報収集・学習効率化のために開発している Python ツール群。**3系統**ある。

| # | プロジェクト | 最新ファイル名 | 概要 |
|---|---|---|---|
| 1 | **統合ニュースダッシュボード** | `consolidated_html_summary_manager_20260708_01.py` | 複数のHTMLサマリ（YouTube/RSS）を統合し、音声読み上げ付きで表示するPython+JS/HTML一体型ダッシュボード |
| 2 | **RSSオーガナイザー** | `rss_organizer_20260703_01.py` | Playwright・Gemini API・Flask・TkinterによるRSSフィード集約・AI要約ツール |
| 3 | **YouTubeプレイリスト管理** | `Youtube_Playlist_management_20260627_02_01.py` | Tkinter製。お気に入り★フラグ・一括登録・★フィルタータブ実装済み |

### ディレクトリ構成（Windows）

```
C:\Users\nx023836\Documents\PythonScripts\RSS\
  consolidated_html_summary_manager_YYYYMMDD_XX.py   ← ツール1
  rss_organizer_YYYYMMDD_XX_XX.py                    ← ツール2
  followed_note_authors.txt                          ← noteフォロー作者URLリスト
  ai_feed_history.json                               ← AIフィード既読履歴（URL→ISOタイムスタンプ辞書）
  start_consolidated_HTML_summary_manager.bat
  start_rss_organizer.bat（最新版rss_organizer_*.pyを自動検出するランチャー）

C:\Users\nx023836\Nexperia\My Private - Documents\Summary\
  _Consolidated_Manager.html    ← ツール1の生成物（成果物）
  summary_database.json         ← ツール1のDBキャッシュ（※重要：下記の落とし穴参照）
  summary_*.html                ← RSSオーガナイザー等が生成する個別サマリHTML（入力）
  archive\                      ← 処理済みサマリHTMLの移動先
```

### summary_*.html のプレフィックス種別

| プレフィックス | 内容 | カード構造 |
|---|---|---|
| `summary_V_` `summary_M_` `summary_N_` `summary_B_` `summary_A_` `summary_S_` `summary_Short_` `summary_BBT_` | YouTube系 | `div.video-card` |
| `summary_RSS_` | RSS系（note/Zenn/Qiita/AIフィード） | `div.thread-card` |

---

## 2. 開発ワークフロー（厳守・最重要）

越智さんは**3フェーズ承認制**を一貫して要求する。**勝手にコードを書いてはならない。**

```
Phase 1: Design Proposal（設計提案）
  - コード生成禁止。設計議論・確認質問のみ
  - 不明点は必ず質問として列挙し、承認前に潰す

Phase 2: Architecture Audit（●２で発動）
  - 提案を批判的に検証。所定の検証テーブル形式で出力
  - 承認ゲート表（純度/最小変更/安定性/ハング耐性/例外整合/後方互換）
  - Devil's Advocate（最悪シナリオ）＋副作用リスクTop3＋ロールバック条件
  - 総合判定: 承認 / 条件付き承認 / 却下

Phase 3: Implementation Patch（●３で発動）
  - 「●３．承認します」を受けてからのみコード生成
  - 出力形式: Change Manifest（CHANGELOG.md用マークダウンコードブロック）
    → unified diff → 完全版コードブロック → 最小テスト手順
```

### コード出力規約（絶対ルール）

- **省略・ellipsis・「以下同様」禁止**。関数・ブロックは必ず完全版を提示
- unified diff → 直後に対応する完全版コードブロック（diffのみは不合格）
- 変更前後の行数と差分を明記（必須）
- 挿入位置は「◯◯行の直後」「関数◯◯の直前」のように明示
- 100行超の出力は「Python編」「JS編」等に分割し「X/N: ○○編」と冒頭宣言
- スコープ外の「ついで修正」は一切禁止（一石一鳥の原則）
- 追加変更が必要になったら "Change Request" として提示し承認を待つ

### バージョニング規約

- ファイル名: `{tool}_YYYYMMDD_XX.py` または `YYYYMMDD_XX_XX`
- VERSIONは越智さんが指定する場合がある（指定されたらそれに従う）
- 却下されたVERSION番号は欠番にする（例: 20260620_01は却下・欠番）

### コミュニケーション上の注意

- 常に日本語。「越智さん」と呼ぶ。結論→項目→詳細の順
- 越智さんはプログラム初心者を自認しているが、**タイミング依存の曖昧なロジックを鋭く見抜く**。「それはタイミングで崩れないか？」という指摘が繰り返し的中してきた。設計段階で決定論的な解を出すこと
- 「どこを変えればいいのか」が伝わらないことが多発した。**行番号＋前後の文脈＋完全な置換ブロック**を必ずセットで示す
- パッチ手動適用のミスが頻発したため、**確実を期す場合は Claude 側でファイルに直接パッチを当てて完成ファイルを渡す**方式が有効だった（Claude Code では直接編集できるのでこの問題は解消されるはず）

---

## 3. ツール1: 統合ニュースダッシュボード 詳細

### アーキテクチャ

- Python（BeautifulSoup）が `Summary\summary_*.html` をパースして JSON 化 → 単一の巨大 HTML（`_Consolidated_Manager.html`）に埋め込んで出力
- 生成物はローカル `file://` で開く。**CORS制限があるためクラウド同期系は不可**（JSONBin.io同期は過去に実装→断念→全削除済み）
- 音声読み上げは Web Speech API（`speechSynthesis`）。「高音質」トグルでSiri系音声を選択

### Python側の主要関数

| 関数 | 役割 | 注意点 |
|---|---|---|
| `parse_youtube_card(card)` | `video-card` をパース | `channel-info` 内のspanを**色コードで識別**: 登録者数=`e53e3e`、動画時間=`2b6cb0`、お気に入り★=`d4a017`。span を `extract()` してから `get_text()` でチャンネル名取得 |
| `parse_rss_card(card)` | `thread-card` をパース | meta_div検索は `"flex-wrap:wrap" in s or "flex-wrap: wrap" in s`（**スペース両対応必須**）。概要セクションは sec-title に「概要」を含むsection→`sum-box`内のclassなし`<div>`群 |
| `extract_data()` | 全HTMLをパース→DBマージ→archive移動 | **summary_database.json にキャッシュされる。パーサー修正後は再パースされない**（下記落とし穴①） |

### item フィールド（flatQueue の item）

```
共通: is_error, type('youtube'|'rss'), title, summary, conclusion, points, keywords[], url
YouTube: thumbnail, channel, subscriber, duration, is_favorite
RSS: source, category, author, likes, char_count, outline[]
```

### JS側の主要構造

```javascript
// グローバル状態
let flatQueue = [];              // 読み上げ順の平坦キュー
let currentFlatIndex = -1;       // 現在位置
let currentPart = '';            // 'file_intro'|'title'|'summary'|'conclusion'|'points'
let isPlaying = false;
let skipMode = 0;                // 0:▶▶(要旨まで) 1:▶(ポイントも・1回) 2:▶固定(持続) 3:▶▶▶(タイトルのみ)
let isChimePlaying = false;      // チャイム再生中フラグ（cancel()抑止用）
let suppressNextHighlightScroll = false;

// flatQueueエントリ: { file, item, fIdx, iIdx, is_first, filename }
// ※filenameフィールドは必須（fIdxはfilteredData依存でズレるため）
```

### 読み上げフロー（20260708_01時点）

```
advanceAuto()
  → currentFlatIndex++
  → currentPart = is_first ? 'file_intro' : 'title'
  → applyAutoSkipMode()            ← カード種別でskipMode自動設定（最新機能）
  → is_first && isPlaying なら playChime(cb) → cb内で playCurrentPart()
  → それ以外は playCurrentPart()

playCurrentPart()
  → if (!isChimePlaying) speechSynthesis.cancel()   ← チャイム中はcancel禁止
  → file_intro: 初回「それでは、N件の…」/ 2件目以降「次に、summary_Xの、N件の…」
     （プレフィックス抽出: /^(summary_[^_]+(?:_[^_]+)*)_\d{8}_/ ）
  → title: 「{iIdx+1}番。 {title}」 / summary / points（全skipMode遷移はhandlePartEnd）

handlePartEnd()
  → file_intro: if(!isChimePlaying) で title へ（チャイム中は割り込み禁止）
  → summary: skipMode 1/2 なら openPointsAccordion() → points読み上げ / 0,3はadvanceAuto
  → points: advanceAuto()
※ conclusion は表示・読み上げとも廃止済み（DOMはdisplay:noneで残存）
```

### applyAutoSkipMode()（VERSION 20260708_01 で追加・最新）

```
優先順:
  skipMode===2（▶固定・手動）→ 何もしない（persist最優先）
  item.is_favorite===true      → skipMode=1
  /^summary_(V|BBT)_/          → skipMode=1
  /^summary_(Short|N)_/        → skipMode=3
  それ以外                      → skipMode=0
呼び出し: カード確定の全9箇所
  startPlayback / resumePlayback / skipToNextItem×2 / skipToPrevItem×2 /
  jumpToPrevFile / jumpToNextFile / advanceAuto
```

### スクロール設計（確定アーキテクチャ・変更禁止級）

- `updateHighlighting()` は**スクロール責務を持たない**
- スクロールは `scrollToCurrentItem(targetEl)` に完全委譲
- 非表示要素（showOnlySelected切替直後等）は **MutationObserver** でDOM確定を検知してからスクロール（3秒タイムアウト安全装置付き）
- `suppressNextHighlightScroll`: `scrollToFirstItemInFile`（手動展開用）でセット、`scrollToCurrentItem` 内で消費
- **教訓: setTimeout/rAFのタイマーベース解は全て失敗した。DOMイベント駆動（MutationObserver）が正解だった**

### チャイム仕様（確定）

- Web Audio API。660Hz→880Hzの上昇2音（各0.25秒、計0.6秒）
- `ctx.resume().then()` 必須（Autoplay Policy対策。t=ctx.currentTimeは**then内で取得**）
- `.catch()` 必須、`safetyTimer`（700ms）でonended非発火を救済
- `isChimePlaying` フラグで `playCurrentPart` の `cancel()` と `handlePartEnd` のfile_intro分岐を抑止

### UIカラー・強調ルール（確定）

| 対象 | 条件 | ボーダー | 背景 |
|---|---|---|---|
| 要旨/概要/ポイントタイトルの各エリア | RSS category==='Followed Note' または YouTube is_favorite===true | `#d4a017`（金） | `#fef9c3`（薄金） |
| 同上・通常 | — | `#3182ce`（青） | `#f8fafc`（白） |
| `📁 Followed Note` バッジ | — | — | `#d4a017`背景・白文字 |
| ★マーク | is_favorite | `color:#d4a017; font-size:1.0em; margin-right:4px;` | — |

※ file-card（HTMLサマリ全体カード）への金ボーダーは**誤実装として撤回済み**。強調は個々のアイテムエリア単位。

### インジケーター仕様（確定）

動画時間（YouTube）: `⬜⬜⬜⬜⬜`≤3分 / `🟩⬜⬜⬜⬜`≤15分 / `🟩🟩⬜⬜⬜`≤30分 / `🟩🟩🟩⬜⬜`≤45分 / `🟩🟩🟩🟩⬜`≤60分 / `🟩🟩🟩🟩🟩`>60分（`buildDurationIndicator`）
文字数（RSS）: 同5マスで ≤1000/≤3000/≤6000/≤9000/≤12000/超（`buildCharCountIndicator`。表示は数値のみ・カンマ「字」除去）

### Gemini API（「主なポイントを生成」ボタン）

- モデルリスト: `['gemini-2.5-flash', 'gemini-2.5-flash-lite']`（503/429でフォールバック）
- **廃止済みモデル（gemini-2.0-flash / 1.5-flash）は使用禁止**（Shut down済み）
- `tools: [{ url_context: {} }]` で記事URLを読ませる
- `generationConfig: { maxOutputTokens: 2048 }` 設定済み（英語長文でThinkingが暴走し[POINTS]タグに到達しない問題の対策）
- **レスポンスは全parts結合必須**: `(data?.candidates?.[0]?.content?.parts || []).map(p => p.text || '').join('\n')`
  （Thinkingモードで parts[0]=思考、parts[1]=実回答になるため。parts[0]のみ取得は既知バグ）
- 生成完了後: pointsArea更新 → `openPointsAccordion()` 自動展開 → `point-titles-div` は非表示化（重複解消）
- 設計判断: RSSは95%読み飛ばすためオンデマンド生成が正（全件バッチ生成はコスト20倍超）

---

## 4. ツール2: RSSオーガナイザー 詳細

### タブ構成

| タブ | 内容 | 取得方法 |
|---|---|---|
| Tab1 | キーワード検索（note/Zenn/Qiita） | RSS |
| Tab2 | フォロー中note.comユーザー | `followed_note_authors.txt` のURLリスト → RSS |
| Tab3 | AIフロンティア20ソース | `AI_FEED_URLS` 定数（**コード内ハードコード**・JSONではない） |

### noteフォロー同期（NoteFollowingSyncer）

- `-auto` バッチ実行時の Step 0 で自動同期（実装済み）
- **ページネーション方式**（`?page=N` を順に開く）。スクロール方式は失敗した（note.comはページネーション型）
- `seen_urlnames` セットで既出URL追跡 → 新規0件のページで終了（**このセットがないと無限ループする**・実証済み）
- 認証: Tab2「🔑 note認証設定」ボタン → urlname/email/パスワード（Windows keyring保存）/sync_mode
- sync_mode: `merge`（追記のみ・古い手動URLが残る）/ `full`（完全上書き・重複解消に有効）
- 既知の残課題: `followed_note_authors.txt` に `/rss` あり・なしの重複が残存（full同期で解消可能）

### note.com スクレイピングの鉄則

- `wait_until="networkidle"` は**使用禁止**（SPA常時通信で無限ハング or 即抜けする）
- 正解: `wait_for_load_state("load")` + `page.wait_for_timeout(2000〜3000)`
- `time.sleep()` より `page.wait_for_timeout()` を優先
- note非公式API `GET /api/v1/followings/{urlname}/list` は**404廃止済み**。スクレイピング一択

### Playwright の鉄則

- `sync_playwright()` は**メインスレッド外（サブスレッド・ThreadPoolExecutor）では動作不可**
- Flaskエンドポイント（`/summarize`・`/detail`）内で処理するアーキテクチャが正解

### Tab3（AIフィード）仕様

- 上限件数の明示設定なし。フィルタ: ①7日以内（`ARTICLE_DAYS_LIMIT=7`）②arXivのみ最新15件（`AI_FEED_ARXIV_MAX=15`）③`ai_feed_history.json` で既読除去（7日保持）
- `ai_feed_history.json` は URL→ISOタイムスタンプ辞書形式（旧URLリスト形式から移行済み）
- `parsedate_to_datetime` はISO 8601日付で失敗するケースあり → `datetime.now()` フォールバック実装済み

---

## 5. 落とし穴カタログ（実際にハマったバグ）

1. **summary_database.json キャッシュ**: パーサー（parse_rss_card等）を修正しても、既にarchive済みのHTMLは再パースされない。**「コードは正しいのに表示されない」時はまずDBキャッシュを疑う**。対処: DBファイル削除 or 対象HTMLをarchiveからSummaryフォルダに戻してbat再実行
2. **JSスコープエラーで全画面真っ白**: `renderFileList` の file ループ内で `item` を参照（未定義）→ JSエラーで描画全停止。「統合サマリーに何も表示されない」時はF12コンソール確認が第一手
3. **flex-wrapスペース問題**: HTML側の `flex-wrap: wrap`（スペースあり）とコード側の検索文字列 `flex-wrap:wrap` の不一致でmeta_div取得失敗 → source/likes等が全部空になった
4. **Thinkingモードのparts分割**: parts[0]のみ取得だと長文記事で[POINTS]タグを見逃す（短文は成功するため「時々失敗する」ように見える）
5. **channel-info の span 順序**: ★スパンが最初のspanになったため `find("span")` が★を掴む。色コード（style属性内の16進値）での識別が堅牢
6. **speechSynthesis.cancel() の割り込み**: チャイムcallback内のspeak()や自動進行を殺す。isChimePlayingフラグ＋条件付きcancelで解決
7. **AudioContext Autoplay Policy**: resume()なしだとチャイムが「鳴ったり鳴らなかったり」する
8. **「18番」誤読**: Web Speech APIが「十八番=おはこ」等と誤読・非決定的（3回に2回「はちばん」）。**未解決・保留中**
9. **タイトル番号とqData.iIdx**: ソート順変更でタイトル内番号とカード並び順は一致しない
10. **パッチ適用の積み忘れ**: 複数バージョンにまたがるパッチで、前の修正が後のベースに含まれず退行（★表示消失・真っ白化を実際に起こした）。**Claude Codeでは編集前に必ず該当箇所をReadして現状確認すること**

---

## 6. 保留中・未解決の課題

| # | 課題 | 状態 |
|---|---|---|
| 1 | 「18番」→「おはこ/はちばん」誤読 | 保留。音声エンジンの非決定動作。読点挿入/漢数字化等の案は出たが未採用 |
| 2 | タイトル→要旨の無音間隔の短縮 | 保留。原因は playCurrentPart 冒頭の cancel()。isAutoAdvance引数案は条件付き承認済みだが「今は放置」指示 |
| 3 | followed_note_authors.txt の重複（/rssあり・なし） | sync_mode=full での手動同期で解消可能。越智さんの操作待ち |
| 4 | OneNote Report Generator batのパスエラー | 保留（別ツール） |
| 5 | AI_FEED_URLS の外部JSON化（GUI管理） | 提案済み・未着手 |
| 6 | 20260708_01（applyAutoSkipMode）の動作検証 | パッチ提示済み。越智さんのテスト結果待ちの可能性あり。Step1〜6のテスト手順参照 |

---

## 7. UI規約（userPreferences由来）

- ダークテーマ指定あり: bg `#1a1a2e` / accent `#e94560`（※統合ダッシュボードは既存ライトテーマを維持中。新規UI作成時に適用検討）
- 絵文字はUnicode直書き（f-string外のJS文字列で定義）
- ログ出力: 日本語＋絵文字ステータス（✅❌🔄📋等）
- YouTubeツールの変更禁止コンポーネント: `check_states`・`save_changes`・`update_display`・`channel_metadata`・`original_data`・ソート/ページングロジック

---

## 8. Claude Code での作業開始チェックリスト

1. 本ファイル（CLAUDE.md）をプロジェクトルートに配置
2. 最新ファイルの確認: `consolidated_html_summary_manager_20260708_01.py` が最新か越智さんに確認（20260708_01パッチが手動適用済みかどうか要確認）
3. 変更前に必ず該当関数をReadし、想定バージョンのコードと一致するか確認（パッチ積み忘れ検出）
4. 3フェーズワークフローを厳守（●２/●３の承認キーワードを待つ）
5. 修正後は必ず: `python -c "import ast; ast.parse(open('file.py', encoding='utf-8').read())"` 相当の構文チェック
6. テスト手順は「bat実行コマンド＋期待ログ＋手動確認Step」の形式で提示
