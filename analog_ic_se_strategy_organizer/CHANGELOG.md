# CHANGELOG — analog_ic_se_strategy_organizer

このフォルダ内の変更履歴。バージョンアップ時は旧ファイルを残したまま新ファイルを追加し、ここに変更点を追記する。

## [実機検証完了] - 2026-08-12

**背景:** これまでの`../common/gemini_client.py`経由への移行（下記「Gemini呼び出し共通化」）は
モック応答での検証にとどまっていたが、越智さんの実環境（会社PC＋自宅PCプロキシ構成）で
実際のGemini API呼び出しを確認した。

**検証内容:** コード変更なし。ドキュメントのみ更新。

- 会社PCから「ステージ0のみ実行」（型番`TPS62840`）を実行し、以下の一連の流れを実機で確認
  1. 会社PCからのGemini API直接呼び出しが実際にSSLハンドシェイクエラーで失敗すること
     （会社PCでの遮断が現実に発生していることの確認）
  2. 失敗後、自動的に自宅PCプロキシ（`GEMINI_PROXY_URL`＝ngrok経由）へフォールバックすること
  3. 自宅PC側`home_pc_server_v2.py`の`/generate`エンドポイントが、`GEMINI_API_KEY`を使って
     実際にGemini API（`google_search`グラウンディング使用）を呼び出し、正常なレスポンスを返すこと
  4. 返ってきた結果でステージ0（製品登録、カテゴリ自動判定）が正常完了すること（`TPS62840`→`DC-DC / PMIC`）
- これにより、`GEMINI_COMMON_DIR`対応・`generate_advanced`のmodel引数伝播を含め、
  Gemini呼び出し共通化の一連の変更がすべて実環境で機能することを確認した
- **未検証のまま残る事項**: 製品ディープダイブ（5ステージ全体）・JSONモード（`responseSchema`指定）の
  実機確認、ディープモード（`gemini-2.5-pro`）での実機確認、`rtocs_organizer`側の実機確認

## [GEMINI_COMMON_DIR対応] - 2026-08-11（同日追加修正）

**背景:** 越智さんの実際のローカル環境では、`rtocs_organizer`（`bbt\RTOCS_organizer`で管理）と
`analog_ic_se_strategy_organizer`（`SE_Strategy\analog_ic_se_strategy_organizer`で管理）の
管理フォルダがバラバラで、gitリポジトリのような「commonフォルダが1つ上の階層にある」構成に
なっていないことが判明。相対パス（`../common`）だけに頼ると`ModuleNotFoundError`になるため、
環境変数で明示的に指定できるようにした。

**変更ファイル:** `ic_engine.py`

- `common/gemini_client.py`の探索先を、環境変数`GEMINI_COMMON_DIR`があればそちらを優先、
  無ければ従来通り「1つ上の階層のcommonフォルダ」にフォールバックするよう変更
- 越智さんはローカルの`gemini_client.py`配置場所を1箇所に決め、`GEMINI_COMMON_DIR`で
  全ツールから同じ場所を指すよう設定すればよい
- **動作検証**: `GEMINI_COMMON_DIR`未設定時は従来通り相対パスでimportできること、設定時は
  そちらが優先されて別ディレクトリの`gemini_client.py`を読み込むことの両方を確認

## [Gemini呼び出し共通化] - 2026-08-11

**背景:** 会社PC上でGemini APIへの直接アクセスが遮断される事象が発生（2026-08-10頃、原因未確定）。
業務停止を避けるため、自宅PC経由のプロキシへ自動フォールバックする共通クライアント
（`../common/gemini_client.py`、submodule `ochi1216/gemini-common-tools`）を導入し、本ツールの
Gemini呼び出しをすべてこちらに置き換えた。詳細は`common/GEMINI_MIGRATION_HANDOVER.md`参照。

**変更ファイル:** `ic_engine.py`, `requirements.txt`（`analog_ic_se_strategy_organizer_*.py`本体・
`ic_prompts.py`・`ic_schema.py`・`ic_report.py`・`ic_index.py`は無変更）

