# 詳細設計・実装記録: analog_ic_se_strategy_organizer

**作成日**: 2026-07-16（同日中に詳細設計→実装まで実施）
**引継ぎ元**: Claude Code（`HANDOVER_analog_ic_scout.md` の後続セッション）
**引継ぎ先**: Claude Code（実機検証セッション。10章参照）
**対象者**: 越智さん（アナログ半導体のシニアシステムエンジニア）

**このドキュメントの位置づけ**: 元々は「詳細設計のみ」を目的に作成したが、同一セッション内で越智さんから「これらをベースに実装を開始してほしい」との指示があり、パイプライン本体・ダッシュボードまで実装した。そのため本文中には設計時点の記述と実装後の更新が混在している（各章に実装状況を注記）。

---

## 1. 背景・経緯

前セッション（`rtocs_organizer` 開発時）で、越智さんから「TIのアナログ製品を型番1つから市場分析・キーカスタマー推定・競合IC比較・次世代スペック提案まで一気通貫でまとめるツール」の構想相談があり、`HANDOVER_analog_ic_scout.md` に構想レベルの引継ぎ資料としてまとめた（実装は未着手、構想・設計のみ）。

今回のセッションはその「詳細設計フェーズ」にあたる。セッション開始時に以下を実施・確認した。

1. **リモートとの差分確認**: `git fetch origin` 実施済み。作業ブランチはリモートと完全一致（差分なし）で作業開始した。
2. **TI公式サイトへの直接アクセス検証**: この実行環境からTIの製品ページ・データシートPDF直リンク・トップページを試したところ、いずれも403 Forbidden（プロキシの中継失敗ログはなし＝TI側のBOT対策と判断）。
3. この結果を踏まえ、越智さんと以下の方針を確認・決定した。

### 確定事項

| 論点 | 決定内容 |
|---|---|
| ツール正式名称・フォルダ名 | `analog_ic_se_strategy_organizer`（`analog_ic_scout`という仮称から変更） |
| バージョン管理ファイル名規則 | ルートREADMEの規則通り `analog_ic_se_strategy_organizer_YYYYMMDD_NN.py`（Streamlitダッシュボード本体に適用） |
| ステージ0（製品取り込み）の方式 | TI公式サイトへの直接HTTPアクセスは403で不可と判明したため不採用。**Gemini検索グラウンディング**（`rtocs_organizer/strategy_engine.py`の`generate_grounded_json`と同じ`google-genai`のgoogle_searchツール方式）で`site:ti.com {型番}`等のクエリを投げ、TI公式情報を検索・要約する方式に統一する |
| 競合メーカーリスト（ステージ3） | 当初は「地域横断の固定デフォルトリストを越智さんが手動でJSON追記する」想定だったが、越智さんが実際に**Excelで67社の競合企業データを作成済み**だったため方針を更新（詳細は6章）。Excelをマスターデータとし、**変換スクリプトで`config/competitors_db.json`を生成**する方式に変更した（JSONを手編集する必要をなくす） |
| キーカスタマー調査 | 非公開情報は扱わず、特許引用・公開テカルダウン記事・TI公表事例など公開情報のみからの「推定」に限定する |

### 追加インプット: 越智さん提供の競合企業Excel

セッション中に越智さんから `analog_power_semiconductor_companies_global_2026.xlsx` が提供され、「内容を分析して適切なデータベースにしてほしい」と依頼された。中身を確認したところ想定より大幅に充実したデータだった。

- **シート構成**: `Summary`（集計）／`US`(18社)／`Europe`(14社)／`Japan`(12社)／`Asia`(23社、台湾・中国・韓国)／`Methodology`（調査方法・判定基準） — 計67社
- **各社の列（22列）**: 地域／国・地域／企業名／親会社・ブランド状況／カンパニーURL／公式製品URL／企業タイプ／車載対応／**9つの製品カテゴリ**(DC-DC・PMIC／LDO／LEDドライバー／AC-DC／ゲートドライバー／ロードスイッチ・eFuse／アイデアルダイオード・ORing／GaNパワーIC・デバイス／パワーディスクリート・モジュール)の●(主要)/△(限定)/—(確認できず)判定／製品群幅スコア(●=1点,△=0.5点の合算)／製品群概要／市場での位置づけ／確認ソースURL／確認日(2026-07-16)
- **重要な発見**: 越智さんの実際の競合ウォッチ対象は「電源IC・パワー半導体」を中心とした9カテゴリであり、当初例示的に検討していた「オペアンプ／DC-DCコンバータ」という当て推量のカテゴリ分けとはズレがあった。**カテゴリスキーマはこの実データに基づいて設計し直した**（5章参照）。
- `Methodology`シートには「●/△/—の判定基準」「地域分類基準」「買収・ブランド統合の扱い（Maxim/Linear→ADI 等）」「情報時点の注記（個別品番は要再確認）」が明記されており、これは後述のfact構造（`source_type`/`confidence`/`as_of`）とほぼ同じ思想。この注意書きはそのまま`competitors_db.json`のメタデータ（`legend`）として保持している。

このExcelを`config/source_data/`に原本保存し、`ic_competitor_import.py`で`config/competitors_db.json`（67社）に変換済み。`config/category_schema.json`（9カテゴリの比較パラメータ定義）も作成済み。**これらは設計の空論ではなく、今回のセッションで実際に作成・検証したファイルである**（詳細は5〜7章、および同フォルダの`README.md`/`CHANGELOG.md`）。

---

## 2. フォルダ・ファイル構成