- `GeminiClient`の内部実装を、`google-generativeai`/`google-genai` SDKの直接呼び出しから
  `../common/gemini_client.py`の`generate_advanced(payload, model=...)`経由に置き換え
  （`sys.path`に`../common`を追加してimport）
- JSONモード・Google Search Groundingのペイロード組み立て（`generationConfig.responseMimeType`、
  `tools:[{"google_search":{}}]`）、コードフェンス除去＋`json.loads`によるレスポンス解析ロジックは
  変更なし（SDKオブジェクトの代わりに生JSON dictを扱うよう`_add_cost`/テキスト抽出のみ調整）
- ディープモード（`gemini-2.5-pro`）は`generate_advanced`に`model=self.model_name`を明示的に渡すことで
  維持。当初`generate_advanced`にモデル指定機能が無く「ディープモードを選んでも常にflashが呼ばれる」
  サイレントバグになる問題を発見・指摘し、共通クライアント側に`model`引数を追加してもらってから移行した
- `requirements.txt`から`google-generativeai`/`google-genai`を削除（本ツールでは直接使用箇所が無くなったため）
- **動作検証**: モックで`generate_advanced`をすり替え、`model`引数が正しく`gemini-2.5-pro`/`flash`を
  伝播すること、JSONモード/grounding使い分けが維持されていることを確認。Streamlit 3タブもエラー無く
  起動することを確認（実際のGemini API呼び出しは`GEMINI_API_KEY`/`GEMINI_PROXY_URL`が無いこの開発環境では
  未検証。越智さんの環境での実機確認が必要）

## [20260718_02] - 2026-07-18

**背景:** MECE改善の優先度3「ロードマップビュー」に着手。単一製品の分析だけでなく、カテゴリ単位で
「次に着手すべきか」を判断できる俯瞰情報を追加した。

**追加ファイル:** `analog_ic_se_strategy_organizer_20260718_02.py`（`_20260718_01`からのコピー＋機能追加。旧版はそのまま残置）

**変更ファイル:** `ic_index.py`

1. **`ic_index.roadmap_priorities()`を追加**: 優先度1で実装した`ic_schema.whitespace_analysis()`
   （市場全体の手薄さ）に、自社の現状ポジション（none/limited/primaryで重み付け。未参入ほど
   優先度を上げる）と、`product_lake`に蓄積された分析済み製品の直近性（そのカテゴリを最後にいつ
   深掘りしたか）を組み合わせ、「ロードマップ優先度」としてカテゴリをランキングする。
   LLM呼び出しは行わず既存データの集計のみで完結する（コスト0）
2. 📊ポートフォリオ俯瞰タブに「🗺️ ロードマップビュー」セクションを新設:
   - 「次に着手すべきカテゴリ」テーブル（ロードマップ優先度・手薄度・自社の現状・分析済み件数・
     直近の分析日・直近の型番）。分析済み製品が0件でも表示できる（未分析カテゴリが可視化される）
   - 分析済み製品がある場合は、カテゴリ別の解析日時×最優先提案（優先度で色分け）の時系列散布図も表示

**明示的なスコープ外（今回は含めない）:** 「TIの推定リフレッシュ周期」のような競合の開発動向シグナルは
含まれていない。これには特許出願・学会発表等の新しいデータソースを扱う別ステージ（MECE改善項目
D: 技術トレンド・特許シグナル分析、未実装）が必要なため、今回のロードマップ優先度はあくまで
「市場の手薄さ×自社の現在地×自社の分析済みの鮮度」という自社データのみに基づく一次的な指標。

**動作検証:** `roadmap_priorities()`の単体テストで、自社が「none」のカテゴリ（AC-DC/LDO）が
生スコアはより高い「アイデアルダイオード/ORing」（自社は既にprimary）より優先順位で上位に来る
ことを確認。分析済み製品なし／あり両方の状態でStreamlit起動＋Playwrightで画面確認（時系列散布図の
色分け・ホバー情報も含め正常表示を確認）。

## [20260718_01] - 2026-07-18

**背景:** MECE改善の優先度2「自社データの権威化＋自社を競合比較に必ず含める」に着手。実装方針を
説明したところ、越智さんから「各デバイスがバラバラにリストアップされていて見づらい。1テーブルで、
どのような製品を企画すればTI含む他のコンペを打ち負かせるか、Nexperia提案が一目でわかる構造にしてほしい」
という具体的な要望があり、レポートのUI構造そのものを作り直した。

**追加ファイル:** `analog_ic_se_strategy_organizer_20260718_01.py`（`_20260717_02`からのコピー＋修正。旧版はそのまま残置）

**変更ファイル:** `ic_engine.py`, `ic_prompts.py`, `ic_report.py`

1. **自社(Nexperia)を競合IC比較に必ず含める**（`ic_engine.py`）: ステージ3で選定した企業リストに
   `config/own_company.json`の自社が含まれていなければ強制的に追加する。自社がそのカテゴリで
   `competitors_db.json`上「none」（現行製品なし）の場合は、ハルシネーション防止のため無理に検索させず
   `"no_current_product": true`として明示するのみに留める
2. **ベンチマーク対象(TI)の重複比較を修正**（`ic_schema.py`）: `load_competitors()`/
   `pick_regional_representatives()`に`exclude_names`引数を追加し、TI自身が「競合」プールから
   選ばれて「TI vs TI」の比較行ができてしまう不具合を修正（実装中の単体テストで発覚）
3. **ステージ4の主語をTIから自社(Nexperia)に転換**（`ic_prompts.py`のSTAGE4_NEXT_GEN）:
   「TIが次に開発すべき」ではなく「自社がTI・全競合を上回るために開発すべき」スペックを提案するよう
   プロンプトを書き換え。各提案の`parameter_key`をcategory_schemaの実キーに正規化し
   （自由記述の`kpi`から変更）、比較表の行と機械的に突合できるようにした
4. **HTMLレポートを1つの統合比較表に再構成**（`ic_report.py`）: 従来「企業ごとのカードがバラバラに
   並ぶ」構造だったステージ3(競合IC比較)とステージ4(次世代スペック提案)を1つのセクションに統合し、
   パラメータ行×企業列（TI／各競合企業／自社(現行)／🏆自社提案(次世代・強調表示)）の1テーブルにした。
   検索失敗企業は列から除外し注記のみ、自社に現行品が無い場合は「未参入」列として表示する
5. ダッシュボードの🎯製品ディープダイブタブ結果表示で、廃止した`"kpi"`キー参照が残っていたバグ
   （`parameter_key`/`kpi_label`への変更に追随していなかった）を修正

**動作検証:** モックのGeminiClientで2ケース（自社が該当カテゴリでprimary＝現行品あり／none＝未参入）を
再現し、統合比較表・自社提案列の強調表示・検索失敗企業の除外・横スクロールでの提案列到達をPlaywrightで
画面確認。ダッシュボード3タブもエラー無く表示されることを確認。

## [20260717_02] - 2026-07-17

**背景:** 越智さんより、本ツールは「TIのシニアシステムエンジニアがTIの将来を考える」ものではなく、
「Nexperiaのシニアシステムエンジニアが、TIをベンチマーク対象として打ち負かすデバイスを企画する」ための
ものだという重要な視点の是正があった。これを受けてMECEに改善点を洗い出し（詳細は
`DESIGN_analog_ic_se_strategy_organizer.md` 14章）、優先度1番から順に着手することにした。

**追加ファイル:**
- `config/own_company.json` — 自社(Nexperia)とベンチマーク対象(TI)を明示する設定ファイル。今後のステップ
  （自社データの権威化、競合比較への自社必須組み込み等）でも再利用する土台
- `analog_ic_se_strategy_organizer_20260717_02.py`（`_20260717_01`からのコピー＋機能追加。旧版はそのまま残置）