```
analog_ic_se_strategy_organizer/
  ic_index.py                                    # 製品ケースライブラリの増分インデックス構築（rtocs_index.pyと同型）【実装済み】
  ic_schema.py                                    # config読み込み・fact構造ヘルパー・カテゴリ解決【実装済み】
  ic_prompts.py                                   # 5ステージ分＋ポートフォリオ俯瞰用のGeminiプロンプト定数【実装済み】
  ic_engine.py                                    # GeminiClient（JSON/grounding）＋ IcPipeline本体【実装済み】
  ic_report.py                                    # HTMLレポート生成【実装済み】
  ic_competitor_import.py                         # Excel(4地域シート)→config/competitors_db.jsonの変換スクリプト【実装済み】
  analog_ic_se_strategy_organizer_20260716_01.py  # Streamlit本体（3タブ）【実装済み】
  config/
    category_schema.json                          # カテゴリ→比較パラメータ一覧（9カテゴリ）【実装済み】
    competitors_db.json                            # ic_competitor_import.pyの生成物（67社）【実装済み】
    source_data/
      analog_power_semiconductor_companies_global_2026.xlsx  # 越智さん提供Excelの原本【保存済み】
  data/                                            # 実行時生成（product_lake/, ic_index.json, ic_reports/ 等）。gitには含めない
  requirements.txt, CHANGELOG.md, README.md         # 【実装済み】
```

初版実装が完了し、パイプラインの制御ロジック・HTMLレポート生成・Streamlitダッシュボード3タブはモック応答とPlaywrightでの画面確認により動作検証済み。**ただし実際のGemini API呼び出しでの検証は未実施**（開発環境に`GEMINI_API_KEY`が無く、`google-generativeai`の依存関係も壊れていたため）。詳細は`CHANGELOG.md`と11章を参照。

---

## 3. 事実確度構造（fact構造）

rtocs_organizerの単純な「(要確認)」注記より一段厳格にするため、ステージ0〜4が返す事実値は以下の構造で持たせる。

```json
{
  "value": "実際の値（数値/文字列/配列/真偽値）",
  "unit": "V",
  "source_type": "TI_official",
  "source_detail": "TI datasheet SLVSxxx Rev.C (2024-11)",
  "source_url": "https://www.ti.com/lit/ds/symlink/xxxx.pdf",
  "confidence": "high",
  "as_of": "2026-07-16",
  "note": ""
}
```

- `source_type`: `"TI_official"`（データシート/アプリケーションノート/TI公式発表）／`"third_party"`（Yole・TechInsights・Omdia・特許・テカルダウン記事等の公開二次情報）／`"llm_estimate"`（検索グラウンディング未使用のLLM知識のみの推定）／`"user_input"`（越智さんによる手動補正）の4値クローズドセット。
- `confidence`: `"high"`（一次情報を直接確認）／`"medium"`（複数の二次情報が一致）／`"low"`（単一ソースまたはLLM推定のみ）の3段階。
- `as_of`: 取得・確認日（データシートは改訂されるため鮮度管理に必須）。
- `ic_schema.py`に`make_fact(value, source_type, confidence, unit=None, source_detail="", source_url="", as_of=None, note="")`ヘルパーを実装済み。不正な`source_type`/`confidence`は自動的に`confidence="low"`へフォールバックする。`normalize_fact()`でLLM出力（dict想定）を安全なfact構造に正規化する。

`competitors_db.json`（6章）は会社単位で1つの`source_url`/`verified_at`しか持たない簡略版だが、同じ思想（出典と確度・鮮度を必ず併記する）を踏襲している。

---

## 4. 製品ケースライブラリのJSON構造

rtocs_organizerの`metadata`/`classifiers`/`content`の3層構造を踏襲する（`data/product_lake/{part_number}_{yyyymmdd_HHMMSS}.json`、1製品=1ファイル）。

```json
{
  "metadata": {
    "part_number": "TPS62840",
    "manufacturer": "Texas Instruments",
    "analyzed_at": "2026-07-16T10:00:00",
    "pipeline_mode": "flash",
    "schema_version": 1,
    "stage_status": {
      "stage0_product": "done",
      "stage1_market": "done",
      "stage2_key_customers": "error",
      "stage3_competitors": "done",
      "stage4_next_gen": "done"
    }
  },
  "classifiers": {
    "category": "dc_dc_pmic",
    "category_confirmed_by_user": false,
    "applications_short": ["Battery-powered IoT", "Industrial sensors"],
    "regions_covered": ["US", "Europe", "Japan", "Asia"],
    "top_priority_kpi": "静止電流(Iq)の低減"
  },
  "content": {
    "stage0_product": { "...": "8.1参照" },
    "stage1_market": { "...": "8.2参照" },
    "stage2_key_customers": { "...": "8.3参照" },
    "stage3_competitors": { "...": "8.4参照" },
    "stage4_next_gen_proposal": { "...": "8.5参照" }
  },
  "costs": {
    "stages_jpy": {"stage0_product": 3.2, "stage1_market": 5.1},
    "total_usd": 0.021,
    "total_jpy": 3.4
  }
}
```

`classifiers`が`ic_index.py`のコンパクトレコード生成元（`rtocs_index.py`の`_record_from_json`に相当）、`content`がフル参照先（`load_full_case()`に相当）になる。`classifiers.category`は5章の9カテゴリキーのいずれかを取る。

---

## 5. カテゴリ別パラメトリックスキーマ（実データ準拠、`config/category_schema.json`）

越智さん提供Excelの9つの製品カテゴリ列をそのままカテゴリキーとして採用した（オペアンプ等の当て推量カテゴリは廃止）。各カテゴリごとにデータシートで実際に比較される項目を定義している。以下は代表2カテゴリの抜粋（全カテゴリの完全な定義は `analog_ic_se_strategy_organizer/config/category_schema.json` を参照）。

**`dc_dc_pmic`（DC-DC / PMIC）**: topology, input_voltage_range(V), output_voltage_range(V), num_outputs(ch), max_output_current(A), peak_efficiency(%), switching_frequency(MHz), quiescent_current(µA), control_scheme, integrated_fet(bool), protection_features(list), package, temp_grade, aec_q100(bool), price_1ku_usd

**`ldo`（LDO）**: input_voltage_range(V), output_voltage_range(V), dropout_voltage(mV), max_output_current(mA), quiescent_current(µA), psrr(dB), output_noise(µVrms), output_accuracy(%), package, temp_grade, aec_q100(bool), price_1ku_usd

残り7カテゴリ（`led_driver`, `ac_dc`, `gate_driver`, `load_switch_efuse`, `ideal_diode_oring`, `gan_power`, `power_discrete_module`）も同様に、各カテゴリの実務的な比較パラメータ（例: `gate_driver`なら絶縁方式・絶縁耐圧・伝搬遅延、`gan_power`ならRds(on)・耐圧・ゲート電荷）を定義済み。`type`は`"number"|"int"|"range"|"string"|"bool"|"list"`のクローズドセットで、`ic_report.py`（未実装）のテーブル描画・バリデーションで分岐に使う想定。

`automotive_capable`（車載対応）は製品カテゴリではなく横断的な属性として`cross_cutting_attributes`に別枠で持たせている（`primary`/`limited`/`none`の3値、`competitors_db.json`の同名フィールドと揃えている）。

---

## 6. 競合企業データベース（`config/competitors_db.json`、実装済み）

越智さん提供Excel（67社）を`ic_competitor_import.py`で変換した実データ。スキーマ:

```json
{
  "generated_at": "2026-07-16T13:59:00",
  "source_file": "analog_power_semiconductor_companies_global_2026.xlsx",
  "as_of": "2026-07-16",
  "legend": {
    "primary": "●: 公式カタログで独立した製品カテゴリ・複数シリーズ・主要戦略製品として明確に確認できる",
    "limited": "△: 製品数が限定・特定用途への統合・モジュール／リファレンス中心",
    "none": "—: 公式公開カタログでは明確な独立製品群を確認できず（技術的に不可能という意味ではない）"
  },
  "categories": ["dc_dc_pmic", "ldo", "led_driver", "ac_dc", "gate_driver",
                 "load_switch_efuse", "ideal_diode_oring", "gan_power", "power_discrete_module"],
  "companies": [
    {
      "name": "Texas Instruments", "region": "US", "country": "米国",
      "parent_or_brand_status": "独立企業",
      "company_url": "https://www.ti.com/",
      "product_url": "https://www.ti.com/power-management/overview.html",
      "company_type": "総合アナログ／電源IC大手",
      "automotive_capable": "primary",
      "categories": {"dc_dc_pmic": "primary", "ldo": "primary", "led_driver": "primary",
                     "ac_dc": "primary", "gate_driver": "primary", "load_switch_efuse": "primary",
                     "ideal_diode_oring": "primary", "gan_power": "primary", "power_discrete_module": "limited"},
      "breadth_score": 8.5,
      "product_overview": "Buck/Boost、PMIC、LDO、車載・照明LED、PFC/フライバック等AC-DC、...",
      "market_positioning": "製品幅、評価環境、アプリケーション支援が最大級。...",
      "source_url": "https://www.ti.com/power-management/overview.html",
      "verified_at": "2026-07-16",
      "active": true
    }
  ]
}
```

- `region`は`US`/`Europe`/`Japan`/`Asia`の4値（Excelのシート名に対応）。`country`はExcelの「国・地域」列そのまま（例: 台湾・中国・韓国・ドイツ・オランダ・ベルギー等）。
- `active`フラグは一時除外用。**再インポート時に`true`へ一律上書きされる**ため、恒久的な除外はExcel側の行削除で行い、再インポートする運用とする（11章の要検証事項にも記載）。
- 実行結果（`python3 ic_competitor_import.py`）: **67社**（US 18／Europe 14／Japan 12／Asia 23）を正しく取り込み、TI・Infineon・ROHM・Silergy・Richtek等をExcel原本と目視突合して一致を確認済み。

ステージ3（競合IC比較、8.4節）は、この`competitors_db.json`から対象製品の`category`で`primary`または`limited`の企業を抽出し、その中から地域バランスを考慮して比較対象を選ぶ設計とする。

---

## 7. `ic_competitor_import.py`（実装済み）

`openpyxl`でExcelの4地域シート（`US`/`Europe`/`Japan`/`Asia`）を読み込み、各行の●/△/—を`primary`/`limited`/`none`にマッピングして`competitors_db.json`を生成する。列位置（0始まり）は固定でハードコードしている（地域=0, 国=1, 企業名=2, ... 確認日=21）。越智さんがExcelを更新した場合の再取り込み手順:

```
pip install -r requirements.txt
python3 ic_competitor_import.py
```

実行すると地域別の取り込み件数がコンソールに表示される。CLI引数`--xlsx`/`--out`で入出力パスを変更可能（デフォルトは`config/source_data/`と`config/competitors_db.json`）。Excelの列順や列数が変わった場合はスクリプト内`CATEGORY_COLUMNS`等の定数を更新する必要がある（11章の要検証事項）。

---

## 8. 5ステージパイプライン詳細設計【実装済み、`ic_engine.py`/`ic_prompts.py`】

全ステージ共通で`ic_engine.py`の`IcPipeline._run_stage(key, label, fn, stages)`（`rtocs_organizer/strategy_engine.py`の`_run_stage`と同一パターン）でラップし、失敗時は`{"error": "取得失敗: {e}"}`を格納して次のステージへ進む。