**改善内容（優先度1: ホワイトスペース分析、LLM呼び出し不要・追加コスト0）:**
- `ic_schema.py`に`load_own_company()`/`own_company_name()`/`find_company()`/`whitespace_analysis()`を追加。
  `competitors_db.json`の集計のみで、カテゴリ別の「手薄度」（主要/限定企業の少なさ）・車載クロスの手薄度・
  最も手薄な地域・自社(Nexperia)の現状ポジションを算出する
- 📊ポートフォリオ俯瞰タブに「🕳️ ホワイトスペース分析」セクションを新設。手薄度グラフ・テーブルに加え、
  「自社未参入×市場全体も手薄→新規参入候補」「自社は既に主要プレイヤー×市場全体は手薄→独走候補」等の
  優先度ラベルを自動生成して表示する
- 動作検証: `whitespace_analysis()`の算出結果をExcel原本由来のNexperiaの実データと突合し一致を確認。
  Streamlitを実際に起動しPlaywrightで画面表示を確認（アイデアルダイオード/ORingが最も手薄度が高く
  Excel Summaryシートの数値と整合することを確認）

## [20260717_01] - 2026-07-17

**追加ファイル:** `analog_ic_se_strategy_organizer_20260717_01.py`（`_20260716_01`からのコピー＋バグ修正。旧版はそのまま残置。`run_dashboard.bat`は自動的にこちらを選ぶため変更不要）

越智さんの実機検証で判明したバグ修正:

- 📊ポートフォリオ俯瞰タブの「競合ギャップが大きい製品ランキング」で、登録済み製品に競合IC比較データが1件も無い場合（「ステージ0のみ実行」で登録した製品のみの状態など）に `KeyError: '競合優位点の総数'` で画面がクラッシュする不具合を修正
  - 原因: `pd.DataFrame(gap_rows)` が空リストから作られると列を持たないDataFrameになり、その状態で`.sort_values("競合優位点の総数", ...)`を呼ぶと存在しない列への参照でKeyErrorになる。空チェック（`if not gap_df.empty`）を`sort_values`の**後**に置いていたため間に合っていなかった
  - 対応: `pd.DataFrame(gap_rows)`生成後、空チェックを行ってから`sort_values`を呼ぶ順序に修正。ファイル内の他の同種箇所（`region_df`/`cat_df`/`cat_count_df`/`pr_df`）は元々正しい順序だったため対象外
  - 案内メッセージも改善し、「ステージ0のみ実行の製品は対象外」であることを明記

## [起動スクリプト追加] - 2026-07-16

**追加ファイル:** `run_dashboard.bat`

Windows用の起動バッチファイル。`analog_ic_se_strategy_organizer_YYYYMMDD_NN.py`のうち
ファイル名（日付・連番）が最も新しいものを`dir /b /o-n`で自動選出して起動するため、
バージョンアップでファイル名が変わってもこのバッチファイル自体は書き換え不要。
コード本体・`requirements.txt`と同じフォルダに置いて使う（バッチファイル自体は日付連番の
バージョン管理対象外とする。常に最新版を指す「固定名の起動口」という役割のため）。

**修正（同日）:** 初版は日本語コメント＋`chcp 65001`を入れていたが、越智さんの環境で
文字コード（Shift-JIS想定の環境でUTF-8のバッチファイルを読み込んだ際の文字化け）により
コマンドが誤認識され、`'y_organizer' は、内部コマンドまたは外部コマンド...`のようなエラーで
起動できない不具合が発生した。`chcp`に頼らず、バッチファイル内の文字をすべて英数字(ASCII)に
書き換えて解消（コメント・メッセージを英語化。動作には影響しない）。

## [20260716_01] - 2026-07-16

`DESIGN_analog_ic_se_strategy_organizer.md` に基づき、パイプライン本体とStreamlitダッシュボードを実装した初版。