### 8.1 ステージ0: 製品取り込み

- **入力**: `part_number`（必須）、`category_hint`（任意）
- **処理**: `generate_grounded_json`。プロンプト骨子: 「TI公式サイト（`site:ti.com {part_number}`）を検索し、型番の製品情報を調査してください。カテゴリは次のクローズドリストから最も近いものを1つ選んでください: dc_dc_pmic, ldo, led_driver, ac_dc, gate_driver, load_switch_efuse, ideal_diode_oring, gan_power, power_discrete_module, generic_analog_ic（フォールバック）。各仕様値には出典URLを明記してください。」5章の`category_schema.json`から該当カテゴリの`parameters`一覧を動的に埋め込み、`key_specs`をそのキーに沿って埋めさせる。
- **出力**: `part_number`, `manufacturer`, `category`(fact構造), `product_family`, `short_description`, `applications`(fact構造の配列), `datasheet_url`(fact構造), `application_notes`, `key_specs`(カテゴリのパラメータキーごとにfact構造), `grounding_note`
- **フォールバック**: 検索失敗時は`{"error": ...}`。カテゴリがクローズドリストに一致しない場合は`generic_analog_ic`に強制フォールバックし`category_confirmed_by_user=false`のまま次段へ進める。

### 8.2 ステージ1: 市場分析

- **入力**: ステージ0の`applications`
- **処理**: `generate_grounded_json`。プロンプト骨子: 「各アプリケーション用途について、第三者調査機関（Yole, TechInsights, Omdia, S&P Global, Fortune Business Insights等）が公表している市場規模・CAGRを検索してください。TI自身が発信している数値は`ti_stated_growth_driver`として別枠で保持し、第三者データと混同しないでください。」
- **出力**: `market_estimates`（`application`, `market_size`(fact構造), `cagr`(fact構造), `ti_stated_growth_driver`(fact構造), `growth_drivers`, `risks`の配列）, `overall_market_view`, `grounding_note`
- **フォールバック**: 個別アプリケーションで情報が見つからなければ当該要素を省略。全滅時は`{"error": ...}`。

### 8.3 ステージ2: キーカスタマー推定

- **入力**: ステージ0のカテゴリ・アプリケーション
- **処理**: `generate_grounded_json`。プロンプト骨子（非公開情報を扱わない旨を明記）: 「非公開の顧客情報・営業情報は一切扱わないでください。Google Patentsの引用関係、TechInsights/System Plus Consultingなどの公開テカルダウン記事、TI自身が公表した事例のみを根拠に、`{category}`カテゴリでTI製品を採用する可能性が高い企業を公開情報から推定してください。根拠のない企業名を創作しないでください。」
- **出力**: `estimated_key_customers`（`company`, `region`, `evidence_type`, `evidence_summary`, `evidence_source_url`, `confidence`の配列）, `customer_segments`, `disclaimer`（「本ステージは公開情報に基づく推定であり、TIとの契約関係を示すものではありません」等）
- **フォールバック**: 根拠が見つからない場合は`estimated_key_customers: []`＋`grounding_note`にその旨を明記。無理に企業名を生成させない。

### 8.4 ステージ3: 競合IC比較

- **入力**: ステージ0の`key_specs`とカテゴリ、`config/competitors_db.json`から該当カテゴリが`primary`/`limited`の企業
- **処理**: 会社ごとに`generate_grounded_json`を個別呼び出し（1社1コールで失敗を分離）。プロンプト骨子: 「{company}（{region}）の製品ラインアップから、TI製品`{part_number}`（主要仕様: {ti_key_specs_summary}）と最も比較可能な近似品番を1つ検索してください。以下のパラメータ一覧に沿って仕様を埋めてください: {category_schema.parameters}」。コスト・レイテンシの観点から「通常モード（地域ごとに`breadth_score`最上位1社、計4社）」と「フルモード（該当カテゴリの`primary`/`limited`全社）」の2モードを設ける。
- **出力**: `competitors`（`company`, `region`, `comparable_part`, `specs`(fact構造), `gap_vs_ti`, `source_url`, `lookup_status`の配列）, `comparison_table_note`
- **フォールバック**: 会社単位のエラーは配列内`lookup_status: "error"`として握りつぶし継続。全社失敗時のみステージ全体を`{"error": ...}`とする。

### 8.5 ステージ4: 次世代スペック提案

- **入力**: ステージ0〜3の全結果（成功分のみ抽出）
- **処理**: `generate_json`（JSONモード、grounding不要。既存事実の統合のため検索は不要と判断）。プロンプト骨子: 「これまでの市場分析・キーカスタマー推定・競合IC比較の結果を統合し、TI製品`{part_number}`をベースに次に開発すべきデバイスのKPI・追加機能を、根拠・実現性リスク・優先度付きで提案してください。」
- **出力**: `executive_summary`, `proposed_specs`（`kpi`, `current_ti_value`, `target_value`, `rationale`, `competitive_gap_addressed`, `feasibility_risk`, `priority`の配列）, `new_feature_proposals`, `closing_message`
- **フォールバック**: `{"error": ...}`。ここが失敗しても0〜3の結果は保存済みのためレポートは部分生成される。

---

## 9. ダッシュボード3タブ構成【実装済み、`analog_ic_se_strategy_organizer_20260716_01.py`】

### タブ1: 📦 製品登録・検索
- 型番入力欄＋カテゴリ手動指定セレクトボックス（5章の9カテゴリ、未指定なら自動判定）
- 「ステージ0のみ実行」ボタン（軽量登録、フル解析前の確認用）
- ステージ0失敗時は「カテゴリを手動選択して再実行」ボタンを表示
- 既存ケースライブラリの一覧テーブル: 型番／カテゴリ／メーカー／主要アプリケーション／解析日時／ステージ完了バッジ
- テキスト検索（型番/アプリケーション）＋カテゴリフィルタ

### タブ2: 📊 ポートフォリオ俯瞰
- 競合企業DBの概況（地域別社数の`plotly.express.pie`、カテゴリ別主要(●)/限定(△)企業数の積み上げ棒グラフ）— `competitors_db.json`から直接集計、分析済み製品が0件でも表示できる
- カテゴリ別製品登録数（`plotly.express.bar`）
- ステージ4提案の優先度別件数（`plotly.express.bar`）
- 競合ギャップが大きい製品ランキング（ステージ3`gap_vs_ti.advantages_of_competitor`の件数をスコア化したテーブル）
- 「AI俯瞰総評」ボタン（rtocsの`generate_trend_commentary`と同型、`ic_engine.generate_portfolio_commentary`＋`ic_prompts.PORTFOLIO_COMMENTARY`として実装、`portfolio_commentary.json`にキャッシュ）

初版では「カテゴリ別CAGR分布」（ステージ1`market_estimates`集計）は未実装（分析済み製品が蓄積してから追加する方が実用的なため見送った）。次バージョンでの追加候補。

### タブ3: 🎯 製品ディープダイブ
- 型番入力＋分析モード（通常/フル競合探索）
- `st.status`で5ステージ進捗表示（rtocsの`progress_cb`パターンを踏襲）
- 実行後: エグゼクティブサマリー・提案KPIトップ3をインライン表示、HTMLレポートを開く/ダウンロードボタン

---

## 10. 実装状況と後続セッションでやること

上記1〜7のステップ（`ic_schema.py`→`ic_index.py`→`ic_engine.py`→`ic_prompts.py`→`IcPipeline`本体→`ic_report.py`→Streamlitダッシュボード3タブ）は2026-07-16のセッションで実装済み。パイプラインの制御ロジック（ステージ間のデータ受け渡し、失敗時のフォールバック、HTMLレポート生成）は`GeminiClient`をモックした単体テストで検証し、ダッシュボードはPlaywrightで実画面（3タブ）を確認した。

**後続セッションでやること（実機検証、8章のステップ8に相当）:**
1. `GEMINI_API_KEY`を設定した環境（この開発環境は`google-generativeai`の依存関係`cryptography`が壊れておりAPI呼び出し確認ができなかった）で`pip install -r requirements.txt`
2. 実際のTI型番数件（例: 越智さんが日常的に扱う型番）で🎯製品ディープダイブタブを実行
3. grounded searchで拾えた`key_specs`の数値をTIデータシートと手動突き合わせ、精度を確認（11章 要検証事項1）
4. 精度・コスト・レイテンシに応じて、ステージ3の呼び出し粒度（通常/フルモード）やプロンプトを調整
5. 検証結果を`CHANGELOG.md`に追記

---

## 11. 未解決・要検証事項

1. **grounding精度の未検証**: TI直接アクセスが403だったためgrounded search方式に統一する方針は確定したが、Gemini検索グラウンディング経由でデータシートの数値項目（効率・Iq等）をどこまで正確に拾えるかは未検証。ハルシネーションリスクが高いため、実装直後に数件を手動データシートと突き合わせる検証ステップ（10章ステップ8）を必須工程として組み込んだ。精度が低い場合、`key_specs`の一部項目を「取得しない/confidence=lowで必ず警告表示」に倒す再設計が必要になる可能性がある。
2. **`ic_competitor_import.py`の列位置ハードコード**: Excelの列順・列数が将来変わった場合、スクリプト内`CATEGORY_COLUMNS`等の定数を手動で追随させる必要がある。列名ヘッダーを動的に読んでマッピングする方式への変更は次回改修候補。
3. **`active`フラグと再インポートの競合**: `competitors_db.json`の`active`フラグは越智さんが個別に`false`へ変更しても、次回`ic_competitor_import.py`実行時に`true`へ一律上書きされる。恒久的な除外はExcel側の行削除で管理する運用を6章・README.mdに明記したが、実運用で使いにくければ「インポート時に既存の`active=false`を保持する」仕様に変更する必要がある。
4. **`generic_analog_ic`フォールバックカテゴリ**: `category_schema.json`はExcel実データに準拠させる方針を優先し、汎用カテゴリはJSONファイルには追加せず`ic_schema.py`内のコード定数（`GENERIC_CATEGORY`）として実装した（`resolve_category()`が9カテゴリ非該当時に自動フォールバック）。この判断が適切か（設定ファイル化した方が越智さんにとって編集しやすいか）は運用してみて再検討の余地がある。
5. **ステージ3の呼び出し粒度とコスト**: 1社1コール設計だが、実測してみないとコスト・レイテンシが許容範囲か分からない。通常モード（地域代表1社）とフルモードの2段階を用意したが、実データで調整が必要。
6. **価格情報(`price_1ku_usd`)の取得精度**: TI価格ページや流通サイトの情報鮮度・正確性はgrounded searchでは低くなりがちなため、必須フィールドにせずoptional・confidence低めを許容する設計にした。
7. **`data/`配下の取り扱い**: `rtocs_organizer/data`は現状リポジトリに未コミット（実行時生成）。`analog_ic_se_strategy_organizer/data`（特に`product_lake`）も同じ運用（git管理外）で良いか、越智さんに確認したい。
8. **競合他社データの転載・利用範囲**: ステージ3で競合各社のデータシート由来スペックを比較表として社内共有する場合の著作権・利用規約上の扱いは未検討。レポート内に免責を入れる想定だが、法務観点の最終確認は越智さん側で行ってほしい。
9. **`schema_version`のマイグレーション方針**: `category_schema.json`を将来改訂した際、既存`product_lake`内の古いJSON（旧スキーマの`key_specs`）をどう扱うか（再解析必須か、旧データのまま許容するか）は未確定。
10. **実際のGemini API呼び出しが未検証**: 開発環境に`GEMINI_API_KEY`が無く、`google-generativeai`パッケージの依存関係（`cryptography`のRustバインディング）も壊れていたため、実機でのAPI呼び出し確認ができなかった。越智さんの環境での実機検証が必須（10章参照）。
11. **ポートフォリオ俯瞰タブのCAGR分布グラフ未実装**: 9章に記載の通り、初版では見送った。分析済み製品が蓄積してから実装するのが実用的。