**追加ファイル:**
- `ic_schema.py` — fact構造ヘルパー（`make_fact`/`normalize_fact`）、`category_schema.json`/`competitors_db.json`のローダー、カテゴリ解決（9カテゴリ以外は`generic_analog_ic`にフォールバック）、地域代表企業選定（`pick_regional_representatives`）、競合DBサマリー（`competitors_summary`）
- `ic_index.py` — `data/product_lake/*.json`（1製品=1ファイル）から`data/ic_index.json`を増分構築（`rtocs_index.py`と同型）。`save_product_case`でパイプライン結果を保存
- `ic_prompts.py` — 5ステージ分のGeminiプロンプト（fact構造での出力を指示）＋ポートフォリオ俯瞰タブ用のAI総評プロンプト
- `ic_engine.py` — `GeminiClient`（JSONモード＋Google Search Grounding、`google-genai`使用）と`IcPipeline`（5ステージ: 製品取り込み→市場分析→キーカスタマー推定→競合IC比較→次世代スペック提案。各ステージ失敗しても継続する部分レポート方針）
- `ic_report.py` — 自己完結HTMLレポート生成（fact構造は出典・確度バッジ付きで描画）
- `analog_ic_se_strategy_organizer_20260716_01.py` — Streamlit 3タブダッシュボード（📦製品登録・検索／📊ポートフォリオ俯瞰／🎯製品ディープダイブ）

**動作検証:**
- `ic_schema.py`/`ic_index.py`: 単体テストで増分構築・fact構造正規化・カテゴリフォールバックを確認
- `ic_engine.py`/`ic_report.py`: `GeminiClient`をモックした一気通貫パイプラインで、ステージ間のデータ受け渡し・HTMLレポート生成（Playwrightでスクリーンショット確認）を確認
- ダッシュボード3タブ: `streamlit run`で起動し、Playwrightで実画面を確認（3タブとも正常表示、チャート描画も確認）
- **未検証**: 実際のGemini API呼び出し（`GEMINI_API_KEY`未設定、かつこの開発環境では`google-generativeai`の依存関係(`cryptography`のRustバインディング)が壊れており動作確認不可）。`GEMINI_API_KEY`を設定した環境で`pip install -r requirements.txt`後に実際のTI型番で動作確認することを推奨する
- **未検証**: grounded searchでデータシートの数値項目をどこまで正確に拾えるか（`DESIGN_analog_ic_se_strategy_organizer.md` 11章の要検証事項1）。実データでの検証が必要

## [構想・詳細設計段階] - 2026-07-16

このツールはまだパイプライン本体（`ic_index.py` / `ic_schema.py` / `ic_prompts.py` / `ic_engine.py` / `ic_report.py` / Streamlitダッシュボード）を実装していない。今回のセッションでは以下のみを作成した。詳細設計は [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md)（リポジトリルート）を参照。

**追加ファイル:**
- `config/source_data/analog_power_semiconductor_companies_global_2026.xlsx` — 越智さんが調査した競合企業一覧（米欧日亜、67社）の原本
- `config/category_schema.json` — 上記Excelの9製品カテゴリ（DC-DC/PMIC, LDO, LEDドライバー, AC-DC, ゲートドライバー, ロードスイッチ/eFuse, アイデアルダイオード/ORing, GaNパワーIC/デバイス, パワーディスクリート/モジュール）ごとの比較パラメータ定義
- `config/competitors_db.json` — 上記Excelを`ic_competitor_import.py`で変換した競合企業データベース（67社）
- `ic_competitor_import.py` — Excel→competitors_db.jsonの変換スクリプト。Excel更新時はこれを再実行するだけでよい
- `requirements.txt` — 将来のパイプライン実装を見越した依存パッケージ一覧（現時点で実際に使用しているのは`openpyxl`のみ）

**次にやること（次セッション）:** [`/DESIGN_analog_ic_se_strategy_organizer.md`](../DESIGN_analog_ic_se_strategy_organizer.md) の「後続実装セッションへの実装順序」節を参照。