---

## 12. 再利用すべき既存資産一覧（`rtocs_organizer/`）

| ファイル | 流用できる部分 |
|---|---|
| `rtocs_organizer/rtocs_index.py` | ケースライブラリの増分構築ロジック（mtimeベースの差分検出、`compact_index_for_llm`形式）。`ic_index.py`の実装元 |
| `rtocs_organizer/strategy_engine.py` | パイプラインの失敗耐性設計（`_run_stage`による`{"error":...}`格納＋続行）、コスト集計、**LLM検索グラウンディングの実装**（`google-genai`の`Client`＋`types.Tool(google_search=types.GoogleSearch())`。レガシーの`google-generativeai`は`google_search_retrieval`しか公開しておらずGemini 2.x系では400エラーになるという教訓を含む）。`ic_engine.py`の実装元 |
| `rtocs_organizer/strategy_prompts.py` | プロンプト設計パターン（システムプレフィックス、JSON出力スキーマの書き方、検索グラウンディング用プロンプトの書き方）。`ic_prompts.py`の実装元 |
| `rtocs_organizer/strategy_report.py` | HTMLレポートのカード型CSS、失敗/スキップ時のフォールバック表示。`ic_report.py`の実装元 |
| `rtocs_organizer/rtocs_dashboard_20260715_04.py` | Streamlit 3タブ構成の実装パターン（`st.status`によるステージ進捗表示、`st.cache_data`によるインデックスキャッシュ） |
| `rtocs_organizer/CHANGELOG.md`, `README.md` | バージョン管理ルール（`ツール名_yyyymmdd_連番.py`、旧版を残したまま新版追加、ツールフォルダごとにCHANGELOG.md）の実例 |

---

## 13. 運用ルール・コミュニケーション上の注意

ルート `README.md` の「開発ルール（バージョン管理）」節を参照。要点:
- バージョンアップ時のファイル名は `ツール名_yyyymmdd_連番.py`
- 旧バージョンは削除・上書きせず新版と併存させる
- 各ツールフォルダに `CHANGELOG.md` を置く

コミュニケーション上の注意（`HANDOVER_analog_ic_scout.md`から継続）:
- 呼称は「越智さん」
- 回答は日本語・結論先出し
- 越智さんはプログラム初心者を自認しつつ、専門領域（半導体）については高度な要求を出してくる。技術的な実現可能性（スクレイピングの法的リスク、API有無、データの信頼性）を率直に指摘し、楽観的な機能一覧の提示だけで終わらせないこと
- パイプライン本体・ダッシュボードは実装済みだが、実際のGemini API呼び出しでの動作確認はまだ完了していない。「動いている」と報告する前に、越智さんの環境での実機検証結果を確認すること

---

## 14. 視点の是正とMECE改善ロードマップ（2026-07-17〜）

### 14.1 根本的な視点の転換

実機検証中、越智さんから重要な訂正があった: **本ツールは「TIのシニアシステムエンジニアがTIの将来を考える」ものではなく、「Nexperiaのシニアシステムエンジニアが、TIをベンチマーク対象として打ち負かす対抗デバイスを企画し、将来ロードマップを描く」ためのもの**である。

これは1ステージの修正では済まない転換点であり、旧来の設計は暗黙に「TIが主語」（ステージ4「TIの次世代スペック提案」、レポートタイトル「TI製品 競合分析レポート」等）になっていた。正しくは「自社(Nexperia)・ベンチマーク対象(TI)・その他参考競合」の3層構造であるべきで、`competitors_db.json`上でNexperiaが他66社と並列の1社として扱われている点、競合IC比較の「地域代表1社」選定ロジックがNexperiaを選ぶ保証をしていない点（＝自社が自分自身との比較から漏れる欠陥）などが顕在化した。

### 14.2 MECE改善項目一覧

越智さんの依頼により、以下をMECEに洗い出した（A〜Eの5カテゴリ、全19項目）。詳細な項目説明は本セッションの会話ログを参照。要点のみ再掲する。

- **A. 視点設計そのものの欠陥**（4項目）: 自社概念の不在、地域代表選定でNexperiaが漏れる欠陥、ステージ4の主語がTIのまま、レポート文言がTI中心
- **B. データ層**（3項目）: `own_company.json`の不在、自社データの非権威化（LLM推測と同列）、自社現行品との比較が無い
- **C. 既存5ステージの再設計**（5項目）: ステージ0のアプリノート深掘り不足、ステージ1に動的シグナル（競合新製品動向）が無い、ステージ2の着地点不明確、ステージ3の自社必須組み込み、ステージ4の主語転換
- **D. 欠落している新規ステージ候補**（5項目）: 技術トレンド・特許シグナル分析、**ホワイトスペース分析**、TAM/SAM/SOM分析、ロードマップ視点（単発分析→時系列企画）、競争力スコアリング・投資判断材料
- **E. 運用・データガバナンス**（2項目）: TIモニタリングの継続性、競合データの鮮度管理

### 14.3 優先順位と実装状況

越智さんの合意により、コスト対効果の高い順に以下の順で着手する。

| # | 項目 | 状況 |
|---|---|---|
| 1 | **D: ホワイトスペース分析**（既存データのみ、LLM呼び出し不要） | ✅ 実装済み（v20260717_02） |
| 2 | **A: 自社を競合比較に必ず含める＋C: ステージ4の主語転換＋レポート文言修正** | ✅ 実装済み（v20260718_01。当初計画にレポートUIの1テーブル統合が追加された。B:自社データの権威化は次項参照） |
| 3 | **D: ロードマップビュー** | ✅ 実装済み（v20260718_02。「TIの推定リフレッシュ周期」等の競合開発動向シグナルは対象外、次項参照） |

### 14.4 優先度1（ホワイトスペース分析）の実装内容

- `config/own_company.json` を新設: `{"name": "Nexperia", "benchmark_target": "Texas Instruments", ...}`。自社・ベンチマーク対象を明示する設定ファイルで、以降のステップ（優先度2）でも再利用する土台
- `ic_schema.py` に追加:
  - `load_own_company()` / `own_company_name()`: 自社設定の読み込み
  - `find_company(name)`: `competitors_db.json`から企業名で1社検索
  - `whitespace_analysis()`: カテゴリ別の「手薄度」（`whitespace_score = 1 - coverage_score`, `coverage_score = (primary数 + limited数×0.5) / 総社数`）、車載クロスの手薄度（そのカテゴリのprimary/limited企業のうち車載対応primary企業が占める割合の低さ）、地域別の手薄さ（最も手薄な地域）、自社(Nexperia)の当該カテゴリでの現状ポジションを算出する。LLM呼び出しは一切行わず、`competitors_db.json`の集計のみで完結する（コスト0）
- ダッシュボード（`analog_ic_se_strategy_organizer_20260717_02.py`）の📊ポートフォリオ俯瞰タブに「🕳️ ホワイトスペース分析」セクションを新設: 手薄度の棒グラフ・テーブルに加え、上位5カテゴリについて自社の現状ポジションと組み合わせた優先度ラベル（★新規参入候補／▲拡張候補／◎独走候補）を自動生成
- 検証: `whitespace_analysis()`の算出結果を`find_company("Nexperia")`の実データと突合し一致を確認（例: アイデアルダイオード/ORingが手薄度最大0.769、Nexperiaは同カテゴリで既にprimary→「◎独走候補」）。Streamlit起動＋Playwrightで画面表示を確認

### 14.5 優先度2（自社必須組み込み＋ステージ4主語転換＋統合比較表）の実装内容

当初計画（`config/own_products.json`のような自社データの権威化）を説明したところ、越智さんから
「各デバイスがバラバラにリストアップされていて見づらい。1テーブルで、どのような製品を企画すれば
TI含む他のコンペを打ち負かせるか、自社提案が一目でわかる構造にしてほしい」という具体的な要望があり、
スコープをレポートUIの根本的な再構成に広げて対応した。

- **自社を競合比較に必ず含める**（`ic_engine.py`ステージ3）: 選定企業リスト（通常モード=地域代表／
  フルモード=該当カテゴリ全社）に`own_company_name()`が含まれていなければ強制的に追加する。
  自社がそのカテゴリで`competitors_db.json`上「none」の場合は、ハルシネーション防止のため
  検索させず`"no_current_product": true`を明示するのみに留める（前セッションでの質疑を踏まえた挙動）
- **ベンチマーク対象(TI)の重複比較を防止**（`ic_schema.py`）: 実装中の単体テストで、TI自身が
  `competitors_db.json`の67社に含まれているため「競合」として選ばれ「TI vs TI」の比較行が
  できてしまう不具合を発見。`load_competitors()`/`pick_regional_representatives()`に
  `exclude_names`引数を追加し、ベンチマーク対象を候補プールから除外するよう修正
- **ステージ4の主語転換**（`ic_prompts.STAGE4_NEXT_GEN`）: 「TIが次に開発すべき」から
  「自社(Nexperia)がTI・全競合を上回るために開発すべき」に書き換え。`target_value`は
  「TIに勝てば十分」ではなく「ステージ3に登場した全企業の最良値を上回る」ことを狙うよう明記。
  各提案の`kpi`（自由記述）を`parameter_key`（category_schemaの実キー）＋`kpi_label`（表示用）に
  変更し、比較表の行と機械的に突合できるようにした
- **HTMLレポートを1つの統合比較表に再構成**（`ic_report.py`）: 旧来の「企業ごとに独立したカード」
  （`_sec_competitors`）と「次世代スペック提案カード」（`_sec_next_gen`）を1つの
  `_sec_comparison_table`に統合。**パラメータ行×企業列**（TI／各競合企業／自社(現行)／
  🏆自社提案(次世代・金色ハイライト)）というマトリクス構造にし、1行を横に読むだけで
  「TIと各社の現状」と「自社が次に狙うべき値」が一目でわかるようにした。検索失敗企業は列から
  除外し脚注にまとめ、各社の強み・弱みの定性コメントは`<details>`で折りたたみ表示に格下げした
- **動作検証**: モックのGeminiClientで「自社に現行品あり(primary)」「自社に現行品なし(none→未参入)」
  の2ケースを再現し、統合比較表・自社提案列の強調表示・横スクロールでの提案列到達をPlaywrightで
  画面確認。ダッシュボード3タブもエラー無く表示されることを確認

**B: 自社データの権威化は今回のスコープに含めず据え置き**。現状Nexperia自身の「現行製品」specも
他社と同じくLLM検索グラウンディング経由（`c.get("categories")`が`primary`/`limited`の場合のみ検索）
であり、越智さんが直接メンテナンスする権威データではない。将来的に`config/own_products.json`を
新設し`fact構造`の`source_type: "user_input"`で扱う拡張の余地は残る（優先度4以降の候補）。

### 14.6 優先度3（ロードマップビュー）の実装内容

当初の構想（「TIの推定リフレッシュ周期 vs 自社の対抗タイミング」を可視化する時系列企画ビュー）は、
TIの製品ロードマップという外部シグナルを扱う新しいデータソース（特許出願・学会発表等）が必要で
設計コストが大きい。まずは**自社データのみで作れる「次に着手すべきカテゴリ」の優先順位付け**に
スコープを絞って実装し、外部シグナルを要する部分は明示的に将来課題として切り出した。

- **`ic_index.roadmap_priorities()`を追加**: 優先度1の`ic_schema.whitespace_analysis()`（市場全体の
  手薄さ）に、自社の現状ポジション（`ROADMAP_STATUS_WEIGHT = {"none": 1.0, "limited": 0.7, "primary": 0.4}`
  で重み付け。未参入のカテゴリほど「新規に企画すべき」優先度を上げる）と、`product_lake`の分析済み
  製品を集計した直近性（`last_analyzed_at`、`analyzed_count`）を組み合わせ、
  `roadmap_score = whitespace_score × status_weight`でカテゴリをランキングする。LLM呼び出し不要（コスト0）
- 📊ポートフォリオ俯瞰タブに「🗺️ ロードマップビュー」セクションを新設:
  - 「次に着手すべきカテゴリ」テーブル（分析済み製品が0件でも表示可能。全カテゴリ「未分析」から
    始まる状態でも、どこから手をつけるべきかが分かる）
  - 分析済み製品が蓄積されている場合は、カテゴリ別の解析日時×最優先提案（優先度で色分け）の
    時系列散布図を追加表示
- **検証**: 単体テストで、自社が「none」のカテゴリ（AC-DC/LDO）が、生の手薄度はより高い
  「アイデアルダイオード/ORing」（自社は既にprimary）よりロードマップ優先度で上位に来ることを確認
  （自社の現在地を加味した優先順位付けが機能している）。分析済み製品なし／あり両方の状態で
  Streamlit+Playwrightにより画面表示を確認

### 14.7 今後の拡張候補（優先度4以降）

- **B: 自社データの権威化**（14.5節で据え置き）: `config/own_products.json`を新設し、越智さんが
  直接メンテナンスするNexperia自社製品の正確なスペックを`fact構造`の`source_type: "user_input"`で扱う
- **D: 技術トレンド・特許シグナル分析**（新規ステージ）: 競合の特許出願・学会発表（APEC/ISSCC/PCIM等）・
  プレスリリースから「TIの推定リフレッシュ周期」のような競合の開発動向を検出する。これが実装できれば
  14.6のロードマップビューに「TIが次にいつ動きそうか」の軸を追加できる
- **D: TAM/SAM/SOM分析**: ステージ1(市場分析)を市場規模・CAGRの取得に留めず、自社が実際に獲得可能な
  範囲（SOM）まで踏み込む
- **D: 競争力スコアリング・投資判断材料**: 実現性リスクを自由記述1行から、保有プロセス・パッケージ
  技術の適合性、特許FTOリスク、必要投資額感等の定量・準定量情報に拡張する
- **E: 運用・データガバナンス**: TIモニタリングの継続性（rtocs_organizerのニュース収集ステージに相当する
  仕組みが無い）、競合企業データ（`competitors_db.json`）の鮮度管理ルールの明文化

---

## 15. Gemini API呼び出しの共通化（2026-08-11）

会社PC上でGemini APIへの直接アクセスが遮断される事象が発生したため（原因未確定）、`ic_engine.py`の
`GeminiClient`は`google-generativeai`/`google-genai` SDKの直接呼び出しから、共通クライアント
`../common/gemini_client.py`（submodule `ochi1216/gemini-common-tools`）の`generate_advanced(payload, model=...)`
経由に置き換えた。直接アクセス失敗時は自宅PC経由プロキシへ自動フォールバックする。

- JSONモード・Google Search Groundingのペイロード組み立て・レスポンス解析ロジック（コードフェンス除去＋
  `json.loads`）は変更していない。SDKオブジェクトの代わりに生JSON dictを扱うよう、コスト集計
  （`usageMetadata.promptTokenCount`等、REST APIのcamelCase）とテキスト抽出のみ調整した
- 「通常モード(flash)／ディープモード(pro)」の切替は、`generate_advanced`に`model=self.model_name`を
  明示的に渡すことで維持している。当初`generate_advanced`にモデル指定機能が無く、ディープモードを
  選んでも常にflashが呼ばれるサイレントバグになる問題を実装前に発見・指摘し、共通クライアント側に
  `model`引数を追加してもらってから移行した（同時期に`rtocs_organizer/strategy_engine.py`も同じ方式で移行）
- 詳細な経緯・インターフェース仕様は`common/GEMINI_MIGRATION_HANDOVER.md`を参照
- **未検証**: この開発環境には`GEMINI_API_KEY`/`GEMINI_PROXY_URL`が無いため、実際のGemini API呼び出し
  （直接・プロキシ経由とも）は未検証。モックでのペイロード組み立て・model伝播・コスト計算確認に留まる
